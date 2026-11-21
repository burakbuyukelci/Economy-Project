"""A–E deney koşucusu (experiments/eval_runner.py): betikli SAHTE modellerle (Ollama gerekmez), GERÇEK araçlarla.

İyi model: öğretmen betiği (kurallara uygun, politika etiketi). Kötü model: tavsiye + uydurma sayı içeren ham cevap. Beklenti: D/E'de zorlama teslim metnini temizler,
A–C'de ham çıktı ölçülür; tüm metrikler satıra ve özete yazılır.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from experiments.eval_runner import CSV_COLUMNS, PROFILES, run_matrix, select_subset, summarize, write_outputs
from harness.llm_backend import ScriptedBackend
from training import spec
from training.questions import build_questions
from training.teacher import build_steps

needs_data = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists(), reason="data/snapshots yok")
BAD = "Bu hisse kesin yükselir, alın; hedef fiyat 350 TL ve %17,3 kazandırır.\nEYLEM: WATCH"


def items_and_questions(n=2):
    qs = build_questions("val", spec.SEED, {"weekday": n, "indicators": n})
    items = [{"id": q.id, "question": q.text, "type": q.type, "as_of": q.as_of.isoformat(), "label": None} for q in qs]
    return items, {q.text: q for q in qs}


def good_factory(by_text):
    """Profil D/E'de öğretmen betiği; A–C'de araç çağrısız tek cevap (iyi ama etiket bilinmeyen) yerine öğretmenin son metni kullanılamaz: kötü ham cevap verilir."""
    def factory(item, session):
        if session.profile.name in ("D", "E"):
            return ScriptedBackend(build_steps(by_text[item["question"]], session)[0])
        return ScriptedBackend([BAD])
    return factory


# =============================== alt küme ===============================
def test_subset_is_proportional_deterministic_and_never_larger_than_n():
    recs = [{"id": f"t{i:03d}", "type": "weekday" if i % 3 else "indicators", "question": "q", "label": "INVESTIGATE"} for i in range(60)]
    a = select_subset(recs, 12)
    assert a == select_subset(recs, 12) and len(a) <= 12 and {r["type"] for r in a} == {"weekday", "indicators"}
    types = [r["type"] for r in a]
    assert types.count("weekday") > types.count("indicators")                    # orantılı
    assert [r["id"] for r in a] == sorted(r["id"] for r in a)


# =============================== koşu ===============================
@needs_data
def test_matrix_rows_and_metrics_for_a_good_and_a_bad_model():
    items, by_text = items_and_questions()
    rows = run_matrix(items, PROFILES, {"iyi": good_factory(by_text)}, repeats=2)
    assert len(rows) == len(items) * len(PROFILES) * 2 and set(CSV_COLUMNS) <= set(rows[0]) | {"reproducible"}
    de = [r for r in rows if r["profile"] in ("D", "E")]
    assert all(r["status"] == "DELIVERED" and r["final_status"] == "ACCEPTED" for r in de)
    assert all(r["n_violations_delivered"] == 0 and r["n_hallucinated"] == 0 and r["action_matches_policy"] is True and r["fallback"] is False for r in de)
    assert all(r["n_invalid_calls"] == 0 and r["invalid_call_rate"] == 0.0 for r in de)
    ab = [r for r in rows if r["profile"] in ("A", "B")]
    assert all(r["final_status"] == "RECORDED" and r["n_violations_delivered"] >= 2 and r["advice_language"] == 1 for r in ab)
    assert all(r["n_hallucinated"] >= 1 and r["numerical_hallucination_rate"] > 0 for r in ab)
    c = [r for r in rows if r["profile"] == "C"]                       # C: kalite kapısını MODEL çağırmadan açıklama istedi -> reddedildi, betik bitti => ABORTED
    assert all(r["status"] == "ABORTED" and r["n_invalid_calls"] >= 1 and r["final_status"] is None for r in c)
    assert all(r["reproducible"] is True for r in rows)                            # belirlenimli sahte model: tekrarlar aynı
    assert all(r["max_prompt_tokens"] is None for r in rows)                      # sahte model gerçek prompt token vermez


@needs_data
def test_summary_aggregates_rates_per_model_and_profile():
    items, by_text = items_and_questions()
    rows = run_matrix(items, PROFILES, {"iyi": good_factory(by_text)})
    summ = summarize(rows)
    assert set(summ) == {f"iyi|{p}" for p in PROFILES}
    d, a = summ["iyi|D"], summ["iyi|A"]
    assert d["numerical_hallucination_rate"] == 0.0 and d["rule_violation_rate_delivered"] == 0.0 and d["advice_language_rate"] == 0.0
    assert d["action_matches_policy_rate"] == 1.0 and d["invalid_tool_call_rate"] == 0.0 and d["fallback_rate"] == 0.0
    assert a["numerical_hallucination_rate"] > 0 and a["rule_violation_rate_delivered"] == 1.0 and a["advice_language_rate"] == 1.0
    assert a["n_runs"] == len(items) and a["n_delivered"] == len(items) and a["unevidenced_rate"] is not None


@needs_data
def test_a_model_that_crashes_is_recorded_not_raised_and_outputs_are_written(tmp_path):
    from harness.llm_backend import LLMError

    items, by_text = items_and_questions(1)

    def broken(item, session):
        def boom(msgs, tools):
            raise LLMError("Ollama kapalı")
        return ScriptedBackend([boom])

    rows = run_matrix(items, ["A", "D"], {"bozuk": broken})
    assert {r["status"] for r in rows} == {"ABORTED"} and all(r["abort_reason"] == "MODEL_ERROR" for r in rows)
    summ = summarize(rows)
    assert summ["bozuk|A"]["n_error_or_aborted"] == len(items)
    write_outputs(tmp_path, rows, summ, {"n_questions": len(items)})
    with (tmp_path / "results.csv").open(encoding="utf-8") as fh:
        got = list(csv.DictReader(fh))
    assert len(got) == len(rows) and "numerical_hallucination_rate" in got[0]
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))["summary"]["bozuk|D"]["n_runs"] == len(items)


@needs_data
def test_real_tool_settings_are_restored_after_a_run():
    from harness import settings

    before = (dict(settings.TOOL_BACKEND_OVERRIDES), settings.EXPOSED_TOOLS)
    items, by_text = items_and_questions(1)
    run_matrix(items[:1], ["D"], {"iyi": good_factory(by_text)})
    assert (dict(settings.TOOL_BACKEND_OVERRIDES), settings.EXPOSED_TOOLS) == before
