"""Çıkarım istemi ile EĞİTİM metninin birebir aynı olduğunu doğrular (Ollama çalışırken):

    python -m experiments.check_template --model gemma3-bist --records data/training/v2_2/val.jsonl --n 2

İstem yolu (2026-11-23 kararı): harness metin-protokolü modunda konuşmayı `render_gemma_prompt` ile EĞİTİM metninin biçiminde (`<start_of_turn>user|model\\n...<end_of_turn>\\n`, sona model tur başlığı)
kendisi biçimlendirip `/api/generate raw=true` gönderir; Ollama'nın Modelfile şablonu ve `/api/chat` yolu KULLANILMAZ. Sebep: `/api/chat` yolu şablon ne olursa olsun eğitim metninden FAZLA token üretiyordu
(tek mesajda +3, asistan turu başına +4; bu denetimin ilk koşusunda ölçüldü). Denetimler:
  1. METİN: kaydın her önekinde `render_gemma_prompt(önek)` == eğitim metni (`training.tokens.gemma_text`, `<bos>` hariç + model tur başlığı). Sunucu gerekmez.
  2. BOS: GGUF tokenizer'ı BOS'u kendisi ekler; `<bos>` yazılsa da sayı DEĞİŞMEMELİ (BOS iki kez eklenmiyor). Küçük sonda isteğiyle sınanır.
  3. (isteğe bağlı `--chat`) bilgi: eski sohbet yolunun token sayısı ham yoldan kaç fazla. Kullanılmaz; yalnızca neden ham yola geçildiğini göstermek içindir (CPU'da yavaş).
Çıkış kodu 0 = metin eşit ve BOS tek.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from harness.llm_backend import OllamaBackend
from harness.text_protocol import fold_system, render_gemma_prompt
from training.tokens import gemma_text

PROBE = "<start_of_turn>user\nMerhaba<end_of_turn>\n<start_of_turn>model\n"


def prefixes(record: dict, n: int) -> list[list[dict[str, str]]]:
    """Kaydın text_messages'ından, user ile biten ilk n önek (son user -> model yanıtı beklenir)."""
    msgs = record["text_messages"]
    out = [msgs[: i + 1] for i, m in enumerate(msgs) if m["role"] == "user"]
    return out[:n]


def raw_prompt(prefix: list[dict[str, str]]) -> str:
    """Eğitim metninden türetilen beklenen istem (`<bos>` HARİÇ; GGUF tokenizer'ı BOS'u kendisi ekler)."""
    return gemma_text(prefix).removeprefix("<bos>") + "<start_of_turn>model\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--records", default="data/training/v2_2/val.jsonl")
    ap.add_argument("--n", type=int, default=5, help="kayıt sayısı (her kayıttan ilk 3 önek)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--chat", action="store_true", help="bilgi: eski /api/chat yolunun token farkını da göster (CPU'da yavaş)")
    args = ap.parse_args(argv)

    # max_new_tokens=1: yalnızca prompt_eval_count gerekir; tam yanıt üretmek CPU'da dakikalar sürer.
    backend = OllamaBackend(model=args.model, host=args.host, tool_mode="text", raw=True, max_new_tokens=1)
    records = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()][: args.n]
    bad = 0
    for rec in records:
        for prefix in prefixes(rec, 3):
            same = render_gemma_prompt(prefix) == raw_prompt(prefix)
            line = f"{'OK ' if same else 'FARK'} {rec['id']} mesaj={len(prefix)} metin {'AYNI' if same else 'FARKLI'}"
            if args.chat:
                raw = backend.raw_prompt_tokens(raw_prompt(prefix))
                chat = OllamaBackend(model=args.model, host=args.host, tool_mode="native", raw=False, max_new_tokens=1).chat(fold_system(prefix), None).prompt_tokens
                line += f" | token: ham={raw}, sohbet yolu={chat} (fark {None if chat is None else chat - raw})"
            bad += 0 if same else 1
            print(line)
    n_plain, n_bos = backend.raw_prompt_tokens(PROBE), backend.raw_prompt_tokens("<bos>" + PROBE)
    bos_ok = n_plain == n_bos
    print(f"{'OK ' if bos_ok else 'FARK'} BOS sondası: <bos> yazılmadan {n_plain} token, yazılınca {n_bos} token ({'BOS tek kez' if bos_ok else 'BOS İKİ KEZ EKLENİYOR olabilir'})")
    bad += 0 if bos_ok else 1
    print("istem eğitim metniyle AYNI (ham yol)" if not bad else f"{bad} denetimde FARK var")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
