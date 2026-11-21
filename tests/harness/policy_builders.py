"""label_policy testleri için ŞEMAYA UYGUN sentetik araç zarfları (schemas.examples tabanlı; her biri validate_envelope'tan geçer).

Değerler uydurmadır; yalnızca politikanın karar tablosunu sınamak içindir (eğitim verisine girmez: data_version mock değil ama
zarflar sentetiktir ve yalnızca testlerde kullanılır).
"""
from __future__ import annotations

import copy
import hashlib
from typing import Any

from schemas import examples as ex
from schemas.enums import ToolName as T
from schemas.registry import validate_envelope

AS_OF = "2026-09-10"


def _hash(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()


def finish(env: dict[str, Any], tag: str) -> dict[str, Any]:
    env["input_hash"] = _hash(tag)
    validate_envelope(env)  # sentetik zarf bile sözleşmeyi bozamaz
    return env


def stats(n: int, hit: float | None, cost: float | None, mean: float | None = 1.0, excl: int = 0) -> dict[str, Any]:
    d = copy.deepcopy(ex._STATS)
    succ = round(n * hit / 100) if hit is not None else 0
    d.update(n_events_complete=n, n_excluded_incomplete_horizon=excl, n_success=succ, n_false_positive=n - succ,
             hit_rate_pct=hit, false_positive_rate_pct=None if hit is None else round(100 - hit, 4),
             mean_return_pct=None if n == 0 else mean, median_return_pct=None if n == 0 else d["median_return_pct"],
             cost_adjusted_mean_return_pct=cost, mean_reversal_strength_pct=None, median_reversal_strength_pct=None)
    return d


def block(h: int, *, n: int = 40, hit: float | None = 60.0, base: float = 50.0, cost: float | None = 0.8,
          is_: tuple[int, float, float] | None = (30, 60.0, 0.9), oos: tuple[int, float, float] | None = (10, 60.0, 0.7),
          flag: bool | None = False, excl: int = 0) -> dict[str, Any]:
    """excl: ufku as_of'u aşan dışlanan olay sayısı. Havuzlu rank bloklarında n + excl ufuklar arasında SABİT olmalı (şema 1.2.0)."""
    b = copy.deepcopy(ex._BLOCK)
    b.update(horizon=h, full=stats(n, hit, cost, excl=excl), in_sample=stats(*is_) if is_ else None,
             out_of_sample=stats(*oos) if oos else None, oos_degradation_flag=flag,
             baseline={"n_obs": 1000, "mean_return_pct": 0.0, "median_return_pct": 0.0, "hit_rate_pct": base},
             mean_diff_vs_baseline_pct=0.5, median_diff_vs_baseline_pct=0.4)
    return b


# ---------------------------------------------------------------- rank_sector_relative_strength
def rank_env(*, tag: str = "rank", peers: int = 3, insufficient: bool = False, strength: str | None = "STRONG",
             subject_lag: float = -8.0, laggard: bool = True, blocks: list[dict[str, Any]] | None = None,
             subject: str = "MAVI") -> dict[str, Any]:
    env = ex.example_envelope(T.RANK_SECTOR_RELATIVE_STRENGTH)
    res = env["results"]
    rows = [
        {"rank": 1, "ticker": "BIMAS", "return_pct": 15.0, "lag_score_pp": 3.0, "return_vs_xu100_pp": 11.0,
         "is_laggard": False, "is_leader": True},
        {"rank": 2, "ticker": "MGROS", "return_pct": 12.0, "lag_score_pp": 0.0, "return_vs_xu100_pp": 8.0,
         "is_laggard": False, "is_leader": False},
        {"rank": 3, "ticker": subject, "return_pct": 4.0, "lag_score_pp": subject_lag, "return_vs_xu100_pp": 0.0,
         "is_laggard": laggard, "is_leader": False},
    ]
    res.update(peer_group_size=peers, insufficient_peers=insufficient, sector_strength=strength, ranking=rows,
               historical_catch_up=[{"block": b, "median_catch_up_size_pp": 2.0}
                                    for b in (blocks if blocks is not None else [block(5), block(10), block(20)])])
    # şema 1.2.0: per_ticker / n_raw / cooldown / benchmark tanımı TUTARLI üretilir (özne havuzlu blokları taşır, diğerleri n=0)
    env["results"] = ex.example_rank_with_per_ticker(res, subject)
    return finish(env, tag)


# ---------------------------------------------------------------- run_backtest
def backtest_env(*, tag: str = "bt", signal_type: str = "CATCH_UP", universe: tuple[str, ...] = ("BIMAS", "MAVI", "MGROS"),
                 test_diff: float | None = 1.5, low_signal: bool = False, flag: bool | None = False,
                 n_signals: int = 30) -> dict[str, Any]:
    env = ex.example_envelope(T.RUN_BACKTEST)
    res = env["results"]
    res["strategy"]["signal_type"] = signal_type
    res["universe"] = list(universe)
    res.update(n_signals=n_signals, low_signal_flag=low_signal, oos_degradation_flag=flag)
    if test_diff is None:
        res["splits"] = []
    else:
        res["splits"][0]["benchmark_diff_pct"] = test_diff
    return finish(env, tag)


# ---------------------------------------------------------------- test_weekday_pattern
def weekday_env(verdict: str = "STABLE", codes: list[str] | None = None, *, tag: str = "wk", ticker: str = "THYAO") -> dict[str, Any]:
    env = ex.example_envelope(T.TEST_WEEKDAY_PATTERN)
    res = env["results"]
    res["ticker"] = ticker
    res["stability_verdict"] = verdict
    res["verdict_codes"] = codes if codes is not None else ([] if verdict == "STABLE" else ["IS_TOO_FEW"])
    res["verdict_reason"] = "; ".join(f"{c}: örnek" for c in res["verdict_codes"])
    return finish(env, tag)


# ---------------------------------------------------------------- detect_reversal_events
def reversal_env(*, tag: str = "rev", ticker: str = "ASELS", n_detected: int = 30, event_date: str | None = "2026-09-09",
                 blocks: list[dict[str, Any]] | None = None, label: str = "single_indicator") -> dict[str, Any]:
    env = ex.example_envelope(T.DETECT_REVERSAL_EVENTS)
    res = env["results"]
    res["ticker"] = ticker
    g = res["groups"][0]
    g["label"] = label
    g["conditions"] = None if label == "single_indicator" else g["conditions"]
    g["n_events_detected"] = n_detected
    # şema 1.3.0: ham olay günü >= olay sayısı, çakışan pencere <= olay sayısı - 1 (araç kuralı; şema çapraz doğrulayıcısı YOK, test_builder_invariants denetler)
    g["n_raw_event_days"] = n_detected + (n_detected // 2)
    g["n_overlapping_forward_windows"] = max(0, min(n_detected - 1, n_detected // 3))
    g["per_horizon"] = blocks if blocks is not None else [block(1), block(3), block(5), block(10)]
    ev = copy.deepcopy(g["events"][0])
    ev["date"] = event_date or "2026-09-01"
    g["events"] = [ev] if event_date and n_detected else []
    return finish(env, tag)


# ---------------------------------------------------------------- calculate_fundamental_change
def fundamental_env(*, tag: str = "fc", ticker: str = "TUPRS", n_quarters: int = 6, tms29: bool = True,
                    improvement_metric: str = "EBITDA_MARGIN", basis: str = "YOY", yoy: str | None = "IMPROVED",
                    qoq: str | None = "IMPROVED", secondary: str | None = "IMPROVED",
                    reaction_mean: float | None = 0.8) -> dict[str, Any]:
    env = ex.example_envelope(T.CALCULATE_FUNDAMENTAL_CHANGE)
    res = env["results"]
    res.update(ticker=ticker, improvement_metric=improvement_metric, improvement_basis=basis,
               n_quarters_disclosed_by_as_of=n_quarters)
    q = res["quarters"][0]
    q["tms29_comparable"] = tms29
    metrics = [{"name": improvement_metric, "value": 8.5, "qoq_change": 0.4, "yoy_change": 1.2, "change_unit": "PP",
                "qoq_direction": qoq, "yoy_direction": yoy}]
    if secondary is not None:
        metrics.append({"name": "NET_DEBT_EBITDA", "value": 1.1, "qoq_change": -0.1, "yoy_change": -0.2,
                        "change_unit": "ABS", "qoq_direction": secondary, "yoy_direction": secondary})
    q["metrics"] = metrics
    if reaction_mean is not None:
        res["reaction_summary"][0]["mean_abnormal_vs_xu100_pct"] = reaction_mean
    return finish(env, tag)


def macro_env(tag: str = "macro") -> dict[str, Any]:
    return finish(ex.example_envelope(T.GET_MACRO_CONTEXT), tag)


def history_env(tag: str = "hist") -> dict[str, Any]:
    return finish(ex.example_envelope(T.GET_STOCK_HISTORY), tag)
