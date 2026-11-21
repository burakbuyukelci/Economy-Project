"""Colab'a yüklenecek TEK zip'i hazırlar: eğitim kodu (training/colab, harness/text_protocol.py) + train/val JSONL.

    python -m training.colab.make_bundle --data data/training/v1 --out colab_bundle.zip

Zip içeriği, Colab'da açıldığında depo düzenini taklit eder (training/, harness/); `train_qlora.py` bu düzene göre çalışır. Veri dosyaları zip'in köküne konur.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODE = ["training/__init__.py", "training/colab/__init__.py", "training/colab/data.py", "training/colab/train_qlora.py",
        "harness/__init__.py", "harness/text_protocol.py"]


def make_bundle(data_dir: Path, out: Path) -> list[str]:
    names: list[str] = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in CODE:
            src = REPO / rel
            if src.exists():
                z.write(src, rel)
                names.append(rel)
        for f in ("train.jsonl", "val.jsonl"):
            p = data_dir / f
            if not p.exists():
                raise FileNotFoundError(f"{p} yok: önce `python -m training.build_dataset` çalıştırın")
            z.write(p, f)
            names.append(f)
    return names


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/training/v1")
    ap.add_argument("--out", default="colab_bundle.zip")
    args = ap.parse_args(argv)
    names = make_bundle(Path(args.data), Path(args.out))
    print(f"{args.out}: {len(names)} dosya\n  " + "\n  ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
