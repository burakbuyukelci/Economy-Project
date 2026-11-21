"""Harness test kurucularının şema 1.3.0 değişmezleri.

Şema 1.3.0 reversal grubunda çapraz doğrulayıcı BİLİNÇLİ olarak yok (harness kurucuları `n_events_detected`'ı değiştirdiği için kırılırdı).
Kurucular artık tutarlı: aşağıdaki kurallar hem kurucularda hem GERÇEK araç zarflarında geçerlidir => `schemas/` sahibine (Bilgisayar 1) çapraz
doğrulayıcıyı şemaya geri eklemesi önerilir (docs/harness_design.md 13.3). Kural referansı `reversal_group_problems` burada tanımlıdır.
"""
from __future__ import annotations

import pytest

from policy_builders import backtest_env, reversal_env
from schemas.enums import ToolName as T
from schemas.examples import example_params


def reversal_group_problems(g: dict) -> list[str]:
    """Önerilen şema kuralı: ham olay günü >= olay sayısı; çakışan pencere <= olay sayısı - 1 (olay yoksa 0)."""
    n, raw, ov = g["n_events_detected"], g.get("n_raw_event_days"), g.get("n_overlapping_forward_windows")
    out = []
    if raw is None or ov is None:
        return ["1.3.0'da iki alan da dolu olmalı"]
    if raw < n:
        out.append(f"n_raw_event_days ({raw}) < n_events_detected ({n})")
    if ov > max(n - 1, 0):
        out.append(f"n_overlapping_forward_windows ({ov}) > n_events_detected - 1 ({n - 1})")
    return out


@pytest.mark.parametrize("n_detected,event_date", [(30, "2026-09-09"), (0, None), (1, "2026-09-09"), (19, "2026-09-01"), (22, "2026-09-09")])
def test_reversal_builder_groups_satisfy_the_proposed_cross_validation(n_detected, event_date):
    env = reversal_env(n_detected=n_detected, event_date=event_date)
    for g in env["results"]["groups"]:
        assert reversal_group_problems(g) == [], (n_detected, g["n_raw_event_days"], g["n_overlapping_forward_windows"])


def test_real_reversal_groups_satisfy_the_same_rule():
    from pathlib import Path

    if not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import detect_reversal_events

    for ticker in ("ASELS", "THYAO", "BIMAS"):
        for family in ("BB_LOWER_TOUCH", "RSI_LOCAL_TROUGH"):
            env = detect_reversal_events.run({**example_params(T.DETECT_REVERSAL_EVENTS), "ticker": ticker, "event_family": family})
            assert env["status"] == "OK"
            for g in env["results"]["groups"]:
                assert reversal_group_problems(g) == [], (ticker, family)


def test_the_rule_actually_rejects_inconsistent_groups():
    assert reversal_group_problems({"n_events_detected": 10, "n_raw_event_days": 9, "n_overlapping_forward_windows": 0})
    assert reversal_group_problems({"n_events_detected": 10, "n_raw_event_days": 12, "n_overlapping_forward_windows": 10})
    assert reversal_group_problems({"n_events_detected": 0, "n_raw_event_days": 0, "n_overlapping_forward_windows": 1})
    assert reversal_group_problems({"n_events_detected": 10, "n_raw_event_days": None, "n_overlapping_forward_windows": 2})


def test_backtest_builder_keeps_last_exit_date_not_after_as_of_and_not_before_the_trade_log():
    env = backtest_env()
    res = env["results"]
    assert res["last_exit_date"] is not None and res["last_exit_date"] <= env["as_of"]
    assert res["last_exit_date"] >= max(t["exit_date"] for t in res["trade_log"])
    assert res["n_winning_trades"] + res["n_losing_trades"] > 0
