"""Volatilite: Bollinger, ATR (Wilder), getiri ve gerçekleşen volatilite."""
from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import SHARPE_ANNUALIZATION_DAYS
from tools.indicators._util import as_float_array, check_window, rolling_apply


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    """Bollinger bantları: orta = SMA(window); üst/alt = orta ± num_std * std. std = POPÜLASYON (ddof=0, klasik tanım).

    pct_b = (close - alt)/(üst - alt) (birimsiz oran; alt bant=0, üst bant=1; bant genişliği 0 ise NaN).
    bandwidth_pct = (üst - alt)/orta * 100. Isınma: window bar.
    """
    check_window(window, "window", minimum=2)
    if num_std <= 0:
        raise ValueError("num_std > 0 olmalı")
    mid = rolling_apply(close, window, np.mean)
    sd = rolling_apply(close, window, np.std)
    upper, lower = mid + num_std * sd, mid - num_std * sd
    width = upper - lower
    pct_b = ((close - lower) / width).where(width > 0)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b,
                         "bandwidth_pct": width / mid * 100.0}, index=close.index)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """TR_t = max(h-l, |h-c_{t-1}|, |l-c_{t-1}|). İlk bar için önceki kapanış yok -> NaN."""
    pc = close.shift(1)
    return pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1, skipna=False)


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ATR. TOHUM: ilk `period` TR'nin (idx 1..period) basit ortalaması; sonra (ATR*(period-1)+TR)/period.
    Isınma: period + 1 bar."""
    check_window(period, "period")
    for s, n in ((high, "high"), (low, "low"), (close, "close")):
        as_float_array(s, n)
    tr = true_range(high, low, close).to_numpy()
    out = np.full(len(tr), np.nan)
    if len(tr) > period:
        atr = tr[1:period + 1].mean()
        out[period] = atr
        for i in range(period + 1, len(tr)):
            atr = (atr * (period - 1) + tr[i]) / period
            out[i] = atr
    return pd.Series(out, index=close.index)


def simple_returns(close: pd.Series, horizon: int = 1) -> pd.Series:
    """Geriye dönük basit getiri (kesir, ör. 0.012): c_t / c_{t-horizon} - 1. Isınma: horizon + 1 bar."""
    check_window(horizon, "horizon")
    return close / close.shift(horizon) - 1.0


def rolling_volatility(close: pd.Series, window: int = 20,
                       annualization_days: int = SHARPE_ANNUALIZATION_DAYS) -> pd.Series:
    """Yıllıklandırılmış gerçekleşen volatilite (kesir): std(1 günlük log getiri, ddof=1) * sqrt(annualization_days).
    Isınma: window + 1 bar."""
    check_window(window, "window", minimum=2)
    logret = np.log(close / close.shift(1))
    sd = rolling_apply(logret.iloc[1:], window, lambda w, axis: np.std(w, axis=axis, ddof=1))
    return sd.reindex(close.index) * np.sqrt(annualization_days)
