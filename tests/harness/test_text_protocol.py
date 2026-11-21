"""Metin tabanlı araç protokolü (harness/text_protocol.py): Gemma 3 Ollama'da yerel araç çağırmayı desteklemeyebilir.

Araç tanımları sistem istemine METİN olarak girer; model `<tool_call>{...}</tool_call>` yazar; araç sonuçları `user` rolünde `<tool_response>` olarak döner.
Mesajlar yalnızca system/user/assistant rolleri taşır ve user/assistant ARDIŞIK değişir (Gemma sohbet şablonu bunu ister). Aynı kodlama hem çıkarımda (OllamaBackend)
hem eğitim verisi biçimlendirmesinde kullanılır: tek doğruluk kaynağı.
"""
from __future__ import annotations

import json

import pytest

from harness.text_protocol import (TEXT_PROTOCOL_VERSION, TOOL_CALL_CLOSE, TOOL_CALL_OPEN, TOOL_RESPONSE_OPEN, encode_messages, parse_reply, render_tools_block)

TOOLS = [{"name": "get_stock_history", "description": "OHLCV history.", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}, "required": ["ticker"]}},
         {"name": "check_data_quality", "description": "Gate.", "parameters": {"type": "object", "properties": {}}}]


def call_block(name, **args):
    return f'{TOOL_CALL_OPEN}{json.dumps({"name": name, "arguments": args}, ensure_ascii=False, separators=(",", ":"))}{TOOL_CALL_CLOSE}'


# =============================== araç bloğu ===============================
def test_tools_block_lists_every_tool_and_states_the_call_format_deterministically():
    block = render_tools_block(TOOLS)
    assert "get_stock_history" in block and "check_data_quality" in block and TOOL_CALL_OPEN in block and TOOL_CALL_CLOSE in block
    assert render_tools_block(TOOLS) == block and render_tools_block([]) == ""
    assert json.dumps(TOOLS[0]["parameters"], ensure_ascii=False, separators=(",", ":"), sort_keys=True) in block


# =============================== kodlama ===============================
def test_system_gets_the_tools_block_and_roles_alternate_with_tool_results_as_user_messages():
    msgs = [{"role": "system", "content": "SİSTEM"}, {"role": "user", "content": "soru"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_stock_history", "arguments": {"ticker": "THYAO"}}}]},
            {"role": "tool", "name": "get_stock_history", "content": '{"status":"OK"}'},
            {"role": "assistant", "content": "HAZIR"}, {"role": "user", "content": "blok"}]
    enc = encode_messages(msgs, TOOLS)
    assert [m["role"] for m in enc] == ["system", "user", "assistant", "user", "assistant", "user"]
    assert enc[0]["content"].startswith("SİSTEM") and "get_stock_history" in enc[0]["content"]
    assert enc[2]["content"] == call_block("get_stock_history", ticker="THYAO")
    assert enc[3]["content"] == f'{TOOL_RESPONSE_OPEN}"get_stock_history">\n{{"status":"OK"}}\n</tool_response>'
    assert "tool_calls" not in json.dumps(enc)                                   # yerel araç alanı yok: şablon bilmez


def test_consecutive_tool_results_are_merged_into_one_user_message():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "a", "arguments": {}}}, {"function": {"name": "b", "arguments": {"x": 1}}}]},
            {"role": "tool", "name": "a", "content": "{1}"}, {"role": "tool", "name": "b", "content": "{2}"}]
    enc = encode_messages(msgs, TOOLS)
    assert [m["role"] for m in enc] == ["system", "user", "assistant", "user"]
    assert enc[2]["content"].count(TOOL_CALL_OPEN) == 2 and enc[3]["content"].count("<tool_response") == 2
    assert enc[3]["content"].index('name="a"') < enc[3]["content"].index('name="b"')


def test_assistant_text_before_a_call_is_kept_and_no_tools_means_no_block():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": "Önce veri alayım.", "tool_calls": [{"function": {"name": "a", "arguments": {}}}]}]
    enc = encode_messages(msgs, None)
    assert enc[0]["content"] == "S" and enc[2]["content"].startswith("Önce veri alayım.\n") and TOOL_CALL_OPEN in enc[2]["content"]


def test_encoding_does_not_mutate_the_input_and_is_deterministic():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "a", "arguments": {"z": 1, "a": 2}}}]}]
    snap = json.dumps(msgs, sort_keys=True)
    a = encode_messages(msgs, TOOLS)
    assert json.dumps(msgs, sort_keys=True) == snap and a == encode_messages(msgs, TOOLS)


def test_two_consecutive_user_messages_are_merged_so_the_template_never_sees_a_double_turn():
    enc = encode_messages([{"role": "system", "content": "S"}, {"role": "user", "content": "a"}, {"role": "user", "content": "b"}], None)
    assert [m["role"] for m in enc] == ["system", "user"] and "a" in enc[1]["content"] and "b" in enc[1]["content"]


# =============================== ayrıştırma ===============================
def test_parse_extracts_calls_and_the_text_around_them():
    text = f"Önce geçmişe bakıyorum.\n{call_block('get_stock_history', ticker='THYAO')}\n{call_block('check_data_quality')}"
    p = parse_reply(text)
    assert p.error is None and p.text == "Önce geçmişe bakıyorum."
    assert [(c.name, c.arguments) for c in p.calls] == [("get_stock_history", {"ticker": "THYAO"}), ("check_data_quality", {})]


def test_parse_of_plain_text_returns_no_calls_and_no_error():
    p = parse_reply("HAZIR")
    assert p.calls == () and p.error is None and p.text == "HAZIR"


def test_encode_then_parse_round_trips_the_tool_calls():
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "get_stock_history", "arguments": {"ticker": "ÇÖĞÜŞ", "n": 3}}}]}]
    enc = encode_messages(msgs, TOOLS)
    p = parse_reply(enc[2]["content"])
    assert [(c.name, c.arguments) for c in p.calls] == [("get_stock_history", {"ticker": "ÇÖĞÜŞ", "n": 3})]


@pytest.mark.parametrize("text", [
    f"{TOOL_CALL_OPEN}{{bozuk json}}{TOOL_CALL_CLOSE}",
    f'{TOOL_CALL_OPEN}{{"name": "a"}}{TOOL_CALL_CLOSE}',                          # arguments yok
    f'{TOOL_CALL_OPEN}{{"name": "a", "arguments": [1]}}{TOOL_CALL_CLOSE}',        # arguments nesne değil
    f'{TOOL_CALL_OPEN}{{"name": 5, "arguments": {{}}}}{TOOL_CALL_CLOSE}',
    f'{TOOL_CALL_OPEN}{{"name": "a", "arguments": {{}}}}',                        # kapanış yok
    f'{call_block("a")}\n{TOOL_CALL_OPEN}{{x}}{TOOL_CALL_CLOSE}',                 # biri geçerli biri bozuk: HİÇBİRİ çalıştırılmaz
])
def test_malformed_tool_calls_give_an_error_and_no_calls(text):
    p = parse_reply(text)
    assert p.error and p.calls == ()


def test_markdown_fences_inside_the_tag_are_tolerated():
    p = parse_reply(f'{TOOL_CALL_OPEN}\n```json\n{{"name": "a", "arguments": {{"k": 1}}}}\n```\n{TOOL_CALL_CLOSE}')
    assert p.error is None and p.calls[0].arguments == {"k": 1}


def test_a_hallucinated_tool_response_after_the_call_is_cut_off():
    p = parse_reply(f'{call_block("a")}\n{TOOL_RESPONSE_OPEN}"a">\n{{"uydurma": 1}}\n</tool_response>')
    assert [c.name for c in p.calls] == ["a"] and "uydurma" not in p.text


def test_protocol_version_is_a_string_for_the_training_records():
    assert isinstance(TEXT_PROTOCOL_VERSION, str) and TEXT_PROTOCOL_VERSION
