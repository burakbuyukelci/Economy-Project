"""Gösterge kataloğu koruma testleri (ileri bakan seri sızıntısı).

* `chikou_plotted` (Ichimoku'nun geriye çizilen, geleceğe bakan Chikou'su) katalog kolonlarında ve durumlarında OLMAMALI.
* KATALOG düzeyinde önek değişmezliği: t gününe kadar kesilmiş veriyle hesaplanan TÜM kolonlar ve kategorik durumlar
  (Supertrend dönüş günleri, Ichimoku konumu dahil), tüm veriyle hesaplananın o güne kadarki kısmıyla birebir aynı.
  (tests/tools/test_indicators_properties.py kütüphane işlevlerini sınar; bu dosya araca giden katalog katmanını sınar.)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import KAMA_FLAT_SLOPE_PCT, VOLUME_HIGH_Z, VOLUME_LOW_Z
from schemas.enums import IndicatorName
from schemas.params import IndicatorConfig
from tools.indicators.catalog import STATE_KEYS, compute


def _ohlcv(n: int = 900, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0002, 0.02, n)))
    open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.lognormal(15, 0.4, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol},
                        index=pd.bdate_range("2023-01-02", periods=n))


def _compute(df: pd.DataFrame):
    return compute(df, IndicatorConfig(), list(IndicatorName), kama_flat_pct=KAMA_FLAT_SLOPE_PCT,
                   volume_high_z=VOLUME_HIGH_Z, volume_low_z=VOLUME_LOW_Z)


def test_catalog_never_exposes_forward_looking_chikou():
    comp = _compute(_ohlcv())
    names = [c.name for c in comp.columns]
    assert not any("PLOTTED" in n for n in names)
    assert [n for n in names if "CHIKOU" in n] == ["ICHIMOKU_CHIKOU_VS_CLOSE_26"]  # yalnızca nedensel c_t - c_{t-26}
    assert not any("chikou" in k.lower() for k in comp.states) and set(comp.states) <= set(STATE_KEYS)


def test_chikou_vs_close_is_backward_looking():
    """ICHIMOKU_CHIKOU_VS_CLOSE_26[t] = close[t] - close[t-26]: yalnızca geçmişe bakar."""
    df = _ohlcv()
    col = next(c for c in _compute(df).columns if c.name == "ICHIMOKU_CHIKOU_VS_CLOSE_26").values
    pd.testing.assert_series_equal(col, df["close"] - df["close"].shift(26), check_names=False)


def test_catalog_prefix_invariance_columns_and_states_incl_supertrend_flips():
    df = _ohlcv()
    full = _compute(df)
    flips = int((full.states["supertrend"].dropna() != full.states["supertrend"].dropna().shift()).sum()) - 1
    assert flips >= 5  # test anlamlı: veride Supertrend dönüş günleri var
    for cut in (260, 431, 700):
        part = _compute(df.iloc[:cut])
        for a, b in zip(part.columns, full.columns):
            assert a.name == b.name
            pd.testing.assert_series_equal(a.values, b.values.iloc[:cut], check_exact=True)
        for k in full.states:
            assert part.states[k].tolist() == full.states[k].iloc[:cut].tolist(), (k, cut)


def test_catalog_future_shock_does_not_change_past_columns_and_states():
    df = _ohlcv()
    cut = 600
    shocked = df.copy()
    shocked.iloc[cut:] = shocked.iloc[cut:] * 1e6
    a, b = _compute(df), _compute(shocked)
    for ca, cb in zip(a.columns, b.columns):
        pd.testing.assert_series_equal(ca.values.iloc[:cut], cb.values.iloc[:cut], check_exact=True)
    for k in a.states:
        assert a.states[k].iloc[:cut].tolist() == b.states[k].iloc[:cut].tolist(), k
