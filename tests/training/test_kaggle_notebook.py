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


def test_bf16_requires_native_hardware_support_not_emulation():
    """Kaggle'ın yeni torch'unda T4'te is_bf16_supported() emülasyonla True döner (çok yavaş); yalnızca compute capability >= 8 bf16 sayılır."""
    from training.colab.compat import bf16_native

    assert bf16_native((7, 5), True) is False      # T4 (emülasyon True dese de)
    assert bf16_native((6, 0), True) is False      # P100
    assert bf16_native((8, 0), True) is True       # A100
    assert bf16_native((8, 9), True) is True       # L4
    assert bf16_native((8, 0), False) is False     # torch desteklemiyorsa asla
    assert "bf16_native(" in SCRIPT and "torch.cuda.is_bf16_supported()\n" not in SCRIPT.replace("torch.cuda.is_bf16_supported())", "")
