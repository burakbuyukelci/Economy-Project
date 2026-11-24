"""Etkileşimli sohbet: soruyu yazarsınız, harness + yerel model cevaplar (canlı demo; her soru `ask` ile aynı oturum hattından geçer).

    python -m experiments.chat --model gemma3-bist-v23 --as-of 2026-09-10

Soru yazın; çok satırlı yapıştırma için bitirince BOŞ satır bırakın. Çıkış: q (ya da Ctrl+C). Her soru otomatik kaydedilir
(`reports/chat/<sıra>_*.json` karar kaydı + `.jsonl` günlük); `python -m experiments.replay <kayıt>` ile aynı sonuç yeniden oynatılır.
Ağ: yalnızca yerel Ollama. Yeni mantık yoktur: her soru `experiments.ask.main` çağrısıdır.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable

from experiments import ask

QUIT = {"q", "quit", "exit", "çık", "cik"}


def read_question(input_fn: Callable[[str], str]) -> str | None:
    """Boş satıra kadar okur. Tek satırlık soru: tek satır + (boş satır ya da hemen Enter). None = çıkış."""
    lines: list[str] = []
    while True:
        try:
            line = input_fn("Soru> " if not lines else "...   ")
        except EOFError:
            return None if not lines else "\n".join(lines)
        if not lines and line.strip().lower() in QUIT:
            return None
        if not line.strip():
            if lines:
                return "\n".join(lines)
            continue                                            # baştaki boş satırlar yok sayılır
        lines.append(line)
        if len(lines) == 1 and not line.rstrip().endswith("\\"):
            return line                                         # tek satırlık soru hemen çalışır; çok satır için satır sonuna \ koyun


def main(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input, backend_factory=None) -> int:
    ap = argparse.ArgumentParser(description="Etkileşimli sohbet (yerel model + harness)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--profile", default="D")
    ap.add_argument("--as-of", default=None, help="analiz tarihi YYYY-MM-DD (soruda işaret yoksa; canlı testte 2026-09-10)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--out", default="reports/chat", help="kayıt klasörü")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    print("Soru yazıp Enter'a basın. Çıkış: q. (Her soru 1–10 dk sürebilir; CPU'da yerel model.)")
    n = len(list(out.glob("*.json")))
    while True:
        try:
            text = read_question(input_fn)
        except KeyboardInterrupt:
            print()
            return 0
        if text is None:
            return 0
        text = text.replace("\\\n", "\n").rstrip("\\")
        n += 1
        a = ["--question", text, "--profile", args.profile, "--record", str(out / f"{n:03d}.json"), "--log", str(out / f"{n:03d}.jsonl")]
        for flag, val in (("--model", args.model), ("--as-of", args.as_of), ("--host", args.host)):
            if val:
                a += [flag, val]
        try:
            ask.main(a, backend_factory=backend_factory)
        except KeyboardInterrupt:
            print("\n(soru iptal edildi)")
        print()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
