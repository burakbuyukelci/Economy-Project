"""Gerçek araçlar (tools/): giriş noktası sözleşmesi, InvalidToolCall -> geçersiz çağrı, gerçek zarfla uçtan uca."""
from __future__ import annotations

import pytest

from harness import settings
from harness.mock_tools import is_mock_envelope
import dataclasses

from harness.profiles import PROFILES
from harness.routing import State as S
from harness.session import HarnessSession
from harness.tool_runner import ToolRejected, run_tool
from schemas.enums import ToolName as T
from schemas.examples import example_params
from schemas.registry import validate_envelope
from tools.common import InvalidToolCall

QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO son günlerde nasıl?"


MANUAL = dataclasses.replace(PROFILES["D"], name="D-manual", auto_gates=False)


@pytest.fixture
def real_stock_history(monkeypatch):
    monkeypatch.setitem(settings.TOOL_BACKEND_OVERRIDES, T.GET_STOCK_HISTORY, "real")


def bad_as_of_params(value):
    p = dict(example_params(T.GET_STOCK_HISTORY))
    p["as_of"] = value
    return p


# --- run_tool: InvalidToolCall -> ToolRejected ---------------------------------------------
@pytest.mark.parametrize("bad", ["bozuk", None, "2026-13-45"])
def test_real_tool_raising_invalid_tool_call_becomes_tool_rejected(real_stock_history, bad):
    with pytest.raises(ToolRejected) as exc:
        run_tool(T.GET_STOCK_HISTORY, bad_as_of_params(bad))
    assert exc.value.code == "AS_OF_INVALID" and "as_of" in exc.value.message
    assert isinstance(exc.value.__cause__, InvalidToolCall)


def test_other_param_errors_come_back_as_error_envelopes_not_exceptions(real_stock_history):
    p = {**example_params(T.GET_STOCK_HISTORY), "ticker": "thyao"}  # şemaya aykırı ama as_of sağlam
    env = run_tool(T.GET_STOCK_HISTORY, p)
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


def test_unknown_ticker_is_an_error_envelope(real_stock_history):
    p = {**example_params(T.GET_STOCK_HISTORY), "ticker": "ZZZZZ"}
    env = run_tool(T.GET_STOCK_HISTORY, p)
    assert env["status"] == "ERROR" and env["error"]["code"] == "UNKNOWN_TICKER"


# --- oturum: ToolRejected geçersiz çağrı olarak loglanır -----------------------------------------
def test_session_logs_tool_rejection_as_invalid_call_and_does_not_advance():
    def runner(tool, params):
        raise ToolRejected("AS_OF_INVALID", "get_stock_history: as_of eksik veya geçersiz ('x')")

    s = HarnessSession.from_question(QUESTION, runner=runner, profile=MANUAL)
    r = s.call_tool("get_stock_history", example_params(T.GET_STOCK_HISTORY))
    assert not r.ok and r.error["type"] == "INVALID_TOOL_CALL" and r.error["code"] == "AS_OF_INVALID"
    assert s.machine.n_invalid_calls == 1 and s.machine.state == S.LOAD_MARKET_DATA
    last = [e for e in s.events if e["kind"] == "INVALID_TOOL_CALL"][-1]
    assert last["tool"] == "get_stock_history" and last["code"] == "AS_OF_INVALID"


# --- gerçek zarfla uçtan uca ------------------------------------------------------------------------
def test_real_get_stock_history_through_the_session_is_a_real_non_mock_envelope(real_stock_history):
    s = HarnessSession.from_question(QUESTION, profile=MANUAL)
    r = s.call_tool("get_stock_history", example_params(T.GET_STOCK_HISTORY))
    assert r.ok, r.error
    env = r.envelope
    validate_envelope(env)
    assert not is_mock_envelope(env) and env["data_version"].startswith("snap_2026-")
    assert env["as_of"] == "2026-09-10"
    # as_of sonrası satır yok (look-ahead): son tarih <= 2026-09-10
    assert max(row["date"] for row in env["results"]["rows"]) <= "2026-09-10"
    assert s.tool_envelopes == [env]
