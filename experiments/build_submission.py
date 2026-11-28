"""Teslim paketi üreticisi (hocanın sunum kuralı, madde 4): tek `submission.json` manifesti + ekleri.

    python -m experiments.build_submission --adapter-zip "C:/Users/.../results (1).zip" --out submission

Üretilenler (`--out` altında):
  submission.json            manifest: model/temel model/SHA-256, dosya listesi (yol, boyut, SHA-256), çalıştırma, dürüstlük beyanı
  source_code.zip            `git ls-files` ile izlenen tüm kaynak (araçlar, harness, scriptler, testler, belgeler, sürümlü veri snapshot'ı)
  fine_tuning/               eğitim/val/test JSONL, veri manifesti ve raporu, eğitim sonucu, hiperparametreler (model_info.json)
  model/                     YALNIZCA LoRA adaptörü (adapter_model.safetensors + adapter_config.json)
  rag/knowledge_base.json    bilgi tabanı belgeleri + kaynak meta verileri (çalışma anında erişim YOK; manifestte yazılı)
  traces/                    beş senaryonun iz kayıtları (`reports/traces/*.json`)
  RUNNING.md                 çalıştırma talimatı
Hiçbir ağ erişimi yoktur; yalnızca yerel dosyalar okunur/yazılır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KB_SOURCES = [
    ("docs/data_dictionary.md", "data documentation"),
    ("docs/tool_usage_guide.md", "tool usage guide"),
    ("docs/calibration_thresholds.md", "calibration thresholds"),
    ("docs/fundamentals_toplama.md", "fundamentals collection notes"),
    ("docs/harness_design.md", "harness design"),
    ("docs/report/limitations.md", "known limitations"),
]
_MAX_CHARS = 3500


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _chunks(text: str) -> list[tuple[str, str]]:
    """Markdown -> [(başlık yolu, metin)]; `#`/`##`/`###` başlıklarında bölünür, uzun bölümler paragraf sınırında parçalanır."""
    out: list[tuple[str, str]] = []
    path: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        buf.clear()
        if not body:
            return
        title = " > ".join(path) or "(giriş)"
        parts, cur = [], ""
        for para in re.split(r"\n\s*\n", body):
            if cur and len(cur) + len(para) > _MAX_CHARS:
                parts.append(cur)
                cur = ""
            cur = f"{cur}\n\n{para}".strip() if cur else para
        if cur:
            parts.append(cur)
        for i, part in enumerate(parts, 1):
            out.append((title if len(parts) == 1 else f"{title} (bölüm {i}/{len(parts)})", part))

    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = path[: level - 1] + [m.group(2).strip()]
        else:
            buf.append(line)
    flush()
    return out


def build_knowledge_base(root: Path = ROOT) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for rel, kind in KB_SOURCES:
        f = root / rel
        if not f.exists():
            continue
        digest = sha256_file(f)
        sources.append({"file": rel, "kind": kind, "sha256": digest, "language": "tr (technical identifiers in English)"})
        for i, (title, body) in enumerate(_chunks(f.read_text(encoding="utf-8")), 1):
            docs.append({"id": f"{Path(rel).stem}-{i:04d}", "title": title, "text": body, "source": {"file": rel, "heading": title, "file_sha256": digest}})
    return {
        "format": "cse481-knowledge-base-1",
        "description": "Project knowledge base: data dictionary, tool usage, calibration thresholds, harness design and limitations, split by heading with source metadata.",
        "runtime_retrieval": False,
        "runtime_retrieval_note": "The final system does NOT retrieve from this file at run time. Every number in an answer comes from a deterministic tool output; "
                                  "this knowledge base documents the domain knowledge, definitions and rules the tools and harness implement.",
        "n_documents": len(docs), "sources": sources, "documents": docs,
    }


def _tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=root, check=True)
    return [p for p in out.stdout.splitlines() if p and (root / p).is_file()]


def _git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=root, timeout=20).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _entry(base: Path, f: Path, role: str) -> dict[str, Any]:
    return {"path": f.relative_to(base).as_posix(), "role": role, "bytes": f.stat().st_size, "sha256": sha256_file(f)}


RUNNING = """# Running the submission

Everything runs locally; no cloud AI API is used. Python 3.12 is required.

## 1. Install
    python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # after unzipping source_code.zip
    (Ollama must be installed: https://ollama.com)

## 2. Model
The submitted weights are the LoRA adapter in `model/` (base model and SHA-256 are in `submission.json`).
The system runs locally from a merged + quantized GGUF of base + adapter under Ollama:
    ollama create gemma3-bist-v23 -f training/ollama/Modelfile.v23      # needs training/ollama/gemma3-bist-v23-q4_k_m.gguf
The GGUF was produced from this adapter by `training/colab/train_qlora.py` (Unsloth merge -> Q4_K_M). To rebuild it from the adapter alone:
merge the adapter into the base model (`model.save_pretrained_merged`), convert with llama.cpp `convert_hf_to_gguf.py`, quantize with `llama-quantize ... Q4_K_M`
(see training/README.md, troubleshooting). That adapter-only rebuild was not re-run when this package was assembled.

## 3. Ask one question (live question)
    python -m experiments.ask --model gemma3-bist-v23 --as-of 2026-09-10 --trace out/trace.json --question "..."
or interactively:  python -m experiments.chat --model gemma3-bist-v23 --as-of 2026-09-10
A delivered answer on a CPU takes about 3-10 minutes; with a GPU it takes well under one minute per turn.

## 4. Tests
    python -m pytest
"""


def build(out: Path, adapter_zip: Path | None, traces_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    info = json.loads((root / "training" / "model_info.json").read_text(encoding="utf-8"))
    files: list[dict[str, Any]] = []

    # 1) kaynak kod
    zpath = out / "source_code.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in _tracked_files(root):
            z.write(root / rel, rel)
    files.append(_entry(out, zpath, "python source code (tools, agent/harness, scripts, tests, docs, versioned data snapshot)"))

    # 2) ince ayar dosyaları
    ft = out / "fine_tuning"
    ft.mkdir()
    for rel in ("data/training/v2_3/train.jsonl", "data/training/v2_3/val.jsonl", "data/training/v2_3/test.jsonl", "data/training/v2_3/manifest.json",
                "data/training/v2_3/report.json", "reports/v2_3/train_result.json", "reports/v2_3/data_stats.json", "reports/v2_3/train_log.txt",
                "training/model_info.json", "training/colab/train_qlora.py"):
        src = root / rel
        if src.exists():
            shutil.copy2(src, ft / src.name)
            files.append(_entry(out, ft / src.name, "fine-tuning: " + ("training data" if rel.endswith("train.jsonl") else "validation data" if rel.endswith("val.jsonl") else "config / results")))
    (ft / "hyperparameters.json").write_text(json.dumps(info["training"]["hyperparameters"] | {"base_model": info["base_model"]["name"], "command": info["training"]["command"]},
                                                         indent=1), encoding="utf-8")
    files.append(_entry(out, ft / "hyperparameters.json", "fine-tuning: hyperparameters"))

    # 3) yalnızca LoRA adaptörü
    adapter = dict(info["adapter"])
    if adapter_zip is not None:
        md = out / "model"
        md.mkdir()
        with zipfile.ZipFile(adapter_zip) as z:
            for name in ("adapter_model.safetensors", "adapter_config.json"):
                with z.open(f"result/adapter/{name}") as src, (md / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        got = sha256_file(md / "adapter_model.safetensors")
        if got != adapter["sha256"]:
            raise SystemExit(f"adaptör SHA-256 uyuşmuyor: zip={got} model_info={adapter['sha256']} (yanlış sürüm?)")
        files.append(_entry(out, md / "adapter_model.safetensors", "LoRA adapter weights (safetensors)"))
        files.append(_entry(out, md / "adapter_config.json", "LoRA adapter config"))

    # 4) RAG / bilgi tabanı
    rag = out / "rag"
    rag.mkdir()
    (rag / "knowledge_base.json").write_text(json.dumps(build_knowledge_base(root), ensure_ascii=False, indent=1), encoding="utf-8")
    files.append(_entry(out, rag / "knowledge_base.json", "knowledge base documents + source metadata (no run-time retrieval)"))

    # 5) iz kayıtları
    tr = out / "traces"
    tr.mkdir()
    scen = []
    for f in sorted(traces_dir.glob("scenario_*_*.json")):
        shutil.copy2(f, tr / f.name)
        files.append(_entry(out, tr / f.name, "scenario trace"))
        t = json.loads(f.read_text(encoding="utf-8"))
        scen.append({"file": f"traces/{f.name}", "scenario": t.get("scenario"), "status": t.get("status"), "action": t["final_answer"]["action"],
                     "answer_source": t["final_answer"]["source"], "duration_s": t["timing"]["duration_s"]})

    (out / "RUNNING.md").write_text(RUNNING, encoding="utf-8")
    files.append(_entry(out, out / "RUNNING.md", "run instructions"))

    manifest = {
        "format": "cse481-submission-1", "course": "CSE-481 Engineering Economics", "instructor": "Dr. Alper Özcan",
        "team": [{"name": "Mert Osman Ayhan", "student_no": "20220808074"}, {"name": "Burak Büyükelçi", "student_no": "20220808071"}], "project": "Integrated BIST 100 Agentic Financial Analytics Harness",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code_commit": _git(root, "rev-parse", "HEAD"),
        "code_dirty_files": (_git(root, "status", "--porcelain") or "").count("\n") + (1 if _git(root, "status", "--porcelain") else 0),
        "model": {"version": info["model_version"], "ollama_name": info["ollama_name"], "base_model": info["base_model"],
                  "adapter": {**adapter, "file": "model/adapter_model.safetensors"}, "local_runtime_artifact": info["local_runtime_artifact"],
                  "inference": info["inference"]},
        "fine_tuning": {"hyperparameters": info["training"]["hyperparameters"], "results": info["training"]["results"], "data": info["training"]["data"]},
        "scenarios": scen, "files": files,
        "run": "see RUNNING.md",
        "honesty_statement": [
            "The model runs locally (Ollama); no cloud AI API is called at any point.",
            "No answer is hard-coded or looked up per question. Every number in a delivered answer comes from a deterministic Python tool output; a number verifier rejects answers containing numbers that are not in the tool outputs.",
            "Text that does not come from the model is labelled: harness fallback text (final_answer.source = harness_fallback) and the out-of-scope message are generated by the harness, not by the model.",
            "docs/sample_runs/ inside the source code is produced by a deterministic teacher script (the training-data generator), NOT by the model; the submitted scenario answers are only in traces/.",
            "The harness may repair formatting mistakes in the model's tool calls (period spelling, ticker typo, split_date, unknown strategy parameters); every repair is logged with the model's original and the executed parameters (harness_interventions in each trace).",
        ],
        "known_limitations": "see docs/report/limitations.md inside source_code.zip (L1-L53): about 25% of full-harness sessions in the 40-question evaluation ended at the turn limit; answer texts can attach tool numbers to the wrong field or horizon (the verifier checks existence only); several course-document features are not implemented (L52).",
    }
    (out / "submission.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Teslim paketi (submission.json + ekler)")
    ap.add_argument("--out", default="submission")
    ap.add_argument("--adapter-zip", default=None, help="Kaggle çıktısı results zip'i (result/adapter/ içerir)")
    ap.add_argument("--traces", default="reports/traces")
    args = ap.parse_args(argv)
    m = build(Path(args.out), Path(args.adapter_zip) if args.adapter_zip else None, Path(args.traces))
    print(f"{args.out}/submission.json yazıldı: {len(m['files'])} dosya, {len(m['scenarios'])} senaryo izi")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
