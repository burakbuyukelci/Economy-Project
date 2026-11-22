"""Ollama Modelfile şablonunun EĞİTİM metniyle aynı token sayısını verdiğini doğrular (Bilgisayar 1, Ollama çalışırken):

    python -m experiments.check_template --model gemma3-bist --records data/training/v1/val.jsonl --n 5

Her örnek için, kaydın ilk k mesajına (son mesaj user olacak şekilde) iki yoldan bakılır:
  * RAW: eğitim metni (`<bos>` HARİÇ; GGUF tokenizer'ı BOS'u kendisi ekler) `/api/generate raw=true` ile gönderilir -> `prompt_eval_count` (şablon UYGULANMAZ);
  * CHAT: aynı konuşma `/api/chat` ile gönderilir (Modelfile şablonu uygulanır) -> `prompt_eval_count`.
İki sayı eşit değilse şablon eğitim metninden farklıdır (fazladan satır/boşluk, çift BOS, system rolü...). Çıkış kodu 0 = hepsi eşit.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.llm_backend import OllamaBackend
from harness.text_protocol import fold_system
from training.tokens import gemma_text


def prefixes(record: dict, n: int) -> list[list[dict[str, str]]]:
    """Kaydın text_messages'ından, user ile biten ilk n önek (son user -> model yanıtı beklenir)."""
    msgs = record["text_messages"]
    out = [msgs[: i + 1] for i, m in enumerate(msgs) if m["role"] == "user"]
    return out[:n]


def raw_prompt(prefix: list[dict[str, str]]) -> str:
    return gemma_text(prefix).removeprefix("<bos>") + "<start_of_turn>model\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--records", default="data/training/v1/val.jsonl")
    ap.add_argument("--n", type=int, default=5, help="kayıt sayısı (her kayıttan ilk 3 önek)")
    ap.add_argument("--host", default=None)
    args = ap.parse_args(argv)

    # native: mesajlar OLDUĞU GİBİ gider (zaten kodlanmış metin mesajları). max_new_tokens=1: yalnızca prompt_eval_count gerekir; tam yanıt üretmek CPU'da dakikalar sürer.
    backend = OllamaBackend(model=args.model, host=args.host, tool_mode="native", max_new_tokens=1)
    records = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()][: args.n]
    bad = 0
    for rec in records:
        for prefix in prefixes(rec, 3):
            raw = backend.raw_prompt_tokens(raw_prompt(prefix))
            chat = backend.chat(fold_system(prefix), None).prompt_tokens
            ok = raw == chat
            bad += 0 if ok else 1
            print(f"{'OK ' if ok else 'FARK'} {rec['id']} mesaj={len(prefix)} raw={raw} chat={chat}")
    print("şablon eğitim metniyle AYNI" if not bad else f"{bad} önekte FARK var: training/ollama/Modelfile TEMPLATE'ini düzeltin")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
