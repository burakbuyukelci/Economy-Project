"""MCP adaptörü: gerçek MCP istemcisiyle (süreç içi) araç listesi ve çağrılar."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from mcp.client import Client

from harness.mcp_server import build_server
from harness.session import HarnessSession
from schemas.enums import ToolName as T
from schemas.examples import example_params

QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO'da örüntü var mı?"
REPO = Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


def with_client(session, fn):
    async def go():
        async with Client(build_server(session)) as client:
            return await fn(client)

    return run(go())


def test_exposes_exactly_the_15_domain_tools_and_no_state_control_tools():
    session = HarnessSession.from_question(QUESTION)
    result = with_client(session, lambda c: c.list_tools())
    names = {t.name for t in result.tools}
    assert names == {t.value for t in T}
    assert len(names) == 15
    assert not {"advance_state", "get_state"} & names


def test_tool_input_schema_comes_from_pydantic_models_and_requires_as_of():
    session = HarnessSession.from_question(QUESTION)
    tools = {t.name: t for t in with_client(session, lambda c: c.list_tools()).tools}
    schema = tools["get_stock_history"].input_schema
    assert "as_of" in schema["required"] and "ticker" in schema["required"]
    assert "analysis date" in tools["get_stock_history"].description


def test_valid_call_returns_the_envelope_as_json():
    session = HarnessSession.from_question(QUESTION)
    res = with_client(session, lambda c: c.call_tool("check_data_quality", example_params(T.CHECK_DATA_QUALITY)))
    assert not res.is_error
    body = json.loads(res.content[0].text)
    assert body["tool"] == "check_data_quality" and body["status"] == "OK" and body["as_of"] == "2026-09-10"
    assert res.structured_content == body


def test_out_of_state_call_is_an_mcp_error_with_allowed_tools_and_is_logged():
    session = HarnessSession.from_question(QUESTION)
    res = with_client(session, lambda c: c.call_tool("test_weekday_pattern", example_params(T.TEST_WEEKDAY_PATTERN)))
    assert res.is_error
    err = json.loads(res.content[0].text)
    assert err["type"] == "INVALID_TOOL_CALL" and err["code"] == "MANDATORY_STATE_SKIPPED"
    assert "check_data_quality" in err["allowed_tools"]
    assert session.machine.n_invalid_calls == 1


def test_as_of_mismatch_over_mcp_is_invalid():
    session = HarnessSession.from_question(QUESTION)
    params = {**example_params(T.CHECK_DATA_QUALITY), "as_of": "2026-09-11"}
    res = with_client(session, lambda c: c.call_tool("check_data_quality", params))
    assert res.is_error and json.loads(res.content[0].text)["code"] == "AS_OF_MISMATCH"


def test_unknown_tool_name_over_mcp_is_invalid_not_a_crash():
    session = HarnessSession.from_question(QUESTION)
    res = with_client(session, lambda c: c.call_tool("place_order", {"as_of": "2026-09-10"}))
    assert res.is_error and json.loads(res.content[0].text)["code"] == "UNKNOWN_TOOL"


def test_full_weekday_flow_through_mcp_ends_ready_for_explanation():
    session = HarnessSession.from_question(QUESTION)

    async def flow(client):
        for tool in (T.CHECK_DATA_QUALITY, T.TEST_WEEKDAY_PATTERN, T.BUILD_EVIDENCE_BUNDLE, T.CHECK_DATA_QUALITY):
            res = await client.call_tool(tool.value, example_params(tool))
            assert not res.is_error, res.content[0].text

    with_client(session, flow)
    assert session.get_state()["state"] == "GENERATE_EXPLANATION"


def test_stdio_process_starts_and_lists_tools():
    """Gerçek süreç + stdio: `python -m harness.mcp_server` çalışır ve 15 aracı listeler."""
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=sys.executable,
                                   args=["-m", "harness.mcp_server", "--question", QUESTION], cwd=str(REPO))

    async def go():
        async with Client(params) as client:
            tools = await client.list_tools()
            res = await client.call_tool("check_data_quality", example_params(T.CHECK_DATA_QUALITY))
            return len(tools.tools), res.is_error

    n, is_error = run(go())
    assert n == 15 and not is_error
