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


# =============================== dayanıklılık: satır satır yazma, devam, bütçe, süre log'u ===============================
from experiments.eval_runner import RowSink, load_prior, main as eval_main, row_key  # noqa: E402


@needs_data
def test_rows_are_written_after_each_session_and_a_resumed_run_skips_finished_rows(tmp_path):
    items, by_text = items_and_questions(2)
    sink = RowSink(tmp_path)
    logs: list[str] = []
    rows1 = run_matrix(items, ["D"], {"iyi": good_factory(by_text)}, progress=logs.append, on_row=sink)
    n = len(items)
    assert len(rows1) == n and len(load_prior(tmp_path)) == n
    with (tmp_path / "results.csv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == n
    assert all("sn" in m and "tahmini kalan" in m for m in logs) and logs[-1].startswith(f"[{n}/{n}]")
    # yeniden başlat: aynı matris + bir profil daha; biten iki satır koşmaz, yalnız yenisi koşar
    calls: list[str] = []

    def counting(item, session):
        calls.append(f"{session.profile.name}:{item['id']}")
        return good_factory(by_text)(item, session)

    rows2 = run_matrix(items, ["D", "E"], {"iyi": counting}, prior_rows=load_prior(tmp_path), on_row=sink)
    assert len(rows2) == 2 * n and all(c.startswith("E:") for c in calls) and len(calls) == n
    assert len({row_key(r) for r in rows2}) == 2 * n
    assert len(load_prior(tmp_path)) == 2 * n


def test_truncated_last_jsonl_line_is_ignored_on_resume(tmp_path):
    (tmp_path / "results.jsonl").write_text('{"model": "m", "profile": "A", "question_id": "q", "repeat": 0}\n{"model": "m", "pro', encoding="utf-8")
    assert [row_key(r) for r in load_prior(tmp_path)] == [("m", "A", "q", 0)]


def test_row_sink_reset_and_fsync_append_only(tmp_path):
    sink = RowSink(tmp_path)
    sink({"model": "m", "profile": "A", "question_id": "q1", "repeat": 0, "status": "DELIVERED"})
    sink({"model": "m", "profile": "A", "question_id": "q2", "repeat": 0, "status": "DELIVERED"})
    assert len(load_prior(tmp_path)) == 2
    assert (tmp_path / "results.csv").read_text(encoding="utf-8").count("\n") == 3   # başlık + 2 satır
    RowSink(tmp_path, reset=True)
    assert not (tmp_path / "results.jsonl").exists() and not (tmp_path / "results.csv").exists()


@needs_data
def test_main_max_runs_splits_a_run_into_two_invocations_and_completes_summary(tmp_path, monkeypatch):
    items, by_text = items_and_questions(2)
    qfile = tmp_path / "q.jsonl"
    qfile.write_text("\n".join(json.dumps({"id": i["id"], "question": i["question"], "type": i["type"], "as_of": i["as_of"], "label": None}) for i in items) + "\n",
                     encoding="utf-8")
    import experiments.eval_runner as ER
    monkeypatch.setattr(ER, "select_subset", lambda recs, n: recs)

    class FakeBackend:
        def __init__(self, **kw): pass
    import harness.llm_backend as LB
    monkeypatch.setattr(LB, "OllamaBackend", lambda **kw: ScriptedBackend([BAD]))
    out = tmp_path / "out"
    argv = ["--questions", str(qfile), "--models", "fake", "--profiles", "A", "--out", str(out)]
    assert eval_main(argv + ["--max-runs", "1"]) == 0
    meta = json.loads((out / "summary.json").read_text(encoding="utf-8"))["meta"]
    assert meta["interrupted"] == "max-runs" and meta["n_rows"] == 1 and meta["complete"] is False
    assert eval_main(argv) == 0   # ikinci çağrı kaldığı yerden devam eder
    meta = json.loads((out / "summary.json").read_text(encoding="utf-8"))["meta"]
    assert meta["n_rows"] == len(items) and meta["complete"] is True and meta["interrupted"] is None
    with (out / "results.csv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == len(items)


# =============================== HARNESS_LLM_TIMEOUT ve num_predict ===============================
def test_llm_timeout_env_overrides_the_default_and_validates(monkeypatch):
    from harness import settings
    monkeypatch.delenv("HARNESS_LLM_TIMEOUT", raising=False)
    assert settings.llm_timeout() == settings.LLM_TIMEOUT_S
    monkeypatch.setenv("HARNESS_LLM_TIMEOUT", "900")
    assert settings.llm_timeout() == 900.0
    from harness.llm_backend import OllamaBackend
    assert OllamaBackend(host="http://127.0.0.1:11434", model="m").timeout == 900.0
    assert OllamaBackend(host="http://127.0.0.1:11434", model="m", timeout=5).timeout == 5
    for bad in ("abc", "0", "-3"):
        monkeypatch.setenv("HARNESS_LLM_TIMEOUT", bad)
        with pytest.raises(ValueError):
            settings.llm_timeout()


def test_check_template_requests_num_predict_one_on_both_paths():
    """Şablon denetimi yalnız prompt_eval_count ister: hem raw hem sohbet yolunda num_predict=1 (tam yanıt üretmek CPU'da dakikalar sürer)."""
    import io
    import urllib.request

    from harness.llm_backend import OllamaBackend

    bodies: list[dict] = []

    class Resp(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(self, req, timeout=None):
        bodies.append(json.loads(req.data.decode("utf-8")))
        payload = {"message": {"role": "assistant", "content": "x"}, "prompt_eval_count": 7}
        return Resp(json.dumps(payload).encode("utf-8"))

    b = OllamaBackend(host="http://127.0.0.1:11434", model="m", tool_mode="native", max_new_tokens=1)
    b._opener = type("O", (), {"open": fake_open})()
    assert b.raw_prompt_tokens("merhaba") == 7
    b.chat([{"role": "user", "content": "merhaba"}], None)
    assert [x["options"]["num_predict"] for x in bodies] == [1, 1]
    # varsayılan sohbet çağrısı sınırsızdır (num_predict gönderilmez)
    bodies.clear()
    OllamaBackend(host="http://127.0.0.1:11434", model="m", tool_mode="native")
    b2 = OllamaBackend(host="http://127.0.0.1:11434", model="m", tool_mode="native")
    b2._opener = b._opener
    b2.chat([{"role": "user", "content": "x"}], None)
    assert "num_predict" not in bodies[0]["options"]
    import experiments.check_template as CT
    assert "max_new_tokens=1" in Path(CT.__file__).read_text(encoding="utf-8")
