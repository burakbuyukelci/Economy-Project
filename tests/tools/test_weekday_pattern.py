"""test_weekday_pattern aracı testleri.

(A) Saf yardımcı: permütasyon testi (elle bilinen sonuçlar, determinizm).
(B) Sentetik snapshot, ELLE hesaplanabilir haftalık senaryolar. Her haftanın (Pzt..Cum) günlük getirisi
    doğrudan yazılır; fiyat = kümülatif çarpım. Örüntü: MON-DOWN (TRIGGER) + THU-UP (OUTCOME).
    * Tetik haftasında Pzt -1, koşulsuz haftada Pzt +1; Perşembe değerleri senaryodan gelir.
    * "İYİ IS": 20 tetik (Per +3) + 20 koşulsuz (Per -0,5) -> tetik ort 3,0; hepsi ort 1,25; fark 1,75.
(C) Her karar dalı uçtan uca: IS_TOO_FEW, IS_NOT_SIGNIFICANT, OOS_TOO_FEW, STABLE ve (b)-(e) kodları.
(D) as_of sızıntısı, ufku dolmamış hafta, tatil/veri boşluğu, pencere sınırı, determinizm.
(E) Yön (DOWN çıktı), maliyet, Bonferroni, conditioning (look-ahead'siz), hata zarfları.
(F) Gerçek v2 snapshot (THYAO Soru 2 + bir başka hisse).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from schemas.results import TestWeekdayPatternResult
from scripts.download_prices import CANONICAL_COLUMNS
from tests.conftest import make_snapshot
from tools import test_weekday_pattern as tool

VERSION = "snap_2026-11-20_v2"
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")

FIRST_MONDAY = date(2024, 1, 1)
BASE_FRIDAY = pd.Timestamp("2023-12-29")  # ilk Pazartesi getirisi için baz kapanış


# =====================================================================================================
# (A) permütasyon testi
# =====================================================================================================
def test_permutation_known_small_case():
    """y=[1,0,0,0], tetik = ilk hafta: k=1 seçimde fark ancak o haftayı seçince 0,75 -> p ~ 1/4."""
    y = np.array([1.0, 0.0, 0.0, 0.0])
    p = tool.permutation_pvalue(y, np.array([True, False, False, False]))
    assert p == pytest.approx(0.25, abs=0.02)


def test_permutation_no_effect_gives_p_one():
    y = np.full(30, 0.7)
    trig = np.zeros(30, bool)
    trig[:10] = True
    assert tool.permutation_pvalue(y, trig) == 1.0


def test_permutation_strong_effect_hits_the_floor_and_is_deterministic():
    y = np.array([3.0] * 20 + [-0.5] * 20)
    trig = np.array([True] * 20 + [False] * 20)
    p = tool.permutation_pvalue(y, trig)
    assert p == pytest.approx(1 / (tool.N_PERMUTATIONS + 1))
    assert tool.permutation_pvalue(y, trig) == p


def test_permutation_no_trigger_is_none():
    assert tool.permutation_pvalue(np.array([1.0, 2.0]), np.array([False, False])) is None


# =====================================================================================================
# (B) sentetik snapshot yardımcıları
# =====================================================================================================
def _frame(ticker: str, closes, dates) -> pd.DataFrame:
    c = np.asarray(closes, float)
    return pd.DataFrame({"ticker": ticker, "date": dates, "open": c, "high": c, "low": c, "close": c, "adj_close": c,
                         "volume": 1000.0, "dividends": 0.0, "stock_splits": 0.0})[CANONICAL_COLUMNS]


def _series(weeks):
    rets = np.asarray(weeks, float).ravel() / 100.0
    closes = 100.0 * np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    dates = pd.bdate_range(BASE_FRIDAY, periods=len(closes))
    return closes, dates


def week(mon=0.0, thu=0.0, tue=0.0, wed=0.0, fri=0.0):
    return (mon, tue, wed, thu, fri)


class Scenario:
    """Tetik haftaları (Pzt `trig_mon`) önce, koşulsuz haftalar (Pzt `non_mon`) sonra; IS sonra OOS."""

    def __init__(self, is_trig_thu, is_non_thu, oos_trig_thu, oos_non_thu, trig_mon=-1.0, non_mon=1.0):
        mk = lambda thus, mon: [week(mon=mon, thu=t) for t in thus]  # noqa: E731
        self.is_weeks = mk(is_trig_thu, trig_mon) + mk(is_non_thu, non_mon)
        self.oos_weeks = mk(oos_trig_thu, trig_mon) + mk(oos_non_thu, non_mon)
        self.weeks = self.is_weeks + self.oos_weeks
        n_is, n_oos = len(self.is_weeks), len(self.oos_weeks)
        self.is_start = FIRST_MONDAY
        self.is_end = FIRST_MONDAY + timedelta(days=7 * (n_is - 1) + 4)          # son IS haftasının Cuması
        self.oos_start = self.is_end + timedelta(days=3)                        # sonraki Pazartesi
        self.oos_end = self.oos_start + timedelta(days=7 * (n_oos - 1) + 4)     # son OOS Cuması
        self.n_is, self.n_oos = n_is, n_oos

    def monday(self, i: int) -> date:
        return FIRST_MONDAY + timedelta(days=7 * i)


def build_root(root, sc: Scenario, index_weeks=None, drop=(), shock_after: date | None = None, ticker="THYAO"):
    closes, dates = _series(sc.weeks)
    xc, xd = _series(index_weeks if index_weeks is not None else [week()] * len(sc.weeks))
    closes, xc = closes.copy(), xc.copy()
    if shock_after is not None:  # as_of SONRASI satırlara aşırı değerler
        closes[dates > pd.Timestamp(shock_after)] *= 1e6
        xc[xd > pd.Timestamp(shock_after)] *= 1e6
    stocks, index = _frame(ticker, closes, dates), _frame("XU100", xc, xd).drop(columns=["ticker"])
    for dt in drop:  # hem hisse hem endeks: gerçek tatil gibi
        stocks = stocks[stocks["date"] != pd.Timestamp(dt)]
        index = index[index["date"] != pd.Timestamp(dt)]
    make_snapshot(root, stocks.reset_index(drop=True), index.reset_index(drop=True), version=VERSION)
    return root


PATTERN = [{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"},
           {"weekday": "THU", "direction": "UP", "role": "OUTCOME"}]


def call(root, sc: Scenario, **over):
    params = {"ticker": "THYAO", "pattern": PATTERN, "in_sample_start": sc.is_start.isoformat(),
              "in_sample_end": sc.is_end.isoformat(), "out_of_sample_start": sc.oos_start.isoformat(),
              "out_of_sample_end": sc.oos_end.isoformat(), "as_of": sc.oos_end.isoformat()}
    params.update(over)
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> TestWeekdayPatternResult:
    assert env["status"] == "OK", env.get("error")
    return TestWeekdayPatternResult.model_validate(env["results"])


def rep(v: float, n: int) -> list[float]:
    return [v] * n


GOOD_IS = dict(is_trig_thu=rep(3.0, 20), is_non_thu=rep(-0.5, 20))

# OOS varyantları (IS iyi: fark 1,75; (e) eşiği 0,5 x 1,75 = 0,875)
OOS_CASES = {
    "stable": (dict(oos_trig_thu=rep(2.0, 10), oos_non_thu=rep(-0.5, 10)), "STABLE", set()),
    # tetik haftasında Per -1, koşulsuzda +0,5: (b) işaret, (c) maliyet, (d) isabet bozulur; (e) değerlendirilmez
    "sign_flip": (dict(oos_trig_thu=rep(-1.0, 10), oos_non_thu=rep(0.5, 10)), "UNSTABLE",
                  {"OOS_SIGN_FLIP", "OOS_COST_ADJ_NOT_POSITIVE", "OOS_HIT_RATE_TOO_LOW"}),
    # ort 0,4 - 0,5 < 0; fark 0,4 - (-0,8) = 1,2 >= 0,875; isabet %100
    "cost": (dict(oos_trig_thu=rep(0.4, 10), oos_non_thu=rep(-2.0, 10)), "UNSTABLE", {"OOS_COST_ADJ_NOT_POSITIVE"}),
    # 4 isabet (+10), 6 ıska (-1): ort 3,4; fark 1,95; isabet %40
    "hit": (dict(oos_trig_thu=rep(10.0, 4) + rep(-1.0, 6), oos_non_thu=rep(-0.5, 10)), "UNSTABLE",
            {"OOS_HIT_RATE_TOO_LOW"}),
    # fark 1,0 - 0,75 = 0,25 < 0,875; ort - maliyet = 0,5 > 0; isabet %100
    "effect": (dict(oos_trig_thu=rep(1.0, 10), oos_non_thu=rep(0.5, 10)), "UNSTABLE", {"OOS_EFFECT_TOO_SMALL"}),
    # IS anlamlı ama OOS'ta yalnızca 3 tetik haftası (< 5)
    "oos_too_few": (dict(oos_trig_thu=rep(2.0, 3), oos_non_thu=rep(-0.5, 17)), "INSUFFICIENT_DATA", {"OOS_TOO_FEW"}),
}


@pytest.fixture(scope="module")
def stable_sc():
    return Scenario(**GOOD_IS, **OOS_CASES["stable"][0])


@pytest.fixture(scope="module")
def stable_root(tmp_path_factory, stable_sc):
    return build_root(tmp_path_factory.mktemp("wk_stable"), stable_sc)


# =====================================================================================================
# (B) elle hesap: STABLE senaryosu
# =====================================================================================================
def test_stable_scenario_hand_computed_numbers(stable_root, stable_sc):
    env = call(stable_root, stable_sc)
    validate_envelope(env)
    r = res(env)
    i, o = r.in_sample, r.out_of_sample
    assert (r.stability_verdict.value, r.verdict_codes) == ("STABLE", [])
    assert r.pattern_label == "MON-DOWN | THU-UP"
    # IS: 40 hafta, hepsi tam; 20 tetik, 20'sinde Per yükseldi
    assert (i.n_weeks_total, i.n_excluded_holiday_weeks, i.n_excluded_incomplete_horizon, i.n_weeks_complete) == (40, 0, 0, 40)
    assert (i.n_trigger_weeks, i.n_occurrences, i.n_false_positive) == (20, 20, 0)
    assert (i.occurrence_rate_pct, i.hit_rate_pct) == (50.0, 100.0)
    assert i.outcome_mean_return_pct == pytest.approx(3.0, abs=1e-3)
    assert i.outcome_median_return_pct == pytest.approx(3.0, abs=1e-3)
    assert i.unconditional_outcome_mean_return_pct == pytest.approx(1.25, abs=1e-3)
    assert i.outcome_mean_diff_vs_unconditional_pct == pytest.approx(1.75, abs=1e-3)
    assert i.cost_adjusted_outcome_mean_return_pct == pytest.approx(3.0 - 0.5, abs=1e-3)  # 2 x (20+5)/100 = 0,5
    # tesadüfi beklenti: 40 x P(Pzt düşüş)=0,5 x P(Per yükseliş)=0,5 = 10
    assert i.expected_occurrences_if_independent == pytest.approx(10.0, abs=1e-3)
    assert i.p_value_raw == pytest.approx(1 / 10001, abs=2e-6) and i.p_value_adjusted == i.p_value_raw
    assert i.t_stat is not None and i.t_stat > 5
    # OOS: 10 tetik / 20 hafta
    assert (o.n_weeks_total, o.n_trigger_weeks, o.n_occurrences) == (20, 10, 10)
    assert o.outcome_mean_diff_vs_unconditional_pct == pytest.approx(2.0 - 0.75, abs=1e-3)
    assert o.cost_adjusted_outcome_mean_return_pct == pytest.approx(1.5, abs=1e-3)
    assert env["n_events"] == 20 + 10 and env["n_excluded_incomplete_horizon"] == 0


def test_per_day_stats_and_unconditional_day_mean(stable_root, stable_sc):
    i = res(call(stable_root, stable_sc)).in_sample
    mon, thu = i.per_day
    assert (mon.weekday.value, mon.role.value, mon.expected_direction.value) == ("MON", "TRIGGER", "DOWN")
    assert (mon.n_obs, mon.direction_match_rate_pct, mon.mean_return_pct) == (40, 50.0, pytest.approx(0.0, abs=1e-3))
    assert (thu.weekday.value, thu.n_obs, thu.direction_match_rate_pct) == ("THU", 40, 50.0)
    assert thu.mean_return_pct == pytest.approx(1.25, abs=1e-3) and thu.median_return_pct == pytest.approx(1.25, abs=1e-3)
    # TÜM işlem günleri: 200 gün; Per toplamı 20*3 - 20*0,5 = 50 -> 0,25
    assert thu.unconditional_mean_return_pct == pytest.approx(0.25, abs=1e-3)
    assert mon.unconditional_mean_return_pct == pytest.approx(0.25, abs=1e-3)


def test_warnings_always_present(stable_root, stable_sc):
    w = " | ".join(call(stable_root, stable_sc)["warnings"])
    for code in ("HISTORICAL_ONLY", "COST_ASSUMPTIONS", "MULTIPLE_TESTING_RISK"):
        assert code in w
    assert "UNSTABLE_PATTERN" not in w and "FEW_EVENTS" not in w


# =====================================================================================================
# (C) her karar dalı
# =====================================================================================================
@pytest.mark.parametrize("name", list(OOS_CASES))
def test_oos_decision_branches(tmp_path, name):
    oos, verdict, codes = OOS_CASES[name]
    sc = Scenario(**GOOD_IS, **oos)
    env = call(build_root(tmp_path, sc), sc)
    validate_envelope(env)
    r = res(env)
    assert (r.stability_verdict.value, {c.value for c in r.verdict_codes}) == (verdict, codes)
    # sayısal alanlar karardan bağımsız DOLU
    assert r.out_of_sample.outcome_mean_return_pct is not None
    assert r.out_of_sample.cost_adjusted_outcome_mean_return_pct is not None
    assert r.out_of_sample.p_value_raw is not None
    for c in codes:
        assert c in r.verdict_reason
    w = " | ".join(env["warnings"])
    assert ("UNSTABLE_PATTERN" in w) == (verdict == "UNSTABLE")
    assert ("FEW_EVENTS" in w) == (verdict == "INSUFFICIENT_DATA")


def test_is_too_few_is_insufficient_data(tmp_path):
    sc = Scenario(is_trig_thu=rep(3.0, 8), is_non_thu=rep(-0.5, 32), **OOS_CASES["stable"][0])
    r = res(call(build_root(tmp_path, sc), sc))
    assert (r.stability_verdict.value, [c.value for c in r.verdict_codes]) == ("INSUFFICIENT_DATA", ["IS_TOO_FEW"])
    assert r.in_sample.n_trigger_weeks == 8 and r.in_sample.p_value_raw is not None  # sayılar yine dolu


def test_is_not_significant_is_unstable(tmp_path):
    """Tetik ve koşulsuz haftalarda Per aynı (+0,5): fark 0 -> p = 1."""
    sc = Scenario(is_trig_thu=rep(0.5, 20), is_non_thu=rep(0.5, 20), **OOS_CASES["stable"][0])
    r = res(call(build_root(tmp_path, sc), sc))
    assert (r.stability_verdict.value, [c.value for c in r.verdict_codes]) == ("UNSTABLE", ["IS_NOT_SIGNIFICANT"])
    assert r.in_sample.p_value_raw == 1.0


def test_opposite_direction_pattern_is_not_significant(tmp_path):
    """Tek yönlü test: tetik haftalarında Per belirgin DÜŞÜYORSA (beklenen UP) anlamlı sayılmaz."""
    sc = Scenario(is_trig_thu=rep(-3.0, 20), is_non_thu=rep(0.5, 20), **OOS_CASES["stable"][0])
    r = res(call(build_root(tmp_path, sc), sc))
    assert r.in_sample.p_value_raw == 1.0
    assert [c.value for c in r.verdict_codes] == ["IS_NOT_SIGNIFICANT"]


def test_bonferroni_adjusts_p_and_can_flip_the_verdict(stable_root, stable_sc):
    r1 = res(call(stable_root, stable_sc))
    r = res(call(stable_root, stable_sc, n_tests_declared=1000))
    assert r.multiple_testing.n_tests_declared == 1000
    assert r.multiple_testing.adjusted_alpha == pytest.approx(0.05 / 1000)
    assert r.in_sample.p_value_raw == r1.in_sample.p_value_raw
    assert r.in_sample.p_value_adjusted == pytest.approx(min(1.0, r.in_sample.p_value_raw * 1000), abs=1e-6)
    assert (r.stability_verdict.value, [c.value for c in r.verdict_codes]) == ("UNSTABLE", ["IS_NOT_SIGNIFICANT"])
    assert r1.stability_verdict.value == "STABLE"
    assert r1.multiple_testing.n_tests_declared == 1


# =====================================================================================================
# (D) as_of, ufku dolmamış hafta, tatil, pencere sınırı, determinizm
# =====================================================================================================
def test_incomplete_last_week_is_excluded_and_post_as_of_shock_is_invisible(tmp_path_factory, stable_sc):
    """as_of = son OOS haftasının Çarşambası: Per (Çarş sonrası) as_of'u aşar -> hafta ufku dolmamış."""
    sc = stable_sc
    as_of = sc.oos_end - timedelta(days=2)  # Çarşamba
    clean = build_root(tmp_path_factory.mktemp("wk_clean"), sc)
    shocked = build_root(tmp_path_factory.mktemp("wk_shock"), sc, shock_after=as_of)
    a, b = call(clean, sc, as_of=as_of.isoformat()), call(shocked, sc, as_of=as_of.isoformat())
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]
    o = res(a).out_of_sample
    assert (o.n_weeks_total, o.n_excluded_incomplete_horizon, o.n_weeks_complete) == (20, 1, 19)
    assert o.window.end == as_of  # OOS bitişi as_of'a kesildi
    assert a["n_excluded_incomplete_horizon"] == 1
    w = " | ".join(a["warnings"])
    assert "AS_OF_CLAMPED" in w and "INCOMPLETE_HORIZON_EXCLUDED" in w


def test_as_of_after_window_end_changes_nothing(stable_root, stable_sc):
    """as_of pencere sonundan ÖNCE değilse, as_of'u uzatmak sonucu değiştirmez (zarf hariç)."""
    a = call(stable_root, stable_sc)["results"]
    far = (stable_sc.oos_end + timedelta(days=30)).isoformat()
    assert call(stable_root, stable_sc, as_of=far)["results"] == a


def test_oos_end_beyond_as_of_is_clamped_with_warning(stable_root, stable_sc):
    env = call(stable_root, stable_sc, out_of_sample_end=(stable_sc.oos_end + timedelta(days=60)).isoformat())
    assert res(env).out_of_sample.window.end == stable_sc.oos_end
    assert "AS_OF_CLAMPED" in " | ".join(env["warnings"])


def test_holiday_and_gap_weeks_are_excluded(tmp_path, stable_sc):
    """Pzt ve Per örüntüde. Hafta 5'te Per yok; hafta 10'da Çarş yok (Per getirisi bir günlük değil);
    hafta 15'te Cuma yok -> hafta 16'nın Pazartesi getirisi (Cuma kapanışından) tanımsız. Hafta 15'in kendisi etkilenmez."""
    sc = stable_sc
    drops = [sc.monday(4) + timedelta(days=3), sc.monday(9) + timedelta(days=2), sc.monday(14) + timedelta(days=4)]
    env = call(build_root(tmp_path, sc, drop=drops), sc)
    i = res(env).in_sample
    assert (i.n_weeks_total, i.n_excluded_holiday_weeks, i.n_weeks_complete) == (40, 3, 37)
    assert "HOLIDAY_WEEKS_EXCLUDED" in " | ".join(env["warnings"])
    assert i.n_weeks_total == i.n_weeks_complete + i.n_excluded_holiday_weeks + i.n_excluded_incomplete_horizon


def test_week_straddling_window_boundary_belongs_to_neither_window(tmp_path, stable_sc):
    """IS bitişi Çarşamba: o haftanın Per'i IS dışında kalır -> hafta dışlanır (IS/OOS verisi karışmaz)."""
    sc = stable_sc
    is_end = sc.monday(sc.n_is - 1) + timedelta(days=2)
    env = call(build_root(tmp_path, sc), sc, in_sample_end=is_end.isoformat())
    r = res(env)
    assert (r.in_sample.n_weeks_total, r.in_sample.n_excluded_holiday_weeks) == (40, 1)
    assert r.out_of_sample.n_weeks_total == 20 and r.out_of_sample.window.start == sc.oos_start


def test_determinism(stable_root, stable_sc):
    a, b = call(stable_root, stable_sc), call(stable_root, stable_sc)
    assert a == b
    assert call(stable_root, stable_sc, n_tests_declared=2)["input_hash"] != a["input_hash"]


# =====================================================================================================
# (E) yön, maliyet, conditioning, hata zarfları
# =====================================================================================================
def test_down_outcome_cost_adjustment_is_directional(tmp_path):
    """MON-UP tetik, THU-DOWN sonuç. Tetik haftasında Per -2: yönlü maliyet sonrası = -(-2) - 0,5 = 1,5."""
    sc = Scenario(is_trig_thu=rep(-2.0, 20), is_non_thu=rep(0.5, 20), oos_trig_thu=rep(-2.0, 10),
                  oos_non_thu=rep(0.5, 10), trig_mon=1.0, non_mon=-1.0)
    pattern = [{"weekday": "MON", "direction": "UP", "role": "TRIGGER"},
               {"weekday": "THU", "direction": "DOWN", "role": "OUTCOME"}]
    r = res(call(build_root(tmp_path, sc), sc, pattern=pattern))
    i = r.in_sample
    assert i.outcome_mean_return_pct == pytest.approx(-2.0, abs=1e-3)
    assert i.cost_adjusted_outcome_mean_return_pct == pytest.approx(1.5, abs=1e-3)
    assert (i.n_trigger_weeks, i.n_occurrences, i.hit_rate_pct) == (20, 20, 100.0)
    assert i.t_stat is not None and i.t_stat > 5  # t yönlüdür: pozitif = beklenen yönde
    assert r.stability_verdict.value == "STABLE"


def test_zero_cost_params_flow_into_cost_model(stable_root, stable_sc):
    r = res(call(stable_root, stable_sc, transaction_cost_bps=0, slippage_bps=0))
    assert r.cost_model.round_trip_cost_pct == 0.0
    assert r.in_sample.cost_adjusted_outcome_mean_return_pct == r.in_sample.outcome_mean_return_pct
    assert res(call(stable_root, stable_sc)).cost_model.round_trip_cost_pct == pytest.approx(0.5)


def _idx_weeks(sc: Scenario, up_first_is: int, up_first_oos: int, big_tail: float = 0.0):
    """Endeks Pzt getirisi: tetik haftalarının ilk `up_*` tanesinde +1, kalanında -1 (koşulsuz haftalarda 0).
    big_tail: Per/Cum günlerine devasa getiri (look-ahead denemesi)."""
    out = []
    for n_trig, n_up, n_tot in ((20, up_first_is, sc.n_is), (10, up_first_oos, sc.n_oos)):
        for k in range(n_tot):
            mon = (1.0 if k < n_up else -1.0) if k < n_trig else 0.0
            out.append(week(mon=mon, thu=big_tail, fri=-big_tail))
    return out


@pytest.mark.parametrize("cond,exp_is,exp_oos", [("NONE", 20, 10), ("XU100_UP", 10, 4), ("XU100_DOWN", 10, 6)])
def test_conditioning_filters_trigger_weeks(tmp_path, stable_sc, cond, exp_is, exp_oos):
    root = build_root(tmp_path, stable_sc, index_weeks=_idx_weeks(stable_sc, 10, 4))
    r = res(call(root, stable_sc, conditioning=cond))
    assert (r.in_sample.n_trigger_weeks, r.out_of_sample.n_trigger_weeks) == (exp_is, exp_oos)
    assert r.conditioning.value == cond
    assert r.in_sample.n_weeks_complete == 40  # koşul yalnızca tetiği süzer, taban (koşulsuz) değişmez


def test_conditioning_never_uses_outcome_days_of_the_index(tmp_path_factory, stable_sc):
    """Endeksin Perşembe/Cuma getirisi (OUTCOME günleri) koşulu etkilememeli: look-ahead yok."""
    a = build_root(tmp_path_factory.mktemp("wk_ix_a"), stable_sc, index_weeks=_idx_weeks(stable_sc, 10, 4))
    b = build_root(tmp_path_factory.mktemp("wk_ix_b"), stable_sc, index_weeks=_idx_weeks(stable_sc, 10, 4, big_tail=30.0))
    for cond in ("XU100_UP", "XU100_DOWN"):
        assert call(a, stable_sc, conditioning=cond)["results"] == call(b, stable_sc, conditioning=cond)["results"]


@pytest.mark.parametrize("pattern,msg", [
    ([{"weekday": "THU", "direction": "UP", "role": "OUTCOME"}], "TRIGGER"),
    ([{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"},
      {"weekday": "THU", "direction": "UP", "role": "OUTCOME"},
      {"weekday": "FRI", "direction": "DOWN", "role": "OUTCOME"}], "OUTCOME"),
])
def test_unsupported_patterns_are_a_clear_error(stable_root, stable_sc, pattern, msg):
    env = call(stable_root, stable_sc, pattern=pattern)
    assert env["status"] == "ERROR" and env["results"] is None
    assert env["error"]["code"] == "UNSUPPORTED_PATTERN" and msg in env["error"]["message"]


def test_unknown_ticker_and_bad_windows_are_error_envelopes(stable_root, stable_sc):
    assert call(stable_root, stable_sc, ticker="ZZZZ")["error"]["code"] == "NO_DATA"
    env = call(stable_root, stable_sc, as_of=(stable_sc.oos_start - timedelta(days=1)).isoformat())
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_WINDOW"  # OOS as_of sonrasında başlıyor
    assert call(stable_root, stable_sc, alpha=5)["error"]["code"] == "INVALID_PARAMS"


# =====================================================================================================
# (F) gerçek v2 snapshot (Soru 2 biçimi; as_of = 2026-09-10)
# =====================================================================================================
def real(ticker="THYAO", **over):
    params = {"ticker": ticker, "pattern": [
        {"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"}, {"weekday": "TUE", "direction": "DOWN", "role": "TRIGGER"},
        {"weekday": "WED", "direction": "DOWN", "role": "TRIGGER"}, {"weekday": "THU", "direction": "UP", "role": "OUTCOME"},
        {"weekday": "FRI", "direction": "UP", "role": "OUTCOME"}],
        "in_sample_start": "2024-01-01", "in_sample_end": "2025-12-31",
        "out_of_sample_start": "2026-01-01", "out_of_sample_end": "2026-09-10", "as_of": "2026-09-10"}
    params.update(over)
    return tool.run_on(params, data_version=VERSION)


@needs_snapshot
def test_real_thyao_question_2():
    env = real()
    validate_envelope(env)
    r = res(env)
    assert r.pattern_label == "MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP"
    assert (r.stability_verdict.value, [c.value for c in r.verdict_codes]) == ("UNSTABLE", ["IS_NOT_SIGNIFICANT"])
    assert r.in_sample.n_trigger_weeks >= 10 and r.in_sample.p_value_raw >= 0.05
    assert r.out_of_sample.n_excluded_incomplete_horizon == 1  # 7-11 Eylül haftası: Cuma 11.09 as_of sonrası
    assert r.out_of_sample.window.end.isoformat() == "2026-09-10"
    assert r.in_sample.n_excluded_holiday_weeks > 0


@needs_snapshot
def test_real_other_stock_is_insufficient_data_and_deterministic():
    r = res(real("ASELS"))
    assert (r.stability_verdict.value, [c.value for c in r.verdict_codes]) == ("INSUFFICIENT_DATA", ["IS_TOO_FEW"])
    assert real("ASELS") == real("ASELS")
