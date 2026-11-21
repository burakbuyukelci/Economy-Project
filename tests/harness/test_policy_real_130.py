"""Etiket politikası T (teknik dönüş) ve C (catch-up) kurallarının GERÇEK `detect_reversal_events` / `run_backtest` / `rank_sector_relative_strength` zarflarıyla testi.

Vakalar (as_of, hisse) haftalık taramayla (2025-09-05 .. 2026-11-13, tüm evren, RSI_LOCAL_TROUGH + retail catch-up) bulundu; zarflar HER KOŞUDA araçlardan yeniden üretilir
(hash/sayı donmuş değil). Tarama sonucu: gerçek zarflarla T3 (TECHNICAL_REVERSAL_CANDIDATE) oluşuyor; C5 (POTENTIAL_CATCH_UP_CANDIDATE) taramada HİÇ oluşmadı:
catch-up yalnızca C2 (HOLD), C4 (REJECT_SIGNAL), C6 (INVESTIGATE) verdi; C5 yalnızca sentetik zarflarla (test_label_policy.py) sınanır.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.label_policy import decide_label
from schemas.enums import AllowedAction as A, ToolName as T
from schemas.examples import example_params

pytestmark = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists(), reason="data/snapshots yok")
GATE_OK = "PASS_WITH_WARNINGS"


def reversal_case(as_of: str, ticker: str, family: str = "RSI_LOCAL_TROUGH"):
    from tools import detect_reversal_events, run_backtest

    year = as_of[:4]
    rv = detect_reversal_events.run({**example_params(T.DETECT_REVERSAL_EVENTS), "as_of": as_of, "ticker": ticker, "event_family": family,
                                     "split_date": f"{year}-01-01"})
    bp = example_params(T.RUN_BACKTEST)
    bt = run_backtest.run({**bp, "as_of": as_of, "end": as_of, "universe": [ticker],
                           "strategy": {**bp["strategy"], "signal_type": "REVERSAL", "train_end": f"{int(year) - 1}-12-31",
                                        "signal_params": {"event_family": family}}})
    assert rv["status"] == "OK" and bt["status"] == "OK", (rv.get("error"), bt.get("error"))
    return rv, bt


def catch_up_case(as_of: str):
    from tools import rank_sector_relative_strength, run_backtest

    year = as_of[:4]
    rk = rank_sector_relative_strength.run({"sector": "retail", "horizon": 20, "as_of": as_of, "split_date": f"{year}-01-01"})
    bp = example_params(T.RUN_BACKTEST)
    bt = run_backtest.run({**bp, "as_of": as_of, "end": as_of, "universe": ["BIMAS", "MAVI", "MGROS"],
                           "strategy": {**bp["strategy"], "signal_type": "CATCH_UP", "train_end": f"{int(year) - 1}-12-31"}})
    assert rk["status"] == "OK" and bt["status"] == "OK", (rk.get("error"), bt.get("error"))
    return rk, bt


# =============================== teknik dönüş (T0–T6) ===============================
def test_real_reversal_candidate_t3_with_the_real_backtest():
    rv, bt = reversal_case("2025-09-05", "MGROS")
    d = decide_label(gate_status=GATE_OK, envelopes=[rv, bt], question="", subject="MGROS")
    s = d.scenarios[0]
    assert d.label == A.TECHNICAL_REVERSAL_CANDIDATE and s.rule_id == "T3_CANDIDATE" and "CANDIDATE_CAVEAT" in d.reason_codes
    assert s.check("current_signal").ok is True                                           # son olay as_of'a yakın
    assert s.check("passing_horizons").ok is True and bt["results"]["strategy"]["signal_type"] == "REVERSAL"
    g = rv["results"]["groups"][0]
    assert g["n_events_detected"] >= 20 and g["n_raw_event_days"] >= g["n_events_detected"]       # 1.3.0 alanları gerçek zarfta dolu


def test_real_reversal_candidate_is_capped_by_gate_investigate_and_by_advice_intent():
    rv, bt = reversal_case("2025-09-05", "MGROS")
    d = decide_label(gate_status="INVESTIGATE", envelopes=[rv, bt], question="", subject="MGROS")
    assert d.label == A.INVESTIGATE and d.scenarios[0].rule_id == "G3_GATE_INVESTIGATE" and d.scenarios[0].raw_label == A.TECHNICAL_REVERSAL_CANDIDATE
    d = decide_label(gate_status=GATE_OK, envelopes=[rv, bt], question="MGROS alayım mı, hedef fiyat ver", subject="MGROS")
    assert d.label == A.WATCH and d.rule_id == "G6_ADVICE_CAP"


def test_real_reversal_without_the_backtest_cannot_be_a_candidate():
    rv, _ = reversal_case("2025-09-05", "MGROS")
    d = decide_label(gate_status=GATE_OK, envelopes=[rv], question="", subject="MGROS")
    assert d.label == A.INVESTIGATE and d.scenarios[0].rule_id == "T4_VALIDATION_MISSING"


@pytest.mark.parametrize("as_of,ticker,label,rule", [
    ("2025-09-05", "ASELS", A.REJECT_SIGNAL, "T2_REJECT_HISTORY"),
    ("2025-09-05", "TUPRS", A.WATCH, "T5_WATCH"),
])
def test_real_reversal_scan_cases_for_the_other_rules(as_of, ticker, label, rule):
    rv, bt = reversal_case(as_of, ticker)
    d = decide_label(gate_status=GATE_OK, envelopes=[rv, bt], question="", subject=ticker)
    assert d.label == label and d.scenarios[0].rule_id == rule


def test_real_reversal_few_events_is_t1_investigate():
    rv, bt = reversal_case("2026-09-10", "ASELS", "BB_LOWER_TOUCH")            # 12 olay < MIN_EVENTS
    d = decide_label(gate_status=GATE_OK, envelopes=[rv, bt], question="", subject="ASELS")
    assert d.label == A.INVESTIGATE and d.scenarios[0].rule_id == "T1_FEW_EVENTS" and "FEW_EVENTS" in d.reason_codes


# =============================== catch-up (C1–C7) gerçek zarflarla ===============================
@pytest.mark.parametrize("as_of,label,rule", [
    ("2025-10-24", A.HOLD, "C2_NOT_LAGGARD"),
    ("2025-09-05", A.REJECT_SIGNAL, "C4_REJECT_HISTORY"),
    ("2026-01-16", A.INVESTIGATE, "C6_VALIDATION_MISSING"),
])
def test_real_catch_up_scan_cases(as_of, label, rule):
    rk, bt = catch_up_case(as_of)
    d = decide_label(gate_status=GATE_OK, envelopes=[rk, bt], question="")
    assert d.label == label and d.scenarios[0].rule_id == rule
    assert "SUBJECT_EVENT_COUNT" in d.reason_codes                                         # C5S özne sayısı gerekçesi her zaman yazılır


def test_real_catch_up_labels_do_not_change_with_an_unsafe_gate_except_g1():
    rk, bt = catch_up_case("2025-09-05")
    assert decide_label(gate_status="INVESTIGATE", envelopes=[rk, bt], question="").label == A.REJECT_SIGNAL      # G3 yalnızca adayları düşürür
    assert decide_label(gate_status="HARD_BLOCK", envelopes=[rk, bt], question="").label == A.ANALYSIS_UNSAFE
