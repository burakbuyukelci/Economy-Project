"""Sürüme bağlı kütüphane API'leri için küçük, saf yardımcılar (torch gerektirmez; yerelde testli).

TRL `SFTConfig` alanı `max_seq_length` ↔ `max_length`, Unsloth `save_pretrained_gguf` argümanı `quantization_method` ↔ `quantization_type` sürüme göre değişir.
Hangisinin geçerli olduğu `inspect.signature` ile ÇALIŞMA ANINDA saptanır (try/except TypeError tahminine güvenilmez).
"""
from __future__ import annotations

import dataclasses
import inspect
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
