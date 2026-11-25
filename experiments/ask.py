"""Canlı demo / canlı test komutu: TEK soru -> yerel model (Ollama) + harness -> izlenebilir oturum.

    python -m experiments.ask --model gemma3-bist --question "Analiz tarihi: 10.09.2026\nBugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver."
    python -m experiments.ask --model gemma3-bist --profile E --question-file soru.txt --log reports/decision_log.jsonl --review REJECTED --reviewer ekip --reason "OOS bozuldu"

Çıktı: araç çağrı izi (hangi araç, kim çağırdı, durum), nihai cevap (`EYLEM:` satırı dahil), denetim özeti (sayı iddiası / halüsinasyon / kanıtsız, kural ihlali,
geçersiz çağrı, politika etiketi ile eşleşme), süre ve (istenirse) karar günlüğü JSONL (`--log`; tekrar oynatma/replay için her olay satırı). Profil D varsayılan
(kapı + kanıt + son denetim harness'te); A..E seçilebilir. Ollama yalnızca yerel (127.0.0.1). Analiz tarihi soruda "Analiz tarihi: GG.AA.YYYY" ile ya da `--as-of` ile verilir
(harness belirler; model değil). Bulut AI API'si YOKTUR.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from experiments.eval_runner import PROFILES, real_tools
from experiments.decision_record import attach_review
from harness.agent_loop import run_session
from harness.as_of import _markers
from harness.event_log import EventLog
from harness.scope_guard import MESSAGE, is_out_of_scope
from harness.llm_backend import LLMError
from harness.routing import ReviewStatus
from harness.session import HarnessSession
from harness.state_machine import HarnessRuleViolation

BackendFactory = Callable[[str, HarnessSession], Any]


def _trace(session: HarnessSession) -> list[str]:
    lines: list[str] = []
    for e in session.events:
        k = e["kind"]
        if k == "TOOL_CALL":
            who = "model" if e.get("actor") == "model" else "harness"
            lines.append(f"  [{who}] {e['tool']} -> {e['status']} (durum: {e.get('state_after')})")
        elif k == "INVALID_TOOL_CALL":
            lines.append(f"  [model] GEÇERSİZ çağrı {e.get('tool')}: {e.get('code')}")
        elif k == "FINAL_CHECK":
            lines.append(f"  [harness] son denetim (deneme {e.get('attempt')}): ok={e.get('ok')}, ihlal={e.get('n_violations')}, eylem={e.get('action')}, politika={e.get('policy_label')}")
        elif k == "EVIDENCE_LOCKED":
            lines.append(f"  [harness] kanıt kilitlendi (kapı {e.get('gate_status')}), lock_hash {str(e.get('lock_hash'))[:12]}")
    return lines


def main(argv: list[str] | None = None, *, backend_factory: BackendFactory | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tek soru: yerel model + harness (canlı demo)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--question", help="soru metni")
    g.add_argument("--question-file", help="soru metni dosyası (UTF-8)")
    ap.add_argument("--model", default=None, help="Ollama model adı (varsayılan: HARNESS_MODEL)")
    ap.add_argument("--profile", default="D", choices=list(PROFILES))
    ap.add_argument("--as-of", default=None, help="analiz tarihi YYYY-MM-DD (soruda işaret yoksa)")
    ap.add_argument("--host", default=None, help="yalnızca localhost/127.0.0.1")
    ap.add_argument("--log", default=None, help="karar günlüğü JSONL (olay başına satır)")
    ap.add_argument("--record", default=None, help="yeniden oynatılabilir TAM karar kaydı (JSON); `python -m experiments.replay` ile doğrulanır")
    ap.add_argument("--trace", default=None, help="hocanın sunum kuralı için TAM iz kaydı (JSON): model/sürüm, istemler, araçlar+params+tarihler, çıktılar, zaman damgaları, sıcaklık, seed")
    ap.add_argument("--scenario", default=None, help="iz kaydına yazılan senaryo adı")
    ap.add_argument("--review", choices=[r.value for r in ReviewStatus if r != ReviewStatus.PENDING_HUMAN_REVIEW], default=None, help="insan incelemesi kararı (profil E)")
    ap.add_argument("--reviewer", default="reviewer")
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)
    text = args.question if args.question is not None else Path(args.question_file).read_text(encoding="utf-8")
    text = text.replace("\\n", "\n")
    if is_out_of_scope(text):                                     # finans dışı soru (hava durumu...): model çalıştırılmadan hemen kısa cevap
        print("=== Kapsam dışı soru: model ve araç çalıştırılmadı ===")
        print(MESSAGE)
        return 0
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    found = _markers(text)
    head_date = as_of or (next(iter(found)) if len(found) == 1 else None)     # --as-of ya da sorudaki tek işaret ("Bugün 10.09.2026")
    if head_date is not None and not re.search(r"(?i)analiz\s+tarihi", text):
        # Eğitim sorularının hepsi "Analiz tarihi: GG.AA.YYYY" satırıyla başlar; hocanın canlı sorularında bu satır yoktur ("Bugün 10.09.2026" gibi işaretler as_of'u
        # çözer ama başlık satırı eksik kalır). Aynı biçimi vermek dağılım kaymasını önler.
        text = f"Analiz tarihi: {head_date.strftime('%d.%m.%Y')}\n{text}"
    kwargs: dict[str, Any] = {}
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        Path(args.log).write_text("", encoding="utf-8")        # her çalıştırma temiz günlük
        kwargs["log"] = EventLog(Path(args.log), timestamps=bool(args.trace))
    elif args.trace:
        kwargs["log"] = EventLog(timestamps=True)               # iz kaydı için zaman damgalı bellek günlüğü
    try:
        with real_tools():
            session = HarnessSession.from_question(text, explicit_as_of=as_of, profile=args.profile, **kwargs)
            review = ({"decision": args.review, "reviewer": args.reviewer, "reason": args.reason}
                      if args.review and session.profile.human_review else None)
            attach_review(session, review)
            if backend_factory is None:
                from harness.llm_backend import OllamaBackend

                backend = OllamaBackend(model=args.model, host=args.host)
                model_name = backend.model
            else:
                backend, model_name = backend_factory(text, session), args.model or "custom"
            started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            t0 = time.time()
            res = run_session(text, backend, session=session)
            secs = time.time() - t0
            finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    except ValueError as exc:                                     # analiz tarihi çözümlenemedi
        print(f"HATA: analiz tarihi bulunamadı ({exc}). Soruya 'Analiz tarihi: GG.AA.YYYY' ekleyin ya da --as-of verin.", file=sys.stderr)
        return 2
    except (LLMError, HarnessRuleViolation) as exc:
        print(f"HATA: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"=== Oturum: as_of {session.as_of.isoformat()} (kaynak: {session.as_of_source}) | profil {session.profile.name} | model {model_name} | durum {res.status} ===")
    print("=== Araç/durum izi ===")
    print("\n".join(_trace(session)) or "  (araç çağrısı yok)")
    print("=== Nihai cevap ===")
    print(session.machine.explanation or ("(teslim edilmedi" + (f": {res.abort_reason}" if res.abort_reason else "") + ")"))
    if review:
        print(f"=== İnsan incelemesi: {review['decision']} ({review['reviewer']}): {review['reason'] or '-'} ===")
    elif args.review:
        print(f"UYARI: --review yalnızca profil E'de kaydedilir (profil {session.profile.name}); kaydedilmedi.", file=sys.stderr)
    m = session.final_metrics()["delivered_level"]
    pol = session.policy
    print("=== Denetim ===")
    print(f"etiket (model): {m.get('action')} | politika: {pol.label.value if pol else None} ({pol.rule_id if pol else None}) | eşleşme: {m.get('policy_match')}")
    print(f"sayı iddiası: {m.get('n_number_claims')}, halüsinasyon: {m.get('n_hallucinated')}, kanıtsız: {m.get('n_unevidenced')} | kural ihlali: {m.get('n_violations')} | "
          f"geçersiz araç çağrısı: {session.machine.n_invalid_calls} | geri çekilme: {m.get('fallback')}")
    print(f"süre: {secs:.1f} sn | model turu: {res.n_model_turns}")
    if args.record:
        from experiments.decision_record import build_record

        Path(args.record).parent.mkdir(parents=True, exist_ok=True)
        Path(args.record).write_text(json.dumps(build_record(session, res.messages, question=text, model=model_name, review=review), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"karar kaydı: {args.record} (tekrar oynatma: python -m experiments.replay {args.record})")
    if args.trace:
        from experiments.trace_export import build_trace

        Path(args.trace).parent.mkdir(parents=True, exist_ok=True)
        trace = build_trace(session, res, res.messages, question=text, model_name=model_name, backend=backend, started_at=started_at, finished_at=finished_at,
                            duration_s=secs, scenario=args.scenario)
        Path(args.trace).write_text(json.dumps(trace, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print(f"iz kaydı: {args.trace} (cevap kaynağı: {trace['final_answer']['source']})")
    if args.log:
        print(f"karar günlüğü: {args.log} ({len(session.events)} olay)")
    return 0 if res.status == "DELIVERED" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
