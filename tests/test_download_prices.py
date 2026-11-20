"""scripts/download_prices.py'nin saf (ağsız) parçaları."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from scripts.download_prices import (
    CANONICAL_COLUMNS,
    drop_incomplete_last_bar,
    next_data_version,
    normalize_frame,
    price_jump_report,
    write_snapshot,
)

IST = ZoneInfo("Europe/Istanbul")


def raw_yahoo(n=5, tz="Europe/Istanbul"):
    idx = pd.date_range("2026-09-01", periods=n, freq="B", tz=tz)
    return pd.DataFrame(
        {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Adj Close": 10.4, "Volume": 1000.0,
         "Dividends": 0.0, "Stock Splits": 0.0},
        index=idx,
    )


def test_normalize_columns_and_tz_naive_dates():
    df = normalize_frame(raw_yahoo(), ticker="THYAO")
    assert list(df.columns) == CANONICAL_COLUMNS
    assert df["date"].dt.tz is None
    assert df["date"].iloc[0] == pd.Timestamp("2026-09-01")  # yerel gün, UTC kayması yok
    assert (df["ticker"] == "THYAO").all()


def test_normalize_drops_nan_close_nonpositive_and_duplicates_and_sorts():
    raw = raw_yahoo(6)
    raw.iloc[1, raw.columns.get_loc("Close")] = np.nan
    raw.iloc[2, raw.columns.get_loc("Close")] = 0.0
    dup = raw.iloc[[4]].copy()
    raw = pd.concat([raw.iloc[::-1], dup])  # ters sıra + yinelenen gün
    df = normalize_frame(raw, ticker="THYAO")
    assert df["date"].is_monotonic_increasing and df["date"].is_unique
    assert len(df) == 4  # 6 gün - NaN kapanış - sıfır fiyat = 4 benzersiz gün; yinelenen gün tek sayılır
    assert (df["close"] > 0).all()


def test_normalize_does_not_forward_fill_missing_days():
    raw = raw_yahoo(5).drop(raw_yahoo(5).index[2])  # ortadan bir gün eksik
    df = normalize_frame(raw, ticker="X")
    assert len(df) == 4  # eksik gün doldurulmaz (uydurma veri yok)


def test_drop_incomplete_last_bar_before_close_drops_today():
    df = normalize_frame(raw_yahoo(5), ticker="X")  # son gün 2026-09-07
    now = datetime(2026, 9, 7, 14, 0, tzinfo=IST)   # seans içi
    out = drop_incomplete_last_bar(df, now)
    assert out["date"].max() == pd.Timestamp("2026-09-04")
    assert len(out) == len(df) - 1


def test_drop_incomplete_last_bar_after_close_keeps_today():
    df = normalize_frame(raw_yahoo(5), ticker="X")
    now = datetime(2026, 9, 7, 19, 0, tzinfo=IST)   # seans sonrası (>= 18:30)
    assert len(drop_incomplete_last_bar(df, now)) == len(df)


def test_drop_incomplete_last_bar_never_drops_past_days():
    df = normalize_frame(raw_yahoo(5), ticker="X")
    now = datetime(2026, 9, 20, 10, 0, tzinfo=IST)  # son bar geçmişte
    assert len(drop_incomplete_last_bar(df, now)) == len(df)


def test_next_data_version(tmp_path):
    assert next_data_version(tmp_path, date(2026, 11, 20)) == "snap_2026-11-20_v1"
    (tmp_path / "snap_2026-11-20_v1").mkdir()
    assert next_data_version(tmp_path, date(2026, 11, 20)) == "snap_2026-11-20_v2"
    assert next_data_version(tmp_path, date(2026, 11, 21)) == "snap_2026-11-21_v1"


def _jump_df(adj, close=None):
    n = len(adj)
    return pd.DataFrame({"ticker": "X", "date": pd.date_range("2026-09-01", periods=n, freq="B"),
                         "close": close or adj, "adj_close": adj})


def test_price_jump_report_flags_over_limit_only():
    df = _jump_df([100.0, 105.0, 94.5, 60.0, 61.0])  # +5, -10 (limit tam), -36.5, +1.7
    rep = price_jump_report(df, limit_pct=10.0, tolerance_pp=0.5)
    assert len(rep) == 1  # yalnız -36.5
    assert rep[0]["ticker"] == "X" and rep[0]["date"] == "2026-09-04"
    assert rep[0]["return_pct"] == pytest.approx(-36.5079, abs=1e-3)
    assert rep[0]["prev_date"] == "2026-09-03" and rep[0]["calendar_gap_days"] == 1


def test_price_jump_tolerance_boundary():
    # limit 10 + tolerans 0.5: +10.4 geçer (tick yuvarlaması), +10.6 bayraklanır
    assert price_jump_report(_jump_df([100.0, 110.4]), 10.0, 0.5) == []
    assert len(price_jump_report(_jump_df([100.0, 110.6]), 10.0, 0.5)) == 1
    assert len(price_jump_report(_jump_df([100.0, 89.0]), 10.0, 0.5)) == 1   # -11.0
    assert price_jump_report(_jump_df([100.0, 89.7]), 10.0, 0.5) == []       # -10.3


def test_price_jump_uses_adj_close_so_dividend_drop_in_raw_close_is_not_flagged():
    # ham close -15% (temettü günü) ama adj_close -3%: bayrak YOK
    df = _jump_df(adj=[100.0, 97.0], close=[100.0, 85.0])
    assert price_jump_report(df) == []


def test_price_jump_flags_unadjusted_split_even_in_adj_close():
    # düzeltilmemiş 1:11 bölünme: adj_close da -90.9% düşer -> bayrak VAR
    rep = price_jump_report(_jump_df([846.0, 78.27]))
    assert len(rep) == 1 and rep[0]["return_pct"] < -90


def test_price_jump_reports_multi_day_gap():
    df = pd.DataFrame({"ticker": "X", "date": pd.to_datetime(["2023-02-08", "2023-02-15"]),
                       "close": [100.0, 120.0], "adj_close": [100.0, 120.0]})
    rep = price_jump_report(df)
    assert rep[0]["calendar_gap_days"] == 7 and rep[0]["prev_date"] == "2023-02-08"


def test_write_snapshot_roundtrip_manifest_and_latest(tmp_path):
    stocks = pd.concat([normalize_frame(raw_yahoo(), "THYAO"), normalize_frame(raw_yahoo(), "MGROS")],
                       ignore_index=True)
    index = normalize_frame(raw_yahoo(), None)
    meta = {"source": "test", "download_start": "2023-01-01"}
    v = write_snapshot(stocks, index, tmp_path, "snap_2026-11-20_v1", meta)
    d = tmp_path / v
    assert (d / "stocks.parquet").exists() and (d / "index.parquet").exists()
    assert (tmp_path / "LATEST").read_text().strip() == v
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert man["data_version"] == v and man["source"] == "test"
    assert man["files"]["stocks.parquet"]["rows"] == len(stocks)
    sha = hashlib.sha256((d / "stocks.parquet").read_bytes()).hexdigest()
    assert man["files"]["stocks.parquet"]["sha256"] == sha
    back = pd.read_parquet(d / "stocks.parquet")
    assert len(back) == len(stocks) and set(back["ticker"]) == {"THYAO", "MGROS"}


def test_write_snapshot_refuses_to_overwrite_existing_version(tmp_path):
    stocks = normalize_frame(raw_yahoo(), "THYAO")
    index = normalize_frame(raw_yahoo(), None)
    write_snapshot(stocks, index, tmp_path, "snap_2026-11-20_v1", {})
    with pytest.raises(FileExistsError):
        write_snapshot(stocks, index, tmp_path, "snap_2026-11-20_v1", {})


def test_write_snapshot_text_files_are_lf_only_on_every_platform(tmp_path):
    stocks = normalize_frame(raw_yahoo(), "THYAO")
    index = normalize_frame(raw_yahoo(), None)
    v = write_snapshot(stocks, index, tmp_path, "snap_2026-11-20_v1", {})
    for f in (tmp_path / v / "manifest.json", tmp_path / "LATEST"):
        assert b"\r" not in f.read_bytes(), f"{f.name} CRLF içeriyor: manifest sha256'ları makineler arası tutmaz"
