"""Oturum: as_of kilidi, şema doğrulama, durum makinesi + mock araçlar uçtan uca."""
from __future__ import annotations

import copy
from datetime import date

import pytest

from harness.as_of import AsOfError
from harness.mock_tools import is_mock_envelope, run_mock_tool
from harness.routing import ReviewStatus, State as S
from harness.session import HarnessSession
from harness.state_machine import HarnessRuleViolation
from harness.tool_runner import RealToolUnavailable
from schemas.enums import AllowedAction, ToolName as T
from schemas.examples import example_params

QUESTION = "Veri dönemi: 01.01.2024 – 10.09.2026\nAnaliz tarihi: 10.09.2026\n\nPerakende sektöründe ... soru ..."


def new(runner=None) -> HarnessSession:
    return HarnessSession.from_question(QUESTION, runner=runner)


def P(tool: T, **over) -> dict:
    return {**example_params(tool), **over}


def run_catch_up(s: HarnessSession) -> None:
    for tool in (T.CHECK_DATA_QUALITY, T.RANK_SECTOR_RELATIVE_STRENGTH, T.BUILD_EVIDENCE_BUNDLE,
                 T.RUN_BACKTEST, T.CHECK_DATA_QUALITY):
        r = s.call_tool(tool.value, P(tool))
        assert r.ok, r.error


# --- as_of ------------------------------------------------------------------------
def test_session_as_of_comes_from_question_preamble():
    assert new().as_of == date(2026, 9, 10)


def test_question_without_analysis_date_cannot_start_a_session():
    with pytest.raises(AsOfError):
        HarnessSession.from_question("THYAO'da 01.01.2024 – 10.09.2026 arasında ... ?")


def test_matching_as_of_passes_and_mismatch_is_invalid_and_logged():
    s = new()
    assert s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY)).ok
    r = s.call_tool("test_weekday_pattern", P(T.TEST_WEEKDAY_PATTERN, as_of="2026-09-11"))
    assert not r.ok and r.error["code"] == "AS_OF_MISMATCH"
    assert "2026-09-10" in r.error["message"] and "2026-09-11" in r.error["message"]
    assert s.machine.n_invalid_calls == 1
    assert s.machine.state == S.CALCULATE_TECHNICALS  # durum değişmedi


def test_missing_as_of_is_invalid():
    s = new()
    params = P(T.CHECK_DATA_QUALITY)
    del params["as_of"]
    r = s.call_tool("check_data_quality", params)
    assert not r.ok and r.error["code"] == "AS_OF_MISSING"


def test_earlier_as_of_than_session_is_also_a_mismatch():
    r = new().call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY, as_of="2026-09-09"))
    assert r.error["code"] == "AS_OF_MISMATCH"


# --- şema doğrulama ---------------------------------------------------------------
def test_schema_invalid_params_are_invalid_calls():
    s = new()
    r = s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY, ticker="thyao"))
    assert not r.ok and r.error["code"] == "INVALID_PARAMS" and "ticker" in r.error["message"]
    assert s.machine.n_invalid_calls == 1


def test_unknown_tool_is_invalid():
    s = new()
    r = s.call_tool("buy_stock", {"as_of": "2026-09-10"})
    assert not r.ok and r.error["code"] == "UNKNOWN_TOOL"
    assert s.events[-1]["kind"] == "INVALID_TOOL_CALL" and s.events[-1]["tool"] == "buy_stock"


def test_invalid_state_error_lists_currently_callable_tools():
    r = new().call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert r.error["code"] == "MANDATORY_STATE_SKIPPED" and r.error["state"] == "LOAD_MARKET_DATA"
    assert set(r.error["allowed_tools"]) == {"get_stock_history", "get_index_history", "check_data_quality"}


# --- uçtan uca akış --------------------------------------------------------------------
def test_catch_up_flow_end_to_end_with_mock_tools():
    s = new()
    run_catch_up(s)
    assert s.machine.state == S.GENERATE_EXPLANATION
    assert s.request_explanation().allowed
    s.complete_explanation(AllowedAction.POTENTIAL_CATCH_UP_CANDIDATE, "açıklama")
    assert s.get_state()["review_status"] == "PENDING_HUMAN_REVIEW"
    s.close()
    assert s.get_state()["state"] == "LOG_AND_CLOSE"
    assert s.machine.n_invalid_calls == 0
    assert all(is_mock_envelope(e) for e in s.tool_envelopes)  # hepsi mock; eğitim verisine girmemeli


def test_catch_up_flow_cannot_skip_backtest():
    s = new()
    for tool in (T.CHECK_DATA_QUALITY, T.RANK_SECTOR_RELATIVE_STRENGTH, T.BUILD_EVIDENCE_BUNDLE):
        assert s.call_tool(tool.value, P(tool)).ok
    r = s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY))
    assert not r.ok and r.error["code"] == "MANDATORY_STATE_SKIPPED" and "RUN_BACKTEST" in r.error["message"]
    assert not s.request_explanation().allowed


def test_weekday_flow_needs_no_backtest():
    s = new()
    for tool in (T.CHECK_DATA_QUALITY, T.TEST_WEEKDAY_PATTERN, T.BUILD_EVIDENCE_BUNDLE, T.CHECK_DATA_QUALITY):
        assert s.call_tool(tool.value, P(tool)).ok
    assert s.request_explanation().allowed


def test_flow_is_deterministic_same_input_same_log_and_hashes():
    def play() -> tuple[list, list]:
        s = new()
        run_catch_up(s)
        return s.events, [e["input_hash"] for e in s.tool_envelopes]

    assert play() == play()


def test_runner_receives_the_original_params_and_envelope_is_returned_verbatim():
    seen = []

    def runner(tool, params):
        seen.append((tool, copy.deepcopy(params)))
        return run_mock_tool(tool, params)

    s = new(runner)
    params = P(T.CHECK_DATA_QUALITY)
    r = s.call_tool("check_data_quality", params)
    assert seen == [(T.CHECK_DATA_QUALITY, params)]
    assert r.envelope["tool"] == "check_data_quality" and r.envelope["as_of"] == "2026-09-10"


# --- harness hataları (modelin suçu değil) -----------------------------------------------
def test_unavailable_real_tool_is_a_harness_error_not_an_invalid_call():
    def runner(tool, params):
        raise RealToolUnavailable("tools.check_data_quality bulunamadı")

    s = new(runner)
    r = s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY))
    assert not r.ok and r.error["type"] == "HARNESS_ERROR" and r.error["code"] == "TOOL_UNAVAILABLE"
    assert s.machine.n_invalid_calls == 0 and s.machine.state == S.LOAD_MARKET_DATA


def test_contract_violating_tool_output_is_blocked_and_not_committed():
    def runner(tool, params):
        env = run_mock_tool(tool, params)
        env["as_of"] = "2026-09-09"  # zarf as_of'u params.as_of ile uyuşmuyor
        return env

    s = new(runner)
    r = s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY))
    assert not r.ok and r.error["code"] == "TOOL_OUTPUT_INVALID"
    assert s.machine.state == S.LOAD_MARKET_DATA and s.machine.completed >= {S.START}
    assert S.CHECK_DATA_QUALITY not in s.machine.completed


def test_tool_error_envelope_is_returned_to_model_but_does_not_advance():
    def runner(tool, params):
        env = run_mock_tool(tool, params)
        env.update({"results": None, "n_events": None, "status": "ERROR",
                    "error": {"code": "UNKNOWN_TICKER", "message": "Bilinmeyen ticker"}})
        return env

    s = new(runner)
    r = s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY))
    assert r.ok and r.envelope["status"] == "ERROR"  # geçerli bir zarf: model hatayı görür
    assert s.machine.state == S.CHECK_DATA_QUALITY and S.CHECK_DATA_QUALITY not in s.machine.completed
    assert s.machine.n_invalid_calls == 0  # modelin hatası değil


# --- güvenli hata yolu ------------------------------------------------------------------
def hard_block_runner(tool, params):
    env = run_mock_tool(tool, params)
    if tool == T.CHECK_DATA_QUALITY:
        env["results"]["gate_status"] = "HARD_BLOCK"
        env["results"]["hard_blocks"] = [{"code": "AS_OF_VIOLATION", "severity": "HARD", "message": "sızıntı"}]
        env["results"]["soft_warnings"] = []
    return env


def test_hard_block_from_quality_tool_ends_in_explanation_with_analysis_unsafe():
    s = new(hard_block_runner)
    r = s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY))
    assert r.ok and r.envelope["results"]["gate_status"] == "HARD_BLOCK"  # model kapı sonucunu görür
    assert s.get_state()["state"] == "GENERATE_EXPLANATION" and s.get_state()["safe_failure"]
    nxt = s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert not nxt.ok and nxt.error["code"] == "NO_TOOLS_IN_STATE"
    assert s.request_explanation().allowed
    with pytest.raises(HarnessRuleViolation):
        s.complete_explanation(AllowedAction.WATCH, "x")
    s.complete_explanation(AllowedAction.ANALYSIS_UNSAFE, "veri güvenli değil")
    s.close()
    assert [e["kind"] for e in s.events if e["kind"] == "SAFE_FAILURE"] == ["SAFE_FAILURE"]


# --- insan incelemesi --------------------------------------------------------------------
def test_live_test_session_ends_with_pending_human_review_never_approved():
    s = new()
    run_catch_up(s)
    s.complete_explanation(AllowedAction.WATCH, "x")
    s.close()
    assert s.get_state()["review_status"] == ReviewStatus.PENDING_HUMAN_REVIEW.value


def test_get_state_is_a_read_only_copy():
    s = new()
    st = s.get_state()
    st["state"] = "LOG_AND_CLOSE"
    st["completed"].append("X")
    assert s.get_state()["state"] == "LOAD_MARKET_DATA" and "X" not in s.get_state()["completed"]
    assert s.get_state()["as_of"] == "2026-09-10"


# --- as_of kaynağı ve AS_OF_ASSUMED -------------------------------------------------------
NO_MARKER = "THYAO'da 01.01.2024 – 10.09.2026 döneminde örüntü var mı?"


def test_marker_in_question_has_no_assumption_warning():
    s = new()
    assert s.as_of_source == "question" and s.warnings == []
    assert not [e for e in s.events if e["kind"] == "AS_OF_ASSUMED"]


def test_default_as_of_is_used_with_a_harness_level_warning_and_event():
    s = HarnessSession.from_question(NO_MARKER, default_as_of=date(2026, 9, 10))
    assert s.as_of == date(2026, 9, 10) and s.as_of_source == "default"
    assert len(s.warnings) == 1 and s.warnings[0].startswith("AS_OF_ASSUMED: ") and "2026-09-10" in s.warnings[0]
    ev = [e for e in s.events if e["kind"] == "AS_OF_ASSUMED"]
    assert len(ev) == 1 and ev[0]["as_of"] == "2026-09-10"
    assert s.get_state()["warnings"] == s.warnings


def test_explicit_as_of_from_eval_set_is_not_an_assumption():
    s = HarnessSession.from_question(NO_MARKER, explicit_as_of=date(2026, 9, 10))
    assert s.as_of_source == "explicit" and s.warnings == []


def test_settings_default_is_read_from_environment(monkeypatch):
    from harness import settings

    monkeypatch.setenv(settings.DEFAULT_AS_OF_ENV, "2026-09-10")
    s = HarnessSession.from_question(NO_MARKER)
    assert s.as_of_source == "default" and s.as_of == date(2026, 9, 10)


def test_no_marker_and_no_default_still_errors(monkeypatch):
    from harness import settings

    monkeypatch.delenv(settings.DEFAULT_AS_OF_ENV, raising=False)
    with pytest.raises(AsOfError):
        HarnessSession.from_question(NO_MARKER)
