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


def test_v1_ccola_unadjusted_split_is_flagged_in_range():
    """v1 (ham Yahoo) CCOLA'daki düzeltilmemiş bedelsiz hâlâ uyarı olarak görünür (v1 değişmez)."""
    env = get_stock_history.run_on({"ticker": "CCOLA", "start": "2024-07-25", "end": "2024-08-10", "as_of": AS_OF},
                                   data_version="snap_2026-11-20_v1")
    w = [x for x in env["warnings"] if x.startswith("PRICE_JUMP_OVER_LIMIT")]
    assert w and "2024-08-01" in w[0] and env["data_version"] == "snap_2026-11-20_v1"


def test_v2_ccola_series_is_continuous_and_has_no_jump_warning():
    env = get_stock_history.run({"ticker": "CCOLA", "start": "2024-07-25", "end": "2024-08-10", "as_of": AS_OF})
    assert env["data_version"] == "snap_2026-11-20_v2"
    assert not [x for x in env["warnings"] if x.startswith("PRICE_JUMP_OVER_LIMIT")]
    by_date = {r["date"]: r for r in env["results"]["rows"]}
    assert 70 < by_date["2024-07-31"]["close"] < 80 and 70 < by_date["2024-08-01"]["close"] < 80


def test_known_calendar_gaps_are_reported(snap):
    a = get_stock_history.run({"ticker": "THYAO", "start": "2024-04-01", "end": "2024-04-30", "as_of": AS_OF})
    assert any("2024-04-09" in w for w in a["warnings"] if w.startswith("MISSING_TRADING_DAYS"))
    b = get_index_history.run({"index": "XU100", "start": "2024-12-20", "end": "2024-12-31", "as_of": AS_OF})
    assert any("2024-12-25" in w for w in b["warnings"] if w.startswith("MISSING_TRADING_DAYS"))


def test_determinism_on_real_data():
    p = {"ticker": "THYAO", "start": "2024-01-01", "end": "2026-09-10", "as_of": AS_OF}
    a, b = get_stock_history.run(p), get_stock_history.run(p)
    assert a == b and a["input_hash"] == b["input_hash"]


V1_RAW, V2_DEFAULT = "snap_2026-11-20_v1", "snap_2026-11-20_v2"


def test_latest_points_to_v2_and_tools_default_to_v2():
    assert (SNAPSHOT_DIR / "LATEST").read_text(encoding="utf-8").strip() == V2_DEFAULT
    s = get_stock_history.run({"ticker": "THYAO", "start": "2026-09-08", "end": "2026-09-10", "as_of": AS_OF})
    i = get_index_history.run({"index": "XU100", "start": "2026-09-08", "end": "2026-09-10", "as_of": AS_OF})
    assert s["data_version"] == i["data_version"] == V2_DEFAULT
    assert load_snapshot().data_version == V2_DEFAULT


def test_no_snapshot_version_hardcoded_in_tools_or_config():
    """Araçlar sürümü LATEST/SNAPSHOT_VERSION'dan alır; kodda sabit sürüm (özellikle ham v1) olmamalı."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    pat = re.compile(r"snap_\d{4}-\d{2}-\d{2}_v\d+")
    hits = {str(p.relative_to(root)): pat.findall(p.read_text(encoding="utf-8"))
            for folder in ("tools", "config") for p in (root / folder).rglob("*.py")
            if pat.search(p.read_text(encoding="utf-8"))}
    assert not hits, hits


def test_v1_is_raw_source_only_v2_manifest_declares_it_as_derived_from():
    import json
    man = json.loads((SNAPSHOT_DIR / V2_DEFAULT / "manifest.json").read_text(encoding="utf-8"))
    assert man["derived_from"]["data_version"] == V1_RAW
    assert load_snapshot(V1_RAW).data_version != load_snapshot().data_version


def test_hashed_text_files_are_lf_in_working_tree():
    """Manifest/LATEST/csv sha256'ları başka manifest'lere yazılıyor; her makinede aynı baytlar olmalı."""
    from config.settings import PRICE_CORRECTIONS_CSV
    files = [SNAPSHOT_DIR / "LATEST", PRICE_CORRECTIONS_CSV, *SNAPSHOT_DIR.glob("*/manifest.json")]
    assert len(files) >= 3
    for f in files:
        assert b"\r" not in f.read_bytes(), f"{f} CRLF içeriyor"
