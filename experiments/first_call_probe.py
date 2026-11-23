"""İlk araç çağrısı doğruluğu: modelin İLK turunu (yalnızca bir model çağrısı) eğitim/test kaydındaki öğretmen çağrısıyla karşılaştırır.

    python -m experiments.first_call_probe --model gemma3-bist --records data/training/v2_2/test.jsonl --types weekday reversal --per-type 3

Neden: tam oturum (A–E) pahalıdır; hatalı araç çağrısı oranının büyük kısmı ilk çağrıda belli olur. Ölçüm: (1) araç adı doğru mu, (2) parametreler öğretmenle BİREBİR mi, (3) değilse hangi alanlar farklı.
İstem, kaydın ilk iki mesajıdır (sistem + soru): çıkarımdakiyle aynı biçim (`render_gemma_prompt`). Model çağrısı: ham yol (`/api/generate raw=true`), sıcaklık 0. Ağ: yalnızca yerel Ollama.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from harness.llm_backend import LLMError, OllamaBackend


def teacher_first_call(rec: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Kaydın İLK GEÇERLİ asistan araç çağrısı (hata-kurtarma yörüngelerinde maskeli hatalı tur atlanır)."""
    bad = set(rec.get("bad_turns") or [])
    turn = -1
    for m in rec["messages"]:
        if m["role"] != "assistant":
            continue
        turn += 1
        if turn in bad:
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc["function"]
            return fn["name"], dict(fn.get("arguments") or {})
        return None            # ilk geçerli asistan turu araç çağrısı değil
    return None


def diff(a: Any, b: Any, path: str = "") -> list[str]:
    """Öğretmen (a) ile model (b) parametre farkları (nokta yolu)."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for k in sorted(set(a) | set(b)):
            out += diff(a.get(k, "<yok>"), b.get(k, "<yok>"), f"{path}.{k}" if path else k)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: öğretmen={json.dumps(a, ensure_ascii=False)[:60]} model={json.dumps(b, ensure_ascii=False)[:60]}"]


def pick(records: list[dict[str, Any]], types: list[str] | None, per_type: int) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in sorted(records, key=lambda r: r["id"]):
        if (not types or r["type"] in types) and not r.get("recovery"):
            by[r["type"]].append(r)
    return [r for t in sorted(by) for r in by[t][:per_type]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--records", required=True)
    ap.add_argument("--types", nargs="*", default=None)
    ap.add_argument("--per-type", type=int, default=3)
    ap.add_argument("--host", default=None)
    ap.add_argument("--out", default=None, help="sonuç JSON")
    args = ap.parse_args(argv)
    recs = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()]
    backend = OllamaBackend(model=args.model, host=args.host, tool_mode="text", raw=True, max_new_tokens=400)
    rows, per = [], defaultdict(Counter)
    for rec in pick(recs, args.types, args.per_type):
        want = teacher_first_call(rec)
        if want is None:
            continue
        prompt = rec["text_messages"][:2]          # eğitimde modele giden metin (sistem + araç tanımları + soru), birebir
        try:
            reply = backend.chat(prompt, None)
        except LLMError as exc:
            print(f"HATA {rec['id']}: {exc}", file=sys.stderr)
            continue
        got = (reply.tool_calls[0].name, dict(reply.tool_calls[0].arguments)) if reply.tool_calls else None
        name_ok = bool(got) and got[0] == want[0]
        exact = bool(got) and got == want
        d = diff(want[1], got[1]) if got and name_ok else (["araç çağrısı yok"] if not got else [f"araç adı: öğretmen={want[0]} model={got[0]}"])
        row = {"id": rec["id"], "type": rec["type"], "tool_ok": name_ok, "exact": exact, "diffs": d, "format_error": reply.format_error}
        rows.append(row)
        per[rec["type"]].update(n=1, tool_ok=int(name_ok), exact=int(exact))
        print(f"{'TAM' if exact else ('ARAÇ-OK' if name_ok else 'YANLIŞ')} {rec['type']:12s} {rec['id']}  " + ("; ".join(d[:3]) if d else ""), flush=True)
    print("\n=== ÖZET (tip: n, doğru araç, birebir parametre) ===")
    for t, c in sorted(per.items()):
        print(f"{t:14s} n={c['n']}  araç {c['tool_ok']}/{c['n']}  birebir {c['exact']}/{c['n']}")
    tot = sum(c["n"] for c in per.values())
    print(f"TOPLAM n={tot}  araç {sum(c['tool_ok'] for c in per.values())}/{tot}  birebir {sum(c['exact'] for c in per.values())}/{tot}")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
