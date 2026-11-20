"""Durum sınıflayıcıları (supertrend, ichimoku_position, kama_slope, volume_regime) ve katalog ısınma tutarlılığı."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config import settings
from schemas.enums import IchimokuState, IndicatorName, KamaSlope, SupertrendState, VolumeRegime
from schemas.params import IndicatorConfig
from tools.indicators import states
from tools.indicators.catalog import compute


def S(*v):
    return pd.Series([float(x) for x in v], index=pd.bdate_range("2024-01-01", periods=len(v)))


def test_kama_slope_boundaries_are_flat_and_units_are_percent():
    # KAMA 100 -> 100.10 (+%0.10: birim yüzde), sonra +%0.11 (RISING), -%0.11 (FALLING); ilk gün ve NaN -> None
    k = S(100.0, 100.10, 100.10 * 1.0011, 100.10 * 1.0011 * (1 - 0.0011), 100.0, np.nan)
    pct = states.kama_slope_pct(k)
    assert pct.iloc[1] == pytest.approx(0.10)
    out = states.kama_slope_state(k, settings.KAMA_FLAT_SLOPE_PCT).tolist()
    assert out[0] is None and out[5] is None                       # ilk gün (önceki yok) ve NaN -> None
    assert out[2] == KamaSlope.RISING and out[3] == KamaSlope.FALLING


def test_kama_slope_exact_threshold_is_flattening():
    k = S(100.0, 100.0 * (1 + 0.0009), 100.0 * (1 + 0.0009) * (1 - 0.0009))
    assert states.kama_slope_state(k, 0.10).tolist() == [None, KamaSlope.FLATTENING, KamaSlope.FLATTENING]


def test_volume_regime_thresholds_and_boundaries():
    z = S(-1.5, -1.0, -0.99, 0.0, 1.0, 1.01, np.nan)
    assert states.volume_regime(z, settings.VOLUME_HIGH_Z, settings.VOLUME_LOW_Z).tolist() == [
        VolumeRegime.LOW, VolumeRegime.NORMAL, VolumeRegime.NORMAL, VolumeRegime.NORMAL, VolumeRegime.NORMAL,
        VolumeRegime.HIGH, None]


def test_ichimoku_position_above_in_below_and_boundary():
    a, b = S(10, 10, 10, 10, np.nan), S(12, 12, 12, 12, 12)      # bulut [10, 12]
    close = S(13, 11, 9, 12, 11)
    assert states.ichimoku_position(close, a, b).tolist() == [
        IchimokuState.ABOVE_CLOUD, IchimokuState.IN_CLOUD, IchimokuState.BELOW_CLOUD, IchimokuState.IN_CLOUD, None]


def test_ichimoku_cloud_uses_min_max_when_spans_cross():
    a, b = S(12, 12), S(10, 10)  # A > B: bulut yine [10, 12]
    assert states.ichimoku_position(S(11, 9), a, b).tolist() == [IchimokuState.IN_CLOUD, IchimokuState.BELOW_CLOUD]


def test_supertrend_state_mapping():
    assert states.supertrend_state(S(1, -1, np.nan)).tolist() == [SupertrendState.BULLISH, SupertrendState.BEARISH, None]


@pytest.mark.parametrize("cfg", [
    IndicatorConfig(),
    IndicatorConfig(sma_windows=[5, 7], ema_windows=[3], rsi_period=5, macd_fast=3, macd_slow=7, macd_signal=4,
                    bollinger_window=6, bollinger_std=1.5, atr_period=4, kama_er_window=5, kama_fast=2, kama_slow=20,
                    supertrend_atr_period=3, supertrend_multiplier=2.5, ichimoku_tenkan=3, ichimoku_kijun=5,
                    ichimoku_senkou_b=8, volume_zscore_window=4),
])
def test_catalog_analytic_warmup_equals_empirical_first_valid_bar(cfg):
    """Her kolon için: ilk geçerli satırın sırası (1 tabanlı) == warmup_bars, ve bundan sonra hiç NaN yok."""
    rng = np.random.default_rng(3)
    n = 300
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, n))), index=idx)
    df = pd.DataFrame({"close": close, "high": close * 1.01, "low": close * 0.99,
                       "volume": pd.Series(rng.lognormal(10, 0.3, n), index=idx)})
    comp = compute(df, cfg, list(IndicatorName), kama_flat_pct=0.1, volume_high_z=1.0, volume_low_z=-1.0)
    assert len(comp.columns) >= 20
    names = [c.name for c in comp.columns]
    assert len(names) == len(set(names))
    for c in comp.columns:
        valid = c.values.notna().to_numpy()
        first = int(np.argmax(valid))
        assert first + 1 == c.warmup_bars, c.name
        assert valid[first:].all(), c.name
    assert set(comp.states) == {"supertrend", "ichimoku_position", "kama_slope", "volume_regime"}


def test_catalog_only_requested_states():
    n = 120
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = pd.Series(np.linspace(100, 120, n), index=idx)
    df = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1, "volume": 1000.0 + np.arange(n)}, index=idx)
    comp = compute(df, IndicatorConfig(), [IndicatorName.RSI, IndicatorName.KAMA], kama_flat_pct=0.1,
                   volume_high_z=1.0, volume_low_z=-1.0)
    assert set(comp.states) == {"kama_slope"}
