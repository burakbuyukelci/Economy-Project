"""Karar kaydı + tekrar oynatma (replay): kayıtlı model yanıtları aynı harness'e yeniden verilir, araçlar gerçek veride yeniden çalışır; sonuç birebir aynı olmalıdır."""
from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from config.settings import SNAPSHOT_DIR
from experiments import ask, replay
from harness.llm_backend import ScriptedBackend
from training.questions import Question
from training.teacher import build_steps

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_MACRO").exists(), reason="gerçek snapshot/makro yok")
Q5 = "Analiz tarihi: 10.09.2026\nBugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver."


def scripted(text):
    q = Question("rp-q5", "macro", "test", text, date(2026, 9, 10), ("EREGL",), 0, {"advice": True, "claim": "kesin yükselir", "with_rate": False, "ticker": "EREGL"})
    return lambda t, session: ScriptedBackend(build_steps(q, session)[0])


@pytest.fixture()
def record_path(tmp_path):
    p = tmp_path / "decision.json"
    code = ask.main(["--question", Q5, "--model", "scripted", "--profile", "E", "--review", "REJECTED", "--reviewer", "ekip", "--reason", "OOS bozuldu",
                     "--record", str(p)], backend_factory=scripted(Q5))
    assert code == 0 and p.exists()
    return p


@needs_data
def test_record_is_self_contained_and_holds_the_decision_facts(record_path):
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    assert rec["format"] == 1 and rec["question"] == Q5 and rec["as_of"] == "2026-09-10" and rec["profile"] == "E"
    assert rec["summary"]["action"] == "INVESTIGATE" and rec["summary"]["policy_label"] == "INVESTIGATE" and rec["summary"]["rule_id"] == "G7_UNVERIFIED_CLAIM"
    assert rec["summary"]["tool_hashes"] and rec["summary"]["lock_hash"] and rec["summary"]["final_text"].endswith("EYLEM: INVESTIGATE")
    assert rec["review"] == {"decision": "REJECTED", "reviewer": "ekip", "reason": "OOS bozuldu"}
    assert rec["data_versions"]["macro"] == ["macro_2026-11-09_v2"] and rec["data_versions"]["price"]
    assert rec["messages"][0]["role"] == "system" and len(rec["committed_evidence"]) >= 6
    assert "2026-09-11" not in json.dumps(rec["summary"])


@needs_data
def test_replay_reproduces_the_decision_exactly(record_path, capsys):
    assert replay.main([str(record_path)]) == 0
    out = capsys.readouterr().out
    assert "REPLAY: AYNI" in out and "araç çağrısı" in out and "lock_hash" in out and "EYLEM" in out


@needs_data
def test_replay_detects_a_changed_tool_call(record_path, tmp_path, capsys):
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    for m in rec["messages"]:                                 # kayıtlı araç çağrısının ufkunu değiştir -> farklı araç çıktısı/input_hash
        for tc in m.get("tool_calls") or []:
            for r in tc["function"]["arguments"].get("relate_to", []):
                r["horizon"] = 10
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    assert replay.main([str(bad)]) == 1
    assert "REPLAY: FARK" in capsys.readouterr().out


@needs_data
def test_replay_detects_a_tampered_summary(record_path, tmp_path, capsys):
    rec = json.loads(record_path.read_text(encoding="utf-8"))
    rec["summary"]["lock_hash"] = "0" * 64
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    assert replay.main([str(bad)]) == 1
    assert "lock_hash" in capsys.readouterr().out


def test_replay_rejects_unknown_format(tmp_path, capsys):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"format": 99}), encoding="utf-8")
    assert replay.main([str(p)]) == 2 and "biçim" in capsys.readouterr().err
