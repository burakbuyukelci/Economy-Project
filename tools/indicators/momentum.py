"""Momentum: RSI (Wilder)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.indicators._util import as_float_array, check_window


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI (0-100). TOHUM: ilk `period` değişimin basit ortalaması; sonra Wilder düzleştirmesi
    avg_t = (avg_{t-1}*(period-1) + x_t)/period. RSI = 100 - 100/(1+RS), RS = avg_kazanç/avg_kayıp.
    Kayıp 0 ise RSI=100; kazanç da 0 ise (düz seri) 50. Isınma: period + 1 bar.
    """
    check_window(period, "period", minimum=2)
    c = as_float_array(close, "close")
    out = np.full(len(c), np.nan)
    if len(c) > period:
        delta = np.diff(c)
        gain, loss = np.where(delta > 0, delta, 0.0), np.where(delta < 0, -delta, 0.0)
        ag, al = gain[:period].mean(), loss[:period].mean()
        out[period] = _rsi(ag, al)
        for i in range(period + 1, len(c)):
            ag = (ag * (period - 1) + gain[i - 1]) / period
            al = (al * (period - 1) + loss[i - 1]) / period
            out[i] = _rsi(ag, al)
    return pd.Series(out, index=close.index)


def _rsi(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
