"""test_weekday_pattern GERÇEK zarflarıyla (THYAO, ASELS; as_of 2026-09-10, split 2026-01-01): kanıt çıkarıcı, etiket politikası W1–W3, doğrulayıcı.

Beklenen değerler zarftan okunur (donmuş hash/sayı dosyası yok); yalnızca kararlar (UNSTABLE / INSUFFICIENT_DATA) soru metninden gelen beklentidir.
"""
from __future__ import annotations

import copy
from datetime import date

import pytest

from harness.evidence import EnvelopeStore, EvidenceBundle, headline_spec, is_headline, make_analysis_id
from harness.label_policy import decide_label
from harness.number_verifier import verify_numbers
from schemas.enums import AllowedAction as A, ToolName as T

AS_OF = date(2026, 9, 10)
QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO'da Pazartesi–Salı–Çarşamba düşüş, ardından Perşembe–Cuma yükseliş örüntüsü var mı?"
GATE_OK = "PASS_WITH_WARNINGS"


def committed(env):
    store = EnvelopeStore()
    store.add(env, actor="model")
    aid = make_analysis_id(AS_OF, QUESTION)
    b = EvidenceBundle(aid, store)
    b.build({"as_of": "2026-09-10", "analysis_id": aid, "source_input_hashes": [env["input_hash"]]})
    b.lock("PASS")
    return b.snapshot()["committed_evidence_set"]


def value_of(item, name):
    return next((v["value"] for v in item["values"] if v["name"] == name), None)


def decide(env, gate=GATE_OK):
    return decide_label(gate_status=gate, envelopes=[env], question=QUESTION)


# =============================== etiket politikası (W1–W3) ===============================
def test_real_thyao_is_unstable_and_rejected(thyao_weekday):
    res = thyao_weekday["results"]
    assert res["pattern_label"] == "MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP" and res["stability_verdict"] == "UNSTABLE"
    d = decide(thyao_weekday)
    s = d.scenarios[0]
    assert d.label == A.REJECT_SIGNAL and s.rule_id == "W3_UNSTABLE" and s.subject == "THYAO"
    assert "PATTERN_UNSTABLE" in d.reason_codes
    assert s.check("verdict_codes").actual == res["verdict_codes"]                          # IS_NOT_SIGNIFICANT, zarftan
    assert s.check("in_sample.n_trigger_weeks").actual == res["in_sample"]["n_trigger_weeks"]
    assert s.check("out_of_sample.n_trigger_weeks").actual == res["out_of_sample"]["n_trigger_weeks"]


def test_real_asels_has_insufficient_data_and_is_investigated(asels_weekday):
    res = asels_weekday["results"]
    assert res["stability_verdict"] == "INSUFFICIENT_DATA"
    d = decide(asels_weekday)
    assert d.label == A.INVESTIGATE and d.scenarios[0].rule_id == "W2_INSUFFICIENT" and d.scenarios[0].subject == "ASELS"
    assert "PATTERN_INSUFFICIENT_DATA" in d.reason_codes and d.scenarios[0].check("verdict_codes").actual == res["verdict_codes"]


@pytest.mark.parametrize("gate", ["PASS", "PASS_WITH_WARNINGS", "INVESTIGATE"])
def test_real_weekday_labels_do_not_change_with_a_passing_gate_or_gate_investigate(thyao_weekday, asels_weekday, gate):
    """G3 yalnızca ADAYLARI düşürür; haftalık örüntünün aday etiketi yoktur => kapı INVESTIGATE de etiketi değiştirmez."""
    assert decide(thyao_weekday, gate).label == A.REJECT_SIGNAL and decide(asels_weekday, gate).label == A.INVESTIGATE


def test_real_weekday_with_an_unsafe_gate_is_analysis_unsafe(thyao_weekday):
    assert decide(thyao_weekday, "HARD_BLOCK").label == A.ANALYSIS_UNSAFE


def test_a_stable_verdict_would_only_reach_watch_never_a_candidate(thyao_weekday):
    """VARSAYIMSAL (gerçek değil): hüküm STABLE olsaydı en olumlusu WATCH (W1); haftalık örüntü için aday etiketi yok."""
    env = copy.deepcopy(thyao_weekday)
    env["results"]["stability_verdict"], env["results"]["verdict_codes"] = "STABLE", []
    d = decide(env)
    assert d.label == A.WATCH and d.scenarios[0].rule_id == "W1_STABLE"


# =============================== kanıt çıkarıcı ===============================
def test_headline_spec_declares_the_weekday_sections_and_policy_values():
    spec = headline_spec()["test_weekday_pattern"]
    assert {"verdict", "window", "multiple_testing"} <= set(spec["headline"])
    assert {"stability_verdict", "verdict_reason", "n_trigger_weeks"} <= set(spec["policy_values"])
    assert is_headline(T.TEST_WEEKDAY_PATTERN, "multiple_testing")


def test_real_thyao_evidence_carries_decision_counts_raw_and_adjusted_p_and_cost_adjusted_mean(thyao_weekday):
    res = thyao_weekday["results"]
    items = [i for i in committed(thyao_weekday) if i["source_input_hash"] == thyao_weekday["input_hash"]]
    verdict = next(i for i in items if value_of(i, "stability_verdict") is not None)
    assert value_of(verdict, "stability_verdict") == "UNSTABLE" and "IS_NOT_SIGNIFICANT" in verdict["statement"]
    windows = [i for i in items if value_of(i, "p_value_raw") is not None]
    assert len(windows) == 2                                                         # örneklem içi ve dışı
    for item, key in zip(windows, ("in_sample", "out_of_sample")):
        w = res[key]
        for name in ("n_weeks_complete", "n_trigger_weeks", "n_occurrences", "p_value_raw", "p_value_adjusted"):
            assert value_of(item, name) == w[name], (key, name)
        assert value_of(item, "cost_adjusted_outcome_mean_return_pct") == w["cost_adjusted_outcome_mean_return_pct"]
        assert str(w["p_value_raw"]) in item["statement"] and str(w["p_value_adjusted"]) in item["statement"]
    mt = next(i for i in items if value_of(i, "n_tests_declared") is not None)
    assert value_of(mt, "n_tests_declared") == res["multiple_testing"]["n_tests_declared"]
    assert value_of(mt, "multiple_testing_method") == "bonferroni" and value_of(mt, "alpha") == res["multiple_testing"]["alpha"]


def test_real_weekday_policy_values_are_in_the_committed_evidence(thyao_weekday, asels_weekday):
    needed = set(headline_spec()["test_weekday_pattern"]["policy_values"])
    for env in (thyao_weekday, asels_weekday):
        names = {v["name"] for i in committed(env) for v in i["values"]}
        assert needed <= names, needed - names


@pytest.mark.parametrize("fixture", ["thyao_weekday", "asels_weekday"])
def test_real_weekday_evidence_numbers_are_copied_not_derived(request, fixture):
    env = request.getfixturevalue(fixture)
    for item in committed(env):
        rep = verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026")
        assert rep.n_hallucinated == 0, (item["statement"], [r.claim.raw for r in rep.claims if r.verdict == "HALLUCINATION"])


def test_real_weekday_warnings_including_multiple_testing_risk_are_quotable(thyao_weekday):
    assert any(w.startswith("MULTIPLE_TESTING_RISK") for w in thyao_weekday["warnings"])      # her zarfta bulunur
    rep = verify_numbers("Bu örüntü tek hipotezdir; n_tests_declared=1 ve Bonferroni düzeltmesi p x 1.", envelopes=[thyao_weekday], question="")
    assert rep.n_hallucinated == 0
