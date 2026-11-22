"""Eğitim kaydı biçimi (JSONL satırı) ve kayıp maskesi.

Kayıt, ÇIKARIMDA modele giden metnin BİREBİR aynısını taşır: `text_messages = harness.text_protocol.encode_messages(messages, tools)` (system+araç bloğu, user, assistant, ...).
`train_mask[i]` metin mesajı i için kayıp hesaplansın mı: yalnızca asistan mesajları (araç çağrıları ve nihai metin) ve hatalı (maskeli) tur HARİÇ.
System, user (soru, politika bloğu, geri besleme) ve araç çıktıları (`<tool_response>` user mesajı) HİÇBİR ZAMAN eğitilmez.
"""
from __future__ import annotations

import json
from typing import Any

from harness.agent_loop import SYSTEM_PROMPT_VERSION
from harness.mock_tools import aux_dataset_versions
from harness.text_protocol import TEXT_PROTOCOL_VERSION, encode_messages
from harness.tool_view import model_tool_specs
from schemas.common import SCHEMA_VERSION
from training import spec
from training.teacher import Generated
from training.tokens import count_tokens, have_real_tokenizer

RECORD_VERSION = "1"


def build_record(g: Generated) -> dict[str, Any]:
    s, q, res = g.session, g.question, g.result
    tools = model_tool_specs(s.visible_tools)
    text_messages = encode_messages(res.messages, tools)
    assistant_structured = [i for i, m in enumerate(res.messages) if m["role"] == "assistant"]
    assistant_encoded = [i for i, m in enumerate(text_messages) if m["role"] == "assistant"]
    if len(assistant_structured) != len(assistant_encoded):
        raise ValueError("asistan mesaj sayısı kodlamada değişti (ardışık asistan birleşmesi?)")
    mask = [False] * len(text_messages)
    for turn, idx in enumerate(assistant_encoded):
        mask[idx] = turn not in g.bad_turns
    pol = s.policy
    envs = [r.envelope for r in s.store.records]
    versions = sorted({e["data_version"] for e in envs})
    aux = sorted({v for e in envs for v in aux_dataset_versions(e)})
    final = res.final
    return {
        "id": q.id, "split": q.split, "type": q.type, "template_idx": q.template_idx,
        "question": q.text, "as_of": q.as_of.isoformat(), "tickers": list(q.tickers),
        "group_held_out": q.type != "catch_up",
        "label": pol.label.value if pol else None, "rule_id": pol.rule_id if pol else None,
        "reasons": [r.code for r in pol.reasons] if pol else [], "gate_status": pol.gate_status if pol else None,
        "recovery": g.recovery, "bad_turns": list(g.bad_turns), "n_final_attempts": final.attempt if final else None,
        "versions": {"record": RECORD_VERSION, "generator": spec.GENERATOR_VERSION, "prompt": SYSTEM_PROMPT_VERSION,
                     "text_protocol": TEXT_PROTOCOL_VERSION, "schema": SCHEMA_VERSION, "data": versions, "fundamentals": aux},
        "tools": [t["name"] for t in tools],
        "messages": res.messages, "text_messages": text_messages, "train_mask": mask,
        "tokens": count_tokens(text_messages), "token_source": "gemma3" if have_real_tokenizer() else "estimate",
    }


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)
