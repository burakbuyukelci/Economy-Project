"""Metin tabanlı araç protokolü: modelin yerel araç çağırma desteğine BAĞIMLI olmayan, kendi biçimimiz.

Neden: Gemma 3 Ollama şablonunda yerel `tools` desteği yoktur (ya da güvenilmezdir). Bu yüzden
  * araç tanımları sistem istemine METİN olarak girer (`render_tools_block`);
  * model araç çağırmak için `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` yazar (bir yanıtta birden çok olabilir);
  * araç sonuçları `user` rolünde `<tool_response name="...">…</tool_response>` olarak döner;
  * mesajlar yalnızca system/user/assistant rollerini taşır ve user/assistant ARDIŞIK değişir (Gemma şablonu bunu ister: ardışık aynı roller birleştirilir).
Aynı `encode_messages` hem çıkarımda (`OllamaBackend`, tool_mode="text") hem eğitim verisi biçimlendirmesinde (training/) kullanılır: eğitim ve çıkarım
istemi BİREBİR aynıdır. Biçim değişirse `TEXT_PROTOCOL_VERSION` artırılır (eğitim verisi dondurulmadan önce).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Sequence

TEXT_PROTOCOL_VERSION = "1"
TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"
TOOL_RESPONSE_OPEN = "<tool_response name="
TOOL_RESPONSE_CLOSE = "</tool_response>"
# model uydurma bir araç sonucu yazmasın: üretim bu dizeyle durdurulur (Ollama options.stop)
STOP_SEQUENCES = (TOOL_RESPONSE_OPEN,)

_COMPACT = {"ensure_ascii": False, "separators": (",", ":")}


def _dump(obj: Any, *, sort_keys: bool = False) -> str:
    return json.dumps(obj, sort_keys=sort_keys, **_COMPACT)


def render_tools_block(tools: Sequence[dict[str, Any]]) -> str:
    """Sistem istemine eklenen araç listesi + çağrı biçimi. Araç yoksa boş."""
    if not tools:
        return ""
    lines = ["ARAÇ ÇAĞRISI BİÇİMİ: bir araç çağırmak için yanıtında tam olarak şunu yaz (birden çok çağrı için blokları art arda yaz):",
             f'{TOOL_CALL_OPEN}{{"name": "<araç_adı>", "arguments": {{...}}}}{TOOL_CALL_CLOSE}',
             f"Sonuç bir sonraki mesajda {TOOL_RESPONSE_OPEN}\"<araç_adı>\">…{TOOL_RESPONSE_CLOSE} içinde gelir; sonucu kendin YAZMA.",
             "ARAÇLAR (ad: açıklama; parametre şeması):"]
    for t in tools:
        lines.append(f'- {t["name"]}: {t.get("description", "")} {_dump(t.get("parameters", {}), sort_keys=True)}')
    return "\n".join(lines)


def _call_block(call: dict[str, Any]) -> str:
    fn = call.get("function", call)
    return f'{TOOL_CALL_OPEN}{_dump({"name": fn["name"], "arguments": fn.get("arguments", {})})}{TOOL_CALL_CLOSE}'


def encode_messages(messages: Sequence[dict[str, Any]], tools: Sequence[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Yapısal mesajlar -> yalnızca system/user/assistant (ardışık değişen) metin mesajları. Girdi değişmez, çıktı belirlenimcidir."""
    out: list[dict[str, str]] = []

    def push(role: str, content: str) -> None:
        if out and out[-1]["role"] == role and role != "system":
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})

    block = render_tools_block(tools or [])
    for m in messages:
        role, content = m["role"], m.get("content") or ""
        if role == "system":
            push("system", content + (f"\n\n{block}" if block else ""))
        elif role == "assistant":
            parts = ([content] if content else []) + [_call_block(c) for c in m.get("tool_calls") or []]
            push("assistant", "\n".join(parts))
        elif role == "tool":
            push("user", f'{TOOL_RESPONSE_OPEN}"{m.get("name", "")}">\n{content}\n{TOOL_RESPONSE_CLOSE}')
        else:
            push("user", content)
    return out


def render_gemma_prompt(messages: Sequence[dict[str, str]]) -> str:
    """Eğitim metninin (`training.tokens.gemma_text`) çıkarım karşılığı: her mesaj `<start_of_turn>user|model\n...<end_of_turn>\n`, sona model tur başlığı.
    `<bos>` YAZILMAZ: GGUF tokenizer'ı BOS'u kendisi ekler (iki kez eklenirse model bozulur). System, ilk user'a katılır (`fold_system`)."""
    parts = []
    for m in fold_system(messages):
        role = "model" if m["role"] == "assistant" else "user"
        parts.append(f"<start_of_turn>{role}\n{m['content']}<end_of_turn>\n")
    return "".join(parts) + "<start_of_turn>model\n"


def fold_system(messages: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Gemma sohbet şablonu `system` rolünü bilmez: sistem metni İLK user mesajının başına `\n\n` ile eklenir (HF şablonu ve eğitim metniyle aynı).
    Ollama'ya yalnızca user/assistant gider; Modelfile şablonu bu yüzden system'e bakmaz."""
    out: list[dict[str, str]] = []
    system = ""
    for m in messages:
        if m["role"] == "system":
            system = m["content"] + "\n\n"
            continue
        content = m["content"]
        if system and m["role"] == "user":
            content, system = system + content, ""
        out.append({"role": m["role"], "content": content})
    if system:  # user yoksa (yalnızca system): user olarak gönder
        out.insert(0, {"role": "user", "content": system.rstrip()})
    return out


@dataclass(frozen=True)
class ParsedCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ParsedReply:
    text: str
    calls: tuple[ParsedCall, ...] = ()
    error: str | None = None          # biçim hatası: hiçbir çağrı çalıştırılmaz, model uyarılır


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _loads_tolerant(body: str) -> Any:
    """json.loads + tek bir söz dizimi toleransı: geçerli JSON nesnesinden SONRA yalnızca fazladan kapanış parantezi (`}` / `]`) varsa nesne kabul edilir
    (model sık sık `}}}}}` fazla yazıyor ve aynı çağrıyı 40 kez tekrarlıyordu). Başka artık metin (ikinci nesne, söz vb.) hâlâ hatadır; anlam değişmez."""
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        if exc.msg != "Extra data":
            raise
        data, end = json.JSONDecoder().raw_decode(body)
        if set(body[end:].strip()) <= set("}]"):
            return data
        raise


def parse_reply(raw: str) -> ParsedReply:
    """Model yanıtını (metin, araç çağrıları) olarak ayırır. Biri bozuksa HİÇBİR çağrı döndürülmez (kısmi çalıştırma yok)."""
    cut = raw.find(TOOL_RESPONSE_OPEN)
    if cut >= 0:                                           # uydurma araç sonucu kesilir
        raw = raw[:cut]
    calls: list[ParsedCall] = []
    pieces: list[str] = []
    pos = 0
    while True:
        start = raw.find(TOOL_CALL_OPEN, pos)
        if start < 0:
            pieces.append(raw[pos:])
            break
        pieces.append(raw[pos:start])
        end = raw.find(TOOL_CALL_CLOSE, start)
        if end < 0:
            return ParsedReply(raw.strip(), (), f"{TOOL_CALL_OPEN} açıldı ama {TOOL_CALL_CLOSE} ile kapatılmadı")
        body = _FENCE.sub("", raw[start + len(TOOL_CALL_OPEN):end].strip()).strip()
        try:
            data = _loads_tolerant(body)
        except json.JSONDecodeError as exc:
            return ParsedReply(raw.strip(), (), f"araç çağrısı geçerli JSON değil: {exc.msg}")
        if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not isinstance(data.get("arguments"), dict):
            return ParsedReply(raw.strip(), (), 'araç çağrısı {"name": <metin>, "arguments": <nesne>} biçiminde olmalı')
        calls.append(ParsedCall(data["name"], data["arguments"]))
        pos = end + len(TOOL_CALL_CLOSE)
    return ParsedReply("".join(pieces).strip(), tuple(calls))
