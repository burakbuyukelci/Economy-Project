"""Sözleşme testleri: schemas/ iki bilgisayar arasındaki ortak anlaşmadır; bu testler bozulursa
sözleşme değişmiş demektir ve insan onayı gerekir."""
from __future__ import annotations

import copy
import re

import pytest
from pydantic import ValidationError

from config.universe import load_universe
from schemas import (
    SCHEMA_VERSION, TOOL_REGISTRY, AllowedAction, GateStatus, ToolName, ToolStatus,
    make_warning, validate_envelope, validate_params,
)
from schemas.enums import PeerGroup, WarningCode
from schemas.examples import EXAMPLE_AS_OF, example_envelope, example_error_envelope, example_params
from schemas.hashing import compute_input_hash

ALL_TOOLS = list(ToolName)


def test_fifteen_tools_registered():
    assert len(ALL_TOOLS) == 15
    assert set(TOOL_REGISTRY) == set(ALL_TOOLS)


def test_schema_version_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", SCHEMA_VERSION)


def test_allowed_action_enum_matches_claude_md():
    assert {a.value for a in AllowedAction} == {
        "HOLD", "WATCH", "INVESTIGATE", "POTENTIAL_CATCH_UP_CANDIDATE", "TECHNICAL_REVERSAL_CANDIDATE",
        "FUNDAMENTAL_IMPROVEMENT_CANDIDATE", "REJECT_SIGNAL", "ANALYSIS_UNSAFE"}


def test_gate_status_enum_matches_claude_md():
    assert {g.value for g in GateStatus} == {"PASS", "PASS_WITH_WARNINGS", "INVESTIGATE", "ANALYSIS_UNSAFE", "HARD_BLOCK"}


def test_no_buy_sell_in_action_enum():
    assert not {"BUY", "SELL"} & {a.value for a in AllowedAction}


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_as_of_is_required_in_every_params_model(tool):
    model = TOOL_REGISTRY[tool].params_model
    assert "as_of" in model.model_fields
    assert model.model_fields["as_of"].is_required()


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_params_without_as_of_rejected(tool):
    raw = example_params(tool)
    raw.pop("as_of")
    with pytest.raises(ValidationError):
        validate_params(tool, raw)


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_params_reject_unknown_field(tool):
    raw = example_params(tool)
    raw["bogus_field"] = 1
    with pytest.raises(ValidationError):
        validate_params(tool, raw)


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_example_envelope_validates(tool):
    env = validate_envelope(example_envelope(tool))
    assert env.tool == tool and env.status == ToolStatus.OK
    assert str(env.as_of) == EXAMPLE_AS_OF


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_example_error_envelope_validates(tool):
    env = validate_envelope(example_error_envelope(tool))
    assert env.status == ToolStatus.ERROR and env.results is None and env.error is not None


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_input_hash_is_deterministic_64_hex(tool):
    env = example_envelope(tool)
    assert re.fullmatch(r"[0-9a-f]{64}", env["input_hash"])
    assert env["input_hash"] == compute_input_hash(tool, env["params"], env["data_version"])
    assert env["input_hash"] == example_envelope(tool)["input_hash"]


def test_input_hash_changes_with_params_and_data_version():
    env = example_envelope(ToolName.GET_STOCK_HISTORY)
    h0 = env["input_hash"]
    p2 = {**env["params"], "ticker": "ASELS"}
    assert compute_input_hash("get_stock_history", p2, env["data_version"]) != h0
    assert compute_input_hash("get_stock_history", env["params"], "snap_2026-11-21_v1") != h0


def test_list_params_normalized_for_stable_hash():
    a = validate_params(ToolName.DETECT_REVERSAL_EVENTS,
                        {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "as_of": "2026-09-10",
                         "forward_horizons": [10, 1, 5, 3, 3]}).model_dump(mode="json")
    b = validate_params(ToolName.DETECT_REVERSAL_EVENTS,
                        {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "as_of": "2026-09-10",
                         "forward_horizons": [1, 3, 5, 10]}).model_dump(mode="json")
    assert a == b


def test_envelope_as_of_must_equal_params_as_of():
    env = example_envelope(ToolName.GET_STOCK_HISTORY)
    env["as_of"] = "2026-09-09"
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_envelope_rejects_results_dates_after_as_of():
    env = example_envelope(ToolName.GET_STOCK_HISTORY)
    env["results"]["rows"][0]["date"] = "2026-09-11"
    env["results"]["last_date"] = "2026-09-11"
    with pytest.raises(ValueError, match="look-ahead"):
        validate_envelope(env)


def test_status_ok_requires_results_and_error_requires_error():
    env = example_envelope(ToolName.GET_STOCK_HISTORY)
    env["results"] = None
    with pytest.raises(ValidationError):
        validate_envelope(env)
    env2 = example_error_envelope(ToolName.GET_STOCK_HISTORY)
    env2["error"] = None
    with pytest.raises(ValidationError):
        validate_envelope(env2)


def test_warning_format_and_codes_enforced():
    env = example_envelope(ToolName.GET_STOCK_HISTORY)
    env["warnings"] = [make_warning(WarningCode.FEW_EVENTS, "n=5 < 20")]
    validate_envelope(env)
    for bad in ["serbest metin uyarı", "NOT_A_CODE: x"]:
        env["warnings"] = [bad]
        with pytest.raises(ValidationError):
            validate_envelope(env)


def test_peer_group_enum_matches_universe_csv():
    assert {p.value for p in PeerGroup} == set(load_universe()["peer_group"])


def test_rank_param_is_named_sector_and_enum():
    f = TOOL_REGISTRY[ToolName.RANK_SECTOR_RELATIVE_STRENGTH].params_model.model_fields
    assert "sector" in f
    with pytest.raises(ValidationError):
        validate_params(ToolName.RANK_SECTOR_RELATIVE_STRENGTH, {"sector": "Retail Trade", "as_of": "2026-09-10"})


def test_reversal_has_touch_mode_and_cost_params():
    p = validate_params(ToolName.DETECT_REVERSAL_EVENTS,
                        {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "as_of": "2026-09-10"})
    assert p.touch_mode.value == "close"
    assert p.transaction_cost_bps == 20.0 and p.slippage_bps >= 0
    with pytest.raises(ValidationError):
        validate_params(ToolName.DETECT_REVERSAL_EVENTS,
                        {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "as_of": "2026-09-10",
                         "touch_mode": "open"})


def test_backtest_signal_lag_zero_rejected():
    raw = example_params(ToolName.RUN_BACKTEST)
    raw["strategy"]["signal_lag_days"] = 0
    with pytest.raises(ValidationError):
        validate_params(ToolName.RUN_BACKTEST, raw)


def test_trade_must_enter_after_signal():
    env = example_envelope(ToolName.RUN_BACKTEST)
    env["results"]["trade_log"][0]["entry_date"] = env["results"]["trade_log"][0]["signal_date"]
    with pytest.raises(ValidationError):
        validate_envelope(env)


def test_weekday_pattern_requires_outcome_day_and_disjoint_periods():
    raw = example_params(ToolName.TEST_WEEKDAY_PATTERN)
    bad = copy.deepcopy(raw)
    bad["pattern"] = [{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"}]
    with pytest.raises(ValidationError):
        validate_params(ToolName.TEST_WEEKDAY_PATTERN, bad)
    bad2 = copy.deepcopy(raw)
    bad2["out_of_sample_start"] = bad2["in_sample_end"]
    with pytest.raises(ValidationError):
        validate_params(ToolName.TEST_WEEKDAY_PATTERN, bad2)


def test_weekday_counts_consistent():
    env = example_envelope(ToolName.TEST_WEEKDAY_PATTERN)
    env["results"]["in_sample"]["n_weeks_complete"] = 5
    with pytest.raises(ValidationError):
        validate_envelope(env)


def test_horizon_stats_counts_consistent():
    env = example_envelope(ToolName.DETECT_REVERSAL_EVENTS)
    env["results"]["groups"][0]["per_horizon"][0]["full"]["n_success"] = 9
    with pytest.raises(ValidationError):
        validate_envelope(env)


# --- Ufku dolmamış pencereler: false-positive olmamalı, sızıntı yakalanmalı --------------------
def _fund_reaction(env):
    return env["results"]["quarters"][0]["reactions"][0]


def test_incomplete_reaction_with_null_date_passes():
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    r = _fund_reaction(env)
    assert r["complete"] is False and r["window_end_date"] is None  # örnek zaten böyle
    validate_envelope(env)


def test_incomplete_reaction_must_not_carry_date_or_returns():
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    _fund_reaction(env)["window_end_date"] = "2026-10-08"  # as_of'tan sonra
    with pytest.raises(ValidationError):
        validate_envelope(env)
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    _fund_reaction(env)["stock_return_pct"] = 1.0
    with pytest.raises(ValidationError):
        validate_envelope(env)


def test_complete_reaction_with_date_after_as_of_is_caught_as_lookahead():
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    r = _fund_reaction(env)
    r.update(complete=True, window_end_date="2026-09-11", stock_return_pct=1.0)
    with pytest.raises(ValueError, match="look-ahead"):
        validate_envelope(env)


def test_complete_reaction_on_or_before_as_of_passes():
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    r = _fund_reaction(env)
    r.update(complete=True, window_end_date="2026-09-10", stock_return_pct=1.0)  # as_of DAHİL
    validate_envelope(env)


def test_complete_reaction_requires_date_and_return():
    env = example_envelope(ToolName.CALCULATE_FUNDAMENTAL_CHANGE)
    _fund_reaction(env).update(complete=True)  # tarih/getiri None kaldı
    with pytest.raises(ValidationError):
        validate_envelope(env)


def _forward_returns(env):
    return env["results"]["groups"][0]["events"][0]["forward_returns"]


def test_incomplete_forward_return_is_null_in_example_and_passes():
    env = example_envelope(ToolName.DETECT_REVERSAL_EVENTS)
    fr = _forward_returns(env)
    assert any(not f["complete"] and f["return_pct"] is None for f in fr)
    validate_envelope(env)


def test_incomplete_forward_return_must_not_have_value():
    for field, value in [("return_pct", 1.0), ("reversal_success", True), ("reversal_strength_pct", 2.0)]:
        env = example_envelope(ToolName.DETECT_REVERSAL_EVENTS)
        f = next(x for x in _forward_returns(env) if not x["complete"])
        f[field] = value
        with pytest.raises(ValidationError):
            validate_envelope(env)


def test_complete_forward_return_requires_value():
    env = example_envelope(ToolName.DETECT_REVERSAL_EVENTS)
    f = next(x for x in _forward_returns(env) if x["complete"])
    f["return_pct"] = None
    with pytest.raises(ValidationError):
        validate_envelope(env)


# --- stability_verdict tutarlılığı --------------------------------------------------------------
def test_verdict_codes_must_match_verdict():
    base = example_envelope(ToolName.TEST_WEEKDAY_PATTERN)
    validate_envelope(base)  # INSUFFICIENT_DATA + IS_TOO_FEW
    cases = [
        ("STABLE", ["IS_TOO_FEW"]),                     # STABLE kod içeremez
        ("INSUFFICIENT_DATA", []),                      # kodsuz olamaz
        ("INSUFFICIENT_DATA", ["IS_NOT_SIGNIFICANT"]),  # yanlış kod
        ("UNSTABLE", []),                               # nedensiz olamaz
        ("UNSTABLE", ["IS_TOO_FEW"]),                   # *_TOO_FEW UNSTABLE'a ait değil
    ]
    for verdict_, codes in cases:
        env = copy.deepcopy(base)
        env["results"]["stability_verdict"] = verdict_
        env["results"]["verdict_codes"] = codes
        env["results"]["verdict_reason"] = " ".join(codes) or "x"
        with pytest.raises(ValidationError):
            validate_envelope(env)


def test_verdict_reason_must_mention_every_code():
    env = example_envelope(ToolName.TEST_WEEKDAY_PATTERN)
    env["results"]["verdict_reason"] = "açıklama kodsuz"
    with pytest.raises(ValidationError):
        validate_envelope(env)


def test_weekday_numeric_fields_required_when_trigger_weeks_positive():
    env = example_envelope(ToolName.TEST_WEEKDAY_PATTERN)
    env["results"]["in_sample"]["outcome_mean_return_pct"] = None
    with pytest.raises(ValidationError):
        validate_envelope(env)


def test_oos_too_small_warning_code_exists():
    assert "OOS_TOO_SMALL" in {c.value for c in WarningCode}


def test_gate_consistency_rules():
    env = example_envelope(ToolName.CHECK_DATA_QUALITY)
    # Kural yalnız şunları bağlar: hard_block varsa HARD_BLOCK; hiç sorun yoksa PASS.
    # Soft uyarılı durumda hangi durumun seçileceği (PASS_WITH_WARNINGS/INVESTIGATE/...) tool mantığıdır.
    validate_envelope(env)
    env["results"]["hard_blocks"] = [{"code": "LOOKAHEAD_SIGNAL", "severity": "HARD", "message": "x"}]
    with pytest.raises(ValidationError):
        validate_envelope(env)  # hard_block var ama gate_status PASS
    env["results"]["gate_status"] = "HARD_BLOCK"
    validate_envelope(env)


def test_no_pct_field_named_without_suffix_for_returns():
    """Birim kuralı: getiri/oran alanları _pct veya _pp ile bitmeli (sayı doğrulayıcı için)."""
    import schemas.results as R
    bad = []
    for name in dir(R):
        cls = getattr(R, name)
        if isinstance(cls, type) and hasattr(cls, "model_fields") and cls.__module__ == R.__name__:
            for f in cls.model_fields:
                if f == "sharpe_diff":  # Sharpe birimsiz bir oran; yüzde değil
                    continue
                if re.search(r"(return|rate|drawdown|diff)$", f) and not f.endswith(("_pct", "_pp")):
                    bad.append(f"{name}.{f}")
    assert not bad, bad
