"""Hacim göstergeleri."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.indicators._util import check_window, rolling_apply


def volume_zscore(volume: pd.Series, window: int = 20) -> pd.Series:
    """z_t = (v_t - ort) / std ; ort ve std (POPÜLASYON, ddof=0) son `window` günden, BUGÜN DAHİL. std=0 ise NaN.
    Isınma: window bar."""
    check_window(window, "window", minimum=2)
    mean = rolling_apply(volume, window, np.mean)
    sd = rolling_apply(volume, window, np.std)
    return ((volume - mean) / sd).where(sd > 0)
