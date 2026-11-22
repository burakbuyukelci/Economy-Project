"""get_fundamental_metrics ve calculate_fundamental_change: sentetik (ağsız) veri + gerçek TUPRS (varsa)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from scripts.download_fundamentals import write_fundamentals_snapshot
from tests.conftest import make_frame, make_snapshot
from tools import calculate_fundamental_change as CH
from tools import get_fundamental_metrics as GM
from tools._fundamentals import COLUMNS, fp_period_end, fp_shift

DATES = pd.bdate_range("2025-01-01", "2026-12-31")
FV = "fundamentals_2026-11-21_v1"
AS_OF = "2026-09-10"
FPS = ["2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2", "2026Q3"]
DISC = ["2025-05-06", "2025-08-05", "2025-11-04", "2026-02-10", "2026-05-12", "2026-08-11", "2026-11-10"]
REV = [1000, 1100, 1200, 1300, 1400, 1500, 1600]
EBITDA = [100, 110, 150, 130, 168, 150, 200]  # marj: 10, 10, 12.5, 10, 12, 10, 12.5


def _row(ticker, fp, disc, mset="INDUSTRIAL", time=None, source="KAP_MANUAL", **kw):
    r = dict.fromkeys(COLUMNS, np.nan)
    r.update(ticker=ticker, fiscal_period=fp, period_end_date=pd.Timestamp(fp_period_end(fp)), disclosure_date=pd.Timestamp(disc),
             disclosure_time=time, disclosure_source="KAP_MANUAL" if source == "KAP_MANUAL" else "YAHOO_APPROX",
             data_source=source, report_basis="STANDALONE", tms29_restated=None, metric_set=mset)
    r.update(kw)
    return r


def _table(times=None, source="KAP_MANUAL"):
    times = times or {}
    rows = []
    for i, fp in enumerate(FPS):
        rows.append(_row("TUPRS", fp, DISC[i], time=times.get(fp), source=source, revenue=REV[i], ebitda=EBITDA[i],
                         net_profit=50 + 10 * i, total_financial_debt=500, cash_and_equivalents=100, equity=1000))
        rows.append(_row("AKBNK", fp, DISC[i], mset="BANK", source=source, net_interest_income=200 + 10 * i,
                         net_profit=100 + 5 * i, equity=2000))
    return pd.DataFrame(rows, columns=COLUMNS)


def _prices(root, scale_after=None):
    def frame(t, base):
        f = make_frame(t, base, DATES, adj_factor=1.0)
        if scale_after is not None:  # as_of sonrası fiyatları bozar (sızıntı testi)
            f.loc[f["date"] > pd.Timestamp(AS_OF), ["adj_close", "close"]] *= scale_after
        return f
    stocks = pd.concat([frame("TUPRS", 100), frame("PETKM", 200), frame("AKBNK", 50)], ignore_index=True)
    index = frame("XU100", 10000).drop(columns=["ticker"])
    make_snapshot(root, stocks, index, version="snap_2026-11-20_v2")


@pytest.fixture()
def env(tmp_path):
    _prices(tmp_path)
    write_fundamentals_snapshot(_table(), tmp_path, FV, {})
    return tmp_path


def _gm(env, **p):
    out = GM.run_on({"ticker": "TUPRS", "as_of": AS_OF, **p}, snapshot_root=env, data_version="snap_2026-11-20_v2", fundamentals_version=FV)
    return out


def _ch(env, **p):
    return CH.run_on({"ticker": "TUPRS", "as_of": AS_OF, **p}, snapshot_root=env, data_version="snap_2026-11-20_v2", fundamentals_version=FV)


def _m(env_, name):
    return {m["name"]: m["value"] for m in env_["results"]["metrics"]}[name]


# --- get_fundamental_metrics --------------------------------------------------------------------------
def test_latest_disclosed_period_and_values(env):
    e = _gm(env)
    validate_envelope(e)
    r = e["results"]
    assert (r["fiscal_period"], r["disclosure_date"], r["tms29_comparable"]) == ("2026Q2", "2026-08-11", True)
    assert _m(e, "EBITDA_MARGIN") == 10.0  # 150/1500*100
    assert _m(e, "REVENUE") == 1500.0


def test_as_of_equal_to_disclosure_date_is_included_and_day_before_is_not(env):
    assert _gm(env, as_of="2026-08-11")["results"]["fiscal_period"] == "2026Q2"
    before = _gm(env, as_of="2026-08-10")
    assert before["results"]["fiscal_period"] == "2026Q1"
    assert _m(before, "EBITDA_MARGIN") == 12.0


def test_alignment_by_disclosure_not_period_end(env):
    # 2026Q2 dönem sonu 30 Haz geçmiş ama KAP açıklaması 11 Ağu: 15 Tem'de Q2 GÖRÜNMEZ
    e = _gm(env, as_of="2026-07-15")
    assert e["results"]["fiscal_period"] == "2026Q1"
    w = [x for x in e["warnings"] if x.startswith("NOT_YET_DISCLOSED_EXCLUDED")]
    assert len(w) == 1 and "1 dönem" in w[0]
    assert "2026-08-11" not in "".join(e["warnings"])  # gelecek açıklama tarihi sızmaz


def test_unfinished_period_is_not_counted_as_pending(env):
    # as_of 2026-09-10: 2026Q3 henüz bitmemiş (30 Eyl) -> ne görünür ne 'bekleyen' sayılır
    e = _gm(env)
    assert not any(w.startswith("NOT_YET_DISCLOSED_EXCLUDED") for w in e["warnings"])
    assert e["results"]["fiscal_period"] != "2026Q3"


def test_requested_period_not_disclosed_is_error(env):
    e = _gm(env, period="2026Q3")
    assert e["status"] == "ERROR" and e["error"]["code"] == "NOT_YET_DISCLOSED"


def test_net_debt_ebitda_ltm_vs_annualised(env):
    ltm = _gm(env, period="2025Q4")  # 2025Q1..Q4 mevcut: LTM = 100+110+150+130 = 490; net borç 400
    assert _m(ltm, "NET_DEBT_EBITDA") == round(400 / 490, 4)
    assert not any("yıllıklandırılmış" in w for w in ltm["warnings"])
    ann = _gm(env, period="2025Q3")  # yalnız 3 çeyrek: 150 x 4 = 600
    assert _m(ann, "NET_DEBT_EBITDA") == round(400 / 600, 4)
    assert any("yıllıklandırılmış" in w for w in ann["warnings"])


def test_ltm_uses_only_disclosed_quarters(env):
    # as_of 2026-05-11: 2026Q1 henüz açıklanmadı; 2025Q4 için LTM 4 çeyrek (hepsi açıklanmış) olsa da Q1'26 kullanılamaz
    e = _gm(env, as_of="2026-05-11")
    assert e["results"]["fiscal_period"] == "2025Q4"


def test_bank_uses_bank_metric_set_only(env):
    e = _gm(env, ticker="AKBNK")
    validate_envelope(e)
    names = [m["name"] for m in e["results"]["metrics"]]
    assert e["results"]["metric_set"] == "BANK" and names == ["NET_INTEREST_INCOME", "NET_PROFIT", "ROE"]
    assert not {"EBITDA", "EBITDA_MARGIN", "NET_DEBT_EBITDA", "DEBT_EQUITY"} & set(names)
    assert any(w.startswith("BANK_METRIC_SET") for w in e["warnings"])
    assert _m(e, "ROE") == round(125 / 2000 * 100, 4)  # 2026Q2: net kâr 100+5*5=125


def test_errors_unknown_ticker_and_no_data(env):
    assert _gm(env, ticker="XXXXX")["error"]["code"] in ("UNKNOWN_TICKER", "INVALID_PARAMS")
    assert _gm(env, ticker="THYAO")["error"]["code"] == "NO_DATA"


def test_provenance_warning_carries_dataset_version_and_yahoo_flag(tmp_path):
    _prices(tmp_path)
    write_fundamentals_snapshot(_table(source="YAHOO"), tmp_path, FV, {})
    e = _gm(tmp_path)
    assert any(w.startswith("HISTORICAL_ONLY") and FV in w for w in e["warnings"])
    assert any("YAHOO_APPROX" in w for w in e["warnings"])


def test_no_leak_from_future_fundamentals_or_prices(env, tmp_path_factory):
    base = _gm(env)
    other = tmp_path_factory.mktemp("o")
    _prices(other)
    t = _table()
    t.loc[pd.to_datetime(t["disclosure_date"]) > pd.Timestamp(AS_OF), ["revenue", "ebitda"]] = 9e9
    write_fundamentals_snapshot(t, other, FV, {})
    assert _gm(other)["results"] == base["results"]
    assert _gm(other)["warnings"] == base["warnings"]


# --- calculate_fundamental_change ---------------------------------------------------------------------
def _q(e, fp):
    return next(q for q in e["results"]["quarters"] if q["fiscal_period"] == fp)


def _mc(q, name):
    return next(m for m in q["metrics"] if m["name"] == name)


def test_change_values_directions_and_units(env):
    e = _ch(env)
    validate_envelope(e)
    q = _q(e, "2026Q1")  # marj 12.0; 2025Q4 10.0; 2025Q1 10.0
    m = _mc(q, "EBITDA_MARGIN")
    assert (m["value"], m["qoq_change"], m["yoy_change"], m["change_unit"]) == (12.0, 2.0, 2.0, "PP")
    assert (m["qoq_direction"], m["yoy_direction"]) == ("IMPROVED", "IMPROVED")
    rev = _mc(q, "REVENUE")
    assert rev["qoq_change"] == round((1400 / 1300 - 1) * 100, 4) and rev["change_unit"] == "PCT"
    nd = _mc(q, "NET_DEBT_EBITDA")  # düşük iyi: 400/558=0.7168 vs 2025Q4 400/490=0.8163 -> düştü -> IMPROVED
    assert nd["change_unit"] == "ABS" and nd["qoq_direction"] == "IMPROVED"


def test_pre_tms29_yoy_and_first_quarter_qoq_are_none_with_warning(env):
    e = _ch(env)
    q1 = _q(e, "2025Q1")
    m = _mc(q1, "EBITDA_MARGIN")
    assert m["qoq_change"] is None and m["yoy_change"] is None and m["yoy_direction"] is None
    assert _mc(_q(e, "2025Q3"), "EBITDA_MARGIN")["yoy_change"] is None  # 2024Q3 TMS 29 öncesi
    assert _mc(_q(e, "2025Q3"), "EBITDA_MARGIN")["qoq_change"] == 2.5
    assert any(w.startswith("PRE_TMS29_NOT_COMPARABLE") for w in e["warnings"])


def test_only_disclosed_quarters_by_as_of_and_pending_count(env):
    e = _ch(env, as_of="2026-07-15")
    assert [q["fiscal_period"] for q in e["results"]["quarters"]] == FPS[:5]
    assert e["results"]["n_quarters_disclosed_by_as_of"] == 5
    assert e["results"]["n_quarters_excluded_not_yet_disclosed"] == 1
    e2 = _ch(env)  # 2026Q3 hiç bitmemiş -> dışlanır ama 'bekleyen' sayılmaz
    assert [q["fiscal_period"] for q in e2["results"]["quarters"]][-1] == "2026Q2"
    assert e2["results"]["n_quarters_excluded_not_yet_disclosed"] == 0


def _expected_reaction(fp_disc, h, base_shift=-1):
    """Bağımsız hesap: TUPRS kapanışı = 100 + i, PETKM = 200 + i, XU100 = 10000 + i (i = DATES konumu)."""
    pos = int(DATES.searchsorted(pd.Timestamp(fp_disc))) + base_shift
    ret = lambda b: (b + pos + h) / (b + pos) * 100 - 100  # noqa: E731
    stock, peer, xu = ret(100), ret(200), ret(10000)
    return round(stock, 4), round(xu, 4), round(float(np.median([stock, peer])), 4)


def test_reaction_base_is_day_before_when_time_unknown(env):
    r = {x["horizon"]: x for x in _q(_ch(env), "2026Q1")["reactions"]}  # 12 May 2026 (Salı)
    stock, xu, sec = _expected_reaction("2026-05-12", 1)
    assert (r[1]["stock_return_pct"], r[1]["xu100_return_pct"], r[1]["sector_return_pct"]) == (stock, xu, sec)
    assert r[1]["window_end_date"] == "2026-05-12"  # 1 günlük tepki = açıklama günü
    assert r[1]["abnormal_vs_xu100_pct"] == round(stock - xu, 4)
    assert r[1]["abnormal_vs_sector_pct"] == round(stock - sec, 4)
    assert r[5]["window_end_date"] == "2026-05-18"


def test_reaction_base_is_disclosure_day_when_after_close(tmp_path):
    _prices(tmp_path)
    write_fundamentals_snapshot(_table(times={"2026Q1": "19:30"}), tmp_path, FV, {})
    r = {x["horizon"]: x for x in _q(_ch(tmp_path), "2026Q1")["reactions"]}
    stock, xu, sec = _expected_reaction("2026-05-12", 1, base_shift=0)
    assert (r[1]["stock_return_pct"], r[1]["window_end_date"]) == (stock, "2026-05-13")
    # saat 14:00 (seans içi) -> bir önceki gün baz (muhafazakâr)
    d2 = tmp_path / "sub"
    d2.mkdir()
    _prices(d2)
    write_fundamentals_snapshot(_table(times={"2026Q1": "14:00"}), d2, FV, {})
    r2 = {x["horizon"]: x for x in _q(_ch(d2), "2026Q1")["reactions"]}
    assert r2[1]["window_end_date"] == "2026-05-12"


def test_incomplete_horizon_is_excluded_and_reported(env):
    e = _ch(env, as_of="2026-08-14")  # Q2 açıklaması 11 Ağu; 20 günlük pencere as_of'u aşar, 1 günlük aşmaz
    q = _q(e, "2026Q2")
    r = {x["horizon"]: x for x in q["reactions"]}
    assert r[1]["complete"] is True and r[1]["window_end_date"] == "2026-08-11"
    assert r[20]["complete"] is False and r[20]["window_end_date"] is None and r[20]["stock_return_pct"] is None
    assert e["n_excluded_incomplete_horizon"] >= 1
    assert any(w.startswith("INCOMPLETE_HORIZON_EXCLUDED") for w in e["warnings"])
    s20 = [s for s in e["results"]["reaction_summary"] if s["horizon"] == 20 and s["group"] == "ALL"][0]
    assert s20["n_excluded_incomplete_horizon"] >= 1
    n_total = e["results"]["n_quarters_disclosed_by_as_of"]
    assert s20["n"] + s20["n_excluded_incomplete_horizon"] == n_total


def test_reaction_never_uses_prices_after_as_of(env, tmp_path_factory):
    base = _ch(env, as_of="2026-08-14")
    other = tmp_path_factory.mktemp("p")
    _prices(other, scale_after=10.0)
    write_fundamentals_snapshot(_table(), other, FV, {})
    assert _ch(other, as_of="2026-08-14")["results"] == base["results"]


def test_summary_groups_and_counts(env):
    e = _ch(env, improvement_metric="EBITDA_MARGIN", improvement_basis="QOQ")
    summ = {(s["horizon"], s["group"]): s for s in e["results"]["reaction_summary"]}
    imp = [q for q in e["results"]["quarters"] if _mc(q, "EBITDA_MARGIN")["qoq_direction"] == "IMPROVED"]
    assert summ[(5, "IMPROVED")]["n"] + summ[(5, "IMPROVED")]["n_excluded_incomplete_horizon"] == len(imp)
    a, i, n = summ[(5, "ALL")], summ[(5, "IMPROVED")], summ[(5, "NOT_IMPROVED")]
    assert a["n"] >= i["n"] + n["n"]  # QoQ'su None olan ilk çeyrek yalnız ALL'da
    assert 0 <= a["hit_rate_vs_xu100_pct"] <= 100
    assert any(w.startswith("FEW_EVENTS") for w in e["warnings"])
    assert any(w.startswith("ASSOCIATION_NOT_CAUSATION") for w in e["warnings"])


def test_bank_change_set_and_improvement_fallback(env):
    e = _ch(env, ticker="AKBNK")
    validate_envelope(e)
    assert e["results"]["metric_set"] == "BANK" and e["results"]["improvement_metric"] == "NET_PROFIT"
    assert {m["name"] for m in e["results"]["quarters"][0]["metrics"]} == {"NET_INTEREST_INCOME", "NET_PROFIT", "ROE"}
    assert any(w.startswith("SOLO_PEER_GROUP") for w in e["warnings"])
    assert all(r["sector_return_pct"] is None and r["abnormal_vs_sector_pct"] is None
               for q in e["results"]["quarters"] for r in q["reactions"] if r["complete"])
    bad = _ch(env, ticker="AKBNK", metrics=["EBITDA"])
    assert bad["status"] == "ERROR" and bad["error"]["code"] == "METRIC_NOT_APPLICABLE"


def test_requested_periods_subset(env):
    e = _ch(env, periods=["2026Q1", "2026Q2"])
    assert [q["fiscal_period"] for q in e["results"]["quarters"]] == ["2026Q1", "2026Q2"]
    assert _mc(_q(e, "2026Q1"), "EBITDA_MARGIN")["yoy_change"] == 2.0  # önceki dönem satırları gizlenmez, yalnız çıktı daralır


def test_determinism_and_hash(env):
    a, b = _ch(env), _ch(env)
    assert a == b and len(a["input_hash"]) == 64
    assert _ch(env, as_of="2026-08-14")["input_hash"] != a["input_hash"]


def test_helpers_period_arithmetic():
    assert fp_shift("2026Q1", -1) == "2025Q4" and fp_shift("2026Q1", -4) == "2025Q1" and fp_shift("2025Q4", 1) == "2026Q1"


# --- gerçek veri (varsa) ----------------------------------------------------------------------------
@pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST_FUNDAMENTALS").exists() or not (SNAPSHOT_DIR / "LATEST").exists(),
                    reason="gerçek bilanço snapshot'ı yok")
def test_real_tuprs_soru4_shape():
    e = CH.run({"ticker": "TUPRS", "as_of": AS_OF})
    validate_envelope(e)
    r = e["results"]
    assert e["status"] == "OK" and r["metric_set"] == "INDUSTRIAL"
    assert all(q["disclosure_date"] <= AS_OF for q in r["quarters"])  # sızıntı yok
    assert "2026Q3" not in [q["fiscal_period"] for q in r["quarters"]]  # Kasım'da açıklanır
    g = GM.run({"ticker": "TUPRS", "as_of": AS_OF})
    validate_envelope(g)
    assert g["results"]["disclosure_date"] <= AS_OF


# --- yasal süre görünürlüğü (açıklama tarihi bilinmeyen dönemler) ----------------------------------------
STAT_DISC = "2026-05-15"  # 2026Q1 dönem sonu 31 Mar + 45 gün


def _table_stat(values_after=None):
    t = _table()
    m = (t["ticker"] == "TUPRS") & (t["fiscal_period"] == "2026Q1")
    t.loc[m, "disclosure_date"] = pd.Timestamp(STAT_DISC)
    t.loc[m, "disclosure_source"] = "STATUTORY_DEADLINE"
    t.loc[m, "data_source"] = "YAHOO"
    if values_after is not None:
        t.loc[m, ["revenue", "ebitda"]] = values_after
    return t


@pytest.fixture()
def env_stat(tmp_path):
    _prices(tmp_path)
    write_fundamentals_snapshot(_table_stat(), tmp_path, FV, {})
    return tmp_path


STAT_TEXT = "açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı"


def test_statutory_row_is_hidden_until_deadline_inclusive(env_stat):
    assert _gm(env_stat, as_of="2026-05-14")["results"]["fiscal_period"] == "2025Q4"
    e = _gm(env_stat, as_of="2026-05-14")
    assert any(w.startswith("NOT_YET_DISCLOSED_EXCLUDED") for w in e["warnings"])  # dönem bitmiş, 'açıklanmamış' sayılır
    on = _gm(env_stat, as_of=STAT_DISC)
    assert on["results"]["fiscal_period"] == "2026Q1" and on["results"]["disclosure_date"] == STAT_DISC
    assert any(STAT_TEXT in w and "2026Q1" in w for w in on["warnings"])


def test_statutory_metrics_visible_but_not_in_reactions_or_stats(env_stat, tmp_path_factory):
    plain = tmp_path_factory.mktemp("plain")
    _prices(plain)
    write_fundamentals_snapshot(_table(), plain, FV, {})
    e, base = _ch(env_stat), _ch(plain)
    q = _q(e, "2026Q1")
    assert q["reactions"] == [] and q["disclosure_date"] == STAT_DISC
    assert _mc(q, "EBITDA_MARGIN")["value"] == 12.0  # metrik/değişim hesabında GÖRÜNÜR
    assert _mc(q, "EBITDA_MARGIN")["qoq_change"] == 2.0
    # QoQ zinciri bozulmaz: 2026Q2 kendi değişimini 2026Q1'e göre hesaplar
    assert _mc(_q(e, "2026Q2"), "EBITDA_MARGIN")["qoq_change"] == _mc(_q(base, "2026Q2"), "EBITDA_MARGIN")["qoq_change"]
    # diğer çeyreklerin tepkileri değişmez
    assert _q(e, "2026Q2")["reactions"] == _q(base, "2026Q2")["reactions"]
    # istatistik: ALL grubunda tepki taşıyan çeyrek sayısı bir azalır, statutory çeyrek ne n ne dışlanan sayısına girer
    for h in (1, 5, 20):
        a = next(s for s in e["results"]["reaction_summary"] if s["horizon"] == h and s["group"] == "ALL")
        b = next(s for s in base["results"]["reaction_summary"] if s["horizon"] == h and s["group"] == "ALL")
        assert a["n"] + a["n_excluded_incomplete_horizon"] == b["n"] + b["n_excluded_incomplete_horizon"] - 1
    assert e["n_events"] == base["n_events"] - 1
    assert e["results"]["n_quarters_disclosed_by_as_of"] == base["results"]["n_quarters_disclosed_by_as_of"]


def test_statutory_warning_text_and_counts(env_stat):
    e = _ch(env_stat)
    validate_envelope(e)
    w = [x for x in e["warnings"] if "STATUTORY" not in x and STAT_TEXT in x]
    assert len(w) >= 1 and any("1/6 çeyreğin" in x for x in w)  # yalnızca ilgili çeyrek, sayı ayrı raporlanır
    assert any(x.startswith("INSUFFICIENT_HISTORY: STATUTORY_DEADLINE: 2026Q1") for x in e["warnings"])


def test_statutory_row_values_after_as_of_never_leak(env_stat, tmp_path_factory):
    # as_of yasal süre görünürlüğünden ÖNCE: satırın değerleri (ve tepkisi) hiçbir şeyi etkilemez
    base = _ch(env_stat, as_of="2026-05-14")
    other = tmp_path_factory.mktemp("s")
    _prices(other)
    write_fundamentals_snapshot(_table_stat(values_after=9e9), other, FV, {})
    assert _ch(other, as_of="2026-05-14")["results"] == base["results"]
    assert "2026Q1" not in [q["fiscal_period"] for q in base["results"]["quarters"]]


def test_statutory_after_deadline_without_reaction_window_complete_flags_untouched(env_stat):
    e = _ch(env_stat, as_of="2026-08-14")
    assert _q(e, "2026Q1")["reactions"] == []
    assert e["n_excluded_incomplete_horizon"] >= 1  # yalnızca 2026Q2'nin 20 günlük penceresi; statutory çeyrek bunu şişirmez
    assert sum(1 for q in e["results"]["quarters"] for r in q["reactions"] if not r["complete"]) == e["n_excluded_incomplete_horizon"]


# --- Net Borç/FAVÖK değişimi: iki uçta AYNI taban (LTM ya da ikisi de yıllıklandırılmış) -----------------------------------
def test_nd_ebitda_change_uses_the_same_basis_on_both_ends_annualised_when_either_lacks_four_quarters(env):
    e = _ch(env)
    q4 = _mc(_q(e, "2025Q4"), "NET_DEBT_EBITDA")
    # kendi değeri LTM (Q1..Q4 mevcut): 400/490; ama 2025Q3 (yalnız 3 çeyrek) yıllıklandırılmış -> değişim İKİSİ DE yıllıklandırılmış kıyaslanır
    assert q4["value"] == round(400 / 490, 4)
    ann_q4, ann_q3 = round(400 / (130 * 4), 4), round(400 / (150 * 4), 4)       # 0.7692, 0.6667
    assert q4["qoq_change"] == round(ann_q4 - ann_q3, 4) and q4["change_unit"] == "ABS"
    assert q4["qoq_change"] != round(round(400 / 490, 4) - ann_q3, 4)           # eski (karışık taban) değer DEĞİL
    assert q4["qoq_direction"] == "DETERIORATED"                                # yüksek borç/FAVÖK kötü; |0.1025| > 0.05
    assert q4["yoy_change"] is None                                             # 2024Q4 yok


def test_nd_ebitda_change_is_ltm_when_both_ends_have_four_quarters(env):
    q = _mc(_q(_ch(env), "2026Q1"), "NET_DEBT_EBITDA")        # 2026Q1 (Q2'25..Q1'26) ve 2025Q4 (Q1..Q4'25): ikisi de LTM
    assert q["value"] == round(400 / 558, 4) and q["qoq_change"] == round(round(400 / 558, 4) - round(400 / 490, 4), 4)


def test_nd_ebitda_yoy_both_annualised_and_warning_lists_the_basis(env):
    e = _ch(env)
    q = _mc(_q(e, "2026Q1"), "NET_DEBT_EBITDA")
    assert q["yoy_change"] == round(round(400 / (168 * 4), 4) - round(400 / (100 * 4), 4), 4)   # 2025Q1 yalnız 1 çeyrek: ikisi de yıllıklandırılmış
    w = [x for x in e["warnings"] if x.startswith("INSUFFICIENT_HISTORY: NET_DEBT_EBITDA değişim tabanı")]
    assert len(w) == 1 and "yıllıklandırılmış" in w[0] and "2025Q4 QOQ" in w[0] and "2026Q1 YOY" in w[0] and "LTM" in w[0] and "2026Q1 QOQ" in w[0]


def test_nd_ebitda_pair_helper_cases(env):
    import pandas as pd
    from tools import _fundamentals as F
    t = _table()
    rows = t.loc[t["ticker"] == "TUPRS"].set_index("fiscal_period", drop=False)
    assert F.nd_ebitda_pair(rows, "2026Q2", "2026Q1")[2] == "LTM"
    assert F.nd_ebitda_pair(rows, "2025Q4", "2025Q3")[2] == "ANNUALISED"
    assert F.nd_ebitda_pair(rows, "2025Q1", "2024Q4") == (None, None, "NONE")
    rows2 = rows.copy()
    rows2["ebitda"] = -5.0                                        # FAVÖK <= 0 (LTM ve yıllıklandırılmış): oran anlamsız -> değişim hesaplanamaz
    assert F.nd_ebitda_pair(rows2, "2026Q1", "2025Q4") == (None, None, "NONE")
    rows3 = rows.copy()
    rows3.loc["2026Q1", "ebitda"] = -5.0                          # tek çeyrek negatif ama LTM toplamı pozitif: LTM geçerli
    assert F.nd_ebitda_pair(rows3, "2026Q2", "2026Q1")[2] == "LTM"
