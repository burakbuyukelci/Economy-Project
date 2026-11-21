"""Mock araçlar: şemaya uyum, determinizm, mock işareti, as_of davranışı, mock/real geçişi."""
from __future__ import annotations

import copy
import types

import pytest

from harness import settings
from harness.mock_tools import (
    MockDataError,
    assert_not_mock,
    is_mock_envelope,
    run_mock_tool,
)
from harness.tool_runner import RealToolUnavailable, run_tool
from schemas.enums import ToolName, ToolStatus
from schemas.examples import example_params
from schemas.hashing import compute_input_hash
from schemas.registry import validate_envelope


@pytest.mark.parametrize("tool", list(ToolName))
def test_every_mock_envelope_passes_contract(tool):
    env = run_mock_tool(tool, example_params(tool))
    parsed = validate_envelope(env)  # şema + as_of çapraz kontrolleri
    assert parsed.status == ToolStatus.OK
    assert env["tool"] == tool.value


@pytest.mark.parametrize("tool", list(ToolName))
def test_mock_input_hash_matches_contract_definition(tool):
    params = example_params(tool)
    env = run_mock_tool(tool, params)
    assert env["input_hash"] == compute_input_hash(tool.value, env["params"], env["data_version"])


def test_mock_is_deterministic():
    p = example_params(ToolName.RANK_SECTOR_RELATIVE_STRENGTH)
    assert run_mock_tool(ToolName.RANK_SECTOR_RELATIVE_STRENGTH, p) == run_mock_tool(
        ToolName.RANK_SECTOR_RELATIVE_STRENGTH, copy.deepcopy(p)
    )


def test_different_params_give_different_hash():
    p1 = example_params(ToolName.GET_STOCK_HISTORY)
    p2 = {**p1, "ticker": "ASELS"}
    h1 = run_mock_tool(ToolName.GET_STOCK_HISTORY, p1)["input_hash"]
    h2 = run_mock_tool(ToolName.GET_STOCK_HISTORY, p2)["input_hash"]
    assert h1 != h2


def test_mock_envelope_is_marked_and_guard_rejects_it():
    env = run_mock_tool(ToolName.CHECK_DATA_QUALITY, example_params(ToolName.CHECK_DATA_QUALITY))
    assert env["data_version"] == settings.MOCK_DATA_VERSION
    assert is_mock_envelope(env)
    with pytest.raises(MockDataError):
        assert_not_mock(env)  # eğitim verisi üretimi bunu çağıracak


def test_non_mock_envelope_passes_guard():
    env = run_mock_tool(ToolName.CHECK_DATA_QUALITY, example_params(ToolName.CHECK_DATA_QUALITY))
    env["data_version"] = "snap_2026-11-20_v1"
    assert not is_mock_envelope(env)
    assert_not_mock(env)


def test_as_of_after_fixture_is_ok_and_echoed():
    p = {**example_params(ToolName.GET_MACRO_CONTEXT), "as_of": "2026-10-01"}
    env = run_mock_tool(ToolName.GET_MACRO_CONTEXT, p)
    assert env["as_of"] == "2026-10-01" and env["params"]["as_of"] == "2026-10-01"
    validate_envelope(env)


def test_as_of_before_fixture_returns_error_envelope_not_leaky_data():
    p = {**example_params(ToolName.GET_MACRO_CONTEXT), "as_of": "2026-06-01", "end": "2026-06-01"}
    env = run_mock_tool(ToolName.GET_MACRO_CONTEXT, p)
    assert env["status"] == "ERROR" and env["results"] is None
    assert env["error"]["code"] == "MOCK_FIXTURE_AFTER_AS_OF"
    validate_envelope(env)  # hata zarfı da sözleşmeye uyar
    assert is_mock_envelope(env)


def test_invalid_params_raise():
    with pytest.raises(Exception):
        run_mock_tool(ToolName.GET_STOCK_HISTORY, {"ticker": "THYAO"})  # as_of yok


# --- mock/real geçişi -------------------------------------------------------
def test_default_backend_is_mock():
    assert settings.backend_for(ToolName.RUN_BACKTEST) == "mock"


def test_run_tool_uses_mock_by_default():
    env = run_tool(ToolName.GET_STOCK_HISTORY, example_params(ToolName.GET_STOCK_HISTORY))
    assert is_mock_envelope(env)


def test_single_setting_switches_one_tool_to_real(monkeypatch):
    calls = []

    def fake_real(params):
        calls.append(params)
        env = run_mock_tool(ToolName.GET_STOCK_HISTORY, params)
        env["data_version"] = "snap_2026-11-20_v1"
        env["input_hash"] = compute_input_hash(env["tool"], env["params"], env["data_version"])
        return env

    fake_module = types.SimpleNamespace(run=fake_real)
    monkeypatch.setitem(settings.TOOL_BACKEND_OVERRIDES, ToolName.GET_STOCK_HISTORY, "real")
    monkeypatch.setattr("harness.tool_runner._import_module", lambda name: fake_module if name == "tools.get_stock_history" else pytest.fail(name))

    p = example_params(ToolName.GET_STOCK_HISTORY)
    env = run_tool(ToolName.GET_STOCK_HISTORY, p)
    assert calls == [p] and not is_mock_envelope(env)
    # diğer araçlar mock kaldı
    assert is_mock_envelope(run_tool(ToolName.GET_INDEX_HISTORY, example_params(ToolName.GET_INDEX_HISTORY)))


def test_real_backend_missing_module_raises_clear_error(monkeypatch):
    monkeypatch.setitem(settings.TOOL_BACKEND_OVERRIDES, ToolName.GET_NEWS_EVENTS, "real")
    with pytest.raises(RealToolUnavailable):
        run_tool(ToolName.GET_NEWS_EVENTS, example_params(ToolName.GET_NEWS_EVENTS))


def test_unknown_backend_value_rejected(monkeypatch):
    monkeypatch.setitem(settings.TOOL_BACKEND_OVERRIDES, ToolName.GET_STOCK_HISTORY, "fake")
    with pytest.raises(ValueError):
        settings.backend_for(ToolName.GET_STOCK_HISTORY)


# --- eğitim verisine uygunluk (CLAUDE.md kural 12: yalnızca v2 ve sonraki üretilmiş sürümler) ------------------
from harness.mock_tools import (  # noqa: E402
    TrainingEligibilityError,
    assert_training_eligible,
    is_training_eligible,
)


def env_with(data_version):
    return {"tool": "get_stock_history", "data_version": data_version}


@pytest.mark.parametrize("version", ["snap_2026-11-20_v2", "snap_2026-11-20_v3", "snap_2026-11-20_v10",
                                     "snap_2027-01-05_v2", "snap_2027-01-05_v1000"])
def test_v2_and_later_generated_versions_are_training_eligible(version):
    assert is_training_eligible(env_with(version))
    assert_training_eligible(env_with(version))


def test_version_numbers_compare_numerically_not_alphabetically():
    assert is_training_eligible(env_with("snap_2026-11-20_v10"))  # "v10" < "v2" alfabetik olurdu


@pytest.mark.parametrize("version", ["snap_2026-11-20_v1", "snap_2027-01-05_v1", "snap_2026-11-20_v0"])
def test_v1_and_below_are_rejected_for_training(version):
    assert not is_training_eligible(env_with(version))
    with pytest.raises(TrainingEligibilityError, match="v2"):
        assert_training_eligible(env_with(version))


def test_mock_is_rejected_for_training_with_the_mock_error():
    mock = run_mock_tool(ToolName.CHECK_DATA_QUALITY, example_params(ToolName.CHECK_DATA_QUALITY))
    assert not is_training_eligible(mock)
    with pytest.raises(MockDataError):
        assert_training_eligible(mock)
    assert issubclass(MockDataError, TrainingEligibilityError)  # tek except ile ikisi de yakalanır


@pytest.mark.parametrize("bad", [None, "", "v2", "snap_2026-11-20", "snap_2026-11-20_v2x", "SNAP_2026-11-20_v2"])
def test_malformed_or_missing_data_version_is_rejected(bad):
    env = env_with(bad)
    assert not is_training_eligible(env)
    with pytest.raises(TrainingEligibilityError):
        assert_training_eligible(env)
    with pytest.raises(TrainingEligibilityError):
        assert_training_eligible({"tool": "x"})  # alan hiç yok


def test_minimum_version_is_a_setting():
    assert settings.MIN_TRAINING_SNAPSHOT_VERSION == 2


def test_a_real_v2_tool_envelope_is_eligible_and_a_v1_one_is_not():
    from tools import get_stock_history

    params = example_params(ToolName.GET_STOCK_HISTORY)
    real_v2 = get_stock_history.run(params)
    assert real_v2["data_version"].endswith("_v2") and is_training_eligible(real_v2)
    real_v1 = get_stock_history.run_on(params, data_version="snap_2026-11-20_v1")
    assert real_v1["data_version"].endswith("_v1") and not is_training_eligible(real_v1)
