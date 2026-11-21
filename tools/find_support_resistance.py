"""find_support_resistance: nedensel pivotlardan destek/direnç bölgeleri (+ as_of).

YÖNTEM (docs/data_dictionary.md §17'den sonraki "Destek/direnç" bölümü):
  1. Fiyatlar adjusted (adj_close ölçekli OHLC), `as_of`'a kesilir; aralık = [start, min(end, as_of)].
  2. NEDENSEL pivot: `i` barı pivot tepe ise high[i] > önceki w barın en yükseği VE >= sonraki w barın en yükseği
     (pivot dip simetrik). Onay için `i + w` bar gerekir; aralığın son w barındaki pivot ONAYLANMAMIŞTIR ve kullanılmaz
     (as_of'ta henüz bilinmez). Düz bölge pivot üretmez.
  3. Tüm pivot fiyatları (tepeler high, dipler low) tek havuzda toplanır ve fiyata göre kümelenir (en düşük fiyata çıpalı:
     küme fiyatı <= çıpa x (1 + tolerans)). Kırılan direnç destek olabildiği için (rol değişimi) tepe/dip ayrımı yapılmaz.
  4. Seviye = küme ortalaması; bölge = [küme min, küme max]; dokunuş = küme içindeki pivot sayısı; `min_touches` altı elenir.
  5. Tip son kapanışa göredir: seviye <= kapanış → SUPPORT, > kapanış → RESISTANCE.
  6. `strength` = Σ 0,5^(yaş/126) x min(2, pivot barı hacmi / aralık medyan hacmi); yaş = o bardan son bara bar sayısı.
  7. Her yönde en yakın MAX_LEVELS_PER_SIDE seviye döner (hafif zarf); nearest_* tam kümeden hesaplanır.
Ağ yok; as_of sonrası satır hesaba girmez.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from schemas.enums import LevelType, PriceAdjustment, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import FindSupportResistanceParams
from schemas.results import FindSupportResistanceResult, SRLevel
from tools.calculate_indicators import _price_frame
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool

TOOL = ToolName.FIND_SUPPORT_RESISTANCE
ROUND = 4
RECENCY_HALF_LIFE_BARS = 126  # ~6 ay: bir dokunuşun ağırlığı 126 barda yarıya iner
VOLUME_WEIGHT_CAP = 2.0       # hacim ağırlığı üst sınırı
MAX_LEVELS_PER_SIDE = 5


def find_pivots(high: np.ndarray, low: np.ndarray, w: int) -> tuple[list[int], list[int]]:
    """(pivot tepe indeksleri, pivot dip indeksleri). Yalnızca iki yanında w barı olan, ONAYLANMIŞ pivotlar.

    Örnek (w=2): high=[1,1,1,5,1,1,1,...] -> i=3 tepedir (5 > önceki 2 bar, >= sonraki 2 bar).
    """
    n = len(high)
    ph: list[int] = []
    pl: list[int] = []
    for i in range(w, n - w):
        if high[i] > high[i - w:i].max() and high[i] >= high[i + 1:i + w + 1].max():
            ph.append(i)
        if low[i] < low[i - w:i].min() and low[i] <= low[i + 1:i + w + 1].min():
            pl.append(i)
    return ph, pl


def cluster_prices(items: list[tuple[float, int]], tol_pct: float) -> list[list[tuple[float, int]]]:
    """(fiyat, indeks) listesini fiyata göre kümeler: küme, en düşük fiyatına çıpalıdır; p <= çıpa x (1 + tol/100) girer."""
    out: list[list[tuple[float, int]]] = []
    for p, i in sorted(items):
        if out and p <= out[-1][0][0] * (1.0 + tol_pct / 100.0):
            out[-1].append((p, i))
        else:
            out.append([(p, i)])
    return out


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0


def _handler(p: FindSupportResistanceParams, snap: Snapshot) -> ToolOutput:
    frame = snap.stocks.loc[snap.stocks["ticker"] == p.ticker]
    if frame.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker} için snapshot {snap.data_version} içinde veri yok")
    eff_end = min(p.end, p.as_of)
    warnings: list[str] = []
    if p.end > p.as_of:
        warnings.append(make_warning(WarningCode.AS_OF_CLAMPED, f"end={p.end.isoformat()} as_of={p.as_of.isoformat()} tarihine kesildi"))

    px = _price_frame(enforce_as_of(frame, p.as_of), PriceAdjustment.ADJUSTED)
    vol = enforce_as_of(frame, p.as_of).set_index("date")["volume"].reindex(px.index)
    mask = (px.index >= pd.Timestamp(p.start)) & (px.index <= pd.Timestamp(eff_end))
    px, vol = px.loc[mask], vol.loc[mask]
    if px.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker}: [{p.start}, {eff_end}] aralığında as_of={p.as_of} öncesi satır yok")

    n = len(px)
    high, low, close = px["high"].to_numpy(float), px["low"].to_numpy(float), px["close"].to_numpy(float)
    v = vol.to_numpy(float)
    med_v = float(np.median(v)) if n else 0.0
    last_close, last_date = float(close[-1]), px.index[-1].date()

    ph, pl = find_pivots(high, low, p.pivot_window)
    items = [(float(high[i]), i) for i in ph] + [(float(low[i]), i) for i in pl]
    if not items:
        warnings.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                                     f"{n} barda onaylanmış pivot yok (pivot_window={p.pivot_window}); seviye üretilmedi"))

    levels: list[SRLevel] = []
    for cl in cluster_prices(items, p.tolerance_pct):
        if len(cl) < p.min_touches:
            continue
        prices = [x for x, _ in cl]
        idxs = [i for _, i in cl]
        level = float(np.mean(prices))
        strength = sum(
            0.5 ** ((n - 1 - i) / RECENCY_HALF_LIFE_BARS) * (min(VOLUME_WEIGHT_CAP, v[i] / med_v) if med_v > 0 else 1.0)
            for i in idxs)
        levels.append(SRLevel(
            type=LevelType.SUPPORT if _r(level) <= _r(last_close) else LevelType.RESISTANCE,
            price=_r(level), zone_low=_r(min(prices)), zone_high=_r(max(prices)), touch_count=len(cl),
            last_touch_date=px.index[max(idxs)].date(), strength=_r(strength)))

    supports = sorted((lv for lv in levels if lv.type == LevelType.SUPPORT), key=lambda lv: -lv.price)
    resistances = sorted((lv for lv in levels if lv.type == LevelType.RESISTANCE), key=lambda lv: lv.price)
    out_levels = resistances[:MAX_LEVELS_PER_SIDE] + supports[:MAX_LEVELS_PER_SIDE]
    if len(resistances) > MAX_LEVELS_PER_SIDE or len(supports) > MAX_LEVELS_PER_SIDE:
        warnings.append(make_warning(WarningCode.HISTORICAL_ONLY, f"her yönde en yakın {MAX_LEVELS_PER_SIDE} seviye listelendi "
                                     f"(toplam {len(supports)} destek, {len(resistances)} direnç)"))
    warnings.append(make_warning(WarningCode.HISTORICAL_ONLY, "Seviyeler geçmiş pivotlardır; gelecekte tutacağı garanti değildir. "
                                 "Fiyatlar adjusted ölçeklidir (son kapanışla aynı ölçek; ham işlem fiyatı olmayabilir)."))
    res = FindSupportResistanceResult(
        ticker=p.ticker, last_close=_r(last_close), last_date=last_date,
        nearest_support=supports[0].price if supports else None,
        nearest_resistance=resistances[0].price if resistances else None, levels=out_levels)
    return ToolOutput(results=res, n_events=None, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
