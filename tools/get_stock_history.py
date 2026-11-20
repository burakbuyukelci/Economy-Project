"""get_stock_history: ticker, start, end (+ as_of) -> OHLCV + metadata. Snapshot'tan okur, ağ yok."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from config.universe import load_universe
from schemas.enums import ToolName
from schemas.params import GetStockHistoryParams
from schemas.results import GetStockHistoryResult
from tools._prices import history_warnings_for_range, slice_prices
from tools.common import Snapshot, ToolFailure, ToolOutput, run_tool

TOOL = ToolName.GET_STOCK_HISTORY


def _handler(p: GetStockHistoryParams, snap: Snapshot) -> ToolOutput:
    uni = load_universe().set_index("ticker")
    if p.ticker not in uni.index:
        raise ToolFailure("UNKNOWN_TICKER", f"{p.ticker} evrende (config/universe.csv) yok")
    frame = snap.stocks.loc[snap.stocks["ticker"] == p.ticker]
    if frame.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker} için snapshot {snap.data_version} içinde veri yok")

    rows, effective_end, warnings = slice_prices(frame, p.start, p.end, p.as_of, p.price_adjustment)
    warnings += history_warnings_for_range(snap, p.ticker, p.start, p.as_of, rows, effective_end)

    res = GetStockHistoryResult(
        ticker=p.ticker, yahoo_symbol=str(uni.loc[p.ticker, "yahoo_symbol"]), price_adjustment=p.price_adjustment,
        requested_start=p.start, requested_end=p.end, effective_end=effective_end,
        first_date=rows[0].date if rows else None, last_date=rows[-1].date if rows else None,
        n_rows=len(rows), rows=rows,
    )
    return ToolOutput(results=res, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
