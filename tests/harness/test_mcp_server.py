"""MCP adaptörü: gerçek MCP istemcisiyle (süreç içi) araç listesi ve çağrılar."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp.client import Client

from harness.mcp_server import build_server
import dataclasses

from harness.profiles import PROFILES
from harness.session import HarnessSession
from schemas.enums import ToolName as T
from schemas.examples import example_params

QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO'da örüntü var mı?"
REPO = Path(__file__).resolve().parents[2]
MANUAL = dataclasses.replace(PROFILES["D"], name="D-manual", auto_gates=False)


def run(coro):
    return asyncio.run(coro)


def with_client(session, fn):
    async def go():
        async with Client(build_server(session)) as client:
            return await fn(client)

    return run(go())


def test_exposes_exactly_the_15_domain_tools_and_no_state_control_tools():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    result = with_client(session, lambda c: c.list_tools())
    names = {t.name for t in result.tools}
    assert names == {t.value for t in T}
    assert len(names) == 15
    assert not {"advance_state", "get_state"} & names


def test_tool_input_schema_comes_from_pydantic_models_and_requires_as_of():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    tools = {t.name: t for t in with_client(session, lambda c: c.list_tools()).tools}
    schema = tools["get_stock_history"].input_schema
    assert "as_of" in schema["required"] and "ticker" in schema["required"]
    assert "analysis date" in tools["get_stock_history"].description


def test_valid_call_returns_the_envelope_as_json():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    res = with_client(session, lambda c: c.call_tool("check_data_quality", example_params(T.CHECK_DATA_QUALITY)))
    assert not res.is_error
    body = json.loads(res.content[0].text)
    assert body["tool"] == "check_data_quality" and body["status"] == "OK" and body["as_of"] == "2026-09-10"
    assert res.structured_content == body


def test_out_of_state_call_is_an_mcp_error_with_allowed_tools_and_is_logged():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    res = with_client(session, lambda c: c.call_tool("test_weekday_pattern", example_params(T.TEST_WEEKDAY_PATTERN)))
    assert res.is_error
    err = json.loads(res.content[0].text)
    assert err["type"] == "INVALID_TOOL_CALL" and err["code"] == "MANDATORY_STATE_SKIPPED"
    assert "check_data_quality" in err["allowed_tools"]
    assert session.machine.n_invalid_calls == 1


def test_as_of_mismatch_over_mcp_is_invalid():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    params = {**example_params(T.CHECK_DATA_QUALITY), "as_of": "2026-09-11"}
    res = with_client(session, lambda c: c.call_tool("check_data_quality", params))
    assert res.is_error and json.loads(res.content[0].text)["code"] == "AS_OF_MISMATCH"


def test_unknown_tool_name_over_mcp_is_invalid_not_a_crash():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    res = with_client(session, lambda c: c.call_tool("place_order", {"as_of": "2026-09-10"}))
    assert res.is_error and json.loads(res.content[0].text)["code"] == "UNKNOWN_TOOL"


def test_full_weekday_flow_through_mcp_ends_ready_for_explanation():
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)

    async def flow(client):
        for tool in (T.CHECK_DATA_QUALITY, T.TEST_WEEKDAY_PATTERN, T.BUILD_EVIDENCE_BUNDLE, T.CHECK_DATA_QUALITY):
            params = example_params(tool)
            if tool == T.BUILD_EVIDENCE_BUNDLE:  # manuel akışta model oturumun analysis_id'sini ve hash'lerini kullanır
                params = {"as_of": "2026-09-10", "analysis_id": session.analysis_id,
                          "source_input_hashes": [r.envelope["input_hash"] for r in session.store.records
                                                  if r.envelope["status"] == "OK"]}
            res = await client.call_tool(tool.value, params)
            assert not res.is_error, res.content[0].text

    with_client(session, flow)
    assert session.get_state()["state"] == "GENERATE_EXPLANATION"


def test_stdio_process_starts_and_lists_the_13_model_tools_by_default():
    """Gerçek süreç + stdio: varsayılan aşama D -> kapı araçları harness'in, model 13 araç görür."""
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "harness.mcp_server", "--question", QUESTION], cwd=str(REPO))

    async def go():
        async with Client(params) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            res = await client.call_tool("get_stock_history", example_params(T.GET_STOCK_HISTORY))
            gate = await client.call_tool("check_data_quality", example_params(T.CHECK_DATA_QUALITY))
            return names, res.is_error, gate.is_error, json.loads(gate.content[0].text)["code"]

    names, call_error, gate_error, gate_code = run(go())
    assert len(names) == 13 and "check_data_quality" not in names and "build_evidence_bundle" not in names
    assert not call_error and gate_error and gate_code == "HARNESS_ONLY_TOOL"


# --- komut satırı: as_of seçenekleri --------------------------------------------------------
from datetime import date  # noqa: E402

from harness.as_of import AsOfError  # noqa: E402
from harness.mcp_server import session_from_args  # noqa: E402

NO_MARKER = "THYAO'da örüntü var mı?"


def test_cli_explicit_as_of():
    s = session_from_args(["--question", NO_MARKER, "--as-of", "2026-09-10"])
    assert s.as_of == date(2026, 9, 10) and s.as_of_source == "explicit"


def test_cli_default_as_of_marks_assumption():
    s = session_from_args(["--question", NO_MARKER, "--default-as-of", "10.09.2026"])
    assert s.as_of_source == "default" and s.warnings[0].startswith("AS_OF_ASSUMED")


def test_cli_without_any_date_fails(monkeypatch):
    from harness import settings

    monkeypatch.delenv(settings.DEFAULT_AS_OF_ENV, raising=False)
    with pytest.raises(AsOfError):
        session_from_args(["--question", NO_MARKER])


# --- D profili (varsayılan): model 13 araç görür, kapıları harness çalıştırır ---------------------------
def test_stage_d_lists_13_tools_and_runs_the_gates_for_the_model():
    session = HarnessSession.from_question("Analiz tarihi: 10.09.2026\nPerakende (BIMAS, MGROS, MAVI) geride kalan?",
                                           profile="D")
    names = {t.name for t in with_client(session, lambda c: c.list_tools()).tools}
    assert len(names) == 13 and not {"check_data_quality", "build_evidence_bundle"} & names

    async def flow(client):
        for tool in (T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST):
            res = await client.call_tool(tool.value, example_params(tool))
            assert not res.is_error, res.content[0].text

    with_client(session, flow)
    assert session.request_explanation().allowed
    assert session.get_state()["evidence"]["locked"] and session.machine.n_invalid_calls == 0


def test_safe_failure_over_mcp_is_an_error_result_with_the_required_action():
    from harness.mock_tools import run_mock_tool

    def runner(tool, params):
        env = run_mock_tool(tool, params)
        if tool == T.CHECK_DATA_QUALITY:
            env["results"].update({"gate_status": "HARD_BLOCK", "soft_warnings": [], "issue_counts": {"AS_OF_VIOLATION": 1},
                                   "hard_blocks": [{"code": "AS_OF_VIOLATION", "severity": "HARD", "message": "x"}]})
        return env

    session = HarnessSession.from_question("Analiz tarihi: 10.09.2026\nTHYAO?", profile="D", runner=runner)
    res = with_client(session, lambda c: c.call_tool("test_weekday_pattern", example_params(T.TEST_WEEKDAY_PATTERN)))
    body = json.loads(res.content[0].text)
    assert res.is_error and body["type"] == "SAFE_FAILURE" and body["required_action"] == "ANALYSIS_UNSAFE"


def test_oos_rule_is_part_of_the_descriptions_of_the_validation_tools_only():
    """Karar: split_date her zaman as_of yılının başı ya da sorudaki OOS başlangıcı (label_policy OOS ister)."""
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    tools = {t.name: t for t in with_client(session, lambda c: c.list_tools()).tools}
    for name in ("rank_sector_relative_strength", "detect_reversal_events", "test_weekday_pattern", "run_backtest"):
        d = tools[name].description
        assert "January 1 of the as_of year" in d and "out-of-sample start stated in the question" in d, name
    assert "split_date" in tools["rank_sector_relative_strength"].description
    assert "strategy.train_end" in tools["run_backtest"].description
    for name in ("get_stock_history", "calculate_indicators", "get_macro_context"):
        assert "January 1" not in tools[name].description


def test_calculate_indicators_schema_exposes_the_1_2_0_light_defaults():
    """Şema 1.2.0: model yeni param'ları şemadan görür; varsayılanlar hafiftir (last_n_rows=0, kolon meta kapalı)."""
    session = HarnessSession.from_question(QUESTION, profile=MANUAL)
    tools = {t.name: t for t in with_client(session, lambda c: c.list_tools()).tools}
    props = tools["calculate_indicators"].input_schema["properties"]
    assert props["include_columns_meta"]["default"] is False and props["last_n_rows"]["default"] == 0
    assert "value_columns" in props
