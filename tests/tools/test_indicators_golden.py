"""Gösterge kütüphanesi altın testleri: elle hesaplanabilir küçük serilerle. Beklenen değerlerin elle hesabı yorumda."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tools.indicators import (
    atr_wilder, bollinger, ema, ichimoku, kama, kaufman_efficiency_ratio, macd, rsi_wilder, sma, supertrend,
    volume_zscore,
)


def S(*v):
    return pd.Series([float(x) for x in v], index=pd.bdate_range("2024-01-01", periods=len(v)))


def nan_mask(s):
    return list(s.isna())


# --- SMA ----------------------------------------------------------------------------------------
def test_sma_golden():
    out = sma(S(1, 2, 3, 4, 5, 6), 3)
    assert nan_mask(out) == [True, True, False, False, False, False]
    assert out.iloc[2:].tolist() == [2.0, 3.0, 4.0, 5.0]  # (1+2+3)/3=2, (2+3+4)/3=3 ...


# --- EMA ----------------------------------------------------------------------------------------
def test_ema_golden_sma_seed():
    # w=3 -> alpha=2/(3+1)=0.5; tohum = ilk 3 değerin SMA'sı = (2+4+6)/3 = 4 (idx2)
    # idx3: 0.5*4 + 0.5*4 = 4 ; idx4: 0.5*8 + 0.5*4 = 6
    out = ema(S(2, 4, 6, 4, 8), 3)
    assert nan_mask(out) == [True, True, False, False, False]
    assert out.iloc[2:].tolist() == [4.0, 4.0, 6.0]


def test_ema_skips_leading_nan_and_seeds_from_first_valid():
    out = ema(pd.Series([np.nan, np.nan, 2.0, 4.0, 6.0, 4.0, 8.0]), 3)
    assert nan_mask(out) == [True] * 4 + [False] * 3
    assert out.iloc[4:].tolist() == [4.0, 4.0, 6.0]


def test_ema_rejects_interior_nan():
    with pytest.raises(ValueError):
        ema(pd.Series([1.0, 2.0, np.nan, 4.0, 5.0]), 2)


# --- RSI (Wilder) -------------------------------------------------------------------------------
def test_rsi_wilder_golden():
    # close 10,11,12,11,13,12 ; p=3 ; değişimler idx1..5: +1,+1,-1,+2,-1
    # idx3 tohum: avg_gain=(1+1+0)/3=2/3, avg_loss=(0+0+1)/3=1/3, RS=2 -> RSI=100-100/3=66.6667
    # idx4: gain=(2/3*2+2)/3=10/9, loss=(1/3*2+0)/3=2/9, RS=5 -> 83.3333
    # idx5: gain=(10/9*2+0)/3=20/27, loss=(2/9*2+1)/3=13/27, RS=20/13 -> 100*20/33 = 60.6061
    out = rsi_wilder(S(10, 11, 12, 11, 13, 12), 3)
    assert nan_mask(out) == [True, True, True, False, False, False]
    assert out.iloc[3:].tolist() == pytest.approx([100 * 2 / 3, 100 * 5 / 6, 100 * 20 / 33], rel=1e-12)


def test_rsi_edge_cases_all_up_is_100_and_flat_is_50():
    assert rsi_wilder(S(1, 2, 3, 4, 5), 3).iloc[-1] == 100.0
    assert rsi_wilder(S(5, 5, 5, 5, 5), 3).iloc[-1] == 50.0


# --- Bollinger ----------------------------------------------------------------------------------
def test_bollinger_golden_population_std():
    # [2,4,6], w=3, k=2: ort=4, popülasyon std = sqrt((4+0+4)/3)=1.632993
    # üst=4+3.265986=7.265986, alt=0.734014 ; %B(close=6)=(6-0.734014)/6.531973=0.806186 ; bant genişliği=6.531973/4*100
    bb = bollinger(S(2, 4, 6), 3, 2.0)
    sd = math.sqrt(8 / 3)
    assert bb["mid"].iloc[2] == pytest.approx(4.0)
    assert bb["upper"].iloc[2] == pytest.approx(4 + 2 * sd)
    assert bb["lower"].iloc[2] == pytest.approx(4 - 2 * sd)
    assert bb["pct_b"].iloc[2] == pytest.approx((6 - (4 - 2 * sd)) / (4 * sd))
    assert bb["bandwidth_pct"].iloc[2] == pytest.approx(4 * sd / 4 * 100)
    assert nan_mask(bb["mid"]) == [True, True, False]


def test_bollinger_flat_series_has_nan_pct_b():
    bb = bollinger(S(5, 5, 5, 5), 3, 2.0)
    assert bb["upper"].iloc[-1] == bb["lower"].iloc[-1] == 5.0
    assert math.isnan(bb["pct_b"].iloc[-1])


# --- ATR (Wilder) -------------------------------------------------------------------------------
def test_atr_wilder_golden():
    # (h,l,c): (10,8,9) (11,9,10) (12,10,11) (13,9,10); p=2
    # TR1=max(2,|11-9|,|9-9|)=2 ; TR2=2 ; TR3=max(4,|13-11|,|9-11|)=4
    # tohum idx2 = (TR1+TR2)/2 = 2 ; idx3 = (2*(2-1)+4)/2 = 3
    h, l, c = S(10, 11, 12, 13), S(8, 9, 10, 9), S(9, 10, 11, 10)
    out = atr_wilder(h, l, c, 2)
    assert nan_mask(out) == [True, True, False, False]
    assert out.iloc[2:].tolist() == [2.0, 3.0]


# --- KAMA ---------------------------------------------------------------------------------------
def test_kaufman_er_golden():
    # close 10,12,14,13 ; n=2 ; idx2: |14-10| / (|12-10|+|14-12|) = 4/4 = 1 ; idx3: |13-12|/(2+1) = 1/3
    er = kaufman_efficiency_ratio(S(10, 12, 14, 13), 2)
    assert nan_mask(er) == [True, True, False, False]
    assert er.iloc[2:].tolist() == pytest.approx([1.0, 1 / 3])


def test_kama_golden():
    # er=2, fast=2 (2/3), slow=30 (2/31). tohum: önceki KAMA = close[1] = 12
    # idx2: ER=1 -> sc=(2/3)^2=0.444444 ; KAMA=12+0.444444*(14-12)=12.888889
    # idx3: ER=1/3 -> sc=(1/3*(2/3-2/31)+2/31)^2 ; KAMA=KAMA2+sc*(13-KAMA2)
    out = kama(S(10, 12, 14, 13), 2, 2, 30)
    assert nan_mask(out) == [True, True, False, False]
    k2 = 12 + (2 / 3) ** 2 * 2
    sc3 = ((1 / 3) * (2 / 3 - 2 / 31) + 2 / 31) ** 2
    assert out.iloc[2] == pytest.approx(k2)
    assert out.iloc[3] == pytest.approx(k2 + sc3 * (13 - k2))


# --- MACD ---------------------------------------------------------------------------------------
def test_macd_golden_structure_and_values():
    close = S(*range(1, 13))  # 1..12 doğrusal
    m = macd(close, fast=3, slow=5, signal=2)
    e3, e5 = ema(close, 3), ema(close, 5)
    # doğrusal seride EMA(n), fiyatın (n-1)/2 gerisindedir: fark = (5-1)/2-(3-1)/2 = 1 -> MACD = 1.0 (ısınma sonrası)
    assert m["macd"].iloc[4:].tolist() == pytest.approx((e3 - e5).iloc[4:].tolist())
    assert m["macd"].iloc[-1] == pytest.approx(1.0)
    assert nan_mask(m["macd"]) == [True] * 4 + [False] * 8          # ısınma = slow bar
    assert nan_mask(m["signal"]) == [True] * 5 + [False] * 7        # slow + signal - 1 bar
    assert m["signal"].iloc[-1] == pytest.approx(1.0)
    assert m["hist"].iloc[-1] == pytest.approx(0.0)
    assert (m["hist"].dropna() == (m["macd"] - m["signal"]).dropna()).all()


# --- Supertrend ---------------------------------------------------------------------------------
def test_supertrend_golden_flip():
    # atr_period=1, çarpan=1 -> ATR = TR. (h,l,c): (10,8,9) (11,9,10.5) (12,10,11.5) (11,7,7.5) (8,6,6)
    # idx1: hl2=10, bantlar 8/12, close>=hl2 -> YUKARI, çizgi=alt=8
    # idx2: alt=9 (yükseldi), üst=12 -> YUKARI, çizgi=9
    # idx3: TR=4.5, close 7.5 < alt 9 -> AŞAĞI (flip), çizgi=üst=12
    # idx4: üst=min(9,12)=9, close 6 < 9 -> AŞAĞI, çizgi=9
    h, l, c = S(10, 11, 12, 11, 8), S(8, 9, 10, 7, 6), S(9, 10.5, 11.5, 7.5, 6)
    st = supertrend(h, l, c, atr_period=1, multiplier=1.0)
    assert nan_mask(st["line"]) == [True, False, False, False, False]
    assert st["line"].iloc[1:].tolist() == [8.0, 9.0, 12.0, 9.0]
    assert st["direction"].iloc[1:].tolist() == [1, 1, -1, -1]


# --- Ichimoku -----------------------------------------------------------------------------------
def test_ichimoku_golden_small_periods():
    h = S(10, 12, 14, 13, 15, 16, 18)
    l = S(8, 9, 11, 10, 12, 13, 14)
    c = S(9, 11, 13, 12, 14, 15, 17)
    ich = ichimoku(h, l, c, tenkan=2, kijun=3, senkou_b=4, displacement=3)
    # tenkan[3] = (max(h2,h3)+min(l2,l3))/2 = (14+10)/2 = 12 ; kijun[3] = (max(h1..h3)+min(l1..l3))/2 = (14+9)/2 = 11.5
    assert ich["tenkan"].iloc[3] == 12.0 and ich["kijun"].iloc[3] == 11.5
    # senkou_a ham[3] = (12+11.5)/2 = 11.75 -> 3 bar İLERİ kayar -> idx6'da ; senkou_b ham[3] = (14+8)/2 = 11 -> idx6
    assert ich["senkou_a"].iloc[6] == 11.75 and ich["senkou_b"].iloc[6] == 11.0
    # ilk geçerli ham senkou_a idx2: tenkan2=(14+9)/2=11.5, kijun2=(14+8)/2=11 -> 11.25 ; 3 bar kayınca idx5'te görünür
    assert nan_mask(ich["senkou_a"]) == [True] * 5 + [False] * 2
    assert ich["senkou_a"].iloc[5] == 11.25
    # chikou_vs_close[3] = close[3] - close[0] = 12 - 9 = 3 (nedensel Chikou; yalnız geçmişe bakar)
    assert ich["chikou_vs_close"].iloc[3] == 3.0 and math.isnan(ich["chikou_vs_close"].iloc[2])


def test_ichimoku_chikou_plotted_is_future_shifted_and_last_rows_nan():
    c = S(9, 11, 13, 12, 14, 15, 17)
    ich = ichimoku(S(10, 12, 14, 13, 15, 16, 18), S(8, 9, 11, 10, 12, 13, 14), c, 2, 3, 4, displacement=3)
    assert ich["chikou_plotted"].iloc[0] == c.iloc[3]       # t gününe, t+3 kapanışı çizilir (SİNYALDE KULLANMA)
    assert ich["chikou_plotted"].iloc[-3:].isna().all()


# --- Hacim z-skoru ------------------------------------------------------------------------------
def test_volume_zscore_golden():
    # [10,20,30], w=3: ort=20, popülasyon std=sqrt(200/3)=8.164966 ; z(30)=(30-20)/8.164966=1.224745
    z = volume_zscore(S(10, 20, 30), 3)
    assert z.iloc[2] == pytest.approx(10 / math.sqrt(200 / 3))
    assert nan_mask(z) == [True, True, False]


def test_volume_zscore_zero_std_is_nan():
    assert math.isnan(volume_zscore(S(7, 7, 7), 3).iloc[2])
