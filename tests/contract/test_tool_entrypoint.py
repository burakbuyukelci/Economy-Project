"""Araç giriş noktası sözleşmesi: tools/<tool_name>.py -> run(params: dict) -> dict.

Harness (Bilgisayar 2) araçları bu imzayla çağırır. tools/ altına eklenen her araç modülü (modül adı =
ToolName değeri) otomatik olarak bu testlere girer; imza bozulursa test kırılır.
"""
from __future__ import annotations

import copy
import importlib
import inspect
import json
import typing
from pathlib import Path

import pytest

from config.settings import SNAPSHOT_DIR
from schemas import ToolName, validate_envelope
from schemas.examples import example_params
from tools.common import InvalidToolCall

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
IMPLEMENTED = [t for t in ToolName if (TOOLS_DIR / f"{t.value}.py").exists()]
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")


def load(tool: ToolName):
    return importlib.import_module(f"tools.{tool.value}")


def test_discovery_finds_at_least_the_two_known_tools():
    # Keşif sessizce boş kalıp testleri anlamsızlaştırmasın
    assert {ToolName.GET_STOCK_HISTORY, ToolName.GET_INDEX_HISTORY} <= set(IMPLEMENTED)


@pytest.mark.parametrize("tool", IMPLEMENTED)
def test_module_exposes_run_and_tool_constant(tool):
    mod = load(tool)
    assert callable(getattr(mod, "run", None)), f"tools/{tool.value}.py içinde run() yok"
    assert getattr(mod, "TOOL", None) == tool


@pytest.mark.parametrize("tool", IMPLEMENTED)
def test_run_signature_is_exactly_run_params_dict_returns_dict(tool):
    run = load(tool).run
    sig = inspect.signature(run)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["params"], f"run yalnızca 'params' almalı: {sig}"
    assert params[0].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[0].default is inspect.Parameter.empty
    hints = typing.get_type_hints(run)
    assert hints.get("params") is dict, f"params tipi dict olmalı: {hints}"
    assert hints.get("return") is dict, f"dönüş tipi dict olmalı: {hints}"


@pytest.mark.parametrize("tool", IMPLEMENTED)
def test_run_rejects_extra_arguments(tool):
    """Test enjeksiyon parametreleri (snapshot_root vb.) public run()'a sızmamalı."""
    with pytest.raises(TypeError):
        load(tool).run({}, snapshot_root=None)  # type: ignore[call-arg]


@pytest.mark.parametrize("tool", IMPLEMENTED)
@needs_snapshot
def test_run_returns_valid_json_serializable_envelope_without_mutating_input(tool):
    run = load(tool).run
    params = example_params(tool)
    before = copy.deepcopy(params)
    env = run(params)
    assert type(env) is dict
    assert params == before, "run() girdi sözlüğünü değiştirmemeli"
    json.dumps(env)  # date/Timestamp gibi serileşmeyen nesne kalmamalı
    validated = validate_envelope(env)
    assert validated.tool == tool and env["tool"] == tool.value
    assert env["as_of"] == params["as_of"]


@pytest.mark.parametrize("tool", IMPLEMENTED)
@needs_snapshot
def test_missing_as_of_raises_invalid_tool_call(tool):
    params = example_params(tool)
    params.pop("as_of")
    with pytest.raises(InvalidToolCall):
        load(tool).run(params)


@pytest.mark.parametrize("tool", IMPLEMENTED)
@needs_snapshot
def test_other_invalid_params_return_error_envelope_not_exception(tool):
    params = example_params(tool)
    params["bogus_field"] = 1  # şemada yok -> extra=forbid
    env = load(tool).run(params)
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS" and env["results"] is None
    validate_envelope(env)
