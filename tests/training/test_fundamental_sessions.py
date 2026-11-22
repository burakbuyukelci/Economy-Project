"""Bilanço (Soru 4) eğitim oturumları: soru üretimi, model görünümü, veri seti sürümü uygunluğu, açıklama notları (gerçek v2 + bilanço snapshot'ı)."""
from __future__ import annotations

import copy
import re
from datetime import date

import pytest

from config.settings import SNAPSHOT_DIR
from harness import settings
from harness.mock_tools import TrainingEligibilityError, assert_training_eligible, aux_dataset_versions, is_training_eligible
from harness.model_view import model_view
from tools import calculate_fundamental_change as CH
from tools import get_fundamental_metrics as GM
from training import spec
from training.composer import FUNDAMENTAL_WARNING_NOTES, fundamental_notes
from training.questions import build_questions, first_visible_date, fourth_visible_date, pick_fundamental_date
from training.splits import tickers_for

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_FUNDAMENTALS").exists(),
                                reason="gerçek snapshot/bilanço veri seti yok")
AS_OF = "2026-09-10"


# --- soru üretimi ------------------------------------------------------------------------------------------------
@needs_data
def test_fundamental_questions_are_dated_after_the_first_visible_disclosure_and_in_split_range():
    for split in spec.SPLITS:
        for q in build_questions(split, spec.SEED, {"fundamental": 12}):
            t = q.plan["ticker"]
            assert q.as_of >= first_visible_date(t), (q.id, t, q.as_of)
            lo, hi = spec.DATE_RANGES[split]
            assert lo <= q.as_of <= hi and q.as_of.weekday() < 5
            assert t in tickers_for(split, "fundamental")
            assert q.text.startswith(f"Analiz tarihi: {q.as_of.strftime('%d.%m.%Y')}")


@needs_data
def test_fundamental_questions_are_deterministic_and_test_templates_stay_in_test():
    a = build_questions("train", spec.SEED, {"fundamental": 10})
    b = build_questions("train", spec.SEED, {"fundamental": 10})
    assert [q.id for q in a] == [q.id for q in b]
    assert all(q.template_idx % 4 != 3 for q in a)
    assert any(q.template_idx % 4 == 3 for q in build_questions("test", spec.SEED, {"fundamental": 30}))


@needs_data
def test_bank_questions_use_bank_metrics_and_net_profit():
    qs = [q for s in spec.SPLITS for q in build_questions(s, spec.SEED, {"fundamental": 40}) if q.plan["bank"]]
    assert qs, "bankalı soru yok (AKBNK eğitimde)"
    assert all(q.plan["metric"] == "NET_PROFIT" and "net faiz geliri" in q.text and "FAVÖK" not in q.text for q in qs)


@needs_data
def test_fourth_quarter_bias_moves_some_dates_after_the_fourth_disclosure():
    import random
    t = "EREGL"
    f4 = fourth_visible_date(t)
    assert f4 is not None and f4 > first_visible_date(t)
    ds = [pick_fundamental_date("train", random.Random(i), t) for i in range(300)]
    ds = [d for d in ds if d is not None]
    assert ds and min(ds) >= first_visible_date(t)
    after = sum(1 for d in ds if d >= f4)
    assert after / len(ds) > 0.6   # yanlılık 0,7 + doğal pay


@needs_data
def test_unsupported_fundamental_templates_no_longer_ask_for_what_the_tool_covers():
    from training.questions import _UNSUPPORTED
    texts = [t for k, t in _UNSUPPORTED if k == "fundamental"]
    assert texts and all("FAVÖK marjı" not in t and "net kârı" not in t for t in texts)


# --- veri seti sürümü uygunluğu (kural 12'nin bilanço karşılığı) -----------------------------------------------------
@needs_data
def test_real_fundamental_envelopes_carry_one_accepted_version_in_the_historical_only_warning():
    for env in (GM.run({"ticker": "TUPRS", "as_of": AS_OF}), CH.run({"ticker": "TUPRS", "as_of": AS_OF})):
        vs = aux_dataset_versions(env)
        assert len(vs) == 1 and re.fullmatch(r"fundamentals_\d{4}-\d{2}-\d{2}_v\d+", vs[0]) and vs[0] in settings.ACCEPTED_FUNDAMENTALS_VERSIONS
        assert is_training_eligible(env)
        assert_training_eligible(env)


@needs_data
def test_unaccepted_or_missing_fundamentals_version_is_rejected(monkeypatch):
    env = CH.run({"ticker": "TUPRS", "as_of": AS_OF})
    monkeypatch.setattr(settings, "ACCEPTED_FUNDAMENTALS_VERSIONS", frozenset({"fundamentals_2026-11-21_v1"}))
    assert not is_training_eligible(env)
    with pytest.raises(TrainingEligibilityError, match="kabul listesinde"):
        assert_training_eligible(env)
    monkeypatch.undo()
    stripped = copy.deepcopy(env)
    stripped["warnings"] = [w for w in stripped["warnings"] if not w.startswith("HISTORICAL_ONLY")]
    assert aux_dataset_versions(stripped) == [] and not is_training_eligible(stripped)
    two = copy.deepcopy(env)
    two["warnings"].append("HISTORICAL_ONLY: bilanço veri seti fundamentals_2026-11-21_v1; kaynak: YAHOO")
    assert len(aux_dataset_versions(two)) == 2 and not is_training_eligible(two)


@needs_data
def test_price_only_tools_are_unaffected_by_the_aux_version_rule():
    from tools import get_stock_history
    env = get_stock_history.run({"ticker": "TUPRS", "start": "2026-09-01", "end": "2026-09-10", "as_of": AS_OF})
    assert aux_dataset_versions(env) == [] and is_training_eligible(env)


def test_macro_envelopes_are_rejected_until_a_macro_snapshot_is_accepted():
    env = {"tool": "get_macro_context", "status": "OK", "data_version": "snap_2026-11-20_v2",
           "warnings": ["HISTORICAL_ONLY: makro veri seti macro_2026-11-21_v1; kaynak TCMB/EVDS"]}
    assert aux_dataset_versions(env) == ["macro_2026-11-21_v1"] and not is_training_eligible(env)


def test_macro_tool_is_not_exposed_in_v2_training():
    from schemas.enums import ToolName as T
    assert T.GET_MACRO_CONTEXT not in spec.REAL_TOOLS
    assert {T.GET_FUNDAMENTAL_METRICS, T.CALCULATE_FUNDAMENTAL_CHANGE} <= spec.REAL_TOOLS


# --- model görünümü ------------------------------------------------------------------------------------------------
@needs_data
def test_model_view_keeps_only_the_latest_quarter_and_evidence_quotable_fields():
    env = CH.run({"ticker": "TUPRS", "as_of": AS_OF})
    v = model_view(env, subject="TUPRS")
    r = v["results"]
    assert len(r["quarters"]) == 1 and r["quarters"][0]["fiscal_period"] == "2026Q2"
    assert "reactions" not in r["quarters"][0] and "benchmark_definition" not in r and "metric_set" not in r
    assert all(set(m) <= {"name", "value", "qoq_change", "yoy_change", "change_unit", "qoq_direction", "yoy_direction"} for m in r["quarters"][0]["metrics"])
    assert all(set(x) <= {"horizon", "group", "n", "mean_abnormal_vs_xu100_pct", "hit_rate_vs_xu100_pct", "n_excluded_incomplete_horizon"} for x in r["reaction_summary"])
    assert "fundamental_view" in v["view_trimmed"]
    assert not any(str(w).startswith("HISTORICAL_ONLY") and "bilanço veri seti" in str(w) for w in v["warnings"])
    # tam zarf değişmez (politika ve doğrulayıcı onu okur)
    assert len(env["results"]["quarters"]) >= 4 and any(str(w).startswith("HISTORICAL_ONLY") for w in env["warnings"])
    g = model_view(GM.run({"ticker": "TUPRS", "as_of": AS_OF}), subject="TUPRS")["results"]
    assert "period_end_date" not in g and g["fiscal_period"] == "2026Q2" and g["metrics"]


@needs_data
def test_model_view_still_shows_the_visibility_warnings_for_dates():
    v = model_view(CH.run({"ticker": "TUPRS", "as_of": AS_OF}), subject="TUPRS")
    assert any("KAP_DATE_VIA_NEWS" in str(w) for w in v["warnings"])   # TUPRS tarihleri haber/KAP doğrulamalı (saat bilinmiyor); belirsizlik uyarısı modele gider


# --- açıklama notları -------------------------------------------------------------------------------------------------
def test_fundamental_notes_contain_no_digits_and_follow_tool_warnings():
    assert all(not any(c.isdigit() for c in text) for _, text in FUNDAMENTAL_WARNING_NOTES)
    notes = fundamental_notes(["INSUFFICIENT_HISTORY: STATUTORY_DEADLINE: 2026Q1 dönemlerinin açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı",
                               "INCOMPLETE_HORIZON_EXCLUDED: 1 pencere"])
    assert notes[0].startswith("Bazı çeyreklerin açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı") and any("eksik veri" in n for n in notes)
    assert fundamental_notes([]) == []


# --- uçtan uca: gerçek oturum ------------------------------------------------------------------------------------------
@needs_data
def test_end_to_end_tuprs_session_is_valid_and_mentions_statutory_note_when_applicable():
    from training.questions import Question, fd
    from training.teacher import generate, real_tools
    from training.validate import session_problems
    d = date(2026, 9, 10)
    text = (f"Analiz tarihi: {fd(d)}\nTUPRS hissesinin 01.01.2024 – {fd(d)} döneminde kamuya açıklanan tüm çeyreklik bilançolarında FAVÖK marjı ve "
            "Net Borç/FAVÖK nasıl değişti? Her açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler XU100'e ve sektöre göre nasıl oldu? İyileşen çeyrekler daha iyi fiyat tepkisi almış mı?")
    q = Question("t-fund", "fundamental", "test", text, d, ("TUPRS",), 0,
                 {"basis": "QOQ", "metric": "EBITDA_MARGIN", "bank": False, "label_question": False, "ticker": "TUPRS"})
    with real_tools():
        g = generate(q)
    assert session_problems(g) == []
    names = [r.envelope["tool"] for r in g.session.store.records]
    assert "get_fundamental_metrics" in names and "calculate_fundamental_change" in names
    final = g.session.machine.explanation
    assert "nedensellik iddia edilmez" in final and "yatırım tavsiyesi" in final.lower()
    assert any(r.envelope["status"] == "OK" for r in g.session.store.records if r.envelope["tool"] == "calculate_fundamental_change")
