"""Değerlendirme sonuçlarından (summary.json, results.csv) rapor tablolarını üretir: sayılar elle kopyalanmaz, dosyadan gelir.

    python -m experiments.eval_tables reports/eval_v2_3 --repro reports/eval_v2_3/summary_repro.json
    python -m experiments.eval_tables reports/eval_v2_3 --compare reports/eval_v2_2

Çıktı Markdown'dır (rapor bölüm 9). Yalnızca yerel dosya okur; ağ yok.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PROFILES = ("A", "B", "C", "D", "E")


def _fmt(v: Any, pct: bool = False, nd: int = 3) -> str:
    if v is None:
        return "–"
    if pct:
        return f"%{v * 100:.1f}"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def load_summary(path: Path) -> dict[str, dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["summary"]


def table_9_1(summary: dict[str, dict[str, Any]], repro: dict[str, dict[str, Any]] | None = None) -> str:
    """Hocanın metrikleri: model x profil. Tekrarlanabilirlik yalnızca `repro` (ayrı --repeats 2 koşusu) verilmişse ve yalnızca onun profilinde dolar."""
    head = ("| Model | Profil | Teslim / koşu | Sayısal halüsinasyon | Hatalı araç çağrısı* | Kanıtsız sayı | Kural ihlali (teslim) | Kural ihlali (deneme) "
            "| Tavsiye dili | Zorunlu adım atlama | Geri çekilme | Etiket = politika | Etiket = beklenen | Tekrarlanabilirlik | Maks. prompt token | Ort. süre (sn) |")
    rows = [head, "|" + "---|" * 16]
    for key in sorted(summary, key=lambda k: (k.split("|")[0] != "gemma3:4b", PROFILES.index(k.split("|")[1]))):
        model, prof = key.split("|")
        s = summary[key]
        rep = (repro or {}).get(key, {}).get("reproducibility_rate")
        rows.append(
            f"| {model} | {prof} | {s['n_delivered']}/{s['n_runs']} | {_fmt(s['numerical_hallucination_rate'], True)} "
            f"| {_fmt(s['invalid_tool_call_rate'], True) if prof != 'A' else '–'} | {_fmt(s['unevidenced_rate'], True) if prof in ('D', 'E') else '–'} "
            f"| {_fmt(s['rule_violation_rate_delivered'], True)} | {_fmt(s['rule_violation_rate_attempts'], True)} | {_fmt(s['advice_language_rate'], True)} "
            f"| {_fmt(s['mandatory_step_skipped_rate'], True) if prof in ('C', 'D', 'E') else '–'} | {_fmt(s['fallback_rate'], True) if prof in ('D', 'E') else '–'} "
            f"| {_fmt(s['action_matches_policy_rate'], True)} | {_fmt(s['action_matches_expected_rate'], True)} | {_fmt(rep, True)} "
            f"| {s['max_prompt_tokens']} | {_fmt(s['mean_seconds'], nd=1)} |")
    rows.append("")
    rows.append("\\* Hatalı araç çağrısı oranı, reddedilen metin turlarını da içerir; bu yüzden şişkindir (bkz. `limitations.md`).")
    return "\n".join(rows)


def type_breakdown(results_csv: Path, model: str, profile: str) -> dict[str, tuple[int, int]]:
    """Soru tipine göre (teslim edilen, toplam)."""
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    with results_csv.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["model"] == model and r["profile"] == profile:
                out[r["type"]][1] += 1
                out[r["type"]][0] += r["status"] == "DELIVERED"
    return {t: (a, b) for t, (a, b) in sorted(out.items())}


def table_types(columns: dict[str, dict[str, tuple[int, int]]]) -> str:
    """Birden çok koşu için tip kırılımı: {sütun adı: type_breakdown}."""
    types = sorted({t for c in columns.values() for t in c})
    rows = ["| Soru tipi | " + " | ".join(columns) + " |", "|---|" + "---|" * len(columns)]
    for t in types:
        rows.append(f"| {t} | " + " | ".join(f"{c[t][0]}/{c[t][1]}" if t in c else "–" for c in columns.values()) + " |")
    tot = [f"{sum(a for a, _ in c.values())}/{sum(b for _, b in c.values())}" for c in columns.values()]
    rows.append("| **Toplam** | " + " | ".join(f"**{x}**" for x in tot) + " |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="değerlendirme klasörü (summary.json, results.csv)")
    ap.add_argument("--repro", default=None, help="tekrarlanabilirlik koşusunun summary.json'u")
    ap.add_argument("--compare", default=None, help="karşılaştırılacak ikinci değerlendirme klasörü (tip kırılımı için)")
    ap.add_argument("--model", default="gemma3-bist")
    ap.add_argument("--profile", default="D")
    args = ap.parse_args(argv)
    d = Path(args.dir)
    repro = load_summary(Path(args.repro)) if args.repro else None
    print(table_9_1(load_summary(d / "summary.json"), repro))
    cols = {d.name: type_breakdown(d / "results.csv", args.model, args.profile)}
    if args.compare:
        c = Path(args.compare)
        cols = {c.name: type_breakdown(c / "results.csv", args.model, args.profile), **cols}
    print()
    print(f"Soru tipine göre teslim ({args.model}, profil {args.profile}):")
    print(table_types(cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
