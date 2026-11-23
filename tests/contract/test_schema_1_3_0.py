"""Şema 1.3.0 sözleşme testleri.

Kapsam: (a) find_support_resistance mesafe alanları, (b) run_backtest.last_exit_date (+ max_result_date),
(c) detect_reversal_events grup başına ham olay günü ve çakışan ileri pencere sayıları; sürüm koşullu zorunluluk;
1.2.0 zarflarının (dondurulmuş) geçerli kalması.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from schemas import SCHEMA_VERSION, ToolName, validate_envelope
from schemas import registry as REG
from schemas.examples import example_envelope

FIXTURES = Path(__file__).parent / "fixtures" / "envelopes_1_2_0"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))
SR, BT, REV = ToolName.FIND_SUPPORT_RESISTANCE, ToolName.RUN_BACKTEST, ToolName.DETECT_REVERSAL_EVENTS


def _env(tool: ToolName, version: str = "1.3.0") -> dict:
    env = copy.deepcopy(example_envelope(tool))
    env["schema_version"] = version
    return env


def test_schema_version_is_at_least_1_3_0():
    assert tuple(int(x) for x in SCHEMA_VERSION.split(".")) >= (1, 3, 0)  # 1.4.0'da yalnızca MacroSeries eklendi


# --- 1.2.0 zarfları geçerli kalır -----------------------------------------------------------------
def test_fixture_set_covers_all_tools():
    assert {t.value for t in ToolName} <= {p.stem for p in FIXTURE_FILES}


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.stem)
def test_frozen_1_2_0_envelopes_still_validate(path):
    env = json.loads(path.read_text(encoding="utf-8"))
    assert env["schema_version"] == "1.2.0"
    validate_envelope(env)


# --- örnek zarflar 1.3.0 alanlarını taşır ---------------------------------------------------------
def test_examples_carry_the_new_fields():
    sr = validate_envelope(_env(SR)).results
    assert (sr["nearest_support_distance_pct"], sr["nearest_resistance_distance_pct"]) == (3.3333, 6.6667)
    assert validate_envelope(_env(BT)).results["last_exit_date"] == "2026-09-04"
    for g in validate_envelope(_env(REV)).results["groups"]:
        assert g["n_raw_event_days"] == 14 and g["n_overlapping_forward_windows"] == 2


# --- (a) find_support_resistance ------------------------------------------------------------------
@pytest.mark.parametrize("field", ["nearest_support_distance_pct", "nearest_resistance_distance_pct"])
def test_sr_distance_none_rejected_for_1_3_0_but_accepted_for_1_2_0(field):
    env = _env(SR)
    env["results"][field] = None
    with pytest.raises(ValueError, match=field):
        validate_envelope(env)
    old = _env(SR, "1.2.0")
    old["results"][field] = None
    validate_envelope(old)


def test_sr_distance_may_be_none_when_the_level_is_none():
    env = _env(SR)
    r = env["results"]
    r.update(nearest_support=None, nearest_support_distance_pct=None,
             levels=[lv for lv in r["levels"] if lv["type"] != "SUPPORT"])
    validate_envelope(env)


def test_sr_distance_requires_a_level_and_must_match_the_formula():
    env = _env(SR)
    env["results"].update(nearest_support=None)
    with pytest.raises(ValueError, match="nearest_support"):
        validate_envelope(env)  # seviye yok ama mesafe dolu
    env = _env(SR)
    env["results"]["nearest_support_distance_pct"] = 5.0  # (300-290)/300*100 = 3.3333
    with pytest.raises(ValueError, match="nearest_support_distance_pct"):
        validate_envelope(env)
    env = _env(SR)
    env["results"]["nearest_resistance_distance_pct"] = 6.0
    with pytest.raises(ValueError, match="nearest_resistance_distance_pct"):
        validate_envelope(env)


# --- (b) run_backtest.last_exit_date --------------------------------------------------------------
def test_backtest_last_exit_date_required_when_there_are_trades_for_1_3_0():
    env = _env(BT)
    env["results"]["last_exit_date"] = None
    with pytest.raises(ValueError, match="last_exit_date"):
        validate_envelope(env)
    old = _env(BT, "1.2.0")
    old["results"].pop("last_exit_date", None)
    validate_envelope(old)


def test_backtest_last_exit_date_none_is_fine_without_trades():
    env = _env(BT)
    r = env["results"]
    r.update(last_exit_date=None, n_winning_trades=0, n_losing_trades=0, n_signals=0, trade_log=[])
    r["strategy_net"]["n_trades"] = 0
    validate_envelope(env)


def test_backtest_last_exit_date_must_cover_the_trade_log():
    env = _env(BT)
    env["results"]["last_exit_date"] = "2026-03-09"  # trade_log'daki çıkış 2026-03-10
    with pytest.raises(ValueError, match="last_exit_date"):
        validate_envelope(env)


def test_backtest_last_exit_date_after_as_of_is_a_look_ahead():
    env = _env(BT)
    env["results"]["last_exit_date"] = "2026-09-11"
    with pytest.raises(ValueError, match="look-ahead"):
        validate_envelope(env)


def test_max_result_date_uses_last_exit_date_even_when_trade_log_is_truncated():
    env = _env(BT)
    r = env["results"]
    r.update(trade_log=[], trade_log_truncated=True, last_exit_date="2026-09-04")
    assert REG.max_result_date(r) == date(2026, 9, 4)  # period.end 2026-09-10 geçmiş-only anahtar değil
    validate_envelope(env)


# --- (c) detect_reversal_events grup alanları -----------------------------------------------------
@pytest.mark.parametrize("field", ["n_raw_event_days", "n_overlapping_forward_windows"])
def test_reversal_group_fields_required_for_1_3_0_but_optional_for_1_2_0(field):
    env = _env(REV)
    env["results"]["groups"][0][field] = None
    with pytest.raises(ValueError, match=field):
        validate_envelope(env)
    old = _env(REV, "1.2.0")
    old["results"]["groups"][0][field] = None
    validate_envelope(old)


def test_reversal_group_new_fields_are_non_negative_ints():
    env = _env(REV)
    env["results"]["groups"][0]["n_raw_event_days"] = -1
    with pytest.raises(ValueError):
        validate_envelope(env)
    env = _env(REV)
    env["results"]["groups"][0]["n_overlapping_forward_windows"] = -1
    with pytest.raises(ValueError):
        validate_envelope(env)
