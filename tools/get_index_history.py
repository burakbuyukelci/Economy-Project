"""get_index_history: index, start, end (+ as_of) -> benchmark serisi. Snapshot'tan okur, ağ yok.

Endeks fiyatı için düzeltme kavramı yoktur (adj_close == close); satırlar 'adjusted' biçiminde döner.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from schemas.enums import PriceAdjustment, ToolName
from schemas.params import GetIndexHistoryParams
from schemas.results import GetIndexHistoryResult
from tools._prices import history_warnings_for_range, slice_prices
from tools.common import Snapshot, ToolFailure, ToolOutput, run_tool

TOOL = ToolName.GET_INDEX_HISTORY


def _handler(p: GetIndexHistoryParams, snap: Snapshot) -> ToolOutput:
    if snap.index.empty:
        raise ToolFailure("NO_DATA", f"{p.index.value} için snapshot {snap.data_version} içinde veri yok")
    rows, effective_end, warnings = slice_prices(snap.index, p.start, p.end, p.as_of, PriceAdjustment.ADJUSTED)
    warnings += history_warnings_for_range(snap, p.index.value, p.start, p.as_of, rows, effective_end)
    res = GetIndexHistoryResult(
        index=p.index, yahoo_symbol=str(snap.manifest.get("index_symbol", "XU100.IS")),
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
