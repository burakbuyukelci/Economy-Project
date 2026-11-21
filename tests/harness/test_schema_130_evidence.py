"""Şema 1.3.0 alanları kanıtta: SR mesafeleri, reversal ham olay günü / çakışan pencere, backtest son çıkış tarihi ve işlem özeti.

GERÇEK v2 araç zarflarıyla (as_of 2026-09-10); beklenen değerler zarftan okunur (donmuş sayı/hash yok).
"""
from __future__ import annotations

from datetime import date

import pytest

from harness.evidence import EnvelopeStore, EvidenceBundle, headline_spec, is_headline, make_analysis_id
from harness.number_verifier import verify_numbers
from schemas.enums import ToolName as T
from schemas.examples import example_params

AS_OF = "2026-09-10"
QUESTION = "Analiz tarihi: 10.09.2026\nASELS ve THYAO için durum nedir?"


@pytest.fixture(scope="module")
def real_130():
    from pathlib import Path

    if not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import detect_reversal_events, find_support_resistance, run_backtest

    sr = find_support_resistance.run({**example_params(T.FIND_SUPPORT_RESISTANCE), "ticker": "THYAO"})
    rv = detect_reversal_events.run({**example_params(T.DETECT_REVERSAL_EVENTS), "ticker": "ASELS", "split_date": "2026-01-01"})
    p = example_params(T.RUN_BACKTEST)
    bt = run_backtest.run({**p, "universe": ["ASELS"], "strategy": {**p["strategy"], "signal_type": "REVERSAL", "train_end": "2025-12-31",
                                                                 "signal_params": {"event_family": "BB_LOWER_TOUCH"}}})
    for e in (sr, rv, bt):
        assert e["status"] == "OK", e.get("error")
    return {"sr": sr, "rv": rv, "bt": bt}


def committed(env):
    store = EnvelopeStore()
    store.add(env, actor="model")
    aid = make_analysis_id(date(2026, 9, 10), QUESTION)
    b = EvidenceBundle(aid, store)
    b.build({"as_of": AS_OF, "analysis_id": aid, "source_input_hashes": [env["input_hash"]]})
    b.lock("PASS")
    return [i for i in b.snapshot()["committed_evidence_set"] if i["source_input_hash"] == env["input_hash"]]


def value_of(item, name):
    return next((v["value"] for v in item["values"] if v["name"] == name), None)


# =============================== spec ===============================
def test_spec_version_and_sections_for_the_three_tools():
    import json
    from pathlib import Path

    raw = json.loads((Path(__file__).resolve().parents[2] / "harness" / "evidence_headlines.json").read_text(encoding="utf-8"))
    assert raw["version"] == 4
    spec = headline_spec()
    assert "levels" in spec["find_support_resistance"]["headline"] and not spec["find_support_resistance"]["context"]
    assert "trades" in spec["run_backtest"]["headline"]
    assert is_headline(T.FIND_SUPPORT_RESISTANCE, "levels") and is_headline(T.RUN_BACKTEST, "trades")


# =============================== destek/direnç mesafeleri ===============================
def test_real_sr_distances_are_committed_numbers_copied_from_the_tool(real_130):
    env = real_130["sr"]
    res = env["results"]
    (item,) = committed(env)
    for name in ("last_close", "nearest_support", "nearest_resistance", "nearest_support_distance_pct", "nearest_resistance_distance_pct"):
        assert value_of(item, name) == res[name], name
    assert str(res["nearest_support_distance_pct"]) in item["statement"] and str(res["nearest_resistance_distance_pct"]) in item["statement"]
    assert verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026").n_hallucinated == 0


def test_sr_without_a_level_has_no_distance_in_the_statement():
    from harness.evidence import EXTRACTORS
    from schemas.examples import example_envelope

    res = example_envelope(T.FIND_SUPPORT_RESISTANCE)["results"]
    res.update(nearest_support=None, nearest_support_distance_pct=None)
    (c,) = EXTRACTORS[T.FIND_SUPPORT_RESISTANCE](res)
    assert "destek mesafesi" not in c.statement and all(v["name"] != "nearest_support_distance_pct" for v in c.values)


# =============================== reversal: ham olay günü ve çakışan pencere ===============================
def test_real_reversal_group_count_carries_raw_event_days_and_overlapping_windows(real_130):
    env = real_130["rv"]
    g = env["results"]["groups"][0]
    items = [i for i in committed(env) if value_of(i, "n_raw_event_days") is not None]
    assert len(items) == 1
    item = items[0]
    assert value_of(item, "n_raw_event_days") == g["n_raw_event_days"]
    assert value_of(item, "n_overlapping_forward_windows") == g["n_overlapping_forward_windows"]
    assert value_of(item, "n_events_detected") == g["n_events_detected"]
    assert g["n_raw_event_days"] >= g["n_events_detected"] and g["n_overlapping_forward_windows"] <= g["n_events_detected"] - 1   # araç kuralı
    assert verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026").n_hallucinated == 0


def test_a_1_2_0_reversal_group_without_the_new_fields_still_extracts():
    from harness.evidence import EXTRACTORS
    from schemas.examples import example_envelope

    res = example_envelope(T.DETECT_REVERSAL_EVENTS)["results"]
    for g in res["groups"]:
        g["n_raw_event_days"] = g["n_overlapping_forward_windows"] = None
    cands = [c for c in EXTRACTORS[T.DETECT_REVERSAL_EVENTS](res) if c.section == "group_count"]
    assert cands and all("ham olay günü" not in c.statement for c in cands)


# =============================== backtest: son çıkış, işlem özeti ===============================
def test_real_backtest_trade_summary_is_committed(real_130):
    env = real_130["bt"]
    res = env["results"]
    items = [i for i in committed(env) if value_of(i, "last_exit_date") is not None]
    assert len(items) == 1
    item = items[0]
    assert value_of(item, "last_exit_date") == res["last_exit_date"]
    assert value_of(item, "n_winning_trades") == res["n_winning_trades"] and value_of(item, "n_losing_trades") == res["n_losing_trades"]
    assert value_of(item, "signal_lag_days_applied") == res["signal_lag_days_applied"]
    assert res["last_exit_date"] in item["statement"] and res["last_exit_date"] <= AS_OF
    assert verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026").n_hallucinated == 0


def test_backtest_without_trades_has_no_last_exit_date_item():
    from harness.evidence import EXTRACTORS
    from schemas.examples import example_envelope

    res = example_envelope(T.RUN_BACKTEST)["results"]
    res.update(last_exit_date=None, n_winning_trades=0, n_losing_trades=0)
    cands = [c for c in EXTRACTORS[T.RUN_BACKTEST](res) if c.section == "trades"]
    assert len(cands) == 1 and all(v["name"] != "last_exit_date" for v in cands[0].values)


@pytest.mark.parametrize("key", ["sr", "rv", "bt"])
def test_all_committed_statements_of_real_130_envelopes_are_verified(real_130, key):
    env = real_130[key]
    for item in committed(env):
        rep = verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026")
        assert rep.n_hallucinated == 0, (item["statement"], [r.claim.raw for r in rep.claims if r.verdict == "HALLUCINATION"])
