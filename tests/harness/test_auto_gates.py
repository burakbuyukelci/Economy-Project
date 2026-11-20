"""D/E profili: kapıları HARNESS çalıştırır. Uçtan uca oturum testleri (mock araçlar)."""
from __future__ import annotations

import pytest

from harness.evidence import make_analysis_id
from harness.mock_tools import is_mock_envelope, run_mock_tool
from harness.routing import State as S
from harness.session import HarnessSession
from harness.state_machine import HarnessRuleViolation
from schemas.enums import AllowedAction, ToolName as T
from schemas.examples import example_params
from schemas.registry import validate_envelope

QUESTION = ("Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) son 20 işlem gününde "
            "sektör medyanının en çok gerisinde kalan hisse hangisi?")
NO_TICKER_QUESTION = "Analiz tarihi: 10.09.2026\nMakro ortam nasıl?"


def P(tool: T, **over) -> dict:
    return {**example_params(tool), **over}


def new(question=QUESTION, stage="D", **kw) -> HarnessSession:
    return HarnessSession.from_question(question, profile=stage, **kw)


def kinds(s, kind, **match):
    return [e for e in s.events if e["kind"] == kind and all(e.get(k) == v for k, v in match.items())]


def calls(s):
    """(actor, araç) sırası."""
    return [(e["actor"], e["tool"]) for e in s.events if e["kind"] == "TOOL_CALL"]


def catch_up(s: HarnessSession):
    assert s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH)).ok
    assert s.call_tool("run_backtest", P(T.RUN_BACKTEST)).ok


# --- model kapıyı çağırmaz; harness doğru sırada çalıştırır ----------------------------------------
def test_catch_up_flow_the_model_only_calls_domain_tools():
    s = new()
    catch_up(s)
    d = s.request_explanation()
    assert d.allowed and s.machine.state == S.GENERATE_EXPLANATION
    assert calls(s) == [
        ("harness", "check_data_quality"),            # modelin ilk analiz çağrısından ÖNCE
        ("model", "rank_sector_relative_strength"),
        ("harness", "build_evidence_bundle"),         # aşama 1: backtest çağrısından ÖNCE
        ("model", "run_backtest"),
        ("harness", "build_evidence_bundle"),         # aşama 2: RISK_GATE
        ("harness", "check_data_quality"),            # son kapı
    ]
    assert s.machine.n_invalid_calls == 0
    assert [e["tool"] for e in s.tool_envelopes] == ["rank_sector_relative_strength", "run_backtest"]  # model yalnızca kendi zarflarını görür
    assert [r.actor for r in s.store.records] == ["harness", "model", "harness", "model", "harness", "harness"]


def test_model_calling_a_gate_tool_is_invalid_and_counted():
    s = new()
    for name in ("check_data_quality", "build_evidence_bundle"):
        r = s.call_tool(name, P(T(name)))
        assert not r.ok and r.error["code"] == "HARNESS_ONLY_TOOL"
    assert s.machine.n_invalid_calls == 2 and s.store.records == []
    assert len(s.visible_tools) == 13


def test_gate_tickers_and_window_are_derived_from_the_models_call():
    s = new()
    s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    gate = s.store.records[0].envelope
    assert gate["tool"] == "check_data_quality"
    assert gate["params"]["tickers"] == ["BIMAS", "MAVI", "MGROS"]  # sector=retail -> peer grubu
    assert (gate["params"]["start"], gate["params"]["end"], gate["params"]["as_of"]) == ("2024-01-01", "2026-09-10", "2026-09-10")
    assert gate["params"]["analysis_bundle"] == []  # ilk kapıda henüz analiz çıktısı yok


def test_final_gate_receives_the_analysis_bundle_of_everything_that_ran():
    s = new()
    catch_up(s)
    s.request_explanation()
    final_gate = [r.envelope for r in s.store.records if r.tool == T.CHECK_DATA_QUALITY][-1]
    assert [i["tool"] for i in final_gate["params"]["analysis_bundle"]] == ["rank_sector_relative_strength", "run_backtest"]


# --- kanıt: iki aşama, sabit analysis_id, kilit -------------------------------------------------------------
def test_two_stage_evidence_keeps_the_analysis_id_and_ids_and_locks_at_the_risk_gate():
    s = new()
    catch_up(s)
    assert s.get_state()["evidence"]["locked"] is False
    s.request_explanation()
    beb = [r.envelope for r in s.store.records if r.tool == T.BUILD_EVIDENCE_BUNDLE]
    assert len(beb) == 2
    aid = make_analysis_id(s.as_of, QUESTION)
    assert aid == s.analysis_id and all(e["results"]["analysis_id"] == aid for e in beb)
    s1, s2 = beb[0]["results"]["full_evidence_set"], beb[1]["results"]["full_evidence_set"]
    assert s1 and len(s2) > len(s1) and s2[:len(s1)] == s1
    assert all(e["source_tool"] == "run_backtest" for e in s2[len(s1):])
    assert not any(e["source_tool"] == "run_backtest" for e in s1)  # aşama 1'de backtest kanıtı YOK

    ev = s.get_state()["evidence"]
    assert ev["locked"] and ev["version"] == 2 and ev["lock_hash"] and ev["n_committed"] > 0
    assert ev["gate_status"] == "PASS_WITH_WARNINGS"
    locked_event = kinds(s, "EVIDENCE_LOCKED")
    assert len(locked_event) == 1 and locked_event[0]["lock_hash"] == ev["lock_hash"]



def test_locked_bundle_rejects_further_builds():
    s = new()
    catch_up(s)
    s.request_explanation()
    some_hash = s.store.records[1].envelope["input_hash"]
    late = s.bundle.build({"as_of": "2026-09-10", "analysis_id": s.analysis_id, "source_input_hashes": [some_hash]})
    assert late["status"] == "ERROR" and late["error"]["code"] == "BUNDLE_LOCKED"


def test_evidence_snapshot_exposes_the_committed_set_with_traceable_hashes():
    s = new()
    catch_up(s)
    s.request_explanation()
    snap = s.evidence_snapshot()
    hashes = {r.envelope["input_hash"] for r in s.store.records}
    assert snap["committed_evidence_set"] and all(e["source_input_hash"] in hashes for e in snap["committed_evidence_set"])
    for env in (r.envelope for r in s.store.records):
        validate_envelope(env)  # harness'in çalıştırdığı zarflar da sözleşmeye uyar


def test_mock_sources_taint_the_bundle():
    s = new()
    catch_up(s)
    s.request_explanation()
    bundle_envs = [r.envelope for r in s.store.records if r.tool == T.BUILD_EVIDENCE_BUNDLE]
    assert all(is_mock_envelope(e) for e in bundle_envs)


# --- zorunlu adımlar ------------------------------------------------------------------------------------------------
def test_explanation_is_refused_until_the_model_ran_the_derived_mandatory_backtest():
    s = new()
    s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    d = s.request_explanation()
    assert not d.allowed and d.code == "MANDATORY_STATE_NOT_REACHED" and "RUN_BACKTEST" in d.message
    assert s.machine.state != S.GENERATE_EXPLANATION and not s.get_state()["evidence"]["locked"]
    s.call_tool("run_backtest", P(T.RUN_BACKTEST))
    assert s.request_explanation().allowed


def test_weekday_flow_needs_no_backtest_and_harness_finishes_the_gates():
    s = new("Analiz tarihi: 10.09.2026\nTHYAO'da örüntü var mı?")
    assert s.call_tool("test_weekday_pattern", P(T.TEST_WEEKDAY_PATTERN)).ok
    assert s.request_explanation().allowed
    assert calls(s) == [("harness", "check_data_quality"), ("model", "test_weekday_pattern"),
                        ("harness", "build_evidence_bundle"), ("harness", "build_evidence_bundle"),
                        ("harness", "check_data_quality")]
    assert s.get_state()["evidence"]["locked"] and s.machine.n_invalid_calls == 0


def test_explanation_with_no_analysis_is_refused_and_runs_no_gates():
    s = new()
    d = s.request_explanation()
    assert not d.allowed and d.code == "PRECONDITION_FAILED" and s.store.records == []


def test_backtest_before_any_analysis_is_invalid():
    s = new()
    r = s.call_tool("run_backtest", P(T.RUN_BACKTEST))
    assert not r.ok and r.error["code"] == "PRECONDITION_FAILED" and s.store.records == []


# --- ticker belirlenemezse -----------------------------------------------------------------------------------------------
def test_ticker_undetermined_returns_to_the_model_and_runs_nothing():
    s = new(NO_TICKER_QUESTION)
    r = s.call_tool("get_macro_context", P(T.GET_MACRO_CONTEXT))
    assert not r.ok and r.error["type"] == "INVALID_TOOL_CALL" and r.error["code"] == "TICKER_UNDETERMINED"
    assert s.machine.n_invalid_calls == 1 and s.store.records == [] and s.machine.state == S.LOAD_MARKET_DATA
    # model bir ticker içeren aracı çağırınca kapı çalışır
    assert s.call_tool("get_news_events", P(T.GET_NEWS_EVENTS)).ok
    assert s.store.records[0].envelope["params"]["tickers"] == ["EREGL"]


def test_question_tickers_are_the_fallback_for_tickerless_calls():
    s = new("Analiz tarihi: 10.09.2026\nEREGL kesin yükselir mi? Dolar/TL yükseliyor.")
    assert kinds(s, "UNIVERSE_SELECTED")[0]["tickers_in_question"] == ["EREGL"]
    assert s.call_tool("get_macro_context", P(T.GET_MACRO_CONTEXT)).ok
    assert s.store.records[0].envelope["params"]["tickers"] == ["EREGL"]


# --- güvenli hata yolu --------------------------------------------------------------------------------------------------------
def gate_runner(blocking_calls: set[int], status: str = "HARD_BLOCK"):
    """N'inci check_data_quality çağrısı (1'den) engelleyici sonuç döndürür."""
    count = {"n": 0}
    executed: list[T] = []

    def runner(tool, params):
        executed.append(tool)
        env = run_mock_tool(tool, params)
        if tool == T.CHECK_DATA_QUALITY:
            count["n"] += 1
            if count["n"] in blocking_calls:
                env["results"]["gate_status"] = status
                if status == "HARD_BLOCK":
                    env["results"]["hard_blocks"] = [{"code": "AS_OF_VIOLATION", "severity": "HARD", "message": "sızıntı"}]
                    env["results"]["soft_warnings"] = []
        return env

    runner.executed = executed  # type: ignore[attr-defined]
    return runner


def test_hard_block_at_the_first_gate_skips_the_models_tool_and_locks_an_unsafe_bundle():
    runner = gate_runner({1})
    s = new(runner=runner)
    r = s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert not r.ok and r.error["type"] == "SAFE_FAILURE" and r.error["gate_status"] == "HARD_BLOCK"
    assert r.error["required_action"] == "ANALYSIS_UNSAFE"
    assert runner.executed == [T.CHECK_DATA_QUALITY]                      # modelin aracı HİÇ çalışmadı
    assert s.machine.n_invalid_calls == 0 and s.machine.safe_failure and s.machine.state == S.GENERATE_EXPLANATION
    ev = s.get_state()["evidence"]
    assert ev["locked"] and ev["gate_status"] == "HARD_BLOCK" and ev["proposed_action"] == "ANALYSIS_UNSAFE"
    assert len(kinds(s, "SAFE_FAILURE")) == 1

    assert s.request_explanation().allowed
    with pytest.raises(HarnessRuleViolation):
        s.complete_explanation(AllowedAction.WATCH, "x")
    s.complete_explanation(AllowedAction.ANALYSIS_UNSAFE, "veri güvenli değil")
    s.close()
    assert s.get_state()["review_status"] == "PENDING_HUMAN_REVIEW"


def test_analysis_unsafe_gate_takes_the_same_path():
    s = new(runner=gate_runner({1}, status="ANALYSIS_UNSAFE"))
    r = s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert r.error["type"] == "SAFE_FAILURE" and r.error["gate_status"] == "ANALYSIS_UNSAFE"


def test_hard_block_at_the_final_gate_ends_in_explanation_with_a_locked_unsafe_bundle():
    s = new(runner=gate_runner({2}))
    catch_up(s)
    d = s.request_explanation()
    assert d.allowed and s.machine.safe_failure and s.machine.state == S.GENERATE_EXPLANATION
    ev = s.get_state()["evidence"]
    assert ev["locked"] and ev["gate_status"] == "HARD_BLOCK" and ev["version"] == 2


def test_after_a_safe_failure_no_more_tools_run():
    s = new(runner=gate_runner({1}))
    s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    r = s.call_tool("test_weekday_pattern", P(T.TEST_WEEKDAY_PATTERN))
    assert not r.ok and r.error["code"] == "NO_TOOLS_IN_STATE"


def test_failed_gate_tool_is_a_harness_error_and_the_models_call_does_not_run():
    executed = []

    def runner(tool, params):
        executed.append(tool)
        env = run_mock_tool(tool, params)
        if tool == T.CHECK_DATA_QUALITY:
            env.update({"results": None, "n_events": None, "status": "ERROR",
                        "error": {"code": "UNKNOWN_TICKER", "message": "Bilinmeyen ticker"}})
        return env

    s = new(runner=runner)
    r = s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert not r.ok and r.error["type"] == "HARNESS_ERROR" and r.error["code"] == "AUTO_STEP_FAILED"
    assert executed == [T.CHECK_DATA_QUALITY] and s.machine.n_invalid_calls == 0
    assert S.CHECK_DATA_QUALITY not in s.machine.completed


# --- determinizm ---------------------------------------------------------------------------------------------------------------
def test_d_flow_is_deterministic_events_and_lock_hash():
    def play():
        s = new()
        catch_up(s)
        s.request_explanation()
        return s.events, s.get_state()["evidence"]["lock_hash"]

    assert play() == play()


# --- aşamalar ------------------------------------------------------------------------------------------------------------------
def test_stage_c_model_calls_the_quality_gate_itself_and_has_no_evidence():
    s = new(stage="C")
    assert s.evidence_snapshot() is None and T.BUILD_EVIDENCE_BUNDLE not in s.visible_tools
    assert s.call_tool("build_evidence_bundle", P(T.BUILD_EVIDENCE_BUNDLE)).error["code"] == "TOOL_NOT_EXPOSED"
    assert not s.call_tool("test_weekday_pattern", P(T.TEST_WEEKDAY_PATTERN)).ok  # önce kalite kontrolü
    assert s.call_tool("check_data_quality", P(T.CHECK_DATA_QUALITY)).ok
    assert s.call_tool("test_weekday_pattern", P(T.TEST_WEEKDAY_PATTERN)).ok
    assert s.request_explanation().allowed and s.machine.state == S.GENERATE_EXPLANATION
    assert calls(s) == [("model", "check_data_quality"), ("model", "test_weekday_pattern")]


def test_stage_a_exposes_no_tools():
    s = new(stage="A")
    assert s.visible_tools == []
    r = s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY))
    assert not r.ok and r.error["code"] == "TOOL_NOT_EXPOSED"


def test_stage_b_has_no_order_or_mandatory_steps_but_still_locks_as_of_and_schema():
    s = new(stage="B")
    assert s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH)).ok  # kalite kontrolü YOK
    assert s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY)).ok                          # sıra serbest
    assert s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY, as_of="2026-09-11")).error["code"] == "AS_OF_MISMATCH"
    assert s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY, ticker="thyao")).error["code"] == "INVALID_PARAMS"
    assert s.request_explanation().allowed
    assert s.machine.n_invalid_calls == 2


# --- strict / lenient (oturum düzeyi) --------------------------------------------------------------------------------------------
def test_strict_session_rejects_a_step_back_and_logs_the_order_violation():
    s = new(order_mode="strict")
    s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    r = s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY))
    assert not r.ok and r.error["code"] == "STATE_ALREADY_PASSED"
    assert s.machine.n_invalid_calls == 1 and s.machine.n_order_violations == 1
    assert kinds(s, "ORDER_VIOLATION")[0]["enforced"] is True


def test_lenient_session_runs_the_step_back_and_logs_it():
    s = new(order_mode="lenient")
    s.call_tool("rank_sector_relative_strength", P(T.RANK_SECTOR_RELATIVE_STRENGTH))
    r = s.call_tool("get_stock_history", P(T.GET_STOCK_HISTORY))
    assert r.ok and s.machine.state == S.RUN_SECTOR_RELATIVE_ANALYSIS
    assert s.machine.n_invalid_calls == 0 and s.machine.n_order_violations == 1
    assert kinds(s, "ORDER_VIOLATION")[0]["enforced"] is False


def test_order_mode_and_stage_come_from_settings_by_default(monkeypatch):
    from harness import settings

    monkeypatch.setenv(settings.EXPERIMENT_STAGE_ENV, "C")
    monkeypatch.setenv(settings.STATE_ORDER_MODE_ENV, "lenient")
    s = HarnessSession.from_question(QUESTION)
    assert s.profile.name == "C" and s.machine.order_mode == "lenient"
    assert kinds(s, "SESSION_START")[0]["stage"] == "C"
