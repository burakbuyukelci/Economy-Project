"""Araç-hata-kurtarma yörüngeleri (v2.3, opsiyonel): modelin ilk çağrısı araç hatası verir (öğretmen kasıtlı bozar), hatalı tur kayıptan MASKELİ, ardından doğru çağrı gelir.

Amaç: model hatayı yapmayı değil, araç hatasından sonra DÜZELTİP YENİDEN çağırmayı öğrenir (v2.1 modeli Soru 2'de hatadan kurtulamadı: `HAZIR` yazıp metin uydurdu).
Varsayılan (TOOL_ERROR_SHARE = 0) davranış DEĞİŞMEZ: v2.2 verisi aynı üretilir.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from config.settings import SNAPSHOT_DIR
from training import spec, teacher
from training.format import build_record
from training.questions import Question, build_questions
from training.teacher import corrupt_call, generate, plan_calls, real_tools, recovery_kind
from training.validate import session_problems

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_MACRO").exists(), reason="gerçek snapshot yok")
ELIGIBLE = ("weekday", "reversal", "catch_up", "indicators", "support_resistance", "history", "fundamental", "macro", "advice")


@pytest.fixture()
def always_tool_error(monkeypatch):
    monkeypatch.setattr(spec, "TOOL_ERROR_SHARE", 1.0)


def test_default_share_is_zero_and_never_assigns_tool_error():
    assert spec.TOOL_ERROR_SHARE == 0.0
    for q in build_questions("train", spec.SEED, {t: 6 for t in spec.TYPE_SHARES}):
        assert recovery_kind(q) != "tool_error"


def test_when_enabled_only_eligible_types_get_it(always_tool_error):
    qs = build_questions("train", spec.SEED, {t: 3 for t in spec.TYPE_SHARES})
    for q in qs:
        assert (recovery_kind(q) == "tool_error") == (q.type in ELIGIBLE), q.type


def test_corrupt_call_changes_exactly_one_thing_and_keeps_json_shape():
    qs = build_questions("train", spec.SEED, {t: 1 for t in ELIGIBLE})
    for q in qs:
        name, params = plan_calls(q)[0]
        bad = corrupt_call(name, params)
        assert bad != params and set(bad) <= set(params) | set(params), (name,)
        json.dumps(bad)
        assert params == plan_calls(q)[0][1]            # girdi değişmez (derin kopya)


@needs_data
def test_every_corruption_is_rejected_by_the_real_tool_with_an_informative_error(always_tool_error):
    from harness.session import HarnessSession
    with real_tools():
        for q in build_questions("train", spec.SEED, {t: 1 for t in ELIGIBLE}):
            name, params = plan_calls(q)[0]
            s = HarnessSession.from_question(q.text, profile="D")
            r = s.call_tool(name, corrupt_call(name, params))
            err = r.error if not r.ok else r.envelope.get("error")
            assert (not r.ok) or r.envelope["status"] == "ERROR", name
            assert err and err["code"] in ("INVALID_PARAMS", "UNSUPPORTED_PATTERN") and len(err["message"]) > 20, (name, err)


@needs_data
@pytest.mark.parametrize("qtype", ["weekday", "reversal", "indicators", "macro", "catch_up", "fundamental"])
def test_session_is_valid_masks_the_bad_turn_and_trains_the_corrected_call(always_tool_error, qtype):
    q = build_questions("train", spec.SEED, {qtype: 1})[0]
    with real_tools():
        g = generate(q, recovery="tool_error")
        assert session_problems(g) == [], (qtype, session_problems(g))
        rec = build_record(g)
    assert g.recovery == "tool_error" and g.bad_turns and g.bad_turns[0] == 0 and rec["recovery"] == "tool_error"
    tm = rec["text_messages"]
    asst = [i for i, m in enumerate(tm) if m["role"] == "assistant"]
    calls = [i for i in asst if "<tool_call>" in tm[i]["content"]]
    assert len(calls) >= 2 and rec["train_mask"][calls[0]] is False and rec["train_mask"][calls[1]] is True       # hatalı tur maskeli, düzeltilmiş çağrı kayıpta
    first_name = plan_calls(q)[0][0]
    assert first_name in tm[calls[0]]["content"] and first_name in tm[calls[1]]["content"] and tm[calls[0]]["content"] != tm[calls[1]]["content"]
    assert any(code in tm[calls[0] + 1]["content"] for code in ("INVALID_PARAMS", "UNSUPPORTED_PATTERN"))            # araç hatası modele görünür
    assert "EYLEM:" in tm[asst[-1]]["content"]


@needs_data
def test_weekday_corruption_reproduces_the_v2_1_failure_and_the_model_recovers(always_tool_error):
    """v2.1 modelinin Soru 2'deki gerçek hatası: TRIGGER'lar OUTCOME yapıldı -> UNSUPPORTED_PATTERN. Kurtarma: roller düzeltilip aynı araç yeniden çağrılır."""
    q = Question("t-wd", "weekday", "train", "Analiz tarihi: 10.09.2026\nTHYAO'da 01.01.2024 – 31.12.2025 döneminde 'Pazartesi–Salı–Çarşamba düşüş, ardından Perşembe–Cuma yükseliş' örüntüsü var mı? "
                 "Bu örüntü 01.01.2026 – 10.09.2026 döneminde de devam ediyor mu?", date(2026, 9, 10), ("THYAO",), 0,
                 {"ticker": "THYAO", "pattern": [("MON", "DOWN", "TRIGGER"), ("TUE", "DOWN", "TRIGGER"), ("WED", "DOWN", "TRIGGER"), ("THU", "UP", "OUTCOME"), ("FRI", "UP", "OUTCOME")],
                  "is_start": date(2024, 1, 1), "is_end": date(2025, 12, 31), "oos_start": date(2026, 1, 1), "oos_end": date(2026, 9, 10)})
    bad = corrupt_call("test_weekday_pattern", plan_calls(q)[0][1])
    assert all(d["role"] == "OUTCOME" for d in bad["pattern"])
    with real_tools():
        g = generate(q, recovery="tool_error")
    assert session_problems(g) == []
    names = [r.envelope["tool"] for r in g.session.store.records]
    statuses = [r.envelope["status"] for r in g.session.store.records if r.envelope["tool"] == "test_weekday_pattern"]
    assert statuses == ["ERROR", "OK"] and "test_weekday_pattern" in names
