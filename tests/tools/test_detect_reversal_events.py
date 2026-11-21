"""detect_reversal_events aracı testleri.

(A) Saf yardımcılar: RSI yerel durum (teyit günü), ardışık seri başlangıcı, çakışan pencere, ileri getiri + MFE.
(B) Sentetik snapshot, ELLE hesaplanabilir olaylar: taban 100/102 dönüşümlü (Bollinger std = 1), sonra dip/tepe.
(C) Sızıntı (as_of sonrası şok, önek değişmezliği), ufku dolmamış olay, determinizm.
(D) Kümelenme (ilk gün), touch_mode, UP/DOWN yön, birleşik koşullar, IS/OOS ve oos_degradation.
(E) RSI aileleri, desteklenmeyen aileler, hata zarfları.
(F) Gerçek v2 snapshot (ASELS, Soru 3: 01.01.2024 - 10.09.2026).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from schemas.enums import EventFamily, RsiState
from schemas.results import DetectReversalEventsResult
from tests.conftest import make_snapshot
from tests.tools.test_find_support_resistance import _frame
from tools import detect_reversal_events as tool
from tools.indicators.volatility import bollinger

VERSION = "snap_2026-11-20_v2"
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")
BASE = [100, 102] * 13  # 26 bar; Bollinger(20,2): ort 101, std 1 -> alt 99, üst 103
UP_PATH = [94, 95, 96, 97, 98, 99, 100, 101, 102, 103]


# =====================================================================================================
# (A) saf yardımcılar
# =====================================================================================================
def test_rsi_local_state_hand_examples():
    """w=3: [50,40,30,35] -> t=3: RSI[2]=30 son 3 değerin en küçüğü ve 35 > 30 -> LOCAL_LOW; teyit günü t=3."""
    s = tool.rsi_local_state(np.array([50.0, 40.0, 30.0, 35.0]), 3)
    assert s == [None, None, None, RsiState.LOCAL_LOW]
    s = tool.rsi_local_state(np.array([30.0, 40.0, 60.0, 55.0]), 3)
    assert s[3] == RsiState.LOCAL_HIGH  # RSI[2]=60 pencerenin en büyüğü, 55 < 60
    s = tool.rsi_local_state(np.array([50.0, 40.0, 30.0, 25.0, 28.0]), 3)
    assert s[3] == RsiState.NEUTRAL  # RSI[2]=30 pencerenin (50,40,30) en küçüğü ama 25 < 30: dönüş yok
    assert s[4] == RsiState.LOCAL_LOW  # RSI[3]=25 (40,30,25) en küçüğü, 28 > 25
    assert tool.rsi_local_state(np.array([np.nan, 1.0, 2.0, 3.0, 4.0]), 3)[3] is None  # pencerede NaN
    assert tool.rsi_local_state(np.array([1.0, 2.0]), 3) == [None, None]  # yetersiz bar


def test_rsi_local_state_is_causal():
    """t günündeki durum yalnızca <= t verisine bağlıdır: seriyi t'de kesmek durumu değiştirmez."""
    rng = np.random.default_rng(7)
    rsi = 50 + 20 * np.sin(np.arange(60) / 3) + rng.normal(0, 2, 60)
    full = tool.rsi_local_state(rsi, 5)
    for t in (10, 25, 40, 59):
        assert tool.rsi_local_state(rsi[:t + 1], 5) == full[:t + 1]


def test_series_starts_and_overlap():
    assert tool.series_starts(np.array([0, 1, 1, 0, 1], bool)) == [(1, 2), (4, 1)]
    assert tool.series_starts(np.zeros(3, bool)) == []
    assert tool.series_starts(np.ones(3, bool)) == [(0, 3)]
    assert tool.count_overlapping([0, 5, 20, 22], 10) == 2  # 0->5 ve 20->22 çakışır; 5->20 çakışmaz; son olay sayılmaz
    assert tool.count_overlapping([3], 10) == 0 and tool.count_overlapping([], 10) == 0


def test_forward_return_directional_and_mfe_clamped_at_zero():
    close = np.array([100.0, 104.0, 102.0, 98.0])
    raw, d, mfe = tool.forward(close, 0, 3, 1.0)
    assert (raw, d) == (pytest.approx(-2.0), pytest.approx(-2.0)) and mfe == pytest.approx(4.0)  # en iyi kapanış 104
    raw, d, mfe = tool.forward(close, 0, 3, -1.0)  # DOWN beklentisi: düşüş lehte
    assert raw == pytest.approx(-2.0) and d == pytest.approx(2.0) and mfe == pytest.approx(2.0)  # en iyi (en düşük) 98
    assert tool.forward(np.array([100.0, 101.0, 102.0]), 0, 2, -1.0)[2] == 0.0  # hep aleyhte: MFE 0
    assert tool.forward(close, 1, 3, 1.0) is None  # ufuk veri sonunu aşar


# =====================================================================================================
# (B) sentetik snapshot yardımcıları
# =====================================================================================================
def build(root, closes, vols=None, dates=None, shock_after: int | None = None, hl=0.001):
    c = np.asarray(closes, float).copy()
    n = len(c)
    dates = pd.bdate_range("2024-01-01", periods=n) if dates is None else dates
    v = np.full(n, 1000.0) if vols is None else np.asarray(vols, float)
    if shock_after is not None:  # as_of SONRASI satırlara aşırı değerler
        c[shock_after + 1:] *= 1e6
    stocks = _frame(c, c * (1 + hl), c * (1 - hl), v, dates, ticker="ASELS")
    index = _frame(np.full(n, 10000.0), np.full(n, 10001.0), np.full(n, 9999.0), v, dates).drop(columns=["ticker"])
    make_snapshot(root, stocks, index, version=VERSION)
    return root


def call(root, n_bars, family="BB_LOWER_TOUCH", as_of_idx=None, **over):
    dates = pd.bdate_range("2024-01-01", periods=n_bars)
    params = {"ticker": "ASELS", "event_family": family, "forward_horizons": [1, 3, 5],
              "as_of": dates[(n_bars - 1) if as_of_idx is None else as_of_idx].date().isoformat()}
    params.update(over)
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> DetectReversalEventsResult:
    assert env["status"] == "OK", env.get("error")
    return DetectReversalEventsResult.model_validate(env["results"])


@pytest.fixture(scope="module")
def one(tmp_path_factory):
    c = BASE + UP_PATH
    return build(tmp_path_factory.mktemp("rev_one"), c), len(c)


def test_hand_computed_single_event(one):
    """Bar 26 (kapanış 94) alt banda (99) dokunur. 95 de bandın altındadır (2 ham gün) -> olay = ilk gün.
    İleri getiri: 95/94-1 = 1,0638; 97/94-1 = 3,1915; 99/94-1 = 5,3191 (hepsi başarı, MFE = getiri)."""
    root, n = one
    env = call(root, n)
    validate_envelope(env)
    r = res(env)
    g = r.groups[0]
    assert (r.expected_direction.value, g.label, g.n_events_detected, g.n_raw_event_days, g.n_overlapping_forward_windows) == (
        "UP", "single_indicator", 1, 2, 0)
    ev = g.events[0]
    assert (ev.date, ev.close) == (pd.bdate_range("2024-01-01", periods=n)[26].date(), 94.0)
    got = [(f.horizon, f.complete, f.return_pct, f.reversal_success, f.reversal_strength_pct) for f in ev.forward_returns]
    assert got == [(1, True, 1.0638, True, 1.0638), (3, True, 3.1915, True, 3.1915), (5, True, 5.3191, True, 5.3191)]
    h5 = g.per_horizon[2]
    assert (h5.full.n_events_complete, h5.full.n_success, h5.full.hit_rate_pct, h5.full.mean_return_pct) == (1, 1, 100.0, 5.3191)
    assert h5.full.cost_adjusted_mean_return_pct == pytest.approx(5.3191 - 0.5, abs=1e-4)
    assert env["n_events"] == 1 and env["n_excluded_incomplete_horizon"] == 0
    assert r.groups[0].per_horizon[0].baseline.n_obs > 0
    assert r.multiple_testing.n_tests_declared == 1


def test_cluster_start_rule_counts_raw_days_but_one_event(one):
    root, n = one
    g = res(call(root, n)).groups[0]
    assert g.n_raw_event_days == 2 and g.n_events_detected == 1  # 94 ve 95 ham gün, tek olay


def test_incomplete_horizon_is_excluded_and_reported(one):
    """as_of = olay + 3 bar: h=1,3 tamam; h=5 dolmamış -> o ufkun istatistiğine girmez, n_excluded = 1."""
    root, n = one
    env = call(root, n, as_of_idx=29)
    g = res(env).groups[0]
    assert [f.complete for f in g.events[0].forward_returns] == [True, True, False]
    assert g.events[0].forward_returns[2].return_pct is None
    h1, h3, h5 = (b.full for b in g.per_horizon)
    assert (h1.n_events_complete, h3.n_events_complete, h5.n_events_complete) == (1, 1, 0)
    assert (h1.n_excluded_incomplete_horizon, h5.n_excluded_incomplete_horizon) == (0, 1)
    assert h5.hit_rate_pct is None and h5.mean_return_pct is None
    assert env["n_excluded_incomplete_horizon"] == 1
    assert "INCOMPLETE_HORIZON_EXCLUDED" in " | ".join(env["warnings"])


# =====================================================================================================
# (C) sızıntı, önek değişmezliği, determinizm
# =====================================================================================================
def test_post_as_of_shock_is_invisible(tmp_path_factory):
    c = BASE + UP_PATH + [100, 102] * 5
    clean = build(tmp_path_factory.mktemp("rev_clean"), c)
    shocked = build(tmp_path_factory.mktemp("rev_shock"), c, shock_after=31)
    a, b = call(clean, len(c), as_of_idx=31), call(shocked, len(c), as_of_idx=31)
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]


def test_prefix_invariance(tmp_path_factory):
    c = BASE + UP_PATH + [100, 102] * 5
    full = build(tmp_path_factory.mktemp("rev_full"), c)
    cut = build(tmp_path_factory.mktemp("rev_cut"), c[:32])
    assert call(full, len(c), as_of_idx=31)["results"] == call(cut, 32)["results"]


def test_determinism_and_envelope(one):
    root, n = one
    a, b = call(root, n), call(root, n)
    assert a == b
    assert call(root, n, n_tests_declared=3)["input_hash"] != a["input_hash"]
    r = res(call(root, n, n_tests_declared=4))
    assert (r.multiple_testing.n_tests_declared, r.multiple_testing.adjusted_alpha) == (4, 0.05 / 4)


# =====================================================================================================
# (D) yön, touch_mode, koşullar, IS/OOS
# =====================================================================================================
def test_upper_touch_is_down_directional(tmp_path):
    """Tepe 106 (üst bant 103): olay günü 106. Sonra 105, 104, 103 ...: ham getiri NEGATİF, başarı True, yönlü getiri POZİTİF."""
    c = BASE + [106, 105, 104, 103, 102, 101, 100, 99, 98, 97]
    r = res(call(build(tmp_path, c), len(c), family="BB_UPPER_TOUCH"))
    g = r.groups[0]
    assert r.expected_direction.value == "DOWN" and g.n_events_detected == 1
    f = g.events[0].forward_returns
    assert f[0].return_pct == pytest.approx(105 / 106 * 100 - 100, abs=1e-4) and f[0].reversal_success is True
    assert f[1].return_pct == pytest.approx(103 / 106 * 100 - 100, abs=1e-4)
    assert f[1].reversal_strength_pct == pytest.approx(106 / 106 * 100 - (103 / 106 * 100), abs=1e-3)  # en iyi (en düşük) kapanış 103 -> +2,8302
    h3 = g.per_horizon[1].full
    assert h3.mean_return_pct == pytest.approx(2.8302, abs=1e-3)  # yönlü: işaret çevrildi
    assert h3.hit_rate_pct == 100.0


def test_failed_reversal_has_zero_or_positive_mfe_and_false_positive(tmp_path):
    c = BASE + [94, 93, 92, 91, 90, 89, 88, 87, 86, 85]
    g = res(call(build(tmp_path, c), len(c))).groups[0]
    f = g.events[0].forward_returns
    assert [x.reversal_success for x in f] == [False, False, False]
    assert all(x.reversal_strength_pct == 0.0 for x in f)  # hiç lehte kapanış yok
    h = g.per_horizon[0].full
    assert (h.n_success, h.n_false_positive, h.false_positive_rate_pct) == (0, 1, 100.0)


def test_touch_mode_low_detects_at_least_as_many_events(tmp_path):
    """close modunda kapanış alt bandın üstünde ama gün içi dip altında olabilir; low modu ⊇ close modu (§4)."""
    c = BASE + [100, 99.2, 100, 102, 100, 102]
    root = build(tmp_path, c, hl=0.01)  # low = close x 0,99
    n_close = res(call(root, len(c), touch_mode="close")).groups[0].n_events_detected
    n_low = res(call(root, len(c), touch_mode="low")).groups[0].n_events_detected
    assert n_low >= n_close and n_low > n_close


def test_condition_set_filters_events_by_states_on_event_day(tmp_path):
    """İki dönüş: ilkinde hacim patlaması (HIGH), ikincisinde normal. Koşullu grup yalnızca ilkini içerir."""
    cycle = BASE + [94, 95, 96, 97, 98, 99, 100, 101, 102, 103]
    c = cycle + BASE + [94, 95, 96, 97, 98, 99, 100, 101, 102, 103]
    v = 1000.0 + 10.0 * (np.arange(len(c)) % 2)  # 1000/1010 dönüşümlü: std > 0, z = ±1 (sınır dahil NORMAL)
    v[26] = 8000.0  # ilk olay günü hacim z yüksek
    root = build(tmp_path, c, vols=v)
    r = res(call(root, len(c), condition_sets=[{"label": "high_volume", "volume_regime": "HIGH"},
                                               {"label": "low_volume", "volume_regime": "LOW"}]))
    u, hv, lv = r.groups
    assert u.n_events_detected == 2
    assert [e.states.volume.value for e in u.events] == ["HIGH", "NORMAL"]
    assert hv.n_events_detected == 1 and hv.events[0].date == u.events[0].date and hv.conditions.label == "high_volume"
    assert lv.n_events_detected == 0 and lv.per_horizon[0].full.n_events_complete == 0
    assert hv.n_raw_event_days == 2 and lv.n_raw_event_days == 0
    assert {g.label for g in r.groups} == {"single_indicator", "high_volume", "low_volume"}


def _cycles(paths):
    c: list[float] = []
    starts: list[int] = []
    for p in paths:
        c += BASE
        starts.append(len(c))
        c += p
    return c, starts


FALL = [94, 92, 90, 88, 86, 84, 82, 80, 78, 76]


def test_oos_degradation_true_when_oos_events_fail(tmp_path):
    """8 IS döngüsü toparlanır, 6 OOS döngüsü düşer. OOS 6 >= MIN_OOS_EVENTS(5): maliyet sonrası ort. IS>0, OOS<=0 -> bayrak True."""
    c, starts = _cycles([UP_PATH] * 8 + [FALL] * 6)
    dates = pd.bdate_range("2024-01-01", periods=len(c))
    split = dates[starts[8] - 5].date().isoformat()  # OOS: 9. döngünün dip gününden önce
    env = call(build(tmp_path, c), len(c), split_date=split)
    r = res(env)
    g = r.groups[0]
    assert g.n_events_detected == 14
    for b in g.per_horizon:
        assert (b.in_sample.n_events_complete, b.out_of_sample.n_events_complete) == (8, 6)
        assert b.in_sample.hit_rate_pct == 100.0 and b.out_of_sample.hit_rate_pct == 0.0
        assert b.oos_degradation_flag is True
    assert "OOS_DEGRADATION" in " | ".join(env["warnings"]) and "OOS_TOO_SMALL" not in " | ".join(env["warnings"])


def test_oos_too_small_gives_false_flag_and_warning(tmp_path):
    c, starts = _cycles([UP_PATH] * 8 + [FALL] * 3)
    dates = pd.bdate_range("2024-01-01", periods=len(c))
    env = call(build(tmp_path, c), len(c), split_date=dates[starts[8] - 5].date().isoformat())
    g = res(env).groups[0]
    assert all(b.oos_degradation_flag is False and b.out_of_sample.n_events_complete == 3 for b in g.per_horizon)
    assert "OOS_TOO_SMALL" in " | ".join(env["warnings"])


def test_no_split_gives_no_in_out_sample(one):
    root, n = one
    b = res(call(root, n)).groups[0].per_horizon[0]
    assert (b.in_sample, b.out_of_sample, b.oos_degradation_flag) == (None, None, None)


def test_overlapping_forward_windows_are_counted(tmp_path):
    """İki olay 10 bar arayla, ufuk 10: ilkinin ileri penceresi ikinciyi kapsar -> 1 çakışma; 3 ufukla da (max 5) çakışmaz."""
    c, starts = _cycles([UP_PATH, UP_PATH])
    root = build(tmp_path, c)
    g10 = res(call(root, len(c), forward_horizons=[10])).groups[0]
    assert g10.n_events_detected == 2 and g10.n_overlapping_forward_windows == 0  # olaylar 36 bar arayla
    c2 = BASE + [94, 100, 102, 100, 102, 100, 102, 100, 94, 100, 102, 100, 102, 100, 102]  # ikinci dip 8 bar sonra
    r = res(call(build(tmp_path / "x", c2), len(c2), forward_horizons=[10]))
    g = r.groups[0]
    assert g.n_events_detected == 2 and g.n_overlapping_forward_windows == 1


def test_few_events_warning(one):
    root, n = one
    assert any(w.startswith("FEW_EVENTS: single_indicator") for w in call(root, n)["warnings"])


# =====================================================================================================
# (E) RSI aileleri, desteklenmeyen aileler, hatalar
# =====================================================================================================
def _wave(n=120):
    i = np.arange(n)
    return 100 + 8 * np.sin(i / 4.0) + 0.3 * np.sin(i / 1.3)


def test_rsi_trough_and_peak_events_match_the_state_definition(tmp_path):
    c = _wave()
    root = build(tmp_path, c)
    lo = res(call(root, len(c), family="RSI_LOCAL_TROUGH", forward_horizons=[3]))
    hi = res(call(root, len(c), family="RSI_LOCAL_PEAK", forward_horizons=[3]))
    assert (lo.expected_direction.value, hi.expected_direction.value) == ("UP", "DOWN")
    assert lo.groups[0].n_events_detected >= 3 and hi.groups[0].n_events_detected >= 3
    assert all(e.states.rsi == RsiState.LOCAL_LOW for e in lo.groups[0].events)
    assert all(e.states.rsi == RsiState.LOCAL_HIGH for e in hi.groups[0].events)
    # her ham gün tek günlük seri (teyit günleri ardışık olamaz) -> ham gün = olay
    assert lo.groups[0].n_raw_event_days == lo.groups[0].n_events_detected
    # bağımsız yeniden hesap: kütüphane RSI'ı + durum fonksiyonu
    from tools.indicators.momentum import rsi_wilder
    st = tool.rsi_local_state(rsi_wilder(pd.Series(c), 14).to_numpy(float))
    expect = [i for i, s in enumerate(st) if s == RsiState.LOCAL_LOW]
    dates = pd.bdate_range("2024-01-01", periods=len(c))
    assert [e.date for e in lo.groups[0].events] == [dates[i].date() for i in expect]


@pytest.mark.parametrize("family", ["BB_MID_TEST", "SUPERTREND_FLIP", "KAMA_SLOPE_CHANGE", "KAMA_PRICE_CROSS",
                                    "ICHIMOKU_BREAKOUT", "ICHIMOKU_REJECTION", "ICHIMOKU_RETURN_INTO_CLOUD", "SR_TOUCH"])
def test_mixed_direction_families_are_unsupported(one, family):
    root, n = one
    env = call(root, n, family=family)
    assert env["status"] == "ERROR" and env["results"] is None
    assert env["error"]["code"] == "UNSUPPORTED_EVENT_FAMILY" and family in env["error"]["message"]
    assert {f.value for f in EventFamily} >= {family}


def test_errors(one):
    root, n = one
    assert call(root, n, ticker="ZZZZ")["error"]["code"] == "NO_DATA"
    dup = [{"label": "a", "volume_regime": "HIGH"}, {"label": "a", "volume_regime": "LOW"}]
    assert call(root, n, condition_sets=dup)["error"]["code"] == "INVALID_PARAMS"
    assert call(root, n, condition_sets=[{"label": "single_indicator", "volume_regime": "HIGH"}])["error"]["code"] == "INVALID_PARAMS"
    assert call(root, n, split_date="2030-01-01")["error"]["code"] == "INVALID_PARAMS"


# =====================================================================================================
# (F) gerçek v2: ASELS, 01.01.2024 - 10.09.2026 (Soru 3)
# =====================================================================================================
SOQ3 = [{"label": "rsi_trough_high_volume", "rsi_state": "LOCAL_LOW", "volume_regime": "HIGH"},
        {"label": "supertrend_bearish_below_cloud", "supertrend_state": "BEARISH", "ichimoku_state": "BELOW_CLOUD"}]


def real(**over):
    p = {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "as_of": "2026-09-10", "split_date": "2026-01-01",
         "forward_horizons": [1, 3, 5, 10], "condition_sets": SOQ3}
    p.update(over)
    return tool.run_on(p, data_version=VERSION)


@needs_snapshot
def test_real_asels_question_3():
    env = real()
    validate_envelope(env)
    r = res(env)
    u, rsi_hv, st = r.groups
    assert (u.n_events_detected, u.n_raw_event_days, u.n_overlapping_forward_windows) == (12, 17, 5)
    assert (rsi_hv.n_events_detected, st.n_events_detected) == (0, 5)
    assert env["n_events"] == 12 and env["n_excluded_incomplete_horizon"] == 0
    h5 = next(b for b in u.per_horizon if b.horizon == 5)
    assert (h5.full.n_events_complete, h5.full.n_success, h5.full.hit_rate_pct) == (12, 8, 66.6667)
    assert (h5.in_sample.n_events_complete, h5.out_of_sample.n_events_complete) == (9, 3)
    assert h5.oos_degradation_flag is False  # OOS 3 < MIN_OOS_EVENTS: false + OOS_TOO_SMALL
    w = " | ".join(env["warnings"])
    assert "FEW_EVENTS" in w and "OOS_TOO_SMALL" in w
    assert real() == real()


@needs_snapshot
def test_real_events_are_never_after_as_of_and_forward_windows_complete():
    r = res(real(as_of="2026-09-10"))
    last = pd.Timestamp("2026-09-10").date()
    for g in r.groups:
        assert all(e.date <= last for e in g.events)
        for e in g.events:
            for f in e.forward_returns:
                assert (f.return_pct is not None) == f.complete
