"""Gösterge kütüphanesi özellik testleri: ta ile çapraz doğrulama, nedensellik (sızıntı), determinizm, girdi korunumu.

Çapraz doğrulama `ta` (yalnızca requirements-dev.txt) varsa koşar; yoksa atlanır, altın testler yeterlidir.
Not: ta, EMA/RSI/ATR'yi ilk değerden başlatır (bizim tohumumuz SMA/basit ortalama). Bu farklar üstel olarak söner, bu yüzden
karşılaştırma ısınmadan >= WARM bar sonra yapılır. KAMA ve Bollinger/SMA aynı tohum/tanım olduğundan birebir eşleşir.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.indicators import (
    atr_wilder, bollinger, ema, ichimoku, kama, macd, rolling_volatility, rsi_wilder, simple_returns, sma, supertrend,
    volume_zscore,
)

N = 1000
WARM = 400


@pytest.fixture(scope="module")
def ohlcv() -> pd.DataFrame:
    """Sabit tohumlu rastgele yürüyüş OHLCV (determinist)."""
    rng = np.random.default_rng(481)
    idx = pd.bdate_range("2023-01-02", periods=N)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, N)))
    open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.005, N))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, N)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, N)))
    vol = rng.lognormal(15, 0.4, N)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


# --- ta ile çapraz doğrulama ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def ta():
    return pytest.importorskip("ta")


def close_to(ours: pd.Series, theirs: pd.Series, start: int, rel: float = 1e-9) -> None:
    a, b = ours.iloc[start:].to_numpy(), theirs.iloc[start:].to_numpy()
    assert not np.isnan(a).any() and not np.isnan(b).any()
    np.testing.assert_allclose(a, b, rtol=rel)


def test_sma_matches_ta(ohlcv, ta):
    from ta.trend import SMAIndicator
    for w in (20, 50, 200):
        close_to(sma(ohlcv.close, w), SMAIndicator(ohlcv.close, w).sma_indicator(), w - 1)


def test_ema_matches_ta_after_warmup(ohlcv, ta):
    from ta.trend import EMAIndicator
    for w in (12, 26):
        close_to(ema(ohlcv.close, w), EMAIndicator(ohlcv.close, w).ema_indicator(), WARM, rel=1e-8)


def test_macd_matches_ta_after_warmup(ohlcv, ta):
    from ta.trend import MACD
    ref = MACD(ohlcv.close, window_slow=26, window_fast=12, window_sign=9)
    ours = macd(ohlcv.close, 12, 26, 9)
    close_to(ours["macd"], ref.macd(), WARM, rel=1e-7)
    close_to(ours["signal"], ref.macd_signal(), WARM, rel=1e-7)


def test_rsi_matches_ta_after_warmup(ohlcv, ta):
    from ta.momentum import RSIIndicator
    close_to(rsi_wilder(ohlcv.close, 14), RSIIndicator(ohlcv.close, 14).rsi(), WARM, rel=1e-8)


def test_bollinger_matches_ta_exactly(ohlcv, ta):
    from ta.volatility import BollingerBands
    ref = BollingerBands(ohlcv.close, window=20, window_dev=2)
    ours = bollinger(ohlcv.close, 20, 2.0)
    close_to(ours["mid"], ref.bollinger_mavg(), 19)
    close_to(ours["upper"], ref.bollinger_hband(), 19)
    close_to(ours["lower"], ref.bollinger_lband(), 19)
    close_to(ours["pct_b"], ref.bollinger_pband(), 19, rel=1e-9)


def test_atr_matches_ta_after_warmup(ohlcv, ta):
    from ta.volatility import AverageTrueRange
    ref = AverageTrueRange(ohlcv.high, ohlcv.low, ohlcv.close, window=14).average_true_range()
    close_to(atr_wilder(ohlcv.high, ohlcv.low, ohlcv.close, 14), ref, WARM, rel=1e-8)


def test_kama_matches_ta_same_seed(ohlcv, ta):
    from ta.momentum import KAMAIndicator
    ref = KAMAIndicator(ohlcv.close, window=10, pow1=2, pow2=30).kama()
    close_to(kama(ohlcv.close, 10, 2, 30), ref, 10, rel=1e-9)  # ta de tohumu close[window-1] alır


def test_ichimoku_matches_ta_unshifted(ohlcv, ta):
    from ta.trend import IchimokuIndicator
    ref = IchimokuIndicator(ohlcv.high, ohlcv.low, window1=9, window2=26, window3=52, visual=False, fillna=False)
    ours = ichimoku(ohlcv.high, ohlcv.low, ohlcv.close, 9, 26, 52, 26)
    close_to(ours["tenkan"], ref.ichimoku_conversion_line(), 8)
    close_to(ours["kijun"], ref.ichimoku_base_line(), 25)
    # ta (visual=False) kaydırmasız span verir; bizimki 26 bar ileri kaymış -> ours.shift(-26) ile karşılaştır
    close_to(ours["senkou_a"].shift(-26).iloc[:-26], ref.ichimoku_a().iloc[:-26], 51)
    close_to(ours["senkou_b"].shift(-26).iloc[:-26], ref.ichimoku_b().iloc[:-26], 51)


# --- nedensellik: gelecek eklemek geçmiş değerleri DEĞİŞTİRMEMELİ ----------------------------------
def _all_columns(df: pd.DataFrame) -> pd.DataFrame:
    o = {}
    for w in (20, 50, 200):
        o[f"sma{w}"] = sma(df.close, w)
    for w in (12, 26):
        o[f"ema{w}"] = ema(df.close, w)
    o["kama"] = kama(df.close, 10, 2, 30)
    o["rsi"] = rsi_wilder(df.close, 14)
    for k, v in macd(df.close, 12, 26, 9).items():
        o[f"macd_{k}"] = v
    for k, v in bollinger(df.close, 20, 2.0).items():
        o[f"bb_{k}"] = v
    o["atr"] = atr_wilder(df.high, df.low, df.close, 14)
    for k, v in supertrend(df.high, df.low, df.close, 10, 3.0).items():
        o[f"st_{k}"] = v
    for k, v in ichimoku(df.high, df.low, df.close, 9, 26, 52, 26).drop(columns="chikou_plotted").items():
        o[f"ich_{k}"] = v
    o["volz"] = volume_zscore(df.volume, 20)
    o["ret5"] = simple_returns(df.close, 5)
    o["vol20"] = rolling_volatility(df.close, 20)
    return pd.DataFrame(o)


def test_prefix_invariance_no_lookahead(ohlcv):
    """t gününe kadar kesilmiş veriyle hesaplanan değerler, tüm veriyle hesaplananın t'ye kadar olan kısmıyla BİREBİR aynı."""
    full = _all_columns(ohlcv)
    for cut in (300, 555, 777):
        part = _all_columns(ohlcv.iloc[:cut])
        pd.testing.assert_frame_equal(part, full.iloc[:cut], check_exact=True)


def test_future_shock_does_not_change_past(ohlcv):
    """as_of sonrasına aşırı değerli satırlar eklenince geçmiş değerler değişmez (kütüphane düzeyi sızıntı testi)."""
    cut = 600
    shocked = ohlcv.copy()
    shocked.iloc[cut:, :4] *= 1e6
    shocked.iloc[cut:, 4] *= 1e6
    a, b = _all_columns(ohlcv).iloc[:cut], _all_columns(shocked).iloc[:cut]
    pd.testing.assert_frame_equal(a, b, check_exact=True)


def test_chikou_plotted_is_the_only_forward_looking_series(ohlcv):
    cut = 600
    a = ichimoku(ohlcv.high, ohlcv.low, ohlcv.close, 9, 26, 52, 26)["chikou_plotted"].iloc[:cut]
    b = ichimoku(ohlcv.iloc[:cut].high, ohlcv.iloc[:cut].low, ohlcv.iloc[:cut].close, 9, 26, 52, 26)["chikou_plotted"]
    assert not a.equals(b)  # bilinçli: bu seri sinyalde kullanılmaz


# --- determinizm / girdi korunumu ----------------------------------------------------------------
def test_determinism_bit_identical(ohlcv):
    pd.testing.assert_frame_equal(_all_columns(ohlcv), _all_columns(ohlcv.copy()), check_exact=True)


def test_inputs_not_mutated(ohlcv):
    before = ohlcv.copy(deep=True)
    _all_columns(ohlcv)
    pd.testing.assert_frame_equal(before, ohlcv, check_exact=True)


def test_nan_input_is_rejected(ohlcv):
    bad = ohlcv.close.copy()
    bad.iloc[100] = np.nan
    with pytest.raises(ValueError):
        rsi_wilder(bad, 14)
    with pytest.raises(ValueError):
        atr_wilder(ohlcv.high, ohlcv.low, bad, 14)


def test_short_series_yields_all_nan_not_error(ohlcv):
    short = ohlcv.iloc[:5]
    assert _all_columns(short).isna().all().all()  # hata fırlatmamalı, her şey ısınmada (NaN)
    assert sma(short.close, 20).isna().all() and rsi_wilder(short.close, 14).isna().all()
    assert supertrend(short.high, short.low, short.close, 10, 3.0)["line"].isna().all()
