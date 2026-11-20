"""Aşama profilleri (A–E), otomatik kapı yönlendirmesi, strict/lenient sıra modu."""
from __future__ import annotations

import dataclasses

import pytest

from harness import settings
from harness.event_log import EventLog
from harness.profiles import PROFILES, StageProfile, get_profile, routing_for, visible_tools
from harness.routing import State as S
from harness.state_machine import HarnessRuleViolation, StateMachine
from schemas.enums import ToolName as T

OK = {"status": "OK", "results": {}}


def machine(stage="D", **kw) -> StateMachine:
    m = StateMachine(EventLog(), routing_for(get_profile(stage)), **kw)
    m.begin()
    return m


def commit(m, tool, gate=None):
    m.commit(tool, {"status": "OK", "results": {"gate_status": gate} if gate else {}})


# --- profil tablosu (kararlaştırılan A–E) -----------------------------------------------------
@pytest.mark.parametrize("name,flags", [
    ("A", (False, False, False, False, False)),
    ("B", (True, False, False, False, False)),
    ("C", (True, True, False, False, False)),
    ("D", (True, True, True, True, False)),
    ("E", (True, True, True, True, True)),
])
def test_profile_table(name, flags):
    p = PROFILES[name]
    assert (p.tools_enabled, p.enforce_states, p.auto_gates, p.evidence, p.human_review) == flags


def test_unknown_stage_and_inconsistent_profiles_are_rejected():
    with pytest.raises(ValueError):
        get_profile("Z")
    with pytest.raises(ValueError):
        StageProfile("x", tools_enabled=True, enforce_states=False, auto_gates=True, evidence=True, human_review=False)
    with pytest.raises(ValueError):
        StageProfile("x", tools_enabled=False, enforce_states=True, auto_gates=False, evidence=False, human_review=False)


def test_settings_stage_and_mode_can_come_from_environment(monkeypatch):
    assert settings.experiment_stage() == "D" and settings.state_order_mode() == "strict"
    monkeypatch.setenv(settings.EXPERIMENT_STAGE_ENV, "c")
    monkeypatch.setenv(settings.STATE_ORDER_MODE_ENV, "Lenient")
    assert settings.experiment_stage() == "C" and settings.state_order_mode() == "lenient"
    monkeypatch.setenv(settings.STATE_ORDER_MODE_ENV, "gevşek")
    with pytest.raises(ValueError):
        settings.state_order_mode()


def test_visible_tools_per_stage():
    assert visible_tools(PROFILES["A"]) == []
    all_tools = set(T)
    assert set(visible_tools(PROFILES["B"])) == all_tools - {T.BUILD_EVIDENCE_BUNDLE}
    assert set(visible_tools(PROFILES["C"])) == all_tools - {T.BUILD_EVIDENCE_BUNDLE}
    for stage in ("D", "E"):
        assert set(visible_tools(PROFILES[stage])) == all_tools - {T.BUILD_EVIDENCE_BUNDLE, T.CHECK_DATA_QUALITY}
        assert len(visible_tools(PROFILES[stage])) == 13
    manual_with_evidence = dataclasses.replace(PROFILES["D"], auto_gates=False)
    assert set(visible_tools(manual_with_evidence)) == all_tools


# --- D/E: kapılar harness'in -------------------------------------------------------------------------
def test_first_analysis_call_requires_the_quality_gate_to_run_before_it():
    m = machine("D")
    d = m.check(T.RANK_SECTOR_RELATIVE_STRENGTH)
    assert d.allowed and d.target == S.RUN_SECTOR_RELATIVE_ANALYSIS and d.auto_before == (S.CHECK_DATA_QUALITY,)


def test_commit_refuses_while_harness_steps_are_pending():
    m = machine("D")
    with pytest.raises(HarnessRuleViolation) as exc:
        m.commit(T.RANK_SECTOR_RELATIVE_STRENGTH, OK)
    assert exc.value.code == "AUTO_STEP_PENDING"


def test_after_the_gate_ran_the_model_call_has_no_pending_steps():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)  # harness adımı
    assert m.state == S.CALCULATE_TECHNICALS
    d = m.check(T.RANK_SECTOR_RELATIVE_STRENGTH)
    assert d.allowed and d.auto_before == ()


def test_backtest_call_triggers_stage_one_evidence_first():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    d = m.check(T.RUN_BACKTEST)
    assert d.allowed and d.auto_before == (S.BUILD_EVIDENCE,)
    commit(m, T.BUILD_EVIDENCE_BUNDLE)  # harness aşama 1
    assert m.state == S.PREVIEW_STRATEGIES
    assert m.check(T.RUN_BACKTEST).auto_before == ()


def test_model_backtest_without_any_analysis_is_a_precondition_failure():
    m = machine("D")
    d = m.check(T.RUN_BACKTEST)
    assert not d.allowed and d.code == "PRECONDITION_FAILED"


def test_explanation_in_d_lists_the_steps_harness_must_run():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.TEST_WEEKDAY_PATTERN)
    d = m.request_explanation()
    assert d.allowed and d.auto_before == (S.BUILD_EVIDENCE, S.RISK_GATE)


def test_explanation_in_d_needs_the_model_to_run_the_mandatory_backtest():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    d = m.request_explanation()
    assert not d.allowed and d.code == "MANDATORY_STATE_NOT_REACHED" and "RUN_BACKTEST" in d.message
    assert "RISK_GATE" not in d.message  # harness'in işi modelden istenmez


def test_explanation_without_any_analysis_is_refused():
    m = machine("D")
    d = m.request_explanation()
    assert not d.allowed and d.code == "PRECONDITION_FAILED"


def test_stage_two_evidence_then_final_gate_run_inside_risk_gate_and_lead_to_explanation():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    commit(m, T.BUILD_EVIDENCE_BUNDLE)
    commit(m, T.RUN_BACKTEST)
    commit(m, T.BUILD_EVIDENCE_BUNDLE)  # aşama 2 (RISK_GATE'te)
    assert m.state == S.RISK_GATE and S.RISK_GATE not in m.completed
    commit(m, T.CHECK_DATA_QUALITY)     # son kapı
    assert m.state == S.GENERATE_EXPLANATION and m.pending_mandatory() == []


def test_unsafe_gate_still_takes_the_safe_failure_path_in_d():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY, gate="HARD_BLOCK")
    assert m.safe_failure and m.state == S.GENERATE_EXPLANATION


# --- C: kapı/kanıt yok, kalite + backtest zorunlu (modelin çağrısı) -------------------------------------
def test_stage_c_has_no_auto_steps_and_only_quality_is_always_mandatory():
    m = machine("C")
    assert m.routing.auto_states == frozenset()
    assert m.mandatory_states() == {S.CHECK_DATA_QUALITY}
    assert not m.check(T.TEST_WEEKDAY_PATTERN).allowed  # kalite kontrolü hâlâ atlanamaz


def test_stage_c_explanation_needs_no_evidence_or_final_gate():
    m = machine("C")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.TEST_WEEKDAY_PATTERN)
    d = m.request_explanation()
    assert d.allowed and d.auto_before == ()
    m.begin_explanation()
    assert m.state == S.GENERATE_EXPLANATION


def test_stage_c_does_not_apply_the_safe_failure_path():
    m = machine("C")
    commit(m, T.CHECK_DATA_QUALITY, gate="HARD_BLOCK")
    assert not m.safe_failure and m.state == S.CALCULATE_TECHNICALS


def test_stage_c_keeps_the_derived_backtest_requirement():
    m = machine("C")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    assert not m.request_explanation().allowed
    commit(m, T.RUN_BACKTEST)
    assert m.request_explanation().allowed


def test_begin_explanation_refuses_while_steps_are_pending():
    m = machine("D")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.TEST_WEEKDAY_PATTERN)
    with pytest.raises(HarnessRuleViolation) as exc:
        m.begin_explanation()
    assert exc.value.code == "AUTO_STEP_PENDING"


# --- enforce=False (A/B): sıra ve zorunluluk denetlenmez --------------------------------------------------
def test_unenforced_machine_allows_any_order_but_still_records_successful_calls():
    m = machine("B", enforce=False)
    d = m.check(T.RANK_SECTOR_RELATIVE_STRENGTH)
    assert d.allowed and d.auto_before == ()
    commit(m, T.RANK_SECTOR_RELATIVE_STRENGTH)
    assert m.state == S.LOAD_MARKET_DATA and m.ok_calls
    assert m.request_explanation().allowed


# --- strict / lenient sıra modu ---------------------------------------------------------------------------------------
def to_calculate_technicals(mode):
    m = machine("C", order_mode=mode)
    commit(m, T.CHECK_DATA_QUALITY)
    return m


def test_strict_rejects_going_back_and_logs_an_order_violation():
    m = to_calculate_technicals("strict")
    d = m.check(T.GET_STOCK_HISTORY)
    assert not d.allowed and d.code == "STATE_ALREADY_PASSED" and d.order_violation
    m.reject(T.GET_STOCK_HISTORY, d.code, d.message)
    assert m.n_invalid_calls == 1 and m.n_order_violations == 1
    ev = m.log.of_kind("ORDER_VIOLATION")
    assert len(ev) == 1 and ev[0]["enforced"] is True and ev[0]["mode"] == "strict"


def test_lenient_allows_going_back_logs_the_violation_and_does_not_move_the_state():
    m = to_calculate_technicals("lenient")
    d = m.check(T.GET_STOCK_HISTORY)
    assert d.allowed and d.order_violation and d.target == S.LOAD_MARKET_DATA
    commit(m, T.GET_STOCK_HISTORY)
    assert m.state == S.CALCULATE_TECHNICALS               # geri gitmedi
    assert m.n_invalid_calls == 0 and m.n_order_violations == 1
    ev = m.log.of_kind("ORDER_VIOLATION")
    assert len(ev) == 1 and ev[0]["enforced"] is False and ev[0]["mode"] == "lenient"
    assert (T.GET_STOCK_HISTORY, S.LOAD_MARKET_DATA) in m.ok_calls


def test_lenient_still_enforces_mandatory_states():
    m = machine("C", order_mode="lenient")
    d = m.check(T.TEST_WEEKDAY_PATTERN)  # kalite kontrolü atlanamaz
    assert not d.allowed and d.code == "MANDATORY_STATE_SKIPPED"


def test_lenient_backward_call_does_not_trigger_auto_advance_or_transition():
    m = machine("C", order_mode="lenient")
    commit(m, T.CHECK_DATA_QUALITY)
    commit(m, T.TEST_WEEKDAY_PATTERN)
    state_before = m.state
    commit(m, T.CALCULATE_INDICATORS)  # CALCULATE_TECHNICALS geçildi: geriye çağrı
    assert m.state == state_before


@pytest.mark.parametrize("mode", ["strict", "lenient"])
def test_both_modes_log_order_violations(mode):
    m = to_calculate_technicals(mode)
    d = m.check(T.GET_INDEX_HISTORY)
    if d.allowed:
        commit(m, T.GET_INDEX_HISTORY)
    else:
        m.reject(T.GET_INDEX_HISTORY, d.code, d.message)
    assert len(m.log.of_kind("ORDER_VIOLATION")) == 1 and m.n_order_violations == 1


def test_invalid_order_mode_rejected():
    with pytest.raises(ValueError):
        StateMachine(order_mode="gevsek")


def test_snapshot_reports_counters_and_mode():
    m = to_calculate_technicals("lenient")
    snap = m.snapshot()
    assert snap["order_mode"] == "lenient" and snap["n_order_violations"] == 0
