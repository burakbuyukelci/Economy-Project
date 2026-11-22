"""Colab değerlendirme koşu planı: GPU tipine göre oturum başına süre tahmini + toplamı bütçenin (varsayılan ~170 dk) altında tutan bölünmüş koşu önerisi.

    python -m experiments.colab.plan --gpu L4 --questions data/training/v2/test.jsonl --n 40 --models 2 --profiles A B C D E
    python -m experiments.colab.plan --gpu T4 --n 40 --calibrate /content/drive/MyDrive/bist_eval/v2/results.jsonl     # ölçülen sürelerle yeniden tahmin

TAHMİN MODELİ (açık varsayım; ölçümle DEĞİŞTİRİLİR):
  süre/koşu = prompt_tokenı / pp_hızı + üretilen_token / tg_hızı + tur_sayısı x TUR_YÜKÜ + (araçlı profilde) ARAÇ_YÜKÜ
  * Token yükü, v2 değerlendirme sorularının öğretmen oturum kayıtlarından (`text_messages`) türetilir (karakter/2,7 ile token): tur sayısı = asistan mesajı sayısı, üretim = asistan
    mesajlarının tokenı, prompt = her tokenın BİR kez işlendiği varsayımıyla (Ollama GPU önek önbelleği) ya da `--no-prefix-cache` ile her turda tüm geçmiş (CPU'daki gözlem).
  * Profil A araçsızdır: tek tur (sistem+soru ~600 token, nihai metin kadar üretim). B–E: oturum kaydının yükü (B/C kapı ve politika turları olmadan daha hafiftir: üst sınır).
  * Model oturumları öğretmen betiğinden uzundur (yeniden deneme, geçersiz çağrı): tahmini süreler x1,5 GÜVENLİK PAYI ile verilir (ölçülen süreler paysız).
  * Hızlar (pp = prompt işleme tok/sn, tg = üretim tok/sn) gemma3:4b Q4_K_M için VARSAYIMDIR (bu geliştirme makinesinde GPU yok; ölçülmedi): T4 1000/30, L4 1500/40, A100 4000/100.
    CPU satırı ÖLÇÜMDÜR (2026-11-21, Bilgisayar 1: prompt ~27 tok/sn, profil A tek soru ~114 sn => tg ~4 tok/sn): değerlendirmenin CPU'da yapılamayacağını gösterir.
  * `--calibrate results.jsonl`: ilk koşulardan ölçülen ortalama sn/koşu (profil bazında, >= 3 satır) varsayımın YERİNE geçer.
Çıktı: model x profil başına sn/koşu, toplam süre, ve her oturumu bütçeye sığdıran `--max-runs` bölünmesi (aynı komut tekrar çalıştırılınca eval_runner kaldığı yerden devam eder).
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

CHARS_PER_TOKEN = 2.7
SPEEDS: dict[str, dict[str, float]] = {
    "T4": {"pp": 1000.0, "tg": 30.0},
    "L4": {"pp": 1500.0, "tg": 40.0},
    "A100": {"pp": 4000.0, "tg": 100.0},
    "CPU": {"pp": 27.0, "tg": 4.0},       # ÖLÇÜM (Bilgisayar 1)
}
A_PROMPT_TOKENS = 600           # profil A: sistem istemi + soru (araç tanımı yok)
TURN_OVERHEAD_S = 0.4           # tur başına HTTP/şablon yükü
TOOL_OVERHEAD_S = 2.0           # araçlı profil: gerçek araç çalıştırma + doğrulama (üretim hattında ~1 sn/oturum ölçüldü; ağır araçlar için pay)
MODEL_LOAD_S = 90.0             # model başına ilk yükleme (Ollama)
CONTINGENCY = 1.5               # gerçek model, öğretmen betiğinden fazla tur/yeniden deneme (FINAL_MAX_RETRIES=2, geçersiz çağrılar) ve daha uzun üretim yapar: VARSAYIM
PROFILES = ("A", "B", "C", "D", "E")


def _tok(m: dict[str, str]) -> float:
    return len(m["content"]) / CHARS_PER_TOKEN + 6


def session_load(record: dict[str, Any], *, prefix_cache: bool = True) -> dict[str, float]:
    """Bir oturum kaydının model yükü: tur sayısı, üretim tokenı, prompt tokenı (önbellekli: her token bir kez; önbelleksiz: her turda tüm geçmiş)."""
    msgs = record["text_messages"]
    asst = [i for i, m in enumerate(msgs) if m["role"] == "assistant"]
    gen = sum(_tok(msgs[i]) for i in asst)
    if prefix_cache:
        prompt = sum(_tok(m) for m in msgs[: asst[-1]])
    else:
        prompt = sum(sum(_tok(m) for m in msgs[:i]) for i in asst)
    return {"turns": float(len(asst)), "gen": gen, "prompt": prompt, "final_gen": _tok(msgs[asst[-1]])}


def run_seconds(load: dict[str, float], profile: str, speeds: dict[str, float]) -> float:
    if profile == "A":
        return A_PROMPT_TOKENS / speeds["pp"] + load["final_gen"] / speeds["tg"] + TURN_OVERHEAD_S
    return load["prompt"] / speeds["pp"] + load["gen"] / speeds["tg"] + load["turns"] * TURN_OVERHEAD_S + TOOL_OVERHEAD_S


def select_records(path: str | Path, n: int) -> list[dict[str, Any]]:
    from experiments.eval_runner import select_subset
    recs = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return select_subset(recs, n)


def calibrated(path: str | Path | None, min_rows: int = 3) -> dict[str, float]:
    """results.jsonl'dan profil başına ölçülen ortalama sn/koşu (>= min_rows satır olan profiller)."""
    if not path or not Path(path).exists():
        return {}
    by: dict[str, list[float]] = defaultdict(list)
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("seconds") is not None and r.get("profile"):
            by[r["profile"]].append(float(r["seconds"]))
    return {p: sum(v) / len(v) for p, v in by.items() if len(v) >= min_rows}


def estimate(records: Sequence[dict[str, Any]], profiles: Sequence[str], n_models: int, gpu: str, *, prefix_cache: bool = True,
             measured: dict[str, float] | None = None) -> dict[str, Any]:
    speeds = SPEEDS[gpu]
    per_profile: dict[str, float] = {}
    for p in profiles:
        if measured and p in measured:
            per_profile[p] = measured[p]
        else:
            per_profile[p] = CONTINGENCY * sum(run_seconds(session_load(r, prefix_cache=prefix_cache), p, speeds) for r in records) / len(records)
    runs_per_model = len(records) * len(profiles)
    total = n_models * (MODEL_LOAD_S + sum(per_profile[p] * len(records) for p in profiles))
    return {"gpu": gpu, "n_questions": len(records), "n_models": n_models, "profiles": list(profiles), "seconds_per_run": {p: round(v, 1) for p, v in per_profile.items()},
            "runs_total": runs_per_model * n_models, "total_minutes": round(total / 60, 1), "calibrated_profiles": sorted(measured or {})}


def split_plan(est: dict[str, Any], budget_min: float = 170.0) -> dict[str, Any]:
    """Toplamı `budget_min`'i aşmayan oturumlara böler. Koşucu sırası model -> profil -> soru olduğundan koşu sayısına göre bölünür (`--max-runs`).
    Oturum sayısı = ceil(toplam / bütçe); her oturum için --max-runs = ceil(toplam koşu / oturum)."""
    sessions = max(1, math.ceil(est["total_minutes"] / budget_min))
    max_runs = math.ceil(est["runs_total"] / sessions)
    return {"budget_min": budget_min, "sessions": sessions, "max_runs_per_session": max_runs,
            "minutes_per_session": round(est["total_minutes"] / sessions, 1)}


def recommend_n(records_all: Sequence[dict[str, Any]], profiles: Sequence[str], n_models: int, gpu: str, budget_min: float, *, max_sessions: int,
                prefix_cache: bool = True, measured: dict[str, float] | None = None) -> int:
    """`max_sessions` oturumda (her biri <= budget_min) bitecek EN BÜYÜK soru sayısı (<= tüm sorular)."""
    from experiments.eval_runner import select_subset
    best = 0
    for n in range(5, len(records_all) + 1, 5):
        est = estimate(select_subset(records_all, n), profiles, n_models, gpu, prefix_cache=prefix_cache, measured=measured)
        if est["total_minutes"] <= budget_min * max_sessions:
            best = n
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Colab değerlendirme koşu planı")
    ap.add_argument("--gpu", choices=sorted(SPEEDS), default="T4")
    ap.add_argument("--questions", default="data/training/v2/test.jsonl")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--models", type=int, default=2, help="model sayısı (temel + ince ayarlı = 2)")
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES), choices=list(PROFILES))
    ap.add_argument("--budget-min", type=float, default=170.0, help="oturum başına hedef süre (dk)")
    ap.add_argument("--max-total-min", type=float, default=180.0, help="TOPLAM koşu süresi hedefi (dk); aşılırsa küçültülmüş --n önerilir")
    ap.add_argument("--no-prefix-cache", action="store_true", help="CPU gözlemi: her turda tüm geçmiş yeniden işlenir")
    ap.add_argument("--calibrate", default=None, help="önceki koşunun results.jsonl'ı: ölçülen sn/koşu varsayımın yerine geçer")
    args = ap.parse_args(argv)
    recs_all = [json.loads(line) for line in Path(args.questions).read_text(encoding="utf-8").splitlines() if line.strip()]
    recs = select_records(args.questions, args.n)
    meas = calibrated(args.calibrate)
    est = estimate(recs, args.profiles, args.models, args.gpu, prefix_cache=not args.no_prefix_cache, measured=meas)
    sp = split_plan(est, args.budget_min)
    print(json.dumps({"estimate": est, "split": sp}, ensure_ascii=False, indent=2))
    print(f"\n{args.gpu}: {est['runs_total']} koşu, tahmini toplam {est['total_minutes']} dk -> {sp['sessions']} oturum x ~{sp['minutes_per_session']} dk "
          f"(oturum başına `--max-runs {sp['max_runs_per_session']}`; aynı komutu tekrar çalıştırmak kaldığı yerden devam eder)")
    n_total = recommend_n(recs_all, args.profiles, args.models, args.gpu, args.max_total_min, max_sessions=1, prefix_cache=not args.no_prefix_cache, measured=meas)
    print(f"toplam <= {args.max_total_min:.0f} dk için en büyük soru sayısı: --n {n_total}" if n_total else f"toplam <= {args.max_total_min:.0f} dk için 5 soru bile sığmıyor")
    if est["total_minutes"] > args.budget_min * 2:
        n2 = recommend_n(recs_all, args.profiles, args.models, args.gpu, args.budget_min, max_sessions=2, prefix_cache=not args.no_prefix_cache, measured=meas)
        print(f"UYARI: iki oturuma sığmıyor; iki oturumda biten en büyük soru sayısı: --n {n2}" if n2 else "UYARI: bu GPU'da iki oturuma sığan soru sayısı yok (daha hızlı GPU ya da daha az profil/model)")
    print("NOT: hızlar varsayımdır (CPU hariç); ilk ~6 koşudan sonra `--calibrate` ile yeniden tahmin edin." if not meas else f"ölçülen süreler kullanıldı: {sorted(meas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
