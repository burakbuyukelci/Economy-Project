"""Colab DEĞERLENDİRME seti: paketleyici (içerik/dışlama), koşu planı (süre tahmini, bölme, kalibrasyon), notebook."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from experiments.colab import make_eval_bundle as MB
from experiments.colab import plan as PL
from experiments.eval_runner import select_subset

REPO = Path(__file__).resolve().parents[2]
has_questions = (REPO / "data" / "training" / "v2" / "test.jsonl").exists() and (REPO / "data" / "snapshots" / "LATEST").exists()


# =============================== paketleyici (sentetik depo) ===============================
def _fake_repo(root: Path) -> Path:
    def w(rel: str, text: str = "x") -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    for d in MB.CODE_DIRS:
        w(f"{d}/__init__.py")
        w(f"{d}/__pycache__/a.pyc")
    w("training/ollama/Modelfile", "FROM ./g.gguf")
    w("training/ollama/g.gguf", "binary")
    w("training/.cache/tokenizer.json")
    w("experiments/requirements.txt")
    w(".env", "EVDS_API_KEY=GIZLI")
    w(".env.example")
    w(".git/config")
    w("tests/test_x.py")
    w("reports/r.csv")
    w("data/raw/fundamentals_kap.csv")
    w("data/snapshots/LATEST", "snap_v2\n")
    w("data/snapshots/LATEST_FUNDAMENTALS", "fundamentals_v1\n")
    w("data/snapshots/snap_v2/stocks.parquet")
    w("data/snapshots/snap_v1/stocks.parquet")
    w("data/snapshots/fundamentals_v1/fundamentals.parquet")
    w("data/snapshots/fundamentals_old/fundamentals.parquet")
    for f in ("test.jsonl", "val.jsonl", "train.jsonl", "report.json", "manifest.json"):
        w(f"data/training/v2/{f}")
    return root


def test_bundle_contains_code_pointed_snapshots_and_questions_but_never_secrets_or_big_files(tmp_path):
    repo = _fake_repo(tmp_path / "repo")
    out = tmp_path / "b.zip"
    sizes = MB.make_bundle(out, repo)
    names = set(zipfile.ZipFile(out).namelist())
    assert {"harness/__init__.py", "tools/__init__.py", "training/ollama/Modelfile", "experiments/requirements.txt"} <= names
    assert {"data/snapshots/LATEST", "data/snapshots/LATEST_FUNDAMENTALS", "data/snapshots/snap_v2/stocks.parquet",
            "data/snapshots/fundamentals_v1/fundamentals.parquet"} <= names
    assert {"data/training/v2/test.jsonl", "data/training/v2/val.jsonl"} <= names
    assert not [n for n in names if n.startswith(".env") or "/.env" in n or n.startswith(".git") or ".git/" in n]
    assert not [n for n in names if n.endswith((".gguf", ".pyc", ".zip")) or "__pycache__" in n or ".cache" in n]
    assert not [n for n in names if n.startswith(("tests/", "reports/", "data/raw/"))]
    assert "data/snapshots/snap_v1/stocks.parquet" not in names and "data/snapshots/fundamentals_old/fundamentals.parquet" not in names
    assert "data/training/v2/train.jsonl" not in names
    assert sizes["total"]["files"] == len(names) and sizes["total"]["file_bytes"] == out.stat().st_size
    assert set(sizes) == {"code", "snapshots", "questions", "total"}


def test_bundle_fails_clearly_without_questions_or_with_dangling_pointer(tmp_path):
    repo = _fake_repo(tmp_path / "repo")
    (repo / "data/training/v2/test.jsonl").unlink()
    with pytest.raises(FileNotFoundError, match="build_dataset"):
        MB.collect(repo)
    repo2 = _fake_repo(tmp_path / "repo2")
    (repo2 / "data/snapshots/LATEST").write_text("snap_yok\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="snap_yok"):
        MB.collect(repo2)


def test_macro_pointer_is_included_when_present(tmp_path):
    repo = _fake_repo(tmp_path / "repo")
    (repo / "data/snapshots/LATEST_MACRO").write_text("macro_v1\n", encoding="utf-8")
    (repo / "data/snapshots/macro_v1").mkdir()
    (repo / "data/snapshots/macro_v1/macro.parquet").write_text("x", encoding="utf-8")
    names = {a for _, a, _ in MB.collect(repo)}
    assert {"data/snapshots/LATEST_MACRO", "data/snapshots/macro_v1/macro.parquet"} <= names


@pytest.mark.skipif(not has_questions, reason="data/training/v2 veya snapshot yok")
def test_real_bundle_is_self_sufficient_after_extraction(tmp_path):
    out = tmp_path / "eval.zip"
    MB.make_bundle(out)
    dest = tmp_path / "x"
    zipfile.ZipFile(out).extractall(dest)
    assert not (dest / ".env").exists() and not (dest / ".git").exists()
    code = ("from tools import get_stock_history; from experiments import eval_runner, check_template; from experiments.colab import plan; "
            "e = get_stock_history.run({'ticker':'THYAO','start':'2026-09-01','end':'2026-09-10','as_of':'2026-09-10'}); "
            "from tools import calculate_fundamental_change as C; f = C.run({'ticker':'TUPRS','as_of':'2026-09-10'}); "
            "print(e['status'], f['status'], e['data_version'])")
    r = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(dest)!r}); exec({code!r})"],
                       cwd=dest, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr[-800:]
    assert r.stdout.split()[:2] == ["OK", "OK"]


# =============================== koşu planı ===============================
def _rec(turns=4, prompt_chars=8000, asst_chars=600):
    msgs = [{"role": "user", "content": "s" * prompt_chars}]
    for _ in range(turns):
        msgs.append({"role": "assistant", "content": "a" * asst_chars})
        msgs.append({"role": "user", "content": "t" * 3000})
    msgs.append({"role": "assistant", "content": "f" * 1200})
    return {"id": "r", "type": "weekday", "text_messages": msgs, "question": "q", "label": "INVESTIGATE"}


def test_session_load_counts_turns_generation_and_prefix_cache():
    r = _rec()
    a = PL.session_load(r)
    b = PL.session_load(r, prefix_cache=False)
    assert a["turns"] == 5 and a["gen"] > 0 and a["final_gen"] == pytest.approx(1200 / 2.7 + 6)
    assert b["prompt"] > 2 * a["prompt"]                       # önbelleksiz: her turda tüm geçmiş yeniden işlenir
    assert b["gen"] == a["gen"]


def test_run_seconds_profile_a_is_cheapest_and_faster_gpus_are_faster():
    load = PL.session_load(_rec())
    t4, l4, a100 = (PL.run_seconds(load, "D", PL.SPEEDS[g]) for g in ("T4", "L4", "A100"))
    assert t4 > l4 > a100
    assert PL.run_seconds(load, "A", PL.SPEEDS["T4"]) < t4
    assert PL.run_seconds(load, "D", PL.SPEEDS["CPU"]) > 5 * t4      # CPU'da değerlendirme pratik değil


def test_estimate_applies_contingency_and_measured_overrides():
    recs = [_rec() for _ in range(10)]
    base = PL.estimate(recs, ["A", "D"], 2, "T4")
    raw_d = PL.run_seconds(PL.session_load(recs[0]), "D", PL.SPEEDS["T4"])
    assert base["seconds_per_run"]["D"] == pytest.approx(raw_d * PL.CONTINGENCY, abs=0.1)
    assert base["runs_total"] == 2 * 2 * 10 and base["calibrated_profiles"] == []
    cal = PL.estimate(recs, ["A", "D"], 2, "T4", measured={"D": 100.0})
    assert cal["seconds_per_run"]["D"] == 100.0 and cal["calibrated_profiles"] == ["D"]           # ölçüm paysız


def test_calibrated_reads_jsonl_needs_min_rows_and_ignores_broken_lines(tmp_path):
    p = tmp_path / "r.jsonl"
    rows = [{"profile": "D", "seconds": s} for s in (10, 20, 30)] + [{"profile": "A", "seconds": 5}]
    p.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"profile": "D", "sec', encoding="utf-8")
    assert PL.calibrated(p) == {"D": 20.0}                       # A yalnız 1 satır -> yok sayılır
    assert PL.calibrated(tmp_path / "yok.jsonl") == {} and PL.calibrated(None) == {}


def test_split_plan_keeps_each_session_under_budget():
    sp = PL.split_plan({"total_minutes": 222.0, "runs_total": 390}, 170.0)
    assert sp["sessions"] == 2 and sp["max_runs_per_session"] == 195 and sp["minutes_per_session"] == 111.0
    assert PL.split_plan({"total_minutes": 86.0, "runs_total": 390}, 170.0)["sessions"] == 1


def test_recommend_n_returns_the_largest_n_that_fits_the_total_budget():
    recs = [{**_rec(), "id": f"r{i:03d}", "type": "weekday" if i % 2 else "indicators"} for i in range(60)]
    profiles = ["A", "B", "C", "D", "E"]
    n_small = PL.recommend_n(recs, profiles, 2, "T4", 60.0, max_sessions=1)
    n_big = PL.recommend_n(recs, profiles, 2, "T4", 600.0, max_sessions=1)
    assert 0 < n_small < n_big <= 60
    assert PL.estimate(select_subset(recs, n_small), profiles, 2, "T4")["total_minutes"] <= 60.0


@pytest.mark.skipif(not has_questions, reason="data/training/v2 yok")
def test_real_questions_plan_t4_needs_two_sessions_and_a100_fits_in_one():
    q = REPO / "data/training/v2/test.jsonl"
    t4 = PL.estimate(PL.select_records(q, 40), list(PL.PROFILES), 2, "T4")
    a100 = PL.estimate(PL.select_records(q, 40), list(PL.PROFILES), 2, "A100")
    assert PL.split_plan(t4)["sessions"] >= 2 and PL.split_plan(a100)["sessions"] == 1
    assert t4["total_minutes"] > a100["total_minutes"] * 2


# =============================== notebook ===============================
def test_notebook_is_valid_and_wires_every_step():
    nb = json.loads((REPO / "experiments" / "colab" / "eval_ollama.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    for needle in ("nvidia-smi", "ollama.com/install.sh", "'ollama','serve'", "ollama pull gemma3:4b", "ollama create gemma3-bist -f Modelfile",
                   "experiments.check_template", "experiments.colab.plan", "experiments.eval_runner", "--max-runs", "HARNESS_LLM_TIMEOUT",
                   "drive.mount", "results.jsonl", "files.download", "--models gemma3:4b gemma3-bist", "A B C D E"):
        assert needle in src, needle
    assert "127.0.0.1" in src                                         # yalnızca yerel sunucu
