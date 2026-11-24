"""Harness oturumu: soru -> as_of kilidi -> durum makinesi -> (otomatik kapılar) -> araç -> sözleşme doğrulaması.

MCP SDK'sından BAĞIMSIZDIR; MCP sunucusu (mcp_server.py) bu sınıfın üstünde ince bir adaptördür.

Bir MODEL araç çağrısının geçtiği kapılar (sırayla; ilk başarısız olan INVALID_TOOL_CALL olarak loglanır):
  1. UNKNOWN_TOOL / TOOL_NOT_EXPOSED / HARNESS_ONLY_TOOL   araç adı ve profile göre görünürlük
  2. durum makinesi                                        NO_TOOLS_IN_STATE / STATE_ALREADY_PASSED /
                                                           MANDATORY_STATE_SKIPPED / PRECONDITION_FAILED
  3. AS_OF_MISSING / AS_OF_MISMATCH                        params.as_of == oturum as_of'u (soru ön metninden)
  4. INVALID_PARAMS                                        şema (schemas.registry.validate_params)
Sonra (D/E profilinde) harness gerekli zorunlu adımları KENDİ çalıştırır (kalite kapısı, kanıt paketi aşama 1),
ardından modelin aracı çalışır; çıktı validate_envelope'tan geçer (geçmezse HARNESS_ERROR, modele iletilmez).
Kapı HARD_BLOCK/ANALYSIS_UNSAFE derse modelin aracı ÇALIŞTIRILMAZ: SAFE_FAILURE sonucu döner (§26).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from harness import settings
from harness.as_of import resolve_as_of
from harness.event_log import EventLog
from harness.evidence import EnvelopeStore, EvidenceBundle, make_analysis_id
from harness.final_check import FinalReport, build_feedback, check_final, fallback_text, render_policy_block
from harness.gate_params import GateParamsError, derive_gate_params, detect_question_tickers
from harness.label_policy import PolicyDecision, decide_session
from harness.param_fixer import drop_unknown_signal_params, fix_params, repair_tickers
from harness.profiles import StageProfile, get_profile, harness_only_tools, routing_for, visible_tools
from harness.routing import ReviewStatus, Routing, State
from harness.state_machine import Decision, HarnessRuleViolation, StateMachine
from harness.tool_runner import RealToolUnavailable, ToolRejected, run_tool
from schemas.enums import AllowedAction, ToolName as T
from schemas.registry import validate_envelope, validate_params

Runner = Callable[[T, dict[str, Any]], dict[str, Any]]
_FROM_SETTINGS: Any = object()  # "varsayılanı settings/ortam değişkeninden oku" işareti


@dataclass(frozen=True)
class ToolCallResult:
    ok: bool
    envelope: dict[str, Any] | None = None
    # {"type": "INVALID_TOOL_CALL" | "HARNESS_ERROR" | "SAFE_FAILURE", "code", "message", ...}
    error: dict[str, Any] | None = None


@dataclass(frozen=True)
class FinalResult:
    """submit_final sonucu. status: ACCEPTED (zorlama; temiz) | RETRY (ihlal; geri besleme var, metin teslim EDİLMEDİ)
    | FALLBACK (deneme hakkı bitti; güvenli metin teslim edildi) | RECORDED (zorlama yok, A–C: ham metin teslim edildi, yalnızca ölçüldü)."""
    status: str
    attempt: int
    max_attempts: int
    report: FinalReport
    text: str | None = None            # teslim edilen metin (RETRY'de None)
    action: AllowedAction | None = None
    feedback: str | None = None        # RETRY'de modele iletilecek mesaj


class HarnessSession:
    def __init__(self, as_of: date, *, as_of_source: str = "explicit", question: str = "",
                 profile: StageProfile | str | None = None, order_mode: str | None = None,
                 runner: Runner | None = None, log: EventLog | None = None, routing: Routing | None = None,
                 exposed_tools: Any = _FROM_SETTINGS) -> None:
        self.as_of = as_of
        self.as_of_source = as_of_source
        self.question = question
        self.warnings: list[str] = []  # harness düzeyi uyarılar ("KOD: açıklama"); araç zarfına GİRMEZ
        self.profile = get_profile(profile) if isinstance(profile, str) else (profile or get_profile(settings.experiment_stage()))
        self.visible_tools: list[T] = visible_tools(self.profile)
        exposed = settings.EXPOSED_TOOLS if exposed_tools is _FROM_SETTINGS else exposed_tools
        if exposed is not None:  # modele açık küme (örn. yalnızca gerçek araçlar); profilin görünürlüğünü yalnızca DARALTIR
            self.visible_tools = [t for t in self.visible_tools if t in set(exposed)]
        self._harness_only = harness_only_tools(self.profile)
        self._runner: Runner = runner or run_tool
        self.log = log if log is not None else EventLog(settings.EVENT_LOG_PATH)
        self.machine = StateMachine(self.log, routing or routing_for(self.profile),
                                    order_mode=order_mode or settings.state_order_mode(),
                                    enforce=self.profile.enforce_states)
        self.tool_envelopes: list[dict[str, Any]] = []  # modele iletilen, doğrulanmış zarflar (sıralı)
        self.store = EnvelopeStore()                    # TÜM zarflar (model + harness), kanıt kaynağı
        self.analysis_id = make_analysis_id(as_of, question)  # oturumdan SABİT; iki kanıt aşamasında değişmez
        self.bundle: EvidenceBundle | None = EvidenceBundle(self.analysis_id, self.store) if self.profile.evidence else None
        self._model_calls: list[tuple[T, dict[str, Any]]] = []  # başarıyla çalışan model çağrıları (kapı parametresi için)
        self.question_tickers: list[str] = detect_question_tickers(question) if question else []
        # nihai çıktı denetimi: politika kararı her profilde hesaplanır (ölçüm); blok yalnızca show_policy_label'da modele gösterilir
        self.policy: PolicyDecision | None = None
        self.policy_text: str = ""
        self._final_reports: list[FinalReport] = []
        self._max_final_attempts: int | None = None
        self._delivered: dict[str, Any] | None = None

        self.log.append("SESSION_START", as_of=as_of.isoformat(), as_of_source=as_of_source,
                        stage=self.profile.name, order_mode=self.machine.order_mode, analysis_id=self.analysis_id)
        if as_of_source == "default":
            msg = f"soruda analiz tarihi işareti yok; varsayılan {as_of.isoformat()} kullanıldı"
            self.warnings.append(f"AS_OF_ASSUMED: {msg}")
            self.log.append("AS_OF_ASSUMED", as_of=as_of.isoformat(), message=msg)
        self.machine.begin()
        self.log.append("UNIVERSE_SELECTED", tickers_in_question=self.question_tickers)

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
        return cls(resolved.date, as_of_source=resolved.source, question=question, **kwargs)

    # ---- LLM'in kullandığı tek giriş ----------------------------------------------------
    def call_tool(self, name: str, params: dict[str, Any]) -> ToolCallResult:
        try:
            tool = T(name)
        except ValueError:
            return self._invalid(name, "UNKNOWN_TOOL", f"tanımsız araç: {name!r}")
        if tool not in self.visible_tools:
            if tool in self._harness_only:
                return self._invalid(tool, "HARNESS_ONLY_TOOL",
                                     f"{tool.value} harness tarafından çalıştırılır; modelin çağırması gerekmez")
            return self._invalid(tool, "TOOL_NOT_EXPOSED", f"{tool.value} bu deney aşamasında ({self.profile.name}) kapalı")

        decision = self.machine.check(tool)
        if not decision.allowed:
            return self._invalid(tool, decision.code or "INVALID", decision.message or "")
        problem = self._check_as_of(params)
        if problem:
            return self._invalid(tool, *problem)
        if settings.normalize_params() and self.question_tickers:
            # hisse kodu yazım hatası ("ERGL" -> "EREGL"): şema geçer ama araç UNKNOWN_TICKER döner ve model aynı çağrıyı tekrarlar (canlı demo Soru 5'te ölçüldü)
            from harness.gate_params import load_universe

            fixed_t, notes_t = repair_tickers(params, self.question_tickers, set(load_universe()["ticker"]))
            if fixed_t is not None:
                self.log.append("PARAMS_NORMALIZED", tool=tool.value, notes=notes_t, original=params, fixed=fixed_t)
                self.warnings.append("PARAMS_NORMALIZED: " + "; ".join(notes_t))
                params = fixed_t
        try:
            validate_params(tool, params)
        except ValidationError as exc:
            fixed, notes = fix_params(tool, params, self.as_of) if settings.normalize_params() else (None, [])
            if fixed is None:
                return self._invalid(tool, "INVALID_PARAMS", _short_errors(exc))
            # biçim hatası onarıldı: çalışan çağrı düzeltilmiş çağrıdır (zarfın params'ı ve input_hash buna göre); sessiz değil
            self.log.append("PARAMS_NORMALIZED", tool=tool.value, notes=notes, original=params, fixed=fixed)
            self.warnings.append("PARAMS_NORMALIZED: " + "; ".join(notes))
            params = fixed
        if settings.normalize_params():
            dropped, notes_d = drop_unknown_signal_params(tool, params)
            if dropped is not None:
                self.log.append("PARAMS_NORMALIZED", tool=tool.value, notes=notes_d, original=params, fixed=dropped)
                self.warnings.append("PARAMS_NORMALIZED: " + "; ".join(notes_d))
                params = dropped

        # harness'in çalıştıracağı zorunlu adımlar (kalite kapısı, kanıt aşama 1) modelin çağrısından ÖNCE
        for state in decision.auto_before:
            failure = self._run_auto_state(state, pending=(tool, params))
            if failure is not None:
                return failure
            if self.machine.safe_failure:
                return self._safe_failure_result()

        envelope, failure = self._execute(tool, params)
        if failure is not None:
            return failure
        assert envelope is not None
        state_before = self.machine.state.value
        self.machine.commit(tool, envelope)
        self.store.add(envelope, actor="model")
        self.tool_envelopes.append(envelope)
        if envelope["status"] == "OK":
            self._model_calls.append((tool, params))
        self._log_call(tool, envelope, "model", state_before)
        self._after_commit()
        return ToolCallResult(ok=True, envelope=envelope)

    # ---- orkestratör tarafı (LLM'e açılmaz) -----------------------------------------------
    def request_explanation(self) -> Decision:
        """Model açıklama yazmak istiyor: zorunlu adımları (harness'inkiler dahil) tamamlar ve açıklama aşamasına geçer."""
        d = self.machine.request_explanation()
        if not d.allowed:
            return d
        for state in d.auto_before:
            failure = self._run_auto_state(state, pending=None)
            if failure is not None:
                code = (failure.error or {}).get("code", "AUTO_STEP_FAILED")
                msg = (failure.error or {}).get("message", "")
                return Decision(False, code=code, message=msg)
            if self.machine.safe_failure:
                break
        self.machine.begin_explanation()
        self._prepare_policy()
        return Decision(True, target=State.GENERATE_EXPLANATION)

    def explanation_context(self) -> str | None:
        """GENERATE_EXPLANATION'da modele verilecek politika bloğu (izinli etiket + gerekçe); yoksa (A–C, D′) None."""
        return self.policy_text or None

    def submit_final(self, text: str) -> FinalResult:
        """Modelin nihai metni. Denetim: sayı doğrulama + eylem koruması (+ D/E'de required_action = politika etiketi).

        Zorlama açıksa (D/E): ihlal -> RETRY (geri besleme), hak bitince FALLBACK (güvenli metin, etiket = politika etiketi).
        Zorlama kapalıysa (A–C): metin AYNEN teslim edilir (RECORDED); yalnızca ölçülür. İhlaller deneme ve teslim düzeyinde ayrı sayılır."""
        if self.machine.state != State.GENERATE_EXPLANATION:
            msg = f"nihai metin yalnızca açıklama aşamasında verilir; şimdiki durum {self.machine.state.value}"
            self.machine.reject(None, "EXPLANATION_NOT_ALLOWED", msg)
            raise HarnessRuleViolation("EXPLANATION_NOT_ALLOWED", msg)
        if self.policy is None:
            self._prepare_policy()
        if self._max_final_attempts is None:
            self._max_final_attempts = 1 + (settings.final_max_retries() if self.profile.enforce_final_check else 0)
        max_attempts = self._max_final_attempts
        report = check_final(self, text, policy=self.policy)
        self._final_reports.append(report)
        attempt = len(self._final_reports)
        self._log_final_check(report, attempt)

        if not self.profile.enforce_final_check:  # ÖLÇÜM: ham metin teslim edilir
            action, source = report.action, "model"
            if action is None:
                action, source = AllowedAction.INVESTIGATE, "defaulted"
                self.log.append("ACTION_DEFAULTED", action=action.value,
                                reason="nihai metinde çözümlenebilir eylem etiketi yok (yalnızca ölçüm)")
            self._deliver(text, action, report, status="RECORDED", source=source, fallback=False)
            return FinalResult("RECORDED", attempt, max_attempts, report, text, action)
        if report.ok:
            assert report.action is not None
            self._deliver(text, report.action, report, status="ACCEPTED", source="model", fallback=False)
            return FinalResult("ACCEPTED", attempt, max_attempts, report, text, report.action)
        if attempt < max_attempts:
            return FinalResult("RETRY", attempt, max_attempts, report,
                               feedback=build_feedback(report, attempt=attempt, max_attempts=max_attempts))
        return self._fallback(report, attempt, max_attempts, "deneme hakkı bitti")

    def deliver_fallback(self, reason: str) -> FinalResult:
        """Orkestratör: döngü nihai metne ulaşamadan durdu (tur sınırı, model hatası). Yalnızca zorlama açık profilde (D/E) ve
        açıklama aşamasında; güvenli metin teslim edilir (etiket = politika etiketi)."""
        if not self.profile.enforce_final_check:
            raise HarnessRuleViolation("FALLBACK_NOT_ENABLED", f"{self.profile.name} profilinde güvenli geri çekilme yok (yalnızca ölçüm)")
        if self.machine.state != State.GENERATE_EXPLANATION:
            msg = f"geri çekilme yalnızca açıklama aşamasında teslim edilir; şimdiki durum {self.machine.state.value}"
            self.machine.reject(None, "EXPLANATION_NOT_ALLOWED", msg)
            raise HarnessRuleViolation("EXPLANATION_NOT_ALLOWED", msg)
        if self.policy is None:
            self._prepare_policy()
        if self._max_final_attempts is None:
            self._max_final_attempts = 1 + settings.final_max_retries()
        return self._fallback(None, len(self._final_reports), self._max_final_attempts, reason)

    def _fallback(self, failed: FinalReport | None, attempt: int, max_attempts: int, reason: str) -> FinalResult:
        assert self.policy is not None
        action = self.policy.label            # güvenli hata yolunda politika zaten ANALYSIS_UNSAFE'tir (G1)
        fb_text = fallback_text(action)
        self.log.append("FINAL_FALLBACK", action=action.value, attempts=attempt, reason=reason)
        delivered_report = check_final(self, fb_text, policy=self.policy)
        self._deliver(fb_text, action, delivered_report, status="FALLBACK", source="fallback", fallback=True)
        return FinalResult("FALLBACK", attempt, max_attempts, failed or delivered_report, fb_text, action)

    def final_metrics(self) -> dict[str, Any]:
        """İhlaller İKİ düzeyde: deneme düzeyi (her denemedeki ihlaller) ve teslim düzeyi (teslim edilen metin)."""
        reps = self._final_reports
        by_code: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for r in reps:
            for v in r.violations:
                by_code[v.code] = by_code.get(v.code, 0) + 1
                by_source[v.source] = by_source.get(v.source, 0) + 1
        attempt_level = {
            "n_attempts_with_violation": sum(1 for r in reps if not r.ok),
            "n_violations": sum(len(r.violations) for r in reps),
            "by_code": dict(sorted(by_code.items())), "by_source": dict(sorted(by_source.items())),
            "n_hallucinated": sum(r.numbers.n_hallucinated for r in reps),
            "n_number_claims": sum(r.numbers.n_claims for r in reps),
        }
        delivered_level: dict[str, Any] = {"delivered": self._delivered is not None}
        if self._delivered is not None:
            delivered_level.update(self._delivered)
        return {"enforced": self.profile.enforce_final_check, "n_attempts": len(reps),
                "max_attempts": self._max_final_attempts, "attempt_level": attempt_level, "delivered_level": delivered_level}

    def complete_explanation(self, action: AllowedAction, text: str) -> None:
        self.machine.complete_explanation(action, text)

    def record_human_review(self, decision: ReviewStatus, reviewer: str, reason: str) -> None:
        self.machine.record_human_review(decision, reviewer, reason)

    def close(self) -> None:
        self.machine.close()

    def get_state(self) -> dict[str, Any]:
        """Salt-okunur kopya; MCP üzerinden AÇILMAZ."""
        snap = self.machine.snapshot()
        snap["callable_tools"] = self._callable_hint()
        out = {**snap, "as_of": self.as_of.isoformat(), "as_of_source": self.as_of_source,
               "warnings": list(self.warnings), "stage": self.profile.name, "analysis_id": self.analysis_id}
        if self.bundle is not None:
            ev = self.bundle.snapshot()
            out["evidence"] = {k: ev[k] for k in ("version", "locked", "lock_hash", "gate_status", "proposed_action",
                                                  "n_full", "n_committed")}
        return out

    def evidence_snapshot(self) -> dict[str, Any] | None:
        """Kanıt paketinin tam görünümü (kilitliyse sayı doğrulayıcının kullanacağı committed küme)."""
        return self.bundle.snapshot() if self.bundle is not None else None

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.log.events

    # ---- araç çalıştırma ---------------------------------------------------------------------
    def _execute(self, tool: T, params: dict[str, Any]) -> tuple[dict[str, Any] | None, ToolCallResult | None]:
        """Aracı çalıştırır ve zarfı doğrular. (zarf, None) ya da (None, hata sonucu) döndürür."""
        try:
            if tool == T.BUILD_EVIDENCE_BUNDLE:
                if self.bundle is None:
                    return None, self._harness_error(tool, "EVIDENCE_DISABLED", "bu aşamada kanıt paketi yok")
                envelope = self.bundle.build(params)  # harness tarafı uygulama (tools/ içinde yok)
            else:
                envelope = self._runner(tool, params)
            parsed = validate_envelope(envelope)
            if parsed.as_of != self.as_of:
                raise ValueError(f"zarf as_of ({parsed.as_of}) != oturum as_of ({self.as_of})")
        except ToolRejected as exc:  # gerçek araç as_of'u reddetti: modelin geçersiz çağrısı sayılır
            return None, self._invalid(tool, exc.code, exc.message)
        except RealToolUnavailable as exc:
            return None, self._harness_error(tool, "TOOL_UNAVAILABLE", str(exc))
        except (ValidationError, ValueError, KeyError) as exc:
            return None, self._harness_error(tool, "TOOL_OUTPUT_INVALID", _short_errors(exc))
        return envelope, None

    def _run_auto_state(self, state: State, pending: tuple[T, dict[str, Any]] | None) -> ToolCallResult | None:
        """Bir durumun harness adımlarını sırayla çalıştırır. Başarısızlıkta modele dönecek sonucu verir.

        Güvenli hata yoluna düşülürse None döner; çağıran `machine.safe_failure` bayrağına bakar."""
        for tool in self.machine.routing.auto_steps[state]:
            if tool == T.CHECK_DATA_QUALITY:
                calls = self._model_calls + ([pending] if pending else [])
                try:
                    params = derive_gate_params(as_of=self.as_of, calls=calls, question_tickers=self.question_tickers,
                                                records=self.store.records)
                except GateParamsError as exc:
                    return self._invalid(pending[0] if pending else "check_data_quality", exc.code, exc.message)
            else:  # kanıt paketi: oturumdaki tüm BAŞARILI zarflar kaynaktır (kapı zarfı dahil: gate_status buradan)
                params = {"as_of": self.as_of.isoformat(), "analysis_id": self.analysis_id,
                          "source_input_hashes": [r.envelope["input_hash"] for r in self.store.records
                                                  if r.tool != T.BUILD_EVIDENCE_BUNDLE and r.envelope["status"] == "OK"]}
            envelope, failure = self._execute(tool, params)
            if failure is not None:
                return failure
            assert envelope is not None
            state_before = self.machine.state.value
            self.machine.commit(tool, envelope)
            self.store.add(envelope, actor="harness")
            self._log_call(tool, envelope, "harness", state_before, step_state=state.value)
            if envelope["status"] != "OK":
                err = envelope.get("error") or {}
                return self._harness_error(tool, "AUTO_STEP_FAILED",
                                           f"{tool.value}: {err.get('code')}: {err.get('message')}")
            self._after_commit()
            if self.machine.safe_failure:
                return None
        return None

    def _after_commit(self) -> None:
        """Açıklama aşamasına ulaşıldıysa (normal ya da güvenli hata yolu) kanıt paketini KİLİTLE."""
        if self.bundle is None or self.bundle.locked or self.machine.state != State.GENERATE_EXPLANATION:
            return
        ok_hashes = [r.envelope["input_hash"] for r in self.store.records
                     if r.tool != T.BUILD_EVIDENCE_BUNDLE and r.envelope["status"] == "OK"]
        if self.bundle.version == 0 and ok_hashes:  # güvenli hata yolu: mevcut kanıtla paketi kur
            env = self.bundle.build({"as_of": self.as_of.isoformat(), "analysis_id": self.analysis_id,
                                     "source_input_hashes": ok_hashes})
            self.store.add(env, actor="harness")
            self.log.append("EVIDENCE_BUILT", stage="safe_failure", version=self.bundle.version, status=env["status"])
        gate = self._latest_gate_status()
        lock_hash = self.bundle.lock(gate)
        self.log.append("EVIDENCE_LOCKED", version=self.bundle.version, lock_hash=lock_hash, gate_status=gate,
                        analysis_id=self.analysis_id)

    def _latest_gate_status(self) -> str | None:
        gate = None
        for r in self.store.records:
            if r.tool == T.CHECK_DATA_QUALITY and r.envelope["status"] == "OK":
                gate = r.envelope["results"].get("gate_status")
        return gate

    def _log_call(self, tool: T, envelope: dict[str, Any], actor: str, state_before: str, **extra: Any) -> None:
        self.log.append("TOOL_CALL", tool=tool.value, actor=actor, state_before=state_before,
                        state_after=self.machine.state.value, status=envelope["status"],
                        input_hash=envelope["input_hash"], data_version=envelope["data_version"], **extra)
        if tool == T.BUILD_EVIDENCE_BUNDLE and envelope["status"] == "OK" and self.bundle is not None:
            self.log.append("EVIDENCE_BUILT", stage=extra.get("step_state", "model"), version=self.bundle.version,
                            n_full=envelope["n_events"])

    # ---- nihai çıktı yardımcıları ------------------------------------------------------------
    def _prepare_policy(self) -> None:
        self.policy = decide_session(self)
        self.policy_text = render_policy_block(self.policy) if self.profile.show_policy_label else ""

    def _log_final_check(self, report: FinalReport, attempt: int) -> None:
        n = report.numbers
        self.log.append("FINAL_CHECK", attempt=attempt, ok=report.ok, enforced=report.enforced, codes=report.codes,
                        n_violations=len(report.violations), n_number_claims=n.n_claims, n_hallucinated=n.n_hallucinated,
                        n_allowlisted_policy=n.n_allowlisted_policy, n_unevidenced=n.n_unevidenced,
                        action=report.action.value if report.action else None,
                        policy_label=report.policy_label.value if report.policy_label else None,
                        policy_match=report.policy_match)
        for v in report.violations:
            self.log.append("RULE_VIOLATION", level="attempt", attempt=attempt, code=v.code, source=v.source,
                            message=v.message, phrase=v.detail.get("phrase"), raw=v.detail.get("raw"))

    def _deliver(self, text: str, action: AllowedAction, report: FinalReport, *, status: str, source: str,
                 fallback: bool) -> None:
        n = report.numbers
        by_code: dict[str, int] = {}
        by_source: dict[str, int] = {}
        for v in report.violations:
            by_code[v.code] = by_code.get(v.code, 0) + 1
            by_source[v.source] = by_source.get(v.source, 0) + 1
        self._delivered = {
            "status": status, "fallback": fallback, "action": action.value, "action_source": source,
            "n_violations": len(report.violations), "by_code": dict(sorted(by_code.items())),
            "by_source": dict(sorted(by_source.items())),
            "policy_label": report.policy_label.value if report.policy_label else None, "policy_match": report.policy_match,
            "n_number_claims": n.n_claims, "n_hallucinated": n.n_hallucinated, "n_unevidenced": n.n_unevidenced,
            "n_allowlisted_policy": n.n_allowlisted_policy, "numerical_hallucination_rate": n.numerical_hallucination_rate,
        }
        if not fallback:
            for v in report.violations:  # teslim düzeyi ihlal kaydı (A–C: ham çıktının ihlalleri)
                self.log.append("RULE_VIOLATION", level="delivered", code=v.code, source=v.source, message=v.message)
        self.complete_explanation(action, text)
        self.log.append("FINAL_DELIVERED", status=status, fallback=fallback, action=action.value,
                        metrics=self.final_metrics())

    # ---- iç yardımcılar ------------------------------------------------------------------
    def _callable_hint(self) -> list[str]:
        return [t.value for t in self.machine.callable_tools() if t in self.visible_tools]

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

    def _invalid(self, tool: T | str, code: str, message: str) -> ToolCallResult:
        self.machine.reject(tool, code, message)
        return ToolCallResult(ok=False, error={
            "type": "INVALID_TOOL_CALL", "code": code, "message": message,
            "state": self.machine.state.value, "allowed_tools": self._callable_hint(),
        })

    def _harness_error(self, tool: T, code: str, message: str) -> ToolCallResult:
        self.log.append("HARNESS_ERROR", tool=tool.value, code=code, message=message)
        return ToolCallResult(ok=False, error={"type": "HARNESS_ERROR", "code": code, "message": message})

    def malformed_call(self, message: str) -> ToolCallResult:
        """Metin protokolünde bozuk araç çağrısı biçimi: geçersiz çağrı olarak sayılır ve loglanır, durum ilerlemez."""
        return self._invalid("malformed_tool_call", "MALFORMED_TOOL_CALL", message)

    def _safe_failure_result(self) -> ToolCallResult:
        ev = self.log.of_kind("SAFE_FAILURE")[-1]
        gate = ev["gate_status"]
        return ToolCallResult(ok=False, error={
            "type": "SAFE_FAILURE", "code": gate, "gate_status": gate,
            "message": (f"veri kalitesi kapısı {gate}: analiz güvenli değil, araç çağrısı yapılmadı. "
                        "Açıklamayı yazın; eylem yalnızca ANALYSIS_UNSAFE olabilir."),
            "required_action": AllowedAction.ANALYSIS_UNSAFE.value,
        })


def _short_errors(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for e in exc.errors()[:5]:
            msg = f"{'.'.join(str(p) for p in e['loc']) or '<kök>'}: {e['msg']}"
            if e["type"] == "string_pattern_mismatch" and (e.get("ctx") or {}).get("pattern") == r"^\d{4}Q[1-4]$":
                msg += " (biçim YYYYQn, örn. 2026Q3; en son dönem için bu alanı hiç yazmayın)"   # modelin tekrar döngüsünü kırmak için ipucu
            parts.append(msg)
        return "; ".join(parts)
    return str(exc)
