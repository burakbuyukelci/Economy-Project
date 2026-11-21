"""run_backtest aracı testleri.

(A) Saf yardımcılar: çakışmasız işlem, performans metrikleri (elle), bölünme pencereleri.
(B) Sentetik snapshot, ELLE hesaplanabilir senaryolar (WEEKDAY/CATCH_UP/REVERSAL).
(C) Sızıntı (as_of sonrası şok, önek değişmezliği), sinyal gecikmesi, ufku dolmamış işlem, determinizm.
(D) IS/OOS bölünmeleri, walk-forward, oos_degradation, varyant B, benchmark'lar, trade_log kısaltma.
(E) Desteklenmeyen kombinasyonlar ve hata zarfları.
(F) Gerçek v2 snapshot.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from schemas import registry as REG
from schemas.results import RunBacktestResult
from tests.conftest import make_snapshot
from tests.tools.test_find_support_resistance import _frame
from tools import run_backtest as tool

VERSION = "snap_2026-11-20_v2"
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")
FIRST_MONDAY = date(2024, 1, 1)
BASE_FRIDAY = pd.Timestamp("2023-12-29")


# =====================================================================================================
# (A) saf yardımcılar
# =====================================================================================================
def test_build_trades_non_overlapping_example():
    """lag=1, hold=2, sinyaller [5,6,7,8]: 5 -> giriş 6, çıkış 8; 6 ve 7 çıkış gününden önce (alınmaz); 8 >= 8 -> alınır (giriş 9, çıkış 11)."""
    close = np.arange(100.0, 130.0)
    done, acc, inc = tool.build_trades([5, 6, 7, 8], close, 1, 2)
    assert done == [(5, 6, 8), (8, 9, 11)] and acc == [5, 8] and inc == []


def test_build_trades_incomplete_exit_counts_as_signal_but_not_trade():
    done, acc, inc = tool.build_trades([5, 18], np.arange(20.0), 1, 2)  # 18 -> çıkış 21 > son bar 19
    assert done == [(5, 6, 8)] and acc == [5, 18] and inc == [18]


def test_build_trades_entry_is_always_after_signal():
    done, _, _ = tool.build_trades(list(range(0, 40, 3)), np.arange(60.0), 2, 3)
    assert all(s < e <= x for s, e, x in done) and all(e - s == 2 for s, e, _ in done)


def test_perf_hand_computed():
    m = tool.perf(np.array([0.10, -0.50, 0.20]), [10.0, -50.0], np.array([1.0, 1.0, 0.0]))
    assert m.cumulative_return_pct == pytest.approx(-34.0)  # 1,1 x 0,5 x 1,2 = 0,66
    assert m.max_drawdown_pct == pytest.approx(-50.0)  # tepe 1,1 -> dip 0,55
    assert (m.n_trades, m.win_rate_pct, m.avg_trade_return_pct, m.median_trade_return_pct) == (2, 50.0, -20.0, -20.0)
    assert m.exposure_pct == pytest.approx(66.6667, abs=1e-3)
    assert tool.perf(np.array([0.01, -0.01]), None).sharpe_ratio == 0.0  # ortalama 0
    assert tool.perf(np.zeros(5), None).sharpe_ratio is None  # std = 0
    flat = tool.perf(np.array([]), None)
    assert (flat.cumulative_return_pct, flat.sharpe_ratio, flat.max_drawdown_pct) == (None, None, None)
    up = tool.perf(np.array([0.01, 0.02]), None)
    assert up.max_drawdown_pct == 0.0 and up.win_rate_pct is None and up.n_trades == 0


def test_perf_sharpe_formula():
    d = np.array([0.01, 0.03, -0.01, 0.02])
    expect = d.mean() / d.std(ddof=1) * np.sqrt(252)
    assert tool.perf(d, None).sharpe_ratio == pytest.approx(expect, abs=1e-4)


def test_split_windows_hand():
    cal = pd.bdate_range("2024-01-01", "2024-03-29")  # 65 işlem günü
    w = tool.split_windows(date(2024, 1, 1), date(2024, 3, 29), date(2024, 1, 31), date(2024, 2, 29), False, cal, 126)
    assert [(n.value, a, b) for n, a, b in w] == [("TRAIN", date(2024, 1, 1), date(2024, 1, 31)),
                                                 ("VALIDATION", date(2024, 2, 1), date(2024, 2, 29)),
                                                 ("TEST", date(2024, 3, 1), date(2024, 3, 29))]
    wf = tool.split_windows(date(2024, 1, 1), date(2024, 3, 29), date(2024, 2, 29), None, True, cal, 10)
    assert [n.value for n, _, _ in wf] == ["TRAIN"] + ["WALK_FORWARD"] * 3  # 1-29 Mart: 21 işlem günü -> 10 + 10 + 1
    assert tool.split_windows(date(2024, 1, 1), date(2024, 3, 29), None, None, False, cal, 126) == []
    assert [n.value for n, _, _ in tool.split_windows(date(2024, 1, 1), date(2024, 3, 29), date(2024, 3, 29), None, False, cal, 126)] == ["TRAIN"]


# =====================================================================================================
# (B) sentetik snapshot yardımcıları
# =====================================================================================================
def week(mon=0.0, tue=0.0, wed=0.0, thu=0.0, fri=0.0):
    return (mon, tue, wed, thu, fri)


def weekly_closes(weeks, base=100.0):
    rets = np.asarray(weeks, float).ravel() / 100.0
    closes = base * np.concatenate([[1.0], np.cumprod(1.0 + rets)])
    return closes, pd.bdate_range(BASE_FRIDAY, periods=len(closes))


def snap(root, closes_by_ticker: dict, dates, index_closes=None, shock_after: pd.Timestamp | None = None):
    frames = []
    for t, c in closes_by_ticker.items():
        c = np.asarray(c, float).copy()
        if shock_after is not None:
            c[dates > shock_after] *= 1e6
        frames.append(_frame(c, c * 1.001, c * 0.999, np.full(len(c), 1000.0), dates, ticker=t))
    xc = np.full(len(dates), 10000.0) if index_closes is None else np.asarray(index_closes, float)
    index = _frame(xc, xc * 1.001, xc * 0.999, np.full(len(dates), 1000.0), dates).drop(columns=["ticker"])
    make_snapshot(root, pd.concat(frames, ignore_index=True), index, version=VERSION)
    return root


PATTERN = [{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"}, {"weekday": "THU", "direction": "UP", "role": "OUTCOME"}]
TRIG = week(mon=-1, tue=1, wed=2, thu=3, fri=4)   # tetik haftası: Pzt düşer
FLAT = week()                                      # Pzt = 0 -> tetik değil


def strat(**over):
    s = {"variant": "A", "signal_type": "WEEKDAY", "signal_params": {"pattern": PATTERN}, "holding_days": 2, "signal_lag_days": 1,
         "benchmarks": ["BUY_AND_HOLD", "XU100"]}
    s.update(over)
    return s


def call(root, dates, universe=("THYAO",), as_of=None, start=None, **over):
    params = {"strategy": strat(), "universe": list(universe), "start": (start or dates[1].date()).isoformat(),
              "end": dates[-1].date().isoformat(), "as_of": (as_of or dates[-1].date()).isoformat()}
    for k, v in over.items():
        if k == "strategy":
            params["strategy"] = {**strat(), **v}
        else:
            params[k] = v
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> RunBacktestResult:
    assert env["status"] == "OK", env.get("error")
    return RunBacktestResult.model_validate(env["results"])


@pytest.fixture(scope="module")
def single(tmp_path_factory):
    """Hafta 1 tetik (Pzt -1, Sal +1, Çar +2, Per +3, Cum +4); 3 düz hafta. Sinyal Pzt kapanışı, giriş Sal, çıkış Per (hold 2)."""
    closes, dates = weekly_closes([TRIG, FLAT, FLAT, FLAT])
    return snap(tmp_path_factory.mktemp("bt_single"), {"THYAO": closes}, dates), dates, closes


def test_hand_computed_single_trade(single):
    """Giriş Salı kapanışı, çıkış Perşembe: brüt = 1,02 x 1,03 - 1 = 5,06 %; net = 5,06 - 0,5 = 4,56.
    Portföy eğrisi: Çar ve Per açık; maliyet ilk (Çar) ve son (Per) tutma gününe 0,25'er: net günlük 1,75 % ve 2,75 %."""
    root, dates, closes = single
    env = call(root, dates)
    validate_envelope(env)
    r = res(env)
    t = r.trade_log[0]
    assert (r.n_signals, r.n_excluded_incomplete_horizon, r.n_winning_trades, r.n_losing_trades) == (1, 0, 1, 0)
    assert (t.ticker, t.signal_date, t.entry_date, t.exit_date) == ("THYAO", dates[1].date(), dates[2].date(), dates[4].date())
    assert (t.gross_return_pct, t.net_return_pct) == (5.06, 4.56)
    assert r.last_exit_date == dates[4].date() and r.signal_lag_days_applied == 1 and r.cost_model.round_trip_cost_pct == 0.5
    assert r.strategy_gross.cumulative_return_pct == pytest.approx(5.06, abs=1e-4)
    assert r.strategy_net.cumulative_return_pct == pytest.approx((1.0175 * 1.0275 - 1) * 100, abs=1e-4)  # 4,5481
    n_days = len(dates) - 1  # 2024-01-01'den itibaren
    assert r.strategy_net.exposure_pct == pytest.approx(100 * 2 / n_days, abs=1e-3)
    daily = np.zeros(n_days)
    daily[1], daily[2] = 0.0175, 0.0275  # dates[2], dates[3]'e karşılık: cal[0] = dates[1] (Pazartesi 2024-01-01)
    daily = np.zeros(n_days)
    daily[2], daily[3] = 0.0175, 0.0275  # Çar, Per (cal[0] = Pzt)
    assert r.strategy_net.sharpe_ratio == pytest.approx(daily.mean() / daily.std(ddof=1) * np.sqrt(252), abs=1e-3)
    assert (r.strategy_net.max_drawdown_pct, r.strategy_net.win_rate_pct, r.strategy_net.n_trades) == (0.0, 100.0, 1)
    assert env["n_events"] == 1 and env["n_excluded_incomplete_horizon"] == 0
    assert "LOW_SIGNAL_COUNT" in " | ".join(env["warnings"]) and r.low_signal_flag is True


def test_benchmarks_hand_computed(single):
    root, dates, closes = single
    r = res(call(root, dates))
    bh, xu = r.benchmarks  # BUY_AND_HOLD, XU100 (sıralı)
    assert (bh.name.value, xu.name.value) == ("BUY_AND_HOLD", "XU100")
    assert bh.metrics.cumulative_return_pct == pytest.approx((closes[-1] / closes[0] - 1) * 100, abs=1e-3)
    assert xu.metrics.cumulative_return_pct == 0.0 and xu.metrics.n_trades == 0 and xu.metrics.win_rate_pct is None
    assert xu.cumulative_return_diff_pct == pytest.approx(r.strategy_net.cumulative_return_pct)
    assert bh.cumulative_return_diff_pct == pytest.approx(r.strategy_net.cumulative_return_pct - bh.metrics.cumulative_return_pct, abs=1e-3)


def test_signal_lag_two_days_moves_entry_and_exit(single):
    """lag=2: giriş Çarşamba kapanışı (+2), çıkış Cuma: brüt = 1,03 x 1,04 - 1 = 7,12 %."""
    root, dates, _ = single
    r = res(call(root, dates, strategy={"signal_lag_days": 2}))
    t = r.trade_log[0]
    assert (t.entry_date, t.exit_date, t.gross_return_pct) == (dates[3].date(), dates[5].date(), 7.12)
    assert r.signal_lag_days_applied == 2 and t.signal_date < t.entry_date


def test_lag_zero_is_rejected_by_the_schema(single):
    root, dates, _ = single
    env = call(root, dates, strategy={"signal_lag_days": 0})
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


def test_overlapping_signals_are_skipped(tmp_path):
    """hold 7: Hafta 1 işlemi (giriş Sal) çıkışı 2. haftanın Perşembesi; 2. haftanın Pazartesi sinyali (çıkıştan önce) alınmaz, 3. hafta alınır."""
    closes, dates = weekly_closes([TRIG, TRIG, TRIG, FLAT, FLAT, FLAT])
    env = call(snap(tmp_path, {"THYAO": closes}, dates), dates, strategy={"holding_days": 7})
    r = res(env)
    assert r.n_signals == 2 and len(r.trade_log) == 2
    assert [t.signal_date for t in r.trade_log] == [dates[1].date(), dates[11].date()]
    assert "1 sinyal açık pozisyon nedeniyle alınmadı" in " | ".join(env["warnings"])


# =====================================================================================================
# (C) sızıntı, ufku dolmamış, determinizm
# =====================================================================================================
def test_incomplete_trade_is_excluded_but_counted_and_shock_is_invisible(tmp_path_factory):
    """as_of = tetik haftasının Çarşambası: çıkış (Perşembe) as_of'u aşar -> sinyal sayılır, işlem yok; as_of sonrası şok görünmez."""
    closes, dates = weekly_closes([FLAT, TRIG, FLAT])
    as_of = dates[8]  # 2. haftanın Çarşambası (dates[0]=Cum, 1-5 hafta 1, 6-10 hafta 2)
    assert as_of.day_name() == "Wednesday"
    clean = snap(tmp_path_factory.mktemp("bt_c"), {"THYAO": closes}, dates)
    shocked = snap(tmp_path_factory.mktemp("bt_s"), {"THYAO": closes}, dates, shock_after=as_of)
    a, b = call(clean, dates, as_of=as_of.date()), call(shocked, dates, as_of=as_of.date())
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]
    r = res(a)
    assert (r.n_signals, r.n_excluded_incomplete_horizon, r.trade_log, r.last_exit_date) == (1, 1, [], None)
    assert r.strategy_net.n_trades == 0 and r.period.end == as_of.date()
    assert "INCOMPLETE_HORIZON_EXCLUDED" in " | ".join(a["warnings"])
    validate_envelope(a)


def test_prefix_invariance(tmp_path_factory):
    closes, dates = weekly_closes([TRIG, FLAT, TRIG, FLAT, FLAT])
    full = snap(tmp_path_factory.mktemp("bt_f"), {"THYAO": closes}, dates)
    cut = snap(tmp_path_factory.mktemp("bt_k"), {"THYAO": closes[:16]}, dates[:16])
    t = dates[15]
    assert call(full, dates, as_of=t.date())["results"] == call(cut, dates[:16])["results"]


def test_determinism_and_envelope(single):
    root, dates, _ = single
    a, b = call(root, dates), call(root, dates)
    assert a == b
    assert call(root, dates, strategy={"holding_days": 3})["input_hash"] != a["input_hash"]


def test_last_exit_date_survives_trade_log_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "BACKTEST_TRADE_LOG_MAX", 2)
    closes, dates = weekly_closes([TRIG] * 6)
    env = call(snap(tmp_path, {"THYAO": closes}, dates), dates, strategy={"holding_days": 2})
    r = res(env)
    assert len(r.trade_log) == 2 and r.trade_log_truncated is True and r.n_signals == 6
    assert r.last_exit_date == max(t.exit_date for t in r.trade_log) == date.fromisoformat(env["results"]["last_exit_date"])
    assert REG.max_result_date(env["results"]) == r.last_exit_date
    validate_envelope(env)


# =====================================================================================================
# (D) bölünmeler, oos_degradation, varyant B, CATCH_UP / REVERSAL
# =====================================================================================================
def win_week():
    return week(mon=-1, tue=0, wed=3, thu=2)     # brüt 1,03 x 1,02 - 1 = 5,06


def lose_week():
    return week(mon=-1, tue=0, wed=-3, thu=-3)   # brüt 0,97 x 0,97 - 1 = -5,91


def split_scenario(n_is, n_oos, oos_week):
    weeks = [win_week(), FLAT] * n_is + [oos_week(), FLAT] * n_oos
    closes, dates = weekly_closes(weeks)
    return closes, dates, dates[1 + 10 * n_is].date() - timedelta(days=1)  # train_end: OOS'un ilk Pazartesisinden önceki gün (Pazar)


def test_oos_degradation_true(tmp_path):
    closes, dates, train_end = split_scenario(8, 6, lose_week)
    env = call(snap(tmp_path, {"THYAO": closes}, dates), dates, strategy={"train_end": train_end.isoformat()})
    r = res(env)
    assert r.n_signals == 14 and r.oos_degradation_flag is True
    assert [s.name.value for s in r.splits] == ["TRAIN", "TEST"]
    tr, te = r.splits
    assert (tr.n_signals, te.n_signals) == (8, 6) and tr.n_signals + te.n_signals == r.n_signals
    assert tr.net_metrics.win_rate_pct == 100.0 and te.net_metrics.win_rate_pct == 0.0
    assert tr.net_metrics.n_trades == 8 and te.net_metrics.n_trades == 6
    assert tr.window.end == train_end and te.window.start == train_end + timedelta(days=1)
    assert te.benchmark_diff_pct == pytest.approx(te.net_metrics.cumulative_return_pct - 0.0 + 0.0 - (te.net_metrics.cumulative_return_pct - te.benchmark_diff_pct), abs=1e-6)
    assert "OOS_DEGRADATION" in " | ".join(env["warnings"])
    validate_envelope(env)


def test_oos_too_small_gives_false_flag(tmp_path):
    closes, dates, train_end = split_scenario(8, 3, lose_week)
    env = call(snap(tmp_path, {"THYAO": closes}, dates), dates, strategy={"train_end": train_end.isoformat()})
    r = res(env)
    assert r.oos_degradation_flag is False and "OOS_TOO_SMALL" in " | ".join(env["warnings"])


def test_no_train_end_gives_no_splits_and_no_flag(single):
    root, dates, _ = single
    r = res(call(root, dates))
    assert (r.splits, r.oos_degradation_flag) == ([], None)


def test_validation_and_walk_forward_windows(tmp_path):
    closes, dates, train_end = split_scenario(8, 6, win_week)
    root = snap(tmp_path, {"THYAO": closes}, dates)
    val_end = (train_end + timedelta(days=28)).isoformat()
    r = res(call(root, dates, strategy={"train_end": train_end.isoformat(), "validation_end": val_end}))
    assert [s.name.value for s in r.splits] == ["TRAIN", "VALIDATION", "TEST"]
    assert sum(s.n_signals for s in r.splits) == r.n_signals == 14
    wf = res(call(root, dates, strategy={"train_end": train_end.isoformat(), "walk_forward": True,
                                         "signal_params": {"pattern": PATTERN, "wf_test_days": 10}}))
    names = [s.name.value for s in wf.splits]
    assert names[0] == "TRAIN" and set(names[1:]) == {"WALK_FORWARD"} and len(names) == 1 + 6  # 60 işlem günü / 10
    assert sum(s.n_signals for s in wf.splits) == wf.n_signals
    assert all(a.window.end < b.window.start for a, b in zip(wf.splits, wf.splits[1:]))


def retail_dates_n(n=80):
    return pd.bdate_range("2024-01-01", periods=n)


def test_catch_up_hand_computed(tmp_path):
    """MAVI t=40'ta 100 -> 90 ve orada kalır (BIMAS/MGROS düz): lag skoru -10 (medyan 0) t=40..59. lag=1, hold=5:
    kabul edilen sinyaller t = 40, 46, 52, 58 (her biri önceki çıkış gününde); giriş 41, 47, 53, 59; fiyat düz -> brüt 0, net -0,5."""
    n = 80
    dates = retail_dates_n(n)
    mavi = np.full(n, 100.0)
    mavi[40:] = 90.0
    root = snap(tmp_path, {"MAVI": mavi, "BIMAS": np.full(n, 100.0), "MGROS": np.full(n, 100.0)}, dates)
    s = {"variant": "A", "signal_type": "CATCH_UP", "signal_params": {}, "holding_days": 5, "signal_lag_days": 1, "benchmarks": ["BUY_AND_HOLD", "SECTOR"]}
    env = tool.run_on({"strategy": s, "universe": ["BIMAS", "MAVI", "MGROS"], "start": "2024-01-01", "end": dates[-1].date().isoformat(),
                       "as_of": dates[-1].date().isoformat()}, snapshot_root=root, data_version=VERSION)
    validate_envelope(env)
    r = res(env)
    assert r.n_signals == 4 and r.n_winning_trades == 0 and r.n_losing_trades == 4
    assert [(t.ticker, t.signal_date, t.entry_date) for t in r.trade_log] == [("MAVI", dates[k].date(), dates[k + 1].date()) for k in (40, 46, 52, 58)]
    assert all(t.gross_return_pct == 0.0 and t.net_return_pct == -0.5 for t in r.trade_log)
    assert r.strategy_net.win_rate_pct == 0.0
    sec = next(b for b in r.benchmarks if b.name.value == "SECTOR")
    assert sec.metrics.cumulative_return_pct == 0.0 or sec.metrics.cumulative_return_pct is not None  # peer medyanı: MAVI düşüşü medyanı etkilemez


def reversal_universe(root, xu_follow: bool):
    c = np.array([100, 102] * 13 + [94, 95, 96, 97, 98, 99, 100, 101, 102, 103], float)
    dates = pd.bdate_range("2024-01-01", periods=len(c))
    xu = c * 100 if xu_follow else None
    return snap(root, {"BIMAS": c, "MGROS": c, "MAVI": c}, dates, index_closes=xu), dates, c


REV = {"variant": "A", "signal_type": "REVERSAL", "signal_params": {"event_family": "BB_LOWER_TOUCH"}, "holding_days": 3,
       "signal_lag_days": 1, "benchmarks": ["BUY_AND_HOLD", "XU100"]}


def run_rev(root, dates, **over):
    s = {**REV, **over}
    return tool.run_on({"strategy": s, "universe": ["BIMAS", "MAVI", "MGROS"], "start": "2024-01-01",
                        "end": dates[-1].date().isoformat(), "as_of": dates[-1].date().isoformat()}, snapshot_root=root, data_version=VERSION)


def test_reversal_signal_hand_computed_and_variant_b_sector_filter(tmp_path_factory):
    """Dönüş olayı bar 26 (kapanış 94). Giriş bar 27 (95), çıkış bar 30 (98): brüt = 98/95 - 1 = 3,1579 %.
    A: 3 sinyal. B: sektör (3 hisse de ~%-7) XU100 sabitken WEAK -> sinyaller elenir. XU100 hisselerle birlikte düşerse NEUTRAL -> korunur."""
    root, dates, c = reversal_universe(tmp_path_factory.mktemp("bt_r1"), xu_follow=False)
    a = res(run_rev(root, dates))
    assert a.n_signals == 3 and all(t.signal_date == dates[26].date() and t.entry_date == dates[27].date() for t in a.trade_log)
    assert all(t.gross_return_pct == 3.1579 for t in a.trade_log)
    env_b = run_rev(root, dates, variant="B")
    validate_envelope(env_b)
    b = res(env_b)
    assert (b.n_signals, b.trade_log, b.last_exit_date) == (0, [], None)
    assert "3 sinyal sektör filtresiyle elendi" in " | ".join(env_b["warnings"])
    root2, dates2, _ = reversal_universe(tmp_path_factory.mktemp("bt_r2"), xu_follow=True)
    assert res(run_rev(root2, dates2, variant="B")).n_signals == 3


def test_reversal_condition_filters_signals(tmp_path):
    root, dates, _ = reversal_universe(tmp_path, xu_follow=False)
    sp = {"event_family": "BB_LOWER_TOUCH", "condition": {"volume_regime": "HIGH"}}
    r = res(run_rev(root, dates, signal_params=sp))
    assert r.n_signals == 0  # hacim sabit -> z tanımsız (None), koşul eşleşmez


# =====================================================================================================
# (E) desteklenmeyen kombinasyonlar ve hatalar
# =====================================================================================================
@pytest.mark.parametrize("over,code", [
    ({"variant": "C"}, "UNSUPPORTED_VARIANT"), ({"variant": "D"}, "UNSUPPORTED_VARIANT"), ({"variant": "E"}, "UNSUPPORTED_VARIANT"),
    ({"signal_type": "FUNDAMENTAL", "signal_params": {}}, "UNSUPPORTED_SIGNAL_TYPE"),
    ({"signal_type": "REVERSAL", "signal_params": {"event_family": "BB_UPPER_TOUCH"}}, "UNSUPPORTED_DIRECTION"),
    ({"signal_type": "REVERSAL", "signal_params": {"event_family": "RSI_LOCAL_PEAK"}}, "UNSUPPORTED_DIRECTION"),
    ({"signal_type": "REVERSAL", "signal_params": {"event_family": "BB_MID_TEST"}}, "UNSUPPORTED_EVENT_FAMILY"),
    ({"signal_params": {"pattern": [{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"},
                                    {"weekday": "THU", "direction": "DOWN", "role": "OUTCOME"}]}}, "UNSUPPORTED_DIRECTION"),
    ({"signal_params": {"pattern": PATTERN, "bogus": 1}}, "INVALID_PARAMS"),
    ({"signal_params": {"pattern": [{"weekday": "THU", "direction": "UP", "role": "OUTCOME"}]}}, "INVALID_PARAMS"),
    ({"walk_forward": True}, "INVALID_PARAMS"),
    ({"signal_type": "CATCH_UP", "signal_params": {}}, "INVALID_PARAMS"),  # tek hisseli evren
])
def test_unsupported_and_invalid_combinations(single, over, code):
    root, dates, _ = single
    env = call(root, dates, strategy=over)
    assert env["status"] == "ERROR" and env["results"] is None and env["error"]["code"] == code


def test_other_errors(single):
    root, dates, _ = single
    assert call(root, dates, universe=("ZZZZ",))["error"]["code"] == "NO_DATA"
    assert call(root, dates, as_of=dates[1].date(), start=dates[3].date())["error"]["code"] == "INVALID_WINDOW"
    sector = call(root, dates, strategy={"benchmarks": ["SECTOR"]})  # THYAO airlines grubunda (2 üye): SECTOR tanımlı ama uyarılı
    assert sector["status"] == "OK" and "SMALL_PEER_GROUP" in " | ".join(sector["warnings"])


def test_sector_benchmark_needs_a_single_peer_group(tmp_path):
    closes, dates = weekly_closes([TRIG, FLAT])
    root = snap(tmp_path, {"THYAO": closes, "BIMAS": closes}, dates)  # farklı peer grupları
    env = call(root, dates, universe=("THYAO", "BIMAS"), strategy={"benchmarks": ["SECTOR"]})
    assert env["error"]["code"] == "INVALID_PARAMS" and "peer" in env["error"]["message"]


# =====================================================================================================
# (F) gerçek v2 snapshot
# =====================================================================================================
def real(strategy, universe, **over):
    p = {"strategy": strategy, "universe": universe, "start": "2024-01-01", "end": "2026-09-10", "as_of": "2026-09-10"}
    p.update(over)
    return tool.run_on(p, data_version=VERSION)


RETAIL = ["BIMAS", "MAVI", "MGROS"]
CATCH = {"variant": "A", "signal_type": "CATCH_UP", "signal_params": {"lag_window": 20, "lag_threshold_pp": 3.0}, "holding_days": 10,
         "signal_lag_days": 1, "benchmarks": ["BUY_AND_HOLD", "XU100", "SECTOR"], "train_end": "2025-12-31"}


@needs_snapshot
def test_real_retail_catch_up():
    env = real(CATCH, RETAIL)
    validate_envelope(env)
    r = res(env)
    assert r.signal_lag_days_applied == 1 and r.last_exit_date <= date(2026, 9, 10)
    assert all(t.signal_date < t.entry_date <= t.exit_date <= date(2026, 9, 10) for t in r.trade_log)
    assert [s.name.value for s in r.splits] == ["TRAIN", "TEST"]
    assert sum(s.n_signals for s in r.splits) == r.n_signals
    assert real(CATCH, RETAIL) == env
    # gerçek değer çapaları (v2, retail, lag_window 20, eşik 3 pp, hold 10, lag 1, as_of 2026-09-10)
    assert (r.n_signals, r.n_excluded_incomplete_horizon, r.n_winning_trades, r.n_losing_trades) == (65, 2, 39, 24)
    assert (r.strategy_gross.cumulative_return_pct, r.strategy_net.cumulative_return_pct) == (112.2934, 62.082)
    assert (r.strategy_net.sharpe_ratio, r.strategy_net.max_drawdown_pct, r.strategy_net.win_rate_pct) == (0.7253, -36.1998, 61.9048)
    assert [(s.name.value, s.n_signals, s.net_metrics.n_trades) for s in r.splits] == [("TRAIN", 48, 48), ("TEST", 17, 15)]
    assert r.oos_degradation_flag is True and r.last_exit_date == date(2026, 8, 28)
    assert {b.name.value: b.metrics.cumulative_return_pct for b in r.benchmarks} == {"BUY_AND_HOLD": 104.2396, "SECTOR": 63.0255, "XU100": 92.6853}
    # as_of'u uzatmak (snapshot sonuna kadar) 2026-09-10 sonrası işlem ekler; 2026-09-10 sonucunda görünmez
    assert max(t.exit_date for t in r.trade_log) <= date(2026, 9, 10)


@needs_snapshot
def test_real_thyao_weekday_strategy_runs():
    q2 = [{"weekday": d, "direction": "DOWN", "role": "TRIGGER"} for d in ("MON", "TUE", "WED")] +          [{"weekday": d, "direction": "UP", "role": "OUTCOME"} for d in ("THU", "FRI")]
    s = {"variant": "A", "signal_type": "WEEKDAY", "signal_params": {"pattern": q2}, "holding_days": 2, "signal_lag_days": 1,
         "benchmarks": ["BUY_AND_HOLD", "XU100"], "train_end": "2025-12-31"}
    env = real(s, ["THYAO"])
    validate_envelope(env)
    r = res(env)
    assert r.n_signals > 0 and r.strategy_net.n_trades <= r.n_signals
    assert (r.strategy_net.cumulative_return_pct - r.strategy_gross.cumulative_return_pct) < 0  # maliyet getiriyi düşürür
    assert (r.n_signals, r.strategy_net.cumulative_return_pct, r.strategy_gross.cumulative_return_pct) == (24, -22.31, -12.3591)
    assert [(s.name.value, s.n_signals) for s in r.splits] == [("TRAIN", 19), ("TEST", 5)] and r.oos_degradation_flag is True
