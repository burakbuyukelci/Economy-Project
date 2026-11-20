"""calculate_indicators: ticker + göstergeler + config (+ as_of) -> as_of günü gösterge durumu ve en fazla son N satır.

KOMPAKT zarf (schemas 1.1.0): tüm zaman serisi DEĞİL; `latest` (state_date günü) + `recent_rows` (önceki en fazla
`last_n_rows` gün). Hesap, snapshot'ın başından as_of'a kadar KESİLMİŞ veri üzerinde yapılır (ısınma `start`'tan bağımsız);
as_of sonrası satırlar hesaba hiç girmez. Ağ yok; yalnızca snapshot okur.
"""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from config.settings import KAMA_FLAT_SLOPE_PCT, VOLUME_HIGH_Z, VOLUME_LOW_Z
from config.universe import load_universe
from schemas.enums import PriceAdjustment, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import CalculateIndicatorsParams
from schemas.results import CalculateIndicatorsResult, IndicatorColumn, IndicatorRow, IndicatorStates
from tools._prices import history_warnings_for_range
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool
from tools.indicators.catalog import STATE_KEYS, compute

TOOL = ToolName.CALCULATE_INDICATORS
ROUND = 4  # zarfta değerler 4 ondalık (kompaktlık + sabit hash)


def _price_frame(df: pd.DataFrame, adjustment: PriceAdjustment) -> pd.DataFrame:
    """as_of'a kesilmiş tek hisse tablosu -> tarih indeksli open/high/low/close/volume.
    adjusted: OHL, adj_close/close oranıyla ölçeklenir, close=adj_close (docs/data_dictionary.md §11.3)."""
    df = df.sort_values("date")
    if adjustment == PriceAdjustment.ADJUSTED:
        f = df["adj_close"] / df["close"]
        out = pd.DataFrame({"open": df["open"] * f, "high": df["high"] * f, "low": df["low"] * f,
                            "close": df["adj_close"]})
    else:
        out = df[["open", "high", "low", "close"]].copy()
    out["volume"] = df["volume"]
    out.index = pd.DatetimeIndex(df["date"])
    return out.astype("float64")


def _num(v: float) -> float | None:
    return None if v is None or not math.isfinite(v) else round(float(v), ROUND)


def _handler(p: CalculateIndicatorsParams, snap: Snapshot) -> ToolOutput:
    uni = load_universe().set_index("ticker")
    if p.ticker not in uni.index:
        raise ToolFailure("UNKNOWN_TICKER", f"{p.ticker} evrende (config/universe.csv) yok")
    frame = snap.stocks.loc[snap.stocks["ticker"] == p.ticker]
    if frame.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker} için snapshot {snap.data_version} içinde veri yok")

    warnings: list[str] = []
    effective_end = min(p.end, p.as_of)
    if p.end > p.as_of:
        warnings.append(make_warning(
            WarningCode.AS_OF_CLAMPED, f"end={p.end.isoformat()} as_of={p.as_of.isoformat()} tarihine kesildi"))

    # as_of'a KES (kural 1); bundan sonra hesap yalnızca bu tablo üzerindedir
    px = _price_frame(enforce_as_of(frame, p.as_of), p.price_adjustment)
    try:
        comp = compute(px, p.config, list(p.indicators), kama_flat_pct=KAMA_FLAT_SLOPE_PCT,
                       volume_high_z=VOLUME_HIGH_Z, volume_low_z=VOLUME_LOW_Z)
    except ValueError as e:
        raise ToolFailure("INVALID_PARAMS", f"gösterge config geçersiz: {e}") from e

    vals = pd.DataFrame({c.name: c.values for c in comp.columns}, index=px.index)
    upto = px.index[px.index <= pd.Timestamp(effective_end)]       # as_of durumu: start'tan bağımsız son işlem günü
    state_ts = upto[-1] if len(upto) else None
    window = upto[upto >= pd.Timestamp(p.start)]                     # dönen satırlar yalnızca [start, state_date]
    all_valid = vals.notna().all(axis=1) if len(vals.columns) else pd.Series(False, index=px.index)

    def row(ts: pd.Timestamp) -> IndicatorRow:
        sv = {k: (comp.states[k].loc[ts] if k in comp.states else None) for k in STATE_KEYS}
        return IndicatorRow(date=ts.date(), close=_num(px.at[ts, "close"]),
                            values={c: _num(vals.at[ts, c]) for c in vals.columns}, states=IndicatorStates(**sv))

    latest = row(state_ts) if state_ts is not None else None
    recent = [row(ts) for ts in window[window < state_ts][-p.last_n_rows:]] if (state_ts is not None and p.last_n_rows) else []

    columns = []
    for c in comp.columns:
        ok = vals[c.name].notna()
        columns.append(IndicatorColumn(
            name=c.name, indicator=c.indicator, warmup_bars=c.warmup_bars,
            first_valid_date=ok.idxmax().date() if ok.any() else None,
            valid_at_as_of=bool(latest is not None and latest.values[c.name] is not None)))

    pending = [f"{c.name} ({c.warmup_bars} bar gerekli)" for c in columns if latest is not None and not c.valid_at_as_of]
    if pending:
        warnings.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"n_bars_used={len(px)}; state_date'te geçerli değil (ısınma/tanımsız): {', '.join(pending)}"))
    # Veri kalitesi uyarıları (eksik işlem günü, fiyat sıçraması) dönen pencere için; pencere boşsa (ör. as_of tatil günü ve
    # start == as_of) as_of durumunun günü kontrol edilir, "aralıkta satır yok" gürültüsü üretilmez.
    check_days = window if len(window) else upto[-1:]
    check_start = p.start if len(window) else (state_ts.date() if state_ts is not None else p.start)
    rows_for_checks = [SimpleNamespace(date=ts.date()) for ts in check_days]
    warnings += history_warnings_for_range(snap, p.ticker, check_start, p.as_of, rows_for_checks, effective_end)  # type: ignore[arg-type]

    res = CalculateIndicatorsResult(
        ticker=p.ticker, price_adjustment=p.price_adjustment,
        state_date=state_ts.date() if state_ts is not None else None,
        n_bars_used=len(px), history_first_date=px.index[0].date() if len(px) else None,
        first_valid_date=all_valid.idxmax().date() if all_valid.any() else None,
        columns=columns, latest=latest, recent_rows=recent)
    return ToolOutput(results=res, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
