"""Şema 1.2.0 sözleşme testleri (docs/schema_1_2_0_plan.md).

Kapsam: (a) BundleItem alanları, (b) rank per_ticker/ham sayı/cooldown/sonuç ölçütü, (c) indicators hafif varsayılanlar,
(d) TickerQuality açıklamaları, (f) issue_counts, sürüm koşullu zorunluluk, 1.1.0 zarflarının geçerliliği, max_result_date.
"""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from schemas import SCHEMA_VERSION, ToolName, validate_envelope
from schemas import registry as REG
from schemas.examples import example_envelope, example_params
from schemas.params import BundleItem, CalculateIndicatorsParams, CheckDataQualityParams, StrategySpec
from schemas.results import TickerQuality

FIXTURES = Path(__file__).parent / "fixtures" / "envelopes_1_1_0"
FIXTURE_FILES = sorted(FIXTURES.glob("*.json"))
RANK, IND, DQ = (ToolName.RANK_SECTOR_RELATIVE_STRENGTH, ToolName.CALCULATE_INDICATORS, ToolName.CHECK_DATA_QUALITY)


def _env(tool: ToolName, version: str = "1.2.0") -> dict:
    env = copy.deepcopy(example_envelope(tool))
    env["schema_version"] = version
    return env


def _indicators_full() -> dict:
    from schemas import examples
    return copy.deepcopy(examples.example_envelope_indicators_full())


# --- sürüm ----------------------------------------------------------------------------------------
def test_schema_version_is_1_2_0():
    assert SCHEMA_VERSION == "1.2.0"


# --- 1.1.0 zarfları geçerli kalır (dondurulmuş fixture'lar) ----------------------------------------
def test_fixture_set_is_not_empty_and_covers_all_tools():
    names = {p.stem for p in FIXTURE_FILES}
    assert {t.value for t in ToolName} <= names and "check_data_quality_with_bundle" in names


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.stem)
def test_frozen_1_1_0_envelopes_still_validate(path):
    env = json.loads(path.read_text(encoding="utf-8"))
    assert env["schema_version"] == "1.1.0"
    validate_envelope(env)


def test_frozen_1_1_0_indicators_envelope_reads_as_meta_included():
    env = json.loads((FIXTURES / "calculate_indicators.json").read_text(encoding="utf-8"))
    res = validate_envelope(env).results
    assert res["columns"] and res.get("columns_meta_included", True) is True


# --- sürüm koşullu zorunluluk ---------------------------------------------------------------------
REQUIRED = [
    (RANK, "n_raw_laggard_observations"), (RANK, "cooldown_days"), (RANK, "outcome_benchmark_definition"),
    (IND, "invalid_columns_at_as_of"), (DQ, "issue_counts"),
]


@pytest.mark.parametrize("tool,field", REQUIRED)
def test_new_field_none_is_rejected_for_1_2_0_but_accepted_for_1_1_0(tool, field):
    env = _env(tool)
    env["results"][field] = None
    with pytest.raises(ValueError, match=field):
        validate_envelope(env)
    old = _env(tool, "1.1.0")
    old["results"][field] = None
    validate_envelope(old)


def test_rank_per_ticker_empty_rejected_for_1_2_0_group_of_two_or_more():
    env = _env(RANK)
    env["results"]["per_ticker"] = []
    with pytest.raises(ValueError, match="per_ticker"):
        validate_envelope(env)
    old = _env(RANK, "1.1.0")
    old["results"]["per_ticker"] = []
    validate_envelope(old)


def test_rank_solo_group_is_exempt_from_required_new_fields():
    env = _env(RANK)
    r = env["results"]
    r.update(peer_group_size=1, insufficient_peers=True, sector_median_return_pct=None, sector_median_vs_xu100_pp=None,
             sector_strength=None, historical_catch_up=[], per_ticker=[], n_raw_laggard_observations=None,
             cooldown_days=None, outcome_benchmark_definition=None)
    r["benchmark_definition"]["members"] = ["BIMAS"]
    r["ranking"] = [{"rank": 1, "ticker": "BIMAS", "return_pct": 15.0, "lag_score_pp": 0.0, "return_vs_xu100_pp": 11.0,
                     "is_laggard": False, "is_leader": False}]
    validate_envelope(env)


# --- (b) rank: per_ticker bütünlüğü ---------------------------------------------------------------
def test_rank_example_has_new_fields_and_validates():
    res = validate_envelope(_env(RANK)).results
    assert res["cooldown_days"] >= 1 and res["n_raw_laggard_observations"] >= 0
    assert {t["ticker"] for t in res["per_ticker"]} == {r["ticker"] for r in res["ranking"]}
    o = res["outcome_benchmark_definition"]
    assert o["type"] == "peer_median" and o["includes_subject_stock"] is False
    assert res["benchmark_definition"]["includes_subject_stock"] is True


def _mut_rank(fn):
    env = _env(RANK)
    fn(env["results"])
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_rank_per_ticker_raw_sum_must_equal_total():
    _mut_rank(lambda r: r["per_ticker"][0].__setitem__("n_raw_laggard_observations",
                                                        r["per_ticker"][0]["n_raw_laggard_observations"] + 1))


def test_rank_per_ticker_blocks_must_sum_to_pooled_block():
    def f(r):
        full = r["per_ticker"][0]["per_horizon"][0]["block"]["full"]
        full["n_success"] += 1
        full["n_false_positive"] -= 1  # tek hissede tutarlı, ama Σ havuzdakiyle eşit değil
    _mut_rank(f)


def test_rank_per_ticker_independent_events_equals_complete_plus_excluded():
    _mut_rank(lambda r: r["per_ticker"][0].__setitem__("n_independent_events", r["per_ticker"][0]["n_independent_events"] + 1))


def test_rank_per_ticker_excluded_equals_longest_horizon_block():
    _mut_rank(lambda r: r["per_ticker"][1].__setitem__("n_excluded_incomplete_horizon", 5))


def test_rank_per_ticker_independent_cannot_exceed_raw():
    def f(r):
        t = r["per_ticker"][0]
        t["n_raw_laggard_observations"] = 1
        r["n_raw_laggard_observations"] -= 11  # toplam tutarlı kalsın (12 -> 1)
    _mut_rank(f)


def test_rank_per_ticker_mirror_fields_must_match_ranking():
    _mut_rank(lambda r: r["per_ticker"][0].__setitem__("lag_score_pp", 99.0))
    _mut_rank(lambda r: r["per_ticker"][0].__setitem__("is_laggard", not r["per_ticker"][0]["is_laggard"]))


def test_rank_per_ticker_must_not_carry_in_or_out_of_sample():
    _mut_rank(lambda r: r["per_ticker"][0]["per_horizon"][0]["block"].__setitem__(
        "in_sample", copy.deepcopy(r["historical_catch_up"][0]["block"]["in_sample"])))


def test_rank_per_ticker_horizons_must_match_pooled_horizons():
    _mut_rank(lambda r: r["per_ticker"][0]["per_horizon"][0]["block"].__setitem__("horizon", 10))


def test_rank_per_ticker_tickers_unique_and_in_ranking():
    _mut_rank(lambda r: r["per_ticker"][1].__setitem__("ticker", r["per_ticker"][0]["ticker"]))
    _mut_rank(lambda r: r["per_ticker"][1].__setitem__("ticker", "THYAO"))


def test_rank_cooldown_must_be_positive():
    _mut_rank(lambda r: r.__setitem__("cooldown_days", 0))


# --- (a) BundleItem -------------------------------------------------------------------------------
_ITEM = {"tool": "run_backtest", "as_of": "2026-09-10", "data_version": "snap_2026-11-20_v2", "input_hash": "a" * 64,
         "n_events": 22, "n_excluded_incomplete_horizon": 1}


def test_bundle_item_new_fields_default_to_none_and_old_items_validate():
    b = BundleItem.model_validate(_ITEM)
    assert b.signal_lag_days_applied is None and b.max_result_date is None


def test_bundle_item_accepts_zero_lag_so_the_gate_can_block_it():
    assert BundleItem.model_validate({**_ITEM, "signal_lag_days_applied": 0}).signal_lag_days_applied == 0
    with pytest.raises(ValidationError):
        StrategySpec.model_validate({"variant": "B", "signal_type": "CATCH_UP", "signal_lag_days": 0})


def test_bundle_item_max_result_date_may_exceed_as_of():
    b = BundleItem.model_validate({**_ITEM, "max_result_date": "2026-09-11"})
    assert b.max_result_date == date(2026, 9, 11)  # ihlali kapı yakalar; şema reddetmez


def test_bundle_item_rejects_unknown_field_and_dump_has_new_keys():
    with pytest.raises(ValidationError):
        BundleItem.model_validate({**_ITEM, "bogus": 1})
    p = CheckDataQualityParams.model_validate({"as_of": "2026-09-10", "tickers": ["THYAO"], "end": "2026-09-10",
                                               "analysis_bundle": [_ITEM]}).model_dump(mode="json")
    assert p["analysis_bundle"][0]["signal_lag_days_applied"] is None and p["analysis_bundle"][0]["max_result_date"] is None


# --- (c) calculate_indicators ---------------------------------------------------------------------
def test_indicators_params_light_defaults():
    p = CalculateIndicatorsParams.model_validate(example_params(IND))
    assert p.last_n_rows == 0 and p.include_columns_meta is False and p.value_columns is None


def test_indicators_value_columns_normalized_and_nonempty():
    raw = {**example_params(IND), "value_columns": ["SMA_50", "RSI_14", "SMA_50"]}
    assert CalculateIndicatorsParams.model_validate(raw).value_columns == ["RSI_14", "SMA_50"]
    with pytest.raises(ValidationError):
        CalculateIndicatorsParams.model_validate({**example_params(IND), "value_columns": []})
    with pytest.raises(ValidationError):
        CalculateIndicatorsParams.model_validate({**example_params(IND), "value_columns": ["rsi 14"]})


def test_indicators_light_example_has_no_columns_but_names_invalid_ones():
    res = validate_envelope(_env(IND)).results
    assert res["columns_meta_included"] is False and res["columns"] == []
    assert res["invalid_columns_at_as_of"] == [] and res["recent_rows"] == []


def test_indicators_full_example_keeps_1_1_0_rules():
    env = _indicators_full()
    res = validate_envelope(env).results
    assert res["columns_meta_included"] is True and res["columns"] and res["recent_rows"]
    assert res["invalid_columns_at_as_of"] == []
    env["results"]["latest"]["values"]["EKSTRA_1"] = 1.0
    with pytest.raises(ValueError, match="columns"):
        validate_envelope(env)


def test_indicators_meta_off_requires_empty_columns():
    env = _env(IND)
    env["results"]["columns"] = _indicators_full()["results"]["columns"]
    with pytest.raises(ValueError, match="columns"):
        validate_envelope(env)


def test_indicators_invalid_columns_must_match_latest_none_values():
    env = _env(IND)
    env["results"]["latest"]["values"]["RSI_14"] = None
    with pytest.raises(ValueError, match="invalid_columns_at_as_of"):
        validate_envelope(env)  # liste [] kaldı ama değer None
    env["results"]["invalid_columns_at_as_of"] = ["RSI_14"]
    validate_envelope(env)
    env["results"]["invalid_columns_at_as_of"] = ["RSI_14", "NOPE_1"]
    with pytest.raises(ValueError, match="invalid_columns_at_as_of"):
        validate_envelope(env)


def test_indicators_rows_must_share_value_keys_when_meta_off():
    env = _env(IND)
    env["results"]["recent_rows"] = [{"date": "2026-09-09", "close": 1.0, "values": {"OTHER_1": 1.0}, "states": {}}]
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_indicators_meta_on_invalid_columns_must_match_flags():
    env = _indicators_full()
    env["results"]["latest"]["values"]["RSI_14"] = None
    env["results"]["columns"][0]["valid_at_as_of"] = False
    with pytest.raises(ValueError, match="invalid_columns_at_as_of"):
        validate_envelope(env)  # [] kaldı
    env["results"]["invalid_columns_at_as_of"] = ["RSI_14"]
    validate_envelope(env)


# --- (d) TickerQuality açıklamaları --------------------------------------------------------------
def test_ticker_quality_descriptions_match_tool_behaviour():
    f = TickerQuality.model_fields
    assert "PRICE_JUMP_TOLERANCE_PP" in f["n_price_jumps_over_limit"].description
    assert "classify_price_jumps" in f["n_price_jumps_over_limit"].description
    d = f["last_data_age_days"].description
    assert "son satır" in d and "pencere" in d


# --- (f) issue_counts ----------------------------------------------------------------------------
def test_issue_counts_example_matches_lists():
    res = validate_envelope(_env(DQ)).results
    assert res["issue_counts"] == {"PRICE_JUMP_OVER_LIMIT": 1}


def _mut_dq(fn):
    env = _env(DQ)
    fn(env["results"])
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_issue_counts_wrong_total_zero_entry_or_wrong_code_rejected():
    _mut_dq(lambda r: r.__setitem__("issue_counts", {}))
    _mut_dq(lambda r: r.__setitem__("issue_counts", {"PRICE_JUMP_OVER_LIMIT": 1, "STALE_DATA": 0}))
    _mut_dq(lambda r: r.__setitem__("issue_counts", {"STALE_DATA": 1}))
    _mut_dq(lambda r: r.__setitem__("issue_counts", {"PRICE_JUMP_OVER_LIMIT": 2}))
    _mut_dq(lambda r: r.__setitem__("issue_counts", {"NOT_A_CODE": 1}))


def test_issue_counts_with_hard_and_soft_issues():
    env = _env(DQ)
    r = env["results"]
    r["hard_blocks"] = [{"code": "LOOKAHEAD_SIGNAL", "severity": "HARD", "message": "x"}]
    r["gate_status"] = "HARD_BLOCK"
    r["issue_counts"] = {"LOOKAHEAD_SIGNAL": 1, "PRICE_JUMP_OVER_LIMIT": 1}
    validate_envelope(env)


def test_issue_counts_empty_dict_is_valid_when_no_issues():
    env = _env(DQ)
    r = env["results"]
    r.update(soft_warnings=[], gate_status="PASS", issue_counts={})
    validate_envelope(env)


# --- D5: max_result_date yardımcısı ---------------------------------------------------------------
def test_max_result_date_scans_dated_result_keys():
    env = example_envelope(ToolName.RUN_BACKTEST)
    assert REG.max_result_date(env["results"]) == date(2026, 3, 10)  # trade_log.exit_date
    assert REG.max_result_date(example_envelope(ToolName.GET_STOCK_HISTORY)["results"]) == date(2026, 9, 10)


def test_max_result_date_none_when_no_dates():
    assert REG.max_result_date({"a": 1, "requested_end": "2030-01-01"}) is None  # requested_end geçmiş-only anahtar değil
    assert REG.max_result_date({}) is None


def test_max_result_date_is_pure_and_deterministic():
    res = example_envelope(ToolName.DETECT_REVERSAL_EVENTS)["results"]
    before = copy.deepcopy(res)
    assert REG.max_result_date(res) == REG.max_result_date(res) == date(2026, 9, 10)
    assert res == before


# --- ortak yardımcı: example_rank_with_per_ticker (harness sentetik zarfları için) -----------------------------------
def _helper(results, subject, **kw):
    from schemas import examples
    return examples.example_rank_with_per_ticker(results, subject, **kw)


def _rank_results_with_blocks(horizons=(5, 10, 20), n=40):
    """Harness policy_builders'a benzer: örnek zarf, ranking + özel havuz blokları (ufuk başına aynı n), per_ticker'sız."""
    res = copy.deepcopy(example_envelope(RANK)["results"])
    base = res["historical_catch_up"][0]["block"]
    blocks = []
    for h in horizons:
        full = {**base["full"], "n_events_complete": n - 1, "n_excluded_incomplete_horizon": 1,
                "n_success": 20, "n_false_positive": n - 1 - 20}
        blocks.append({"block": {**copy.deepcopy(base), "horizon": h, "full": full}, "median_catch_up_size_pp": 2.0})
    res["historical_catch_up"] = blocks
    res["ranking"][2]["ticker"] = "PETKM"
    res["benchmark_definition"]["members"] = ["BIMAS", "MGROS", "PETKM"]
    for k in ("per_ticker", "n_raw_laggard_observations", "cooldown_days", "outcome_benchmark_definition"):
        res.pop(k)
    return res


def _as_envelope(res):
    env = _env(RANK)
    env["results"] = res
    return env


@pytest.mark.parametrize("subject", ["BIMAS", "MGROS", "PETKM"])
def test_helper_builds_valid_per_ticker_for_custom_pooled_blocks(subject):
    res = _helper(_rank_results_with_blocks(), subject)
    validate_envelope(_as_envelope(res))  # 1.2.0 damgalı: tüm şema kuralları + sürüm koşullu zorunluluk
    assert [t["ticker"] for t in res["per_ticker"]] == ["BIMAS", "MGROS", "PETKM"]
    me = next(t for t in res["per_ticker"] if t["ticker"] == subject)
    assert me["n_independent_events"] == 40 and me["n_excluded_incomplete_horizon"] == 1 and me["n_raw_laggard_observations"] == 40
    for t in res["per_ticker"]:
        if t["ticker"] != subject:
            assert (t["n_raw_laggard_observations"], t["n_independent_events"], t["n_excluded_incomplete_horizon"]) == (0, 0, 0)
            assert all(r["block"]["full"]["n_events_complete"] == 0 and r["block"]["full"].get("hit_rate_pct") is None
                       for r in t["per_horizon"])
    assert res["n_raw_laggard_observations"] == 40 and res["cooldown_days"] == 20


def test_helper_subject_carries_pooled_blocks_without_in_out_of_sample():
    src = _rank_results_with_blocks()
    res = _helper(src, "PETKM")
    me = next(t for t in res["per_ticker"] if t["ticker"] == "PETKM")
    for mine, pooled in zip(me["per_horizon"], src["historical_catch_up"]):
        assert mine["block"]["full"] == pooled["block"]["full"] and mine["block"]["baseline"] == pooled["block"]["baseline"]
        assert mine["block"]["in_sample"] is None and mine["block"]["out_of_sample"] is None
        assert mine["median_catch_up_size_pp"] == pooled["median_catch_up_size_pp"]


def test_helper_mirrors_come_from_ranking_and_outcome_definition_excludes_subject():
    src = _rank_results_with_blocks()
    res = _helper(src, "PETKM", cooldown_days=10, n_raw_subject=120)
    rank = {r["ticker"]: r for r in res["ranking"]}
    for t in res["per_ticker"]:
        assert (t["is_laggard"], t["lag_score_pp"]) == (rank[t["ticker"]]["is_laggard"], rank[t["ticker"]]["lag_score_pp"])
    assert res["cooldown_days"] == 10 and res["n_raw_laggard_observations"] == 120
    o = res["outcome_benchmark_definition"]
    assert o["includes_subject_stock"] is False and o["members"] == res["benchmark_definition"]["members"]
    assert res["benchmark_definition"]["includes_subject_stock"] is True
    validate_envelope(_as_envelope(res))


def test_helper_does_not_mutate_input_and_is_deterministic():
    src = _rank_results_with_blocks()
    before = copy.deepcopy(src)
    a, b = _helper(src, "PETKM"), _helper(src, "PETKM")
    assert src == before and a == b


def test_helper_works_on_the_default_example_too():
    res = _helper(example_envelope(RANK)["results"], "MAVI")
    validate_envelope(_as_envelope(res))
    assert next(t for t in res["per_ticker"] if t["ticker"] == "MAVI")["is_laggard"] is True


def test_helper_insufficient_group_gets_none_and_empty_and_validates():
    src = _rank_results_with_blocks()
    src.update(peer_group_size=1, insufficient_peers=True, historical_catch_up=[], sector_strength=None,
               sector_median_return_pct=None, sector_median_vs_xu100_pp=None)
    src["ranking"] = src["ranking"][:1]
    res = _helper(src, "BIMAS")
    assert (res["per_ticker"], res["n_raw_laggard_observations"], res["cooldown_days"], res["outcome_benchmark_definition"]) == (
        [], None, None, None)
    validate_envelope(_as_envelope(res))


def test_helper_rejects_unknown_subject_inconsistent_totals_and_small_raw():
    src = _rank_results_with_blocks()
    with pytest.raises(ValueError, match="ranking"):
        _helper(src, "THYAO")
    bad = copy.deepcopy(src)
    bad["historical_catch_up"][1]["block"]["full"]["n_excluded_incomplete_horizon"] = 3
    with pytest.raises(ValueError, match="ufuklar arasında"):
        _helper(bad, "PETKM")
    with pytest.raises(ValueError, match="n_raw_subject"):
        _helper(src, "PETKM", n_raw_subject=10)
    empty = copy.deepcopy(src)
    empty["historical_catch_up"] = []
    with pytest.raises(ValueError, match="boş"):
        _helper(empty, "PETKM")
