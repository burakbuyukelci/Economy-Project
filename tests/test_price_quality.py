"""Fiyat sıçraması şiddeti: hisseye özgü -> HARD, piyasa geneli -> SOFT; as_of sızıntısı yok."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from schemas.enums import DQCode, DQSeverity, GateStatus
from tools.price_quality import classify_price_jumps, gate_from_issues


def make_stocks(n_tickers=10, n_days=8, jumps=None):
    """jumps: {(ticker, day_index): çarpan}. Düz 100 fiyat; belirtilen gün fiyat çarpanla değişir ve kalır."""
    dates = pd.bdate_range("2026-09-01", periods=n_days)
    frames = []
    for k in range(n_tickers):
        tk = f"TCK{k}"
        px = pd.Series(100.0, index=range(n_days))
        for (jt, jd), mult in (jumps or {}).items():
            if jt == tk:
                px.iloc[jd:] = 100.0 * mult
        frames.append(pd.DataFrame({"ticker": tk, "date": dates, "close": px.values, "adj_close": px.values}))
    return pd.concat(frames, ignore_index=True)


def classify(stocks, tickers, start="2026-09-01", end="2026-09-30", as_of="2026-09-30", **kw):
    return classify_price_jumps(stocks, tickers, date.fromisoformat(start), date.fromisoformat(end),
                                date.fromisoformat(as_of), **kw)


def test_idiosyncratic_jump_is_hard_block():
    s = make_stocks(jumps={("TCK3", 4): 1 / 11})  # tek hisse -%90.9
    issues = classify(s, ["TCK3"])
    assert len(issues) == 1
    i = issues[0]
    assert i.severity == DQSeverity.HARD and i.code == DQCode.WRONG_TICKER_OR_BROKEN_HISTORY
    assert i.ticker == "TCK3" and i.date == date(2026, 9, 7) and i.value == pytest.approx(-90.9091, abs=1e-3)
    assert gate_from_issues(issues) == GateStatus.HARD_BLOCK


def test_market_wide_jump_is_soft():
    s = make_stocks(jumps={(f"TCK{k}", 4): 1.2 for k in range(6)})  # 10 hissenin 6'sı (%60) aynı gün +%20
    issues = classify(s, ["TCK0"])
    assert len(issues) == 1 and issues[0].severity == DQSeverity.SOFT
    assert issues[0].code == DQCode.PRICE_JUMP_OVER_LIMIT
    assert gate_from_issues(issues) == GateStatus.PASS_WITH_WARNINGS


def test_market_wide_threshold_boundary_is_inclusive_at_half():
    five = make_stocks(jumps={(f"TCK{k}", 4): 1.2 for k in range(5)})   # tam %50 -> piyasa geneli
    assert classify(five, ["TCK0"])[0].severity == DQSeverity.SOFT
    four = make_stocks(jumps={(f"TCK{k}", 4): 1.2 for k in range(4)})   # %40 -> hisseye özgü
    assert classify(four, ["TCK0"])[0].severity == DQSeverity.HARD


def test_tolerance_prevents_flag_on_limit_moves():
    s = make_stocks(jumps={("TCK1", 4): 1.10})  # tam +%10 (limit): bayrak yok
    assert classify(s, ["TCK1"]) == []
    assert gate_from_issues([]) == GateStatus.PASS


def test_only_requested_tickers_and_range_are_reported():
    s = make_stocks(jumps={("TCK3", 4): 1 / 11})
    assert classify(s, ["TCK0"]) == []                                   # başka hisse
    assert classify(s, ["TCK3"], start="2026-09-08") == []               # sıçrama aralık öncesi (09-07)
    assert len(classify(s, ["TCK3"], end="2026-09-07")) == 1             # aralığın son günü dahil


def test_jump_after_as_of_never_reported_and_not_counted_in_share():
    s = make_stocks(jumps={("TCK3", 6): 1 / 11})  # 2026-09-09'da sıçrama
    assert classify(s, ["TCK3"], as_of="2026-09-08") == []               # as_of öncesi görünmez
    assert len(classify(s, ["TCK3"], as_of="2026-09-09")) == 1           # as_of günü dahil


def test_share_uses_only_tickers_with_data_that_day():
    s = make_stocks(jumps={("TCK3", 4): 1 / 11, ("TCK4", 4): 1 / 11})
    # 10 hisseden 8'inin o gün verisi yok -> payda 2, 2/2 = %100 -> piyasa geneli sayılır
    d = pd.Timestamp("2026-09-07")
    drop = s[(s["date"] == d) & (~s["ticker"].isin(["TCK3", "TCK4"]))].index
    s = s.drop(drop)
    # eksik günlerde pct_change önceki mevcut güne göre hesaplanır; sıçrama yine görünür
    issues = classify(s, ["TCK3"])
    assert issues and issues[0].severity == DQSeverity.SOFT


def test_gate_priority_hard_over_soft():
    s = make_stocks(jumps={("TCK3", 4): 1 / 11})
    hard = classify(s, ["TCK3"])
    soft = classify(make_stocks(jumps={(f"TCK{k}", 4): 1.2 for k in range(6)}), ["TCK0"])
    assert gate_from_issues(hard + soft) == GateStatus.HARD_BLOCK
