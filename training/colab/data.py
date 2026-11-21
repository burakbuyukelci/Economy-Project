"""Colab eğitim verisi hazırlığı: JSONL kayıt -> `input_ids` / `labels` / `attention_mask` (torch ve transformers GEREKTİRMEZ; saf mantık, yerelde test edilir).

Gemma 3 sohbet biçimi (HF şablonuyla aynı düzen, `harness.text_protocol.fold_system` ile): `<bos>` + her mesaj için `<start_of_turn>user|model\\n…<end_of_turn>\\n`; system
metni ilk user mesajının başına `\\n\\n` ile eklenir. Kayıp (label) YALNIZCA `train_mask` doğru olan asistan mesajlarının içeriği + `<end_of_turn>` için hesaplanır;
system, user (soru, politika bloğu, geri bildirim), araç çıktıları (`<tool_response>`) ve MASKELİ hatalı asistan turları -100'dür (bağlamda kalır).
Her parça ayrı kodlanıp birleştirilir; parça sınırları özel token'larda olduğundan bütün metni kodlamayla aynıdır (gerçek tokenizer ile testli).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Sequence

from harness.text_protocol import fold_system

IGNORE = -100
Encode = Callable[[str], list[int]]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def segments(record: dict[str, Any]) -> list[tuple[str, bool]]:
    """(metin parçası, eğitilsin mi). Birleşimi `training.tokens.gemma_text` ile aynıdır."""
    msgs, mask = record["text_messages"], record["train_mask"]
    if len(msgs) != len(mask):
        raise ValueError(f"{record.get('id')}: train_mask uzunluğu mesaj sayısıyla aynı değil")
    non_system = [bool(m) for msg, m in zip(msgs, mask) if msg["role"] != "system"]
    folded = fold_system(msgs)
    if len(folded) != len(non_system):
        raise ValueError(f"{record.get('id')}: system katlama sonrası mesaj sayısı uyuşmuyor")
    out: list[tuple[str, bool]] = [("<bos>", False)]
    for m, train in zip(folded, non_system):
        if m["role"] == "assistant":
            out += [("<start_of_turn>model\n", False), (m["content"] + "<end_of_turn>", train), ("\n", False)]
        else:
            out.append((f"<start_of_turn>user\n{m['content']}<end_of_turn>\n", False))
    return out


def encode_record(record: dict[str, Any], encode: Encode, max_len: int) -> dict[str, Any] | None:
    """Kayıt -> örnek. `max_len` aşılırsa None (süzülür). Eğitilecek hiç token yoksa ValueError."""
    ids: list[int] = []
    labels: list[int] = []
    for text, train in segments(record):
        piece = encode(text)
        ids += piece
        labels += piece if train else [IGNORE] * len(piece)
    n_train = sum(1 for x in labels if x != IGNORE)
    if n_train == 0:
        raise ValueError(f"{record.get('id')}: eğitilecek asistan metni yok (train_mask hepsi False)")
    if len(ids) > max_len:
        return None
    return {"id": record.get("id"), "input_ids": ids, "labels": labels, "attention_mask": [1] * len(ids), "n_train_tokens": n_train}


def build_examples(records: Sequence[dict[str, Any]], encode: Encode, max_len: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    dropped: list[str] = []
    for r in records:
        ex = encode_record(r, encode, max_len)
        if ex is None:
            dropped.append(str(r.get("id")))
        else:
            examples.append(ex)
    total = sum(len(e["input_ids"]) for e in examples)
    train = sum(e["n_train_tokens"] for e in examples)
    stats = {"n_in": len(records), "n_kept": len(examples), "n_dropped_long": len(dropped), "dropped_ids": dropped[:20], "max_len": max_len,
             "total_tokens": total, "train_tokens": train, "train_token_share": round(train / total, 4) if total else 0.0,
             "mean_len": round(total / len(examples)) if examples else 0, "longest": max((len(e["input_ids"]) for e in examples), default=0)}
    return examples, stats
