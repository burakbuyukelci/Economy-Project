"""Colab DEĞERLENDİRME paketi: repo kodu + fiyat/bilanço/makro snapshot'ları + değerlendirme soruları -> TEK zip.

    python -m experiments.colab.make_eval_bundle --out eval_bundle.zip [--questions data/training/v2]

İçerik (Colab'da açılınca depo düzenini taklit eder; `python -m experiments.eval_runner` doğrudan çalışır):
  * kod: harness/, schemas/, tools/, config/, training/ (ollama/Modelfile dahil; .cache, çıktı klasörleri ve *.gguf HARİÇ), experiments/, scripts/ (veri indirici DEĞİL gerekmez ama
    config/tools bazı sabitler için import edebilir: küçük, dahil)
  * veri: data/snapshots/ altında YALNIZCA `LATEST`, `LATEST_FUNDAMENTALS`, `LATEST_MACRO` (varsa) işaretçilerinin gösterdiği sürümler (v1 ham kaynak GEREKMEZ)
  * sorular: <questions>/test.jsonl ve val.jsonl (+ report.json, manifest.json); train.jsonl DAHİL DEĞİL (değerlendirmede gerekmez, büyük)
HARİÇ: .git, .env* (anahtarlar), .venv, __pycache__, tests/, reports/, data/raw, *.zip, *.gguf, *.safetensors. GGUF (ince ayarlı model) pakete GİRMEZ: Drive'dan ya da yüklemeyle (notebook).
Çalıştırınca boyutları (ham/sıkıştırılmış, bölüm bazında) raporlar.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODE_DIRS = ("harness", "schemas", "tools", "config", "training", "experiments", "scripts")
SKIP_DIR_NAMES = {".git", ".venv", "__pycache__", ".cache", ".pytest_cache", "output", "checkpoints", "colab_outputs"}
SKIP_SUFFIXES = {".pyc", ".zip", ".gguf", ".safetensors", ".bin", ".pt", ".pth", ".ckpt"}
POINTERS = ("LATEST", "LATEST_FUNDAMENTALS", "LATEST_MACRO")
QUESTION_FILES = ("test.jsonl", "val.jsonl", "report.json", "manifest.json")


def _skip(path: Path) -> bool:
    if path.name.startswith(".env") or path.suffix in SKIP_SUFFIXES:
        return True
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def collect(repo: Path = REPO, questions_dir: str = "data/training/v2") -> list[tuple[Path, str, str]]:
    """(dosya yolu, zip içi ad, bölüm) listesi; sıralı ve belirlenimli."""
    items: list[tuple[Path, str, str]] = []
    for d in CODE_DIRS:
        for p in sorted((repo / d).rglob("*")):
            if p.is_file() and not _skip(p.relative_to(repo)):
                items.append((p, p.relative_to(repo).as_posix(), "code"))
    for f in ("pytest.ini", "pyproject.toml"):
        if (repo / f).exists():
            items.append((repo / f, f, "code"))
    snaps = repo / "data" / "snapshots"
    for ptr in POINTERS:
        pf = snaps / ptr
        if not pf.exists():
            continue
        items.append((pf, f"data/snapshots/{ptr}", "snapshots"))
        version = pf.read_text(encoding="utf-8").strip()
        vdir = snaps / version
        if not vdir.is_dir():
            raise FileNotFoundError(f"{pf.name} -> {version} klasörü yok")
        for p in sorted(vdir.rglob("*")):
            if p.is_file():
                items.append((p, p.relative_to(repo).as_posix(), "snapshots"))
    qdir = repo / questions_dir
    for name in QUESTION_FILES:
        if (qdir / name).exists():
            items.append((qdir / name, f"{questions_dir}/{name}", "questions"))
    if not any(a.endswith("test.jsonl") for _, a, _ in items):
        raise FileNotFoundError(f"{qdir / 'test.jsonl'} yok: önce `python -m training.build_dataset` çalıştırın")
    return items


def make_bundle(out: Path, repo: Path = REPO, questions_dir: str = "data/training/v2") -> dict[str, dict[str, int]]:
    """Zip'i yazar; bölüm bazında {"files", "raw_bytes", "zip_bytes"} döndürür (+ "total")."""
    items = collect(repo, questions_dir)
    sizes: dict[str, dict[str, int]] = {}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path, arc, section in items:
            z.write(path, arc)
            info = z.getinfo(arc)
            s = sizes.setdefault(section, {"files": 0, "raw_bytes": 0, "zip_bytes": 0})
            s["files"] += 1
            s["raw_bytes"] += info.file_size
            s["zip_bytes"] += info.compress_size
    sizes["total"] = {k: sum(v[k] for sec, v in sizes.items() if sec != "total") for k in ("files", "raw_bytes", "zip_bytes")}
    sizes["total"]["file_bytes"] = out.stat().st_size
    return sizes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="eval_bundle.zip")
    ap.add_argument("--questions", default="data/training/v2")
    args = ap.parse_args(argv)
    sizes = make_bundle(Path(args.out), REPO, args.questions)
    for sec, v in sizes.items():
        print(f"{sec:10s} dosya {v['files']:5d}  ham {v['raw_bytes'] / 1e6:7.2f} MB  zip {v['zip_bytes'] / 1e6:7.2f} MB")
    print(f"{args.out}: {sizes['total']['file_bytes'] / 1e6:.2f} MB (GGUF dahil DEĞİL; Drive'dan/yüklemeyle)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
