"""Kaggle not defteri: geçerli JSON, kullandığı bayraklar train_qlora.py'de var, Colab'a özgü çağrı yok."""
from __future__ import annotations

import json
import re
from pathlib import Path

NB = Path("training/kaggle/train_qlora_kaggle.ipynb")
SCRIPT = Path("training/colab/train_qlora.py").read_text(encoding="utf-8")


def _code():
    nb = json.loads(NB.read_text(encoding="utf-8"))
    return ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


def test_notebook_flags_exist_in_training_script():
    defined = set(re.findall(r'add_argument\("(--[a-z-]+)"', SCRIPT))
    used = {f for src in _code() for line in src.splitlines() if line.startswith("!") and "train_qlora.py" in line for f in re.findall(r"(--[a-z][a-z-]*)", line)}
    assert used and used <= defined, used - defined


def test_notebook_pins_single_gpu_and_has_no_colab_only_calls():
    src = "\n".join(_code())
    assert "google.colab" not in src and "/content/" not in src
    assert all("CUDA_VISIBLE_DEVICES=0" in l for s in _code() for l in s.splitlines() if l.startswith("!") and "train_qlora.py" in l)
    assert "--out /tmp/" in src and "/kaggle/working/ckpt" in src   # büyük dosyalar /tmp'de, kontrol noktası kalıcı klasörde
