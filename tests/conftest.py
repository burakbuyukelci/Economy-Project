"""Ortak fixture'lar: ağsız, sentetik ama gerçek yazıcıyla üretilen küçük snapshot."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.download_prices import CANONICAL_COLUMNS, write_snapshot

DATA_VERSION = "snap_2026-11-20_v1"
AS_OF = "2026-09-10"  # Perşembe; 2026-09-11 (Cuma) veride VAR ama as_of sonrası
DATES = pd.bdate_range("2026-08-24", "2026-09-18")  # 20 işlem günü

# Manifest'teki sıçrama raporu: biri as_of ÖNCESİ, biri as_of SONRASI (sızıntı testi için)
JUMPS = [
    {"ticker": "THYAO", "date": "2026-09-02", "return_pct": -90.7, "adj_close_prev": 50.0, "adj_close": 4.6,
     "prev_date": "2026-09-01", "calendar_gap_days": 1},
    {"ticker": "THYAO", "date": "2026-09-14", "return_pct": 33.3, "adj_close_prev": 60.0, "adj_close": 80.0,
     "prev_date": "2026-09-11", "calendar_gap_days": 3},
    {"ticker": "XU100", "date": "2026-09-08", "return_pct": 12.0, "adj_close_prev": 100.0, "adj_close": 112.0,
     "prev_date": "2026-09-07", "calendar_gap_days": 1},
]


def make_frame(ticker, base, dates, adj_factor=0.5):
    n = len(dates)
    close = pd.Series([base + i for i in range(n)], dtype=float)
    return pd.DataFrame({
        "ticker": ticker, "date": dates, "open": close - 1, "high": close + 2, "low": close - 2,
        "close": close, "adj_close": close * adj_factor, "volume": [1000.0 + i for i in range(n)],
        "dividends": 0.0, "stock_splits": 0.0,
    })[CANONICAL_COLUMNS]


def make_snapshot(root, stocks, index, version=DATA_VERSION, jumps=None):
    meta = {"source": "synthetic-test", "download_start": "2023-01-01", "index_symbol": "XU100.IS",
            "analysis_start_default": "2024-01-01", "price_jump_limit_pct": 10.0, "price_jump_tolerance_pp": 0.5,
            "price_jump_report": jumps or []}
    write_snapshot(stocks, index, root, version, meta)
    return root


@pytest.fixture(scope="session")
def snapshot_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("snapshots")
    thyao = make_frame("THYAO", 100, DATES)
    # MGROS'ta 2026-09-03 eksik (hem THYAO hem XU100'de var -> eksik işlem günü testi)
    mgros = make_frame("MGROS", 200, DATES)
    mgros = mgros[mgros["date"] != pd.Timestamp("2026-09-03")].reset_index(drop=True)
    stocks = pd.concat([thyao, mgros], ignore_index=True)
    index = make_frame("XU100", 10000, DATES, adj_factor=1.0).drop(columns=["ticker"])
    return make_snapshot(root, stocks, index, jumps=JUMPS)
