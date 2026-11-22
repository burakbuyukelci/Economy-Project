"""Soyut LLM arka ucu: yerel Ollama HTTP istemcisi (yalnızca loopback) ve testler için betikli sahte model.

CLAUDE.md kural 4: final sistemde bulut AI API'si yok. Bu dosya `urllib` kullanan TEK harness dosyasıdır
(testle denetlenir); adres yalnızca localhost / loopback IP olabilir, yönlendirme izlenmez, ortam proxy'leri yok sayılır.

Arayüz küçük tutuldu: `chat(messages, tools) -> ModelReply`.
  messages  [{"role": "system|user|assistant|tool", "content": str, ("tool_calls": [...])}]
  tools     MCP'den bağımsız yalın biçim: [{"name", "description", "parameters": <JSON şeması>}]  (yoksa None)
Ayarlar (model adı, sıcaklık = 0, bağlam sınırı, seed) `harness/settings.py`'den gelir ve ortam değişkeniyle ezilir.
"""
from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence
from urllib.parse import urlsplit

from harness import settings
from harness.text_protocol import STOP_SEQUENCES, encode_messages, fold_system, parse_reply


class LLMError(RuntimeError):
    """Model çağrısı başarısız (bağlantı, HTTP, protokol, bozuk araç argümanı)."""


class ContextLimitExceeded(LLMError):
    """İstem bağlam sınırına dayandı: Ollama sessizce kırpardı (sistem istemi kaybolabilir), bu yüzden hata sayılır."""


class ScriptExhausted(LLMError):
    """Betikli sahte modelin adımları bitti (test, beklenenden fazla çağrı yaptı)."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    format_error: str | None = None     # metin protokolünde bozuk araç çağrısı: çağrı çalıştırılmaz, model uyarılır (oturum "geçersiz çağrı" sayar)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


Messages = Sequence[dict[str, Any]]
ToolSpecs = Sequence[dict[str, Any]]


class LLMBackend(ABC):
    name: str = "llm"

    @abstractmethod
    def chat(self, messages: Messages, tools: ToolSpecs | None = None) -> ModelReply:
        """Bir model turu: araç çağrıları ve/veya metin."""


# =============================== betikli sahte model ===============================
class ScriptedBackend(LLMBackend):
    """Testler için: önceden yazılmış adımlar sırayla döner. Adım bir ModelReply, bir metin ya da
    (mesajlar, araçlar) -> ModelReply | metin olan bir fonksiyon olabilir (önceki araç zarflarından sayı çekmek için).
    Adımlar bitince döngüye girmez, `ScriptExhausted` fırlatır. Her çağrı `calls` içine KOPYA olarak kaydedilir."""

    def __init__(self, steps: Sequence[Any], *, name: str = "scripted") -> None:
        self._steps = list(steps)
        self._i = 0
        self.name = name
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: Messages, tools: ToolSpecs | None = None) -> ModelReply:
        msgs = json.loads(json.dumps(list(messages), ensure_ascii=False))
        tls = json.loads(json.dumps(list(tools), ensure_ascii=False)) if tools is not None else None
        self.calls.append({"messages": msgs, "tools": tls})
        if self._i >= len(self._steps):
            raise ScriptExhausted(f"betik bitti: {self._i} adım vardı, {self._i + 1}. çağrı geldi")
        step = self._steps[self._i]
        self._i += 1
        if callable(step):
            step = step(json.loads(json.dumps(msgs)), tls)
        return step if isinstance(step, ModelReply) else ModelReply(text=str(step))


# =============================== yerel Ollama ===============================
_LOOPBACK_NAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def _check_local(host: str) -> str:
    """Adres yalnızca http(s)://<loopback>[:port] olabilir. Dış ana makine, kimlik bilgisi ve yol reddedilir."""
    parts = urlsplit(host)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Ollama adresi http://localhost:PORT biçiminde olmalı: {host!r}")
    if parts.username is not None or parts.password is not None:
        raise ValueError(f"Ollama adresinde kimlik bilgisi olamaz: {host!r}")
    name = parts.hostname.lower()
    if name not in _LOOPBACK_NAMES:
        try:
            if not ipaddress.ip_address(name).is_loopback:
                raise ValueError("loopback değil")
        except ValueError:
            raise ValueError(f"Ollama yalnızca yerel olabilir (localhost/loopback): {host!r}") from None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError(f"Ollama adresi yalnızca ana makine ve port içermeli: {host!r}")
    return host.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # yönlendirme izlenmez: 3xx HTTPError olarak yükselir


def _to_ollama_tools(tools: ToolSpecs) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t.get("parameters", {"type": "object", "properties": {}})}}
            for t in tools]


def _parse_arguments(raw: Any, tool: str) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMError(f"{tool}: araç argümanları geçerli JSON değil: {exc}") from None
    if not isinstance(raw, dict):
        raise LLMError(f"{tool}: araç argümanları bir nesne olmalı, gelen: {type(raw).__name__}")
    return raw


class OllamaBackend(LLMBackend):
    """POST {host}/api/chat (akış yok). Sıcaklık varsayılan 0, seed sabit; ayarlar settings'ten, parametreyle ezilebilir."""

    def __init__(self, *, host: str | None = None, model: str | None = None, temperature: float | None = None,
                 num_ctx: int | None = None, seed: int | None = None, timeout: float | None = None, tool_mode: str | None = None,
                 max_new_tokens: int | None = None) -> None:
        self.host = _check_local(host if host is not None else settings.ollama_host())
        self.model = model or settings.llm_model()
        self.temperature = settings.llm_temperature() if temperature is None else temperature
        self.num_ctx = settings.llm_num_ctx() if num_ctx is None else num_ctx
        self.seed = settings.LLM_SEED if seed is None else seed
        self.timeout = settings.llm_timeout() if timeout is None else timeout
        self.max_new_tokens = max_new_tokens    # None = sınırsız; şablon denetimi gibi yalnızca prompt_eval_count gereken çağrılarda 1
        self.tool_mode = tool_mode if tool_mode is not None else settings.llm_tool_mode()
        if self.tool_mode not in ("text", "native"):
            raise ValueError(f"tool_mode 'text' ya da 'native' olmalı: {self.tool_mode!r}")
        self.name = f"ollama:{self.model}"
        # ortam proxy'lerini YOK SAY (istek başka yere yönlenemesin) ve yönlendirmeyi izleme
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def chat(self, messages: Messages, tools: ToolSpecs | None = None) -> ModelReply:
        body: dict[str, Any] = {
            "model": self.model, "messages": list(messages), "stream": False,
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx, "seed": self.seed},
        }
        if self.max_new_tokens is not None:
            body["options"]["num_predict"] = self.max_new_tokens
        if self.tool_mode == "text":     # araçlar istemde METİN; yalnızca system/user/assistant rolleri; uydurma araç sonucu yazılamaz
            body["messages"] = fold_system(encode_messages(messages, tools))
            body["options"]["stop"] = list(STOP_SEQUENCES)
        elif tools:
            body["tools"] = _to_ollama_tools(tools)
        req = urllib.request.Request(f"{self.host}/api/chat", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMError(f"Ollama HTTP {exc.code}: {exc.reason}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise LLMError(f"Ollama'ya bağlanılamadı ({self.host}): {exc}") from None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LLMError(f"Ollama yanıtı geçerli JSON değil: {exc}") from None
        return self._parse(payload)

    def raw_prompt_tokens(self, prompt: str) -> int:
        """`/api/generate` raw=true: Modelfile şablonu UYGULANMADAN, verilen metnin token sayısı (şablon doğrulaması için: sohbet çağrısının prompt_eval_count'uyla eşleşmeli)."""
        body = {"model": self.model, "prompt": prompt, "raw": True, "stream": False,
                "options": {"temperature": 0, "num_ctx": self.num_ctx, "seed": self.seed, "num_predict": 1}}
        req = urllib.request.Request(f"{self.host}/api/generate", data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise LLMError(f"Ollama'ya bağlanılamadı ({self.host}): {exc}") from None
        n = payload.get("prompt_eval_count")
        if not isinstance(n, int):
            raise LLMError("Ollama yanıtında prompt_eval_count yok")
        return n

    def _parse(self, payload: Any) -> ModelReply:
        msg = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get("content", ""), str):
            raise LLMError("Ollama yanıtında geçerli 'message' yok")
        if self.tool_mode == "text":
            return self._parse_text(msg.get("content", ""), payload)
        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") if isinstance(tc, dict) else None
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str):
                raise LLMError("Ollama araç çağrısında 'function.name' yok")
            calls.append(ToolCall(fn["name"], _parse_arguments(fn.get("arguments", {}), fn["name"])))
        prompt, done = self._counts(payload)
        return ModelReply(msg.get("content", ""), tuple(calls), prompt, done)

    def _counts(self, payload: dict[str, Any]) -> tuple[int | None, int | None]:
        prompt, done = payload.get("prompt_eval_count"), payload.get("eval_count")
        if isinstance(prompt, int) and prompt >= self.num_ctx:
            raise ContextLimitExceeded(f"istem {prompt} token; bağlam sınırı {self.num_ctx} (kırpılmış olabilir)")
        return (prompt if isinstance(prompt, int) else None), (done if isinstance(done, int) else None)

    def _parse_text(self, content: str, payload: dict[str, Any]) -> ModelReply:
        parsed = parse_reply(content)
        prompt, done = self._counts(payload)
        return ModelReply(parsed.text, tuple(ToolCall(c.name, c.arguments) for c in parsed.calls), prompt, done, parsed.error)
