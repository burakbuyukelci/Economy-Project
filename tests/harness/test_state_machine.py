"""Durum makinesi: araç alt kümeleri, zorunlu durumlar (araçlardan türetilir), güvenli hata yolu, insan incelemesi."""
from __future__ import annotations

import dataclasses

import pytest

from harness.event_log import EventLog
from harness.routing import DEFAULT_ROUTING, ReviewStatus, State as S
from harness.state_machine import HarnessRuleViolation, StateMachine
from schemas.enums import AllowedAction, ToolName as T


def ok(gate_status: str | None = None) -> dict:
    """Makinenin okuduğu en küçük başarılı zarf (yalnızca status ve gerekirse gate_status)."""
    results = {"gate_status": gate_status} if gate_status else {}
    return {"status": "OK", "results": results}


ERR = {"status": "ERROR", "results": None}


def call(m: StateMachine, tool: T, env: dict | None = None):
    """Önce check, izinliyse commit. Karar nesnesini döndürür."""
    d = m.check(tool)
    if d.allowed:
        m.commit(tool, env or ok())
    return d


def fresh(routing=DEFAULT_ROUTING) -> StateMachine:
    m = StateMachine(EventLog(), routing)
    m.begin()
    return m


# --- başlangıç ---------------------------------------------------------------
def test_begin_runs_start_and_select_universe_then_waits_at_load_market_data():
    m = fresh()
    assert m.state == S.LOAD_MARKET_DATA
    moves = [(e["from"], e["to"]) for e in m.log.of_kind("STATE_TRANSITION")]
    assert moves == [("START", "SELECT_UNIVERSE"), ("SELECT_UNIVERSE", "LOAD_MARKET_DATA")]


def test_tools_callable_at_start_include_optional_data_and_the_mandatory_quality_check():
    m = fresh()
    assert set(m.callable_tools()) == {T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY, T.CHECK_DATA_QUALITY}


# --- zorunlu CHECK_DATA_QUALITY atlanamaz --------------------------------------
@pytest.mark.parametrize("tool", [T.RANK_SECTOR_RELATIVE_STRENGTH, T.TEST_WEEKDAY_PATTERN, T.GET_MACRO_CONTEXT,
                                  T.BUILD_EVIDENCE_BUNDLE, T.RUN_BACKTEST])
def test_cannot_skip_check_data_quality(tool):
    m = fresh()
    d = m.check(tool)
    assert not d.allowed and d.code == "MANDATORY_STATE_SKIPPED"
    assert "CHECK_DATA_QUALITY" in d.message


def test_optional_market_data_may_be_skipped_and_quality_check_auto_advances():
    m = fresh()
    assert call(m, T.CHECK_DATA_QUALITY).allowed
    assert m.state == S.CALCULATE_TECHNICALS  # CHECK_DATA_QUALITY zorunlu araç çağrılınca otomatik ilerledi
    assert S.CHECK_DATA_QUALITY in m.completed


def test_failed_quality_call_does_not_satisfy_or_advance():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY, ERR)
    assert m.state == S.CHECK_DATA_QUALITY and S.CHECK_DATA_QUALITY not in m.completed
    assert not m.check(T.RANK_SECTOR_RELATIVE_STRENGTH).allowed
    assert m.check(T.CHECK_DATA_QUALITY).allowed  # yeniden deneme serbest


def test_going_back_to_a_passed_state_is_invalid():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    d = m.check(T.GET_STOCK_HISTORY)
    assert not d.allowed and d.code == "STATE_ALREADY_PASSED"


def test_repeated_calls_inside_the_same_state_are_allowed():
    m = fresh()
    call(m, T.GET_STOCK_HISTORY)
    assert call(m, T.GET_STOCK_HISTORY).allowed
    assert call(m, T.GET_INDEX_HISTORY).allowed and m.state == S.LOAD_MARKET_DATA


# --- zorunlu RUN_BACKTEST: araçlardan türetilir -----------------------------------
def catch_up_until_evidence(m: StateMachine) -> None:
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    call(m, T.BUILD_EVIDENCE_BUNDLE)


def test_backtest_becomes_mandatory_when_rank_sector_was_called():
    m = fresh()
    catch_up_until_evidence(m)
    d = m.check(T.CHECK_DATA_QUALITY)  # RISK_GATE'e atlamaya çalış
    assert not d.allowed and d.code == "MANDATORY_STATE_SKIPPED" and "RUN_BACKTEST" in d.message
    assert m.pending_mandatory() == [S.RUN_BACKTEST, S.RISK_GATE]


def test_backtest_then_risk_gate_completes_catch_up_flow():
    m = fresh()
    catch_up_until_evidence(m)
    call(m, T.RUN_BACKTEST)
    assert call(m, T.RUN_BACKTEST).allowed  # strateji varyantı karşılaştırması: aynı durumda tekrar
    assert m.state == S.RUN_BACKTEST
    assert call(m, T.CHECK_DATA_QUALITY).allowed
    assert m.state == S.GENERATE_EXPLANATION and m.pending_mandatory() == []


@pytest.mark.parametrize("analysis_tool", [T.TEST_WEEKDAY_PATTERN, T.DETECT_REVERSAL_EVENTS,
                                           T.CALCULATE_FUNDAMENTAL_CHANGE, T.GET_MACRO_CONTEXT])
def test_backtest_is_optional_for_other_analysis_tools(analysis_tool):
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, analysis_tool)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    assert call(m, T.CHECK_DATA_QUALITY).allowed  # RISK_GATE, backtest'siz
    assert m.state == S.GENERATE_EXPLANATION


def test_mandatory_set_comes_from_tools_actually_called_not_from_a_question_type():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)         # backtest zorunlu DEĞİL
    assert S.RUN_BACKTEST not in m.mandatory_states()
    # ... ama model aynı oturumda rank_sector'ı da çağırırsa zorunlu olur
    m2 = fresh()
    call(m2, T.CHECK_DATA_QUALITY)
    call(m2, T.RANK_SECTOR_RELATIVE_STRENGTH)
    call(m2, T.TEST_WEEKDAY_PATTERN)
    assert S.RUN_BACKTEST in m2.mandatory_states()


def test_failed_rank_sector_call_does_not_make_backtest_mandatory():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.RANK_SECTOR_RELATIVE_STRENGTH, ERR)
    assert S.RUN_BACKTEST not in m.mandatory_states()


def test_mandatory_table_is_data_not_code():
    # tablo değişince davranış değişir: hoca "weekday için de backtest" derse tek satır yeter
    routing = dataclasses.replace(
        DEFAULT_ROUTING,
        tool_triggers={**DEFAULT_ROUTING.tool_triggers, T.TEST_WEEKDAY_PATTERN: frozenset({S.RUN_BACKTEST})},
    )
    m = fresh(routing)
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    assert not m.check(T.CHECK_DATA_QUALITY).allowed


# --- kanıt paketi --------------------------------------------------------------------
def test_build_evidence_needs_at_least_one_analysis_result():
    m = fresh()
    call(m, T.GET_STOCK_HISTORY)
    call(m, T.CHECK_DATA_QUALITY)
    d = m.check(T.BUILD_EVIDENCE_BUNDLE)
    assert not d.allowed and d.code == "PRECONDITION_FAILED"


def test_cannot_jump_over_build_evidence_to_the_risk_gate():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)
    d = m.check(T.CHECK_DATA_QUALITY)
    assert not d.allowed and d.code == "MANDATORY_STATE_SKIPPED" and "BUILD_EVIDENCE" in d.message


def test_after_evidence_built_analysis_tools_are_closed():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    assert m.check(T.TEST_WEEKDAY_PATTERN).code == "STATE_ALREADY_PASSED"


# --- §26 güvenli hata yolu -----------------------------------------------------------
@pytest.mark.parametrize("gate", ["HARD_BLOCK", "ANALYSIS_UNSAFE"])
def test_unsafe_gate_at_first_quality_check_goes_straight_to_explanation(gate):
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY, ok(gate))
    assert m.state == S.GENERATE_EXPLANATION and m.safe_failure
    ev = m.log.of_kind("SAFE_FAILURE")
    assert len(ev) == 1 and ev[0]["gate_status"] == gate and ev[0]["tool"] == "check_data_quality"
    assert m.pending_mandatory() == []  # kalan zorunlu durumlar bu yolda aranmaz
    assert m.check(T.RANK_SECTOR_RELATIVE_STRENGTH).code == "NO_TOOLS_IN_STATE"


def test_unsafe_gate_at_risk_gate_also_takes_the_safe_failure_path():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY, ok("PASS"))
    call(m, T.TEST_WEEKDAY_PATTERN)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    call(m, T.CHECK_DATA_QUALITY, ok("HARD_BLOCK"))
    assert m.safe_failure and m.state == S.GENERATE_EXPLANATION


@pytest.mark.parametrize("gate", ["PASS", "PASS_WITH_WARNINGS", "INVESTIGATE"])
def test_non_blocking_gates_continue_normally(gate):
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY, ok(gate))
    assert not m.safe_failure and m.state == S.CALCULATE_TECHNICALS


def test_safe_failure_forces_analysis_unsafe_action():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY, ok("HARD_BLOCK"))
    with pytest.raises(HarnessRuleViolation) as exc:
        m.complete_explanation(AllowedAction.WATCH, "metin")
    assert exc.value.code == "ACTION_NOT_ALLOWED_AFTER_SAFE_FAILURE"
    m.complete_explanation(AllowedAction.ANALYSIS_UNSAFE, "metin")
    assert m.state == S.HUMAN_REVIEW


# --- açıklamaya erken geçiş ---------------------------------------------------------
def test_explanation_refused_while_mandatory_states_are_pending():
    m = fresh()
    call(m, T.GET_STOCK_HISTORY)
    d = m.request_explanation()
    assert not d.allowed and d.code == "MANDATORY_STATE_NOT_REACHED"
    assert "CHECK_DATA_QUALITY" in d.message and "RISK_GATE" in d.message
    assert m.log.of_kind("INVALID_TOOL_CALL")[-1]["code"] == "MANDATORY_STATE_NOT_REACHED"


def test_explanation_allowed_after_risk_gate_and_after_safe_failure():
    m = fresh()
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    call(m, T.CHECK_DATA_QUALITY)
    assert m.request_explanation().allowed
    m2 = fresh()
    call(m2, T.CHECK_DATA_QUALITY, ok("ANALYSIS_UNSAFE"))
    assert m2.request_explanation().allowed


# --- geçersiz çağrılar loglanır ------------------------------------------------------
def test_invalid_calls_are_logged_with_state_and_counted():
    m = fresh()
    d = m.check(T.RANK_SECTOR_RELATIVE_STRENGTH)
    m.reject(T.RANK_SECTOR_RELATIVE_STRENGTH, d.code, d.message)
    m.reject("hayali_arac", "UNKNOWN_TOOL", "tanımsız araç")
    assert m.n_invalid_calls == 2
    e = m.log.of_kind("INVALID_TOOL_CALL")
    assert e[0]["tool"] == "rank_sector_relative_strength" and e[0]["state"] == "LOAD_MARKET_DATA"
    assert e[0]["code"] == "MANDATORY_STATE_SKIPPED"
    assert e[1]["tool"] == "hayali_arac" and e[1]["code"] == "UNKNOWN_TOOL"
    assert [x["seq"] for x in m.log.events] == sorted(x["seq"] for x in m.log.events)


def test_commit_refuses_a_call_that_check_would_reject():
    m = fresh()
    with pytest.raises(HarnessRuleViolation):
        m.commit(T.RANK_SECTOR_RELATIVE_STRENGTH, ok())


# --- insan incelemesi ------------------------------------------------------------------
def finish_normal(m: StateMachine) -> None:
    call(m, T.CHECK_DATA_QUALITY)
    call(m, T.TEST_WEEKDAY_PATTERN)
    call(m, T.BUILD_EVIDENCE_BUNDLE)
    call(m, T.CHECK_DATA_QUALITY)
    m.complete_explanation(AllowedAction.WATCH, "açıklama")


def test_review_defaults_to_pending_and_close_never_approves():
    m = fresh()
    finish_normal(m)
    assert m.state == S.HUMAN_REVIEW and m.review_status == ReviewStatus.PENDING_HUMAN_REVIEW
    m.close()
    assert m.state == S.LOG_AND_CLOSE and m.review_status == ReviewStatus.PENDING_HUMAN_REVIEW
    assert m.log.of_kind("SESSION_CLOSED")[0]["review_status"] == "PENDING_HUMAN_REVIEW"


def test_approval_requires_explicit_named_human_with_reason():
    m = fresh()
    finish_normal(m)
    with pytest.raises(HarnessRuleViolation):
        m.record_human_review(ReviewStatus.APPROVED, reviewer="", reason="iyi")
    with pytest.raises(HarnessRuleViolation):
        m.record_human_review(ReviewStatus.APPROVED, reviewer="ayse", reason="  ")
    with pytest.raises(HarnessRuleViolation):
        m.record_human_review(ReviewStatus.PENDING_HUMAN_REVIEW, reviewer="ayse", reason="x")
    m.record_human_review(ReviewStatus.REJECTED, reviewer="ayse", reason="max drawdown çok yüksek")
    assert m.review_status == ReviewStatus.REJECTED


def test_review_only_in_human_review_state():
    m = fresh()
    with pytest.raises(HarnessRuleViolation):
        m.record_human_review(ReviewStatus.APPROVED, reviewer="ayse", reason="x")


def test_closed_session_rejects_everything():
    m = fresh()
    finish_normal(m)
    m.close()
    assert m.check(T.GET_STOCK_HISTORY).code == "SESSION_CLOSED"
