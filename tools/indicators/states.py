"""Kategorik gösterge durumları (vektörel). Tanımlar: docs/data_dictionary.md "Göstergeler". Eşikler: config/settings.py,
gerekçe: docs/calibration_thresholds.md. NaN (ısınma) -> None. Sınıflar schemas.enums içindeki mevcut enum'lardır."""
from __future__ import annotations

import numpy as np
import pandas as pd

from schemas.enums import IchimokuState, KamaSlope, SupertrendState, VolumeRegime


def _series(index: pd.Index, labels: list) -> pd.Series:
    return pd.Series(labels, index=index, dtype="object")


def supertrend_state(direction: pd.Series) -> pd.Series:
    """direction +1 -> BULLISH (çizgi fiyatın altında), -1 -> BEARISH (çizgi fiyatın üstünde)."""
    return _series(direction.index, [None if np.isnan(d) else (SupertrendState.BULLISH if d > 0 else SupertrendState.BEARISH)
                                     for d in direction.to_numpy()])


def ichimoku_position(close: pd.Series, senkou_a: pd.Series, senkou_b: pd.Series) -> pd.Series:
    """Bulut = [min(A,B), max(A,B)] (günün kendi, 26 bar önceden hesaplanıp ileri kaydırılmış değerleri).
    close > üst -> ABOVE_CLOUD ; close < alt -> BELOW_CLOUD ; sınırlar dahil aralık -> IN_CLOUD."""
    top, bottom = np.maximum(senkou_a, senkou_b), np.minimum(senkou_a, senkou_b)
    out = []
    for c, t, b in zip(close.to_numpy(), top.to_numpy(), bottom.to_numpy()):
        if np.isnan(t) or np.isnan(b):
            out.append(None)
        elif c > t:
            out.append(IchimokuState.ABOVE_CLOUD)
        elif c < b:
            out.append(IchimokuState.BELOW_CLOUD)
        else:
            out.append(IchimokuState.IN_CLOUD)
    return _series(close.index, out)


def kama_slope_pct(kama: pd.Series) -> pd.Series:
    """KAMA'nın 1 günlük % değişimi: (KAMA_t / KAMA_{t-1} - 1) * 100."""
    return (kama / kama.shift(1) - 1.0) * 100.0


def kama_slope_state(kama: pd.Series, flat_pct: float) -> pd.Series:
    """slope > +flat_pct -> RISING ; slope < -flat_pct -> FALLING ; aksi (sınır dahil) FLATTENING."""
    out = []
    for s in kama_slope_pct(kama).to_numpy():
        if np.isnan(s):
            out.append(None)
        elif s > flat_pct:
            out.append(KamaSlope.RISING)
        elif s < -flat_pct:
            out.append(KamaSlope.FALLING)
        else:
            out.append(KamaSlope.FLATTENING)
    return _series(kama.index, out)


def volume_regime(z: pd.Series, high_z: float, low_z: float) -> pd.Series:
    """z > high_z -> HIGH ; z < low_z -> LOW ; aksi (sınır dahil) NORMAL."""
    out = []
    for v in z.to_numpy():
        if np.isnan(v):
            out.append(None)
        elif v > high_z:
            out.append(VolumeRegime.HIGH)
        elif v < low_z:
            out.append(VolumeRegime.LOW)
        else:
            out.append(VolumeRegime.NORMAL)
    return _series(z.index, out)
