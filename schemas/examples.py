"""Her araç için minimal GEÇERLİ örnek zarf (mock araçlar ve contract testleri kullanır).

Değerler uydurmadır; yalnızca şekli gösterir. as_of = 2026-09-10.
"""
from __future__ import annotations

import copy
from typing import Any

from schemas.common import SCHEMA_VERSION, make_cost_model


def _REL_WINDOW(n, start, end, corr, beta, p_raw, p_adj, sig, n_up, n_down, n_excl):  # noqa: N802
    """get_macro_context örneği için ilişki penceresi (1.5.0); tutarlı: up + down <= n_obs, unconditional.n == n_obs."""
    grp = lambda k, mean: {"n": k, "mean_return_pct": mean, "median_return_pct": mean, "cost_adjusted_mean_return_pct": round(mean - 0.5, 4)}  # noqa: E731
    return {"window": {"start": start, "end": end}, "n_obs": n, "n_excluded_incomplete_horizon": n_excl, "correlation": corr, "beta": beta,
            "p_value_raw": p_raw, "p_value_adjusted": p_adj, "significant_after_correction": sig,
            "macro_up": grp(n_up, 0.5228), "macro_down": grp(n_down, 1.3324), "unconditional": grp(n, 0.6194)}
from schemas.enums import ToolName
from schemas.hashing import compute_input_hash
from schemas.registry import validate_params

EXAMPLE_AS_OF = "2026-09-10"
EXAMPLE_DATA_VERSION = "snap_2026-11-20_v1"

_HASH = "0" * 64
_COST = make_cost_model().model_dump(mode="json")
_PCT = {"cumulative_return_pct": 10.0, "annualized_return_pct": 12.0, "sharpe_ratio": 0.8, "max_drawdown_pct": -9.5,
        "win_rate_pct": 55.0, "n_trades": 22, "avg_trade_return_pct": 0.6, "median_trade_return_pct": 0.4,
        "exposure_pct": 30.0}
_STATS = {"n_events_complete": 10, "n_excluded_incomplete_horizon": 1, "n_success": 6, "n_false_positive": 4,
          "hit_rate_pct": 60.0, "false_positive_rate_pct": 40.0, "mean_return_pct": 1.2, "median_return_pct": 0.9,
          "cost_adjusted_mean_return_pct": 0.5, "mean_reversal_strength_pct": 2.0, "median_reversal_strength_pct": 1.8}
_BASE = {"n_obs": 400, "mean_return_pct": 0.2, "median_return_pct": 0.1, "hit_rate_pct": 51.0}
_BLOCK = {"horizon": 5, "full": _STATS, "in_sample": _STATS, "out_of_sample": _STATS, "baseline": _BASE,
          "mean_diff_vs_baseline_pct": 1.0, "median_diff_vs_baseline_pct": 0.8, "oos_degradation_flag": False}


def _tstats(n: int, excl: int, ok: int) -> dict[str, Any]:
    """Tek hissenin HorizonStats'ı (rank per_ticker örneği)."""
    return {"n_events_complete": n, "n_excluded_incomplete_horizon": excl, "n_success": ok, "n_false_positive": n - ok,
            "hit_rate_pct": round(100 * ok / n, 4), "false_positive_rate_pct": round(100 * (n - ok) / n, 4),
            "mean_return_pct": 0.5, "median_return_pct": 0.3, "cost_adjusted_mean_return_pct": 0.0,
            "mean_reversal_strength_pct": None, "median_reversal_strength_pct": None}


def _ticker_catch_up(ticker: str, lag: float, laggard: bool, raw: int, n: int, excl: int, ok: int) -> dict[str, Any]:
    """Havuzlu _BLOCK (ufuk 5) ile toplamı tutan tek hisse kırılımı; IS/OOS yok."""
    block = {"horizon": 5, "full": _tstats(n, excl, ok), "in_sample": None, "out_of_sample": None, "baseline": _BASE,
             "mean_diff_vs_baseline_pct": 0.3, "median_diff_vs_baseline_pct": 0.2, "oos_degradation_flag": None}
    return {"ticker": ticker, "is_laggard": laggard, "lag_score_pp": lag, "n_raw_laggard_observations": raw,
            "n_independent_events": n + excl, "n_excluded_incomplete_horizon": excl,
            "per_horizon": [{"block": block, "median_catch_up_size_pp": 1.5}]}


_MT = {"n_tests_declared": 1, "alpha": 0.05, "adjusted_alpha": 0.05, "method": "bonferroni",
       "note": "Çok sayıda kombinasyon denendiğinde tesadüfi örüntü bulma riski artar."}
_ROW = {"date": "2026-09-10", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "adj_close": 10.4, "volume": 1000.0}


def _wk(start: str, end: str) -> dict[str, Any]:
    return {
        "window": {"start": start, "end": end}, "n_weeks_total": 10, "n_excluded_holiday_weeks": 1,
        "n_excluded_incomplete_horizon": 0, "n_weeks_complete": 9, "n_trigger_weeks": 3, "n_occurrences": 2,
        "n_false_positive": 1, "occurrence_rate_pct": 22.2, "hit_rate_pct": 66.7,
        "expected_occurrences_if_independent": 0.3,
        "per_day": [{"weekday": "THU", "expected_direction": "UP", "role": "OUTCOME", "n_obs": 9,
                     "mean_return_pct": 0.3, "median_return_pct": 0.2, "direction_match_rate_pct": 55.0,
                     "unconditional_mean_return_pct": 0.1, "unconditional_median_return_pct": 0.1}],
        "outcome_mean_return_pct": 0.8, "outcome_median_return_pct": 0.7,
        "unconditional_outcome_mean_return_pct": 0.2, "unconditional_outcome_median_return_pct": 0.1,
        "outcome_mean_diff_vs_unconditional_pct": 0.6, "cost_adjusted_outcome_mean_return_pct": 0.1,
        "t_stat": 1.1, "p_value_raw": 0.3, "p_value_adjusted": 0.3,
    }


_PARAMS: dict[ToolName, dict[str, Any]] = {
    ToolName.GET_STOCK_HISTORY: {"ticker": "THYAO", "start": "2026-09-08", "end": "2026-09-10"},
    ToolName.GET_INDEX_HISTORY: {"index": "XU100", "start": "2026-09-08", "end": "2026-09-10"},
    ToolName.CALCULATE_INDICATORS: {"ticker": "THYAO", "indicators": ["RSI"], "end": "2026-09-10"},
    ToolName.DETECT_REVERSAL_EVENTS: {"ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "touch_mode": "close"},
    ToolName.FIND_SUPPORT_RESISTANCE: {"ticker": "THYAO", "end": "2026-09-10"},
    ToolName.RANK_SECTOR_RELATIVE_STRENGTH: {"sector": "retail", "horizon": 20},
    ToolName.TEST_WEEKDAY_PATTERN: {
        "ticker": "THYAO",
        "pattern": [{"weekday": "MON", "direction": "DOWN", "role": "TRIGGER"},
                    {"weekday": "THU", "direction": "UP", "role": "OUTCOME"}],
        "in_sample_start": "2024-01-01", "in_sample_end": "2025-12-31",
        "out_of_sample_start": "2026-01-01", "out_of_sample_end": "2026-09-10"},
    ToolName.GET_FUNDAMENTAL_METRICS: {"ticker": "TUPRS"},
    ToolName.CALCULATE_FUNDAMENTAL_CHANGE: {"ticker": "TUPRS"},
    ToolName.GET_MACRO_CONTEXT: {"start": "2026-01-01", "end": "2026-09-10", "n_tests_declared": 1,
                                 "relate_to": [{"ticker": "EREGL", "macro_series": "USDTRY", "horizon": 5, "lag_days": 0, "split_date": "2026-01-01"}]},
    ToolName.GET_NEWS_EVENTS: {"ticker": "EREGL", "start": "2026-09-01", "end": "2026-09-10"},
    ToolName.GET_SPEECH_FEATURES: {"source_id": "damodaran_valuation_01"},
    ToolName.RUN_BACKTEST: {
        "strategy": {"variant": "B", "signal_type": "CATCH_UP"},
        "universe": ["BIMAS", "MAVI", "MGROS"], "start": "2024-01-01", "end": "2026-09-10"},
    ToolName.CHECK_DATA_QUALITY: {"tickers": ["THYAO"], "end": "2026-09-10"},
    ToolName.BUILD_EVIDENCE_BUNDLE: {"analysis_id": "demo-001", "source_input_hashes": [_HASH]},
}

_RESULTS: dict[ToolName, dict[str, Any]] = {
    ToolName.GET_STOCK_HISTORY: {
        "ticker": "THYAO", "yahoo_symbol": "THYAO.IS", "price_adjustment": "adjusted",
        "requested_start": "2026-09-08", "requested_end": "2026-09-10", "effective_end": "2026-09-10",
        "first_date": "2026-09-10", "last_date": "2026-09-10", "n_rows": 1, "rows": [_ROW]},
    ToolName.GET_INDEX_HISTORY: {
        "index": "XU100", "yahoo_symbol": "XU100.IS", "requested_start": "2026-09-08",
        "requested_end": "2026-09-10", "effective_end": "2026-09-10", "first_date": "2026-09-10",
        "last_date": "2026-09-10", "n_rows": 1, "rows": [_ROW]},
    # 1.2.0 hafif varsayılan: columns/recent_rows yok (include_columns_meta=False, last_n_rows=0). Tam varyant: example_envelope_indicators_full().
    ToolName.CALCULATE_INDICATORS: {
        "ticker": "THYAO", "price_adjustment": "adjusted", "state_date": "2026-09-10", "n_bars_used": 900,
        "history_first_date": "2023-01-02", "first_valid_date": "2023-01-23",
        "columns_meta_included": False, "columns": [], "invalid_columns_at_as_of": [],
        "latest": {"date": "2026-09-10", "close": 299.25, "values": {"RSI_14": 41.2}, "states": {}},
        "recent_rows": []},
    ToolName.DETECT_REVERSAL_EVENTS: {
        "ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "touch_mode": "close", "expected_direction": "UP",
        "analysis_start": "2024-01-01", "analysis_end": "2026-09-10", "split_date": "2026-01-01",
        "cost_model": _COST,
        "groups": [{"label": "single_indicator", "conditions": None, "n_events_detected": 11,
                    "per_horizon": [_BLOCK],
                    "regime_breakdown": [{"regime": "XU100_UP", "horizon": 10, "n_events": 5, "hit_rate_pct": 60.0,
                                          "mean_return_pct": 1.0}],
                    "events": [{"date": "2026-09-01", "close": 100.0,
                                "states": {"rsi": "LOCAL_LOW", "supertrend": "BEARISH", "kama_slope": "FLATTENING",
                                           "ichimoku": "BELOW_CLOUD", "volume": "HIGH"},
                                "forward_returns": [{"horizon": 1, "complete": True, "return_pct": 0.5,
                                                     "reversal_success": True, "reversal_strength_pct": 1.0},
                                                    {"horizon": 10, "complete": False, "return_pct": None,
                                                     "reversal_success": None, "reversal_strength_pct": None}]}],
                    "events_truncated": False, "n_raw_event_days": 14, "n_overlapping_forward_windows": 2}],
        "multiple_testing": _MT},
    ToolName.FIND_SUPPORT_RESISTANCE: {
        "ticker": "THYAO", "last_close": 300.0, "last_date": "2026-09-10", "nearest_support": 290.0,
        "nearest_resistance": 320.0,
        "nearest_support_distance_pct": 3.3333, "nearest_resistance_distance_pct": 6.6667,
        "levels": [{"type": "SUPPORT", "price": 290.0, "zone_low": 288.0, "zone_high": 292.0, "touch_count": 3,
                    "last_touch_date": "2026-08-20", "strength": 0.7}]},
    ToolName.RANK_SECTOR_RELATIVE_STRENGTH: {
        "sector": "retail", "peer_group_size": 3, "insufficient_peers": False, "horizon": 20,
        "window_start": "2026-08-12", "window_end": "2026-09-10",
        "benchmark_definition": {"type": "peer_median", "includes_subject_stock": True, "price_field": "adj_close",
                                 "return_type": "simple", "peer_group": "retail",
                                 "members": ["BIMAS", "MAVI", "MGROS"]},
        "sector_median_return_pct": 12.0, "xu100_return_pct": 4.0, "sector_median_vs_xu100_pp": 8.0,
        "sector_strength": "STRONG",
        "strength_thresholds": {"strong_min_vs_xu100_pp": 2.0, "weak_max_vs_xu100_pp": -2.0},
        "lag_threshold_pp": 3.0,
        "ranking": [{"rank": 1, "ticker": "BIMAS", "return_pct": 15.0, "lag_score_pp": 3.0,
                     "return_vs_xu100_pp": 11.0, "is_laggard": False, "is_leader": True},
                    {"rank": 2, "ticker": "MGROS", "return_pct": 12.0, "lag_score_pp": 0.0,
                     "return_vs_xu100_pp": 8.0, "is_laggard": False, "is_leader": False},
                    {"rank": 3, "ticker": "MAVI", "return_pct": 9.0, "lag_score_pp": -3.0,
                     "return_vs_xu100_pp": 5.0, "is_laggard": True, "is_leader": False}],
        "historical_catch_up": [{"block": {**_BLOCK, "horizon": 5}, "median_catch_up_size_pp": 2.1}],
        "n_raw_laggard_observations": 72, "cooldown_days": 20,
        "outcome_benchmark_definition": {"type": "peer_median", "includes_subject_stock": False, "price_field": "adj_close",
                                         "return_type": "simple", "peer_group": "retail",
                                         "members": ["BIMAS", "MAVI", "MGROS"]},
        # ticker sıralı; Σ ham 12+40+20, Σ tamamlanmış 4+3+3, Σ dışlanan 0+1+0, Σ başarı 3+2+1 = havuz
        "per_ticker": [_ticker_catch_up("BIMAS", 3.0, False, 12, 4, 0, 3),
                       _ticker_catch_up("MAVI", -3.0, True, 40, 3, 1, 2),
                       _ticker_catch_up("MGROS", 0.0, False, 20, 3, 0, 1)],
        "cost_model": _COST, "structural_vs_temporary": None},
    ToolName.TEST_WEEKDAY_PATTERN: {
        "ticker": "THYAO", "pattern_label": "MON-DOWN | THU-UP", "conditioning": "NONE", "cost_model": _COST,
        "in_sample": _wk("2024-01-01", "2025-12-31"), "out_of_sample": _wk("2026-01-01", "2026-09-10"),
        "stability_verdict": "INSUFFICIENT_DATA", "verdict_codes": ["IS_TOO_FEW"],
        "verdict_reason": "IS_TOO_FEW: n_trigger_weeks=3 < 10", "multiple_testing": _MT},
    ToolName.GET_FUNDAMENTAL_METRICS: {
        "ticker": "TUPRS", "metric_set": "INDUSTRIAL", "fiscal_period": "2026Q2", "period_end_date": "2026-06-30",
        "disclosure_date": "2026-08-12", "tms29_comparable": True,
        "metrics": [{"name": "EBITDA_MARGIN", "value": 8.5, "unit": "PCT"}]},
    ToolName.CALCULATE_FUNDAMENTAL_CHANGE: {
        "ticker": "TUPRS", "metric_set": "INDUSTRIAL",
        "benchmark_definition": {"type": "peer_median", "includes_subject_stock": True, "price_field": "adj_close",
                                 "return_type": "simple", "peer_group": "energy_petrochem",
                                 "members": ["PETKM", "TUPRS"]},
        "improvement_metric": "EBITDA_MARGIN", "improvement_basis": "YOY",
        "n_quarters_disclosed_by_as_of": 6, "n_quarters_excluded_not_yet_disclosed": 0,
        "quarters": [{"fiscal_period": "2026Q2", "period_end_date": "2026-06-30", "disclosure_date": "2026-08-12",
                      "tms29_comparable": True,
                      "metrics": [{"name": "EBITDA_MARGIN", "value": 8.5, "qoq_change": 0.4, "yoy_change": 1.2,
                                   "change_unit": "PP", "qoq_direction": "IMPROVED", "yoy_direction": "IMPROVED"}],
                      "reactions": [{"horizon": 20, "window_end_date": None, "complete": False,
                                     "stock_return_pct": None, "xu100_return_pct": None, "sector_return_pct": None,
                                     "abnormal_vs_xu100_pct": None, "abnormal_vs_sector_pct": None}]}],
        "reaction_summary": [{"horizon": 5, "group": "IMPROVED", "n": 3, "n_excluded_incomplete_horizon": 0,
                              "mean_abnormal_vs_xu100_pct": 0.8, "median_abnormal_vs_xu100_pct": 0.6,
                              "hit_rate_vs_xu100_pct": 66.7, "mean_abnormal_vs_sector_pct": 0.4,
                              "median_abnormal_vs_sector_pct": 0.3}]},
    ToolName.GET_MACRO_CONTEXT: {
        "start": "2026-01-01", "end": "2026-09-10",
        "series": [{"series": "USDTRY", "source": "TCMB/EVDS", "frequency": "daily", "n_points": 1,
                    "last_publication_date": "2026-09-10", "gaps": [],
                    "points": [{"observation_date": "2026-09-10", "publication_date": "2026-09-10",
                                "value": 41.0}]}],
        "relations": [{
            "ticker": "EREGL", "macro_series": "USDTRY", "horizon": 5, "lag_days": 0, "transform": "PCT_CHANGE",
            "full": _REL_WINDOW(134, "2026-01-02", "2026-09-08", -0.163, -1.6229, 0.0629, 0.0629, False, 118, 16, 1),
            "in_sample": _REL_WINDOW(100, "2024-01-08", "2025-12-26", -0.1912, -1.7, 0.05, 0.05, False, 88, 12, 0),
            "out_of_sample": _REL_WINDOW(33, "2026-01-09", "2026-09-08", 0.1115, 0.9, 0.52, 0.52, False, 30, 3, 1),
            "oos_degradation_flag": True, "sample_last_date": "2026-09-08"}],
        "multiple_testing": {"n_tests_declared": 1, "alpha": 0.05, "adjusted_alpha": 0.05, "method": "bonferroni",
                             "note": "Çok sayıda kombinasyon denendiğinde tesadüfi örüntü bulma riski artar."},
        "cost_model": {"transaction_cost_bps_per_side": 20.0, "slippage_bps_per_side": 5.0, "round_trip_cost_pct": 0.5}},
    ToolName.GET_NEWS_EVENTS: {
        "n_events_returned": 1,
        "events": [{"event_id": "kap-0001", "published_date": "2026-09-05", "published_time": "18:30",
                    "headline": "Örnek KAP açıklaması", "source": "KAP", "url": None, "tickers": ["EREGL"],
                    "topics": ["earnings"], "category": "EARNINGS", "stance": None}]},
    ToolName.GET_SPEECH_FEATURES: {
        "source_id": "damodaran_valuation_01", "video_url": "https://example.org/video",
        "speaker_channel": "Örnek kanal", "published_date": "2026-05-01", "transcript_quality": 0.9,
        "segments": [{"start_sec": 0.0, "end_sec": 30.0, "topics": ["valuation"], "stance": None,
                      "uncertainty": None,
                      "claims": [{"text": "Örnek iddia", "claim_type": "OPINION", "numerical_claim_verified": None}]}]},
    ToolName.RUN_BACKTEST: {
        "strategy": {"variant": "B", "signal_type": "CATCH_UP", "signal_params": {}, "holding_days": 5,
                     "signal_lag_days": 1, "benchmarks": ["BUY_AND_HOLD", "XU100"], "train_end": None,
                     "validation_end": None, "walk_forward": False, "transaction_cost_bps": 20.0,
                     "slippage_bps": 5.0},
        "universe": ["BIMAS", "MAVI", "MGROS"], "period": {"start": "2024-01-01", "end": "2026-09-10"},
        "signal_lag_days_applied": 1, "cost_model": _COST,
        "sharpe_definition": "günlük getiri, rf=0, yıllıklandırma sqrt(252)",
        "n_signals": 22, "n_excluded_incomplete_horizon": 1, "n_winning_trades": 12, "n_losing_trades": 10,
        "strategy_gross": _PCT, "strategy_net": _PCT,
        "benchmarks": [{"name": "XU100", "metrics": _PCT, "cumulative_return_diff_pct": 1.5, "sharpe_diff": 0.1}],
        "splits": [{"name": "TEST", "window": {"start": "2026-01-01", "end": "2026-09-10"}, "n_signals": 5,
                    "net_metrics": _PCT, "benchmark_diff_pct": 0.5}],
        "oos_degradation_flag": False, "low_signal_flag": False,
        "trade_log": [{"ticker": "MAVI", "signal_date": "2026-03-02", "entry_date": "2026-03-03",
                       "exit_date": "2026-03-10", "gross_return_pct": 2.0, "net_return_pct": 1.4}],
        "trade_log_truncated": False, "last_exit_date": "2026-09-04"},
    ToolName.CHECK_DATA_QUALITY: {
        "gate_status": "PASS_WITH_WARNINGS", "gate_reason": "1 yumuşak uyarı",
        "hard_blocks": [],
        "soft_warnings": [{"code": "PRICE_JUMP_OVER_LIMIT", "severity": "SOFT",
                           "message": "Olası düzeltilmemiş bedelsiz", "ticker": "THYAO", "date": "2025-06-01",
                           "value": 25.0}],
        "checks_run": ["PRICE_JUMPS"], "price_jump_limit_pct": 10.0,
        "issue_counts": {"PRICE_JUMP_OVER_LIMIT": 1},
        "ticker_reports": [{"ticker": "THYAO", "n_rows": 400, "first_date": "2024-01-02",
                            "last_date": "2026-09-10", "n_missing_trading_days": 0, "last_data_age_days": 0,
                            "max_abs_daily_return_pct": 25.0, "max_abs_daily_return_date": "2025-06-01",
                            "n_price_jumps_over_limit": 1}]},
    ToolName.BUILD_EVIDENCE_BUNDLE: {
        "analysis_id": "demo-001",
        "full_evidence_set": [{"evidence_id": "E1", "statement": "Örnek", "source_tool": "rank_sector_relative_strength",
                               "source_input_hash": _HASH,
                               "values": [{"name": "lag_score_pp", "value": -8.5, "unit": "pp"}]}],
        "committed_evidence_set": [{"evidence_id": "E1", "statement": "Örnek",
                                    "source_tool": "rank_sector_relative_strength", "source_input_hash": _HASH,
                                    "values": []}],
        "gate_status": "PASS_WITH_WARNINGS", "proposed_action": "WATCH"},
}

# Örnek zarflarda n_events (anlamlıysa)
_INDICATORS_FULL_RESULT: dict[str, Any] = {
    "ticker": "THYAO", "price_adjustment": "adjusted", "state_date": "2026-09-10", "n_bars_used": 900,
    "history_first_date": "2023-01-02", "first_valid_date": "2023-01-23",
    "columns_meta_included": True,
    "columns": [{"name": "RSI_14", "indicator": "RSI", "warmup_bars": 14, "first_valid_date": "2023-01-23",
                 "valid_at_as_of": True}],
    "invalid_columns_at_as_of": [],
    "latest": {"date": "2026-09-10", "close": 299.25, "values": {"RSI_14": 41.2}, "states": {}},
    "recent_rows": [{"date": "2026-09-09", "close": 301.0, "values": {"RSI_14": 44.0}, "states": {}}]}

_N_EVENTS = {ToolName.DETECT_REVERSAL_EVENTS: 11, ToolName.TEST_WEEKDAY_PATTERN: 4, ToolName.RUN_BACKTEST: 22,
             ToolName.CALCULATE_FUNDAMENTAL_CHANGE: 6, ToolName.RANK_SECTOR_RELATIVE_STRENGTH: 10,
             ToolName.GET_NEWS_EVENTS: 1}


def example_params(tool: ToolName) -> dict[str, Any]:
    """as_of eklenmiş, varsayılanlar açılmış (normalize) örnek params."""
    raw = {**copy.deepcopy(_PARAMS[tool]), "as_of": EXAMPLE_AS_OF}
    return validate_params(tool, raw).model_dump(mode="json")


def example_envelope(tool: ToolName | str) -> dict[str, Any]:
    tool = ToolName(tool)
    params = example_params(tool)
    return {
        "tool": tool.value,
        "schema_version": SCHEMA_VERSION,
        "params": params,
        "as_of": EXAMPLE_AS_OF,
        "data_version": EXAMPLE_DATA_VERSION,
        "input_hash": compute_input_hash(tool, params, EXAMPLE_DATA_VERSION),
        "results": copy.deepcopy(_RESULTS[tool]),
        "n_events": _N_EVENTS.get(tool),
        "n_excluded_incomplete_horizon": 0,
        "warnings": ["HISTORICAL_ONLY: Geçmiş kanıt; gelecek getiri garantisi değildir."],
        "status": "OK",
        "error": None,
    }


def example_envelope_indicators_full() -> dict[str, Any]:
    """calculate_indicators, kolon meta'lı (include_columns_meta=True) ve 5 geçmiş satırlı (last_n_rows=5) örnek zarf.

    Varsayılan örnek (example_envelope) hafiftir; kolon ısınma kuralları (1.1.0) bu varyant üzerinde sınanır."""
    tool = ToolName.CALCULATE_INDICATORS
    raw = {**copy.deepcopy(_PARAMS[tool]), "as_of": EXAMPLE_AS_OF, "include_columns_meta": True, "last_n_rows": 5}
    params = validate_params(tool, raw).model_dump(mode="json")
    env = example_envelope(tool)
    env.update(params=params, input_hash=compute_input_hash(tool, params, EXAMPLE_DATA_VERSION),
               results=copy.deepcopy(_INDICATORS_FULL_RESULT))
    return env


def example_rank_with_per_ticker(
    results: dict[str, Any], subject: str, *, cooldown_days: int = 20, n_raw_subject: int | None = None,
) -> dict[str, Any]:
    """Bir rank `results` sözlüğü için 1.2.0 alanlarını (per_ticker, n_raw_laggard_observations, cooldown_days,
    outcome_benchmark_definition) TUTARLI üretir; girdiyi DEĞİŞTİRMEZ (kopya döner). Sentetik zarf kuran testler/harness içindir.

    Kurallar: `per_ticker` ticker sıralı; aynalar (`is_laggard`, `lag_score_pp`) `ranking`'ten; ÖZNE havuzlu blokları taşır
    (IS/OOS ve `oos_degradation_flag` None; hisse bazlı blokta IS/OOS yok), DİĞERLERİ n=0 (baz n_obs=0). Böylece her ufukta
    Σ hisse = havuz. `n_raw_subject` verilmezse öznenin ham sayısı = bağımsız olay sayısı; diğerlerinde 0.
    `insufficient_peers` ise yeni alanlar None / [] döner (tek hisseli grup muafiyeti).
    Havuzlu bloklarda `n_events_complete + n_excluded_incomplete_horizon` ufuktan bağımsız sabit olmalı (şema kuralı), değilse ValueError.
    """
    res = copy.deepcopy(results)
    if res.get("insufficient_peers"):
        res.update(per_ticker=[], n_raw_laggard_observations=None, cooldown_days=None, outcome_benchmark_definition=None)
        return res
    rows = {r["ticker"]: r for r in res["ranking"]}
    if subject not in rows:
        raise ValueError(f"özne {subject!r} ranking içinde yok: {sorted(rows)}")
    pooled = res["historical_catch_up"]
    if not pooled:
        raise ValueError("historical_catch_up boş: hisse bazlı kırılım kurulamaz")
    totals = {r["block"]["full"]["n_events_complete"] + r["block"]["full"]["n_excluded_incomplete_horizon"] for r in pooled}
    if len(totals) != 1:
        raise ValueError(f"havuz blokları ufuklar arasında farklı bağımsız olay sayısı taşıyor: {sorted(totals)}")
    n_independent = totals.pop()
    longest = max(pooled, key=lambda r: r["block"]["horizon"])["block"]["full"]["n_excluded_incomplete_horizon"]
    raw_subject = n_independent if n_raw_subject is None else n_raw_subject
    if raw_subject < n_independent:
        raise ValueError("n_raw_subject bağımsız olay sayısından küçük olamaz")
    empty_full = {"n_events_complete": 0, "n_excluded_incomplete_horizon": 0, "n_success": 0, "n_false_positive": 0}
    per_ticker = []
    for t in sorted(rows):
        mine = t == subject
        per_horizon = []
        for r in pooled:
            b = r["block"]
            if mine:
                block = {**copy.deepcopy(b), "in_sample": None, "out_of_sample": None, "oos_degradation_flag": None}
                per_horizon.append({"block": block, "median_catch_up_size_pp": r.get("median_catch_up_size_pp")})
            else:
                per_horizon.append({"block": {"horizon": b["horizon"], "full": dict(empty_full), "in_sample": None,
                                              "out_of_sample": None, "baseline": {"n_obs": 0}}, "median_catch_up_size_pp": None})
        per_ticker.append({
            "ticker": t, "is_laggard": rows[t]["is_laggard"], "lag_score_pp": rows[t]["lag_score_pp"],
            "n_raw_laggard_observations": raw_subject if mine else 0,
            "n_independent_events": n_independent if mine else 0,
            "n_excluded_incomplete_horizon": longest if mine else 0, "per_horizon": per_horizon})
    res.update(per_ticker=per_ticker, n_raw_laggard_observations=raw_subject, cooldown_days=cooldown_days,
               outcome_benchmark_definition={**copy.deepcopy(res["benchmark_definition"]), "includes_subject_stock": False})
    return res


def example_error_envelope(tool: ToolName | str, code: str = "UNKNOWN_TICKER", message: str = "Bilinmeyen ticker") -> dict[str, Any]:
    env = example_envelope(tool)
    env.update({"results": None, "status": "ERROR", "error": {"code": code, "message": message}, "n_events": None})
    return env
