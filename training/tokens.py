"""Token sayımı: GERÇEK Gemma 3 tokenizer'ı varsa onunla, yoksa karakter tahminiyle (JSON ağırlıklı içerikte ~2,7 karakter/token ölçüldü).

Tokenizer dosyası: `TRAIN_TOKENIZER_JSON` ortam değişkeni ya da `training/.cache/tokenizer.json` (commit EDİLMEZ; `python -m training.tokens --fetch` indirir:
`unsloth/gemma-3-4b-it` tokenizer.json). Sayım Gemma sohbet biçimini taklit eder (`<start_of_turn>user|model ... <end_of_turn>`; system ilk user'a katılır) ve `<bos>` ekler.
Colab'da kesin süzme `tokenizer.apply_chat_template` ile yapılır (training/colab/train_qlora.py); fark birkaç tokendir.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from training import spec

DEFAULT_PATH = Path(__file__).resolve().parent / ".cache" / "tokenizer.json"
FETCH_URL = "https://huggingface.co/unsloth/gemma-3-4b-it/resolve/main/tokenizer.json"
ESTIMATE_CHARS_PER_TOKEN = 2.7


def gemma_text(text_messages: list[dict[str, str]]) -> str:
    """Sohbet şablonunun metin hali (system mesajı ilk user'ın başına eklenir)."""
    parts: list[str] = ["<bos>"]
    system = ""
    for m in text_messages:
        if m["role"] == "system":
            system = m["content"] + "\n\n"
            continue
        role = "model" if m["role"] == "assistant" else "user"
        content = (system + m["content"]) if (role == "user" and system) else m["content"]
        system = "" if role == "user" else system
        parts.append(f"<start_of_turn>{role}\n{content}<end_of_turn>\n")
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


def fetch(dest: Path = DEFAULT_PATH) -> Path:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(urllib.request.urlopen(FETCH_URL, timeout=120).read())
    return dest


if __name__ == "__main__":  # pragma: no cover
    if "--fetch" in sys.argv:
        print(fetch())
    else:
        print({"real_tokenizer": have_real_tokenizer(), "limit": spec.MAX_TOKENS})
