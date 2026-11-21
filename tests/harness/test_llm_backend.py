"""LLMBackend: betikli sahte model ve yerel Ollama HTTP istemcisi (yalnızca localhost).

Ollama istemcisi GERÇEK bir yerel HTTP sunucusuna (127.0.0.1, rastgele port, test içinde) karşı sınanır; dış ağ yoktur.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from harness import settings
from harness.llm_backend import (ContextLimitExceeded, LLMBackend, LLMError, ModelReply, OllamaBackend, ScriptedBackend,
                                 ScriptExhausted, ToolCall)

MESSAGES = [{"role": "system", "content": "sistem"}, {"role": "user", "content": "soru"}]
TOOLS = [{"name": "get_stock_history", "description": "OHLCV", "parameters": {"type": "object", "properties": {"ticker": {"type": "string"}}}}]


# =============================== ModelReply / ToolCall ===============================
def test_reply_helpers():
    r = ModelReply(tool_calls=(ToolCall("get_stock_history", {"ticker": "THYAO"}),))
    assert r.has_tool_calls and r.text == "" and r.tool_calls[0].arguments == {"ticker": "THYAO"}
    assert not ModelReply(text="merhaba").has_tool_calls


# =============================== ScriptedBackend ===============================
def test_scripted_backend_replays_steps_in_order_and_records_calls():
    b = ScriptedBackend(["önce metin", ModelReply(tool_calls=(ToolCall("x", {}),)), lambda msgs, tools: f"{len(msgs)} mesaj"])
    assert isinstance(b, LLMBackend)
    assert b.chat(MESSAGES, TOOLS).text == "önce metin"
    assert b.chat(MESSAGES).tool_calls == (ToolCall("x", {}),)
    assert b.chat(MESSAGES).text == "2 mesaj"
    assert len(b.calls) == 3 and b.calls[0]["messages"] == MESSAGES and b.calls[0]["tools"] == TOOLS and b.calls[1]["tools"] is None


def test_scripted_backend_copies_inputs_so_later_mutation_cannot_change_the_record():
    b = ScriptedBackend(["a"])
    msgs = [dict(m) for m in MESSAGES]
    b.chat(msgs)
    msgs[0]["content"] = "değişti"
    assert b.calls[0]["messages"][0]["content"] == "sistem"


def test_scripted_backend_raises_when_the_script_runs_out_instead_of_looping():
    b = ScriptedBackend(["tek"])
    b.chat(MESSAGES)
    with pytest.raises(ScriptExhausted):
        b.chat(MESSAGES)


def test_scripted_step_may_raise_to_simulate_model_failures():
    def boom(msgs, tools):
        raise LLMError("sahte hata")
    with pytest.raises(LLMError):
        ScriptedBackend([boom]).chat(MESSAGES)


def test_scripted_backend_is_deterministic_and_has_a_name():
    def run():
        b = ScriptedBackend(["a", "b"], name="sahte")
        return b.name, [b.chat(MESSAGES).text, b.chat(MESSAGES).text]
    assert run() == run() == ("sahte", ["a", "b"])


# =============================== ayarlar ===============================
def test_llm_settings_defaults_and_environment_overrides(monkeypatch):
    assert settings.llm_temperature() == 0.0 and settings.llm_num_ctx() > 0 and settings.llm_model()
    assert settings.ollama_host().startswith("http://127.0.0.1") or settings.ollama_host().startswith("http://localhost")
    monkeypatch.setenv(settings.LLM_MODEL_ENV, "qwen2.5:3b")
    monkeypatch.setenv(settings.LLM_TEMPERATURE_ENV, "0.2")
    monkeypatch.setenv(settings.LLM_NUM_CTX_ENV, "4096")
    assert settings.llm_model() == "qwen2.5:3b" and settings.llm_temperature() == 0.2 and settings.llm_num_ctx() == 4096


@pytest.mark.parametrize("env,value", [("LLM_TEMPERATURE_ENV", "sıcak"), ("LLM_TEMPERATURE_ENV", "-1"),
                                       ("LLM_NUM_CTX_ENV", "0"), ("LLM_NUM_CTX_ENV", "çok")])
def test_invalid_llm_settings_are_rejected(monkeypatch, env, value):
    monkeypatch.setenv(getattr(settings, env), value)
    fn = settings.llm_temperature if env == "LLM_TEMPERATURE_ENV" else settings.llm_num_ctx
    with pytest.raises(ValueError):
        fn()


def test_seed_defaults_to_the_shared_random_seed():
    from config.settings import RANDOM_SEED
    assert settings.LLM_SEED == RANDOM_SEED


# =============================== yalnızca localhost ===============================
@pytest.mark.parametrize("host", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434", "http://127.0.0.5:1"])
def test_loopback_hosts_are_accepted(host):
    assert OllamaBackend(host=host, model="m").host == host.rstrip("/")


@pytest.mark.parametrize("host", ["http://example.com:11434", "http://192.168.1.20:11434", "http://10.0.0.2:11434", "http://0.0.0.0:11434",
                                  "https://api.openai.com", "http://localhost.evil.com:80", "http://127.0.0.1@evil.com:80",
                                  "ftp://127.0.0.1", "127.0.0.1:11434", ""])
def test_non_local_hosts_are_rejected_at_construction(host):
    with pytest.raises(ValueError):
        OllamaBackend(host=host, model="m")


# =============================== yerel sahte Ollama sunucusu ===============================
class _Server:
    def __init__(self):
        self.requests: list[dict] = []
        self.responses: list[tuple[int, dict | str, dict]] = []   # (durum, gövde, ek başlıklar)
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                outer.requests.append({"path": self.path, "body": json.loads(self.rfile.read(n) or b"{}"), "headers": dict(self.headers)})
                status, body, headers = outer.responses.pop(0)
                raw = body if isinstance(body, str) else json.dumps(body)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw.encode())))
                self.end_headers()
                self.wfile.write(raw.encode())

            def log_message(self, *a):  # sessiz
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def ok(content="", tool_calls=None, **extra):
    msg = {"role": "assistant", "content": content}
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return (200, {"model": "m", "message": msg, "done": True, **extra}, {})


def test_request_carries_model_temperature_context_seed_and_no_streaming(server):
    server.responses.append(ok("cevap", prompt_eval_count=120, eval_count=7))
    b = OllamaBackend(host=server.url, model="qwen-test", temperature=0.0, num_ctx=4096, seed=42)
    r = b.chat(MESSAGES, TOOLS)
    req = server.requests[0]
    assert req["path"] == "/api/chat"
    body = req["body"]
    assert body["model"] == "qwen-test" and body["stream"] is False and body["messages"] == MESSAGES
    assert body["options"] == {"temperature": 0.0, "num_ctx": 4096, "seed": 42}
    assert body["tools"] == [{"type": "function", "function": {"name": "get_stock_history", "description": "OHLCV",
                                                                "parameters": TOOLS[0]["parameters"]}}]
    assert r.text == "cevap" and r.prompt_tokens == 120 and r.completion_tokens == 7 and not r.has_tool_calls


def test_defaults_come_from_settings(server, monkeypatch):
    monkeypatch.setenv(settings.LLM_MODEL_ENV, "env-model")
    monkeypatch.setenv(settings.LLM_NUM_CTX_ENV, "2048")
    monkeypatch.setenv(settings.OLLAMA_HOST_ENV, server.url)
    server.responses.append(ok("x"))
    b = OllamaBackend()
    b.chat(MESSAGES)
    body = server.requests[0]["body"]
    assert body["model"] == "env-model" and body["options"]["temperature"] == 0.0 and body["options"]["num_ctx"] == 2048
    assert body["options"]["seed"] == settings.LLM_SEED and "tools" not in body


def test_tool_calls_are_parsed_with_dict_or_json_string_arguments(server):
    server.responses.append(ok("", [{"function": {"name": "get_stock_history", "arguments": {"ticker": "THYAO", "as_of": "2026-09-10"}}},
                                    {"function": {"name": "check_data_quality", "arguments": '{"tickers": ["THYAO"]}'}}]))
    r = OllamaBackend(host=server.url, model="m").chat(MESSAGES, TOOLS)
    assert r.tool_calls == (ToolCall("get_stock_history", {"ticker": "THYAO", "as_of": "2026-09-10"}),
                            ToolCall("check_data_quality", {"tickers": ["THYAO"]}))


@pytest.mark.parametrize("args", ["{bozuk", '["liste"]', 5])
def test_unusable_tool_arguments_are_an_llm_error_not_a_silent_empty_call(server, args):
    server.responses.append(ok("", [{"function": {"name": "x", "arguments": args}}]))
    with pytest.raises(LLMError):
        OllamaBackend(host=server.url, model="m").chat(MESSAGES, TOOLS)


def test_prompt_at_the_context_limit_is_reported_instead_of_silently_truncated(server):
    server.responses.append(ok("kırpılmış", prompt_eval_count=4096))
    with pytest.raises(ContextLimitExceeded):
        OllamaBackend(host=server.url, model="m", num_ctx=4096).chat(MESSAGES)


@pytest.mark.parametrize("response", [(500, {"error": "model yok"}, {}), (200, "html değil json", {}), (200, {"nomessage": 1}, {}),
                                      (200, {"message": {"role": "assistant", "content": 5}}, {})])
def test_http_and_protocol_errors_become_llm_errors(server, response):
    server.responses.append(response)
    with pytest.raises(LLMError):
        OllamaBackend(host=server.url, model="m").chat(MESSAGES)


def test_redirects_are_not_followed(server):
    server.responses.append((302, "", {"Location": "http://example.com/steal"}))
    with pytest.raises(LLMError):
        OllamaBackend(host=server.url, model="m").chat(MESSAGES)
    assert len(server.requests) == 1


def test_connection_refused_is_an_llm_error():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                                              # kimse dinlemiyor
    with pytest.raises(LLMError):
        OllamaBackend(host=f"http://127.0.0.1:{port}", model="m", timeout=0.5).chat(MESSAGES)


def test_environment_proxies_are_ignored(server, monkeypatch):
    """HTTP_PROXY gibi ortam değişkenleri istekleri başka bir yere yönlendiremez."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    server.responses.append(ok("proxy yok"))
    assert OllamaBackend(host=server.url, model="m").chat(MESSAGES).text == "proxy yok"


def test_same_request_gives_same_payload(server):
    for _ in range(2):
        server.responses.append(ok("a"))
    b = OllamaBackend(host=server.url, model="m")
    b.chat(MESSAGES, TOOLS)
    b.chat(MESSAGES, TOOLS)
    assert server.requests[0]["body"] == server.requests[1]["body"]


# =============================== ağ yalnızca bu dosyada ===============================
def test_only_llm_backend_imports_network_libraries_and_no_cloud_sdk_anywhere():
    """CLAUDE.md kural 3-4: harness/ içinde ağ kütüphanesi yalnızca llm_backend.py'de; hiçbir yerde bulut AI SDK'sı yok."""
    import ast
    from pathlib import Path

    net = {"requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "socket", "ftplib", "smtplib", "websocket", "websockets"}
    cloud = {"openai", "anthropic", "google", "cohere", "mistralai"}
    root = Path(__file__).resolve().parents[2]
    offenders: dict[str, set[str]] = {}
    for folder in ("harness", "training", "experiments"):
        for py in (root / folder).rglob("*.py"):
            names: set[str] = set()
            for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names.add(node.module.split(".")[0])
            bad = (names & cloud) | (names & net if py.name != "llm_backend.py" else set())
            if bad:
                offenders[str(py.relative_to(root))] = bad
    assert not offenders, offenders
