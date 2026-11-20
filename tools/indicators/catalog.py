"""Kolon kataloğu: IndicatorConfig + istenen göstergeler -> adlandırılmış kolonlar, analitik ısınma ve durumlar.

calculate_indicators aracı bunu çağırır; detect_reversal_events / run_backtest de aynı adlandırmayı kullanabilir.
Hesap, verilen OHLCV üzerinde yapılır (çağıran as_of'a kadar keser); kütüphane geleceği bilmez.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from schemas.enums import IndicatorName
from schemas.params import IndicatorConfig
from tools.indicators import states
from tools.indicators.momentum import rsi_wilder
from tools.indicators.trend import ema, ichimoku, kama, macd, sma, supertrend
from tools.indicators.volatility import atr_wilder, bollinger
from tools.indicators.volume import volume_zscore

STATE_KEYS = ("supertrend", "ichimoku_position", "kama_slope", "volume_regime")


@dataclass(frozen=True)
class Column:
    name: str
    indicator: IndicatorName
    warmup_bars: int          # ilk geçerli değer için gereken bar sayısı (analitik; testlerde ampirik NaN sonuyla eşitlenir)
    values: pd.Series


@dataclass(frozen=True)
class Computed:
    columns: list[Column]
    states: dict[str, pd.Series] = field(default_factory=dict)  # yalnızca istenen göstergelerin durumları


def fmt(x: float | int) -> str:
    """Kolon adı parçası: tamsayı -> '20' ; ondalık -> '2.0', '2.5' (bilimsel gösterim yok)."""
    if isinstance(x, int):
        return str(x)
    return f"{x:.1f}" if float(x).is_integer() else f"{x:.10g}"


def compute(ohlcv: pd.DataFrame, cfg: IndicatorConfig, indicators: list[IndicatorName], *,
            kama_flat_pct: float, volume_high_z: float, volume_low_z: float) -> Computed:
    """ohlcv: sütunlar high, low, close, volume; indeks = tarih (artan). Sırayla IndicatorName.value'ya göre."""
    close, high, low, vol = ohlcv["close"], ohlcv["high"], ohlcv["low"], ohlcv["volume"]
    cols: list[Column] = []
    st: dict[str, pd.Series] = {}

    def add(name: str, ind: IndicatorName, warmup: int, values: pd.Series) -> None:
        cols.append(Column(name, ind, warmup, values))

    for ind in sorted(set(indicators), key=lambda i: i.value):
        if ind == IndicatorName.SMA:
            for w in cfg.sma_windows:
                add(f"SMA_{fmt(w)}", ind, w, sma(close, w))
        elif ind == IndicatorName.EMA:
            for w in cfg.ema_windows:
                add(f"EMA_{fmt(w)}", ind, w, ema(close, w))
        elif ind == IndicatorName.KAMA:
            n, f, s = cfg.kama_er_window, cfg.kama_fast, cfg.kama_slow
            k = kama(close, n, f, s)
            add(f"KAMA_{fmt(n)}_{fmt(f)}_{fmt(s)}", ind, n + 1, k)
            st["kama_slope"] = states.kama_slope_state(k, kama_flat_pct)
        elif ind == IndicatorName.RSI:
            add(f"RSI_{fmt(cfg.rsi_period)}", ind, cfg.rsi_period + 1, rsi_wilder(close, cfg.rsi_period))
        elif ind == IndicatorName.MACD:
            f, s, g = cfg.macd_fast, cfg.macd_slow, cfg.macd_signal
            m = macd(close, f, s, g)
            tag = f"{fmt(f)}_{fmt(s)}_{fmt(g)}"
            add(f"MACD_{tag}", ind, s, m["macd"])
            add(f"MACD_SIGNAL_{tag}", ind, s + g - 1, m["signal"])
            add(f"MACD_HIST_{tag}", ind, s + g - 1, m["hist"])
        elif ind == IndicatorName.BOLLINGER:
            w, k = cfg.bollinger_window, cfg.bollinger_std
            bb = bollinger(close, w, k)
            tag = f"{fmt(w)}_{fmt(float(k))}"
            add(f"BB_UPPER_{tag}", ind, w, bb["upper"])
            add(f"BB_MID_{tag}", ind, w, bb["mid"])
            add(f"BB_LOWER_{tag}", ind, w, bb["lower"])
            add(f"BB_B_{tag}", ind, w, bb["pct_b"])
            add(f"BB_BANDWIDTH_PCT_{tag}", ind, w, bb["bandwidth_pct"])
        elif ind == IndicatorName.ATR:
            add(f"ATR_{fmt(cfg.atr_period)}", ind, cfg.atr_period + 1, atr_wilder(high, low, close, cfg.atr_period))
        elif ind == IndicatorName.SUPERTREND:
            p, m_ = cfg.supertrend_atr_period, cfg.supertrend_multiplier
            s_ = supertrend(high, low, close, p, m_)
            add(f"SUPERTREND_{fmt(p)}_{fmt(float(m_))}", ind, p + 1, s_["line"])
            st["supertrend"] = states.supertrend_state(s_["direction"])
        elif ind == IndicatorName.ICHIMOKU:
            t, kj, b = cfg.ichimoku_tenkan, cfg.ichimoku_kijun, cfg.ichimoku_senkou_b
            disp = kj  # standart: kaydırma = kijun (26)
            ich = ichimoku(high, low, close, t, kj, b, disp)
            add(f"ICHIMOKU_TENKAN_{fmt(t)}", ind, t, ich["tenkan"])
            add(f"ICHIMOKU_KIJUN_{fmt(kj)}", ind, kj, ich["kijun"])
            add(f"ICHIMOKU_SENKOU_A_{fmt(t)}_{fmt(kj)}", ind, max(t, kj) + disp, ich["senkou_a"])
            add(f"ICHIMOKU_SENKOU_B_{fmt(b)}", ind, b + disp, ich["senkou_b"])
            add(f"ICHIMOKU_CHIKOU_VS_CLOSE_{fmt(disp)}", ind, disp + 1, ich["chikou_vs_close"])
            st["ichimoku_position"] = states.ichimoku_position(close, ich["senkou_a"], ich["senkou_b"])
        elif ind == IndicatorName.VOLUME_ZSCORE:
            z = volume_zscore(vol, cfg.volume_zscore_window)
            add(f"VOLUME_ZSCORE_{fmt(cfg.volume_zscore_window)}", ind, cfg.volume_zscore_window, z)
            st["volume_regime"] = states.volume_regime(z, volume_high_z, volume_low_z)
    return Computed(cols, st)
