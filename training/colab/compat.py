"""Sürüme bağlı kütüphane API'leri için küçük, saf yardımcılar (torch gerektirmez; yerelde testli).

TRL `SFTConfig` alanı `max_seq_length` ↔ `max_length`, Unsloth `save_pretrained_gguf` argümanı `quantization_method` ↔ `quantization_type` sürüme göre değişir.
Hangisinin geçerli olduğu `inspect.signature` ile ÇALIŞMA ANINDA saptanır (try/except TypeError tahminine güvenilmez).
"""
from __future__ import annotations

import dataclasses
import inspect
import re
from pathlib import Path
from typing import Any, Callable, Sequence


def supported_names(obj: Callable[..., Any] | type) -> tuple[set[str], bool]:
    """(adlandırılabilir parametre adları, **kwargs kabul ediyor mu). Sınıf verilirse `__init__` ve dataclass alanları taranır."""
    names: set[str] = set()
    var_kw = False
    target = obj.__init__ if inspect.isclass(obj) else obj          # type: ignore[union-attr]
    for p in inspect.signature(target).parameters.values():
        if p.kind is inspect.Parameter.VAR_KEYWORD:
            var_kw = True
        elif p.kind not in (inspect.Parameter.VAR_POSITIONAL,) and p.name != "self":
            names.add(p.name)
    if inspect.isclass(obj) and dataclasses.is_dataclass(obj):
        names |= {f.name for f in dataclasses.fields(obj)}
    return names, var_kw


def first_supported(obj: Callable[..., Any] | type, candidates: Sequence[str]) -> str | None:
    """Adaylardan İLK desteklenen ad; hiçbiri yoksa None (çağıran açık hata verir)."""
    names, _ = supported_names(obj)
    return next((c for c in candidates if c in names), None)


def kwargs_for(obj: Callable[..., Any] | type, **choices: Sequence[str]) -> dict[str, str | None]:
    """`kwargs_for(SFTConfig, seq=("max_seq_length", "max_length"))` -> {"seq": "max_seq_length"}"""
    return {k: first_supported(obj, v) for k, v in choices.items()}


def latest_checkpoint(root: str | Path) -> Path | None:
    """`root` altındaki EN SON TAMAMLANMIŞ HF Trainer kontrol noktası (`checkpoint-<adım>`; içinde `trainer_state.json` olmalı: yarım yazılmış klasör sayılmaz).
    Yoksa None. Kesilen eğitim `trainer.train(resume_from_checkpoint=...)` ile buradan devam eder."""
    root = Path(root)
    if not root.is_dir():
        return None
    best: tuple[int, Path] | None = None
    for d in root.iterdir():
        m = re.fullmatch(r"checkpoint-(\d+)", d.name)
        if m and d.is_dir() and (d / "trainer_state.json").exists() and (best is None or int(m.group(1)) > best[0]):
            best = (int(m.group(1)), d)
    return best[1] if best else None


def bf16_native(capability: tuple[int, int], torch_says_supported: bool) -> bool:
    """bf16 yalnızca YERLEŞİK donanım desteğiyle (compute capability >= 8: Ampere ve sonrası) seçilir.

    Neden: yeni torch sürümlerinde `torch.cuda.is_bf16_supported()` T4'te (capability 7.5) EMÜLASYONLA True döner;
    emüle bf16 çok yavaştır (eğitim süresini kat kat uzatır, Kaggle 9 saat sınırını aşabilir). T4/P100'de fp16/float32 yolu kullanılır.
    """
    return bool(torch_says_supported) and capability[0] >= 8
