"""Makro (Soru 5) eğitim oturumları (v2.2): soru üretimi, araç çağrısı planı (relate_to), açıklama, veri seti sürümü, görünürlük (gerçek v2 + makro snapshot'ı)."""
from __future__ import annotations

import json
from datetime import date

import pytest

from config.settings import SNAPSHOT_DIR
from harness import settings
from harness.mock_tools import aux_dataset_versions, is_training_eligible
from schemas.enums import ToolName as T
from schemas.registry import validate_params
from training import spec
from training.composer import MACRO_FUNDING_NOTE
from training.questions import build_questions
from training.splits import tickers_for
from training.teacher import generate, plan_calls, real_tools
from training.validate import dataset_problems, session_problems

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_MACRO").exists(), reason="gerçek snapshot/makro veri seti yok")


# --- sabitler -----------------------------------------------------------------------------------------------------
def test_spec_adds_macro_type_and_exposes_the_real_macro_tool():
    assert spec.GENERATOR_VERSION == "2.2"
    assert "macro" in spec.TYPE_SHARES and abs(sum(spec.TYPE_SHARES.values()) - 1) < 1e-9
    assert T.GET_MACRO_CONTEXT in spec.REAL_TOOLS
    assert "macro_2026-11-09_v2" in settings.ACCEPTED_MACRO_VERSIONS and "macro_2026-11-09_v1" not in settings.ACCEPTED_MACRO_VERSIONS
    assert spec.allocate("train")["macro"] >= 60 and sum(spec.allocate("test").values()) == spec.SIZES["test"]


def test_macro_is_no_longer_taught_as_an_unsupported_topic():
    """v2.1 verisi 'makro için araç yok' diyordu (48 örnek); makro artık gerçek araç: unsupported şablonlarında makro KALMAMALI."""
    from training.composer import UNSUPPORTED_NOTE
    from training.questions import _UNSUPPORTED
    assert all(kind != "macro" for kind, _ in _UNSUPPORTED) and "macro" not in UNSUPPORTED_NOTE


# --- soru üretimi -------------------------------------------------------------------------------------------------
def test_macro_questions_are_deterministic_dated_in_range_and_test_templates_stay_in_test():
    for split in spec.SPLITS:
        a = build_questions(split, spec.SEED, {"macro": 14})
        assert [q.id for q in a] == [q.id for q in build_questions(split, spec.SEED, {"macro": 14})]
        for q in a:
            lo, hi = spec.DATE_RANGES[split]
            assert lo <= q.as_of <= hi and q.as_of.weekday() < 5 and q.plan["ticker"] in tickers_for(split, "macro")
            assert q.text.startswith(f"Analiz tarihi: {q.as_of.strftime('%d.%m.%Y')}") and q.plan["ticker"] in q.text
            assert (q.plan["claim"] in q.text) if q.plan["claim"] else ("kesin" not in q.text and "garanti" not in q.text)
            assert q.plan["advice"] == ("hedef fiyat" in q.text.lower())
    assert all(q.template_idx % 4 != 3 for q in build_questions("train", spec.SEED, {"macro": 30}))
    assert any(q.template_idx % 4 == 3 for q in build_questions("test", spec.SEED, {"macro": 30}))


def test_macro_questions_cover_claim_advice_and_neutral_variants():
    qs = build_questions("train", spec.SEED, {"macro": 40})
    assert any(q.plan["claim"] for q in qs) and any(not q.plan["advice"] for q in qs) and any(q.plan["with_rate"] for q in qs)


# --- araç çağrısı planı -------------------------------------------------------------------------------------------
def test_plan_calls_uses_relate_to_with_oos_split_and_declared_test_count():
    for q in build_questions("train", spec.SEED, {"macro": 20}):
        (name, params), = plan_calls(q)
        assert name == "get_macro_context" and params["as_of"] == q.as_of.isoformat() and params["start"] == "2024-01-01" and params["end"] == params["as_of"]
        rel = params["relate_to"]
        assert [r["lag_days"] for r in rel if r["macro_series"] == "USDTRY"] == [0, 5] and all(r["ticker"] == q.plan["ticker"] for r in rel)
        assert all(r["split_date"] == date(q.as_of.year, 1, 1).isoformat() for r in rel)          # RULES.md kural 2: OOS = as_of yılının 1 Ocak'ı
        assert params["n_tests_declared"] == len(rel) and ("TCMB_FUNDING_COST" in {r["macro_series"] for r in rel}) == q.plan["with_rate"]
        assert {"USDTRY", "TCMB_FUNDING_COST"} <= set(params["series"])
        validate_params(T.GET_MACRO_CONTEXT, params)                                                # şemaya uyar
        if q.plan["with_rate"]:
            assert next(r for r in rel if r["macro_series"] == "TCMB_FUNDING_COST")["transform"] == "LEVEL_DIFF"


# --- uçtan uca: gerçek oturumlar ------------------------------------------------------------------------------------
@needs_data
def test_end_to_end_sessions_are_valid_and_follow_the_question_five_behaviour():
    qs = build_questions("train", spec.SEED, {"macro": 16})
    seen_claim = seen_rate = seen_neutral = False
    with real_tools():
        for q in qs:
            g = generate(q)
            assert session_problems(g) == [], (q.id, session_problems(g))
            text = g.session.machine.explanation
            names = [r.envelope["tool"] for r in g.session.store.records]
            assert "get_macro_context" in names and g.session.policy.label.value == "INVESTIGATE"
            assert g.session.policy.rule_id == ("G7_UNVERIFIED_CLAIM" if q.plan["claim"] else "G7_NO_SCENARIO")
            assert text.rstrip().endswith("EYLEM: INVESTIGATE") and "nedensellik iddia edilmez" in text
            assert "~" in text and "korelasyon" in text and "düzeltilmiş p" in text           # ilişki araç çıktısından gösterilir
            assert MACRO_FUNDING_NOTE in text                                                    # politika faizi değil notu
            if q.plan["advice"]:
                assert "Yatırım tavsiyesi ve hedef fiyat veremem" in text
            if q.plan["claim"]:
                assert f"“{q.plan['claim']}” iddiası araç çıktılarıyla doğrulanmamıştır" in text
                seen_claim = True
            seen_rate |= q.plan["with_rate"]
            seen_neutral |= not q.plan["advice"]
    assert seen_claim and seen_neutral


@needs_data
def test_record_carries_macro_version_and_dataset_problems_reject_unaccepted_one():
    from training.format import build_record
    q = build_questions("train", spec.SEED, {"macro": 1})[0]
    with real_tools():
        g = generate(q)
    rec = build_record(g)
    assert rec["versions"]["macro"] == ["macro_2026-11-09_v2"] and rec["versions"]["fundamentals"] == [] and rec["type"] == "macro"
    assert "get_macro_context" in rec["tools"] and "check_data_quality" not in rec["tools"]
    env = next(r.envelope for r in g.session.store.records if r.envelope["tool"] == "get_macro_context")
    assert aux_dataset_versions(env) == ["macro_2026-11-09_v2"] and is_training_eligible(env)
    bad = json.loads(json.dumps(rec))
    bad["versions"]["macro"] = ["macro_2026-11-09_v1"]
    assert any("makro veri seti" in p for p in dataset_problems([bad], [], max_label_share=1.0))
    miss = json.loads(json.dumps(rec))
    miss["versions"]["macro"] = []
    assert any("makro veri seti sürümü yok" in p for p in dataset_problems([miss], [], max_label_share=1.0))


@needs_data
def test_model_sees_every_number_the_macro_explanation_quotes():
    from tests.training.test_view_visibility import hallucinations
    with real_tools():
        for q in build_questions("test", spec.SEED, {"macro": 8}):
            g = generate(q)
            assert hallucinations(g) == [], q.id


@needs_data
def test_model_view_of_the_real_macro_call_is_small():
    from training.format import build_record
    q = build_questions("train", spec.SEED, {"macro": 1})[0]
    with real_tools():
        rec = build_record(generate(q))
    tool_msgs = [m for m in rec["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 1 and len(tool_msgs[0]["content"]) < 4500           # 700+ nokta modele gitmez
    assert rec["tokens"] < 8192
