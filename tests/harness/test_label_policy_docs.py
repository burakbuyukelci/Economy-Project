"""Politika dokümantasyonu ile kod tutarlılığı: kural tablosu (docs/harness_design.md bölüm 11), kılavuz ve eğitim kuralları."""
from __future__ import annotations

import re
from pathlib import Path

import harness.settings as settings
from harness.label_policy import CAVEAT_TEXT, PolicyThresholds, RULE_IDS

REPO = Path(__file__).resolve().parents[2]
DESIGN = (REPO / "docs" / "harness_design.md").read_text(encoding="utf-8")
GUIDE = (REPO / "docs" / "tool_usage_guide.md").read_text(encoding="utf-8")
RULES = (REPO / "training" / "RULES.md").read_text(encoding="utf-8")


def section_11() -> str:
    start = DESIGN.index("## 11. Etiket politikası")
    return DESIGN[start:]


def test_every_rule_id_in_the_code_is_documented_and_vice_versa():
    documented = set(re.findall(r"`([GCWTF]\d_[A-Z0-9_]+)`", section_11()))
    assert documented == set(RULE_IDS), (documented ^ set(RULE_IDS))


def test_documented_thresholds_match_the_settings():
    text = section_11()
    t = PolicyThresholds()
    assert f"+{str(t.hit_margin_pp).replace('.', ',')} pp" in text
    for name in ("POLICY_HIT_MARGIN_PP", "POLICY_MIN_PASSING_HORIZONS", "POLICY_MIN_PEERS", "POLICY_SIGNAL_RECENCY_TRADING_DAYS",
                 "POLICY_MIN_QUARTERS"):
        assert name in text and hasattr(settings, name)


def test_fundamental_rules_are_marked_provisional_in_the_docs():
    text = section_11()
    assert "GEÇİCİ" in text and "F1–F4" in text and "gözden geçirilecek" in text


def test_candidate_note_is_documented_and_present_in_code():
    assert "CANDIDATE_CAVEAT" in section_11()
    for phrase in ("tarihsel gözlem", "örnek küçük", "belirsizlik var"):
        assert phrase in CAVEAT_TEXT.lower()


def test_split_date_rule_is_written_in_guide_training_rules_and_design_doc():
    for text in (GUIDE, RULES, section_11()):
        assert "1 Ocak" in text and "OOS doğrulaması yapılmadı" in text
    assert "split_date" in GUIDE and "out_of_sample_start" in GUIDE and "train_end" in GUIDE
    assert "split_date" in RULES and "train_end" in RULES


def test_gate_investigate_assumption_and_pending_real_gate_test_are_documented():
    assert "aday eylem yasak" in DESIGN and "test_real_retail_with_the_real_gate_tool" in DESIGN
