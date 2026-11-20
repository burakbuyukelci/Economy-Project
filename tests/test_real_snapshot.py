"""Repoya commit edilmiş GERÇEK snapshot üzerinde bütünlük ve look-ahead testleri.

Snapshot sürümleri değişmezdir; bu testler `data/snapshots/LATEST` sürümünü kullanır. Snapshot yoksa atlanır.
"""
from __future__ import annotations

import hashlib
import json

import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from config.universe import load_universe
from schemas import validate_envelope
from tools import get_index_history, get_stock_history
from tools.common import load_snapshot

pytestmark = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")

AS_OF = "2026-09-10"


@pytest.fixture(scope="module")
def snap():
    return load_snapshot()


def test_manifest_matches_files_and_version(snap):
    d = SNAPSHOT_DIR / snap.data_version
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["data_version"] == snap.data_version == d.name
    for name, info in man["files"].items():
        assert hashlib.sha256((d / name).read_bytes()).hexdigest() == info["sha256"], f"{name} değişmiş!"
    assert man["index_symbol"] == "XU100.IS"


def test_all_universe_tickers_and_index_present(snap):
    assert set(snap.stocks["ticker"]) == set(load_universe()["ticker"])
    assert len(snap.index) > 900


def test_no_duplicates_nan_or_nonpositive_prices(snap):
    assert not snap.stocks.duplicated(["ticker", "date"]).any()
    assert snap.index["date"].is_unique
    cols = ["open", "high", "low", "close", "adj_close"]
    for df in (snap.stocks, snap.index):
        assert not df[cols].isna().any().any()
        assert (df[cols] > 0).all().all()
        assert df["date"].dt.tz is None


def test_download_start_covers_indicator_warmup(snap):
    assert snap.stocks["date"].min() == pd.Timestamp("2023-01-02")
    assert snap.manifest["download_start"] == "2023-01-01"
    assert snap.manifest["analysis_start_default"] == "2024-01-01"


def test_raw_snapshot_contains_rows_after_as_of_so_the_cut_test_is_meaningful(snap):
    th = snap.stocks[snap.stocks["ticker"] == "THYAO"]
    assert (th["date"] > pd.Timestamp(AS_OF)).sum() > 0
    assert (th["date"] == pd.Timestamp("2026-09-11")).any()


def test_thyao_as_of_2026_09_10_cut_matches_independent_count(snap):
    env = get_stock_history.run({"ticker": "THYAO", "start": "2024-01-01", "end": "2026-11-20", "as_of": AS_OF})
    validate_envelope(env)
    r = env["results"]
    th = snap.stocks[snap.stocks["ticker"] == "THYAO"]
    expected = th[(th["date"] >= "2024-01-01") & (th["date"] <= AS_OF)]
    assert r["n_rows"] == len(expected) and len(r["rows"]) == len(expected)
    assert r["last_date"] == AS_OF and r["first_date"] == "2024-01-02"
    assert max(row["date"] for row in r["rows"]) == AS_OF
    assert not any(row["date"] >= "2026-09-11" for row in r["rows"])


def test_index_as_of_cut(snap):
    env = get_index_history.run({"index": "XU100", "start": "2024-01-01", "end": "2026-11-20", "as_of": AS_OF})
    validate_envelope(env)
    assert env["results"]["last_date"] == AS_OF
    assert all(r["date"] <= AS_OF for r in env["results"]["rows"])


def test_every_ticker_respects_as_of(snap):
    for tk in load_universe()["ticker"]:
        env = get_stock_history.run({"ticker": tk, "start": "2023-01-01", "end": "2026-11-20", "as_of": AS_OF})
        assert env["status"] == "OK", tk
        assert env["results"]["last_date"] <= AS_OF, tk


def test_ccola_unadjusted_split_is_flagged_in_range(snap):
    env = get_stock_history.run({"ticker": "CCOLA", "start": "2024-07-25", "end": "2024-08-10", "as_of": AS_OF})
    w = [x for x in env["warnings"] if x.startswith("PRICE_JUMP_OVER_LIMIT")]
    assert w and "2024-08-01" in w[0]


def test_known_calendar_gaps_are_reported(snap):
    a = get_stock_history.run({"ticker": "THYAO", "start": "2024-04-01", "end": "2024-04-30", "as_of": AS_OF})
    assert any("2024-04-09" in w for w in a["warnings"] if w.startswith("MISSING_TRADING_DAYS"))
    b = get_index_history.run({"index": "XU100", "start": "2024-12-20", "end": "2024-12-31", "as_of": AS_OF})
    assert any("2024-12-25" in w for w in b["warnings"] if w.startswith("MISSING_TRADING_DAYS"))


def test_determinism_on_real_data():
    p = {"ticker": "THYAO", "start": "2024-01-01", "end": "2026-09-10", "as_of": AS_OF}
    a, b = get_stock_history.run(p), get_stock_history.run(p)
    assert a == b and a["input_hash"] == b["input_hash"]
