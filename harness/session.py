"""Harness oturumu: soru -> as_of kilidi -> durum makinesi -> araç -> sözleşme doğrulaması.

MCP SDK'sından BAĞIMSIZDIR; MCP sunucusu (mcp_server.py) bu sınıfın üstünde ince bir adaptördür.

Bir araç çağrısının geçtiği kapılar (sırayla; ilk başarısız olan INVALID_TOOL_CALL olarak loglanır):
  1. UNKNOWN_TOOL            araç adı 15 araçtan biri değil
  2. durum makinesi          NO_TOOLS_IN_STATE / STATE_ALREADY_PASSED / MANDATORY_STATE_SKIPPED / PRECONDITION_FAILED
  3. AS_OF_MISSING/MISMATCH  params.as_of, sorunun ön metninden çıkarılan oturum as_of'una EŞİT olmalı
  4. INVALID_PARAMS          şema (schemas.registry.validate_params) doğrulaması
Sonra araç çalışır; çıktı validate_envelope'tan geçer (geçmezse HARNESS_ERROR, modele iletilmez).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from harness import settings
from harness.as_of import resolve_as_of
from harness.event_log import EventLog
from harness.routing import DEFAULT_ROUTING, ReviewStatus, Routing
from harness.state_machine import Decision, StateMachine
from harness.tool_runner import RealToolUnavailable, ToolRejected, run_tool
from schemas.enums import AllowedAction, ToolName
from schemas.registry import validate_envelope, validate_params

Runner = Callable[[ToolName, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ToolCallResult:
    ok: bool
    envelope: dict[str, Any] | None = None
    error: dict[str, Any] | None = None  # {"type": "INVALID_TOOL_CALL"|"HARNESS_ERROR", "code", "message", ...}


_FROM_SETTINGS: Any = object()  # "varsayılan analiz tarihini settings/ortam değişkeninden oku" işareti


class HarnessSession:
    def __init__(self, as_of: date, *, as_of_source: str = "explicit", runner: Runner | None = None,
                 log: EventLog | None = None, routing: Routing = DEFAULT_ROUTING) -> None:
        self.as_of = as_of
        self.as_of_source = as_of_source
        self.warnings: list[str] = []  # harness düzeyi uyarılar ("KOD: açıklama"); araç zarfına GİRMEZ
        self._runner: Runner = runner or run_tool
        self.log = log if log is not None else EventLog(settings.EVENT_LOG_PATH)
        self.machine = StateMachine(self.log, routing)
        self.tool_envelopes: list[dict[str, Any]] = []  # modele iletilen, doğrulanmış zarflar (sıralı)
        self.log.append("SESSION_START", as_of=as_of.isoformat(), as_of_source=as_of_source)
        if as_of_source == "default":
            msg = f"soruda analiz tarihi işareti yok; varsayılan {as_of.isoformat()} kullanıldı"
            self.warnings.append(f"AS_OF_ASSUMED: {msg}")
            self.log.append("AS_OF_ASSUMED", as_of=as_of.isoformat(), message=msg)
        self.machine.begin()

    @classmethod
    def from_question(cls, question: str, *, explicit_as_of: date | None = None,
                      default_as_of: date | None = _FROM_SETTINGS, **kwargs: Any) -> "HarnessSession":
        """Oturum as_of'u MODEL tarafından değil harness tarafından belirlenir.

        Öncelik: sorudaki işaret > explicit_as_of (eval seti) > varsayılan (settings/ortam/CLI) > hata.
        Yalnızca varsayılana düşülürse AS_OF_ASSUMED uyarısı üretilir.
        """
        if default_as_of is _FROM_SETTINGS:
            default_as_of = settings.default_as_of()
        resolved = resolve_as_of(question, explicit=explicit_as_of, default=default_as_of)
        return cls(resolved.date, as_of_source=resolved.source, **kwargs)

    # ---- LLM'in kullandığı tek giriş ----------------------------------------------------
    def call_tool(self, name: str, params: dict[str, Any]) -> ToolCallResult:
        try:
            tool = ToolName(name)
        except ValueError:
            return self._invalid(name, "UNKNOWN_TOOL", f"tanımsız araç: {name!r}")

        decision = self.machine.check(tool)
        if not decision.allowed:
            return self._invalid(tool, decision.code or "INVALID", decision.message or "")

        problem = self._check_as_of(params)
        if problem:
            return self._invalid(tool, *problem)
        try:
            validate_params(tool, params)
        except ValidationError as exc:
            return self._invalid(tool, "INVALID_PARAMS", _short_errors(exc))

        try:
            envelope = self._runner(tool, params)
            parsed = validate_envelope(envelope)
            if parsed.as_of != self.as_of:
                raise ValueError(f"zarf as_of ({parsed.as_of}) != oturum as_of ({self.as_of})")
        except ToolRejected as exc:  # gerçek araç as_of'u reddetti: modelin geçersiz çağrısı sayılır
            return self._invalid(tool, exc.code, exc.message)
        except RealToolUnavailable as exc:
            return self._harness_error(tool, "TOOL_UNAVAILABLE", str(exc))
        except (ValidationError, ValueError, KeyError) as exc:
            return self._harness_error(tool, "TOOL_OUTPUT_INVALID", _short_errors(exc))

        state_before = self.machine.state.value
        self.machine.commit(tool, envelope)
        self.tool_envelopes.append(envelope)
        self.log.append("TOOL_CALL", tool=tool.value, state_before=state_before, state_after=self.machine.state.value,
                        status=envelope["status"], input_hash=envelope["input_hash"],
                        data_version=envelope["data_version"])
        return ToolCallResult(ok=True, envelope=envelope)

    # ---- orkestratör tarafı (LLM'e açılmaz) -----------------------------------------------
    def request_explanation(self) -> Decision:
        return self.machine.request_explanation()

    def complete_explanation(self, action: AllowedAction, text: str) -> None:
        self.machine.complete_explanation(action, text)

    def record_human_review(self, decision: ReviewStatus, reviewer: str, reason: str) -> None:
        self.machine.record_human_review(decision, reviewer, reason)

    def close(self) -> None:
        self.machine.close()

    def get_state(self) -> dict[str, Any]:
        """Salt-okunur kopya; MCP üzerinden AÇILMAZ."""
        return {**self.machine.snapshot(), "as_of": self.as_of.isoformat(), "as_of_source": self.as_of_source,
                "warnings": list(self.warnings)}

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.log.events

    # ---- iç yardımcılar ------------------------------------------------------------------
    def _check_as_of(self, params: dict[str, Any]) -> tuple[str, str] | None:
        if "as_of" not in params:
            return "AS_OF_MISSING", f"as_of zorunlu; oturum analiz tarihi {self.as_of.isoformat()}"
        raw = params["as_of"]
        try:
            given = raw if isinstance(raw, date) else date.fromisoformat(str(raw))
        except ValueError:
            return "INVALID_PARAMS", f"as_of geçerli bir YYYY-MM-DD tarihi değil: {raw!r}"
        if given != self.as_of:
            return "AS_OF_MISMATCH", (f"as_of={given.isoformat()} oturum analiz tarihi "
                                      f"{self.as_of.isoformat()} ile aynı olmalı")
        return None

    def _invalid(self, tool: ToolName | str, code: str, message: str) -> ToolCallResult:
        self.machine.reject(tool, code, message)
        return ToolCallResult(ok=False, error={
            "type": "INVALID_TOOL_CALL", "code": code, "message": message,
            "state": self.machine.state.value,
            "allowed_tools": [t.value for t in self.machine.callable_tools()],
        })

    def _harness_error(self, tool: ToolName, code: str, message: str) -> ToolCallResult:
        self.log.append("HARNESS_ERROR", tool=tool.value, code=code, message=message)
        return ToolCallResult(ok=False, error={"type": "HARNESS_ERROR", "code": code, "message": message})


def _short_errors(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc']) or '<kök>'}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(parts)
    return str(exc)
