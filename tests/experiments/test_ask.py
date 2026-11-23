"""experiments/ask.py: canlı demo komutu (tek soru -> izlenebilir oturum). Model yerine öğretmen betiği (ScriptedBackend) kullanılır."""
from __future__ import annotations

import json
from datetime import date

import pytest

from config.settings import SNAPSHOT_DIR
from experiments import ask
from harness.llm_backend import ScriptedBackend
from training.questions import Question
from training.teacher import build_steps

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_MACRO").exists(), reason="gerçek snapshot/makro yok")
Q5 = "Analiz tarihi: 10.09.2026\nBugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver."


def scripted(question_text: str):
    q = Question("ask-q5", "macro", "test", question_text, date(2026, 9, 10), ("EREGL",), 0,
                 {"advice": True, "claim": "kesin yükselir", "with_rate": False, "ticker": "EREGL"})
    return lambda text, session: ScriptedBackend(build_steps(q, session)[0])


def _strip_time(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("süre"))   # süre duvar saatidir; geri kalan çıktı belirlenimli


@needs_data
def test_ask_prints_trace_final_answer_and_audit_and_writes_a_decision_log(tmp_path, capsys):
    log = tmp_path / "decision_log.jsonl"
    code = ask.main(["--question", Q5, "--model", "scripted", "--log", str(log)], backend_factory=scripted(Q5))
    out = capsys.readouterr().out
    assert code == 0
    assert "get_macro_context" in out and "EYLEM: INVESTIGATE" in out and "halüsinasyon: 0" in out and "kanıtsız: 0" in out
    assert "hedef fiyat veremem" in out and "politika faizi değil" in out and "=== Araç/durum izi ===" in out and "[model] get_macro_context -> OK" in out
    events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "SESSION_START" and "FINAL_DELIVERED" in kinds and "SESSION_CLOSED" in kinds
    assert not any("2026-09-11" in json.dumps(e) for e in events)


@needs_data
def test_ask_is_deterministic_and_accepts_explicit_as_of(capsys):
    q = "EREGL için dolar/TL ilişkisi nedir? Bugün alayım mı? Hedef fiyat ver. Dolar yükselince kesin yükselir."
    ask.main(["--question", q, "--as-of", "2026-09-10", "--model", "scripted"], backend_factory=scripted(q))
    a = _strip_time(capsys.readouterr().out)
    ask.main(["--question", q, "--as-of", "2026-09-10", "--model", "scripted"], backend_factory=scripted(q))
    assert a == _strip_time(capsys.readouterr().out) and "EYLEM:" in a and "as_of 2026-09-10" in a


def test_ask_requires_an_analysis_date(capsys):
    code = ask.main(["--question", "EREGL alayım mı?", "--model", "scripted"], backend_factory=lambda t, s: None)
    assert code == 2 and "analiz tarihi" in capsys.readouterr().err.lower()
