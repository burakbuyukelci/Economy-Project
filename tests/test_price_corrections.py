"""scripts/apply_price_corrections.py: v2 = f(v1, csv); v1 dokunulmaz; manifest izlenebilirliği.

Sentetik testler küçük bir v1 üzerinde; gerçek testler commit edilmiş snap_2026-11-20_v1/v2 üzerinde
(yoksa atlanır).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config.settings import PRICE_CORRECTIONS_CSV, SNAPSHOT_DIR
from schemas.enums import DQSeverity, GateStatus
from scripts.apply_price_corrections import (
    apply_corrections,
    build_corrected_snapshot,
    load_corrections,
)
from scripts.download_prices import CANONICAL_COLUMNS
from tests.conftest import DATES, make_frame, make_snapshot
from tools.common import load_snapshot
from tools.price_quality import classify_price_jumps, gate_from_issues, price_jump_report

V1, V2 = "snap_2026-11-20_v1", "snap_2026-11-20_v2"
CSV_HEADER = "ticker,date_from,date_to,price_divisor,volume_multiplier,source\n"
PRICE_COLS = ["open", "high", "low", "close", "adj_close", "dividends"]


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_csv(path: Path, *rows: str) -> Path:
    path.write_text(CSV_HEADER + "".join(r + "\n" for r in rows), encoding="utf-8")
    return path


def synthetic_v1(root: Path) -> Path:
    """THYAO: ilk 5 gün 11 kat yüksek (düzeltilmemiş bölünme sonrası düşüş), MGROS düz."""
    th = make_frame("THYAO", 100, DATES)
    th.loc[:4, ["open", "high", "low", "close", "adj_close"]] *= 11  # 2026-08-24..28 yüksek
    th.loc[:4, "volume"] /= 11
    mg = make_frame("MGROS", 200, DATES)
    stocks = pd.concat([th, mg], ignore_index=True)
    index = make_frame("XU100", 10000, DATES, 1.0).drop(columns=["ticker"])
    jumps = price_jump_report(stocks) + [dict(r, ticker="XU100") for r in price_jump_report(index)]
    make_snapshot(root, stocks, index, jumps=jumps)
    return root


@pytest.fixture()
def v1_root(tmp_path):
    return synthetic_v1(tmp_path / "src")


@pytest.fixture()
def csv_path(tmp_path):
    return write_csv(tmp_path / "corr.csv", "THYAO,,2026-08-28,11,11,KAP 1323127")


def build(v1_root, csv_path, out_root, out_version=None):
    return build_corrected_snapshot(v1_root, "snap_2026-11-20_v1", csv_path, out_root, out_version)


# --- doğrulama (csv) -----------------------------------------------------------------------------
@pytest.mark.parametrize("row, msg", [
    ("ZZZZZ,,2026-08-28,11,11,KAP 1323127", "evrende"),
    ("THYAO,,2026-08-28,0,11,KAP 1323127", "price_divisor"),
    ("THYAO,,2026-08-28,11,-1,KAP 1323127", "volume_multiplier"),
    ("THYAO,2026-09-01,2026-08-28,11,11,KAP 1323127", "date_from"),
    ("THYAO,,2026-08-28,11,11,", "source"),
    ("THYAO,,2026-08-28,abc,11,KAP 1323127", "price_divisor"),
])
def test_csv_validation_rejects_bad_rows(tmp_path, row, msg):
    p = write_csv(tmp_path / "c.csv", row)
    with pytest.raises(ValueError, match=msg):
        load_corrections(p)


def test_csv_validation_rejects_overlapping_rules_and_missing_columns(tmp_path):
    p = write_csv(tmp_path / "c.csv", "THYAO,,2026-08-28,11,11,KAP 1323127", "THYAO,2026-08-27,,2,2,KAP 1323127")
    with pytest.raises(ValueError, match="çakış"):
        load_corrections(p)
    q = tmp_path / "d.csv"
    q.write_text("ticker,price_divisor\nTHYAO,11\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sütun"):
        load_corrections(q)


def test_rule_that_affects_no_rows_is_an_error(v1_root, tmp_path):
    p = write_csv(tmp_path / "c.csv", "THYAO,2030-01-01,2030-12-31,11,11,KAP 1323127")
    with pytest.raises(ValueError, match="hiç satır"):
        build(v1_root, p, tmp_path / "out")


# --- matematik -----------------------------------------------------------------------------------
def test_apply_divides_prices_multiplies_volume_only_inside_range_and_ticker(v1_root, csv_path):
    v1 = load_snapshot("snap_2026-11-20_v1", v1_root).stocks
    out, applied = apply_corrections(v1, load_corrections(csv_path))
    cut = pd.Timestamp("2026-08-28")
    m = (v1["ticker"] == "THYAO") & (v1["date"] <= cut)
    np.testing.assert_allclose(out.loc[m, PRICE_COLS].to_numpy(), v1.loc[m, PRICE_COLS].to_numpy() / 11, rtol=1e-12)
    np.testing.assert_allclose(out.loc[m, "volume"].to_numpy(), v1.loc[m, "volume"].to_numpy() * 11, rtol=1e-12)
    pd.testing.assert_frame_equal(out.loc[~m], v1.loc[~m])            # diğer her şey birebir aynı
    pd.testing.assert_series_equal(out["stock_splits"], v1["stock_splits"])  # kayıt alanı dokunulmaz
    assert len(out) == len(v1) and applied[0]["n_rows_affected"] == int(m.sum()) == 5


def test_apply_does_not_mutate_input_frame(v1_root, csv_path):
    v1 = load_snapshot("snap_2026-11-20_v1", v1_root).stocks
    before = v1.copy(deep=True)
    apply_corrections(v1, load_corrections(csv_path))
    pd.testing.assert_frame_equal(v1, before)


def test_correction_removes_the_jump_and_manifest_report_is_regenerated(v1_root, csv_path, tmp_path):
    v1_man = json.loads((v1_root / "snap_2026-11-20_v1" / "manifest.json").read_text(encoding="utf-8"))
    assert [j for j in v1_man["price_jump_report"] if j["ticker"] == "THYAO"], "v1 sentetik sıçrama içermeli"
    out = tmp_path / "out"
    v = build(v1_root, csv_path, out)
    man = json.loads((out / v / "manifest.json").read_text(encoding="utf-8"))
    assert [j for j in man["price_jump_report"] if j["ticker"] == "THYAO"] == []


# --- v2 = f(v1, csv): determinizm, v1 dokunulmazlığı, izlenebilirlik ------------------------------
def test_build_is_deterministic(v1_root, csv_path, tmp_path):
    a = build(v1_root, csv_path, tmp_path / "a")
    b = build(v1_root, csv_path, tmp_path / "b")
    assert a == b == "snap_2026-11-20_v2"
    for name in ("stocks.parquet", "index.parquet"):
        assert sha(tmp_path / "a" / a / name) == sha(tmp_path / "b" / b / name)
    assert (tmp_path / "a" / a / "manifest.json").read_bytes() == (tmp_path / "b" / b / "manifest.json").read_bytes()


def test_v1_is_left_untouched(v1_root, csv_path, tmp_path):
    files = [p for p in (v1_root / "snap_2026-11-20_v1").iterdir()] + [v1_root / "LATEST"]
    before = {p.name: sha(p) for p in files}
    build(v1_root, csv_path, tmp_path / "out")
    assert {p.name: sha(p) for p in files} == before
    assert sorted(p.name for p in v1_root.iterdir()) == ["LATEST", "snap_2026-11-20_v1"]


def test_build_refuses_to_overwrite_existing_version(v1_root, csv_path, tmp_path):
    build(v1_root, csv_path, tmp_path / "out")
    with pytest.raises(FileExistsError):
        build(v1_root, csv_path, tmp_path / "out", "snap_2026-11-20_v2")


def test_build_refuses_tampered_source(v1_root, csv_path, tmp_path):
    p = v1_root / "snap_2026-11-20_v1" / "stocks.parquet"
    p.write_bytes(p.read_bytes() + b"\x00")
    with pytest.raises(ValueError, match="sha256"):
        build(v1_root, csv_path, tmp_path / "out")


def test_manifest_traceability(v1_root, csv_path, tmp_path):
    out = tmp_path / "out"
    v = build(v1_root, csv_path, out)
    man = json.loads((out / v / "manifest.json").read_text(encoding="utf-8"))
    src = json.loads((v1_root / "snap_2026-11-20_v1" / "manifest.json").read_text(encoding="utf-8"))
    assert man["data_version"] == v
    assert man["corrections_csv"]["sha256"] == sha(csv_path)
    d = man["derived_from"]
    assert d["data_version"] == "snap_2026-11-20_v1"
    assert d["stocks_sha256"] == src["files"]["stocks.parquet"]["sha256"]
    assert d["index_sha256"] == src["files"]["index.parquet"]["sha256"]
    assert d["manifest_sha256"] == sha(v1_root / "snap_2026-11-20_v1" / "manifest.json")
    a = man["corrections_applied"]
    assert len(a) == 1 and a[0]["ticker"] == "THYAO" and a[0]["price_divisor"] == 11 and a[0]["volume_multiplier"] == 11
    assert a[0]["source"] == "KAP 1323127" and a[0]["n_rows_affected"] == 5
    assert a[0]["date_from"] is None and a[0]["date_to"] == "2026-08-28"
    assert man["created_utc"] == src["created_utc"]          # duvar saati yok: türetme deterministik
    assert "corrections" in man["price_policy"]


def test_default_out_version_is_next_number_for_source_date(v1_root, csv_path, tmp_path):
    assert build(v1_root, csv_path, tmp_path / "x") == "snap_2026-11-20_v2"


def test_latest_pointer_points_to_new_version_in_out_root(v1_root, csv_path, tmp_path):
    out = tmp_path / "out"
    v = build(v1_root, csv_path, out)
    assert (out / "LATEST").read_text().strip() == v


# --- GERÇEK snapshot: v1 bozuk (HARD_BLOCK), v2 düzeltilmiş --------------------------------------
real = pytest.mark.skipif(not ((SNAPSHOT_DIR / V1).exists() and (SNAPSHOT_DIR / V2).exists()),
                          reason="gerçek v1/v2 snapshot yok")


@real
def test_v1_ccola_falls_to_hard_block_in_analysis_window():
    v1 = load_snapshot(V1)
    issues = classify_price_jumps(v1.stocks, ["CCOLA"], date(2024, 1, 1), date(2026, 9, 10), date(2026, 9, 10))
    assert len(issues) == 1
    assert issues[0].severity == DQSeverity.HARD and issues[0].date == date(2024, 8, 1)
    assert gate_from_issues(issues) == GateStatus.HARD_BLOCK


@real
def test_v1_other_tickers_do_not_hard_block_in_analysis_window():
    v1 = load_snapshot(V1)
    others = sorted(set(v1.stocks["ticker"]) - {"CCOLA"})
    issues = classify_price_jumps(v1.stocks, others, date(2024, 1, 1), date(2026, 9, 10), date(2026, 9, 10))
    assert issues == []


@real
def test_v1_pre_window_2023_02_15_is_market_wide_soft_not_hard():
    v1 = load_snapshot(V1)
    issues = classify_price_jumps(v1.stocks, ["THYAO"], date(2023, 1, 1), date(2023, 3, 1), date(2026, 9, 10))
    assert len(issues) == 1 and issues[0].severity == DQSeverity.SOFT and issues[0].date == date(2023, 2, 15)
    assert gate_from_issues(issues) == GateStatus.PASS_WITH_WARNINGS


@real
def test_v2_ccola_has_no_flags_and_passes_gate():
    v2 = load_snapshot(V2)
    full = classify_price_jumps(v2.stocks, ["CCOLA"], date(2023, 1, 1), date(2026, 9, 10), date(2026, 9, 10))
    assert [i for i in full if i.severity == DQSeverity.HARD] == []
    window = classify_price_jumps(v2.stocks, ["CCOLA"], date(2024, 1, 1), date(2026, 9, 10), date(2026, 9, 10))
    assert window == [] and gate_from_issues(window) == GateStatus.PASS


@real
def test_v2_manifest_jump_report_regenerated_no_ccola_and_nothing_in_analysis_window():
    man = json.loads((SNAPSHOT_DIR / V2 / "manifest.json").read_text(encoding="utf-8"))
    rep = man["price_jump_report"]
    # CCOLA'nın 2024-08-01 bayrağı kalkmış olmalı; geriye yalnızca 30 hissenin ortak 2023-02-15 bayrağı kalır
    assert [j for j in rep if j["ticker"] == "CCOLA" and j["date"] != "2023-02-15"] == []
    assert [j for j in rep if j["ticker"] == "CCOLA" and j["date"] >= "2024-01-01"] == []
    assert [j for j in rep if j["date"] >= "2024-01-01"] == []
    assert {j["date"] for j in rep} == {"2023-02-15"} and len(rep) == 30


@real
def test_v2_equals_rebuild_from_v1_and_csv(tmp_path):
    v = build_corrected_snapshot(SNAPSHOT_DIR, V1, PRICE_CORRECTIONS_CSV, tmp_path, V2)
    mine, committed = load_snapshot(v, tmp_path), load_snapshot(V2)
    pd.testing.assert_frame_equal(mine.stocks, committed.stocks)
    pd.testing.assert_frame_equal(mine.index, committed.index)
    m1 = {k: v_ for k, v_ in mine.manifest.items() if k != "files"}
    m2 = {k: v_ for k, v_ in committed.manifest.items() if k != "files"}
    assert m1 == m2
    assert {k: v_["rows"] for k, v_ in mine.manifest["files"].items()} == \
           {k: v_["rows"] for k, v_ in committed.manifest["files"].items()}


@real
def test_v1_files_match_their_manifest_and_are_unchanged_by_building_v2(tmp_path):
    d = SNAPSHOT_DIR / V1
    before = {p.name: sha(p) for p in d.iterdir()}
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    for name, info in man["files"].items():
        assert before[name] == info["sha256"]
    build_corrected_snapshot(SNAPSHOT_DIR, V1, PRICE_CORRECTIONS_CSV, tmp_path, V2)
    assert {p.name: sha(p) for p in d.iterdir()} == before


@real
def test_v2_only_ccola_before_2024_08_01_changed_and_math_is_exact():
    v1, v2 = load_snapshot(V1), load_snapshot(V2)
    a, b = v1.stocks, v2.stocks
    assert list(b.columns) == CANONICAL_COLUMNS and len(a) == len(b)
    m = (a["ticker"] == "CCOLA") & (a["date"] <= pd.Timestamp("2024-07-31"))
    assert int(m.sum()) == 392  # CCOLA'nın 2023-01-02..2024-07-31 arası satırları (manifest: n_rows_affected)
    np.testing.assert_allclose(b.loc[m, PRICE_COLS].to_numpy(), a.loc[m, PRICE_COLS].to_numpy() / 11, rtol=1e-12)
    np.testing.assert_allclose(b.loc[m, "volume"].to_numpy(), a.loc[m, "volume"].to_numpy() * 11, rtol=1e-12)
    pd.testing.assert_frame_equal(b.loc[~m].reset_index(drop=True), a.loc[~m].reset_index(drop=True))
    pd.testing.assert_frame_equal(v2.index, v1.index)
    c = b[b["ticker"] == "CCOLA"].set_index("date")
    ret = c.loc["2024-08-01", "close"] / c.loc["2024-07-31", "close"] - 1
    assert ret == pytest.approx(0.01773, abs=2e-4)           # 846/11 = 76,91 -> 78,27: +%1,77, normal bir gün


@real
def test_v2_manifest_records_csv_sources_and_v1_hashes():
    man = json.loads((SNAPSHOT_DIR / V2 / "manifest.json").read_text(encoding="utf-8"))
    src = json.loads((SNAPSHOT_DIR / V1 / "manifest.json").read_text(encoding="utf-8"))
    assert man["corrections_csv"]["sha256"] == sha(PRICE_CORRECTIONS_CSV)
    assert man["derived_from"]["data_version"] == V1
    assert man["derived_from"]["stocks_sha256"] == src["files"]["stocks.parquet"]["sha256"]
    assert man["derived_from"]["manifest_sha256"] == sha(SNAPSHOT_DIR / V1 / "manifest.json")
    (c,) = man["corrections_applied"]
    assert (c["ticker"], c["date_from"], c["date_to"], c["price_divisor"], c["volume_multiplier"]) == \
           ("CCOLA", None, "2024-07-31", 11, 11)
    assert c["source"] == "KAP bildirim 1323127"


# --- bölünme (stock_splits>0) sürekliliği: 30 hissenin tüm olayları, v2 üzerinde -------------------
@real
def test_split_events_price_and_volume_continuity_in_v2():
    st = load_snapshot(V2).stocks.sort_values(["ticker", "date"]).reset_index(drop=True)
    ev = st[st["stock_splits"] > 0]
    assert len(ev) == 18
    bad_price, bad_volume, big_moves = [], [], []
    for _, e in ev.iterrows():
        g = st[st["ticker"] == e["ticker"]].reset_index(drop=True)
        i = int(g.index[g["date"] == e["date"]][0])
        pre, post = g.iloc[max(0, i - 10):i], g.iloc[i:i + 10]
        if not 0.7 < post["close"].median() / pre["close"].median() < 1.43:
            bad_price.append((e["ticker"], str(e["date"].date())))
        v_ratio = post["volume"].median() / pre["volume"].median()
        if e["stock_splits"] >= 3 and v_ratio > e["stock_splits"] / 2:   # düzeltilmemiş hacim ~ faktör kadar artardı
            bad_volume.append((e["ticker"], str(e["date"].date()), round(float(v_ratio), 2)))
        ret = (g["adj_close"].pct_change() * 100).iloc[max(1, i - 20): i + 21]
        for j in ret.index[ret.abs() > 10.5]:
            big_moves.append((e["ticker"], str(g["date"].iloc[j].date())))
    assert bad_price == [] and bad_volume == []
    # ±20 gün içindeki tek >%10,5 hareket, bölünmeyle ilgisiz piyasa geneli 2023-02-15 açılışı olabilir
    assert {d for _, d in big_moves} <= {"2023-02-15"}, big_moves
