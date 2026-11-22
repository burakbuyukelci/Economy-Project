"""Öğretmen betik: bir soru için araç çağrıları planı + GERÇEK `HarnessSession` (D profili, gerçek araçlar) içinde tam oturum.

`ScriptedBackend` ile çalışır (model YOK): araç çağrıları `plan_calls`, ara metin `HAZIR`, nihai metin `composer`. Oturum, çıkarımdaki protokolle BİREBİR aynı koşar
(agent_loop.run_session), bu yüzden kayıt biçimi çıkarımla uyumludur. Hata-kurtarma yörüngelerinde hatalı asistan turu kayıptan MASKELENİR.
Yeni araç eklemek: `plan_calls`'a tip için çağrı listesi, `composer._pick`'e kanıt seçimi.
"""
from __future__ import annotations

import hashlib
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterator

from harness import settings
from harness.agent_loop import RunResult, run_session
from harness.llm_backend import ModelReply, ScriptedBackend, ToolCall
from harness.session import HarnessSession
from harness.text_protocol import TOOL_CALL_OPEN, parse_reply
from schemas.enums import AllowedAction as A, ToolName as T
from training import spec
from training.composer import compose_final, fundamental_notes
from training.questions import Question

Call = tuple[str, dict[str, Any]]
RECOVERY_KINDS = ("as_of", "malformed", "early", "final_violation")


def iso(d: date) -> str:
    return d.isoformat()


@contextmanager
def real_tools() -> Iterator[None]:
    """Gerçek araçlar + modele açık küme = yalnızca gerçek araçlar. Çıkışta ayarlar geri alınır."""
    old_over, old_exposed = dict(settings.TOOL_BACKEND_OVERRIDES), settings.EXPOSED_TOOLS
    try:
        for t in (*spec.REAL_TOOLS, T.CHECK_DATA_QUALITY):
            settings.TOOL_BACKEND_OVERRIDES[t] = "real"
        settings.EXPOSED_TOOLS = spec.REAL_TOOLS
        yield
    finally:
        settings.TOOL_BACKEND_OVERRIDES.clear()
        settings.TOOL_BACKEND_OVERRIDES.update(old_over)
        settings.EXPOSED_TOOLS = old_exposed


# =============================== araç çağrısı planı ===============================
def _indicators(q: Question, names: list[str], last_n: int = 0) -> Call:
    params: dict[str, Any] = {"as_of": iso(q.as_of), "ticker": q.plan["ticker"], "indicators": names, "end": iso(q.as_of)}
    if last_n:
        params["last_n_rows"] = last_n
    return ("calculate_indicators", params)


def _reversal_calls(q: Question, family: str, conditions: list[dict[str, Any]], with_backtest: bool) -> list[Call]:
    year = q.as_of.year
    calls: list[Call] = [("detect_reversal_events", {
        "as_of": iso(q.as_of), "ticker": q.plan["ticker"], "event_family": family, "split_date": iso(date(year, 1, 1)),
        "n_tests_declared": 1 + len(conditions), **({"condition_sets": conditions} if conditions else {})})]
    if with_backtest:
        calls.append(("run_backtest", {
            "as_of": iso(q.as_of), "universe": [q.plan["ticker"]], "start": "2024-01-01", "end": iso(q.as_of),
            "strategy": {"variant": "B", "signal_type": "REVERSAL", "holding_days": 5, "train_end": iso(date(year - 1, 12, 31)),
                         "signal_params": {"event_family": family}}}))
    return calls


def plan_calls(q: Question) -> list[Call]:
    p, t, a = q.plan, q.plan.get("ticker"), iso(q.as_of)
    if q.type == "weekday":
        return [("test_weekday_pattern", {
            "as_of": a, "ticker": t, "pattern": [{"weekday": d, "direction": di, "role": r} for d, di, r in p["pattern"]],
            "in_sample_start": iso(p["is_start"]), "in_sample_end": iso(p["is_end"]),
            "out_of_sample_start": iso(p["oos_start"]), "out_of_sample_end": iso(p["oos_end"]), "n_tests_declared": 1})]
    if q.type == "reversal":
        return _reversal_calls(q, p["family"], p["conditions"], p["with_backtest"])
    if q.type == "catch_up":
        year = q.as_of.year
        members = ["BIMAS", "MAVI", "MGROS"]
        return [("rank_sector_relative_strength", {"as_of": a, "sector": "retail", "horizon": p["horizon"], "split_date": iso(date(year, 1, 1))}),
                ("run_backtest", {"as_of": a, "universe": members, "start": "2024-01-01", "end": a,
                                  "strategy": {"variant": "B", "signal_type": "CATCH_UP", "holding_days": 5,
                                               "train_end": iso(date(year - 1, 12, 31)), "signal_params": {}}})]
    if q.type == "indicators":
        return [_indicators(q, p["indicators"], p["last_n_rows"])]
    if q.type == "support_resistance":
        return [("find_support_resistance", {"as_of": a, "ticker": t, "start": iso(q.as_of - timedelta(days=365)), "end": a})]
    if q.type == "history":
        calls: list[Call] = [("get_stock_history", {"as_of": a, "ticker": t, "start": iso(p["start"]), "end": a})]
        if p["relative"]:
            calls.append(("get_index_history", {"as_of": a, "index": "XU100", "start": iso(p["start"]), "end": a}))
        return calls + [_indicators(q, ["RSI"])]
    if q.type == "advice":
        if p["variant"] == "reversal":
            return _reversal_calls(q, "BB_LOWER_TOUCH", [], True)
        return [_indicators(q, ["RSI", "BOLLINGER"])]
    if q.type == "fundamental":
        # YoY için 2024 verisi yok (TMS 29 öncesi alınmaz): soruda temel belirtilmemişse QOQ. Banka için iyileşme metriği NET_PROFIT (şema varsayılanı EBITDA_MARGIN bankada geçersiz).
        return [("get_fundamental_metrics", {"as_of": a, "ticker": t}),
                ("calculate_fundamental_change", {"as_of": a, "ticker": t, "improvement_metric": p["metric"], "improvement_basis": p["basis"] or "QOQ"})]
    if q.type == "unsupported":
        return [_indicators(q, ["RSI"])]
    if q.type == "stale":
        return [_indicators(q, p["indicators"])]
    raise ValueError(f"bilinmeyen soru tipi: {q.type}")


# =============================== üretim ===============================
@dataclass
class Generated:
    question: Question
    result: RunResult
    session: HarnessSession
    recovery: str | None
    bad_turns: tuple[int, ...]            # kayıptan maskelenecek asistan turları (0 tabanlı, asistan mesajı sırası)
    problems: list[str] = field(default_factory=list)


def _rng(q: Question, salt: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{spec.SEED}:{salt}:{q.id}".encode()).hexdigest()[:16], 16))


def recovery_kind(q: Question) -> str | None:
    """Belirlenimli: soruların ~%10'una kurtarma yörüngesi atanır (kimlikten türer, bölme içinde sıradan bağımsız)."""
    rng = _rng(q, "recovery")
    if rng.random() >= spec.RECOVERY_SHARE:
        return None
    kinds = ("final_violation",) if q.type == "stale" else RECOVERY_KINDS
    return rng.choice(kinds)


def _bad_final(good: str, rng: random.Random) -> str:
    """Kurallara uymayan nihai metin (maskelenir): uydurma sayı ya da tavsiye dili eklenir."""
    tail = rng.choice([" Bence yaklaşık %17,3 daha yükselebilir.", " Hedef fiyat 350 TL; hisseyi alın.", " Bu hisse kesin yükselir, alın."])
    head, sep, label = good.rpartition("\nEYLEM:")
    return head + tail + sep + label


def build_steps(q: Question, session: HarnessSession, recovery: str | None = None) -> tuple[list[Any], list[int]]:
    """Öğretmen betiği: ScriptedBackend adımları ve kayıptan MASKELENECEK asistan turlarının sırası. `session` nihai metin için (politika + kilitli kanıt) gerekir."""
    calls = plan_calls(q)
    rng = _rng(q, "compose")

    def final(msgs: list[dict[str, Any]], tools: Any) -> str:
        pol = session.policy
        assert pol is not None
        reasons = [(r.code, r.message) for r in pol.reasons]
        rule = pol.rule_id                      # G5_COMBINE'da politika kimliği zaten belirleyici senaryonunkidir
        snap = session.evidence_snapshot()
        evidence = snap["committed_evidence_set"] if snap else []
        warns = [str(w) for r in session.store.records if str(r.envelope["tool"]).startswith(("calculate_fundamental", "get_fundamental"))
                 for w in (r.envelope.get("warnings") or [])]
        return compose_final(qtype=q.type, plan=q.plan, ticker=q.plan.get("ticker") or "", label=pol.label, rule_id=rule, reasons=reasons,
                             evidence=evidence, rng=rng, claim=q.plan.get("claim"), notes=fundamental_notes(warns))

    steps: list[Any] = []
    bad: list[int] = []
    first_name, first_params = calls[0]
    if recovery == "as_of":
        wrong = {**first_params, "as_of": iso(q.as_of - timedelta(days=1))}
        bad.append(len(steps))
        steps.append(ModelReply(tool_calls=(ToolCall(first_name, wrong),)))
    elif recovery == "malformed":
        text = f'{TOOL_CALL_OPEN}{{"name": "{first_name}", "arguments": {{"as_of": "{iso(q.as_of)}"'
        bad.append(len(steps))
        steps.append(ModelReply(text=text, format_error=parse_reply(text).error))
    elif recovery == "early":
        bad.append(len(steps))
        steps.append("HAZIR")
    for name, params in calls:
        steps.append(ModelReply(tool_calls=(ToolCall(name, params),)))
    steps.append("HAZIR")
    if recovery == "final_violation":
        bad.append(len(steps))
        steps.append(lambda msgs, tools: _bad_final(final(msgs, tools), _rng(q, "badfinal")))
    steps.append(final)
    return steps, bad


def generate(q: Question, *, recovery: str | None = None) -> Generated:
    """Soru -> gerçek oturum (yalnızca gerçek araçlar). Çağıran `real_tools()` bağlamında olmalıdır."""
    session = HarnessSession.from_question(q.text, profile="D")
    steps, bad = build_steps(q, session, recovery)
    result = run_session(q.text, ScriptedBackend(steps), session=session)
    return Generated(q, result, session, recovery, tuple(bad))
