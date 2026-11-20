"""get_stock_history / get_index_history: look-ahead, determinizm, hata durumları."""
from __future__ import annotations

import pytest

from schemas import SCHEMA_VERSION, validate_envelope
from tests.conftest import AS_OF, DATA_VERSION
from tools import get_index_history, get_stock_history
from tools.common import InvalidToolCall


def call_stock(snapshot_root, **over):
    p = {"ticker": "THYAO", "start": "2026-08-24", "end": "2026-09-18", "as_of": AS_OF, **over}
    return get_stock_history.run_on(p, snapshot_root=snapshot_root)


def call_index(snapshot_root, **over):
    p = {"index": "XU100", "start": "2026-08-24", "end": "2026-09-18", "as_of": AS_OF, **over}
    return get_index_history.run_on(p, snapshot_root=snapshot_root)


def dates(env):
    return [r["date"] for r in env["results"]["rows"]]


# --- as_of / look-ahead -----------------------------------------------------
def test_no_row_after_as_of_stock(snapshot_root):
    env = call_stock(snapshot_root)
    assert env["status"] == "OK"
    ds = dates(env)
    assert ds and max(ds) == AS_OF
    assert all(d <= AS_OF for d in ds)
    assert "2026-09-11" not in ds  # veride var ama as_of sonrası
    assert env["results"]["n_rows"] == 14 == len(ds)
    assert env["results"]["last_date"] == AS_OF
    assert env["results"]["effective_end"] == AS_OF


def test_no_row_after_as_of_index(snapshot_root):
    env = call_index(snapshot_root)
    ds = dates(env)
    assert max(ds) == AS_OF and all(d <= AS_OF for d in ds) and env["results"]["n_rows"] == 14


def test_as_of_is_inclusive(snapshot_root):
    env = call_stock(snapshot_root, as_of="2026-09-04")
    assert max(dates(env)) == "2026-09-04"


def test_as_of_on_weekend_returns_friday(snapshot_root):
    env = call_stock(snapshot_root, as_of="2026-09-12")  # Cumartesi
    assert max(dates(env)) == "2026-09-11"


def test_end_before_as_of_is_respected_without_clamp_warning(snapshot_root):
    env = call_stock(snapshot_root, end="2026-09-04")
    assert max(dates(env)) == "2026-09-04"
    assert not any(w.startswith("AS_OF_CLAMPED") for w in env["warnings"])


def test_end_after_as_of_clamped_with_warning(snapshot_root):
    env = call_stock(snapshot_root)  # end 2026-09-18 > as_of
    assert any(w.startswith("AS_OF_CLAMPED") for w in env["warnings"])
    assert env["results"]["requested_end"] == "2026-09-18"


def test_start_after_as_of_gives_empty_ok_with_warning(snapshot_root):
    env = call_stock(snapshot_root, start="2026-09-14", end="2026-09-18")
    assert env["status"] == "OK" and env["results"]["n_rows"] == 0
    assert env["results"]["first_date"] is None and env["results"]["last_date"] is None
    assert any(w.startswith("INSUFFICIENT_HISTORY") for w in env["warnings"])


def test_snapshot_is_not_truncated_by_earlier_call(snapshot_root):
    """Önbellekteki snapshot kesilirse sonraki geç as_of çağrısı eksik veri döner (sinsi hata)."""
    early = call_stock(snapshot_root, as_of="2026-08-28")
    late = call_stock(snapshot_root, as_of="2026-09-18")
    assert max(dates(early)) == "2026-08-28"
    assert max(dates(late)) == "2026-09-18" and late["results"]["n_rows"] == 20


# --- determinizm ------------------------------------------------------------
def test_same_call_same_hash_and_output(snapshot_root):
    a, b = call_stock(snapshot_root), call_stock(snapshot_root)
    assert a == b and a["input_hash"] == b["input_hash"]


def test_equivalent_param_spellings_same_hash(snapshot_root):
    a = call_stock(snapshot_root)
    b = get_stock_history.run_on(
        {"as_of": AS_OF, "end": "2026-09-18", "start": "2026-08-24", "ticker": "THYAO"}, snapshot_root=snapshot_root)
    assert a["input_hash"] == b["input_hash"]


def test_hash_changes_with_as_of_ticker_and_data_version(snapshot_root):
    base = call_stock(snapshot_root)["input_hash"]
    assert call_stock(snapshot_root, as_of="2026-09-09")["input_hash"] != base
    assert call_stock(snapshot_root, ticker="MGROS")["input_hash"] != base
    assert call_index(snapshot_root)["input_hash"] != base


def test_envelope_validates_against_contract(snapshot_root):
    for env in (call_stock(snapshot_root), call_index(snapshot_root)):
        assert validate_envelope(env).data_version == DATA_VERSION
        assert env["schema_version"] == SCHEMA_VERSION and env["as_of"] == AS_OF
        assert env["n_events"] is None and env["n_excluded_incomplete_horizon"] == 0


# --- hata durumları ---------------------------------------------------------
def test_unknown_ticker_returns_error_status(snapshot_root):
    env = call_stock(snapshot_root, ticker="ZZZZZ")
    assert env["status"] == "ERROR" and env["results"] is None
    assert env["error"]["code"] == "UNKNOWN_TICKER"
    validate_envelope(env)


def test_universe_ticker_missing_in_snapshot_returns_no_data(snapshot_root):
    env = call_stock(snapshot_root, ticker="ASELS")  # evrende var, sentetik snapshot'ta yok
    assert env["status"] == "ERROR" and env["error"]["code"] == "NO_DATA"


def test_invalid_params_with_valid_as_of_returns_error_envelope(snapshot_root):
    env = call_stock(snapshot_root, ticker="thy")  # desen ihlali
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"
    assert env["as_of"] == AS_OF
    validate_envelope(env)


def test_start_after_end_is_invalid_params(snapshot_root):
    env = call_stock(snapshot_root, start="2026-09-10", end="2026-09-01")
    assert env["error"]["code"] == "INVALID_PARAMS"


def test_missing_or_bad_as_of_raises_invalid_tool_call(snapshot_root):
    with pytest.raises(InvalidToolCall):
        get_stock_history.run_on({"ticker": "THYAO", "start": "2026-09-01", "end": "2026-09-10"},
                              snapshot_root=snapshot_root)
    with pytest.raises(InvalidToolCall):
        get_stock_history.run_on({"ticker": "THYAO", "start": "2026-09-01", "end": "2026-09-10",
                               "as_of": "10/09/2026"}, snapshot_root=snapshot_root)


def test_unknown_index_is_invalid_params(snapshot_root):
    env = call_index(snapshot_root, index="XU030")
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


# --- fiyat alanı / eksik gün ------------------------------------------------
def test_adjusted_mode_scales_ohlc_by_adj_factor(snapshot_root):
    row = call_stock(snapshot_root, start="2026-08-24", end="2026-08-24")["results"]["rows"][0]
    # sentetik: close=100, adj_close=50 (faktör 0.5), open=99, high=102, low=98
    assert row["close"] == row["adj_close"] == 50.0
    assert (row["open"], row["high"], row["low"]) == (49.5, 51.0, 49.0)


def test_unadjusted_mode_returns_raw_prices(snapshot_root):
    env = call_stock(snapshot_root, start="2026-08-24", end="2026-08-24", price_adjustment="unadjusted")
    row = env["results"]["rows"][0]
    assert (row["open"], row["high"], row["low"], row["close"], row["adj_close"]) == (99.0, 102.0, 98.0, 100.0, 50.0)
    assert env["results"]["price_adjustment"] == "unadjusted"


def test_default_price_adjustment_is_adjusted(snapshot_root):
    assert call_stock(snapshot_root)["results"]["price_adjustment"] == "adjusted"


def test_missing_trading_day_vs_index_calendar_warns(snapshot_root):
    env = call_stock(snapshot_root, ticker="MGROS")  # 2026-09-03 eksik
    assert env["results"]["n_rows"] == 13
    w = [x for x in env["warnings"] if x.startswith("MISSING_TRADING_DAYS")]
    assert w and "2026-09-03" in w[0]
    assert not any(x.startswith("MISSING_TRADING_DAYS") for x in call_stock(snapshot_root)["warnings"])


# --- fiyat sıçraması uyarıları: as_of öncesi görünür, as_of SONRASI asla sızmaz ---------------------
def jump_warnings(env):
    return [w for w in env["warnings"] if w.startswith("PRICE_JUMP_OVER_LIMIT")]


def test_jump_inside_range_is_warned_with_details(snapshot_root):
    w = jump_warnings(call_stock(snapshot_root))
    assert len(w) == 1 and "2026-09-02" in w[0] and "-90.7" in w[0] and "THYAO" in w[0]


def test_jump_after_as_of_never_appears_anywhere_in_output(snapshot_root):
    import json
    env = call_stock(snapshot_root)  # as_of 2026-09-10; 2026-09-14 sıçraması as_of sonrası
    blob = json.dumps(env, ensure_ascii=False)
    assert "2026-09-14" not in blob and "33.3" not in blob


def test_jump_is_reported_once_as_of_reaches_it(snapshot_root):
    w = jump_warnings(call_stock(snapshot_root, as_of="2026-09-18"))
    assert len(w) == 2 and any("2026-09-14" in x for x in w)


def test_no_jump_warning_when_range_excludes_it(snapshot_root):
    assert jump_warnings(call_stock(snapshot_root, start="2026-09-03")) == []


def test_other_tickers_jumps_not_mixed_in(snapshot_root):
    assert jump_warnings(call_stock(snapshot_root, ticker="MGROS")) == []


def test_index_jump_warning(snapshot_root):
    w = jump_warnings(call_index(snapshot_root))
    assert len(w) == 1 and "XU100" in w[0] and "2026-09-08" in w[0]


# --- birleşik işlem takvimi ------------------------------------------------------------------------
def test_day_missing_only_in_index_is_flagged_for_index_not_for_stock(tmp_path):
    """XU100 bir işlem gününü (ör. 25 Aralık) üretmiyor ama hisseler üretiyor: takvimde SAYILIR."""
    from tests.conftest import DATES, make_frame, make_snapshot
    import pandas as pd
    stocks = pd.concat([make_frame("THYAO", 100, DATES), make_frame("MGROS", 200, DATES)], ignore_index=True)
    index = make_frame("XU100", 10000, DATES, 1.0).drop(columns=["ticker"])
    index = index[index["date"] != pd.Timestamp("2026-09-02")]
    root = make_snapshot(tmp_path, stocks, index)
    idx_env = get_index_history.run_on({"index": "XU100", "start": "2026-08-24", "end": "2026-09-10", "as_of": AS_OF},
                                    snapshot_root=root)
    w = [x for x in idx_env["warnings"] if x.startswith("MISSING_TRADING_DAYS")]
    assert w and "2026-09-02" in w[0]
    stk_env = get_stock_history.run_on({"ticker": "THYAO", "start": "2026-08-24", "end": "2026-09-10", "as_of": AS_OF},
                                    snapshot_root=root)
    assert not any(x.startswith("MISSING_TRADING_DAYS") for x in stk_env["warnings"])


def test_day_missing_in_stocks_but_present_in_index_is_flagged_for_stocks(tmp_path):
    """2024-04-09 benzeri: endekste var, hisselerin çoğunda yok -> takvimde (endeks sayesinde) ve hisse eksik."""
    from tests.conftest import DATES, make_frame, make_snapshot
    import pandas as pd
    drop = pd.Timestamp("2026-09-02")
    stocks = pd.concat([make_frame("THYAO", 100, DATES), make_frame("MGROS", 200, DATES)], ignore_index=True)
    stocks = stocks[stocks["date"] != drop]
    index = make_frame("XU100", 10000, DATES, 1.0).drop(columns=["ticker"])
    root = make_snapshot(tmp_path, stocks, index)
    env = get_stock_history.run_on({"ticker": "THYAO", "start": "2026-08-24", "end": "2026-09-10", "as_of": AS_OF},
                                snapshot_root=root)
    w = [x for x in env["warnings"] if x.startswith("MISSING_TRADING_DAYS")]
    assert w and "2026-09-02" in w[0]


def test_calendar_never_includes_dates_after_as_of_in_warnings(tmp_path):
    from tests.conftest import DATES, make_frame, make_snapshot
    import json
    import pandas as pd
    stocks = pd.concat([make_frame("THYAO", 100, DATES), make_frame("MGROS", 200, DATES)], ignore_index=True)
    stocks = stocks[~((stocks["ticker"] == "THYAO") & (stocks["date"] == pd.Timestamp("2026-09-15")))]
    index = make_frame("XU100", 10000, DATES, 1.0).drop(columns=["ticker"])
    root = make_snapshot(tmp_path, stocks, index)
    env = get_stock_history.run_on({"ticker": "THYAO", "start": "2026-08-24", "end": "2026-09-18", "as_of": AS_OF},
                                snapshot_root=root)
    assert "2026-09-15" not in json.dumps(env)  # as_of sonrası eksik gün bilgisi sızmaz


def test_yahoo_symbols_in_results(snapshot_root):
    assert call_stock(snapshot_root)["results"]["yahoo_symbol"] == "THYAO.IS"
    assert call_index(snapshot_root)["results"]["yahoo_symbol"] == "XU100.IS"


def test_rows_sorted_and_unique(snapshot_root):
    ds = dates(call_stock(snapshot_root))
    assert ds == sorted(ds) and len(ds) == len(set(ds))
