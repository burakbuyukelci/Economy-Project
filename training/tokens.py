"""Token sayımı: GERÇEK Gemma 3 tokenizer'ı varsa onunla, yoksa karakter tahminiyle (JSON ağırlıklı içerikte ~2,7 karakter/token ölçüldü).

Tokenizer dosyası: `TRAIN_TOKENIZER_JSON` ortam değişkeni ya da `training/.cache/tokenizer.json` (commit EDİLMEZ). İndirme (ağ yalnızca elle/komut satırında; training/ içinde ağ kodu YOK):
`curl -L -o training/.cache/tokenizer.json https://huggingface.co/unsloth/gemma-3-4b-it/resolve/main/tokenizer.json`. Sayım Gemma sohbet biçimini taklit eder (`<start_of_turn>user|model ... <end_of_turn>`; system ilk user'a katılır) ve `<bos>` ekler.
Colab'da kesin süzme `tokenizer.apply_chat_template` ile yapılır (training/colab/train_qlora.py); fark birkaç tokendir.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from harness.text_protocol import fold_system
from training import spec

DEFAULT_PATH = Path(__file__).resolve().parent / ".cache" / "tokenizer.json"
ESTIMATE_CHARS_PER_TOKEN = 2.7


def gemma_text(text_messages: list[dict[str, str]]) -> str:
    """Sohbet şablonunun metin hali: `<bos>` + her mesaj için `<start_of_turn>user|model\n...<end_of_turn>\n` (system ilk user'a `fold_system` ile katılır)."""
    parts = ["<bos>"]
    for m in fold_system(text_messages):
        role = "model" if m["role"] == "assistant" else "user"
        parts.append(f"<start_of_turn>{role}\n{m['content']}<end_of_turn>\n")
    return "".join(parts)


@lru_cache(maxsize=1)
def _tokenizer() -> Any | None:
    path = Path(os.environ.get("TRAIN_TOKENIZER_JSON", DEFAULT_PATH))
    if not path.exists():
        return None
    try:
        from tokenizers import Tokenizer
    except ImportError:
        return None
    return Tokenizer.from_file(str(path))


def have_real_tokenizer() -> bool:
    return _tokenizer() is not None


def count_tokens(text_messages: list[dict[str, str]]) -> int:
    tok = _tokenizer()
    text = gemma_text(text_messages)
    if tok is not None:
        return len(tok.encode(text, add_special_tokens=False).ids)
    return int(len(text) / ESTIMATE_CHARS_PER_TOKEN) + 1


if __name__ == "__main__":  # pragma: no cover
    print({"real_tokenizer": have_real_tokenizer(), "limit": spec.MAX_TOKENS})
