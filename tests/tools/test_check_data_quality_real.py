"""check_data_quality: gerçek snapshot (v1 ham, v2 düzeltilmiş) üzerinde çapa değerler.

Yoksa atlanır (CI'da snapshot olmayabilir); yerelde gerçekten koşar.
"""
from __future__ import annotations

import pytest

from config.settings import SNAPSHOT_DIR
from config.universe import load_universe
from schemas import validate_envelope
from tools import check_data_quality as cdq
from tools import rank_sector_relative_strength as rank

V1, V2 = "snap_2026-11-20_v1", "snap_2026-11-20_v2"
AS_OF = "2026-09-10"
needs_snapshot = pytest.mark.skipif(
    not ((SNAPSHOT_DIR / V1).is_dir() and (SNAPSHOT_DIR / V2).is_dir()), reason="gerçek v1/v2 snapshot yok")
pytestmark = needs_snapshot


def gate(tickers, v=V2, as_of=AS_OF, start="2024-01-01", **over):
    env = cdq.run_on({"tickers": tickers, "as_of": as_of, "end": as_of, "start": start, **over},
                     snapshot_root=SNAPSHOT_DIR, data_version=v)
    validate_envelope(env)
    return env


def reports(env):
    return {t["ticker"]: t for t in env["results"]["ticker_reports"]}


def soft(env):
    return [(i["code"], i["ticker"], i["date"], i["value"]) for i in env["results"]["soft_warnings"]]


# ---------------------------------------------------------------------------------------------- CCOLA: v1 HARD, v2 PASS
def test_v1_ccola_is_hard_block_with_the_unadjusted_split():
    env = gate(["CCOLA"], v=V1)
    r = env["results"]
    assert env["data_version"] == V1 and r["gate_status"] == "HARD_BLOCK"
    assert [(i["code"], i["ticker"], i["date"], i["value"]) for i in r["hard_blocks"]] == [
        ("WRONG_TICKER_OR_BROKEN_HISTORY", "CCOLA", "2024-08-01", -90.7479)]
    assert "hard 1 (WRONG_TICKER_OR_BROKEN_HISTORY×1)" in r["gate_reason"]
    assert reports(env)["CCOLA"]["n_price_jumps_over_limit"] == 1
    assert reports(env)["CCOLA"]["max_abs_daily_return_pct"] == 90.7479


def test_v2_ccola_is_pass_and_default_snapshot_is_v2():
    env = cdq.run_on({"tickers": ["CCOLA"], "as_of": AS_OF, "end": AS_OF})          # snapshot belirtilmedi -> LATEST
    validate_envelope(env)
    r = env["results"]
    assert env["data_version"] == V2 and r["gate_status"] == "PASS"
    assert r["hard_blocks"] == [] and r["soft_warnings"] == []
    c = reports(env)["CCOLA"]
    assert (c["n_rows"], c["first_date"], c["last_date"], c["last_data_age_days"]) == (673, "2024-01-02", "2026-09-10", 0)
    assert (c["n_missing_trading_days"], c["n_price_jumps_over_limit"]) == (0, 0)
    assert (c["max_abs_daily_return_pct"], c["max_abs_daily_return_date"]) == (10.0, "2025-03-21")


def test_v1_and_v2_hashes_differ_and_v1_leak_cannot_see_the_split_before_it_happens():
    assert gate(["CCOLA"], v=V1)["input_hash"] != gate(["CCOLA"], v=V2)["input_hash"]
    # bölünme sıçraması 2024-08-01'de: as_of bir gün önceyse görünmez, as_of günüyse görünür
    assert gate(["CCOLA"], v=V1, as_of="2024-07-31")["results"]["gate_status"] == "PASS"
    assert gate(["CCOLA"], v=V1, as_of="2024-08-01")["results"]["gate_status"] == "HARD_BLOCK"


# ---------------------------------------------------------------------------------------------- 2023-02-15 piyasa geneli
@pytest.mark.parametrize("v", [V1, V2])
def test_2023_02_15_market_wide_jump_is_soft_for_all_30_tickers(v):
    tickers = sorted(load_universe()["ticker"])
    env = gate(tickers, v=v, as_of="2023-03-01", start="2023-01-02")
    r = env["results"]
    assert len(tickers) == 30 and r["gate_status"] == "PASS_WITH_WARNINGS" and r["hard_blocks"] == []
    assert len(r["soft_warnings"]) == 30 and {i["code"] for i in r["soft_warnings"]} == {"PRICE_JUMP_OVER_LIMIT"}
    assert {i["date"] for i in r["soft_warnings"]} == {"2023-02-15"}
    assert "PRICE_JUMP_OVER_LIMIT×30" in r["gate_reason"]
    assert reports(env)["THYAO"]["n_price_jumps_over_limit"] == 1 and reports(env)["THYAO"]["max_abs_daily_return_pct"] == 21.6522


# ---------------------------------------------------------------------------------------------- THYAO ve retail
def test_thyao_v2_has_one_real_missing_day_and_nothing_else():
    env = gate(["THYAO"])
    r = env["results"]
    assert r["gate_status"] == "PASS_WITH_WARNINGS" and r["hard_blocks"] == []
    assert soft(env) == [("MISSING_TRADING_DAYS", "THYAO", None, 1.0)]
    assert "2024-04-09" in r["soft_warnings"][0]["message"]               # o gün 30 hissenin yalnızca 9'unda veri var
    t, x = reports(env)["THYAO"], reports(env)["XU100"]
    assert (t["n_rows"], t["n_missing_trading_days"], t["max_abs_daily_return_pct"], t["max_abs_daily_return_date"]) == (
        672, 1, 8.5616, "2026-04-08")
    assert (x["n_rows"], x["n_missing_trading_days"]) == (671, 2)          # 2024-12-25 ve 2025-12-25: bilinen Yahoo boşluğu


def test_retail_v2_with_a_real_rank_envelope_in_the_bundle():
    rk = rank.run_on({"sector": "retail", "as_of": AS_OF}, snapshot_root=SNAPSHOT_DIR, data_version=V2)
    assert rk["status"] == "OK" and rk["n_events"] == 43 and rk["n_excluded_incomplete_horizon"] == 1
    item = {k: rk[k] for k in ("tool", "as_of", "data_version", "input_hash", "n_events", "n_excluded_incomplete_horizon")}
    env = gate(["BIMAS", "MAVI", "MGROS"], analysis_bundle=[item])
    r = env["results"]
    assert {"EVENT_COUNT", "PEER_GROUP_SIZE", "DATA_VERSION_CONSISTENCY", "AS_OF_CONSISTENCY"} <= set(r["checks_run"])
    # n_events=43 >= 20 ve peer grubu 3: bu kontroller sorun çıkarmaz; kalan tek uyarı MGROS'un 2024-04-09 boşluğu
    assert r["gate_status"] == "PASS_WITH_WARNINGS" and soft(env) == [("MISSING_TRADING_DAYS", "MGROS", None, 1.0)]
    rep = reports(env)
    assert (rep["BIMAS"]["n_rows"], rep["MAVI"]["n_rows"], rep["MGROS"]["n_rows"]) == (673, 673, 672)


def test_real_bundle_item_from_v1_in_a_v2_gate_is_investigate():
    item = {"tool": "detect_reversal_events", "as_of": AS_OF, "data_version": V1, "input_hash": "0" * 64, "n_events": 30}
    env = gate(["CCOLA"], analysis_bundle=[item])
    assert env["results"]["gate_status"] == "INVESTIGATE"
    assert [i["code"] for i in env["results"]["soft_warnings"]] == ["DATA_VERSION_MISMATCH"]


# ---------------------------------------------------------------------------------------------- bayatlık ve determinizm
def test_as_of_beyond_snapshot_end_is_analysis_unsafe_with_41_day_staleness():
    env = gate(["THYAO"], as_of="2026-12-31")            # snapshot son satırı 2026-11-20
    r = env["results"]
    assert r["gate_status"] == "ANALYSIS_UNSAFE" and r["hard_blocks"] == []
    assert reports(env)["THYAO"]["last_data_age_days"] == 41 and reports(env)["THYAO"]["last_date"] == "2026-11-20"
    assert ("STALE_DATA", "THYAO", "2026-11-20", 41.0) in soft(env) and ("STALE_DATA", "XU100", "2026-11-20", 41.0) in soft(env)
    assert "Kapıyı belirleyen: STALE_DATA×2" in r["gate_reason"]


def test_real_determinism_and_no_rows_after_as_of_in_report():
    a, b = gate(["THYAO", "BIMAS"]), gate(["BIMAS", "THYAO"])
    assert a == b
    assert all(t["last_date"] <= AS_OF for t in a["results"]["ticker_reports"])
