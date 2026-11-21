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


def test_pooled_historical_blocks_and_policy_critical_fields_are_not_trimmed():
    env = rank_env(subject="MAVI")
    v = model_view(env, subject="MAVI")
    for key in ("historical_catch_up", "n_raw_laggard_observations", "cooldown_days", "outcome_benchmark_definition", "sector_strength"):
        assert v["results"][key] == _strip(env["results"][key]), key


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
