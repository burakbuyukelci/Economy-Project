"""Karar kaydını TEKRAR OYNAT (replay): kayıtlı model yanıtları aynı harness'e yeniden verilir; araçlar gerçek veride yeniden çalışır; özet birebir aynı olmalıdır.

    python -m experiments.replay reports/decision_q5.json

Neden: "aynı girdi → aynı çıktı" (CLAUDE.md kural 8) ve kanıt bütünlüğü gösterilir. Model çağrılmaz (Ollama gerekmez): modelin kayıtlı yanıtları (araç çağrıları, taslak, nihai metin) sırayla
beslenir; harness kapıyı/kanıtı/politikayı yeniden hesaplar. Farklı çıkan her şey (araç `input_hash`, nihai metin, etiket, kural, `lock_hash`, sayı denetimi) listelenir. Çıkış kodu: 0 aynı, 1 fark, 2 geçersiz kayıt.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from experiments.decision_record import FORMAT, attach_review, compare, summary_of
from experiments.eval_runner import real_tools
from harness.agent_loop import run_session
from harness.llm_backend import ModelReply, ScriptedBackend, ToolCall
from harness.session import HarnessSession
from harness.text_protocol import TOOL_CALL_OPEN, parse_reply


def steps_from_messages(messages: list[dict[str, Any]]) -> list[ModelReply]:
    """Kayıtlı asistan mesajlarından (sırayla) model yanıtları: araç çağrıları, taslak ve nihai metinler, bozuk çağrı metinleri."""
    out: list[ModelReply] = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        calls = tuple(ToolCall(tc["function"]["name"], dict(tc["function"].get("arguments") or {})) for tc in m.get("tool_calls") or [])
        text = m.get("content") or ""
        if calls:
            out.append(ModelReply(text=text, tool_calls=calls))
        elif TOOL_CALL_OPEN in text and parse_reply(text).error:      # bozuk araç çağrısı metni (çalıştırılmaz; geçersiz çağrı sayılır)
            out.append(ModelReply(text=text, format_error=parse_reply(text).error))
        else:
            out.append(ModelReply(text=text))
    return out


def replay_record(rec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(oynatma özeti, farklar)."""
    with real_tools():
        session = HarnessSession.from_question(rec["question"], explicit_as_of=date.fromisoformat(rec["as_of"]), profile=rec["profile"])
        attach_review(session, rec.get("review"))
        try:
            run_session(rec["question"], ScriptedBackend(steps_from_messages(rec["messages"])), session=session)
        except Exception as exc:                                  # betik bitti vb.: kayıtla oynatma uyuşmuyor
            return {}, [f"oynatma çalıştırılamadı: {type(exc).__name__}: {str(exc)[:120]}"]
    got = summary_of(session)
    return got, compare(rec["summary"], got)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Karar kaydını tekrar oynat ve doğrula")
    ap.add_argument("record", help="`experiments.ask --record` çıktısı (JSON)")
    args = ap.parse_args(argv)
    rec = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if rec.get("format") != FORMAT:
        print(f"HATA: kayıt biçimi {rec.get('format')!r} desteklenmiyor (beklenen {FORMAT})", file=sys.stderr)
        return 2
    got, diffs = replay_record(rec)
    s = rec["summary"]
    print(f"=== REPLAY: {'AYNI' if not diffs else 'FARK'} | soru kimliği as_of {rec['as_of']} | profil {rec['profile']} | model {rec.get('model')} ===")
    if got:
        same = lambda a, b: "AYNI" if a == b else "FARKLI"  # noqa: E731
        print(f"araç çağrısı: kayıt {len(s['tool_hashes'])} / oynatma {len(got['tool_hashes'])}: {same(s['tool_hashes'], got['tool_hashes'])} (input_hash sırası)")
        print(f"lock_hash: {str(got['lock_hash'])[:16]}… {same(s['lock_hash'], got['lock_hash'])}")
        print(f"nihai metin: {same(s['final_text'], got['final_text'])} | EYLEM {got['action']} (politika {got['policy_label']}, {got['rule_id']})")
        print(f"sayı iddiası {got['n_number_claims']}, halüsinasyon {got['n_hallucinated']}, kanıtsız {got['n_unevidenced']}")
    for d in diffs:
        print(f"  FARK -> {d}")
    return 0 if not diffs else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
