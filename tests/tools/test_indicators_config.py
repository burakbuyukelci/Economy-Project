"""Gösterge eşikleri ve tanım tutarlılığı: config değerleri, IndicatorConfig varsayılanları, ortak std tanımı (ddof=0)."""
from __future__ import annotations

import inspect

import numpy as np
import pandas as pd
import pytest

from config import settings
from schemas.params import IndicatorConfig
from tools.indicators import bollinger, kama, macd, rsi_wilder, supertrend, volume_zscore, atr_wilder, ichimoku


def test_approved_threshold_values():
    assert settings.KAMA_FLAT_SLOPE_PCT == 0.10
    assert settings.VOLUME_HIGH_Z == 1.0 and settings.VOLUME_LOW_Z == -1.0
    assert settings.VOLATILITY_WINDOW == 20 and settings.RETURN_HORIZONS == [1, 5, 20]


def test_threshold_sanity():
    assert settings.KAMA_FLAT_SLOPE_PCT > 0 and settings.VOLUME_LOW_Z < 0 < settings.VOLUME_HIGH_Z


def test_library_signature_defaults_equal_indicator_config():
    """Kütüphane varsayılanları, config'teki (schemas.params.IndicatorConfig) tek kaynakla aynı olmalı."""
    c = IndicatorConfig()

    def d(fn, name):
        return inspect.signature(fn).parameters[name].default

    assert d(rsi_wilder, "period") == c.rsi_period
    assert (d(macd, "fast"), d(macd, "slow"), d(macd, "signal")) == (c.macd_fast, c.macd_slow, c.macd_signal)
    assert (d(bollinger, "window"), d(bollinger, "num_std")) == (c.bollinger_window, c.bollinger_std)
    assert d(atr_wilder, "period") == c.atr_period
    assert (d(kama, "er_window"), d(kama, "fast"), d(kama, "slow")) == (c.kama_er_window, c.kama_fast, c.kama_slow)
    assert (d(supertrend, "atr_period"), d(supertrend, "multiplier")) == (c.supertrend_atr_period, c.supertrend_multiplier)
    assert (d(ichimoku, "tenkan"), d(ichimoku, "kijun"), d(ichimoku, "senkou_b")) == (
        c.ichimoku_tenkan, c.ichimoku_kijun, c.ichimoku_senkou_b)
    assert d(volume_zscore, "window") == c.volume_zscore_window


def test_bollinger_and_volume_zscore_use_same_population_std_ddof0():
    """Aynı seri, aynı pencere: Bollinger'ın std'si (üst-orta)/k, hacim z-skorunun paydasıyla birebir aynı ve ddof=0."""
    rng = np.random.default_rng(7)
    x = pd.Series(rng.lognormal(3, 0.3, 120))
    w, k = 20, 2.0
    bb = bollinger(x, w, k)
    bb_std = (bb["upper"] - bb["mid"]) / k
    z = volume_zscore(x, w)
    z_std = (x - bb["mid"]) / z                       # z = (x-ort)/std  ->  std = (x-ort)/z
    ref0 = x.rolling(w).std(ddof=0)
    ref1 = x.rolling(w).std(ddof=1)
    ok = z.notna() & (z.abs() > 1e-6)
    np.testing.assert_allclose(bb_std.dropna(), ref0.dropna(), rtol=1e-10)
    np.testing.assert_allclose(z_std[ok], bb_std[ok], rtol=1e-8)
    assert not np.allclose(bb_std.dropna(), ref1.dropna())   # ddof=1 DEĞİL
