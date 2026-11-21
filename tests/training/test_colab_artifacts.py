"""Colab/Ollama çıktılarının kendi kendine tutarlılığı (GPU/Ollama olmadan): not defteri, paket, Modelfile, eğitim betiği."""
from __future__ import annotations

import json
import py_compile
import zipfile
from pathlib import Path

from harness.text_protocol import STOP_SEQUENCES

REPO = Path(__file__).resolve().parents[2]


def test_notebook_is_valid_and_runs_the_documented_commands():
    nb = json.loads((REPO / "training" / "colab" / "train_qlora.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4 and nb["metadata"]["colab"]["gpuType"] == "T4"
    src = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    assert "pip install -q unsloth" in src and "colab_bundle.zip" in src and "--dry-run" in src
    assert "--gguf q4_k_m" in src and "train.jsonl" in src and "val.jsonl" in src and "files.download" in src


def test_train_script_compiles_and_has_the_agreed_defaults():
    p = REPO / "training" / "colab" / "train_qlora.py"
    py_compile.compile(str(p), doraise=True)
    text = p.read_text(encoding="utf-8")
    assert 'DEFAULT_MODEL = "unsloth/gemma-3-4b-it"' in text and "load_in_4bit=True" in text and "default=8192" in text
    assert "train_on_responses_only" not in text           # kayıp maskesi KENDİ mantığımız (hatalı turlar da maskelenir)
    assert "skip_prepare_dataset" in text and "PadCollator" in text and "save_pretrained_gguf" in text


def test_bundle_contains_code_and_data_and_fails_without_data(tmp_path):
    import pytest

    from training.colab.make_bundle import make_bundle

    data = tmp_path / "d"
    data.mkdir()
    with pytest.raises(FileNotFoundError):
        make_bundle(data, tmp_path / "b.zip")
    (data / "train.jsonl").write_text("{}\n", encoding="utf-8")
    (data / "val.jsonl").write_text("{}\n", encoding="utf-8")
    names = make_bundle(data, tmp_path / "b.zip")
    with zipfile.ZipFile(tmp_path / "b.zip") as z:
        assert set(z.namelist()) == set(names)
    assert {"training/colab/data.py", "training/colab/train_qlora.py", "harness/text_protocol.py", "train.jsonl", "val.jsonl"} <= set(names)


def test_modelfile_template_matches_the_training_layout_and_stops():
    mf = (REPO / "training" / "ollama" / "Modelfile").read_text(encoding="utf-8")
    body = mf.split('TEMPLATE """', 1)[1].split('"""', 1)[0]
    assert "<start_of_turn>user" in body and "<start_of_turn>model" in body and "<end_of_turn>" in body
    assert "<bos>" not in body                                                             # GGUF tokenizer BOS'u kendisi ekler
    assert 'PARAMETER stop "<end_of_turn>"' in mf and all(f'PARAMETER stop "{s}"' in mf for s in STOP_SEQUENCES)
    assert "PARAMETER temperature 0" in mf and "FROM ./gemma3-bist-q4_k_m.gguf" in mf


def test_readme_documents_every_command_it_relies_on():
    rd = (REPO / "training" / "README.md").read_text(encoding="utf-8")
    for needle in ("python -m training.build_dataset", "python -m training.colab.make_bundle", "train_qlora.ipynb", "ollama create gemma3-bist",
                   "experiments.check_template", "experiments.eval_runner", "seq", "8192", "6144", "T4", "--tight"):
        assert needle in rd, needle


def test_version_dependent_arguments_are_detected_with_inspect_not_try_except():
    text = (REPO / "training" / "colab" / "train_qlora.py").read_text(encoding="utf-8")
    assert "first_supported(SFTConfig" in text and "first_supported(model.save_pretrained_gguf" in text
    assert "except TypeError" not in text


def test_first_supported_picks_the_argument_name_the_installed_version_has():
    import dataclasses

    from training.colab.compat import first_supported, kwargs_for, supported_names

    def old(a, max_seq_length=1): ...
    def new(a, *, max_length=1): ...
    def neither(a, **kw): ...
    assert first_supported(old, ("max_seq_length", "max_length")) == "max_seq_length"
    assert first_supported(new, ("max_seq_length", "max_length")) == "max_length"
    assert first_supported(neither, ("max_seq_length", "max_length")) is None and supported_names(neither)[1] is True

    @dataclasses.dataclass
    class Cfg:
        max_length: int = 1
    assert first_supported(Cfg, ("max_seq_length", "max_length")) == "max_length"
    assert kwargs_for(Cfg, seq=("max_seq_length", "max_length"), x=("zzz",)) == {"seq": "max_length", "x": None}
