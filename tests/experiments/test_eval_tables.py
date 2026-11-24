"""Rapor tabloları: sayılar summary/results dosyasından birebir gelir (elle kopyalama yok)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from experiments.eval_tables import main, table_9_1, table_types, type_breakdown

S = {"n_delivered": 30, "n_runs": 40, "numerical_hallucination_rate": 0.0, "invalid_tool_call_rate": 0.8664, "unevidenced_rate": 0.1178,
     "rule_violation_rate_delivered": 0.0, "rule_violation_rate_attempts": 0.3158, "advice_language_rate": 0.0, "mandatory_step_skipped_rate": 0.0,
     "fallback_rate": 0.1333, "action_matches_policy_rate": 1.0, "action_matches_expected_rate": 0.8, "max_prompt_tokens": 8181, "mean_seconds": 30.78}


def test_table_has_exact_numbers_and_repro_only_where_given():
    md = table_9_1({"gemma3-bist|D": S, "gemma3-bist|A": {**S, "n_delivered": 40}}, {"gemma3-bist|D": {"reproducibility_rate": 0.4737}})
    assert "30/40" in md and "%86.6" in md and "%11.8" in md and "%47.4" in md and "8181" in md and "30.8" in md
    a_row = next(line for line in md.splitlines() if line.startswith("| gemma3-bist | A "))
    assert "%47.4" not in a_row                                  # tekrarlanabilirlik yalnızca verilen profilde


def test_type_breakdown_and_table(tmp_path: Path):
    p = tmp_path / "results.csv"
    with p.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["model", "profile", "type", "status"])
        w.writeheader()
        for t, st in (("weekday", "DELIVERED"), ("weekday", "DELIVERED"), ("reversal", "ABORTED"), ("reversal", "DELIVERED")):
            w.writerow({"model": "gemma3-bist", "profile": "D", "type": t, "status": st})
        w.writerow({"model": "gemma3:4b", "profile": "D", "type": "weekday", "status": "ABORTED"})
    bd = type_breakdown(p, "gemma3-bist", "D")
    assert bd == {"reversal": (1, 2), "weekday": (2, 2)}
    md = table_types({"eski": bd, "yeni": {"weekday": (1, 2)}})
    assert "| weekday | 2/2 | 1/2 |" in md and "| reversal | 1/2 | – |" in md and "**3/4**" in md


def test_cli_runs_on_directory(tmp_path: Path, capsys):
    (tmp_path / "summary.json").write_text(json.dumps({"meta": {}, "summary": {"gemma3-bist|D": S}}), encoding="utf-8")
    with (tmp_path / "results.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["model", "profile", "type", "status"])
        w.writeheader()
        w.writerow({"model": "gemma3-bist", "profile": "D", "type": "weekday", "status": "DELIVERED"})
    assert main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "30/40" in out and "| weekday |" in out
