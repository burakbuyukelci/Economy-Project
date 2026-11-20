"""tools/common.py: enforce_as_of, input_hash, snapshot yükleme, zarf kurma."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from schemas import validate_envelope
from schemas.enums import ToolName
from tools.common import (
    InvalidToolCall,
    LookAheadError,
    enforce_as_of,
    input_hash,
    load_snapshot,
    resolve_data_version,
)
from tests.conftest import DATA_VERSION


def frame():
    return pd.DataFrame({"date": pd.to_datetime(["2026-09-09", "2026-09-10", "2026-09-11", "2026-09-14"]),
                         "x": [1, 2, 3, 4]})


# --- enforce_as_of --------------------------------------------------------
def test_enforce_as_of_is_inclusive():
    out = enforce_as_of(frame(), date(2026, 9, 10))
    assert list(out["x"]) == [1, 2]
    assert out["date"].max() == pd.Timestamp("2026-09-10")


def test_enforce_as_of_cuts_all_later_rows_even_weekend_as_of():
    out = enforce_as_of(frame(), date(2026, 9, 13))  # Pazar
    assert list(out["x"]) == [1, 2, 3]


def test_enforce_as_of_does_not_mutate_input():
    df = frame()
    enforce_as_of(df, date(2026, 9, 10))
    assert len(df) == 4


def test_enforce_as_of_before_all_data_returns_empty():
    assert enforce_as_of(frame(), date(2020, 1, 1)).empty


def test_enforce_as_of_missing_date_column_raises():
    with pytest.raises(KeyError):
        enforce_as_of(pd.DataFrame({"a": [1]}), date(2026, 9, 10))


def test_enforce_as_of_rejects_string_as_of():
    with pytest.raises(TypeError):
        enforce_as_of(frame(), "2026-09-10")


def test_enforce_as_of_custom_column():
    df = frame().rename(columns={"date": "disclosure_date"})
    assert len(enforce_as_of(df, date(2026, 9, 10), date_col="disclosure_date")) == 2


def test_look_ahead_error_exists():
    assert issubclass(LookAheadError, Exception)


# --- input_hash -----------------------------------------------------------
def test_input_hash_stable_and_key_order_independent():
    a = input_hash("get_stock_history", {"ticker": "THYAO", "as_of": "2026-09-10"}, DATA_VERSION)
    b = input_hash("get_stock_history", {"as_of": "2026-09-10", "ticker": "THYAO"}, DATA_VERSION)
    assert a == b and len(a) == 64


def test_input_hash_differs_by_tool_param_and_version():
    base = input_hash("get_stock_history", {"ticker": "THYAO"}, DATA_VERSION)
    assert base != input_hash("get_index_history", {"ticker": "THYAO"}, DATA_VERSION)
    assert base != input_hash("get_stock_history", {"ticker": "ASELS"}, DATA_VERSION)
    assert base != input_hash("get_stock_history", {"ticker": "THYAO"}, "snap_2026-11-21_v1")


def test_input_hash_matches_schema_definition():
    from schemas.hashing import compute_input_hash
    p = {"ticker": "THYAO"}
    assert input_hash("get_stock_history", p, DATA_VERSION) == compute_input_hash("get_stock_history", p, DATA_VERSION)


# --- snapshot -------------------------------------------------------------
def test_load_snapshot_explicit_and_latest(snapshot_root):
    s = load_snapshot(root=snapshot_root)  # LATEST
    assert s.data_version == DATA_VERSION
    assert {"THYAO", "MGROS"} == set(s.stocks["ticker"])
    assert s.index["date"].is_monotonic_increasing
    assert load_snapshot(DATA_VERSION, root=snapshot_root).data_version == DATA_VERSION


def test_resolve_data_version_env_override(snapshot_root, monkeypatch):
    monkeypatch.setenv("SNAPSHOT_VERSION", "snap_2026-01-01_v9")
    assert resolve_data_version(snapshot_root) == "snap_2026-01-01_v9"


def test_load_snapshot_missing_version_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot("snap_2026-01-01_v1", root=tmp_path)


def test_invalid_tool_call_is_exception():
    assert issubclass(InvalidToolCall, Exception)
    assert ToolName.GET_STOCK_HISTORY and validate_envelope  # içe aktarma sağlığı
