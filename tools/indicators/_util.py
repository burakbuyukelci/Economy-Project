"""Gösterge kütüphanesi ortak yardımcıları (saf pandas/numpy, ağ yok).

Tasarım: tüm göstergeler NEDENSELDİR; `t` günündeki değer yalnızca `<= t` verisinden hesaplanır
(tek istisna: Ichimoku `chikou_plotted`, bkz. trend.ichimoku). Pencereli ortalama/std/max/min iki geçişli
numpy ile hesaplanır (kayan toplam hatası yok, aynı girdi -> bit düzeyinde aynı çıktı).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view


def as_float_array(s: pd.Series, name: str = "seri", allow_leading_nan: bool = False) -> np.ndarray:
    """Seriyi float64 diziye çevirir. Ara/sondaki NaN yasak; baştaki NaN yalnız `allow_leading_nan` ile."""
    x = s.to_numpy(dtype="float64", copy=True)
    nan = np.isnan(x)
    if nan.any():
        first_valid = int(np.argmax(~nan)) if (~nan).any() else len(x)
        if not allow_leading_nan or nan[first_valid:].any():
            raise ValueError(f"{name}: NaN içeriyor (veri temizliği çağıran tarafın sorumluluğunda)")
    return x


def check_window(window: int, name: str = "window", minimum: int = 1) -> None:
    if not isinstance(window, (int, np.integer)) or window < minimum:
        raise ValueError(f"{name} >= {minimum} bir tamsayı olmalı, alındı: {window!r}")


def windows(x: np.ndarray, w: int) -> np.ndarray:
    """(n-w+1, w) pencere görünümü; n < w ise boş (0, w)."""
    if len(x) < w:
        return np.empty((0, w))
    return sliding_window_view(x, w)


def rolling_apply(s: pd.Series, w: int, func) -> pd.Series:
    """Her gün için son `w` gün (bugün dahil) üzerinde func(pencereler, axis=1); ilk w-1 gün NaN."""
    x = s.to_numpy(dtype="float64")
    out = np.full(len(x), np.nan)
    win = windows(x, w)
    if len(win):
        out[w - 1:] = func(win, axis=1)
    return pd.Series(out, index=s.index)
