"""Catch-up özne sınırı (C5S_SUBJECT_CAP): havuzlu kanıt ANA kalır; özne bazlı (per_ticker) veri yalnızca TUTARLILIK denetimidir.

Kural (docs/harness_design.md 11.2): aday etiket (C5) oluştuktan ve G3 uygulandıktan SONRA, özne için
  * ufuk bazında EN KÜÇÜK tamamlanmış olay sayısı < MIN_OOS_EVENTS (5)  -> WATCH  (SUBJECT_FEW_EVENTS)
  * özne kendi isabeti kendi taban isabetinin altında olan ufuk sayısı ÇOĞUNLUKTA (below*2 > n) -> WATCH  (SUBJECT_BELOW_BASELINE)
  * per_ticker yok / özne yok (1.1.0 zarfı)  -> WATCH  (SUBJECT_BREAKDOWN_MISSING; doğrulanamadı)
Her durumda `SUBJECT_EVENT_COUNT` bilgisi reasons'ta yazılır. Aday olmayan yollar (C2, C3, C4, C6, G3) DEĞİŞMEZ.
Eşik yeni sabit değildir: mevcut `MIN_OOS_EVENTS`.
"""
from __future__ import annotations

import copy

import pytest

import config.settings as cfg
from harness.label_policy import RULE_IDS, decide_label
from policy_builders import backtest_env, rank_env
from schemas.enums import AllowedAction as A

CU = A.POTENTIAL_CATCH_UP_CANDIDATE
GATE_OK = "PASS_WITH_WARNINGS"


def decide(envs, *, gate=GATE_OK, subject=None, **kw):
    return decide_label(gate_status=gate, envelopes=envs, question="", subject=subject, **kw)


def codes(d, i=0):
    return [r.code for r in d.scenarios[i].reasons]


def reason(d, code, i=0):
    return next(r.message for r in d.scenarios[i].reasons if r.code == code)


def with_subject_stats(env, ticker, horizons):
    """Öznenin per_ticker bloklarını (n_events_complete, hit, baseline_hit) üçlüleriyle ayarlar (zarfı yerinde değiştirir)."""
    row = next(t for t in env["results"]["per_ticker"] if t["ticker"] == ticker)
    assert len(row["per_horizon"]) == len(horizons)
    for ph, (n, hit, base) in zip(row["per_horizon"], horizons):
        ph["block"]["full"]["n_events_complete"] = n
        ph["block"]["full"]["hit_rate_pct"] = hit
        ph["block"]["baseline"]["hit_rate_pct"] = base
    return env


def cu_envs(horizons, *, subject="MAVI", **kw):
    return [with_subject_stats(rank_env(subject=subject, **kw), subject, horizons), backtest_env()]


OK = [(9, 60.0, 50.0), (9, 60.0, 50.0), (9, 60.0, 50.0)]


def test_rule_id_is_registered_and_documented_in_the_design_doc():
    assert "C5S_SUBJECT_CAP" in RULE_IDS


# =============================== temel: özne tutarlıysa aday kalır ===============================
def test_consistent_subject_keeps_the_candidate_and_still_reports_the_subject_count():
    d = decide(cu_envs(OK), subject="MAVI")
    s = d.scenarios[0]
    assert d.label == CU and s.rule_id == "C5_CANDIDATE" and "CANDIDATE_CAVEAT" in codes(d)
    assert not {"SUBJECT_FEW_EVENTS", "SUBJECT_BELOW_BASELINE", "SUBJECT_BREAKDOWN_MISSING"} & set(codes(d))
    assert "SUBJECT_EVENT_COUNT" in codes(d)                       # her durumda yazılır
    assert s.check("subject_min_events_complete").ok and s.check("subject_horizons_below_baseline").ok


# =============================== olay sayısı (ufuk bazında en küçük tamamlanmış) ===============================
@pytest.mark.parametrize("n,expected", [(4, A.WATCH), (5, CU)])
def test_subject_event_floor_is_min_oos_events_at_the_boundary(n, expected):
    d = decide(cu_envs([(9, 60.0, 50.0), (n, 60.0, 50.0), (9, 60.0, 50.0)]), subject="MAVI")
    assert d.label == expected
    if expected == A.WATCH:
        s = d.scenarios[0]
        assert s.rule_id == "C5S_SUBJECT_CAP" and s.raw_label == CU and s.base_rule_id == "C5_CANDIDATE"
        assert "SUBJECT_FEW_EVENTS" in codes(d) and "CANDIDATE_CAVEAT" in codes(d)      # ham etiket aday: uyarı notu kalır
        assert s.check("subject_min_events_complete").actual == n and s.check("subject_min_events_complete").ok is False


def test_the_floor_uses_the_smallest_horizon_not_the_independent_event_count():
    """n_independent_events büyük olsa bile en uzun ufukta tamamlanmış olay azsa özne sınırı devreye girer."""
    envs = cu_envs([(30, 60.0, 50.0), (30, 60.0, 50.0), (3, 60.0, 50.0)])
    row = next(t for t in envs[0]["results"]["per_ticker"] if t["ticker"] == "MAVI")
    row["n_independent_events"] = 33                                 # ham/bağımsız büyük, tamamlanmış küçük
    d = decide(envs, subject="MAVI")
    assert d.label == A.WATCH and d.scenarios[0].check("subject_min_events_complete").actual == 3
    assert "33" in reason(d, "SUBJECT_EVENT_COUNT")                  # bağımsız sayı reasons'ta yine yazılır


def test_the_floor_follows_config_at_call_time(monkeypatch):
    envs = cu_envs([(6, 60.0, 50.0)] * 3)
    assert decide(envs, subject="MAVI").label == CU
    monkeypatch.setattr(cfg, "MIN_OOS_EVENTS", 7)
    assert decide(envs, subject="MAVI").label == A.WATCH


# =============================== özne kendi geçmişinde bazın altında (çoğunluk) ===============================
@pytest.mark.parametrize("below,expected", [(0, CU), (1, CU), (2, A.WATCH), (3, A.WATCH)])
def test_majority_of_horizons_below_the_subjects_own_baseline_caps_to_watch(below, expected):
    hz = [(9, 40.0 if i < below else 60.0, 50.0) for i in range(3)]
    d = decide(cu_envs(hz), subject="MAVI")
    assert d.label == expected
    s = d.scenarios[0]
    assert s.check("subject_horizons_below_baseline").actual == below
    assert ("SUBJECT_BELOW_BASELINE" in codes(d)) == (expected == A.WATCH)
    if expected == A.WATCH:
        assert s.rule_id == "C5S_SUBJECT_CAP"


def test_equal_hit_rate_is_not_below_baseline_and_missing_rates_are_not_counted_as_below():
    assert decide(cu_envs([(9, 50.0, 50.0)] * 3), subject="MAVI").label == CU
    assert decide(cu_envs([(9, None, 50.0)] * 3), subject="MAVI").label == CU


# =============================== per_ticker yok => doğrulanamadı => WATCH ===============================
def test_missing_per_ticker_caps_the_candidate_to_watch():
    envs = [rank_env(subject="MAVI"), backtest_env()]
    envs[0]["results"]["per_ticker"] = []                            # 1.1.0 zarfı
    d = decide(envs, subject="MAVI")
    assert d.label == A.WATCH and d.scenarios[0].rule_id == "C5S_SUBJECT_CAP" and "SUBJECT_BREAKDOWN_MISSING" in codes(d)
    assert "SUBJECT_EVENT_COUNT" not in codes(d)                     # veri yok: sayı da yok


def test_subject_absent_from_per_ticker_is_treated_as_missing():
    envs = [rank_env(subject="MAVI"), backtest_env()]
    envs[0]["results"]["per_ticker"] = [t for t in envs[0]["results"]["per_ticker"] if t["ticker"] != "MAVI"]
    assert decide(envs, subject="MAVI").label == A.WATCH


# =============================== sıra: G3 önce, aday olmayan yollar değişmez ===============================
def test_gate_investigate_wins_over_the_subject_cap_so_the_label_is_never_less_cautious():
    d = decide(cu_envs([(2, 40.0, 50.0)] * 3), gate="INVESTIGATE", subject="MAVI")
    s = d.scenarios[0]
    assert d.label == A.INVESTIGATE and s.rule_id == "G3_GATE_INVESTIGATE"
    assert not {"SUBJECT_FEW_EVENTS", "SUBJECT_BELOW_BASELINE"} & set(codes(d))        # uygulanmayan sınır gerekçe yazmaz
    assert "SUBJECT_EVENT_COUNT" in codes(d)


def test_non_candidate_paths_are_unchanged_even_with_a_weak_subject():
    weak = [(2, 40.0, 50.0)] * 3
    # C2: özne geride değil
    d = decide([with_subject_stats(rank_env(subject="MAVI", laggard=False), "MAVI", weak), backtest_env()], subject="MAVI")
    assert d.label == A.HOLD and d.scenarios[0].rule_id == "C2_NOT_LAGGARD"
    # C4: havuzlu geçmiş başarısız
    envs = cu_envs(weak)
    d = decide([rank_env(subject="MAVI", blocks=[__import__("policy_builders").block(h, hit=45.0) for h in (5, 10, 20)]), backtest_env()],
               subject="MAVI")
    assert d.label == A.REJECT_SIGNAL and d.scenarios[0].rule_id == "C4_REJECT_HISTORY"
    # C7: sektör STRONG değil => WATCH zaten (özne sınırı kural kimliğini değiştirmez)
    d = decide([with_subject_stats(rank_env(subject="MAVI", strength="NEUTRAL"), "MAVI", weak), backtest_env()], subject="MAVI")
    assert d.label == A.WATCH and d.scenarios[0].rule_id == "C7_WATCH"
    assert envs  # (cu_envs yardımcısı kullanıldı)


def test_subject_count_reason_is_written_on_every_path_that_has_a_subject_row():
    d_hold = decide([rank_env(subject="MAVI", laggard=False), backtest_env()], subject="MAVI")
    assert d_hold.label == A.HOLD and "SUBJECT_EVENT_COUNT" in codes(d_hold)
    msg = reason(decide(cu_envs(OK), subject="MAVI"), "SUBJECT_EVENT_COUNT")
    assert "MAVI" in msg and "bağımsız olay" in msg and "ham" in msg


def test_decision_is_deterministic_and_does_not_mutate_the_input():
    envs = cu_envs([(3, 40.0, 50.0)] * 3)
    snap = copy.deepcopy(envs)
    a, b = decide(envs, subject="MAVI"), decide(envs, subject="MAVI")
    assert a.to_dict() == b.to_dict() and envs == snap


# =============================== GERÇEK retail (as_of 2026-09-10): üç özne ===============================
@pytest.mark.parametrize("subject,label,rule", [
    ("BIMAS", A.HOLD, "C2_NOT_LAGGARD"), ("MGROS", A.HOLD, "C2_NOT_LAGGARD"), ("MAVI", A.REJECT_SIGNAL, "C4_REJECT_HISTORY"),
])
def test_real_retail_labels_are_unchanged_for_each_subject(retail_rank_split, subject, label, rule):
    d = decide([retail_rank_split], subject=subject)
    assert d.label == label and d.scenarios[0].rule_id == rule
    row = next(t for t in retail_rank_split["results"]["per_ticker"] if t["ticker"] == subject)
    msg = reason(d, "SUBJECT_EVENT_COUNT")                           # sayılar zarftan aynen
    assert subject in msg and str(row["n_independent_events"]) in msg and str(row["n_raw_laggard_observations"]) in msg


@pytest.mark.parametrize("subject,expected,why", [
    ("BIMAS", CU, None),                         # kendi isabeti 3/3 ufukta bazın ÜSTÜNDE
    ("MAVI", CU, None),                          # 1/3 ufukta altında (5g): çoğunluk değil
    ("MGROS", A.WATCH, "SUBJECT_BELOW_BASELINE"),  # 10g ve 20g'de altında: 2/3
])
def test_real_per_ticker_stats_under_the_hypothetical_candidate_premise(retail_rank_split, subject, expected, why):
    """VARSAYIM (gerçek değil): özne geride, havuzlu doğrulama ve backtest geçmiş, sektör STRONG. Özne sayıları GERÇEK retail zarfından."""
    real = next(t for t in retail_rank_split["results"]["per_ticker"] if t["ticker"] == subject)
    env = rank_env(subject="MAVI")                                   # MAVI satırı geride kalan; özne başka hisseyse adları takas et
    if subject != "MAVI":
        swap = {"MAVI": subject, subject: "MAVI"}
        for r in env["results"]["ranking"] + env["results"]["per_ticker"]:
            r["ticker"] = swap.get(r["ticker"], r["ticker"])
    env["results"]["per_ticker"] = [{**copy.deepcopy(real), "is_laggard": True} if t["ticker"] == subject else t
                                    for t in env["results"]["per_ticker"]]
    d = decide([env, backtest_env()], subject=subject)
    assert d.label == expected, (subject, d.scenarios[0].rule_id, codes(d))
    assert d.scenarios[0].check("subject_min_events_complete").ok is True     # gerçek tamamlanmış sayılar (9 / 20 / 14) >= 5
    assert (why in codes(d)) if why else "SUBJECT_BELOW_BASELINE" not in codes(d)
