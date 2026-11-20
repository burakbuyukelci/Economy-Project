"""Kanıt paketi (harness tarafı build_evidence_bundle): iki aşama, idempotans, kilit, izlenebilirlik."""
from __future__ import annotations

import copy
import re
from datetime import date

import pytest

from harness import settings
from harness.evidence import EnvelopeStore, EvidenceBundle, make_analysis_id
from harness.mock_tools import is_mock_envelope, run_mock_tool
from schemas.enums import ToolName as T
from schemas.examples import example_params
from schemas.registry import validate_envelope

AS_OF = date(2026, 9, 10)
QUESTION = "Analiz tarihi: 10.09.2026\nPerakende sektöründe geride kalan hisse hangisi?"
AID = make_analysis_id(AS_OF, QUESTION)


def mock_env(tool: T, **over) -> dict:
    return run_mock_tool(tool, {**example_params(tool), **over})


def make_store(*tools: T) -> tuple[EnvelopeStore, dict[T, str]]:
    store, hashes = EnvelopeStore(), {}
    for t in tools:
        rec = store.add(mock_env(t), actor="model")
        hashes[t] = rec.envelope["input_hash"]
    return store, hashes


def bparams(*hashes: str, analysis_id: str = AID) -> dict:
    return {"as_of": AS_OF.isoformat(), "analysis_id": analysis_id, "source_input_hashes": list(hashes)}


ANALYSIS = (T.CHECK_DATA_QUALITY, T.RANK_SECTOR_RELATIVE_STRENGTH, T.DETECT_REVERSAL_EVENTS,
            T.TEST_WEEKDAY_PATTERN, T.CALCULATE_FUNDAMENTAL_CHANGE, T.GET_MACRO_CONTEXT)


# --- analysis_id ---------------------------------------------------------------------------------
def test_analysis_id_is_derived_from_session_not_from_the_bundle_contents():
    assert AID == make_analysis_id(AS_OF, QUESTION)
    assert AID != make_analysis_id(AS_OF, QUESTION + " ?")
    assert AID != make_analysis_id(date(2026, 9, 9), QUESTION)
    assert AID.startswith("2026-09-10-") and len(AID) <= 80


# --- zarf ve sözleşme -------------------------------------------------------------------------------
def test_bundle_envelope_passes_the_contract_and_ids_are_sequential():
    store, h = make_store(*ANALYSIS)
    env = EvidenceBundle(AID, store).build(bparams(*h.values()))
    parsed = validate_envelope(env)
    assert parsed.status.value == "OK" and env["tool"] == "build_evidence_bundle"
    full = env["results"]["full_evidence_set"]
    assert [e["evidence_id"] for e in full] == [f"E{i}" for i in range(1, len(full) + 1)]
    assert len(full) > 6
    committed_ids = {e["evidence_id"] for e in env["results"]["committed_evidence_set"]}
    assert committed_ids and committed_ids <= {e["evidence_id"] for e in full}
    assert env["results"]["analysis_id"] == AID and env["n_events"] == len(full)


# Tanımlayıcılar (2026Q2, RSI_14, BIMAS) sayı değildir: önünde/arkasında harf-rakam-alt çizgi olmayan sayılar
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w])")


def numbers_in(obj) -> set[float]:
    out: set[float] = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= numbers_in(v)
    return out


@pytest.mark.parametrize("tool", [T.RANK_SECTOR_RELATIVE_STRENGTH, T.DETECT_REVERSAL_EVENTS, T.TEST_WEEKDAY_PATTERN,
                                  T.CALCULATE_FUNDAMENTAL_CHANGE, T.GET_FUNDAMENTAL_METRICS, T.GET_MACRO_CONTEXT,
                                  T.RUN_BACKTEST, T.CALCULATE_INDICATORS, T.FIND_SUPPORT_RESISTANCE, T.GET_NEWS_EVENTS])
def test_every_number_in_evidence_comes_from_the_source_tool_output(tool):
    """CLAUDE.md kural 6: kanıttaki hiçbir sayı araç çıktısında olmayan bir sayı olamaz."""
    store, h = make_store(tool)
    env = EvidenceBundle(AID, store).build(bparams(h[tool]))
    source_numbers = numbers_in(store.by_hash(h[tool]).envelope["results"]) | numbers_in(
        store.by_hash(h[tool]).envelope["params"])
    items = env["results"]["full_evidence_set"]
    assert items, f"{tool.value}: kanıt üretilmedi"
    for item in items:
        for v in item["values"]:
            if isinstance(v["value"], (int, float)):
                assert float(v["value"]) in source_numbers, (tool.value, item["evidence_id"], v)
        text = re.sub(r"\d{4}-\d{2}-\d{2}", "", item["statement"])
        for raw in NUM.findall(text):
            assert float(raw) in source_numbers, (tool.value, item["evidence_id"], raw, item["statement"])


def test_loader_tools_and_gate_produce_no_evidence_items_but_are_accepted_as_sources():
    store, h = make_store(T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY, T.CHECK_DATA_QUALITY)
    env = EvidenceBundle(AID, store).build(bparams(*h.values()))
    assert env["results"]["full_evidence_set"] == [] and env["status"] == "OK"
    assert env["results"]["gate_status"] == "PASS_WITH_WARNINGS"  # son check_data_quality'den


# --- idempotans ve iki aşama ---------------------------------------------------------------------------
def test_calling_again_with_the_same_params_is_idempotent():
    store, h = make_store(*ANALYSIS)
    b = EvidenceBundle(AID, store)
    first = b.build(bparams(*h.values()))
    v = b.version
    second = b.build(bparams(*reversed(list(h.values()))))  # sıra önemsiz
    assert first == second and b.version == v


def test_stage_two_adds_backtest_evidence_without_renumbering_stage_one():
    store, h = make_store(*ANALYSIS)
    b = EvidenceBundle(AID, store)
    stage1 = b.build(bparams(*h.values()))
    assert b.version == 1
    bt = store.add(mock_env(T.RUN_BACKTEST), actor="model").envelope["input_hash"]
    stage2 = b.build(bparams(*h.values(), bt))
    assert b.version == 2

    s1, s2 = stage1["results"]["full_evidence_set"], stage2["results"]["full_evidence_set"]
    assert s2[:len(s1)] == s1  # aşama 1 kanıtları aynı id, aynı içerik
    new = s2[len(s1):]
    assert new and all(e["source_tool"] == "run_backtest" and e["source_input_hash"] == bt for e in new)
    assert [e["evidence_id"] for e in new] == [f"E{i}" for i in range(len(s1) + 1, len(s2) + 1)]
    assert any(e["evidence_id"] in {c["evidence_id"] for c in stage2["results"]["committed_evidence_set"]} for e in new)
    assert stage1["input_hash"] != stage2["input_hash"]
    assert stage2["results"]["analysis_id"] == stage1["results"]["analysis_id"] == AID  # id değişmedi


def test_subset_request_after_superset_returns_only_requested_sources_with_stable_ids():
    store, h = make_store(*ANALYSIS)
    b = EvidenceBundle(AID, store)
    full = b.build(bparams(*h.values()))
    sub = b.build(bparams(h[T.RANK_SECTOR_RELATIVE_STRENGTH]))
    sub_items = sub["results"]["full_evidence_set"]
    assert sub_items and all(e["source_tool"] == "rank_sector_relative_strength" for e in sub_items)
    by_id = {e["evidence_id"]: e for e in full["results"]["full_evidence_set"]}
    assert all(by_id[e["evidence_id"]] == e for e in sub_items)


def test_numbering_is_deterministic_across_independent_runs():
    def run():
        store, h = make_store(*ANALYSIS)
        return EvidenceBundle(AID, store).build(bparams(*h.values()))

    assert run() == run()


# --- hatalar -------------------------------------------------------------------------------------------------
def test_unknown_source_hash_and_wrong_analysis_id_are_error_envelopes():
    store, h = make_store(T.RANK_SECTOR_RELATIVE_STRENGTH)
    b = EvidenceBundle(AID, store)
    e1 = b.build(bparams("a" * 64))
    assert e1["status"] == "ERROR" and e1["error"]["code"] == "UNKNOWN_SOURCE_HASH"
    e2 = b.build(bparams(h[T.RANK_SECTOR_RELATIVE_STRENGTH], analysis_id="baska-id"))
    assert e2["status"] == "ERROR" and e2["error"]["code"] == "ANALYSIS_ID_MISMATCH"
    validate_envelope(e1)
    validate_envelope(e2)
    assert b.version == 0  # hatalı çağrılar sürümü artırmaz


def test_a_bundle_cannot_use_another_bundle_as_a_source():
    store, h = make_store(T.RANK_SECTOR_RELATIVE_STRENGTH)
    b = EvidenceBundle(AID, store)
    env = b.build(bparams(h[T.RANK_SECTOR_RELATIVE_STRENGTH]))
    store.add(env, actor="harness")
    again = b.build(bparams(env["input_hash"]))
    assert again["status"] == "ERROR" and again["error"]["code"] == "INVALID_SOURCE_TOOL"


# --- kilit -----------------------------------------------------------------------------------------------------
def test_lock_freezes_the_bundle_and_records_a_deterministic_hash():
    store, h = make_store(*ANALYSIS)
    b = EvidenceBundle(AID, store)
    b.build(bparams(*h.values()))
    lock_hash = b.lock("PASS_WITH_WARNINGS")
    assert b.locked and re.fullmatch(r"[0-9a-f]{64}", lock_hash)
    assert b.snapshot()["lock_hash"] == lock_hash and b.snapshot()["gate_status"] == "PASS_WITH_WARNINGS"

    late = b.build(bparams(*h.values()))
    assert late["status"] == "ERROR" and late["error"]["code"] == "BUNDLE_LOCKED"
    assert b.lock("PASS_WITH_WARNINGS") == lock_hash  # idempotent

    store2, h2 = make_store(*ANALYSIS)
    b2 = EvidenceBundle(AID, store2)
    b2.build(bparams(*h2.values()))
    assert b2.lock("PASS_WITH_WARNINGS") == lock_hash  # aynı girdi -> aynı kilit hash'i


def test_lock_hash_depends_on_the_final_gate_and_the_evidence():
    def locked(tools, gate):
        store, h = make_store(*tools)
        b = EvidenceBundle(AID, store)
        b.build(bparams(*h.values()))
        return b.lock(gate)

    base = locked(ANALYSIS, "PASS")
    assert locked(ANALYSIS, "INVESTIGATE") != base      # aynı kanıt, farklı kapı
    assert locked(ANALYSIS[:3], "PASS") != base         # aynı kapı, farklı kanıt
    assert locked(ANALYSIS, "PASS") == base


@pytest.mark.parametrize("gate,action", [("HARD_BLOCK", "ANALYSIS_UNSAFE"), ("ANALYSIS_UNSAFE", "ANALYSIS_UNSAFE"),
                                          ("INVESTIGATE", "INVESTIGATE"), ("PASS", None), ("PASS_WITH_WARNINGS", None)])
def test_proposed_action_only_reflects_the_gate(gate, action):
    store, h = make_store(T.RANK_SECTOR_RELATIVE_STRENGTH)
    b = EvidenceBundle(AID, store)
    b.build(bparams(*h.values()))
    b.lock(gate)
    assert b.snapshot()["proposed_action"] == action


# --- veri sürümü ve uyarılar ---------------------------------------------------------------------------------------
def test_mock_sources_taint_the_bundle_with_the_mock_data_version():
    store, h = make_store(T.RANK_SECTOR_RELATIVE_STRENGTH)
    env = EvidenceBundle(AID, store).build(bparams(*h.values()))
    assert is_mock_envelope(env) and env["data_version"] == settings.MOCK_DATA_VERSION


def real_looking(tool: T, data_version: str) -> dict:
    env = copy.deepcopy(mock_env(tool))
    env["data_version"] = data_version
    from schemas.hashing import compute_input_hash

    env["input_hash"] = compute_input_hash(tool.value, env["params"], data_version)
    return env


def test_non_mock_sources_keep_their_data_version():
    store = EnvelopeStore()
    rec = store.add(real_looking(T.RANK_SECTOR_RELATIVE_STRENGTH, "snap_2026-11-20_v1"), actor="model")
    env = EvidenceBundle(AID, store).build(bparams(rec.envelope["input_hash"]))
    assert env["data_version"] == "snap_2026-11-20_v1" and not is_mock_envelope(env)
    validate_envelope(env)


def test_differing_data_versions_warn():
    store = EnvelopeStore()
    a = store.add(real_looking(T.RANK_SECTOR_RELATIVE_STRENGTH, "snap_2026-11-20_v1"), actor="model")
    c = store.add(real_looking(T.GET_MACRO_CONTEXT, "snap_2026-11-21_v1"), actor="model")
    env = EvidenceBundle(AID, store).build(bparams(a.envelope["input_hash"], c.envelope["input_hash"]))
    assert any(w.startswith("DATA_VERSION_MISMATCH: ") for w in env["warnings"])
    validate_envelope(env)


def test_source_warnings_propagate_to_the_bundle_deduplicated():
    store, h = make_store(T.RANK_SECTOR_RELATIVE_STRENGTH, T.DETECT_REVERSAL_EVENTS)
    env = EvidenceBundle(AID, store).build(bparams(*h.values()))
    assert env["warnings"].count("HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir.") == 1


# --- gerçek zarflar ---------------------------------------------------------------------------------------------------
def test_real_loader_envelopes_are_accepted_as_sources():
    from tools import get_stock_history

    real = get_stock_history.run(example_params(T.GET_STOCK_HISTORY))
    assert real["status"] == "OK" and not is_mock_envelope(real)
    store = EnvelopeStore()
    rec = store.add(real, actor="model")
    env = EvidenceBundle(AID, store).build(bparams(rec.envelope["input_hash"]))
    assert env["status"] == "OK" and env["data_version"] == real["data_version"]
    validate_envelope(env)
