"""A–E deney koşucusu: aynı sorular, profil (A–E) x model (temel / ince ayarlı), tüm metrikler CSV + JSON.

Hoca: "model sabit, mimari değişsin" (hoca_qa.md Soru 5). Bu koşucu bir modelin profiller arası farkını (ve temel/ince ayarlı karşılaştırmasını) ölçer; her koşu GERÇEK araçlar,
GERÇEK oturum ve harness'in `final_metrics()` çıktısıyla sayılır. Ollama yalnızca yerel (127.0.0.1). Minimum bağımlılık: pydantic, pandas, numpy, pyarrow + `data/snapshots/`.

    python -m experiments.eval_runner --questions data/training/v1/test.jsonl --n 40 --models gemma3:4b gemma3-bist --out reports/eval_v1

DAYANIKLILIK (Colab/CPU'da koşular kesilir): her oturumdan sonra satır `results.jsonl` (tipli, devam için) ve `results.csv` (ekleme) dosyalarına YAZILIR ve süre log'lanır
(`[i/N] model profil soru durum 12.3sn, geçen/tahmini kalan`); aynı `--out` ile yeniden başlatınca biten (model, profil, soru, tekrar) satırları ATLANIR (`--no-resume` sıfırdan başlatır).
Bitişte (ya da Ctrl+C ile) `summary.json` ve tekrarlanabilirlik sütunlu `results.csv` tüm satırlardan yeniden yazılır. Zaman aşımı: `HARNESS_LLM_TIMEOUT` (sn).

Metrikler (satır = soru x profil x model x tekrar): sayısal halüsinasyon (teslim ve deneme düzeyi), geçersiz araç çağrısı oranı, kanıtsız sayı, kural ihlalleri, etiket uyumu
(politika ve veri kümesi beklentisi), zorunlu adım atlama, geri çekilme, tekrarlanabilirlik (tekrar >= 2 ise), bağlam (prompt token), süre.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import time
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from harness import settings
from harness.agent_loop import run_session
from harness.llm_backend import LLMBackend, LLMError
from harness.session import HarnessSession
from harness.state_machine import HarnessRuleViolation
from schemas.enums import ToolName as T
from training import spec

PROFILES = ("A", "B", "C", "D", "E")
BackendFactory = Callable[[dict[str, Any], HarnessSession], LLMBackend]

CSV_COLUMNS = [
    "model", "profile", "question_id", "type", "as_of", "repeat", "status", "final_status", "abort_reason", "n_model_turns", "seconds",
    "n_tool_calls", "n_invalid_calls", "invalid_call_rate", "n_order_violations", "mandatory_pending",
    "n_number_claims", "n_hallucinated", "numerical_hallucination_rate", "n_unevidenced", "n_hallucinated_attempts", "n_attempts", "attempts_with_violation",
    "n_violations_attempt", "n_violations_delivered", "violation_codes_delivered", "fallback", "safe_failure",
    "delivered_action", "policy_label", "expected_label", "action_matches_policy", "action_matches_expected", "advice_language", "max_prompt_tokens", "final_hash",
]


def select_subset(records: Sequence[dict[str, Any]], n: int, seed: int = spec.SEED) -> list[dict[str, Any]]:
    """Tipe göre ORANTILI ve belirlenimli alt küme (kimlik sırası + tohumlu karıştırma)."""
    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(records, key=lambda r: r["id"]):
        by_type[r["type"]].append(r)
    total = sum(len(v) for v in by_type.values()) or 1
    out: list[dict[str, Any]] = []
    quotas = {t: max(1, round(n * len(v) / total)) for t, v in by_type.items()}
    for t in sorted(by_type):
        items = list(by_type[t])
        random.Random(f"{seed}:{t}").shuffle(items)
        out += items[: quotas[t]]
    return sorted(out, key=lambda r: r["id"])[:n] if len(out) > n else sorted(out, key=lambda r: r["id"])


@contextmanager
def real_tools() -> Iterator[None]:
    """Gerçek araçlar; modele AÇIK küme yalnızca gerçek araçlar (profil görünürlüğünü yalnızca daraltır)."""
    old_over, old_exposed = dict(settings.TOOL_BACKEND_OVERRIDES), settings.EXPOSED_TOOLS
    try:
        for t in (*spec.REAL_TOOLS, T.CHECK_DATA_QUALITY):
            settings.TOOL_BACKEND_OVERRIDES[t] = "real"
        settings.EXPOSED_TOOLS = frozenset(spec.REAL_TOOLS | {T.CHECK_DATA_QUALITY})   # C profilinde kapıyı model çağırır; D/E'de harness-içi
        yield
    finally:
        settings.TOOL_BACKEND_OVERRIDES.clear()
        settings.TOOL_BACKEND_OVERRIDES.update(old_over)
        settings.EXPOSED_TOOLS = old_exposed


def run_one(item: dict[str, Any], profile: str, model: str, factory: BackendFactory, repeat: int = 0) -> dict[str, Any]:
    """Tek koşu -> metrik satırı. Model/bağlantı hatası satıra yazılır (koşucu çökmez)."""
    t0 = time.time()
    session = HarnessSession.from_question(item["question"], profile=profile)
    row: dict[str, Any] = {"model": model, "profile": profile, "question_id": item["id"], "type": item["type"], "as_of": item.get("as_of"), "repeat": repeat,
                           "expected_label": item.get("label")}
    try:
        res = run_session(item["question"], factory(item, session), session=session)
        row.update(status=res.status, abort_reason=res.abort_reason, n_model_turns=res.n_model_turns)
        row["final_status"] = res.final.status if res.final else None
    except (LLMError, HarnessRuleViolation) as exc:
        row.update(status="ERROR", abort_reason=f"{type(exc).__name__}: {str(exc)[:120]}", n_model_turns=0, final_status=None)
    row["seconds"] = round(time.time() - t0, 2)
    fill_metrics(row, session)
    return row


def fill_metrics(row: dict[str, Any], s: HarnessSession) -> None:
    m = s.final_metrics()
    d, a = m["delivered_level"], m["attempt_level"]
    model_calls = [e for e in s.events if e["kind"] == "TOOL_CALL" and e.get("actor") == "model"]
    invalid = s.machine.n_invalid_calls
    pol = s.policy
    action = d.get("action")
    expected = row.get("expected_label")
    claims = d.get("n_number_claims") or 0
    row.update(
        n_tool_calls=len(model_calls) + invalid, n_invalid_calls=invalid,
        invalid_call_rate=round(invalid / (len(model_calls) + invalid), 4) if (len(model_calls) + invalid) else 0.0,
        n_order_violations=s.machine.n_order_violations, mandatory_pending=len(s.machine.pending_mandatory()) if d.get("delivered") else None,
        n_number_claims=claims, n_hallucinated=d.get("n_hallucinated"), numerical_hallucination_rate=d.get("numerical_hallucination_rate"),
        n_unevidenced=d.get("n_unevidenced"), n_hallucinated_attempts=a["n_hallucinated"], n_attempts=m["n_attempts"],
        attempts_with_violation=a["n_attempts_with_violation"], n_violations_attempt=a["n_violations"], n_violations_delivered=d.get("n_violations"),
        violation_codes_delivered=";".join(f"{k}:{v}" for k, v in (d.get("by_code") or {}).items()), fallback=d.get("fallback"),
        safe_failure=s.machine.safe_failure, delivered_action=action, policy_label=pol.label.value if pol else None,
        action_matches_policy=(action == pol.label.value) if (action and pol) else None,
        action_matches_expected=(action == expected) if (action and expected) else None,
        advice_language=int((d.get("by_code") or {}).get("ADVICE_LANGUAGE", 0) > 0) if d.get("delivered") else None,
        max_prompt_tokens=max([e["prompt_tokens"] for e in s.events if e["kind"] == "MODEL_TURN" and e.get("prompt_tokens")] or [None]),
        final_hash=hashlib.sha256((s.machine.explanation or "").encode()).hexdigest()[:12] if s.machine.explanation else None)


def add_reproducibility(rows: list[dict[str, Any]]) -> None:
    """Aynı (model, profil, soru) için tekrarların nihai metin özeti ve eylemi aynı mı? (tekrar >= 2 ise)"""
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["profile"], r["question_id"])].append(r)
    for g in groups.values():
        same = len(g) >= 2 and len({(r["final_hash"], r["delivered_action"]) for r in g}) == 1
        for r in g:
            r["reproducible"] = same if len(g) >= 2 else None


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """(model, profil) başına toplamlar. Oranlar paydası açık: hocanın metrikleri (halüsinasyon, geçersiz çağrı, kanıtsız, kural ihlali, tekrarlanabilirlik)."""
    out: dict[str, Any] = {}
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["profile"])].append(r)
    for (model, profile), g in sorted(groups.items()):
        claims = sum(r["n_number_claims"] or 0 for r in g)
        calls = sum(r["n_tool_calls"] or 0 for r in g)
        delivered = [r for r in g if r["n_violations_delivered"] is not None]
        out[f"{model}|{profile}"] = {
            "n_runs": len(g), "n_delivered": len(delivered), "n_error_or_aborted": sum(1 for r in g if r["status"] != "DELIVERED"),
            "numerical_hallucination_rate": round(sum(r["n_hallucinated"] or 0 for r in g) / claims, 4) if claims else 0.0,
            "n_number_claims": claims, "n_hallucinated": sum(r["n_hallucinated"] or 0 for r in g),
            "unevidenced_rate": round(sum(r["n_unevidenced"] or 0 for r in g) / claims, 4) if claims else 0.0,
            "invalid_tool_call_rate": round(sum(r["n_invalid_calls"] or 0 for r in g) / calls, 4) if calls else 0.0,
            "rule_violation_rate_delivered": round(sum(1 for r in delivered if r["n_violations_delivered"]) / len(delivered), 4) if delivered else None,
            "rule_violation_rate_attempts": round(sum(r["attempts_with_violation"] or 0 for r in g) / max(1, sum(r["n_attempts"] or 0 for r in g)), 4),
            "advice_language_rate": _rate(g, "advice_language"), "fallback_rate": _rate(g, "fallback"),
            "mandatory_step_skipped_rate": round(sum(1 for r in g if (r["mandatory_pending"] or 0) > 0) / len(delivered), 4) if delivered else None,
            "action_matches_policy_rate": _rate(g, "action_matches_policy"), "action_matches_expected_rate": _rate(g, "action_matches_expected"),
            "reproducibility_rate": _rate(g, "reproducible"), "mean_seconds": round(sum(r["seconds"] for r in g) / len(g), 2),
            "max_prompt_tokens": max([r["max_prompt_tokens"] for r in g if r.get("max_prompt_tokens")] or [None]),
        }
    return out


def row_key(r: dict[str, Any]) -> tuple[str, str, str, int]:
    return (str(r["model"]), str(r["profile"]), str(r["question_id"]), int(r["repeat"]))


def run_matrix(items: Sequence[dict[str, Any]], profiles: Sequence[str], factories: dict[str, BackendFactory], repeats: int = 1,
               progress: Callable[[str], None] | None = None, *, prior_rows: Sequence[dict[str, Any]] = (),
               on_row: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Matris koşusu. `prior_rows`: önceki (kesilen) koşudan biten satırlar; aynı (model, profil, soru, tekrar) ATLANIR ve sonuca eklenir.
    `on_row(row)`: her YENİ satırdan hemen sonra çağrılır (CSV/JSONL'a ekleme için). Dönüş: önceki + yeni satırlar (tekrarlanabilirlik hesaplanmış)."""
    done = {row_key(r) for r in prior_rows}
    rows: list[dict[str, Any]] = [dict(r) for r in prior_rows]
    total = len(factories) * len(profiles) * len(items) * repeats
    n_new, t0 = 0, time.time()
    with real_tools():
        for model, factory in factories.items():
            for profile in profiles:
                for item in items:
                    for rep in range(repeats):
                        if (model, profile, str(item["id"]), rep) in done:
                            continue
                        row = run_one(item, profile, model, factory, rep)
                        rows.append(row)
                        n_new += 1
                        if on_row:
                            on_row(row)
                        if progress:
                            elapsed = time.time() - t0
                            left = total - len(done) - n_new
                            eta = elapsed / n_new * left
                            progress(f"[{len(done) + n_new}/{total}] {model} {profile} {item['id']} {row['status']} {row['seconds']}sn "
                                     f"(geçen {elapsed / 60:.1f} dk, tahmini kalan {eta / 60:.1f} dk)")
    add_reproducibility(rows)
    return rows


def load_prior(out: Path) -> list[dict[str, Any]]:
    """`results.jsonl` (tipli) -> önceki satırlar. Bozuk son satır (yazım sırasında kesilmiş) sessizce atlanır."""
    path = out / "results.jsonl"
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


class RowSink:
    """Her satırı hemen `results.jsonl`'a (devam için) ve `results.csv`'ye (ekleme) yazar; dosyalar her satırdan sonra flush+fsync edilir."""

    def __init__(self, out: Path, *, reset: bool = False) -> None:
        out.mkdir(parents=True, exist_ok=True)
        self.jsonl, self.csv = out / "results.jsonl", out / "results.csv"
        if reset:
            for f in (self.jsonl, self.csv):
                f.unlink(missing_ok=True)

    def __call__(self, row: dict[str, Any]) -> None:
        with self.jsonl.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        new = not self.csv.exists() or self.csv.stat().st_size == 0
        with self.csv.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS + ["reproducible"], extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
            fh.flush()
            os.fsync(fh.fileno())


def write_outputs(out: Path, rows: list[dict[str, Any]], summary: dict[str, Any], meta: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cols = CSV_COLUMNS + ["reproducible"]
    with (out / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    (out / "summary.json").write_text(json.dumps({"meta": meta, "summary": summary}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A–E deney koşucusu (yerel Ollama)")
    ap.add_argument("--questions", default="data/training/v2/test.jsonl")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--models", nargs="+", required=True, help="Ollama model adları (örn. gemma3:4b gemma3-bist)")
    ap.add_argument("--profiles", nargs="+", default=list(PROFILES), choices=list(PROFILES))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--host", default=None, help="yalnızca localhost/127.0.0.1 (varsayılan: HARNESS_OLLAMA_HOST)")
    ap.add_argument("--out", default="reports/eval_v2")
    ap.add_argument("--no-resume", action="store_true", help="önceki sonuçları sil, sıfırdan başla (varsayılan: kaldığı yerden devam)")
    ap.add_argument("--max-runs", type=int, default=None, help="bu çağrıda en çok bu kadar YENİ oturum koş (iki Colab oturumuna bölmek için); sonra temiz çıkar")
    args = ap.parse_args(argv)

    from harness.llm_backend import OllamaBackend

    out = Path(args.out)
    records = [json.loads(line) for line in Path(args.questions).read_text(encoding="utf-8").splitlines() if line.strip()]
    items = select_subset(records, args.n)
    factories = {m: (lambda item, session, _m=m: OllamaBackend(model=_m, host=args.host)) for m in args.models}
    prior = [] if args.no_resume else load_prior(out)
    sink = RowSink(out, reset=args.no_resume)
    if prior:
        print(f"devam: {len(prior)} biten satır bulundu ({out / 'results.jsonl'}); atlanacak", flush=True)
    budget = {"left": args.max_runs}

    def on_row(row: dict[str, Any]) -> None:
        sink(row)
        if budget["left"] is not None:
            budget["left"] -= 1
            if budget["left"] <= 0:
                raise _BudgetReached()

    rows: list[dict[str, Any]] = list(prior)
    interrupted = None
    try:
        rows = run_matrix(items, args.profiles, factories, args.repeats, progress=lambda s: print(s, flush=True), prior_rows=prior, on_row=on_row)
    except _BudgetReached:
        interrupted = "max-runs"
        rows = load_prior(out)
    except KeyboardInterrupt:
        interrupted = "KeyboardInterrupt"
        rows = load_prior(out)
    add_reproducibility(rows)
    summary = summarize(rows) if rows else {}
    total = len(args.models) * len(args.profiles) * len(items) * args.repeats
    write_outputs(out, rows, summary, {"n_questions": len(items), "profiles": args.profiles, "models": args.models, "repeats": args.repeats,
                                       "question_ids": [i["id"] for i in items], "n_rows": len(rows), "n_expected_rows": total,
                                       "complete": len(rows) >= total, "interrupted": interrupted,
                                       "total_seconds": round(sum(r.get("seconds") or 0 for r in rows), 1)})
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if interrupted:
        print(f"KESİLDİ ({interrupted}): {len(rows)}/{total} satır yazıldı; aynı komutla yeniden çalıştırın", flush=True)
        return 130 if interrupted == "KeyboardInterrupt" else 0
    return 0


class _BudgetReached(Exception):
    """--max-runs bütçesi doldu (hata değil: bölünmüş koşu)."""


if __name__ == "__main__":
    raise SystemExit(main())
