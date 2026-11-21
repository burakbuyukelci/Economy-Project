"""Etiket politikası (harness/label_policy.py): kanıt + kapı -> izinli eylem. Kural tablosu docs/harness_design.md bölüm 11.

Önce testler: her tablo satırı, sınır değerleri, öncelik/birleştirme matrisi, tavsiye niyeti, determinizm ve GERÇEK retail örneği.
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest

import config.settings as cfg
from harness import settings
from harness.label_policy import (
    CANDIDATE_LABELS, CAUTION_ORDER, RULE_IDS, PolicyThresholds, combine_scenario_labels, decide_label, detect_advice_intent,
)
from policy_builders import (
    backtest_env, block, fundamental_env, history_env, macro_env, rank_env, reversal_env, weekday_env,
)
from schemas.enums import AllowedAction as A

REPO = Path(__file__).resolve().parents[2]
CU, TR, FI = A.POTENTIAL_CATCH_UP_CANDIDATE, A.TECHNICAL_REVERSAL_CANDIDATE, A.FUNDAMENTAL_IMPROVEMENT_CANDIDATE
GATE_OK = "PASS_WITH_WARNINGS"


def decide(envs, *, gate=GATE_OK, question="", subject=None, **kw):
    return decide_label(gate_status=gate, envelopes=envs, question=question, subject=subject, **kw)


def rule_of(d, i=0):
    return d.scenarios[i].rule_id


def good_cu(**over):
    """Her koşulu sağlayan catch-up kanıtı (rank + backtest)."""
    return [rank_env(**over), backtest_env()]


# =============================== eşikler ve ayarlar ===============================
def test_threshold_defaults_are_the_approved_values():
    t = PolicyThresholds()
    assert (t.hit_margin_pp, t.min_passing_horizons, t.min_peers, t.min_quarters, t.signal_recency_trading_days) == (5.0, 2, 3, 4, 3)
    assert t.min_events == cfg.MIN_EVENTS and t.min_oos_events == cfg.MIN_OOS_EVENTS
    assert settings.POLICY_HIT_MARGIN_PP == 5.0 and settings.POLICY_MIN_QUARTERS == 4


def test_min_events_follows_config_at_call_time(monkeypatch):
    envs = [rank_env(blocks=[block(5, n=25), block(10, n=25), block(20, n=25)]), backtest_env()]
    assert decide(envs).label == CU
    monkeypatch.setattr(cfg, "MIN_EVENTS", 30)
    d = decide(envs)
    assert d.label == A.INVESTIGATE and rule_of(d) == "C3_FEW_EVENTS"


def test_rule_ids_and_ordering_constants():
    assert CAUTION_ORDER == (A.ANALYSIS_UNSAFE, A.INVESTIGATE, A.REJECT_SIGNAL, A.WATCH, A.HOLD, CU, TR, FI) or \
        CAUTION_ORDER[:5] == (A.ANALYSIS_UNSAFE, A.INVESTIGATE, A.REJECT_SIGNAL, A.WATCH, A.HOLD)
    assert CANDIDATE_LABELS == frozenset({CU, TR, FI})
    assert {"G1_GATE_UNSAFE", "G2_GATE_MISSING", "G3_GATE_INVESTIGATE", "G6_ADVICE_CAP", "G7_NO_SCENARIO",
            "C1_PEERS_OR_STRENGTH", "C5_CANDIDATE", "W1_STABLE", "T6_NO_EVENTS", "F3_CANDIDATE"} <= RULE_IDS


# =============================== G1/G2: kapı ===============================
@pytest.mark.parametrize("gate", ["HARD_BLOCK", "ANALYSIS_UNSAFE"])
def test_g1_unsafe_gate_overrides_everything(gate):
    d = decide(good_cu(), gate=gate)
    assert d.label == A.ANALYSIS_UNSAFE and d.rule_id == "G1_GATE_UNSAFE"


def test_g1_applies_even_without_any_evidence():
    assert decide([], gate="HARD_BLOCK").label == A.ANALYSIS_UNSAFE


@pytest.mark.parametrize("gate", [None, "", "WEIRD", "pass"])
def test_g2_missing_or_unknown_gate_is_investigate(gate):
    d = decide(good_cu(), gate=gate)
    assert d.label == A.INVESTIGATE and d.rule_id == "G2_GATE_MISSING"
    assert "GATE_MISSING" in d.reason_codes


@pytest.mark.parametrize("gate", ["PASS", "PASS_WITH_WARNINGS"])
def test_passing_gates_allow_candidates(gate):
    assert decide(good_cu(), gate=gate).label == CU


# =============================== G3: kapı INVESTIGATE yalnızca adayları düşürür ===============================
def candidate_cases():
    return {
        CU: good_cu(),
        TR: [reversal_env(), backtest_env(signal_type="REVERSAL", universe=("ASELS",))],
        FI: [fundamental_env()],
    }


@pytest.mark.parametrize("label", [CU, TR, FI], ids=lambda a: a.value)
def test_g3_gate_investigate_drops_only_candidates(label):
    envs = candidate_cases()[label]
    assert decide(envs, gate="PASS").label == label
    d = decide(envs, gate="INVESTIGATE")
    assert d.label == A.INVESTIGATE
    assert d.scenarios[0].raw_label == label and d.scenarios[0].rule_id == "G3_GATE_INVESTIGATE"
    assert "GATE_INVESTIGATE_CAP" in d.reason_codes


@pytest.mark.parametrize("envs,expected", [
    ([weekday_env("STABLE")], A.WATCH),
    ([weekday_env("UNSTABLE", ["OOS_SIGN_FLIP"])], A.REJECT_SIGNAL),
    ([rank_env(laggard=False, subject_lag=-1.0)], A.HOLD),
    ([rank_env(blocks=[block(5, hit=40.0), block(10, hit=40.0), block(20, hit=40.0)])], A.REJECT_SIGNAL),
])
def test_g3_gate_investigate_lets_hold_watch_reject_pass_through(envs, expected):
    d = decide(envs, gate="INVESTIGATE")
    assert d.label == expected
    assert d.scenarios[0].raw_label == d.scenarios[0].label == expected


# =============================== G5: birleştirme matrisi ===============================
@pytest.mark.parametrize("items,expected,rule", [
    ([(CU, "A")], CU, "G5_COMBINE"),
    ([(CU, "A"), (CU, "B")], CU, "G5_COMBINE"),
    ([(CU, "A"), (TR, "B")], A.WATCH, "G5_DIFFERENT_CANDIDATES"),
    ([(CU, "A"), (TR, "A")], A.WATCH, "G5_DIFFERENT_CANDIDATES"),
    ([(CU, "A"), (TR, "B"), (FI, "C")], A.WATCH, "G5_DIFFERENT_CANDIDATES"),
    ([(CU, "A"), (A.REJECT_SIGNAL, "A")], A.INVESTIGATE, "G5_CANDIDATE_VS_REJECT"),
    ([(TR, "A"), (A.REJECT_SIGNAL, "A")], A.INVESTIGATE, "G5_CANDIDATE_VS_REJECT"),
    ([(FI, "A"), (A.REJECT_SIGNAL, "A")], A.INVESTIGATE, "G5_CANDIDATE_VS_REJECT"),
    ([(CU, "A"), (A.REJECT_SIGNAL, "B")], A.REJECT_SIGNAL, "G5_COMBINE"),            # farklı özne: çelişki değil, en temkinli
    ([(CU, None), (A.REJECT_SIGNAL, None)], A.REJECT_SIGNAL, "G5_COMBINE"),          # özne bilinmiyorsa aynı sayılmaz
    ([(CU, "A"), (TR, "B"), (A.REJECT_SIGNAL, "A")], A.INVESTIGATE, "G5_CANDIDATE_VS_REJECT"),
    ([(CU, "A"), (A.HOLD, "A")], A.HOLD, "G5_COMBINE"),
    ([(CU, "A"), (TR, "B"), (A.HOLD, "C")], A.HOLD, "G5_COMBINE"),                   # HOLD adaylardan temkinli
    ([(CU, "A"), (A.WATCH, "B")], A.WATCH, "G5_COMBINE"),
    ([(A.HOLD, "A"), (A.WATCH, "A")], A.WATCH, "G5_COMBINE"),
    ([(A.WATCH, "A"), (A.REJECT_SIGNAL, "A")], A.REJECT_SIGNAL, "G5_COMBINE"),
    ([(A.REJECT_SIGNAL, "A"), (A.INVESTIGATE, "B")], A.INVESTIGATE, "G5_COMBINE"),
    ([(A.INVESTIGATE, "A"), (A.ANALYSIS_UNSAFE, "B")], A.ANALYSIS_UNSAFE, "G5_COMBINE"),
    ([(CU, "A"), (A.ANALYSIS_UNSAFE, "A")], A.ANALYSIS_UNSAFE, "G5_COMBINE"),
])
def test_g5_combination_matrix(items, expected, rule):
    assert combine_scenario_labels(items) == (expected, rule)


def test_g5_is_order_independent():
    items = [(CU, "A"), (TR, "B"), (A.REJECT_SIGNAL, "A"), (A.HOLD, "C"), (A.WATCH, "D")]
    base = combine_scenario_labels(items)
    for perm in itertools.permutations(items):
        assert combine_scenario_labels(list(perm)) == base


def test_g5_conflict_end_to_end_same_subject():
    d = decide([rank_env(tag="r1", subject="MAVI"), backtest_env(),
                rank_env(tag="r2", subject="MAVI", blocks=[block(5, hit=40.0), block(10, hit=40.0), block(20, hit=40.0)])])
    assert d.label == A.INVESTIGATE and d.rule_id == "G5_CANDIDATE_VS_REJECT"
    assert sorted(s.label.value for s in d.scenarios) == ["INVESTIGATE".replace("INVESTIGATE", "POTENTIAL_CATCH_UP_CANDIDATE"), "REJECT_SIGNAL"] \
        or {s.label for s in d.scenarios} == {CU, A.REJECT_SIGNAL}


def test_g5_two_different_candidates_end_to_end():
    d = decide([rank_env(), backtest_env(), fundamental_env(ticker="MAVI")])
    assert {s.label for s in d.scenarios} == {CU, FI}
    assert d.label == A.WATCH and d.rule_id == "G5_DIFFERENT_CANDIDATES"


def test_g5_scenarios_are_sorted_deterministically_regardless_of_input_order():
    envs = [weekday_env(tag="w"), rank_env(), backtest_env(), fundamental_env()]
    a = decide(envs).to_dict()
    for perm in itertools.permutations(envs):
        assert decide(list(perm)).to_dict() == a


# =============================== G6/G7: tavsiye niyeti ve senaryosuz durum ===============================
@pytest.mark.parametrize("q,advice,certain", [
    ("Bugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver.", True, True),
    ("Yarın EREGL alayım mı?", True, False),
    ("THYAO için hedef fiyat ver.", True, False),
    ("THYAO'yu satmalı mıyım?", True, False),
    ("Should I buy THYAO now?", True, False),
    ("What is the price target for THYAO?", True, False),
    ("EREGL garanti kazandırır mı?", False, True),
    ("Perakende sektöründe (BIMAS, MGROS, MAVI) son 20 işlem gününde en çok geride kalan hisse hangisi? POTENTIAL_CATCH_UP_CANDIDATE olarak etiketlenebilir mi?", False, False),
    ("ASELS'te kaç kez alt Bollinger bandına dokunuldu? Bunların kaçında fiyat 5 gün içinde yükseldi?", False, False),
    ("TUPRS'un tüm çeyreklik bilançolarında FAVÖK marjı nasıl değişti?", False, False),
    ("", False, False),
])
def test_advice_intent_detection(q, advice, certain):
    assert detect_advice_intent(q) == (advice, certain)


def test_g6_caps_candidates_and_hold_to_watch():
    q = "THYAO'yu alayım mı?"
    for envs in (good_cu(), [reversal_env(), backtest_env(signal_type="REVERSAL", universe=("ASELS",))], [fundamental_env()]):
        d = decide(envs, question=q)
        assert d.label == A.WATCH and d.rule_id == "G6_ADVICE_CAP" and d.advice_intent
        assert "ADVICE_INTENT_CAP" in d.reason_codes
    d = decide([rank_env(laggard=False, subject_lag=-1.0)], question=q)
    assert d.label == A.WATCH and d.rule_id == "G6_ADVICE_CAP"


@pytest.mark.parametrize("envs,expected", [
    ([weekday_env("STABLE")], A.WATCH),
    ([weekday_env("UNSTABLE", ["OOS_SIGN_FLIP"])], A.REJECT_SIGNAL),
    ([weekday_env("INSUFFICIENT_DATA")], A.INVESTIGATE),
])
def test_g6_does_not_touch_watch_reject_investigate(envs, expected):
    d = decide(envs, question="THYAO'yu alayım mı?")
    assert d.label == expected and d.rule_id != "G6_ADVICE_CAP"


def test_g6_unsafe_passes_through_advice_questions():
    assert decide(good_cu(), gate="HARD_BLOCK", question="alayım mı?").label == A.ANALYSIS_UNSAFE


def test_g6_without_advice_question_candidates_stay():
    assert decide(good_cu(), question="Perakende sektöründe en çok geride kalan hangisi?").label == CU


def test_g7_question_five_macro_only_with_unverified_certainty_claim():
    q = "Bugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı? Hedef fiyat ver."
    d = decide([macro_env(), history_env()], question=q)
    assert d.label == A.INVESTIGATE and d.rule_id == "G7_UNVERIFIED_CLAIM"
    assert d.advice_intent and d.certainty_claim and "UNVERIFIED_CERTAINTY_CLAIM" in d.reason_codes
    assert d.scenarios == []


def test_g7_no_scenario_tools_default_is_investigate():
    for envs in ([], [history_env()], [macro_env()]):
        d = decide(envs, question="THYAO nasıl?")
        assert d.label == A.INVESTIGATE and d.rule_id == "G7_NO_SCENARIO" and "NO_SCENARIO_EVIDENCE" in d.reason_codes


def test_error_envelopes_and_gate_bundle_envelopes_are_ignored():
    bad = rank_env()
    bad = {**bad, "status": "ERROR", "results": None, "error": {"code": "NO_DATA", "message": "x"}}
    assert decide([bad], question="").rule_id == "G7_NO_SCENARIO"


# =============================== catch-up (C1–C7) ===============================
def test_c5_candidate_when_everything_holds():
    d = decide(good_cu())
    s = d.scenarios[0]
    assert d.label == CU and s.rule_id == "C5_CANDIDATE" and s.subject == "MAVI" and s.scenario == "CATCH_UP"
    assert s.check("passing_horizons").actual == 3 and s.check("passing_horizons").ok


@pytest.mark.parametrize("over,rule", [
    (dict(peers=2), "C1_PEERS_OR_STRENGTH"),
    (dict(peers=1, insufficient=True), "C1_PEERS_OR_STRENGTH"),
    (dict(strength=None), "C1_PEERS_OR_STRENGTH"),
])
def test_c1_peers_or_strength_missing(over, rule):
    d = decide([rank_env(**over), backtest_env()])
    assert d.label == A.INVESTIGATE and rule_of(d) == rule


def test_c1_peer_boundary_three_is_enough():
    assert decide(good_cu(peers=3)).label == CU
    assert decide(good_cu(peers=2)).label == A.INVESTIGATE


def test_c1_subject_not_in_ranking():
    d = decide(good_cu(), subject="XXXXX")
    assert d.label == A.INVESTIGATE and "SUBJECT_NOT_IN_RANKING" in d.reason_codes


def test_c2_not_laggard_is_hold():
    d = decide(good_cu(laggard=False, subject_lag=-2.0))
    assert d.label == A.HOLD and rule_of(d) == "C2_NOT_LAGGARD"


def test_subject_defaults_to_the_most_lagging_stock_and_can_be_overridden():
    env = rank_env(subject="MAVI", subject_lag=-8.0)
    assert decide([env, backtest_env()]).scenarios[0].subject == "MAVI"
    d = decide([env, backtest_env()], subject="BIMAS")   # lider: laggard değil
    assert d.scenarios[0].subject == "BIMAS" and d.label == A.HOLD


@pytest.mark.parametrize("n,expected,rule", [(19, A.INVESTIGATE, "C3_FEW_EVENTS"), (20, CU, "C5_CANDIDATE")])
def test_c3_event_count_boundary(n, expected, rule):
    # 1.2.0: havuzlu bloklarda n_events_complete + n_excluded ufuklar arasında sabit (bağımsız olay sayısı 40): fark "dışlanan" olarak yazılır
    d = decide([rank_env(blocks=[block(5), block(10, n=n, excl=40 - n), block(20)]), backtest_env()])
    assert d.label == expected and rule_of(d) == rule
    assert d.scenarios[0].check("h10.n_events_complete").actual == n


def test_c3_precedes_reject():
    d = decide([rank_env(blocks=[block(5, n=10, hit=10.0), block(10, n=10, hit=10.0), block(20, n=10, hit=10.0)])])
    assert d.label == A.INVESTIGATE and rule_of(d) == "C3_FEW_EVENTS"      # az olayla REJECT iddia edilmez


def test_c4_reject_when_majority_of_horizons_below_baseline():
    d = decide([rank_env(blocks=[block(5, hit=45.0), block(10, hit=45.0), block(20, hit=60.0)])])
    assert d.label == A.REJECT_SIGNAL and rule_of(d) == "C4_REJECT_HISTORY"


def test_c4_one_of_three_below_baseline_is_not_a_reject():
    d = decide([rank_env(blocks=[block(5, hit=45.0), block(10), block(20)]), backtest_env()])
    assert d.label == CU                                                     # 2/3 ufuk geçti


def test_c4_oos_degradation_flag_rejects_even_with_good_hit_rates():
    d = decide([rank_env(blocks=[block(5), block(10), block(20, flag=True)]), backtest_env()])
    assert d.label == A.REJECT_SIGNAL and rule_of(d) == "C4_REJECT_HISTORY"
    assert d.scenarios[0].check("h20.oos_degradation_flag").ok is False


def test_c4_backtest_oos_degradation_flag_rejects():
    d = decide([rank_env(), backtest_env(flag=True)])
    assert d.label == A.REJECT_SIGNAL and rule_of(d) == "C4_REJECT_HISTORY"


@pytest.mark.parametrize("hit,expected", [(54.99, A.WATCH), (55.0, CU)])
def test_hit_margin_boundary_is_five_points(hit, expected):
    d = decide([rank_env(blocks=[block(5, hit=hit), block(10, hit=hit), block(20, hit=hit)]), backtest_env()])
    assert d.label == expected
    assert d.scenarios[0].check("h5.hit_minus_baseline_pp").actual == pytest.approx(hit - 50.0)


@pytest.mark.parametrize("which", ["full", "is", "oos"])
def test_non_positive_cost_adjusted_mean_fails_the_horizon(which):
    kw = {"full": dict(cost=-0.1), "is": dict(is_=(30, 60.0, -0.1)), "oos": dict(oos=(10, 60.0, 0.0))}[which]
    d = decide([rank_env(blocks=[block(5, **kw), block(10, **kw), block(20)]), backtest_env()])
    assert d.label == A.WATCH and rule_of(d) == "C7_WATCH"              # yalnızca 1/3 ufuk geçti (<2)
    assert d.scenarios[0].check("passing_horizons").actual == 1


def test_two_passing_horizons_are_enough():
    d = decide([rank_env(blocks=[block(5, cost=-1.0), block(10), block(20)]), backtest_env()])
    assert d.label == CU and d.scenarios[0].check("passing_horizons").actual == 2


def test_c6_oos_missing_is_investigate_with_the_required_reason():
    d = decide([rank_env(blocks=[block(5, is_=None, oos=None, flag=None), block(10, is_=None, oos=None, flag=None),
                                 block(20, is_=None, oos=None, flag=None)]), backtest_env()])
    assert d.label == A.INVESTIGATE and rule_of(d) == "C6_VALIDATION_MISSING"
    assert "OOS_VALIDATION_MISSING" in d.reason_codes
    assert any(r.message == "OOS doğrulaması yapılmadı" for r in d.reasons)


@pytest.mark.parametrize("n_oos,expected", [(4, A.INVESTIGATE), (5, CU)])
def test_c6_oos_sample_size_boundary(n_oos, expected):
    d = decide([rank_env(blocks=[block(h, oos=(n_oos, 60.0, 0.7)) for h in (5, 10, 20)]), backtest_env()])
    assert d.label == expected


@pytest.mark.parametrize("bt", [None, "no_test_split", "low_signal"])
def test_c6_backtest_missing_or_unusable_is_investigate(bt):
    envs = [rank_env()]
    if bt == "no_test_split":
        envs.append(backtest_env(test_diff=None))
    elif bt == "low_signal":
        envs.append(backtest_env(low_signal=True, n_signals=5))
    d = decide(envs)
    assert d.label == A.INVESTIGATE and rule_of(d) == "C6_VALIDATION_MISSING"
    assert {"BACKTEST_MISSING", "BACKTEST_NO_TEST_SPLIT", "BACKTEST_LOW_SIGNAL"} & set(d.reason_codes)


def test_backtest_for_another_signal_or_universe_does_not_count():
    assert decide([rank_env(), backtest_env(signal_type="REVERSAL")]).label == A.INVESTIGATE
    assert decide([rank_env(), backtest_env(universe=("AKBNK",))]).label == A.INVESTIGATE


def test_c7_backtest_not_beating_benchmark_is_watch():
    d = decide([rank_env(), backtest_env(test_diff=-0.2)])
    assert d.label == A.WATCH and rule_of(d) == "C7_WATCH"
    d = decide([rank_env(), backtest_env(test_diff=0.0)])
    assert d.label == A.WATCH                                                # > 0 şart (0 yetmez)


@pytest.mark.parametrize("strength", ["NEUTRAL", "WEAK"])
def test_c7_sector_not_strong_with_good_history_is_watch(strength):
    d = decide(good_cu(strength=strength))
    assert d.label == A.WATCH and rule_of(d) == "C7_WATCH"
    assert d.scenarios[0].check("sector_strength").ok is False


def test_candidate_requires_pass_or_pass_with_warnings_gate_only():
    for gate, expected in (("PASS", CU), ("PASS_WITH_WARNINGS", CU), ("INVESTIGATE", A.INVESTIGATE)):
        assert decide(good_cu(), gate=gate).label == expected


# =============================== haftanın günü (W1–W3) ===============================
@pytest.mark.parametrize("verdict,codes,expected,rule", [
    ("STABLE", [], A.WATCH, "W1_STABLE"),
    ("INSUFFICIENT_DATA", ["IS_TOO_FEW"], A.INVESTIGATE, "W2_INSUFFICIENT"),
    ("INSUFFICIENT_DATA", ["OOS_TOO_FEW"], A.INVESTIGATE, "W2_INSUFFICIENT"),
    ("UNSTABLE", ["IS_NOT_SIGNIFICANT"], A.REJECT_SIGNAL, "W3_UNSTABLE"),
    ("UNSTABLE", ["OOS_SIGN_FLIP"], A.REJECT_SIGNAL, "W3_UNSTABLE"),
    ("UNSTABLE", ["OOS_COST_ADJ_NOT_POSITIVE", "OOS_HIT_RATE_TOO_LOW"], A.REJECT_SIGNAL, "W3_UNSTABLE"),
])
def test_weekday_table(verdict, codes, expected, rule):
    d = decide([weekday_env(verdict, codes)])
    assert d.label == expected and rule_of(d) == rule and d.scenarios[0].scenario == "WEEKDAY"


def test_weekday_never_yields_a_candidate_label():
    for v, c in (("STABLE", []), ("UNSTABLE", ["OOS_SIGN_FLIP"]), ("INSUFFICIENT_DATA", ["IS_TOO_FEW"])):
        assert decide([weekday_env(v, c)]).label not in CANDIDATE_LABELS


def test_weekday_records_verdict_codes_as_info():
    s = decide([weekday_env("UNSTABLE", ["OOS_SIGN_FLIP"])]).scenarios[0]
    assert s.check("stability_verdict").actual == "UNSTABLE" and s.check("verdict_codes").actual == ["OOS_SIGN_FLIP"]


# =============================== teknik dönüş (T0–T6) ===============================
def good_tr(**over):
    return [reversal_env(**over), backtest_env(signal_type="REVERSAL", universe=("ASELS",))]


def test_t3_candidate_when_everything_holds():
    d = decide(good_tr())
    assert d.label == TR and rule_of(d) == "T3_CANDIDATE" and d.scenarios[0].scenario == "REVERSAL"
    assert d.scenarios[0].subject == "ASELS"


def test_t6_no_events_is_hold_and_precedes_few_events():
    d = decide([reversal_env(n_detected=0, event_date=None,
                             blocks=[block(1, n=0, hit=None, cost=None, is_=None, oos=None, flag=None)])])
    assert d.label == A.HOLD and rule_of(d) == "T6_NO_EVENTS"


def test_t6_applies_only_to_a_valid_scan():
    bad = {**reversal_env(), "status": "ERROR", "results": None, "error": {"code": "NO_DATA", "message": "x"}}
    assert decide([bad]).rule_id == "G7_NO_SCENARIO"


def test_t0_no_unconditional_group_is_investigate():
    d = decide([reversal_env(label="rsi_trough_and_volume")])
    assert d.label == A.INVESTIGATE and rule_of(d) == "T0_NO_PRIMARY_GROUP"


@pytest.mark.parametrize("n,expected,rule", [(19, A.INVESTIGATE, "T1_FEW_EVENTS"), (20, TR, "T3_CANDIDATE")])
def test_t1_event_count_boundary(n, expected, rule):
    d = decide(good_tr(blocks=[block(1), block(3), block(5, n=n), block(10)]))
    assert d.label == expected and rule_of(d) == rule


def test_t2_reject_majority_below_baseline_or_oos_degradation():
    d = decide([reversal_env(blocks=[block(1, hit=40.0), block(3, hit=40.0), block(5), block(10)])])   # 2/4: çoğunluk değil
    assert d.label != A.REJECT_SIGNAL
    d = decide([reversal_env(blocks=[block(1, hit=40.0), block(3, hit=40.0), block(5, hit=40.0), block(10)])])
    assert d.label == A.REJECT_SIGNAL and rule_of(d) == "T2_REJECT_HISTORY"
    d = decide(good_tr(blocks=[block(1), block(3), block(5, flag=True), block(10)]))
    assert d.label == A.REJECT_SIGNAL and rule_of(d) == "T2_REJECT_HISTORY"


def test_t4_validation_missing_is_investigate():
    d = decide([reversal_env(blocks=[block(h, is_=None, oos=None, flag=None) for h in (1, 3, 5, 10)]),
                backtest_env(signal_type="REVERSAL", universe=("ASELS",))])
    assert d.label == A.INVESTIGATE and rule_of(d) == "T4_VALIDATION_MISSING" and "OOS_VALIDATION_MISSING" in d.reason_codes
    d = decide([reversal_env()])                                                  # backtest yok
    assert d.label == A.INVESTIGATE and rule_of(d) == "T4_VALIDATION_MISSING" and "BACKTEST_MISSING" in d.reason_codes


@pytest.mark.parametrize("event_date,expected", [
    ("2026-09-10", TR),    # as_of günü
    ("2026-09-09", TR),    # 1 işlem günü
    ("2026-09-07", TR),    # Pzt -> Per: 3 işlem günü (sınır dahil)
    ("2026-09-04", A.WATCH),  # Cum -> Per: 4 işlem günü
    ("2026-08-03", A.WATCH),
])
def test_t3_current_signal_recency_boundary_is_three_trading_days(event_date, expected):
    d = decide(good_tr(event_date=event_date))
    assert d.label == expected
    if expected == A.WATCH:
        assert rule_of(d) == "T5_WATCH"


def test_t5_watch_when_history_is_mixed():
    d = decide(good_tr(blocks=[block(1, hit=52.0), block(3, hit=52.0), block(5, hit=52.0), block(10, hit=52.0)]))
    assert d.label == A.WATCH and rule_of(d) == "T5_WATCH"


def test_reversal_uses_the_unconditional_group_not_combined_ones():
    env = reversal_env()
    assert decide([env, backtest_env(signal_type="REVERSAL", universe=("ASELS",))]).scenarios[0].check("primary_group").actual == "single_indicator"


# =============================== temel veri (F1–F4) — GEÇİCİ eşikler ===============================
@pytest.mark.parametrize("over,expected,rule", [
    (dict(n_quarters=3), A.INVESTIGATE, "F1_INSUFFICIENT"),
    (dict(n_quarters=4), FI, "F3_CANDIDATE"),
    (dict(tms29=False), A.INVESTIGATE, "F1_INSUFFICIENT"),
    (dict(), FI, "F3_CANDIDATE"),
    (dict(yoy="DETERIORATED", secondary="DETERIORATED"), A.REJECT_SIGNAL, "F2_REJECT"),
    (dict(yoy="DETERIORATED", secondary=None), A.REJECT_SIGNAL, "F2_REJECT"),
    (dict(yoy="DETERIORATED", secondary="IMPROVED"), A.WATCH, "F4_WATCH"),
    (dict(yoy="FLAT"), A.WATCH, "F4_WATCH"),
    (dict(yoy=None), A.WATCH, "F4_WATCH"),
    (dict(secondary="DETERIORATED"), A.WATCH, "F4_WATCH"),
    (dict(secondary=None), FI, "F3_CANDIDATE"),
])
def test_fundamental_table(over, expected, rule):
    d = decide([fundamental_env(**over)])
    assert d.label == expected and rule_of(d) == rule and d.scenarios[0].scenario == "FUNDAMENTAL"


def test_fundamental_basis_selects_the_direction_field():
    assert decide([fundamental_env(basis="QOQ", qoq="IMPROVED", yoy="DETERIORATED")]).label == FI
    assert decide([fundamental_env(basis="QOQ", qoq="DETERIORATED", yoy="IMPROVED", secondary="DETERIORATED")]).label == A.REJECT_SIGNAL


def test_fundamental_price_reaction_is_reported_but_never_gates():
    neg = decide([fundamental_env(reaction_mean=-3.0)])
    pos = decide([fundamental_env(reaction_mean=3.0)])
    assert neg.label == pos.label == FI
    assert neg.scenarios[0].check("reaction.mean_abnormal_vs_xu100_pct.h5.IMPROVED").info is True


def test_fundamental_thresholds_are_marked_provisional():
    d = decide([fundamental_env()])
    assert d.scenarios[0].provisional is True and "THRESHOLDS_PROVISIONAL" in d.reason_codes
    assert decide([weekday_env()]).scenarios[0].provisional is False
    assert decide(good_cu()).scenarios[0].provisional is False


# =============================== zorunlu notlar ve bilgi alanları ===============================
@pytest.mark.parametrize("label", [CU, TR, FI], ids=lambda a: a.value)
def test_candidate_labels_always_carry_the_uncertainty_note(label):
    d = decide(candidate_cases()[label])
    assert d.label == label and "CANDIDATE_CAVEAT" in d.reason_codes
    text = " ".join(r.message for r in d.reasons if r.code == "CANDIDATE_CAVEAT").lower()
    for phrase in ("tarihsel gözlem", "örnek küçük", "belirsizlik var"):
        assert phrase in text


def test_non_candidate_labels_do_not_need_the_note():
    assert "CANDIDATE_CAVEAT" not in decide([weekday_env()]).reason_codes


def test_hit_rate_standard_error_is_info_not_a_rule():
    d = decide(good_cu())
    se = d.scenarios[0].check("h5.hit_rate_se_pp")
    assert se.info is True and se.ok is None
    assert se.actual == pytest.approx(round(100 * math.sqrt(0.6 * 0.4 / 40), 4))
    # SE ne kadar büyük olursa olsun etiket değişmez: n=20 (SE büyür), hâlâ aday
    d2 = decide([rank_env(blocks=[block(h, n=20) for h in (5, 10, 20)]), backtest_env()])
    assert d2.label == CU and d2.scenarios[0].check("h5.hit_rate_se_pp").actual > se.actual


def test_standard_error_is_none_when_not_computable():
    d = decide([reversal_env(n_detected=0, event_date=None, blocks=[block(1, n=0, hit=None, cost=None, is_=None, oos=None, flag=None)])])
    assert d.scenarios[0].check("h1.hit_rate_se_pp").actual is None


def test_every_rule_check_is_traceable_to_a_source_value():
    d = decide(good_cu())
    s = d.scenarios[0]
    rule_checks = [c for c in s.checks if not c.info]
    assert rule_checks
    for c in rule_checks:
        assert c.tool and c.input_hash and c.path, c.id
    assert {c.tool for c in rule_checks} <= {"rank_sector_relative_strength", "run_backtest"}


# =============================== determinizm ve serileştirme ===============================
def test_decision_is_deterministic_and_json_serialisable():
    envs = good_cu()
    a = decide(envs, question="THYAO'yu alayım mı?").to_dict()
    b = decide(envs, question="THYAO'yu alayım mı?").to_dict()
    assert a == b
    assert json.loads(json.dumps(a, ensure_ascii=False))["label"] == "WATCH"


def test_policy_does_not_mutate_its_inputs():
    envs = good_cu()
    snapshot = json.dumps(envs, sort_keys=True)
    decide(envs, question="alayım mı?")
    assert json.dumps(envs, sort_keys=True) == snapshot


# =============================== eylem koruması entegrasyonu ===============================
def test_guard_catches_a_model_label_that_differs_from_the_policy():
    from harness.action_guard import check_final_output

    d = decide([rank_env(), backtest_env(flag=True)])           # politika: REJECT_SIGNAL
    assert d.label == A.REJECT_SIGNAL
    text = "Geçmiş doğrulama başarısız.\nEYLEM: POTENTIAL_CATCH_UP_CANDIDATE"
    rep = check_final_output(text, required_action=d.label)
    assert [v.code for v in rep.violations] == ["ACTION_MISMATCH_REQUIRED"]
    assert check_final_output("Geçmiş doğrulama başarısız.\nEYLEM: REJECT_SIGNAL", required_action=d.label).ok


# =============================== GERÇEK retail örneği (as_of 2026-09-10) ===============================
def test_real_retail_without_split_date_is_rejected(retail_rank):
    """MAVI laggard (-3,2452 pp), sektör WEAK (-3,66 pp), isabet bazın altında; OOS yok. Kapı: PASS_WITH_WARNINGS varsayımı."""
    d = decide([retail_rank], question="Perakende sektöründe en çok geride kalan hisse hangisi?")
    s = d.scenarios[0]
    assert d.label == A.REJECT_SIGNAL and s.rule_id == "C4_REJECT_HISTORY" and s.subject == "MAVI"
    assert s.check("peer_group_size").actual == 3 and s.check("peer_group_size").ok
    assert s.check("lag_score_pp").actual == pytest.approx(-3.2452)
    assert s.check("subject_is_laggard").ok is True
    assert s.check("sector_strength").actual == "WEAK" and s.check("sector_strength").ok is False
    assert [s.check(f"h{h}.n_events_complete").actual for h in (5, 10, 20)] == [43, 43, 43]
    assert s.check("h5.hit_minus_baseline_pp").actual == pytest.approx(46.5116 - 49.6742, abs=1e-3)
    assert s.check("h10.hit_minus_baseline_pp").actual == pytest.approx(48.8372 - 50.5556, abs=1e-3)
    assert s.check("h20.hit_minus_baseline_pp").actual == pytest.approx(48.8372 - 48.7179, abs=1e-3)
    assert s.check("h20.cost_adjusted_mean_full").actual == pytest.approx(0.6596) and s.check("h5.cost_adjusted_mean_full").ok is False
    assert s.check("h5.oos_degradation_flag").actual is None          # split_date yok => OOS değerlendirilmedi
    assert "OOS_VALIDATION_MISSING" in d.reason_codes


def test_real_retail_with_split_date_has_oos_degradation(retail_rank_split):
    d = decide([retail_rank_split])
    s = d.scenarios[0]
    assert d.label == A.REJECT_SIGNAL and s.rule_id == "C4_REJECT_HISTORY"
    assert s.check("h20.oos_degradation_flag").actual is True and s.check("h5.oos_degradation_flag").actual is False
    assert s.check("h5.oos_cost_adjusted_mean").actual == pytest.approx(-1.3434)
    assert s.check("h10.oos_cost_adjusted_mean").actual == pytest.approx(-2.0882)
    assert s.check("h20.oos_cost_adjusted_mean").actual == pytest.approx(-0.8768)
    assert [s.check(f"h{h}.oos_n").actual for h in (5, 10, 20)] == [10, 10, 10]
    assert "OOS_VALIDATION_MISSING" not in d.reason_codes


def test_real_retail_is_rejected_even_when_the_gate_is_investigate(retail_rank):
    assert decide([retail_rank], gate="INVESTIGATE").label == A.REJECT_SIGNAL      # G3 yalnızca adayları düşürür


def test_real_retail_advice_question_does_not_turn_reject_into_watch(retail_rank):
    assert decide([retail_rank], question="MAVI'yi alayım mı?").label == A.REJECT_SIGNAL


@pytest.mark.skipif(not (REPO / "tools" / "check_data_quality.py").exists(),
                    reason="tools/check_data_quality.py henüz yok (Bilgisayar 1). Gelince bu test retail örneğini GERÇEK kapıyla koşar.")
def test_real_retail_with_the_real_gate_tool(retail_rank, retail_rank_split):
    """TODO (kapı aracı gelince): kapıyı gerçek araçla çalıştır; PASS/PASS_WITH_WARNINGS ise etiket REJECT_SIGNAL kalmalı,
    HARD_BLOCK/ANALYSIS_UNSAFE ise ANALYSIS_UNSAFE, INVESTIGATE ise yine REJECT_SIGNAL (G3 yalnızca adayları düşürür)."""
    from tools import check_data_quality

    gate_env = check_data_quality.run({"tickers": ["BIMAS", "MAVI", "MGROS"], "end": "2026-09-10", "as_of": "2026-09-10"})
    assert gate_env["status"] == "OK"
    gate = gate_env["results"]["gate_status"]
    expected = A.ANALYSIS_UNSAFE if gate in ("HARD_BLOCK", "ANALYSIS_UNSAFE") else A.REJECT_SIGNAL
    for env in (retail_rank, retail_rank_split):
        assert decide_label(gate_status=gate, envelopes=[env, gate_env]).label == expected


# =============================== oturum yardımcısı ve soru kalıpları ===============================
def _session(question, profile="B"):
    from harness.session import HarnessSession

    return HarnessSession.from_question(question, profile=profile)


def _gate_env():
    from harness.mock_tools import run_mock_tool
    from schemas.enums import ToolName
    from schemas.examples import example_params

    return run_mock_tool(ToolName.CHECK_DATA_QUALITY, example_params(ToolName.CHECK_DATA_QUALITY))


def test_decide_session_reads_gate_envelopes_and_the_single_question_ticker():
    s = _session("Analiz tarihi: 10.09.2026\nMAVI geride kalan mı, POTENTIAL_CATCH_UP_CANDIDATE olabilir mi?")
    assert s.question_tickers == ["MAVI"]
    for e in good_cu():
        s.store.add(e, actor="model")
    from harness.label_policy import decide_session
    assert decide_session(s).label == A.INVESTIGATE           # kapı zarfı yok => G2
    s.store.add(_gate_env(), actor="harness")                  # mock kapı: PASS_WITH_WARNINGS
    d = decide_session(s)
    assert d.label == CU and d.gate_status == "PASS_WITH_WARNINGS" and d.scenarios[0].subject == "MAVI"


def test_decide_session_without_a_single_ticker_uses_the_most_lagging_stock():
    from harness.label_policy import decide_session

    s = _session("Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) en çok geride kalan hisse hangisi?")
    assert len(s.question_tickers) == 3
    for e in good_cu():
        s.store.add(e, actor="model")
    s.store.add(_gate_env(), actor="harness")
    assert decide_session(s).scenarios[0].subject == "MAVI"


def test_decide_session_uses_only_the_locked_bundle_sources():
    from harness.label_policy import decide_session

    s = _session("Analiz tarihi: 10.09.2026\nMAVI için durum nedir?", profile="D")
    rank, bt, wk = rank_env(), backtest_env(), weekday_env("UNSTABLE", ["OOS_SIGN_FLIP"])
    for e in (rank, bt, wk):
        s.store.add(e, actor="model")
    s.store.add(_gate_env(), actor="harness")
    s.bundle.build({"as_of": "2026-09-10", "analysis_id": s.analysis_id,
                    "source_input_hashes": [rank["input_hash"], bt["input_hash"]]})
    d = decide_session(s)
    assert d.label == CU and {x.scenario for x in d.scenarios} == {"CATCH_UP"}      # wk pakette değil: etiketi etkilemez
    assert decide_label(gate_status="PASS", envelopes=[rank, bt, wk]).label == A.REJECT_SIGNAL   # pakette olsaydı


def test_question_advice_lexicon_examples_all_trigger_the_intent():
    lex = json.loads((REPO / "harness" / "lexicons" / "advice_phrases.json").read_text(encoding="utf-8"))
    for entry in lex["question_advice"]:
        assert entry["examples"]
        for q in entry["examples"]:
            assert detect_advice_intent(q)[0] is True, q
