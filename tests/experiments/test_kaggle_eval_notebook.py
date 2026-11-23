"""Kaggle değerlendirme not defteri: geçerli JSON, bayraklar koşucuda var, Colab'a özgü çağrı yok, v2.2 sorularını kullanır."""
from __future__ import annotations

import json
import re
from pathlib import Path

NB = Path("experiments/kaggle/eval_ollama_kaggle.ipynb")
RUNNER = Path("experiments/eval_runner.py").read_text(encoding="utf-8")
PLAN = Path("experiments/colab/plan.py").read_text(encoding="utf-8")
CHECK = Path("experiments/check_template.py").read_text(encoding="utf-8")


def _code() -> str:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    return "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")


def _flags(src: str, module: str) -> set[str]:
    return {f for line in src.splitlines() if line.startswith("!") and module in line for f in re.findall(r"(--[a-z][a-z-]*)", line)}


def test_commands_only_use_flags_that_exist():
    src = _code()
    for module, text in (("experiments.eval_runner", RUNNER), ("experiments.colab.plan", PLAN), ("experiments.check_template", CHECK)):
        used = _flags(src, module)
        defined = set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', text))
        assert used and used <= defined, (module, used - defined)


def test_no_colab_only_calls_and_uses_v2_2_questions_and_local_ollama():
    src = _code()
    assert "google.colab" not in src and "/content/" not in src
    assert "data/training/v2_2/test.jsonl" in src and "data/training/v2_2/val.jsonl" in src
    assert "127.0.0.1" in src and "CUDA_VISIBLE_DEVICES" in src
    assert "--profiles A B C D E" in src and "gemma3:4b gemma3-bist" in src


def test_eval_bundle_makes_questions_dir_selectable():
    assert "--questions" in Path("experiments/colab/make_eval_bundle.py").read_text(encoding="utf-8")


def test_notebook_handles_a_dataset_whose_zip_kaggle_already_extracted():
    """Kaggle veri setine yüklenen zip'i otomatik açar (126 ayrı dosya); not defteri zip'i de, açılmış ağacı da bulmalı (2026-11-23: zip aranıp bulunamadı)."""
    src = _code()
    assert "eval_bundle.zip" in src and "harness/__init__.py" in src and "copytree" in src and "assert roots" in src
