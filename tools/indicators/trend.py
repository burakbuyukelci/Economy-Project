"""Trend göstergeleri: SMA, EMA, KAMA, MACD, Supertrend, Ichimoku."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.indicators._util import as_float_array, check_window, rolling_apply
from tools.indicators.volatility import atr_wilder


def sma(close: pd.Series, window: int) -> pd.Series:
    """Basit hareketli ortalama: son `window` kapanışın aritmetik ortalaması. Isınma: `window` bar."""
    check_window(window, "window")
    return rolling_apply(close, window, np.mean)


def ema(series: pd.Series, window: int) -> pd.Series:
    """Üstel hareketli ortalama. alpha = 2/(window+1). TOHUM: ilk `window` geçerli değerin SMA'sı.

    EMA_t = alpha*x_t + (1-alpha)*EMA_{t-1}. Isınma: `window` bar (baştaki NaN'lar sayılmaz; MACD sinyali için).
    """
    check_window(window, "window")
    x = as_float_array(series, "ema girdisi", allow_leading_nan=True)
    out = np.full(len(x), np.nan)
    valid = np.flatnonzero(~np.isnan(x))
    if len(valid) >= window:
        f = valid[0]
        seed_idx = f + window - 1
        out[seed_idx] = x[f:seed_idx + 1].mean()
        alpha = 2.0 / (window + 1)
        for i in range(seed_idx + 1, len(x)):
            out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def kaufman_efficiency_ratio(close: pd.Series, er_window: int) -> pd.Series:
    """ER_t = |c_t - c_{t-n}| / sum_{i=t-n+1..t} |c_i - c_{i-1}|  (0..1). Hiç hareket yoksa 0. Isınma: n+1 bar."""
    check_window(er_window, "er_window", minimum=2)
    c = as_float_array(close, "close")
    n = er_window
    out = np.full(len(c), np.nan)
    if len(c) > n:
        change = np.abs(c[n:] - c[:-n])
        path = rolling_apply(pd.Series(np.abs(np.diff(c))), n, np.sum).to_numpy()[n - 1:]
        out[n:] = np.where(path > 0, change / np.where(path > 0, path, 1.0), 0.0)
    return pd.Series(out, index=close.index)


def kama(close: pd.Series, er_window: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman Uyarlanabilir Hareketli Ortalama.

    sc_t = (ER_t * (2/(fast+1) - 2/(slow+1)) + 2/(slow+1))^2 ; KAMA_t = KAMA_{t-1} + sc_t * (c_t - KAMA_{t-1}).
    ER yüksekse (trend) KAMA fiyata hızlı yaklaşır, düşükse (yatay/gürültü) yavaşlar.
    TOHUM: ilk ER gününde (idx n) önceki KAMA = c_{n-1}. İlk çıktı idx n; ısınma: n+1 bar.
    """
    check_window(fast, "fast")
    check_window(slow, "slow")
    if not fast < slow:
        raise ValueError("fast < slow olmalı")
    er = kaufman_efficiency_ratio(close, er_window).to_numpy()
    c = as_float_array(close, "close")
    fast_sc, slow_sc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    out = np.full(len(c), np.nan)
    n = er_window
    if len(c) > n:
        prev = c[n - 1]
        for i in range(n, len(c)):
            sc = (er[i] * (fast_sc - slow_sc) + slow_sc) ** 2
            prev = prev + sc * (c[i] - prev)
            out[i] = prev
    return pd.Series(out, index=close.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD = EMA(fast) - EMA(slow); sinyal = MACD'nin EMA(signal)'ı (SMA tohumlu); hist = MACD - sinyal.

    Isınma: macd -> slow bar; signal/hist -> slow + signal - 1 bar.
    """
    if not fast < slow:
        raise ValueError("fast < slow olmalı")
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig}, index=close.index)


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, atr_period: int = 10,
               multiplier: float = 3.0) -> pd.DataFrame:
    """Supertrend: ATR bantlı trend izleyici. Sütunlar: line (çizgi), direction (+1 yükseliş, -1 düşüş).

    hl2=(h+l)/2 ; ham_üst=hl2+m*ATR ; ham_alt=hl2-m*ATR.
    Nihai üst bant yalnızca DÜŞER (veya önceki kapanış üstüne çıktıysa sıfırlanır); nihai alt bant yalnızca YÜKSELİR
    (veya önceki kapanış altına indiyse sıfırlanır). Yön: yükselişteyken close < nihai_alt -> düşüş;
    düşüştesyken close > nihai_üst -> yükseliş. Çizgi = yükselişte nihai_alt, düşüşte nihai_üst.
    İlk geçerli günde yön: close >= hl2 ise +1, değilse -1. Isınma: atr_period + 1 bar.
    """
    if multiplier <= 0:
        raise ValueError("multiplier > 0 olmalı")
    h, l, c = (as_float_array(s, n) for s, n in ((high, "high"), (low, "low"), (close, "close")))
    atr = atr_wilder(high, low, close, atr_period).to_numpy()
    n = len(c)
    line = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    valid = np.flatnonzero(~np.isnan(atr))
    if len(valid):
        hl2 = (h + l) / 2.0
        basic_up, basic_lo = hl2 + multiplier * atr, hl2 - multiplier * atr
        i0 = valid[0]
        fu, fl = basic_up[i0], basic_lo[i0]
        d = 1 if c[i0] >= hl2[i0] else -1
        line[i0], direction[i0] = (fl if d == 1 else fu), d
        for i in range(i0 + 1, n):
            fu = basic_up[i] if (basic_up[i] < fu or c[i - 1] > fu) else fu
            fl = basic_lo[i] if (basic_lo[i] > fl or c[i - 1] < fl) else fl
            if d == 1 and c[i] < fl:
                d = -1
            elif d == -1 and c[i] > fu:
                d = 1
            line[i], direction[i] = (fl if d == 1 else fu), d
    return pd.DataFrame({"line": line, "direction": direction}, index=close.index)


def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series, tenkan: int = 9, kijun: int = 26,
             senkou_b: int = 52, displacement: int | None = None) -> pd.DataFrame:
    """Ichimoku Kinko Hyo. `displacement` varsayılanı = kijun (standart 26).

    tenkan = (max high + min low)/2, son `tenkan` gün ; kijun aynı, `kijun` gün.
    senkou_a = ((tenkan+kijun)/2) `displacement` bar İLERİ kaydırılmış; senkou_b = ((max high + min low)/2, `senkou_b` gün)
    `displacement` bar ileri. Yani gün t'deki bulut, t-displacement gününün verisinden gelir (geleceğe bakmaz).
    chikou_vs_close = close_t - close_{t-displacement}  (Chikou'nun NEDENSEL karşılığı; sinyalde bunu kullan).
    chikou_plotted  = close kaydırılmış GERİ: satır t'ye close_{t+displacement} çizilir. Son `displacement` satır NaN.
        UYARI: bu seri geleceğe bakar; olay/sinyal üretiminde KULLANILMAZ (yalnızca grafik karşılığı için).
    Isınma: tenkan -> tenkan bar; kijun -> kijun bar; senkou_a -> max(tenkan,kijun)+displacement; senkou_b ->
    senkou_b+displacement; chikou_vs_close -> displacement+1.
    """
    for name, v in (("tenkan", tenkan), ("kijun", kijun), ("senkou_b", senkou_b)):
        check_window(v, name)
    disp = kijun if displacement is None else displacement
    check_window(disp, "displacement")

    def mid(w: int) -> pd.Series:
        return (rolling_apply(high, w, np.max) + rolling_apply(low, w, np.min)) / 2.0

    t, k = mid(tenkan), mid(kijun)
    return pd.DataFrame({
        "tenkan": t,
        "kijun": k,
        "senkou_a": ((t + k) / 2.0).shift(disp),
        "senkou_b": mid(senkou_b).shift(disp),
        "chikou_vs_close": close - close.shift(disp),
        "chikou_plotted": close.shift(-disp),
    }, index=close.index)
