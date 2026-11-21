"""v1 eğitim/doğrulama/test verisi üretimi (tek komut, belirlenimli, yalnızca GERÇEK v2 araç çıktıları ve şema 1.3.0).

    python -m training.build_dataset --out data/training/v1            # üretir (data/training/ commit edilmez)
    python -m training.build_dataset --dry-run                         # etiket dağılımı taraması: yazmadan, doğal dağılımı raporlar

Akış: soru üretimi (fazla örneklemeli) -> öğretmen oturumu (gerçek araçlar, D profili) -> doğrulama hattı -> bağlam süzgeci (token tahmini) ->
tip başına etiket KOTALARIYLA seçim -> JSONL + report.json + manifest.json. Tek etiket payı > %80 ise çıkış kodu 2 (DUR). Boyut eksikleri raporda `shortfall`.
Artımlı: yeni araç/tip eklemek `spec.TYPE_SHARES`, `questions.BUILDERS`, `teacher.plan_calls` ve (gerekirse) `LABEL_QUOTAS`/`OVERSAMPLE` satırlarıdır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from training import spec
from training.format import build_record, dumps
from training.questions import Question, build_questions
from training.teacher import generate, real_tools, recovery_kind
from training.validate import dataset_problems, session_problems, too_long

# Tip başına HEDEF etiket payları (gerçekte oluşabilenlerle sınırlı; oluşmayan etiketin kotası boş kalır ve sıradakilerle doldurulur).
LABEL_QUOTAS: dict[str, dict[str, float]] = {
    "weekday": {"REJECT_SIGNAL": 0.45, "INVESTIGATE": 0.45, "WATCH": 0.10},
    "reversal": {"REJECT_SIGNAL": 0.35, "INVESTIGATE": 0.25, "WATCH": 0.20, "TECHNICAL_REVERSAL_CANDIDATE": 0.20},
    "catch_up": {"HOLD": 0.35, "REJECT_SIGNAL": 0.35, "INVESTIGATE": 0.30},
    "advice": {"INVESTIGATE": 0.80, "WATCH": 0.20},
}
OVERSAMPLE = {"weekday": 2.5, "reversal": 6.0, "catch_up": 4.0, "indicators": 1.4, "support_resistance": 1.4, "history": 1.4, "advice": 4.0,
              "unsupported": 1.4, "stale": 1.4}


def _candidates(split: str, seed: int) -> list[Question]:
    alloc = {t: max(n, int(round(n * OVERSAMPLE[t]))) for t, n in spec.allocate(split).items()}
    return build_questions(split, seed, alloc)


def _run(q: Question) -> tuple[dict[str, Any] | None, str | None]:
    """(kayıt, red nedeni). Red: 'invalid: ...' ya da 'too_long'."""
    g = generate(q, recovery=recovery_kind(q))
    problems = session_problems(g)
    if problems:
        return None, "invalid: " + problems[0][:140]
    rec = build_record(g)
    if too_long(rec):
        return rec, "too_long"
    return rec, None


def _select(recs: list[dict[str, Any]], qtype: str, n: int) -> list[dict[str, Any]]:
    """Etiket kotalarıyla seçim (sıra korunur); doldurulamayan kota kalan adaylarla tamamlanır."""
    quotas = LABEL_QUOTAS.get(qtype)
    if not quotas:
        return recs[:n]
    want = {label: int(round(share * n)) for label, share in quotas.items()}
    chosen: list[dict[str, Any]] = []
    taken: Counter[str] = Counter()
    for r in recs:
        if len(chosen) < n and taken[r["label"]] < want.get(r["label"], 0):
            chosen.append(r)
            taken[r["label"]] += 1
    rest = [r for r in recs if r not in chosen]
    return (chosen + rest[: n - len(chosen)])[:n]


def build(splits: tuple[str, ...], seed: int, *, progress: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"records": {}, "natural": {}, "drops": {}, "questions": [], "candidates": {}}
    with real_tools():
        for split in splits:
            cands = _candidates(split, seed)
            out["questions"] += cands
            out["candidates"][split] = dict(Counter(q.type for q in cands))
            ok_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
            natural: dict[str, Counter[str]] = defaultdict(Counter)
            drops: Counter[str] = Counter()
            for i, q in enumerate(cands):
                if progress and i % 200 == 0:
                    print(f"  {split} {i}/{len(cands)}", file=sys.stderr, flush=True)
                rec, why = _run(q)
                if rec is not None:
                    natural[q.type][rec["label"]] += 1
                if why:
                    drops[f"{q.type}:{why.split(':')[0]}"] += 1
                    if why.startswith("invalid"):
                        drops[f"first_invalid:{q.type}:{why[:110]}"] += 1
                    continue
                ok_by_type[q.type].append(rec)
            chosen: list[dict[str, Any]] = []
            for qtype, n in spec.allocate(split).items():
                chosen += _select(ok_by_type[qtype], qtype, n)
            out["records"][split] = chosen
            out["natural"][split] = {t: dict(c) for t, c in natural.items()}
            out["drops"][split] = dict(drops)
    return out


def report(built: dict[str, Any], splits: tuple[str, ...]) -> dict[str, Any]:
    rep: dict[str, Any] = {"generator": spec.GENERATOR_VERSION, "seed": spec.SEED, "splits": {}}
    allr = [r for s in splits for r in built["records"][s]]
    for s in splits:
        rs = built["records"][s]
        toks = sorted(r["tokens"] for r in rs) or [0]
        rep["splits"][s] = {
            "n": len(rs), "target": spec.SIZES[s],
            "by_type": dict(Counter(r["type"] for r in rs)),
            "by_label": dict(Counter(r["label"] for r in rs)),
            "by_rule": dict(Counter(r["rule_id"] for r in rs)),
            "by_type_label": {t: dict(Counter(r["label"] for r in rs if r["type"] == t)) for t in sorted({r["type"] for r in rs})},
            "recovery": dict(Counter(r["recovery"] or "none" for r in rs)),
            "tokens": {"source": sorted({r["token_source"] for r in rs}), "mean": round(sum(toks) / len(toks)), "p95": toks[int(0.95 * (len(toks) - 1))], "max": toks[-1]},
            "shortfall": {t: spec.allocate(s)[t] - sum(1 for r in rs if r["type"] == t) for t in spec.allocate(s)
                          if sum(1 for r in rs if r["type"] == t) < spec.allocate(s)[t]},
            "natural_labels_before_selection": built["natural"][s],
            "dropped": built["drops"][s],
            "candidates": built["candidates"][s],
            "too_long_rate_by_type": {t: round(built["drops"][s].get(f"{t}:too_long", 0) / n, 4) for t, n in built["candidates"][s].items()},
            "too_long_rate_overall": round(sum(v for k, v in built["drops"][s].items() if k.endswith(":too_long")) / max(1, sum(built["candidates"][s].values())), 4),
        }
    rep["overall_labels"] = dict(Counter(r["label"] for r in allr))
    top = Counter(r["label"] for r in allr).most_common(1)
    rep["top_label_share"] = round(top[0][1] / len(allr), 3) if allr else 0.0
    return rep


def write(out: Path, built: dict[str, Any], rep: dict[str, Any], splits: tuple[str, ...]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for s in splits:
        path = out / f"{s}.jsonl"
        path.write_text("\n".join(dumps(r) for r in sorted(built["records"][s], key=lambda r: r["id"])) + "\n", encoding="utf-8", newline="\n")
        files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"files_sha256": files, "generator": spec.GENERATOR_VERSION, "seed": spec.SEED,
                                                    "command": "python -m training.build_dataset"}, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v1 eğitim verisi üretici")
    ap.add_argument("--out", default="data/training/v1")
    ap.add_argument("--dry-run", action="store_true", help="yazma; etiket dağılımını raporla")
    ap.add_argument("--splits", nargs="+", default=list(spec.SPLITS), choices=list(spec.SPLITS))
    ap.add_argument("--seed", type=int, default=spec.SEED)
    ap.add_argument("--max-tokens", type=int, default=None, help=f"oturum token sınırı (varsayılan {spec.MAX_TOKENS})")
    ap.add_argument("--tight", action="store_true", help="model görünümü SIKI MOD (6144 geri dönüşü; canlıda HARNESS_VIEW_TIGHT=1 ile aynı olmalı)")
    args = ap.parse_args(argv)
    spec.SEED = args.seed
    if args.max_tokens:
        spec.MAX_TOKENS = args.max_tokens
    if args.tight:
        from harness import settings

        settings.MODEL_VIEW_TIGHT = True
    splits = tuple(args.splits)
    built = build(splits, args.seed, progress=True)
    rep = report(built, splits)
    recs = [r for s in splits for r in built["records"][s]]
    rep["dataset_problems"] = dataset_problems(recs, built["questions"]) if len(splits) == len(spec.SPLITS) else []
    print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
    if not args.dry_run:
        write(Path(args.out), built, rep, splits)
        print(f"yazıldı: {args.out}", file=sys.stderr)
    if rep["top_label_share"] > 0.80:
        print(f"DUR: tek etiket payı {rep['top_label_share']} > 0.80", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
