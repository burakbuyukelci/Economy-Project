"""Durum makinesi (proje dokümanı §23). MCP SDK'sından BAĞIMSIZ saf Python.

Fikir: LLM yalnızca ALAN araçlarını çağırır; durum geçişlerini HARNESS yapar.
  1. Model bir araç çağırır -> `check(tool)`: bu araç hangi durumda çalışır, o duruma gidilebilir mi?
     Aracın izinli olduğu durumlardan, şimdiki durumdan SONRA gelen ilki hedef durumdur.
     Araya giren durumlardan ZORUNLU ve henüz yerine getirilmemiş olan varsa:
       * manuel durumsa çağrı INVALID (MANDATORY_STATE_SKIPPED),
       * harness'in kendi çalıştıracağı (auto) durumsa `Decision.auto_before` içinde listelenir; oturum
         önce o adımları çalıştırır, sonra modelin çağrısını.
  2. Araç çalışır -> `commit(tool, envelope)`: harness hedef duruma geçer; durumun zorunlu aracı
     başarıyla çağrılmışsa otomatik bir sonraki duruma ilerler.
  3. Zorunlu durumlar tablodan (routing.py) ve modelin BAŞARIYLA çağırdığı araçlardan türetilir.
  4. check_data_quality sonucu HARD_BLOCK/ANALYSIS_UNSAFE ise doğrudan GENERATE_EXPLANATION
     (§26 güvenli hata yolu); eylem yalnızca ANALYSIS_UNSAFE olabilir.
  5. Geçersiz çağrılar sayılır ve EventLog'a yazılır (deney metriği: invalid tool-call rate).
  6. Sıra sertliği: strict = geçilmiş duruma dönüş reddedilir; lenient = çalışır, durum geri gitmez.
     İki modda da ORDER_VIOLATION olayı yazılır ve `n_order_violations` artar.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harness.event_log import EventLog
from harness.routing import DEFAULT_ROUTING, ReviewStatus, Routing, State
from schemas.enums import AllowedAction, ToolName


class HarnessRuleViolation(Exception):
    """Harness kuralı ihlali (orkestratör tarafı API'leri için). LLM çağrıları Decision döndürür."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Decision:
    allowed: bool
    target: State | None = None
    code: str | None = None
    message: str | None = None
    auto_before: tuple[State, ...] = ()  # çağrıdan ÖNCE harness'in çalıştıracağı zorunlu durumlar
    order_violation: bool = False        # geçilmiş bir duruma dönüş (strict: reddedildi, lenient: izin verildi)


class StateMachine:
    def __init__(self, log: EventLog | None = None, routing: Routing = DEFAULT_ROUTING, *,
                 order_mode: str = "strict", enforce: bool = True) -> None:
        if order_mode not in ("strict", "lenient"):
            raise ValueError(f"order_mode 'strict' veya 'lenient' olmalı: {order_mode!r}")
        self.log = log if log is not None else EventLog()
        self.routing = routing
        self.order_mode = order_mode
        self.enforce = enforce  # False: yalnızca bilgi amaçlı (profil A/B), sıra ve zorunluluk denetlenmez
        self._index = {s: i for i, s in enumerate(routing.order)}
        self.state: State = State.START
        self.completed: set[State] = set()
        self.ok_calls: list[tuple[ToolName, State]] = []   # (araç, çağrıldığı durum): yalnızca status=OK
        self.safe_failure = False
        self.action: AllowedAction | None = None
        self.explanation: str | None = None
        self.review_status = ReviewStatus.PENDING_HUMAN_REVIEW
        self.n_invalid_calls = 0
        self.n_order_violations = 0

    # ---- başlangıç --------------------------------------------------------
    def begin(self) -> None:
        """START ve SELECT_UNIVERSE harness-içidir; ikisini geçip LOAD_MARKET_DATA'da bekler."""
        if self.state != State.START:
            raise HarnessRuleViolation("ALREADY_STARTED", "oturum zaten başlatıldı")
        self.completed.add(State.START)
        self._transition(State.SELECT_UNIVERSE, "begin")
        self.completed.add(State.SELECT_UNIVERSE)
        self._transition(State.LOAD_MARKET_DATA, "begin")

    # ---- türetilmiş zorunluluk ----------------------------------------------
    def mandatory_states(self) -> set[State]:
        """Sabit zorunlular + başarıyla çağrılan araçların tetiklediği durumlar (soru türü YOK)."""
        out = set(self.routing.always_mandatory)
        for tool, _ in self.ok_calls:
            out |= self.routing.tool_triggers.get(tool, frozenset())
        return out

    def _unmet(self, state: State) -> bool:
        return (
            state in self.mandatory_states()
            and state not in self.completed
            and bool(self.routing.state_tools[state])
        )

    def pending_mandatory(self) -> list[State]:
        """Açıklamadan önce henüz yerine getirilmemiş zorunlu durumlar (sıralı; auto olanlar dahil)."""
        if self.safe_failure:
            return []  # güvenli hata yolu: kalan analiz adımları aranmaz
        return [s for s in self.routing.order if self._unmet(s)]

    def has_evidence_source(self) -> bool:
        """Kanıt paketi için en az bir BAŞARILI analiz çağrısı var mı?"""
        return any(s in self.routing.evidence_sources for _, s in self.ok_calls)

    # ---- çağrı denetimi (saf, durum DEĞİŞTİRMEZ) -------------------------------
    def check(self, tool: ToolName) -> Decision:
        r = self.routing
        if self.state == State.LOG_AND_CLOSE:
            return Decision(False, code="SESSION_CLOSED", message="oturum kapandı")
        if self.state in (State.START, State.SELECT_UNIVERSE):
            return Decision(False, code="NOT_STARTED", message="oturum henüz başlatılmadı")
        if self.state in r.post_analysis:
            return Decision(False, code="NO_TOOLS_IN_STATE",
                            message=f"{self.state.value} aşamasında araç çağrılamaz; açıklama yazılmalı")
        if not self.enforce:
            return Decision(True)

        tool_states = [s for s in r.order if tool in r.state_tools[s]]
        if not tool_states:
            return Decision(False, code="UNROUTED_TOOL", message=f"{tool.value} hiçbir duruma bağlı değil")

        current = self._index[self.state]
        candidates = [s for s in tool_states if self._index[s] >= current]
        order_violation = False
        if candidates:
            target = candidates[0]
        else:
            order_violation = True
            if self.order_mode == "strict":
                return Decision(False, code="STATE_ALREADY_PASSED", order_violation=True,
                                message=f"{tool.value} için uygun durum geçildi (şimdiki durum {self.state.value})")
            target = tool_states[-1]  # lenient: en son uygun durum; durum geri gitmez

        skipped: list[State] = []
        auto_before: list[State] = []
        for s in r.order[current:self._index[target]]:
            if self._unmet(s):
                (auto_before if s in r.auto_states else skipped).append(s)
        if skipped:
            names = ", ".join(s.value for s in skipped)
            return Decision(False, code="MANDATORY_STATE_SKIPPED", order_violation=order_violation,
                            message=f"{tool.value} çağrılmadan önce zorunlu durum(lar) tamamlanmalı: {names}")

        if (target == State.BUILD_EVIDENCE or State.BUILD_EVIDENCE in auto_before) and not self.has_evidence_source():
            return Decision(False, code="PRECONDITION_FAILED", order_violation=order_violation,
                            message="kanıt paketi için önce en az bir analiz aracı başarıyla çağrılmalı (NO_EVIDENCE_SOURCE)")
        return Decision(True, target=target, auto_before=tuple(auto_before), order_violation=order_violation)

    def callable_tools(self) -> list[ToolName]:
        """Şu anda geçerli olacak araçlar (model için ipucu; get_state çıktısında da var)."""
        return [t for t in ToolName if self.check(t).allowed]

    # ---- çağrı sonrası ilerleme --------------------------------------------------
    def commit(self, tool: ToolName, envelope: dict[str, Any]) -> None:
        d = self.check(tool)
        if not d.allowed:
            raise HarnessRuleViolation(d.code or "INVALID", d.message or "")
        if d.auto_before:
            raise HarnessRuleViolation("AUTO_STEP_PENDING",
                                       "önce harness adımları çalıştırılmalı: " + ", ".join(s.value for s in d.auto_before))
        ok = envelope.get("status") == "OK"
        if not self.enforce:
            if ok:
                self.ok_calls.append((tool, self.state))
            return
        target = d.target
        assert target is not None
        r = self.routing
        backward = self._index[target] < self._index[self.state]
        if d.order_violation:  # lenient: çağrı çalıştı ama sıra ihlali
            self._order_violation(tool, enforced=False)

        if not backward:
            # araya giren araçsız durumlar (ör. PREVIEW_STRATEGIES) sessizce geçilir
            for s in r.order[self._index[self.state]:self._index[target]]:
                if not r.state_tools[s]:
                    self.completed.add(s)
            if target != self.state:
                self._transition(target, f"tool_call:{tool.value}")

        if not ok:
            return  # başarısız çağrı ne durumu tamamlar ne de zorunluluk tetikler
        self.ok_calls.append((tool, target))
        if r.satisfied_by.get(target) == tool:
            self.completed.add(target)

        if tool == r.gate_tool and target in r.gate_states:
            gate = (envelope.get("results") or {}).get("gate_status")
            if gate in r.safe_failure_gates:
                self.safe_failure = True
                self.log.append("SAFE_FAILURE", tool=tool.value, state=target.value, gate_status=gate,
                                forced_action=AllowedAction.ANALYSIS_UNSAFE.value)
                self._transition(State.GENERATE_EXPLANATION, f"safe_failure:{gate}")
                return

        if not backward and target in r.auto_advance and target in self.completed:
            self._transition(r.order[self._index[target] + 1], "auto_advance")

    # ---- geçersiz çağrı kaydı -------------------------------------------------------
    def reject(self, tool: ToolName | str | None, code: str, message: str) -> None:
        self.n_invalid_calls += 1
        name = tool.value if isinstance(tool, ToolName) else tool
        self.log.append("INVALID_TOOL_CALL", tool=name, state=self.state.value, code=code, message=message)
        if code == "STATE_ALREADY_PASSED":
            self._order_violation(name, enforced=True)

    def _order_violation(self, tool: ToolName | str | None, *, enforced: bool) -> None:
        self.n_order_violations += 1
        name = tool.value if isinstance(tool, ToolName) else tool
        self.log.append("ORDER_VIOLATION", tool=name, state=self.state.value, enforced=enforced,
                        mode=self.order_mode)

    # ---- açıklama / insan incelemesi / kapanış (orkestratör tarafı) -----------------
    def request_explanation(self) -> Decision:
        """Model açıklama yazmak istiyor. Saf karar: zorunlu MANUEL durumlar tamam mı, harness'in
        çalıştıracağı adımlar (auto_before) neler? Geçiş için `begin_explanation()` çağrılır."""
        if self.state == State.GENERATE_EXPLANATION:
            return Decision(True, target=State.GENERATE_EXPLANATION)
        if self.state in self.routing.post_analysis:
            return Decision(False, code="EXPLANATION_NOT_ALLOWED", message=f"şimdiki durum {self.state.value}")
        if not self.enforce:
            return Decision(True, target=State.GENERATE_EXPLANATION)
        pending = self.pending_mandatory()
        manual = [s for s in pending if s not in self.routing.auto_states]
        auto = [s for s in pending if s in self.routing.auto_states]
        if manual:
            msg = "açıklamadan önce zorunlu durum(lar) tamamlanmalı: " + ", ".join(s.value for s in manual)
            self.reject(None, "MANDATORY_STATE_NOT_REACHED", msg)
            return Decision(False, code="MANDATORY_STATE_NOT_REACHED", message=msg)
        if auto and not self.has_evidence_source():
            msg = "açıklamadan önce en az bir analiz aracı başarıyla çağrılmalı (NO_EVIDENCE_SOURCE)"
            self.reject(None, "PRECONDITION_FAILED", msg)
            return Decision(False, code="PRECONDITION_FAILED", message=msg)
        return Decision(True, target=State.GENERATE_EXPLANATION, auto_before=tuple(auto))

    def begin_explanation(self) -> None:
        """Zorunlu adımlar (auto olanlar dahil) bittikten sonra GENERATE_EXPLANATION'a geç."""
        d = self.request_explanation()
        if not d.allowed:
            raise HarnessRuleViolation(d.code or "EXPLANATION_NOT_ALLOWED", d.message or "")
        if d.auto_before:
            raise HarnessRuleViolation("AUTO_STEP_PENDING",
                                       "önce harness adımları çalıştırılmalı: " + ", ".join(s.value for s in d.auto_before))
        if self.state != State.GENERATE_EXPLANATION:
            self._transition(State.GENERATE_EXPLANATION, "explanation_requested")

    def complete_explanation(self, action: AllowedAction, text: str) -> None:
        if self.state != State.GENERATE_EXPLANATION:
            self._violation("EXPLANATION_NOT_ALLOWED", f"şimdiki durum {self.state.value}")
        try:
            action = AllowedAction(action)
        except ValueError:
            self._violation("ACTION_NOT_IN_ENUM", f"izinli eylem seti dışında: {action!r}")
        if self.safe_failure and action != AllowedAction.ANALYSIS_UNSAFE:
            self._violation("ACTION_NOT_ALLOWED_AFTER_SAFE_FAILURE",
                            f"güvenli hata yolunda eylem ANALYSIS_UNSAFE olmalı, {action.value} verildi")
        self.action, self.explanation = action, text
        self.log.append("EXPLANATION_COMPLETE", action=action.value, safe_failure=self.safe_failure)
        self._transition(State.HUMAN_REVIEW, "explanation_complete")
        self.log.append("HUMAN_REVIEW_PENDING", review_status=self.review_status.value)

    def record_human_review(self, decision: ReviewStatus, reviewer: str, reason: str) -> None:
        """Yalnızca AÇIK, isimli bir insan kararı. Hiçbir otomatik yol APPROVED üretmez."""
        if self.state != State.HUMAN_REVIEW:
            self._violation("REVIEW_NOT_ALLOWED", f"şimdiki durum {self.state.value}")
        if decision not in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
            self._violation("REVIEW_DECISION_INVALID", "karar APPROVED veya REJECTED olmalı")
        if not reviewer.strip() or not reason.strip():
            self._violation("REVIEW_INCOMPLETE", "inceleyen kişi ve gerekçe zorunlu")
        self.review_status = decision
        self.log.append("HUMAN_REVIEW", decision=decision.value, reviewer=reviewer.strip(), reason=reason.strip())

    def close(self) -> None:
        if self.state != State.HUMAN_REVIEW:
            self._violation("CLOSE_NOT_ALLOWED", f"şimdiki durum {self.state.value}")
        self._transition(State.LOG_AND_CLOSE, "close")
        self.log.append("SESSION_CLOSED", review_status=self.review_status.value,
                        action=self.action.value if self.action else None, n_invalid_calls=self.n_invalid_calls,
                        n_order_violations=self.n_order_violations)

    # ---- salt-okunur görünüm (LLM'e AÇILMAZ; harness-içi) ------------------------------
    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "completed": [s.value for s in self.routing.order if s in self.completed],
            "pending_mandatory": [s.value for s in self.pending_mandatory()],
            "callable_tools": [t.value for t in self.callable_tools()],
            "safe_failure": self.safe_failure,
            "review_status": self.review_status.value,
            "n_invalid_calls": self.n_invalid_calls,
            "n_order_violations": self.n_order_violations,
            "order_mode": self.order_mode,
        }

    # ---- iç yardımcılar -------------------------------------------------------------------
    def _transition(self, to: State, reason: str) -> None:
        self.log.append("STATE_TRANSITION", **{"from": self.state.value, "to": to.value, "reason": reason})
        self.state = to

    def _violation(self, code: str, message: str) -> None:
        self.reject(None, code, message)
        raise HarnessRuleViolation(code, message)
