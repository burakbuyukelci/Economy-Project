"""Modele giden zarf görünümü (harness/model_view.py): boş (null) alanlar atılır, rank'te per_ticker yalnızca ÖZNE satırı tam, ranking sıkıştırılır,
kırpma işareti konur. Kanıt, politika ve sayı doğrulayıcı TAM zarfla çalışır (oturum deposu değişmez).
"""
from __future__ import annotations

import copy
import json

import pytest

from harness.model_view import model_view
from policy_builders import rank_env
from schemas.enums import ToolName as T


def size(x):
    return len(json.dumps(x, ensure_ascii=False, sort_keys=True))


# =============================== genel: null atma ===============================
def test_none_values_are_dropped_recursively_and_other_values_are_untouched():
    env = {"tool": "x", "status": "OK", "results": {"a": None, "b": [1, {"c": None, "d": 0}], "e": False, "f": ""}, "n_events": None, "warnings": []}
    v = model_view(env, subject=None)
    assert v["results"] == {"b": [1, {"d": 0}], "e": False, "f": ""} and "n_events" not in v and v["warnings"] == []


def test_the_echo_of_the_models_own_call_and_identifiers_are_dropped_but_provenance_stays():
    env = {"tool": "x", "params": {"ticker": "THYAO"}, "as_of": "2026-09-10", "schema_version": "1.3.0", "input_hash": "a" * 64,
           "data_version": "snap_2026-11-20_v2", "status": "OK", "results": {"k": 1}, "n_events": 3, "n_excluded_incomplete_horizon": 0,
           "warnings": ["W: x"]}
    v = model_view(env, subject=None)
    assert set(v) == {"data_version", "status", "results", "n_events", "n_excluded_incomplete_horizon", "warnings"}


def test_the_input_envelope_is_never_mutated():
    env = rank_env()
    snap = copy.deepcopy(env)
    model_view(env, subject="MAVI")
    assert env == snap


def test_a_generic_envelope_without_lossy_trimming_has_no_trim_marker():
    env = {"tool": "get_stock_history", "status": "OK", "results": {"rows": [{"close": 1.0, "volume": None}]}}
    assert "view_trimmed" not in model_view(env, subject=None)


def test_error_envelopes_pass_through_with_only_nulls_dropped():
    env = {"tool": "x", "status": "ERROR", "results": None, "error": {"code": "NO_DATA", "message": "m"}}
    v = model_view(env, subject=None)
    assert v["error"] == {"code": "NO_DATA", "message": "m"} and v["status"] == "ERROR"


# =============================== rank: per_ticker ve ranking ===============================
def test_rank_per_ticker_keeps_the_subject_row_in_full_and_summarises_the_others():
    env = rank_env(subject="MAVI")
    full = {t["ticker"]: t for t in env["results"]["per_ticker"]}
    v = model_view(env, subject="MAVI")
    rows = {t["ticker"]: t for t in v["results"]["per_ticker"]}
    assert set(rows) == set(full)
    assert "per_horizon" in rows["MAVI"] and rows["MAVI"]["n_independent_events"] == full["MAVI"]["n_independent_events"]
    for t in set(full) - {"MAVI"}:
        assert set(rows[t]) == {"ticker", "is_laggard", "lag_score_pp", "n_raw_laggard_observations", "n_independent_events",
                                "n_excluded_incomplete_horizon"}, t
        assert rows[t]["n_independent_events"] == full[t]["n_independent_events"]                    # özet sayılar korunur
    assert "per_ticker" in v["view_trimmed"]


def test_rank_ranking_is_compressed_but_keeps_the_numbers_the_answer_needs():
    env = rank_env(subject="MAVI")
    v = model_view(env, subject="MAVI")
    full = {r["ticker"]: r for r in env["results"]["ranking"]}
    for r in v["results"]["ranking"]:
        assert set(r) <= {"rank", "ticker", "return_pct", "lag_score_pp", "is_laggard"} and "return_vs_xu100_pp" not in r
        assert r["return_pct"] == full[r["ticker"]]["return_pct"] and r["lag_score_pp"] == full[r["ticker"]]["lag_score_pp"]
    assert "ranking" in v["view_trimmed"]


def test_subject_defaults_to_the_most_lagging_stock_when_none_is_given():
    env = rank_env(subject="MAVI")                                    # MAVI: lag -8.0, diğerleri >= 0
    v = model_view(env, subject=None)
    rows = {t["ticker"]: t for t in v["results"]["per_ticker"]}
    assert "per_horizon" in rows["MAVI"] and all("per_horizon" not in rows[t] for t in rows if t != "MAVI")


def test_pooled_blocks_keep_the_committed_numbers_and_drop_only_the_fields_evidence_never_quotes():
    env = rank_env(subject="MAVI")
    v = model_view(env, subject="MAVI")
    for key in ("n_raw_laggard_observations", "cooldown_days", "outcome_benchmark_definition", "sector_strength"):
        assert v["results"][key] == _strip(env["results"][key]), key
    keep = ("n_events_complete", "n_excluded_incomplete_horizon", "n_success", "n_false_positive", "hit_rate_pct", "mean_return_pct", "cost_adjusted_mean_return_pct")
    for shown, full in zip(v["results"]["historical_catch_up"], env["results"]["historical_catch_up"]):
        sb, fb = shown["block"], full["block"]
        assert sb["horizon"] == fb["horizon"] and sb["oos_degradation_flag"] == fb["oos_degradation_flag"]      # politika-kritik bayrak kalır
        assert sb["baseline"] == {"hit_rate_pct": fb["baseline"]["hit_rate_pct"]}
        for part, kk in (("full", keep), ("in_sample", ("n_events_complete", "hit_rate_pct", "cost_adjusted_mean_return_pct")),
                         ("out_of_sample", ("n_events_complete", "hit_rate_pct", "cost_adjusted_mean_return_pct"))):
            assert sb[part] == {k: fb[part][k] for k in kk if fb[part].get(k) is not None}, part
            assert "median_return_pct" not in sb[part] and "false_positive_rate_pct" not in sb[part]
        assert "mean_diff_vs_baseline_pct" not in sb
    assert "block_stats" in v["view_trimmed"]


def _strip(x):
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def test_single_stock_group_without_per_ticker_is_left_alone():
    env = rank_env(peers=1, insufficient=True, strength=None)
    v = model_view(env, subject=None)
    assert "per_ticker" not in v["results"] or v["results"]["per_ticker"] == []


# =============================== gerçek retail: boyut ve doğrulayıcı ===============================
def test_real_retail_view_is_much_smaller_and_every_number_in_it_is_in_the_full_envelope(retail_rank_split):
    from harness.number_verifier import verify_numbers

    v = model_view(retail_rank_split, subject="MAVI")
    assert size(v) < 0.65 * size(retail_rank_split), (size(v), size(retail_rank_split))
    # modelin gördüğü her sayı tam zarfta var: görünümden alıntılanan metin halüsinasyon sayılmaz
    text = json.dumps(v["results"], ensure_ascii=False)
    rep = verify_numbers(text.replace('"', " ").replace(",", " "), envelopes=[retail_rank_split], question="")
    assert rep.n_hallucinated == 0, [r.claim.raw for r in rep.claims if r.verdict == "HALLUCINATION"][:5]
    mavi = next(t for t in v["results"]["per_ticker"] if t["ticker"] == "MAVI")
    assert mavi["n_independent_events"] == 21 and "per_horizon" in mavi


# =============================== oturum entegrasyonu ===============================
def test_the_tool_message_shows_the_view_while_the_session_store_keeps_the_full_envelope():
    from harness.agent_loop import run_session
    from harness.llm_backend import ModelReply, ScriptedBackend, ToolCall
    from schemas.examples import example_params

    q = "Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) en çok geride kalan hisse hangisi?"
    steps = [ModelReply(tool_calls=(ToolCall("rank_sector_relative_strength", example_params(T.RANK_SECTOR_RELATIVE_STRENGTH)),)),
             ModelReply(tool_calls=(ToolCall("run_backtest", example_params(T.RUN_BACKTEST)),)), "HAZIR", "EYLEM: INVESTIGATE"]
    backend = ScriptedBackend(steps)
    res = run_session(q, backend, profile="D")
    shown = json.loads(next(m["content"] for m in res.messages if m["role"] == "tool" and m["name"] == "rank_sector_relative_strength"))
    full = res.session.tool_envelopes[0]
    assert shown["view_trimmed"] and "view_trimmed" not in full
    assert len(shown["results"]["per_ticker"]) == len(full["results"]["per_ticker"])
    assert size(shown) < size(full)
    assert any(r.envelope is full for r in res.session.store.records) or full in [r.envelope for r in res.session.store.records]


# =============================== kanıta girmeyen uzun listeler ===============================
def test_reversal_events_and_backtest_trade_log_are_cut_to_the_last_records_and_marked():
    from harness.model_view import LIST_KEEP

    ev = [{"date": f"2026-01-{d:02d}", "close": 1.0 + d} for d in range(1, 21)]
    rv = {"tool": "detect_reversal_events", "status": "OK", "results": {"groups": [{"label": "single_indicator", "n_events_detected": 20, "events": ev},
                                                                                  {"label": "c", "n_events_detected": 1, "events": ev[:1]}]}}
    v = model_view(rv, subject=None)
    assert v["results"]["groups"][0]["events"] == [{"date": e["date"]} for e in ev[-LIST_KEEP:]] and v["results"]["groups"][1]["events"] == [{"date": ev[0]["date"]}]
    assert v["results"]["groups"][0]["n_events_detected"] == 20 and v["view_trimmed"] == ["groups[].events"]
    assert len(rv["results"]["groups"][0]["events"]) == 20                                      # girdi değişmez
    bt = {"tool": "run_backtest", "status": "OK", "results": {"trade_log": [{"n": i} for i in range(10)], "n_signals": 10}}
    v = model_view(bt, subject=None)
    assert v["results"]["trade_log"] == [{"n": i} for i in range(10 - LIST_KEEP, 10)] and v["view_trimmed"] == ["trade_log"] and v["results"]["n_signals"] == 10
    short = {"tool": "run_backtest", "status": "OK", "results": {"trade_log": [{"n": 1}]}}
    assert "view_trimmed" not in model_view(short, subject=None)


def test_backtest_view_keeps_the_numbers_the_evidence_quotes_and_drops_the_rest():
    res = {"strategy": {"transaction_cost_bps": 20.0, "variant": "B", "signal_type": "REVERSAL", "holding_days": 5, "signal_params": {"event_family": "X"}, "train_end": "2025-12-31"},
           "strategy_gross": {"cumulative_return_pct": 9.0}, "cost_model": {"x": 1}, "sharpe_definition": "d",
           "strategy_net": {"cumulative_return_pct": 1.5, "sharpe_ratio": 0.7, "max_drawdown_pct": -3.0, "win_rate_pct": 55.0, "n_trades": 9, "avg_trade_return_pct": 0.2, "exposure_pct": 4.0},
           "benchmarks": [{"name": "XU100", "metrics": {"cumulative_return_pct": 7.0}, "cumulative_return_diff_pct": -5.5, "sharpe_diff": 0.1}],
           "splits": [{"name": "TEST", "window": {"start": "a", "end": "b"}, "n_signals": 4, "net_metrics": {"cumulative_return_pct": 2.0, "annualized_return_pct": 3.0}, "benchmark_diff_pct": 1.0}],
           "n_signals": 9, "last_exit_date": "2026-09-04", "trade_log": [{"n": 1}, {"n": 2}]}
    v = model_view({"tool": "run_backtest", "status": "OK", "results": res,
                    "warnings": ["COST_ASSUMPTIONS: x", "HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir.", "HISTORICAL_ONLY: 34 sinyal alınmadı", "LOW_SIGNAL_COUNT: n=9"]}, subject=None)
    r = v["results"]
    assert r["strategy_net"] == {"cumulative_return_pct": 1.5, "sharpe_ratio": 0.7, "max_drawdown_pct": -3.0, "win_rate_pct": 55.0, "n_trades": 9}
    assert r["benchmarks"] == [{"name": "XU100", "cumulative_return_diff_pct": -5.5, "sharpe_diff": 0.1}]
    assert r["splits"][0]["net_metrics"] == {"cumulative_return_pct": 2.0} and r["splits"][0]["benchmark_diff_pct"] == 1.0 and r["splits"][0]["n_signals"] == 4
    assert r["strategy"] == {"variant": "B", "signal_type": "REVERSAL", "holding_days": 5, "train_end": "2025-12-31", "signal_params": {"event_family": "X"}}
    assert "strategy_gross" not in r and "cost_model" not in r and r["last_exit_date"] == "2026-09-04" and r["trade_log"] == [{"n": 2}]
    assert v["warnings"] == ["HISTORICAL_ONLY: 34 sinyal alınmadı", "LOW_SIGNAL_COUNT: n=9"]            # sabit notlar atıldı, sayılı ve diğer uyarılar kaldı
    assert {"backtest_slim", "trade_log"} <= set(v["view_trimmed"])


def test_history_rows_keep_only_the_first_two_and_last_three():
    rows = [{"date": f"2026-09-{d:02d}", "close": float(d)} for d in range(1, 21)]
    v = model_view({"tool": "get_stock_history", "status": "OK", "results": {"ticker": "X", "n_rows": 20, "rows": rows}}, subject=None)
    assert [r["date"] for r in v["results"]["rows"]] == ["2026-09-01", "2026-09-02", "2026-09-18", "2026-09-19", "2026-09-20"]
    assert v["results"]["n_rows"] == 20 and v["view_trimmed"] == ["rows"]
    short = {"tool": "get_stock_history", "status": "OK", "results": {"rows": rows[:4]}}
    assert "view_trimmed" not in model_view(short, subject=None)


def test_history_rows_also_keep_the_highest_and_lowest_close_rows_the_evidence_quotes():
    rows = [{"date": f"2026-09-{d:02d}", "close": c} for d, c in zip(range(1, 21), [5, 6, 7, 99, 8, 9, 10, 1, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22])]
    v = model_view({"tool": "get_stock_history", "status": "OK", "results": {"rows": rows}}, subject=None)
    got = [r["date"] for r in v["results"]["rows"]]
    assert got == ["2026-09-01", "2026-09-02", "2026-09-04", "2026-09-08", "2026-09-18", "2026-09-19", "2026-09-20"]       # sıra korunur; zirve (99) ve dip (1) var
    assert max(r["close"] for r in v["results"]["rows"]) == 99 and min(r["close"] for r in v["results"]["rows"]) == 1


def test_weekday_windows_keep_only_the_numbers_the_evidence_quotes():
    w = {"window": {"start": "a", "end": "b"}, "n_weeks_total": 105, "n_weeks_complete": 85, "n_trigger_weeks": 18, "n_occurrences": 5, "per_day": [{"x": 1}],
         "t_stat": 1.1, "hit_rate_pct": 27.0, "outcome_mean_return_pct": 1.3, "outcome_mean_diff_vs_unconditional_pct": 0.5,
         "cost_adjusted_outcome_mean_return_pct": 0.8, "p_value_raw": 0.12, "p_value_adjusted": 0.12}
    v = model_view({"tool": "test_weekday_pattern", "status": "OK", "results": {"stability_verdict": "UNSTABLE", "in_sample": dict(w), "out_of_sample": dict(w),
                                                                              "cost_model": {"x": 1}, "multiple_testing": {"n_tests_declared": 1}}}, subject=None)
    r = v["results"]
    assert set(r["in_sample"]) == {"window", "n_weeks_complete", "n_trigger_weeks", "n_occurrences", "outcome_mean_return_pct",
                                   "outcome_mean_diff_vs_unconditional_pct", "cost_adjusted_outcome_mean_return_pct", "p_value_raw", "p_value_adjusted"}
    assert r["stability_verdict"] == "UNSTABLE" and r["multiple_testing"] == {"n_tests_declared": 1} and "cost_model" not in r
    assert "weekday_window_stats" in v["view_trimmed"]


def test_tight_mode_keeps_only_the_horizons_the_evidence_selects(monkeypatch):
    from harness import settings

    def rv():
        return {"tool": "detect_reversal_events", "status": "OK", "results": {"groups": [{"label": "single_indicator", "n_events_detected": 3, "events": [],
                "per_horizon": [{"horizon": h, "full": {"n_events_complete": 3, "hit_rate_pct": 50.0}} for h in (1, 3, 5, 10)]}]}}
    assert [b["horizon"] for b in model_view(rv(), subject=None)["results"]["groups"][0]["per_horizon"]] == [1, 3, 5, 10]          # varsayılan: kapalı
    monkeypatch.setattr(settings, "MODEL_VIEW_TIGHT", True)
    v = model_view(rv(), subject=None)
    assert [b["horizon"] for b in v["results"]["groups"][0]["per_horizon"]] == [5] and "tight_horizons" in v["view_trimmed"]
