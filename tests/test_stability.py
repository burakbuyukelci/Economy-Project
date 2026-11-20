"""stability_verdict ve oos_degradation_flag kuralları (docs/data_dictionary.md §8-9)."""
from __future__ import annotations

import pytest

from schemas.common import HorizonStats
from schemas.enums import Direction, StabilityVerdict as V, VerdictCode as C
from schemas.examples import _wk
from schemas.results import WeekdayPeriodResult
from tools.stability import oos_degradation, weekday_stability_verdict


def period(n_trigger=20, diff=0.8, cost_adj=0.3, hit=60.0, p_adj=0.01) -> WeekdayPeriodResult:
    d = _wk("2024-01-01", "2025-12-31")
    d.update(n_weeks_total=100, n_excluded_holiday_weeks=0, n_excluded_incomplete_horizon=0, n_weeks_complete=100,
             n_trigger_weeks=n_trigger, n_occurrences=n_trigger // 2, n_false_positive=n_trigger - n_trigger // 2,
             outcome_mean_diff_vs_unconditional_pct=diff, cost_adjusted_outcome_mean_return_pct=cost_adj,
             hit_rate_pct=hit, p_value_adjusted=p_adj)
    return WeekdayPeriodResult.model_validate(d)


def verdict(is_, oos, direction=Direction.UP):
    return weekday_stability_verdict(is_, oos, direction, alpha=0.05)


# (i) IS n < eşik
def test_is_too_few_gives_insufficient_data():
    v, codes, reason = verdict(period(n_trigger=9), period(n_trigger=50))
    assert v == V.INSUFFICIENT_DATA and codes == [C.IS_TOO_FEW]
    assert "IS_TOO_FEW" in reason and "9" in reason and "10" in reason


def test_is_exactly_at_threshold_is_sufficient():
    v, codes, _ = verdict(period(n_trigger=10), period(n_trigger=5))
    assert v == V.STABLE and codes == []


# (ii) IS yeterli ama anlamlı değil -> UNSTABLE
def test_is_not_significant_is_unstable_even_if_oos_small():
    v, codes, reason = verdict(period(p_adj=0.2), period(n_trigger=1))
    assert v == V.UNSTABLE and codes == [C.IS_NOT_SIGNIFICANT]
    assert "0.2" in reason


def test_is_p_value_none_counts_as_not_significant():
    v, codes, _ = verdict(period(p_adj=None), period())
    assert v == V.UNSTABLE and C.IS_NOT_SIGNIFICANT in codes


# (iii) IS anlamlı, OOS n küçük -> INSUFFICIENT_DATA
def test_oos_too_few():
    v, codes, reason = verdict(period(), period(n_trigger=4))
    assert v == V.INSUFFICIENT_DATA and codes == [C.OOS_TOO_FEW]
    assert "4" in reason and "5" in reason


# (iv) b-e
def test_stable_when_all_conditions_hold():
    assert verdict(period(diff=0.8), period(n_trigger=8, diff=0.5, cost_adj=0.2, hit=55.0))[0] == V.STABLE


def test_sign_flip():
    v, codes, _ = verdict(period(diff=0.8), period(n_trigger=8, diff=-0.3))
    assert v == V.UNSTABLE and C.OOS_SIGN_FLIP in codes


def test_cost_adjusted_not_positive():
    v, codes, _ = verdict(period(), period(n_trigger=8, cost_adj=0.0))
    assert v == V.UNSTABLE and C.OOS_COST_ADJ_NOT_POSITIVE in codes


def test_hit_rate_too_low():
    v, codes, _ = verdict(period(), period(n_trigger=8, hit=40.0))
    assert v == V.UNSTABLE and C.OOS_HIT_RATE_TOO_LOW in codes


def test_effect_too_small_boundary():
    # IS 0.8, OOS 0.4 = tam yarı -> yeterli; 0.39 -> yetersiz
    assert verdict(period(diff=0.8), period(n_trigger=8, diff=0.4))[0] == V.STABLE
    v, codes, _ = verdict(period(diff=0.8), period(n_trigger=8, diff=0.39))
    assert v == V.UNSTABLE and C.OOS_EFFECT_TOO_SMALL in codes


def test_multiple_failures_all_reported_with_numbers():
    v, codes, reason = verdict(period(diff=0.8), period(n_trigger=8, diff=-0.3, cost_adj=-0.1, hit=30.0))
    assert v == V.UNSTABLE
    assert set(codes) == {C.OOS_SIGN_FLIP, C.OOS_COST_ADJ_NOT_POSITIVE, C.OOS_HIT_RATE_TOO_LOW}
    for c in codes:
        assert c.value in reason
    assert "-0.3" in reason and "30.0" in reason


def test_numeric_fields_stay_populated_regardless_of_verdict():
    # Verdict INSUFFICIENT_DATA olsa bile period sonuçları dolu kalır (araç alanları boşaltmaz).
    is_ = period(n_trigger=3)
    assert is_.outcome_mean_return_pct is not None and is_.p_value_raw is not None
    assert verdict(is_, period())[0] == V.INSUFFICIENT_DATA


# --- oos_degradation_flag -------------------------------------------------
def stats(n=10, hit=60.0, cost_adj=0.5):
    n_success = round(n * hit / 100)
    return HorizonStats(n_events_complete=n, n_excluded_incomplete_horizon=0, n_success=n_success,
                        n_false_positive=n - n_success, hit_rate_pct=hit,
                        false_positive_rate_pct=100 - hit, mean_return_pct=1.0, median_return_pct=0.8,
                        cost_adjusted_mean_return_pct=cost_adj)


def test_oos_small_gives_false_and_too_small():
    flag, too_small = oos_degradation(stats(), stats(n=4, hit=0.0, cost_adj=-5.0))
    assert flag is False and too_small is True


def test_oos_cost_adjusted_nonpositive_while_is_positive():
    assert oos_degradation(stats(cost_adj=0.5), stats(cost_adj=0.0)) == (True, False)
    assert oos_degradation(stats(cost_adj=0.5), stats(cost_adj=-0.2)) == (True, False)


def test_is_nonpositive_does_not_trigger_cost_rule():
    assert oos_degradation(stats(cost_adj=-0.1, hit=60.0), stats(cost_adj=-0.2, hit=60.0)) == (False, False)


def test_hit_rate_drop_strictly_more_than_15_points():
    assert oos_degradation(stats(hit=60.0), stats(hit=44.0)) == (True, False)   # düşüş 16
    assert oos_degradation(stats(hit=60.0), stats(hit=45.0)) == (False, False)  # düşüş tam 15 -> false


def test_no_degradation():
    assert oos_degradation(stats(), stats()) == (False, False)


def test_missing_is_or_oos_gives_none():
    assert oos_degradation(None, stats()) == (None, False)
    assert oos_degradation(stats(), None) == (None, False)


def test_none_metrics_do_not_crash():
    s_none = HorizonStats(n_events_complete=0, n_excluded_incomplete_horizon=2, n_success=0, n_false_positive=0)
    assert oos_degradation(stats(), s_none) == (False, True)
