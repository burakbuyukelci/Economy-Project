"""check_data_quality parametrelerini harness'in türetmesi: ticker, tarih aralığı, analysis_bundle."""
from __future__ import annotations

from datetime import date

import pytest

from config.universe import build_sector_peer_groups, load_universe
from harness.evidence import EnvelopeStore
from harness.gate_params import GateParamsError, detect_question_tickers, derive_gate_params
from harness.mock_tools import run_mock_tool
from schemas.enums import ToolName as T
from schemas.examples import example_params
from schemas.registry import validate_params

AS_OF = date(2026, 9, 10)
Q1 = ("Perakende sektöründe (BIMAS, MGROS, MAVI) 10.09.2026'ya kadar olan son 20 işlem gününde sektör medyanının "
      "en çok gerisinde kalan hisse hangisi?")
Q5 = "Bugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı?"


def derive(calls=(), question_tickers=(), records=()):
    return derive_gate_params(as_of=AS_OF, calls=list(calls), question_tickers=list(question_tickers), records=list(records))


# --- sorudan ticker (SELECT_UNIVERSE) ----------------------------------------------------------
def test_detects_tickers_from_real_questions_using_the_universe():
    assert detect_question_tickers(Q1) == ["BIMAS", "MAVI", "MGROS"]
    assert detect_question_tickers(Q5) == ["EREGL"]


def test_detection_is_exact_word_match_and_case_sensitive():
    assert detect_question_tickers("THYAOX ve thyao ve XTHYAO") == []
    assert detect_question_tickers("THYAO,ASELS;TUPRS.") == ["ASELS", "THYAO", "TUPRS"]


def test_every_universe_ticker_is_detectable():
    for t in load_universe()["ticker"]:
        assert detect_question_tickers(f"{t} nasıl?") == [t]


# --- ticker türetme ---------------------------------------------------------------------------------------
def test_ticker_from_a_single_pending_call():
    p = derive(calls=[(T.TEST_WEEKDAY_PATTERN, example_params(T.TEST_WEEKDAY_PATTERN))])
    assert p["tickers"] == ["THYAO"]


def test_union_of_ticker_tickers_and_universe_keys_over_all_calls():
    calls = [
        (T.GET_STOCK_HISTORY, {"ticker": "THYAO"}),
        (T.RUN_BACKTEST, {"universe": ["MAVI", "BIMAS"]}),
        (T.CHECK_DATA_QUALITY, {"tickers": ["ASELS"]}),
    ]
    assert derive(calls=calls)["tickers"] == ["ASELS", "BIMAS", "MAVI", "THYAO"]


def test_sector_expands_to_peer_group_members_from_the_universe_file():
    members = build_sector_peer_groups()["retail"]
    assert members  # BIMAS, MAVI, MGROS
    p = derive(calls=[(T.RANK_SECTOR_RELATIVE_STRENGTH, example_params(T.RANK_SECTOR_RELATIVE_STRENGTH))])
    assert p["tickers"] == sorted(members)


def test_question_tickers_are_only_a_fallback():
    assert derive(calls=[(T.GET_MACRO_CONTEXT, {"start": "2026-01-01"})], question_tickers=["EREGL"])["tickers"] == ["EREGL"]
    chosen = derive(calls=[(T.GET_STOCK_HISTORY, {"ticker": "THYAO"})], question_tickers=["EREGL"])
    assert chosen["tickers"] == ["THYAO"]


def test_invalid_ticker_strings_are_dropped_and_may_leave_nothing():
    with pytest.raises(GateParamsError) as exc:
        derive(calls=[(T.GET_STOCK_HISTORY, {"ticker": "thyao"})])
    assert exc.value.code == "TICKER_UNDETERMINED"


def test_undetermined_tickers_raise_with_actionable_message():
    with pytest.raises(GateParamsError) as exc:
        derive(calls=[(T.GET_MACRO_CONTEXT, {"start": "2026-01-01", "end": "2026-09-10"})])
    assert exc.value.code == "TICKER_UNDETERMINED"
    assert "ticker" in exc.value.message and "sector" in exc.value.message


# --- tarih aralığı ---------------------------------------------------------------------------------------------
def test_end_is_always_the_session_as_of_and_start_is_never_narrower_than_the_default_window():
    p = derive(calls=[(T.GET_STOCK_HISTORY, {"ticker": "THYAO", "start": "2026-09-08", "end": "2026-09-09"})])
    assert p["end"] == "2026-09-10" and p["start"] == "2024-01-01"


def test_start_widens_to_the_earliest_model_start():
    calls = [(T.GET_STOCK_HISTORY, {"ticker": "THYAO", "start": "2023-03-01"}),
             (T.TEST_WEEKDAY_PATTERN, {"ticker": "THYAO", "in_sample_start": "2023-06-01"})]
    assert derive(calls=calls)["start"] == "2023-03-01"


def test_unparseable_model_dates_are_ignored():
    assert derive(calls=[(T.GET_STOCK_HISTORY, {"ticker": "THYAO", "start": "dün"})])["start"] == "2024-01-01"


# --- analysis_bundle ------------------------------------------------------------------------------------------------
def make_records():
    store = EnvelopeStore()
    for t in (T.GET_STOCK_HISTORY, T.CHECK_DATA_QUALITY, T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST,
              T.BUILD_EVIDENCE_BUNDLE):
        store.add(run_mock_tool(t, example_params(t)), actor="model")
    err = run_mock_tool(T.GET_MACRO_CONTEXT, example_params(T.GET_MACRO_CONTEXT))
    err.update({"results": None, "n_events": None, "status": "ERROR", "error": {"code": "NO_DATA", "message": "x"}})
    store.add(err, actor="model")
    return store.records


def test_bundle_items_come_from_ok_envelopes_without_gate_and_evidence_envelopes():
    p = derive(calls=[(T.GET_STOCK_HISTORY, {"ticker": "THYAO"})], records=make_records())
    tools = [i["tool"] for i in p["analysis_bundle"]]
    assert tools == ["get_stock_history", "rank_sector_relative_strength", "run_backtest"]
    bt = p["analysis_bundle"][-1]
    assert bt["n_events"] == 22 and bt["as_of"] == "2026-09-10" and bt["data_version"] == "snap_1900-01-01_v0"
    assert set(bt) == {"tool", "as_of", "data_version", "input_hash", "n_events", "n_excluded_incomplete_horizon"}


def test_derived_params_are_valid_check_data_quality_params_and_deterministic():
    calls = [(T.GET_STOCK_HISTORY, {"ticker": "THYAO"})]
    p = derive(calls=calls, records=make_records())
    parsed = validate_params(T.CHECK_DATA_QUALITY, p)
    assert parsed.end == AS_OF and parsed.as_of == AS_OF and parsed.include_index is True
    assert derive(calls=calls, records=make_records()) == p
    run_mock_tool(T.CHECK_DATA_QUALITY, p)  # mock da kabul eder
