"""Ham (`raw`) istem yolu: harness konuşmayı EĞİTİM metniyle birebir biçimlendirip `/api/generate raw=true` gönderir.

Neden: Ollama'nın `/api/chat` yolu (model/şablon ne olursa olsun) eğitim metninden FAZLA token üretiyordu (tek mesajda +3, her asistan turunda +4; `check_template`, 2026-11-23);
`/api/generate raw=true` ise eğitim metniyle aynı sayıyı verir. Böylece şablon uyuşmazlığı riski ortadan kalkar.
"""
from __future__ import annotations

import json

import pytest

from harness import settings
from harness.llm_backend import OllamaBackend
from harness.text_protocol import encode_messages, fold_system, render_gemma_prompt
from tests.harness.test_llm_backend import _Server  # sahte yerel Ollama sunucusu
from training.tokens import gemma_text

MSGS = [{"role": "system", "content": "SİSTEM METNİ"}, {"role": "user", "content": "Soru?"},
        {"role": "assistant", "content": '<tool_call>{"name": "get_stock_history", "arguments": {"ticker": "THYAO"}}</tool_call>'},
        {"role": "user", "content": '<tool_response name="get_stock_history">{"status": "OK"}</tool_response>'}]


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def test_render_matches_the_training_text_exactly():
    # eğitim metni: <bos> + her mesaj `<start_of_turn>rol\n...<end_of_turn>\n`; çıkarımda BOS'u GGUF tokenizer'ı ekler, sona model tur başlığı eklenir
    assert render_gemma_prompt(MSGS) == gemma_text(MSGS).removeprefix("<bos>") + "<start_of_turn>model\n"
    assert render_gemma_prompt(MSGS).startswith("<start_of_turn>user\nSİSTEM METNİ\n\nSoru?<end_of_turn>\n")   # system ilk user'a katılır
    assert "<bos>" not in render_gemma_prompt(MSGS) and render_gemma_prompt(MSGS).endswith("<end_of_turn>\n<start_of_turn>model\n")
    assert render_gemma_prompt(fold_system(MSGS)) == render_gemma_prompt(MSGS)        # katlama idempotent


def test_default_is_raw_in_text_mode_and_env_can_disable(monkeypatch):
    monkeypatch.delenv("HARNESS_RAW_PROMPT", raising=False)
    assert settings.llm_raw() is True and OllamaBackend(model="m").raw is True
    monkeypatch.setenv("HARNESS_RAW_PROMPT", "0")
    assert settings.llm_raw() is False and OllamaBackend(model="m").raw is False
    monkeypatch.setenv("HARNESS_RAW_PROMPT", "evet-belki")
    with pytest.raises(ValueError):
        settings.llm_raw()


def test_raw_request_goes_to_generate_with_the_exact_prompt_and_stop(server):
    server.responses.append((200, {"response": '<tool_call>{"name": "get_stock_history", "arguments": {"ticker": "THYAO"}}</tool_call>',
                                   "prompt_eval_count": 50, "eval_count": 9}, {}))
    b = OllamaBackend(host=server.url, model="gemma3-bist", raw=True, tool_mode="text")
    reply = b.chat([{"role": "system", "content": "SİSTEM"}, {"role": "user", "content": "Soru?"}], None)
    req = server.requests[0]
    assert req["path"] == "/api/generate" and req["body"]["raw"] is True and req["body"]["stream"] is False and "messages" not in req["body"]
    assert req["body"]["prompt"] == "<start_of_turn>user\nSİSTEM\n\nSoru?<end_of_turn>\n<start_of_turn>model\n"
    assert req["body"]["options"]["stop"] == ["<tool_response name="] and req["body"]["options"]["temperature"] == 0 and req["body"]["options"]["seed"] == 42
    assert [c.name for c in reply.tool_calls] == ["get_stock_history"] and reply.prompt_tokens == 50 and reply.completion_tokens == 9


def test_raw_final_text_and_malformed_call_are_parsed_like_the_chat_path(server):
    server.responses.append((200, {"response": "Nihai metin.\nEYLEM: INVESTIGATE", "prompt_eval_count": 7, "eval_count": 5}, {}))
    server.responses.append((200, {"response": '<tool_call>{"name": "x", "arguments": {', "prompt_eval_count": 7, "eval_count": 5}, {}))
    b = OllamaBackend(host=server.url, model="m", raw=True, tool_mode="text")
    r1 = b.chat([{"role": "user", "content": "s"}], None)
    assert r1.text.endswith("EYLEM: INVESTIGATE") and not r1.tool_calls and r1.format_error is None
    r2 = b.chat([{"role": "user", "content": "s"}], None)
    assert r2.format_error and not r2.tool_calls


def test_raw_false_keeps_the_chat_path(server):
    server.responses.append((200, {"message": {"role": "assistant", "content": "merhaba"}, "prompt_eval_count": 3, "eval_count": 1}, {}))
    b = OllamaBackend(host=server.url, model="m", raw=False, tool_mode="text")
    assert b.chat([{"role": "user", "content": "s"}], None).text == "merhaba"
    assert server.requests[0]["path"] == "/api/chat"


def test_raw_http_errors_become_llm_errors(server):
    from harness.llm_backend import LLMError
    server.responses.append((500, "hata", {}))
    with pytest.raises(LLMError):
        OllamaBackend(host=server.url, model="m", raw=True, tool_mode="text").chat([{"role": "user", "content": "s"}], None)


def test_encode_messages_is_unchanged_for_plain_text_messages():
    plain = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    assert json.dumps(encode_messages(plain, None), sort_keys=True) == json.dumps(plain, sort_keys=True)
