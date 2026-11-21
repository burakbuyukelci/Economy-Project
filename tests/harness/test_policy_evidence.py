"""Politika <-> kanıt tutarlılığı: etiketi belirleyen alanlar KİLİTLİ committed kanıtta da bulunur.

Gerekçe: model yalnızca committed kanıta dayanarak açıklama yazar (CLAUDE.md kural 6, §25). Etiket, o kanıtta olmayan bir alana
dayanırsa açıklama etiketi gerekçelendiremez. Hangi değer adlarının zorunlu olduğu VERİDİR: evidence_headlines.json `policy_values`.
"""
from __future__ import annotations

from datetime import date

import pytest

from harness.evidence import EXTRACTORS, EnvelopeStore, EvidenceBundle, headline_spec, is_headline, make_analysis_id
from harness.label_policy import decide_label
from policy_builders import backtest_env, fundamental_env, rank_env, reversal_env
from schemas.enums import ToolName as T
from schemas.examples import example_envelope

AS_OF = date(2026, 9, 10)
QUESTION = "Analiz tarihi: 10.09.2026\nPerakende sektöründe geride kalan hisse hangisi?"


def locked_committed(*envs):
    store = EnvelopeStore()
    for e in envs:
        store.add(e, actor="model")
    aid = make_analysis_id(AS_OF, QUESTION)
    b = EvidenceBundle(aid, store)
    b.build({"as_of": "2026-09-10", "analysis_id": aid, "source_input_hashes": [e["input_hash"] for e in envs]})
    b.lock("PASS")
    return b.snapshot()["committed_evidence_set"]


def value_of(item, name):
    return next((v["value"] for v in item["values"] if v["name"] == name), None)


def items_for(committed, env, horizon=None):
    out = [i for i in committed if i["source_input_hash"] == env["input_hash"]]
    if horizon is not None:
        out = [i for i in out if value_of(i, "horizon") == horizon]
    return out


def _full_example(tool):
    """Politikanın okuduğu alanları dolu örnek zarf."""
    if tool == T.RANK_SECTOR_RELATIVE_STRENGTH:
        return rank_env()
    if tool == T.DETECT_REVERSAL_EVENTS:
        return reversal_env()
    if tool == T.CALCULATE_FUNDAMENTAL_CHANGE:
        return fundamental_env()
    if tool == T.RUN_BACKTEST:
        return backtest_env()
    return example_envelope(tool)


# =============================== veri: policy_values ===============================
def test_policy_values_are_declared_for_every_tool_with_an_extractor():
    spec = headline_spec()
    for tool in EXTRACTORS:
        assert "policy_values" in spec[tool.value], tool.value
        assert isinstance(spec[tool.value]["policy_values"], list)


@pytest.mark.parametrize("tool", sorted(EXTRACTORS, key=lambda t: t.value), ids=lambda t: t.value)
def test_policy_values_are_present_in_the_committed_evidence(tool):
    """Politikanın okuduğu değer adları, başlık (committed) kanıt adaylarının değerlerinde bulunur."""
    needed = set(headline_spec()[tool.value]["policy_values"])
    produced = set()
    for cand in EXTRACTORS[tool](_full_example(tool)["results"]):
        if is_headline(tool, cand.section):
            produced |= {v["name"] for v in cand.values}
    assert needed <= produced, f"committed kanıtta eksik: {needed - produced}"


def test_policy_values_names_are_real_value_names_not_stale():
    for tool, spec in headline_spec().items():
        produced = set()
        for cand in EXTRACTORS[T(tool)](_full_example(T(tool))["results"]):
            produced |= {v["name"] for v in cand.values}
        assert set(spec["policy_values"]) <= produced, (tool, set(spec["policy_values"]) - produced)


# =============================== sayısal tutarlılık: GERÇEK retail ===============================
@pytest.mark.parametrize("fixture", ["retail_rank", "retail_rank_split"])
def test_real_retail_policy_facts_equal_the_committed_values(fixture, request):
    env = request.getfixturevalue(fixture)
    committed = locked_committed(env)
    d = decide_label(gate_status="PASS", envelopes=[env])
    s = d.scenarios[0]
    sector = next(i for i in items_for(committed, env) if value_of(i, "sector_strength") is not None)
    assert value_of(sector, "peer_group_size") == s.check("peer_group_size").actual
    assert value_of(sector, "sector_strength") == s.check("sector_strength").actual
    lag = next(i for i in items_for(committed, env) if value_of(i, "is_laggard") is not None)
    assert value_of(lag, "is_laggard") == ("true" if s.check("subject_is_laggard").actual else "false")
    assert value_of(lag, "lag_score_pp") == s.check("lag_score_pp").actual
    for h in (5, 10, 20):
        item = items_for(committed, env, horizon=h)[0]
        assert value_of(item, "n_events_complete") == s.check(f"h{h}.n_events_complete").actual
        assert value_of(item, "cost_adjusted_mean_return_pct") == s.check(f"h{h}.cost_adjusted_mean_full").actual
        assert round(value_of(item, "hit_rate_pct") - value_of(item, "baseline_hit_rate_pct"), 4) == \
            s.check(f"h{h}.hit_minus_baseline_pp").actual
        assert value_of(item, "in_sample_cost_adjusted_mean_return_pct") == s.check(f"h{h}.is_cost_adjusted_mean").actual
        assert value_of(item, "out_of_sample_cost_adjusted_mean_return_pct") == s.check(f"h{h}.oos_cost_adjusted_mean").actual
        assert value_of(item, "out_of_sample_n_events_complete") == s.check(f"h{h}.oos_n").actual
        flag = s.check(f"h{h}.oos_degradation_flag").actual
        assert value_of(item, "oos_degradation_flag") == (None if flag is None else ("true" if flag else "false"))


def test_real_retail_statements_carry_the_same_numbers_the_policy_uses(retail_rank_split):
    committed = locked_committed(retail_rank_split)
    text = " ".join(i["statement"] for i in committed)
    for needle in ("40.0", "-1.3434", "-2.0882", "-0.8768", "true"):   # OOS isabet, OOS maliyet sonrası ortalamalar, 20g bayrağı
        assert needle in text, needle


# =============================== sayısal tutarlılık: sentetik teknik/temel/backtest ===============================
def test_reversal_policy_facts_are_committed():
    env = reversal_env(event_date="2026-09-09")
    committed = locked_committed(env)
    d = decide_label(gate_status="PASS", envelopes=[env, backtest_env(signal_type="REVERSAL", universe=("ASELS",))])
    s = d.scenarios[0]
    group = next(i for i in items_for(committed, env) if value_of(i, "n_events_detected") is not None)
    assert value_of(group, "n_events_detected") == s.check("n_events_detected").actual
    assert value_of(group, "last_event_date") == s.check("current_signal").actual["last_event"]
    for h in (1, 3, 5, 10):
        item = items_for(committed, env, horizon=h)[0]
        assert value_of(item, "baseline_hit_rate_pct") is not None
        assert value_of(item, "out_of_sample_cost_adjusted_mean_return_pct") == s.check(f"h{h}.oos_cost_adjusted_mean").actual


def test_fundamental_policy_facts_are_committed():
    env = fundamental_env(yoy="IMPROVED", qoq="DETERIORATED", secondary="IMPROVED")
    committed = locked_committed(env)
    items = items_for(committed, env)
    assert any(value_of(i, "yoy_direction") == "IMPROVED" and value_of(i, "qoq_direction") == "DETERIORATED" for i in items)
    assert any(value_of(i, "tms29_comparable") == "true" for i in items)
    counts = next(i for i in items if value_of(i, "n_quarters_disclosed_by_as_of") is not None)
    assert value_of(counts, "improvement_metric") == "EBITDA_MARGIN" and value_of(counts, "improvement_basis") == "YOY"


def test_backtest_policy_facts_are_committed():
    env = backtest_env(test_diff=1.5, low_signal=False, flag=False)
    committed = locked_committed(env)
    items = items_for(committed, env)
    assert any(value_of(i, "signal_type") == "CATCH_UP" for i in items)
    assert any(value_of(i, "benchmark_diff_pct") == 1.5 for i in items)
    flags = next(i for i in items if value_of(i, "low_signal_flag") is not None)
    assert value_of(flags, "low_signal_flag") == "false" and value_of(flags, "oos_degradation_flag") == "false"
    assert value_of(flags, "n_signals") == 30


# =============================== şema 1.2.0: havuz tanımı ve hisse bazlı kırılım kanıtta ===============================
def test_rank_evidence_carries_the_pooling_definition_and_the_benchmark():
    env = rank_env()
    committed = items_for(locked_committed(env), env)
    pool = [i for i in committed if value_of(i, "n_raw_laggard_observations") is not None and value_of(i, "ticker") is None]
    assert len(pool) == 1
    res = env["results"]
    assert value_of(pool[0], "n_raw_laggard_observations") == res["n_raw_laggard_observations"]
    assert value_of(pool[0], "cooldown_days") == res["cooldown_days"]
    assert value_of(pool[0], "outcome_benchmark_type") == "peer_median" and value_of(pool[0], "outcome_benchmark_includes_subject") == "false"
    assert str(res["n_raw_laggard_observations"]) in pool[0]["statement"] and "peer_median" in pool[0]["statement"]


def test_rank_evidence_has_one_item_per_ticker_with_subject_level_counts_and_horizon_hit_rates():
    env = rank_env()
    committed = items_for(locked_committed(env), env)
    per_ticker = [i for i in committed if value_of(i, "ticker") is not None and value_of(i, "ticker_n_independent_events") is not None]
    rows = {t["ticker"]: t for t in env["results"]["per_ticker"]}
    assert sorted(value_of(i, "ticker") for i in per_ticker) == sorted(rows)
    for item in per_ticker:
        t = rows[value_of(item, "ticker")]
        assert value_of(item, "ticker_n_raw_laggard_observations") == t["n_raw_laggard_observations"]
        assert value_of(item, "ticker_n_independent_events") == t["n_independent_events"]
        assert value_of(item, "ticker_n_excluded_incomplete_horizon") == t["n_excluded_incomplete_horizon"]
        for row in t["per_horizon"]:                       # ufuk başına: tamamlanmış olay, isabet, taban isabet (özne kendi geçmişi)
            h = row["block"]["horizon"]
            assert value_of(item, f"ticker_h{h}_n_events_complete") == row["block"]["full"]["n_events_complete"]
            assert value_of(item, f"ticker_h{h}_hit_rate_pct") == row["block"]["full"].get("hit_rate_pct")
            assert value_of(item, f"ticker_h{h}_baseline_hit_rate_pct") == row["block"]["baseline"].get("hit_rate_pct")


def test_rank_evidence_numbers_are_copied_not_derived():
    """Harness yeni sayı türetmez (CLAUDE.md kural 6): kanıt cümlelerindeki her sayı kaynak zarfta birebir var."""
    from harness.number_verifier import verify_numbers

    env = rank_env()
    for item in items_for(locked_committed(env), env):
        rep = verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026")
        assert rep.n_hallucinated == 0, (item["statement"], [(r.claim.raw, r.verdict) for r in rep.claims if r.verdict == "HALLUCINATION"])


def test_a_1_1_0_rank_envelope_without_the_new_fields_still_extracts_without_the_new_items():
    env = rank_env()
    for k in ("n_raw_laggard_observations", "cooldown_days", "outcome_benchmark_definition"):
        env["results"][k] = None
    env["results"]["per_ticker"] = []
    committed = items_for(locked_committed(env), env)
    assert committed and all(value_of(i, "ticker_n_independent_events") is None and value_of(i, "cooldown_days") is None for i in committed)


def test_single_stock_group_has_no_pooling_or_per_ticker_items():
    env = rank_env(peers=1, insufficient=True, strength=None)
    committed = items_for(locked_committed(env), env)
    assert all(value_of(i, "ticker_n_independent_events") is None and value_of(i, "cooldown_days") is None for i in committed)


def test_real_retail_per_ticker_evidence_matches_the_tool_output(retail_rank_split):
    """GERÇEK retail (as_of 2026-09-10): hisse bazlı sayılar kanıtta aynen; havuz = parçaların toplamı. Beklenen değerler zarftan okunur (hash/sayı donmuş dosya yok)."""
    from harness.number_verifier import verify_numbers

    env = retail_rank_split
    committed = items_for(locked_committed(env), env)
    by_ticker = {value_of(i, "ticker"): i for i in committed if value_of(i, "ticker_n_independent_events") is not None}
    rows = {t["ticker"]: t for t in env["results"]["per_ticker"]}
    assert set(by_ticker) == set(rows) == {"BIMAS", "MAVI", "MGROS"}
    assert sum(value_of(i, "ticker_n_independent_events") for i in by_ticker.values()) == 44
    assert sum(value_of(i, "ticker_n_raw_laggard_observations") for i in by_ticker.values()) == 398 == env["results"]["n_raw_laggard_observations"]
    for t, item in by_ticker.items():
        assert value_of(item, "ticker_n_independent_events") == rows[t]["n_independent_events"]
        rep = verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026")
        assert rep.n_hallucinated == 0
