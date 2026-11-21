"""rank_sector_relative_strength aracı testleri.

(A) Saf yardımcılar: kendisi hariç medyan, bağımsızlaştırma (cooldown).
(B) Sentetik snapshot, ELLE hesaplanabilir senaryolar:
    * jump  : 20 günde +9 / +7 / +1 (XU100 +4) -> medyan 7, lag +2 / 0 / -6
    * a_case: B +%6, A(laggard) +%4, C +%1 -> kendisi DAHİL medyanla excess 0 (yanlış pozitif),
              kendisi HARİÇ medyanla +0,5 (başarı)
    * step  : tek hisse 20 gün üst üste geride -> ham 20 gözlem, cooldown sonrası olay sayısı
(C) Sızıntı (as_of sonrası şok), ufku dolmamış olay, determinizm, uyarılar, hata zarfları.
(D) Gerçek v2 snapshot, retail grubu, as_of = 2026-09-10.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from schemas.results import RankSectorRelativeStrengthResult
from scripts.download_prices import CANONICAL_COLUMNS
from tests.conftest import make_snapshot
from tools import rank_sector_relative_strength as tool
from tools.common import load_snapshot

VERSION = "snap_2026-11-20_v2"
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")


# =====================================================================================================
# (A) saf yardımcılar
# =====================================================================================================
def test_leave_one_out_median_user_example():
    """B +6, A +4, C +1: A için diğerlerinin medyanı (6,1) = 3,5; kendisi dahil medyan 4 olurdu."""
    m = np.array([[6.0, 4.0, 1.0]])  # sütunlar: B, A, C
    loo = tool.leave_one_out_median(m)
    assert loo.tolist() == [[2.5, 3.5, 5.0]]
    assert float(np.median(m[0])) == 4.0  # dahil medyan: A için excess 0 -> yanlış pozitif olurdu
    assert 4.0 - loo[0, 1] == pytest.approx(0.5)


def test_leave_one_out_median_two_members_is_the_other_member():
    m = np.array([[3.0, -1.0], [0.5, 2.0]])
    assert tool.leave_one_out_median(m).tolist() == [[-1.0, 3.0], [2.0, 0.5]]


def test_independent_events_cooldown_single_stock():
    mask = np.zeros((50, 1), bool)
    mask[5:, 0] = True  # t=5'ten sonra hep geride
    assert tool.independent_events(mask, 5, 49, cooldown=20) == [(5, 0), (25, 0), (45, 0)]
    assert [t for t, _ in tool.independent_events(mask, 5, 49, cooldown=5)] == list(range(5, 50, 5))


def test_independent_events_cooldown_counts_from_accepted_event_not_from_gaps():
    """Aradaki gün laggard değilse bile cooldown KABUL EDİLEN olaydan sayılır: 5 -> 10 elenir, 26 kabul (>= 5+20)."""
    mask = np.zeros((40, 1), bool)
    mask[[5, 10, 24, 26], 0] = True
    assert tool.independent_events(mask, 0, 39, cooldown=20) == [(5, 0), (26, 0)]


def test_independent_events_stocks_are_independent_of_each_other_and_sorted():
    mask = np.zeros((40, 2), bool)
    mask[5:, 0] = True
    mask[7, 1] = True
    assert tool.independent_events(mask, 5, 39, cooldown=20) == [(5, 0), (7, 1), (25, 0)]


def test_independent_events_respects_first_and_last_t():
    mask = np.ones((30, 1), bool)
    assert [t for t, _ in tool.independent_events(mask, 10, 20, cooldown=5)] == [10, 15, 20]


# =====================================================================================================
# (B) sentetik snapshot
# =====================================================================================================
N = 80
DATES = pd.bdate_range("2024-01-01", periods=N)  # 2024-01-01 Pazartesi
FLAT = np.full(N, 100.0)


def d(i: int) -> str:
    return DATES[i].date().isoformat()


def _frame(ticker: str, closes, dates) -> pd.DataFrame:
    c = np.asarray(closes, float)
    return pd.DataFrame({"ticker": ticker, "date": dates, "open": c, "high": c, "low": c, "close": c, "adj_close": c,
                         "volume": 1000.0, "dividends": 0.0, "stock_splits": 0.0})[CANONICAL_COLUMNS]


def _snap(root, closes: dict, xu, dates=DATES, jumps=None, drop=(), shock_after: int | None = None):
    closes = {t: np.asarray(c, float).copy() for t, c in closes.items()}
    xu = np.asarray(xu, float).copy()
    if shock_after is not None:  # as_of SONRASI satırlara aşırı değerler
        for c in (*closes.values(), xu):
            c[shock_after + 1:] *= 1e6
    stocks = pd.concat([_frame(t, c, dates) for t, c in closes.items()], ignore_index=True)
    for t, i in drop:
        stocks = stocks[~((stocks["ticker"] == t) & (stocks["date"] == dates[i]))]
    index = _frame("XU100", xu, dates).drop(columns=["ticker"])
    make_snapshot(root, stocks.reset_index(drop=True), index, version=VERSION, jumps=jumps)
    return root


def step(final: float, at: int = 40) -> np.ndarray:
    a = FLAT.copy()
    a[at:] = final
    return a


def jump_scenario():
    """t=40'ta tek adımda 109 / 107 / 101 (XU100 104); as_of = 59 -> 20 günlük getiri +9 / +7 / +1 / XU100 +4."""
    return {"BIMAS": step(109), "MGROS": step(107), "MAVI": step(101)}, step(104)


def a_case_scenario():
    """MAVI = A (laggard). t=40'ta 100 -> 90 (geride); sonraki 5 günde MAVI +4% (90 -> 93,6), BIMAS +6%, MGROS +1%."""
    k = np.arange(N) - 40
    ramp = np.clip(k, 0, 5) / 5
    return {"MAVI": np.where(k < 0, 100.0, 90.0 + 3.6 * ramp), "BIMAS": 100.0 + 6.0 * ramp,
            "MGROS": 100.0 + 1.0 * ramp}, FLAT


def step_scenario():
    """MAVI t=40'ta 100 -> 90 ve orada kalır; 20 gün (t=40..59) boyunca 20 günlük getirisi -10 (diğerleri 0)."""
    return {"MAVI": step(90), "BIMAS": FLAT, "MGROS": FLAT}, FLAT


def walk(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))


RW_N = 1500
RW_DATES = pd.bdate_range("2024-01-01", periods=RW_N)


def rw_scenario():
    return {"BIMAS": walk(RW_N, 1), "MGROS": walk(RW_N, 2), "MAVI": walk(RW_N, 3)}, walk(RW_N, 4)


def call(root, as_of, group="retail", **over):
    params = {"sector": group, "as_of": as_of, **over}
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> RankSectorRelativeStrengthResult:
    assert env["status"] == "OK", env
    return RankSectorRelativeStrengthResult.model_validate(env["results"])


def block(r: RankSectorRelativeStrengthResult, h: int):
    return next(c for c in r.historical_catch_up if c.block.horizon == h)


def warn(env, code: str) -> list[str]:
    return [w for w in env["warnings"] if w.startswith(code + ":")]


@pytest.fixture(scope="module")
def roots(tmp_path_factory):
    base = tmp_path_factory.mktemp("rank")
    out = {}
    for name, (sc, xu) in {"jump": jump_scenario(), "a_case": a_case_scenario(), "step": step_scenario()}.items():
        out[name] = _snap(base / name, sc, xu)
    sc, xu = a_case_scenario()
    out["a_case_shock"] = _snap(base / "a_case_shock", sc, xu, shock_after=45)
    sc, xu = jump_scenario()
    out["jump_shock"] = _snap(base / "jump_shock", sc, xu, shock_after=59)
    sc, xu = rw_scenario()
    out["rw"] = _snap(base / "rw", sc, xu, RW_DATES)
    out["rw_shock"] = _snap(base / "rw_shock", sc, xu, RW_DATES, shock_after=1400)
    return out


RW_AS_OF = RW_DATES[1400].date().isoformat()


# --- 1. elle hesaplanabilir 3 hisselik grup ------------------------------------------------------------
def test_hand_computed_three_stock_group(roots):
    env = call(roots["jump"], d(59))
    validate_envelope(env)
    r = res(env)
    assert env["tool"] == "rank_sector_relative_strength" and env["status"] == "OK"
    assert (r.sector.value, r.peer_group_size, r.insufficient_peers, r.horizon) == ("retail", 3, False, 20)
    assert (r.window_start, r.window_end) == (DATES[40].date(), DATES[59].date())
    assert r.xu100_return_pct == 4.0 and r.sector_median_return_pct == 7.0 and r.sector_median_vs_xu100_pp == 3.0
    assert r.sector_strength.value == "STRONG"  # +3 >= +2
    assert (r.strength_thresholds.strong_min_vs_xu100_pp, r.strength_thresholds.weak_max_vs_xu100_pp) == (2.0, -2.0)
    assert [(x.rank, x.ticker, x.return_pct, x.lag_score_pp, x.return_vs_xu100_pp, x.is_laggard, x.is_leader)
            for x in r.ranking] == [
        (1, "BIMAS", 9.0, 2.0, 5.0, False, False),
        (2, "MGROS", 7.0, 0.0, 3.0, False, False),
        (3, "MAVI", 1.0, -6.0, -3.0, True, False),
    ]
    bd = r.benchmark_definition
    assert (bd.type, bd.includes_subject_stock, bd.price_field, bd.return_type, bd.peer_group) == (
        "peer_median", True, "adj_close", "simple", "retail")
    assert bd.members == ["BIMAS", "MAVI", "MGROS"]
    assert r.structural_vs_temporary is None
    assert r.cost_model.round_trip_cost_pct == 0.5


def test_lag_threshold_boundary_is_inclusive_and_changes_flags(roots):
    at = lambda thr: [(x.ticker, x.is_laggard, x.is_leader) for x in res(call(roots["jump"], d(59), lag_threshold_pp=thr)).ranking]
    assert at(6.0)[2] == ("MAVI", True, False)          # lag -6 <= -6: sınır dahil
    assert at(6.5)[2] == ("MAVI", False, False)
    assert at(2.0)[0] == ("BIMAS", False, True)         # lag +2 >= +2: sınır dahil


def test_rank_ties_are_broken_alphabetically(tmp_path):
    same = step(110)
    _snap(tmp_path, {"BIMAS": same, "MGROS": same, "MAVI": same}, FLAT)
    r = res(call(tmp_path, d(59)))
    assert [(x.rank, x.ticker, x.lag_score_pp) for x in r.ranking] == [(1, "BIMAS", 0.0), (2, "MAVI", 0.0), (3, "MGROS", 0.0)]


def test_as_of_on_non_trading_day_uses_previous_trading_day(roots):
    sat = (DATES[59] + pd.Timedelta(days=1)).date().isoformat()
    r = res(call(roots["jump"], sat))
    assert r.window_end == DATES[59].date()


def test_missing_member_day_is_dropped_from_common_panel_with_warning(tmp_path):
    """MGROS t=50'de yok (diğerlerinde var): ortak panelden düşer, doldurulmaz; pencere bir takvim günü geriye kayar."""
    sc, xu = jump_scenario()
    _snap(tmp_path, sc, xu, drop=[("MGROS", 50)])
    env = call(tmp_path, d(59))
    r = res(env)
    assert r.window_start == DATES[39].date() and r.window_end == DATES[59].date()
    assert (r.sector_median_return_pct, r.ranking[2].return_pct) == (7.0, 1.0)
    w = warn(env, "MISSING_TRADING_DAYS")
    assert len(w) == 1 and d(50) in w[0]


def test_price_jump_warning_only_for_rows_up_to_as_of(tmp_path):
    sc, xu = jump_scenario()
    jumps = [{"ticker": "MAVI", "date": d(50), "return_pct": 15.0, "prev_date": d(49)},
             {"ticker": "MAVI", "date": d(70), "return_pct": 25.0, "prev_date": d(69)}]
    _snap(tmp_path, sc, xu, jumps=jumps)
    w = warn(call(tmp_path, d(59)), "PRICE_JUMP_OVER_LIMIT")
    assert len(w) == 1 and d(50) in w[0] and d(70) not in w[0]


# --- 2. sızıntı --------------------------------------------------------------------------------------
def test_future_shock_after_as_of_changes_nothing(roots):
    for plain, shock, as_of in (("jump", "jump_shock", d(59)), ("a_case", "a_case_shock", d(45)),
                                ("rw", "rw_shock", RW_AS_OF)):
        a, b = call(roots[plain], as_of), call(roots[shock], as_of)
        assert a["results"] == b["results"], plain
        assert a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"], plain
        assert (a["n_events"], a["n_excluded_incomplete_horizon"]) == (b["n_events"], b["n_excluded_incomplete_horizon"])


def test_snapshot_physically_truncated_at_as_of_gives_identical_results(roots, tmp_path):
    """Veri t=45'te FİZİKSEL olarak kesilince sonuç, tam snapshot + as_of=45 ile birebir aynı."""
    sc, xu = a_case_scenario()
    cut = DATES[:46]
    _snap(tmp_path, {t: c[:46] for t, c in sc.items()}, xu[:46], dates=cut)
    a, b = call(roots["a_case"], d(45)), call(tmp_path, d(45))
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]
    assert res(a).window_end == DATES[45].date()


# --- 3. ufku dolmamış olaylar + kullanıcı örneği (kendisi hariç medyan) -----------------------------------
def test_leave_one_out_outcome_user_example_is_a_success_not_a_false_positive(roots):
    """t=40 olayı (MAVI, lag -10): +5 gün sonra MAVI +4, BIMAS +6, MGROS +1.
    Dahil medyan 4 -> excess 0 (yanlış pozitif olurdu); HARİÇ medyan 3,5 -> excess +0,5 (başarı)."""
    env = call(roots["a_case"], d(45), forward_horizons=[5])
    r = res(env)
    b = block(r, 5)
    f = b.block.full
    assert (f.n_events_complete, f.n_success, f.n_false_positive, f.n_excluded_incomplete_horizon) == (1, 1, 0, 1)
    assert (f.hit_rate_pct, f.false_positive_rate_pct, f.mean_return_pct, f.median_return_pct) == (100.0, 0.0, 0.5, 0.5)
    assert f.cost_adjusted_mean_return_pct == 0.0           # 0,5 - tur maliyeti 0,5
    assert b.median_catch_up_size_pp == 0.5
    # t=45 olayı (MAVI yine geride) as_of günü: ufku dolmamış -> dışlandı; zarf en uzun ufuk için aynı sayıları taşır
    assert (env["n_events"], env["n_excluded_incomplete_horizon"]) == (1, 1)
    assert warn(env, "INCOMPLETE_HORIZON_EXCLUDED")


def test_event_whose_horizon_crosses_as_of_is_excluded_not_counted(roots):
    """as_of=44: t=40 olayının +5 günü (45) as_of'u aşar -> hiçbir istatistiğe girmez, yalnızca dışlanan sayısına."""
    env = call(roots["a_case"], d(44), forward_horizons=[5])
    f = block(res(env), 5).block.full
    assert (f.n_events_complete, f.n_success, f.n_false_positive, f.n_excluded_incomplete_horizon) == (0, 0, 0, 1)
    assert (f.hit_rate_pct, f.mean_return_pct, f.median_return_pct, f.cost_adjusted_mean_return_pct) == (None, None, None, None)
    assert block(res(env), 5).median_catch_up_size_pp is None
    assert (env["n_events"], env["n_excluded_incomplete_horizon"]) == (0, 1)
    assert warn(env, "FEW_EVENTS")


def test_jump_scenario_per_horizon_completeness(roots):
    """t=40 olayı: +5 ve +10 gün tamamlandı (45, 50 <= 59); +20 gün (60) as_of'u aşar. Hepsi excess 0 -> yanlış pozitif."""
    env = call(roots["jump"], d(59))
    r = res(env)
    h5, h10, h20 = (block(r, h).block.full for h in (5, 10, 20))
    assert (h5.n_events_complete, h5.n_false_positive, h5.n_excluded_incomplete_horizon) == (1, 1, 0)
    assert (h10.n_events_complete, h10.n_false_positive, h10.n_excluded_incomplete_horizon) == (1, 1, 0)
    assert (h20.n_events_complete, h20.n_excluded_incomplete_horizon, h20.hit_rate_pct) == (0, 1, None)
    assert (env["n_events"], env["n_excluded_incomplete_horizon"]) == (0, 1)


def test_baseline_is_hand_computable(roots):
    """Ufuk 5: uygun gün t=20..54 (35 gün) x 3 hisse = 105 gözlem. Sıçrama t=40'ta; t=35..39 pencereleri sıçramayı içerir:
    kendisi hariç excess BIMAS 9-4=+5, MGROS 7-5=+2, MAVI 1-8=-7 (5 gün). Toplam 0 -> ort 0; pozitif 10/105 = %9,5238."""
    b = block(res(call(roots["jump"], d(59))), 5).block.baseline
    assert (b.n_obs, b.mean_return_pct, b.median_return_pct, b.hit_rate_pct) == (105, 0.0, 0.0, 9.5238)


def test_baseline_hit_rate_is_about_fifty_percent_on_exchangeable_walks(roots):
    """Kendisi HARİÇ medyanla, değiştirilebilir (iid) hisselerde baz isabet oranı ~%50 olmalı (dahil medyanla ~%33 olurdu)."""
    r = res(call(roots["rw"], RW_AS_OF, forward_horizons=[5, 10, 20]))
    for h in (5, 10, 20):
        b = block(r, h).block.baseline
        assert b.n_obs > 3000
        assert 45.0 <= b.hit_rate_pct <= 55.0, (h, b.hit_rate_pct)
        assert abs(b.mean_return_pct) < 0.5


# --- 4. örtüşme / cooldown ---------------------------------------------------------------------------
def test_cooldown_equals_longest_forward_horizon(roots):
    """MAVI 20 gün (t=40..59) geride. fh=[5,10,20] -> cooldown 20 -> 1 olay; fh=[5] -> cooldown 5 -> 4 olay (40,45,50,55)."""
    long_ = call(roots["step"], d(70), forward_horizons=[5, 10, 20])
    short = call(roots["step"], d(70), forward_horizons=[5])
    assert block(res(long_), 5).block.full.n_events_complete == 1
    assert (short["n_events"], short["n_excluded_incomplete_horizon"]) == (4, 0)
    (hw,) = warn(long_, "HISTORICAL_ONLY")
    assert "BIMAS 0, MAVI 20, MGROS 0 (toplam 20)" in hw and "cooldown=20" in hw
    assert "BIMAS 0, MAVI 1, MGROS 0 (toplam 1)" in hw
    (hs,) = warn(short, "HISTORICAL_ONLY")
    assert "cooldown=5" in hs and "BIMAS 0, MAVI 4, MGROS 0 (toplam 4)" in hs


def test_raw_plus_independent_counts_and_definitions_are_in_historical_only_warning(roots):
    (w,) = warn(call(roots["a_case"], d(45), forward_horizons=[5]), "HISTORICAL_ONLY")
    assert "tespit: grup medyanı (kendisi dahil); sonuç: kendisi hariç peer medyanı" in w


def test_every_call_carries_multiple_testing_and_historical_warnings(roots):
    env = call(roots["jump"], d(59))
    assert warn(env, "HISTORICAL_ONLY") and warn(env, "MULTIPLE_TESTING_RISK")


# --- 5. küçük gruplar ---------------------------------------------------------------------------------
def test_solo_group_is_ok_with_explicit_warning_and_no_ranking_meaning(tmp_path):
    _snap(tmp_path, {"ASELS": walk(N, 5)}, FLAT)
    env = call(tmp_path, d(59), group="solo_asels")
    validate_envelope(env)
    r = res(env)
    assert env["status"] == "OK" and warn(env, "SOLO_PEER_GROUP")
    assert (r.peer_group_size, r.insufficient_peers) == (1, True)
    assert (r.sector_median_return_pct, r.xu100_return_pct is not None, r.sector_median_vs_xu100_pp, r.sector_strength) == (
        None, True, None, None)
    (row,) = r.ranking
    assert (row.rank, row.ticker, row.lag_score_pp, row.is_laggard, row.is_leader) == (1, "ASELS", 0.0, False, False)
    assert r.historical_catch_up == [] and env["n_events"] is None


def test_two_stock_group_warns_and_lag_scores_mirror(tmp_path):
    _snap(tmp_path, {"THYAO": walk(N, 6), "PGSUS": walk(N, 7)}, walk(N, 8))
    env = call(tmp_path, d(59), group="airlines")
    r = res(env)
    assert warn(env, "SMALL_PEER_GROUP") and not warn(env, "SOLO_PEER_GROUP")
    assert (r.peer_group_size, r.insufficient_peers) == (2, False)
    assert r.ranking[0].lag_score_pp == -r.ranking[1].lag_score_pp


# --- 6. determinizm -----------------------------------------------------------------------------------
def test_determinism_bit_identical(roots):
    a, b = call(roots["rw"], RW_AS_OF), call(roots["rw"], RW_AS_OF)
    assert a == b and a["input_hash"] == b["input_hash"]
    assert a["data_version"] == VERSION and len(a["input_hash"]) == 64


def _negative_zeros(obj) -> list:
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _negative_zeros(v)]
    if isinstance(obj, list):
        return [x for v in obj for x in _negative_zeros(v)]
    return [obj] if isinstance(obj, float) and obj == 0.0 and np.signbit(obj) else []


def test_rounding_helper_never_returns_negative_zero():
    """3 üyede kendisi hariç excess toplamı matematiksel olarak 0: ortalama -1e-17 çıkıp yuvarlanınca -0.0 olabilir (gerçek
    retail verisinde oldu). Zarfa "-0.0" sızmamalı."""
    for tiny in (-1e-17, -0.0, -4e-5):
        v = tool._r(tiny)
        assert v == 0.0 and not np.signbit(v)
    assert tool._r(-0.0001) == -0.0001


def test_no_negative_zero_in_results(roots):
    split = RW_DATES[700].date().isoformat()
    for env in (call(roots["rw"], RW_AS_OF, split_date=split), call(roots["jump"], d(59))):
        assert _negative_zeros(env["results"]) == []


# --- örneklem içi / dışı ------------------------------------------------------------------------------
def test_split_partitions_events_and_sets_degradation_flags(roots):
    split = RW_DATES[700].date().isoformat()
    r = res(call(roots["rw"], RW_AS_OF, split_date=split))
    for c in r.historical_catch_up:
        b = c.block
        assert b.in_sample is not None and b.out_of_sample is not None
        assert b.in_sample.n_events_complete + b.out_of_sample.n_events_complete == b.full.n_events_complete
        assert (b.in_sample.n_excluded_incomplete_horizon + b.out_of_sample.n_excluded_incomplete_horizon
                == b.full.n_excluded_incomplete_horizon)
        assert b.oos_degradation_flag in (True, False)
    no_split = res(call(roots["rw"], RW_AS_OF))
    assert all(c.block.in_sample is None and c.block.oos_degradation_flag is None for c in no_split.historical_catch_up)


def test_small_oos_sample_sets_flag_false_with_warning(roots):
    split = RW_DATES[1390].date().isoformat()  # OOS = son 10 gün: en fazla hisse başına 1 olay
    env = call(roots["rw"], RW_AS_OF, split_date=split)
    r = res(env)
    assert all(c.block.out_of_sample.n_events_complete < 5 for c in r.historical_catch_up)
    assert all(c.block.oos_degradation_flag is False for c in r.historical_catch_up)
    assert warn(env, "OOS_TOO_SMALL")


# --- hata zarfları ---------------------------------------------------------------------------------
def test_analysis_start_after_as_of_is_invalid_params(roots):
    env = call(roots["jump"], d(59), analysis_start="2025-01-01")
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


def test_insufficient_history_is_error_envelope(roots):
    env = call(roots["jump"], d(10))  # 11 satır < horizon + 1
    assert env["status"] == "ERROR" and env["error"]["code"] == "INSUFFICIENT_HISTORY"
    validate_envelope(env)


def test_member_without_data_is_no_data_error(tmp_path):
    _snap(tmp_path, {"BIMAS": step(109), "MGROS": step(107)}, FLAT)  # MAVI yok
    env = call(tmp_path, d(59))
    assert env["status"] == "ERROR" and env["error"]["code"] == "NO_DATA" and "MAVI" in env["error"]["message"]


def test_unknown_sector_is_invalid_params(roots):
    env = call(roots["jump"], d(59), group="not_a_group")
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


# =====================================================================================================
# (D) gerçek v2 snapshot: retail, as_of = 2026-09-10
# =====================================================================================================
REAL_AS_OF = "2026-09-10"


def real(**over):
    return tool.run_on({"sector": "retail", "as_of": REAL_AS_OF, **over}, snapshot_root=SNAPSHOT_DIR, data_version=VERSION)


@needs_snapshot
def test_real_retail_last_20_days_anchors():
    env = real()
    validate_envelope(env)
    r = res(env)
    assert env["data_version"] == VERSION
    assert (r.window_start, r.window_end) == (date(2026, 8, 14), date(2026, 9, 10))
    assert [(x.rank, x.ticker, x.return_pct) for x in r.ranking] == [
        (1, "BIMAS", 14.2098), (2, "MGROS", -1.8116), (3, "MAVI", -5.0568)]
    assert r.sector_median_return_pct == -1.8116 and r.xu100_return_pct == 1.8518
    assert r.sector_median_vs_xu100_pp == -3.6634 and r.sector_strength.value == "WEAK"
    assert [x.is_laggard for x in r.ranking] == [False, False, True]
    assert r.ranking[2].lag_score_pp == -3.2452 and r.ranking[2].return_vs_xu100_pp == -6.9086


@needs_snapshot
def test_real_retail_historical_counts_and_invariants():
    env = real()
    r = res(env)
    (hw,) = warn(env, "HISTORICAL_ONLY")
    assert "BIMAS 43, MAVI 227, MGROS 128 (toplam 398)" in hw and "cooldown=20" in hw
    assert [c.block.horizon for c in r.historical_catch_up] == [5, 10, 20]
    # kabul edilen her bağımsız olay her ufukta ya tamamlanmıştır ya dışlanmıştır: toplam sabit (44)
    for c in r.historical_catch_up:
        f = c.block.full
        assert f.n_success + f.n_false_positive == f.n_events_complete
        assert f.n_events_complete + f.n_excluded_incomplete_horizon == 44
    assert env["n_events"] + env["n_excluded_incomplete_horizon"] == 44
    assert (env["n_events"], env["n_excluded_incomplete_horizon"]) == (
        r.historical_catch_up[-1].block.full.n_events_complete, r.historical_catch_up[-1].block.full.n_excluded_incomplete_horizon)


@needs_snapshot
def test_real_leakage_truncated_snapshot_gives_identical_results(tmp_path):
    full = load_snapshot(VERSION)
    cut = pd.Timestamp(REAL_AS_OF)
    assert full.stocks["date"].max() > cut
    make_snapshot(tmp_path, full.stocks[full.stocks["date"] <= cut].reset_index(drop=True),
                  full.index[full.index["date"] <= cut].reset_index(drop=True), version=VERSION)
    a = real(split_date="2026-01-01")
    b = tool.run_on({"sector": "retail", "as_of": REAL_AS_OF, "split_date": "2026-01-01"},
                    snapshot_root=tmp_path, data_version=VERSION)
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]


@needs_snapshot
def test_real_results_have_no_negative_zero():
    assert _negative_zeros(real(split_date="2026-01-01")["results"]) == []


@needs_snapshot
def test_real_determinism():
    assert real() == real()


# =====================================================================================================
# (E) şema 1.2.0: per_ticker, ham sayı, cooldown_days, sonuç ölçütü (docs/schema_1_2_0_plan.md)
# =====================================================================================================
def _by_ticker(r: RankSectorRelativeStrengthResult) -> dict:
    return {t.ticker: t for t in r.per_ticker}


def test_per_ticker_counts_step_scenario_only_mavi_has_events(roots):
    """MAVI 20 gün (t=40..59) geride: ham 20; cooldown 20 -> 1 bağımsız olay. Diğer iki hissede olay yok."""
    env = call(roots["step"], d(70), forward_horizons=[5, 10, 20])
    validate_envelope(env)
    r = res(env)
    assert env["schema_version"] == "1.2.0"
    assert (r.cooldown_days, r.n_raw_laggard_observations) == (20, 20)
    assert [t.ticker for t in r.per_ticker] == ["BIMAS", "MAVI", "MGROS"]  # ticker sıralı
    assert [(t.n_raw_laggard_observations, t.n_independent_events, t.n_excluded_incomplete_horizon) for t in r.per_ticker] == [
        (0, 0, 0), (20, 1, 0), (0, 0, 0)]
    by = _by_ticker(r)
    # yalnız MAVI olay verdiği için MAVI'nin blokları havuzlu bloklarla birebir aynı olmalı
    for pooled, mine in zip(r.historical_catch_up, by["MAVI"].per_horizon):
        assert mine.block.full == pooled.block.full and mine.median_catch_up_size_pp == pooled.median_catch_up_size_pp
    empty = by["BIMAS"].per_horizon[2].block.full
    assert (empty.n_events_complete, empty.hit_rate_pct, empty.mean_return_pct) == (0, None, None)


def test_cooldown_days_field_follows_longest_forward_horizon(roots):
    short = res(call(roots["step"], d(70), forward_horizons=[5]))
    assert short.cooldown_days == 5
    assert _by_ticker(short)["MAVI"].n_independent_events == 4 and short.n_raw_laggard_observations == 20


def test_per_ticker_mirrors_ranking_rows(roots):
    r = res(call(roots["jump"], d(59)))
    rank = {x.ticker: x for x in r.ranking}
    for t in r.per_ticker:
        assert (t.is_laggard, t.lag_score_pp) == (rank[t.ticker].is_laggard, rank[t.ticker].lag_score_pp)
    assert (_by_ticker(r)["MAVI"].is_laggard, _by_ticker(r)["MAVI"].lag_score_pp) == (True, -6.0)


def test_outcome_benchmark_definition_excludes_subject_stock(roots):
    r = res(call(roots["jump"], d(59)))
    o, b = r.outcome_benchmark_definition, r.benchmark_definition
    assert (o.type, o.includes_subject_stock, o.price_field, o.return_type, o.peer_group) == (
        "peer_median", False, "adj_close", "simple", "retail")
    assert o.members == b.members == ["BIMAS", "MAVI", "MGROS"] and b.includes_subject_stock is True


def test_per_ticker_parts_sum_to_pool_on_random_walks_with_split(roots):
    env = call(roots["rw"], RW_AS_OF, split_date=RW_DATES[700].date().isoformat())
    validate_envelope(env)  # şema doğrulayıcısı toplamları zaten denetler; aşağıda açıkça da sayıyoruz
    r = res(env)
    assert r.n_raw_laggard_observations == sum(t.n_raw_laggard_observations for t in r.per_ticker) > 0
    assert sum(t.n_independent_events for t in r.per_ticker) == env["n_events"] + env["n_excluded_incomplete_horizon"]
    for i, pooled in enumerate(r.historical_catch_up):
        parts = [t.per_horizon[i].block for t in r.per_ticker]
        assert all(p.in_sample is None and p.out_of_sample is None for p in parts)
        for attr in ("n_events_complete", "n_excluded_incomplete_horizon", "n_success", "n_false_positive"):
            assert sum(getattr(p.full, attr) for p in parts) == getattr(pooled.block.full, attr)
        assert sum(p.baseline.n_obs for p in parts) == pooled.block.baseline.n_obs  # baz da parçaların toplamı


def test_per_ticker_baseline_is_that_tickers_own_unconditional_excess(roots):
    r = res(call(roots["rw"], RW_AS_OF, forward_horizons=[5]))
    pooled = r.historical_catch_up[0].block.baseline
    parts = [t.per_horizon[0].block.baseline for t in r.per_ticker]
    assert len(parts) == 3
    # 3 üyede kendisi hariç medyan: Σ excess = 0 -> hisse baz ortalamalarının ağırlıklı toplamı havuz ortalamasına eşit (yuvarlama payı)
    assert abs(sum(p.mean_return_pct * p.n_obs for p in parts) / pooled.n_obs - pooled.mean_return_pct) < 1e-3


def test_solo_group_has_no_new_event_fields(tmp_path):
    _snap(tmp_path, {"ASELS": walk(N, 5)}, FLAT)
    env = call(tmp_path, d(59), group="solo_asels")
    validate_envelope(env)
    r = res(env)
    assert (r.per_ticker, r.n_raw_laggard_observations, r.cooldown_days, r.outcome_benchmark_definition) == ([], None, None, None)


def test_two_stock_group_has_per_ticker_for_both_members(tmp_path):
    _snap(tmp_path, {"THYAO": walk(N, 6), "PGSUS": walk(N, 7)}, walk(N, 8))
    env = call(tmp_path, d(59), group="airlines")
    validate_envelope(env)
    r = res(env)
    assert [t.ticker for t in r.per_ticker] == ["PGSUS", "THYAO"] and r.cooldown_days == 20


def test_historical_only_warning_text_still_has_counts_during_transition(roots):
    (w,) = warn(call(roots["step"], d(70), forward_horizons=[5, 10, 20]), "HISTORICAL_ONLY")
    assert "BIMAS 0, MAVI 20, MGROS 0 (toplam 20)" in w and "cooldown=20" in w


@needs_snapshot
def test_real_retail_per_ticker_matches_documented_counts():
    """docs/data_dictionary 14.4: ham BIMAS 43, MAVI 227, MGROS 128 (398); bağımsız 9/21/14 (44), ufku dolmamış 1."""
    env = real(split_date="2026-01-01")
    validate_envelope(env)
    r = res(env)
    by = _by_ticker(r)
    assert r.n_raw_laggard_observations == 398 and r.cooldown_days == 20
    assert [(k, v.n_raw_laggard_observations, v.n_independent_events) for k, v in by.items()] == [
        ("BIMAS", 43, 9), ("MAVI", 227, 21), ("MGROS", 128, 14)]
    assert sum(v.n_excluded_incomplete_horizon for v in by.values()) == env["n_excluded_incomplete_horizon"] == 1
    assert (by["MAVI"].is_laggard, by["MAVI"].lag_score_pp) == (True, -3.2452)
    assert r.outcome_benchmark_definition.includes_subject_stock is False
