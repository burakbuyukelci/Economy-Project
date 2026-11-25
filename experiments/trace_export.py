"""İz kaydı (trace) dışa aktarımı: hocanın sunum kuralı (grup başına 5 senaryonun TAM süreç kaydı).

İstenen en az içerik: model ve sürümü, sistem ve kullanıcı istemi, çağrılan araçlar + parametreleri + tarih aralıkları, araç çıktıları, nihai yanıt,
zaman damgaları, sıcaklık (temperature) ve seed değerleri. `build_trace` bunların hepsini TEK JSON'da toplar.

Dürüstlük için ayrıca (akademik dürüstlük kuralı):
  * `final_answer.source`: "model" (cevabı modelin kendisi yazdı) ya da "harness_fallback" (model teslim edemedi; harness'in güvenli şablon metni). İkincisi model çıktısı
    gibi sunulmaz.
  * `harness_interventions`: harness'in modelin araç çağrısını onardığı her yer (PARAMS_NORMALIZED: modelin yazdığı orijinal params ve çalışan params yan yana).
  * Sayılar yalnızca araç çıktısından gelir; `audit` sayı doğrulayıcı sonucunu (halüsinasyon / kanıtsız sayısı) içerir.
Zaman damgaları yalnızca bu kayıt içindir (`EventLog(timestamps=True)`); kanıt hash'lerine ve replay özetine girmez.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from experiments.decision_record import summary_of
from harness import settings
from harness.session import HarnessSession

FORMAT = "cse481-trace-1"
MODEL_INFO = Path(__file__).resolve().parents[1] / "training" / "model_info.json"
_DATE_KEYS = ("as_of", "start", "end", "analysis_start", "analysis_end", "split_date", "out_of_sample_start", "period")


def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, cwd=Path(__file__).resolve().parents[1])
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def ollama_digest(backend: Any) -> str | None:
    """Model özeti (digest): yalnızca gerçek Ollama arka ucunda var; ağ erişimi `harness/llm_backend.py` içindedir. Yoksa None (sahte değer yazılmaz)."""
    fn = getattr(backend, "model_digest", None)
    return fn() if callable(fn) else None


def _date_range(params: dict[str, Any]) -> dict[str, Any]:
    out = {k: params[k] for k in _DATE_KEYS if k in params}
    for k in ("relate_to",):                       # iç içe tarih alanları (makro ilişki)
        for i, item in enumerate(params.get(k) or []):
            if isinstance(item, dict) and "split_date" in item:
                out[f"{k}[{i}].split_date"] = item["split_date"]
    return out


def build_trace(session: HarnessSession, result: Any, messages: list[dict[str, Any]], *, question: str, model_name: str, backend: Any | None = None,
                started_at: str | None = None, finished_at: str | None = None, duration_s: float | None = None, scenario: str | None = None) -> dict[str, Any]:
    events = session.events
    info = json.loads(MODEL_INFO.read_text(encoding="utf-8")) if MODEL_INFO.exists() else {}
    by_hash = {r.envelope["input_hash"]: r.envelope for r in session.store.records}

    calls: list[dict[str, Any]] = []
    interventions: list[dict[str, Any]] = []
    pending_norm: dict[str, dict[str, Any]] = {}
    for e in events:
        k = e["kind"]
        if k == "PARAMS_NORMALIZED":
            iv = {"ts": e.get("ts"), "tool": e.get("tool"), "notes": e.get("notes"), "model_original_params": e.get("original"), "executed_params": e.get("fixed")}
            interventions.append(iv)
            pending_norm[e.get("tool")] = iv
        elif k == "TOOL_CALL":
            env = by_hash.get(e["input_hash"])
            params = (env or {}).get("params") or {}
            call = {"seq": e["seq"], "ts": e.get("ts"), "caller": e.get("actor"), "tool": e["tool"], "status": e.get("status"), "params": params,
                    "date_range": _date_range(params), "input_hash": e["input_hash"], "data_version": e.get("data_version"), "state_after": e.get("state_after"),
                    "output": env}
            norm = pending_norm.pop(e["tool"], None) if e.get("actor") == "model" else None
            if norm is not None:
                call["model_original_params"] = norm["model_original_params"]
            calls.append(call)
        elif k == "INVALID_TOOL_CALL":
            calls.append({"seq": e["seq"], "ts": e.get("ts"), "caller": "model", "tool": e.get("tool"), "status": "REJECTED_BY_HARNESS", "error_code": e.get("code"),
                          "error_message": e.get("message")})
    turns = [{"seq": e["seq"], "ts": e.get("ts"), "turn": e.get("turn"), "prompt_tokens": e.get("prompt_tokens"), "completion_tokens": e.get("completion_tokens"),
              "n_tool_calls": e.get("n_tool_calls")} for e in events if e["kind"] == "MODEL_TURN"]
    fallback = any(e["kind"] == "FINAL_FALLBACK" for e in events)
    summary = summary_of(session)
    sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
    usr_msg = next((m["content"] for m in messages if m.get("role") == "user"), None)
    gen = {"temperature": getattr(backend, "temperature", None), "seed": getattr(backend, "seed", None), "num_ctx": getattr(backend, "num_ctx", None),
           "max_new_tokens": getattr(backend, "max_new_tokens", None), "tool_mode": getattr(backend, "tool_mode", None), "max_model_turns": settings.AGENT_MAX_TURNS}
    return {
        "format": FORMAT, "scenario": scenario, "question": question, "as_of": session.as_of.isoformat(), "as_of_source": session.as_of_source,
        "profile": session.profile.name, "status": result.status, "abort_reason": getattr(result, "abort_reason", None),
        "model": {"name": model_name, "version": info.get("model_version"), "ollama_digest": ollama_digest(backend) if backend is not None else None,
                  "base_model": (info.get("base_model") or {}).get("name"), "adapter_sha256": (info.get("adapter") or {}).get("sha256"),
                  "gguf_sha256": (info.get("local_runtime_artifact") or {}).get("sha256")},
        "generation": gen,
        "prompts": {"system": sys_msg, "user": usr_msg},
        "timing": {"started_at": started_at, "finished_at": finished_at, "duration_s": None if duration_s is None else round(duration_s, 1)},
        "model_turns": turns,
        "tool_calls": calls,
        "harness_interventions": interventions,
        "conversation": messages,
        "final_answer": {"text": session.machine.explanation, "action": summary.get("action"), "source": "harness_fallback" if fallback else "model"},
        "audit": {k: summary[k] for k in ("policy_label", "rule_id", "lock_hash", "n_number_claims", "n_hallucinated", "n_unevidenced", "n_invalid_calls")},
        "reproducibility": {"data_versions": sorted({c["data_version"] for c in calls if c.get("data_version")}), "tool_input_hashes": summary["tool_hashes"],
                            "code_commit": _git_commit()},
        "events": events,
    }
