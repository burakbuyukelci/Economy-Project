"""Genelleme testi koşucusu: varyantları araç zincirinden geçirir (model YOK; öğretmen betiği, profil D, gerçek araçlar) ve sonuçları hata türüne göre gruplar.

    python -m tests.generalization.run [--out tests/generalization/report] [--only Q4]

SADECE RAPORLAR: hata bulursa düzeltmez, listeler. Kategoriler (bir varyant birden çok kategoride olabilir):
  CRASH               koşucu/harness/araç zincirinde yakalanmamış Python istisnası
  NOT_DELIVERED       oturum teslim edilmedi (abort) ya da nihai metin ACCEPTED değil / geri çekilme kullanıldı
  INVALID_ARGUMENT    geçersiz araç çağrısı (harness: INVALID_TOOL_CALL olayı) ya da araç `INVALID_PARAMS` / `UNKNOWN_TICKER` hatası
  TOOL_ERROR          araç zarfı status=ERROR (diğer kodlar; kod bazında alt gruplanır)
  MISSING_DATA        eksik veri: araç `NO_DATA`/`NOT_YET_DISCLOSED` hatası ya da `MACRO_DATA_MISSING` / `MISSING_TRADING_DAYS` uyarısı (BEKLENEN olabilir: makro snapshot'ı yok)
  LEAK                bir zarfın en geç sonuç tarihi as_of sonrası (schemas.registry.max_result_date) ya da sonuç ağacında as_of sonrası ISO tarih dizesi (ikincil, yanlış pozitif olabilir)
  NUMBER_QUALITY      nihai metinde sayı halüsinasyonu ya da kanıtsız sayı
"""
from __future__ import annotations

import argparse
import json
import re
import traceback
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from experiments.sample_runs import _final_fn, tools_context
from harness.agent_loop import run_session
from harness.llm_backend import ModelReply, ScriptedBackend, ToolCall
from harness.number_verifier import verify_session
from harness.session import HarnessSession
from schemas.registry import max_result_date
from tests.generalization.variants import TYPES, all_variants

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MISSING_CODES = {"NO_DATA", "NOT_YET_DISCLOSED"}
INVALID_TOOL_CODES = {"INVALID_PARAMS", "UNKNOWN_TICKER"}
MISSING_WARNINGS = ("MACRO_DATA_MISSING", "MISSING_TRADING_DAYS")
HARNESS_TOOLS = ("check_data_quality", "build_evidence_bundle")
CATEGORIES = ("CRASH", "NOT_DELIVERED", "INVALID_ARGUMENT", "TOOL_ERROR", "MISSING_DATA", "LEAK", "NUMBER_QUALITY")


def _future_dates(node: Any, as_of: date, path: str = "results") -> list[str]:
    """Sonuç ağacındaki as_of SONRASI ISO tarih dizeleri (yol: değer). İkincil denetim."""
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            out += _future_dates(v, as_of, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node[:400]):
            out += _future_dates(v, as_of, f"{path}[{i}]")
    elif isinstance(node, str) and ISO.match(node):
        try:
            if date.fromisoformat(node) > as_of:
                out.append(f"{path}={node}")
        except ValueError:
            pass
    return out


def execute(v: dict[str, Any]) -> dict[str, Any]:
    """Tek varyant -> kayıt. Hiçbir istisna dışarı sızmaz (CRASH olarak kaydedilir)."""
    as_of = date.fromisoformat(v["as_of"])
    rec: dict[str, Any] = {"id": v["id"], "type": v["type"], "as_of": v["as_of"], "tickers": v["tickers"], "params": v["params"], "categories": [], "findings": []}

    def add(cat: str, detail: str) -> None:
        if cat not in rec["categories"]:
            rec["categories"].append(cat)
        rec["findings"].append({"category": cat, "detail": detail})

    try:
        session = HarnessSession.from_question(v["text"], profile="D")
        teacher_final = _final_fn(v, session)

        def final(msgs: list[dict[str, Any]], tools: Any) -> str:
            # politika yoksa (açıklama aşamasına geçilemedi: örn. hiçbir analiz aracı başarılı olmadı) öğretmenin kuracağı metin yoktur: model "bitti" demeye devam eder;
            # böylece harness'in GERÇEK davranışı (reddetme geri bildirimi, AGENT_MAX_TURNS) görülür, öğretmen betiği çökmez
            return teacher_final(msgs, tools) if session.policy is not None else "Veri yok; sonuç verilemiyor."

        steps: list[Any] = [ModelReply(tool_calls=(ToolCall(n, p),)) for n, p in v["calls"]] + ["HAZIR", final] + ["Veri yok; sonuç verilemiyor."] * 45
        result = run_session(v["text"], ScriptedBackend(steps), session=session)
    except Exception as exc:  # noqa: BLE001 - amaç tam olarak bunu yakalamak
        tb = traceback.extract_tb(exc.__traceback__)
        where = f"{Path(tb[-1].filename).name}:{tb[-1].lineno} {tb[-1].name}" if tb else "?"
        add("CRASH", f"{type(exc).__name__}: {str(exc)[:200]} @ {where}")
        rec["status"] = "CRASH"
        return rec

    rec["status"], rec["final_status"] = result.status, result.final.status if result.final else None
    pol = session.policy
    rec["label"], rec["rule_id"] = (pol.label.value, pol.rule_id) if pol else (None, None)
    if result.status != "DELIVERED":
        add("NOT_DELIVERED", f"oturum durumu {result.status}: {result.abort_reason}")
    elif result.final is None or result.final.status != "ACCEPTED":
        add("NOT_DELIVERED", f"nihai durum {result.final.status if result.final else None}")
    if [e for e in session.events if e["kind"] == "FINAL_FALLBACK"]:
        add("NOT_DELIVERED", "güvenli geri çekilme kullanıldı")
    for e in session.events:
        if e["kind"] == "INVALID_TOOL_CALL":
            add("INVALID_ARGUMENT", f"harness reddi {e.get('code')}: {str(e.get('message') or e.get('detail') or '')[:160]}")
    for r in session.store.records:
        env = r.envelope
        tool = env["tool"]
        if env["status"] != "OK":
            code = (env.get("error") or {}).get("code")
            msg = str((env.get("error") or {}).get("message"))[:160]
            cat = "INVALID_ARGUMENT" if code in INVALID_TOOL_CODES else "MISSING_DATA" if code in MISSING_CODES else "TOOL_ERROR"
            add(cat, f"{tool} ERROR {code}: {msg}")
            continue
        for w in env.get("warnings") or []:
            if str(w).startswith(MISSING_WARNINGS) and tool not in HARNESS_TOOLS:      # kapı/kanıt paketi aynı uyarıları yeniden yayar: çift sayılmaz
                add("MISSING_DATA", f"{tool} {str(w)[:170]}")
        mrd = max_result_date(env["results"]) if env.get("results") else None
        if mrd and mrd > as_of:
            add("LEAK", f"{tool} en geç sonuç tarihi {mrd} > as_of {as_of}")
        for fd_ in _future_dates(env.get("results"), as_of)[:3]:
            add("LEAK", f"{tool} (ikincil) {fd_}")
    try:
        rep = verify_session(session, session.machine.explanation or "")
        rec["numbers"] = {"claims": len(rep.claims), "hallucinated": rep.n_hallucinated, "unevidenced": rep.n_unevidenced}
        if rep.n_hallucinated or rep.n_unevidenced:
            add("NUMBER_QUALITY", f"halüsinasyon {rep.n_hallucinated}, kanıtsız {rep.n_unevidenced}")
    except Exception as exc:  # noqa: BLE001
        add("CRASH", f"sayı doğrulama istisnası {type(exc).__name__}: {str(exc)[:160]}")
    rec["tools"] = [r.envelope["tool"] for r in session.store.records if r.envelope["tool"] not in ("check_data_quality", "build_evidence_bundle")]
    return rec


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, list[str]] = defaultdict(list)
    detail: dict[str, Counter] = defaultdict(Counter)
    for r in records:
        for f in r["findings"]:
            detail[f["category"]][re.sub(r"\b[A-Z]{4,6}\b(?=:)", "<HİSSE>", re.sub(r"\d{4}-\d{2}-\d{2}|\d+", "#", f["detail"]))[:150]] += 1
        for c in r["categories"]:
            by_cat[c].append(r["id"])
    per_type = {t: {"n": sum(1 for r in records if r["type"] == t),
                    "ran_ok": sum(1 for r in records if r["type"] == t and r["status"] == "DELIVERED"),
                    "clean": sum(1 for r in records if r["type"] == t and not [c for c in r["categories"] if c != "MISSING_DATA"] and r["status"] == "DELIVERED"),
                    "with_findings": sum(1 for r in records if r["type"] == t and r["categories"])} for t in TYPES}
    return {"n_variants": len(records), "n_distinct_tickers": len({t for r in records for t in r["tickers"]}),
            "ran_ok": sum(1 for r in records if r["status"] == "DELIVERED"), "per_type": per_type,
            "by_category": {c: {"n_variants": len(by_cat[c]), "variants": by_cat[c], "patterns": detail[c].most_common()} for c in CATEGORIES if by_cat.get(c)},
            "labels": dict(Counter(f"{r['type']}:{r.get('label')}" for r in records))}


def render(records: list[dict[str, Any]], s: dict[str, Any]) -> str:
    L = ["# Genelleme testi raporu (model yok; öğretmen betiği, profil D, gerçek araçlar)", "",
         f"* Varyant: **{s['n_variants']}**; farklı hisse: **{s['n_distinct_tickers']}**; oturumu teslim eden: **{s['ran_ok']}/{s['n_variants']}**", "",
         "| Tip | Varyant | Teslim (çalıştı) | Temiz (MISSING_DATA hariç bulgu yok) | Bulgulu |", "|---|---|---|---|---|"]
    for t, v in s["per_type"].items():
        L.append(f"| {t} | {v['n']} | {v['ran_ok']} | {v['clean']} | {v['with_findings']} |")
    L += ["", "## Hata türüne göre", ""]
    if not s["by_category"]:
        L.append("Bulgu yok.")
    for c, v in s["by_category"].items():
        L += [f"### {c} ({v['n_variants']} varyant)", "", f"Varyantlar: {', '.join(v['variants'])}", ""]
        for pat, n in v["patterns"]:
            L.append(f"* x{n}: {pat}")
        L.append("")
    L += ["## Varyant ayrıntıları", "", "| id | hisse(ler) | as_of | parametre | etiket (kural) | bulgular |", "|---|---|---|---|---|---|"]
    for r in records:
        L.append(f"| {r['id']} | {','.join(r['tickers'])[:40]} | {r['as_of']} | {json.dumps(r['params'], ensure_ascii=False)[:90]} | {r.get('label')} ({r.get('rule_id')}) | "
                 f"{', '.join(r['categories']) or '-'} |")
    return "\n".join(L) + "\n"


def run(only: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    variants = [v for v in all_variants() if only is None or v["id"].startswith(only)]
    with tools_context():
        records = [execute(v) for v in variants]
    return records, summarize(records)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/generalization/report")
    ap.add_argument("--only", default=None, help="id öneki (örn. Q4)")
    args = ap.parse_args(argv)
    records, s = run(args.only)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps({"summary": s, "records": records}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (out / "report.md").write_text(render(records, s), encoding="utf-8", newline="\n")
    print(json.dumps({k: s[k] for k in ("n_variants", "n_distinct_tickers", "ran_ok", "per_type")}, ensure_ascii=False, indent=1))
    for c, v in s["by_category"].items():
        print(f"{c}: {v['n_variants']} varyant {v['variants']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
