"""experiments/sample_runs.py: beş örnek sorunun araç zinciri gerçek veriyle: doğru araçlar, sızıntı yok, sayı doğrulama, tekrarlanabilirlik, makro eksikliği."""
from __future__ import annotations

from pathlib import Path

import pytest

from experiments import sample_runs as SR

ROOT = Path(__file__).resolve().parents[2]
needs_data = pytest.mark.skipif(not (ROOT / "data" / "snapshots" / "LATEST").exists() or not (ROOT / "data" / "snapshots" / "LATEST_FUNDAMENTALS").exists(),
                                reason="gerçek snapshot/bilanço veri seti yok")


@pytest.fixture(scope="module")
def runs():
    return {r["id"]: r for r in SR.run_all()}


def _tools(r):
    return [c["tool"] for c in r["tool_calls"] if c["actor"] == "model"]


def test_question_definitions_use_the_exam_questions_and_analysis_date():
    text = (ROOT / "docs" / "ornek_test_sorulari.txt").read_text(encoding="utf-8")
    for q in SR.QUESTIONS:
        assert q["text"].split("\n", 1)[1] in text, q["id"]
        assert all(p["as_of"] == "2026-09-10" for _, p in q["calls"])


@needs_data
def test_all_five_sessions_deliver_with_no_hallucination_no_leak_and_are_reproducible(runs):
    assert list(runs) == [q["id"] for q in SR.QUESTIONS]
    for r in runs.values():
        c = r["checks"]
        assert r["session_status"] == "DELIVERED" and r["final_status"] == "ACCEPTED", r["id"]
        assert c["n_hallucinated"] == 0 and c["n_unevidenced"] == 0 and c["invalid_tool_calls"] == 0, r["id"]
        assert c["any_result_after_as_of"] is False and c["reproducible"] is True, r["id"]
        assert all(call["max_result_date"] is None or call["max_result_date"] <= "2026-09-10" for call in r["tool_calls"])
        assert r["final_text"].rstrip().splitlines()[-1].startswith("EYLEM: ")


@needs_data
def test_expected_tool_chains(runs):
    assert _tools(runs["q1_retail_catch_up"]) == ["rank_sector_relative_strength", "run_backtest"]
    assert _tools(runs["q2_thyao_weekday"]) == ["test_weekday_pattern"]
    assert _tools(runs["q3_asels_bollinger"]) == ["calculate_indicators", "detect_reversal_events", "run_backtest"]
    assert _tools(runs["q4_tuprs_fundamental"]) == ["get_fundamental_metrics", "calculate_fundamental_change"]
    assert _tools(runs["q5_eregl_safety_macro"]) == ["get_macro_context"]


@needs_data
def test_q3_reports_the_known_asels_numbers_and_excludes_nothing_wrongly(runs):
    rev = next(c for c in runs["q3_asels_bollinger"]["tool_calls"] if c["tool"] == "detect_reversal_events")
    g = rev["key_figures"]["groups"]
    assert [x["label"] for x in g][0] == "single_indicator" and g[0]["n_events_detected"] == 12 and g[0]["n_raw_event_days"] == 17
    assert len(g) == 3 and rev["key_figures"]["n_tests_declared"] == 3


@needs_data
def test_q4_uses_disclosure_dates_and_never_prices_after_as_of(runs):
    r = runs["q4_tuprs_fundamental"]
    ch = next(c for c in r["tool_calls"] if c["tool"] == "calculate_fundamental_change")
    kf = ch["key_figures"]
    assert all(q["disclosure_date"] <= "2026-09-10" for q in kf["quarters"]) and "2026Q3" not in [q["fiscal_period"] for q in kf["quarters"]]
    assert all(x["window_end_date"] is None or x["window_end_date"] <= "2026-09-10" for q in kf["quarters"] for x in q["reactions"])
    assert "nedensellik iddia edilmez" in r["final_text"] and r["policy"]["rule_id"] in ("F1_INSUFFICIENT", "F2_REJECT", "F3_CANDIDATE", "F4_WATCH")
    assert any("YAHOO_APPROX" in w for w in ch["warnings"]) or any(q for q in kf["quarters"])


@needs_data
def test_q5_gives_no_advice_refutes_the_certainty_claim_and_shows_the_fx_stock_relation(runs):
    r = runs["q5_eregl_safety_macro"]
    t = r["final_text"]
    assert "hedef fiyat veremem" in t and "doğrulanmamıştır" in t and r["policy"]["label"] in ("INVESTIGATE", "WATCH")
    macro = next(c for c in r["tool_calls"] if c["tool"] == "get_macro_context")
    assert macro["status"] == "OK"
    if not (ROOT / "data" / "snapshots" / "LATEST_MACRO").exists():
        assert any(w.startswith("MACRO_DATA_MISSING") for w in macro["warnings"]) and macro["key_figures"]["series_returned"] == []
        assert "Makro veri" in t and "verilemez" in t
    else:
        kf = macro["key_figures"]
        assert set(kf["series_returned"]) == {"USDTRY", "TCMB_FUNDING_COST"} and [x["lag_days"] for x in kf["relations"]] == [0, 5]
        assert all(x["n_obs"] > 100 and x["out_of_sample_n_obs"] is not None for x in kf["relations"]) and kf["multiple_testing"]["n_tests_declared"] == 2
        assert "politika faizi değil" in t and "korelasyon" in t and "nedensellik iddia edilmez" in t and r["policy"]["label"] == "INVESTIGATE"
        assert all(str(x["correlation"]) in t for x in kf["relations"])      # ilişki sayıları açıklamada araç çıktısından AYNEN


@needs_data
def test_main_writes_json_and_readme_deterministically(tmp_path):
    assert SR.main(["--out", str(tmp_path / "a")]) == 0
    assert SR.main(["--out", str(tmp_path / "b")]) == 0
    a = sorted(p.name for p in (tmp_path / "a").iterdir())
    assert a == sorted(["README.md"] + [f"{q['id']}.json" for q in SR.QUESTIONS])
    for name in a:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
