"""check_data_quality aracı: sentetik snapshot ile uçtan uca (params -> zarf).

Veri: 5 hisse x 20 işlem günü (2026-08-24 .. 2026-09-18), as_of = 2026-09-10 (Perşembe). 2026-09-11..18 veride VAR ama as_of sonrası.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from schemas import validate_envelope
from tests.conftest import AS_OF, DATES, make_frame, make_snapshot
from tools import check_data_quality as cdq

V2 = "snap_2026-11-20_v2"
TICKERS = ["BIMAS", "CCOLA", "MAVI", "MGROS", "THYAO"]


def build(tmp_path, jumps=None, drop=None, dates=DATES, tickers=TICKERS, version=V2, drop_index=None):
    """jumps: {(ticker, gün_indeksi): çarpan} adj_close'a bu günden itibaren uygulanır; drop: {(ticker, 'YYYY-MM-DD')};
    drop_index: {'YYYY-MM-DD'} XU100'den silinen günler."""
    frames = []
    for k, tk in enumerate(tickers):
        f = make_frame(tk, 100 + 10 * k, dates)
        for (jt, jd), mult in (jumps or {}).items():
            if jt == tk:
                f.loc[f.index[jd:], "adj_close"] = f.loc[f.index[jd:], "adj_close"] * mult
        frames.append(f)
    stocks = pd.concat(frames, ignore_index=True)
    for tk, d in (drop or set()):
        stocks = stocks[~((stocks["ticker"] == tk) & (stocks["date"] == pd.Timestamp(d)))]
    index = make_frame("XU100", 10000, dates, adj_factor=1.0).drop(columns=["ticker"])
    index = index[~index["date"].isin([pd.Timestamp(d) for d in (drop_index or ())])]
    make_snapshot(tmp_path, stocks, index, version=version)
    return tmp_path


def call(root, **over):
    p = {"tickers": ["THYAO"], "start": "2026-08-24", "end": "2026-09-10", "as_of": AS_OF, **over}
    return cdq.run_on(p, snapshot_root=root, data_version=V2)


def bundle_item(tool="detect_reversal_events", n_events=30, as_of=AS_OF, data_version=V2, h="0"):
    return {"tool": tool, "as_of": as_of, "data_version": data_version, "input_hash": h * 64, "n_events": n_events}


@pytest.fixture()
def clean(tmp_path):
    return build(tmp_path)


def hard_codes(env):
    return [i["code"] for i in env["results"]["hard_blocks"]]


def soft_codes(env):
    return [i["code"] for i in env["results"]["soft_warnings"]]


# ------------------------------------------------------------------------------------------- boş bundle (ilk kapı)
def test_empty_bundle_clean_data_is_pass_and_first_gate_runs_price_checks_only(clean):
    env = call(clean)
    validate_envelope(env)
    r = env["results"]
    assert env["status"] == "OK" and env["tool"] == "check_data_quality" and env["n_events"] is None
    assert r["gate_status"] == "PASS" and r["hard_blocks"] == [] and r["soft_warnings"] == []
    assert r["checks_run"] == ["PRICE_JUMPS", "MISSING_DAYS", "STALENESS", "AS_OF_CONSISTENCY", "TICKER_IDENTITY"]
    for unrun in ("DATA_VERSION_CONSISTENCY", "SIGNAL_SHIFT", "EVENT_COUNT", "PEER_GROUP_SIZE", "MACRO_COVERAGE",
                  "NEWS_COVERAGE", "TRANSCRIPT_QUALITY", "FUNDAMENTAL_DISCLOSURE_ALIGNMENT"):
        assert unrun in r["gate_reason"]
    assert "Çalışmayan kontroller" in r["gate_reason"]


def test_ticker_reports_have_real_values_for_stock_and_index(clean):
    r = call(clean)["results"]["ticker_reports"]
    assert [t["ticker"] for t in r] == ["THYAO", "XU100"]
    th = r[0]
    assert th["n_rows"] == 14 and th["first_date"] == "2026-08-24" and th["last_date"] == "2026-09-10"
    assert th["last_data_age_days"] == 0 and th["n_missing_trading_days"] == 0 and th["n_price_jumps_over_limit"] == 0
    assert th["max_abs_daily_return_pct"] is not None and th["max_abs_daily_return_date"] is not None


def test_include_index_false_drops_xu100_report(clean):
    r = call(clean, include_index=False)["results"]["ticker_reports"]
    assert [t["ticker"] for t in r] == ["THYAO"]


# ------------------------------------------------------------------------------------------- fiyat HARD / SOFT
def test_idiosyncratic_jump_is_hard_block(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1 / 11})
    env = call(root)
    r = env["results"]
    assert r["gate_status"] == "HARD_BLOCK" and env["status"] == "OK"
    assert hard_codes(env) == ["WRONG_TICKER_OR_BROKEN_HISTORY"] and r["hard_blocks"][0]["ticker"] == "THYAO"
    assert r["hard_blocks"][0]["date"] == "2026-09-03" and r["hard_blocks"][0]["value"] < -90
    assert "hard 1" in r["gate_reason"] and "WRONG_TICKER_OR_BROKEN_HISTORY×1" in r["gate_reason"]
    assert r["ticker_reports"][0]["n_price_jumps_over_limit"] == 1


def test_market_wide_jump_is_soft(tmp_path):
    root = build(tmp_path, jumps={(tk, 8): 1.25 for tk in TICKERS})  # 5/5 hisse aynı gün +%25
    env = call(root)
    assert env["results"]["gate_status"] == "PASS_WITH_WARNINGS"
    assert hard_codes(env) == [] and soft_codes(env) == ["PRICE_JUMP_OVER_LIMIT"]


def test_jump_after_as_of_is_invisible(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 15): 1 / 11})  # gün 15 = 2026-09-14: as_of (09-10) sonrası
    assert call(root)["results"]["gate_status"] == "PASS"
    assert call(root, as_of="2026-09-14", end="2026-09-14")["results"]["gate_status"] == "HARD_BLOCK"


def test_custom_price_jump_limit_changes_flagging(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1.08})  # +%8
    assert call(root)["results"]["gate_status"] == "PASS"                                   # limit 10 + 0,5
    env = call(root, price_jump_limit_pct=5.0)
    assert env["results"]["gate_status"] == "HARD_BLOCK" and env["results"]["price_jump_limit_pct"] == 5.0


def test_unknown_ticker_is_hard_block_with_empty_report(clean):
    env = call(clean, tickers=["THYAO", "ZZZZZ"])
    r = env["results"]
    assert r["gate_status"] == "HARD_BLOCK" and hard_codes(env) == ["WRONG_TICKER_OR_BROKEN_HISTORY"]
    assert r["hard_blocks"][0]["ticker"] == "ZZZZZ" and "snapshot'ta yok" in r["hard_blocks"][0]["message"]
    zz = next(t for t in r["ticker_reports"] if t["ticker"] == "ZZZZZ")
    assert zz["n_rows"] == 0 and zz["first_date"] is None and zz["last_data_age_days"] is None


def test_ticker_without_rows_in_window_is_hard(clean):
    # as_of'a kadar satır var (08-24..09-10) ama istenen pencere [08-01, 08-20] boş
    env = call(clean, start="2026-08-01", end="2026-08-20", include_index=False)
    assert hard_codes(env) == ["WRONG_TICKER_OR_BROKEN_HISTORY"] and env["results"]["gate_status"] == "HARD_BLOCK"
    assert "pencerede satır yok" in env["results"]["hard_blocks"][0]["message"]
    both = call(clean, start="2026-08-01", end="2026-08-20")      # endeks de aynı pencerede boş
    assert [i["ticker"] for i in both["results"]["hard_blocks"]] == ["THYAO", "XU100"]


def test_missing_trading_day_is_soft(tmp_path):
    root = build(tmp_path, drop={("MGROS", "2026-09-03")})
    env = call(root, tickers=["MGROS"])
    assert soft_codes(env) == ["MISSING_TRADING_DAYS"] and env["results"]["gate_status"] == "PASS_WITH_WARNINGS"
    assert env["results"]["ticker_reports"][0]["n_missing_trading_days"] == 1
    assert env["results"]["soft_warnings"][0]["value"] == 1


def test_index_missing_day_is_reported_but_raises_no_warning(tmp_path):
    """XU100'de bilinen Yahoo boşluğu (25 Aralık; data_dictionary 11.4): rapora girer, kapıyı etkilemez. Hissede aynı boşluk uyarıdır."""
    env = call(build(tmp_path, drop_index={"2026-09-03"}))
    xu = next(t for t in env["results"]["ticker_reports"] if t["ticker"] == "XU100")
    assert xu["n_missing_trading_days"] == 1                      # 09-03'te hisselerin hepsinde veri var -> takvimde
    assert env["results"]["soft_warnings"] == [] and env["results"]["gate_status"] == "PASS"


# ------------------------------------------------------------------------------------------- bayatlık kademeleri
@pytest.mark.parametrize("as_of,gate,age", [
    ("2026-09-18", "PASS", 0), ("2026-09-22", "PASS", 4), ("2026-09-23", "PASS_WITH_WARNINGS", 5),
    ("2026-09-28", "PASS_WITH_WARNINGS", 10), ("2026-09-29", "INVESTIGATE", 11), ("2026-10-18", "INVESTIGATE", 30),
    ("2026-10-19", "ANALYSIS_UNSAFE", 31),
])
def test_staleness_tiers(clean, as_of, gate, age):
    env = call(clean, as_of=as_of, end=as_of, start="2026-08-24")
    r = env["results"]
    assert r["gate_status"] == gate
    assert r["ticker_reports"][0]["last_data_age_days"] == age
    assert r["hard_blocks"] == []


def test_stale_index_is_reported_with_xu100_label(clean):
    r = call(clean, as_of="2026-10-19", end="2026-10-19")["results"]
    assert {i["ticker"] for i in r["soft_warnings"] if i["code"] == "STALE_DATA"} == {"THYAO", "XU100"}


# ------------------------------------------------------------------------------------------- bundle
def test_healthy_bundle_passes_and_adds_bundle_checks(clean):
    env = call(clean, analysis_bundle=[bundle_item(n_events=30)])
    r = env["results"]
    assert r["gate_status"] == "PASS"
    assert {"AS_OF_CONSISTENCY", "DATA_VERSION_CONSISTENCY", "EVENT_COUNT"} <= set(r["checks_run"])
    assert "PEER_GROUP_SIZE" not in r["checks_run"]


def test_bundle_item_as_of_after_session_as_of_is_hard_block(clean):
    env = call(clean, analysis_bundle=[bundle_item(as_of="2026-09-11")])
    validate_envelope(env)  # ihlalin tarihi `date` alanında taşınsaydı look-ahead taraması bu zarfı reddederdi
    assert env["results"]["gate_status"] == "HARD_BLOCK" and hard_codes(env) == ["AS_OF_VIOLATION"]
    assert env["results"]["hard_blocks"][0]["date"] is None and "2026-09-11" in env["results"]["hard_blocks"][0]["message"]


def test_bundle_data_version_mismatch_is_investigate(clean):
    env = call(clean, analysis_bundle=[bundle_item(data_version="snap_2026-11-20_v1")])
    assert env["results"]["gate_status"] == "INVESTIGATE" and soft_codes(env) == ["DATA_VERSION_MISMATCH"]


def test_few_events_in_bundle_is_investigate_and_zero_events_too(clean):
    env = call(clean, analysis_bundle=[bundle_item("detect_reversal_events", 7)])
    assert env["results"]["gate_status"] == "INVESTIGATE" and soft_codes(env) == ["FEW_EVENTS"]
    env0 = call(clean, analysis_bundle=[bundle_item("rank_sector_relative_strength", 0)])
    assert env0["results"]["gate_status"] == "INVESTIGATE"


def test_unknown_tool_in_bundle_does_not_run_event_count(clean):
    env = call(clean, analysis_bundle=[bundle_item("get_stock_history", None)])
    assert "EVENT_COUNT" not in env["results"]["checks_run"] and env["results"]["gate_status"] == "PASS"


def test_small_peer_group_with_rank_in_bundle_is_investigate(clean):
    item = bundle_item("rank_sector_relative_strength", 25)
    env = call(clean, tickers=["THYAO"], analysis_bundle=[item])   # THYAO peer grubu = 2 (config/universe.csv)
    assert env["results"]["gate_status"] == "INVESTIGATE" and soft_codes(env) == ["SMALL_PEER_GROUP"]
    assert "PEER_GROUP_SIZE" in env["results"]["checks_run"]
    ok = call(clean, tickers=["BIMAS", "MAVI", "MGROS"], analysis_bundle=[item])   # retail = 3
    assert ok["results"]["gate_status"] == "PASS" and "PEER_GROUP_SIZE" in ok["results"]["checks_run"]


def test_hard_wins_over_soft_in_same_call(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1 / 11})
    env = call(root, analysis_bundle=[bundle_item("detect_reversal_events", 3)])
    assert env["results"]["gate_status"] == "HARD_BLOCK"
    assert hard_codes(env) == ["WRONG_TICKER_OR_BROKEN_HISTORY"] and soft_codes(env) == ["FEW_EVENTS"]


# ------------------------------------------------------------------------------------------- checks alt kümesi
def test_explicit_checks_run_only_requested_and_name_the_unrunnable(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1 / 11}, drop={("THYAO", "2026-09-03")})
    env = call(root, checks=["PRICE_JUMPS", "SIGNAL_SHIFT"])
    r = env["results"]
    assert r["checks_run"] == ["PRICE_JUMPS"] and hard_codes(env) == ["WRONG_TICKER_OR_BROKEN_HISTORY"]
    assert soft_codes(env) == [] and "SIGNAL_SHIFT" in r["gate_reason"] and "MISSING_DAYS" not in r["gate_reason"]


# ------------------------------------------------------------------------------------------- sızıntı ve determinizm
def test_rows_after_as_of_do_not_change_the_result(tmp_path_factory):
    """Aynı veri iki kez: tam seri vs as_of'ta kesilmiş seri. as_of sonrası satırlar sonucu DEĞİŞTİRMEMELİ."""
    full_dates = DATES                                  # 2026-08-24 .. 09-18
    cut_dates = DATES[DATES <= pd.Timestamp(AS_OF)]     # .. 09-10
    # as_of sonrasında sert bir şok ekle: görünürse sonuç değişir
    full = build(tmp_path_factory.mktemp("full"), jumps={("THYAO", 15): 1 / 11}, dates=full_dates)
    cut = build(tmp_path_factory.mktemp("cut"), dates=cut_dates)
    a, b = call(full), call(cut)
    assert a["results"] == b["results"] and a["input_hash"] == b["input_hash"]
    assert a["results"]["gate_status"] == "PASS"


def test_determinism_same_input_same_output_and_ticker_order_irrelevant(clean):
    a = call(clean, tickers=["THYAO", "BIMAS", "MAVI"])
    b = call(clean, tickers=["MAVI", "THYAO", "BIMAS", "THYAO"])
    assert a == b and a["input_hash"] == b["input_hash"] and len(a["input_hash"]) == 64
    assert call(clean, tickers=["THYAO"])["input_hash"] != a["input_hash"]


def test_end_after_as_of_is_clamped_with_warning(clean):
    env = call(clean, end="2026-09-18")
    assert any(w.startswith("AS_OF_CLAMPED") for w in env["warnings"]) and env["results"]["gate_status"] == "PASS"


def test_soft_issue_order_is_deterministic(tmp_path):
    root = build(tmp_path, drop={("MGROS", "2026-09-03"), ("BIMAS", "2026-09-04")})
    a = call(root, tickers=["MGROS", "BIMAS"])
    assert [i["ticker"] for i in a["results"]["soft_warnings"]] == ["BIMAS", "MGROS"]


# ------------------------------------------------------------------------------------------- şema 1.2.0: issue_counts
def test_issue_counts_is_empty_dict_not_none_when_no_issues(clean):
    env = call(clean)
    validate_envelope(env)
    assert env["schema_version"] == "1.2.0" and env["results"]["issue_counts"] == {}


def test_issue_counts_matches_hard_and_soft_lists_and_is_sorted_by_code(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1 / 11}, drop={("THYAO", "2026-09-03")})
    env = call(root, analysis_bundle=[bundle_item("detect_reversal_events", 3)])
    validate_envelope(env)
    r = env["results"]
    assert r["issue_counts"] == {"FEW_EVENTS": 1, "MISSING_TRADING_DAYS": 1, "WRONG_TICKER_OR_BROKEN_HISTORY": 1}
    assert list(r["issue_counts"]) == sorted(r["issue_counts"])  # belirlenimcilik: anahtar sırası kod adına göre
    assert sum(r["issue_counts"].values()) == len(r["hard_blocks"]) + len(r["soft_warnings"])
    assert "hard 1 (WRONG_TICKER_OR_BROKEN_HISTORY×1)" in r["gate_reason"]  # geçiş dönemi: metin de duruyor


def test_issue_counts_respects_checks_subset(tmp_path):
    root = build(tmp_path, jumps={("THYAO", 8): 1 / 11}, drop={("THYAO", "2026-09-03")})
    env = call(root, checks=["PRICE_JUMPS"])
    validate_envelope(env)
    assert env["results"]["issue_counts"] == {"WRONG_TICKER_OR_BROKEN_HISTORY": 1}


# ------------------------------------------------------------------------------------------- şema 1.2.0: BundleItem lag / max_result_date
def backtest_item(**extra):
    return {**bundle_item("run_backtest", 30), **extra}


def test_signal_lag_one_in_bundle_passes_and_signal_shift_is_run(clean):
    env = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1)])
    validate_envelope(env)
    r = env["results"]
    assert r["gate_status"] == "PASS" and "SIGNAL_SHIFT" in r["checks_run"] and "SIGNAL_SHIFT" not in r["gate_reason"].split("Çalışmayan")[-1]


def test_signal_lag_zero_in_bundle_is_hard_lookahead_signal(clean):
    env = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=0)])
    validate_envelope(env)
    r = env["results"]
    assert r["gate_status"] == "HARD_BLOCK" and hard_codes(env) == ["LOOKAHEAD_SIGNAL"]
    assert r["hard_blocks"][0]["value"] == 0.0 and "SIGNAL_SHIFT" in r["checks_run"]
    assert r["issue_counts"] == {"LOOKAHEAD_SIGNAL": 1}


def test_backtest_without_lag_in_bundle_does_not_count_as_signal_shift_checked(clean):
    env = call(clean, analysis_bundle=[backtest_item()])
    r = env["results"]
    assert "SIGNAL_SHIFT" not in r["checks_run"] and "SIGNAL_SHIFT" in r["gate_reason"]  # 'geçti' sayılmaz; adıyla çalışmadı denir
    mixed = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1), backtest_item()])
    assert "SIGNAL_SHIFT" not in mixed["results"]["checks_run"]  # her backtest öğesi lag taşımadıkça kontrol tam sayılmaz


def test_no_backtest_in_bundle_signal_shift_is_not_run(clean):
    assert "SIGNAL_SHIFT" not in call(clean, analysis_bundle=[bundle_item()])["results"]["checks_run"]


def test_backtest_result_after_as_of_is_backtest_future_info(clean):
    env = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1, max_result_date="2026-09-11")])
    validate_envelope(env)
    r = env["results"]
    assert r["gate_status"] == "HARD_BLOCK" and hard_codes(env) == ["BACKTEST_FUTURE_INFO"]
    assert r["hard_blocks"][0]["date"] is None and "2026-09-11" in r["hard_blocks"][0]["message"]
    ok = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1, max_result_date="2026-09-10")])
    assert ok["results"]["gate_status"] == "PASS"  # as_of günü dahil


def test_non_backtest_result_after_as_of_is_lookahead_signal(clean):
    env = call(clean, analysis_bundle=[{**bundle_item("detect_reversal_events", 30), "max_result_date": "2026-09-14"}])
    validate_envelope(env)
    assert hard_codes(env) == ["LOOKAHEAD_SIGNAL"] and env["results"]["gate_status"] == "HARD_BLOCK"


def test_explicit_checks_signal_shift_only_evaluates_lag_not_result_date(clean):
    item = backtest_item(signal_lag_days_applied=0, max_result_date="2026-09-14")
    env = call(clean, checks=["SIGNAL_SHIFT"], analysis_bundle=[item])
    assert hard_codes(env) == ["LOOKAHEAD_SIGNAL"] and env["results"]["checks_run"] == ["SIGNAL_SHIFT"]
    env2 = call(clean, checks=["AS_OF_CONSISTENCY"], analysis_bundle=[item])
    assert hard_codes(env2) == ["BACKTEST_FUTURE_INFO"] and env2["results"]["checks_run"] == ["AS_OF_CONSISTENCY"]


def test_old_style_bundle_items_without_new_fields_still_work(clean):
    env = call(clean, analysis_bundle=[bundle_item("detect_reversal_events", 30)])
    validate_envelope(env)
    assert env["results"]["gate_status"] == "PASS"


def test_bundle_with_new_fields_is_deterministic_and_changes_the_hash(clean):
    a = call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1)])
    assert a == call(clean, analysis_bundle=[backtest_item(signal_lag_days_applied=1)])
    assert a["input_hash"] != call(clean, analysis_bundle=[backtest_item()])["input_hash"]
