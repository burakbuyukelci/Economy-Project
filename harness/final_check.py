"""Nihai çıktı denetimi: sayı doğrulama + eylem koruması + politika etiketi TEK raporda (madde: modül entegrasyonu).

Saf fonksiyonlar (oturumu yalnızca OKUR; durum değiştirmez). Bağlama ve yeniden deneme döngüsü `HarnessSession.submit_final`'dadır.

İki ayrı kavram:
  ÖLÇÜM    her profilde (A–E) aynı değerlendirici çalışır; rapor üretilir (halüsinasyon, ihlal, politika uyumu).
  ZORLAMA  yalnızca profilde `enforce_final_check` açıksa (D/E): ihlal -> yeniden deneme -> güvenli geri çekilme,
           ve eylem etiketi politika etiketine EŞİT olmak zorundadır (`required_action`).

İhlal kodları (tek liste, kaynak alanıyla):
  numbers  NUMBER_HALLUCINATION            araç çıktısında / izin listelerinde olmayan sayı (hocanın metriği)
  action   NO_ACTION | MULTIPLE_ACTIONS | ACTION_NOT_IN_ENUM | ACTION_MISMATCH_REQUIRED   (action_guard)
  advice   ADVICE_LANGUAGE                 al/sat, hedef fiyat, kesinlik dili            (action_guard)
Notlar (ihlal DEĞİL): NUMBER_UNEVIDENCED (araçta var, kilitli kanıtta yok; yumuşak uyarı), QUOTED_REFUTATION.
`ALLOWLISTED_POLICY`: modele gösterilen politika bloğundaki sayılar (rapor ayrıca sayar, ihlal değildir).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harness.action_guard import ActionGuardReport, check_final_output
from harness.label_policy import CANDIDATE_LABELS, PolicyDecision, decide_session
from harness.number_verifier import VerificationReport, verify_session
from schemas.enums import AllowedAction

ADVICE_CODES = frozenset({"ADVICE_LANGUAGE"})


@dataclass(frozen=True)
class FinalViolation:
    code: str
    source: str                      # "numbers" | "action" | "advice"
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "source": self.source, "message": self.message, "detail": dict(self.detail)}


@dataclass
class FinalReport:
    text: str
    enforced: bool
    required_action: AllowedAction | None      # yalnızca zorlamada (D/E) politika etiketi
    policy: PolicyDecision | None
    numbers: VerificationReport
    guard: ActionGuardReport
    violations: list[FinalViolation] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def action(self) -> AllowedAction | None:
        return self.guard.action

    @property
    def policy_label(self) -> AllowedAction | None:
        return self.policy.label if self.policy is not None else None

    @property
    def policy_match(self) -> bool | None:
        """Modelin etiketi politika etiketine eşit mi? Etiket çözümlenemediyse ya da politika yoksa None."""
        if self.action is None or self.policy is None:
            return None
        return self.action == self.policy.label

    @property
    def codes(self) -> list[str]:
        return [v.code for v in self.violations]

    def to_dict(self) -> dict[str, Any]:
        n = self.numbers
        return {
            "ok": self.ok, "enforced": self.enforced,
            "required_action": self.required_action.value if self.required_action else None,
            "action": self.action.value if self.action else None,
            "policy_label": self.policy_label.value if self.policy_label else None,
            "policy_rule_id": self.policy.rule_id if self.policy else None,
            "policy_match": self.policy_match,
            "violations": [v.to_dict() for v in self.violations], "notes": [dict(x) for x in self.notes],
            "n_number_claims": n.n_claims, "n_hallucinated": n.n_hallucinated, "n_unevidenced": n.n_unevidenced,
            "n_allowlisted_policy": n.n_allowlisted_policy,
            "numerical_hallucination_rate": n.numerical_hallucination_rate,
        }


# =============================== politika bloğu (modele gösterilen) ===============================
def render_policy_block(decision: PolicyDecision) -> str:
    """GENERATE_EXPLANATION'da D/E modeline verilen blok: izinli etiket + kural + kapı + gerekçe kodları.

    Yalnızca politika kararının kendisi vardır; araç değerleri (isabet oranı vb.) buradan GELMEZ. Bloktaki sayılar
    (gerekçe metinlerindeki eşikler: `MIN_EVENTS (20)`, `< 4` çeyrek) sayı doğrulayıcıda ALLOWLISTED_POLICY olur."""
    lines = [
        "POLİTİKA KARARI (harness hesapladı; eylem etiketi bu olmalıdır):",
        f"EYLEM: {decision.label.value}",
        f"Kural: {decision.rule_id}",
        f"Kalite kapısı: {decision.gate_status or 'yok'}",
    ]
    if decision.reasons:
        lines.append("Gerekçeler:")
        lines.extend(f"- {r.code}: {r.message}" for r in decision.reasons)
    return "\n".join(lines)


# =============================== denetim ===============================
def check_final(session: Any, text: str, *, policy: PolicyDecision | None = None, enforce: bool | None = None) -> FinalReport:
    """Nihai metni denetler. enforce=None => profilin `enforce_final_check` bayrağı.

    Politika her profilde hesaplanır (ölçüm); `required_action` yalnızca zorlamada verilir."""
    enforced = session.profile.enforce_final_check if enforce is None else enforce
    decision = policy if policy is not None else decide_session(session)
    required = decision.label if enforced else None
    numbers = verify_session(session, text)
    guard = check_final_output(text, required_action=required)

    violations: list[FinalViolation] = []
    for v in guard.violations:
        violations.append(FinalViolation(v.code, "advice" if v.code in ADVICE_CODES else "action", v.message,
                                         {k: val for k, val in v.to_dict().items() if k not in ("code", "message") and val is not None}))
    for r in numbers.claims:
        if r.verdict == "HALLUCINATION":
            detail: dict[str, Any] = {"raw": r.claim.raw, "kind": r.claim.kind, "start": r.claim.start, "end": r.claim.end}
            hint = r.derivation_hint
            if hint:
                detail["derivation_hint"] = hint
            violations.append(FinalViolation("NUMBER_HALLUCINATION", "numbers",
                                             f"{r.claim.raw!r} araç çıktısında yok", detail))

    notes: list[dict[str, Any]] = [{"code": n.code, "message": n.message, "phrase": n.phrase} for n in guard.notes]
    notes.extend({"code": "NUMBER_UNEVIDENCED", "message": "araç çıktısında var, kilitli kanıt kümesinde yok", "raw": r.claim.raw}
                 for r in numbers.claims if r.verdict == "UNEVIDENCED")
    return FinalReport(text, enforced, required, decision, numbers, guard, violations, notes)


# =============================== geri besleme ve güvenli geri çekilme ===============================
def build_feedback(report: FinalReport, *, attempt: int, max_attempts: int) -> str:
    """Başarısız denemeden sonra MODELE verilen Türkçe hata mesajı (deterministik)."""
    lines = [f"Nihai cevabınız kurallara uymadı (deneme {attempt}/{max_attempts}). Aşağıdakileri düzeltip cevabın TAMAMINI yeniden yazın:"]
    for v in report.violations:
        if v.code == "NUMBER_HALLUCINATION":
            line = f"- Uydurma sayı: {v.detail['raw']} araç çıktısında yok; yalnızca araç çıktısındaki sayıları aynen kullanın, kendiniz sayı hesaplamayın."
            if v.detail.get("derivation_hint"):
                line += f" (kendi hesabınız gibi görünüyor: {v.detail['derivation_hint']})"
        elif v.code == "ADVICE_LANGUAGE":
            line = (f"- Yatırım tavsiyesi/hedef fiyat/kesinlik dili: {v.detail.get('phrase')!r} "
                    f"(cümle: {v.detail.get('sentence')!r}). Tavsiye vermeyin; yalnızca tarihsel gözlemi anlatın.")
        else:
            line = f"- Eylem etiketi: {v.message}"
        lines.append(line)
    final_label = report.required_action
    if final_label is not None:
        lines.append(f"Son satır tam olarak şu olmalı: EYLEM: {final_label.value}")
    else:
        lines.append("Son satır tam olarak izinli bir etiket olmalı: EYLEM: <ETİKET>")
    return "\n".join(lines)


_FALLBACK_BODY = ("Bu soru için kurallara uygun bir açıklama üretilemedi: model çıktısı sayı doğrulama ve eylem koruması "
                  "denetimlerinden geçmedi ve atıldı. Araç çıktıları ve denetim kayıtları saklanmıştır; insan incelemesi gerekir.")
_FALLBACK_NOTE = {
    AllowedAction.ANALYSIS_UNSAFE: "Veri kalitesi kapısı analizin güvenli olmadığını gösteriyor; sonuç üretilmedi.",
    AllowedAction.INVESTIGATE: "Kanıt yetersiz ya da doğrulanamadı; daha fazla inceleme gerekir.",
}


def fallback_text(action: AllowedAction | str) -> str:
    """Güvenli geri çekilme metni: sayı içermez, tavsiye dili içermez, kendisi `check_final_output`'tan geçer (testli)."""
    action = AllowedAction(action)
    parts = [_FALLBACK_BODY]
    if action in _FALLBACK_NOTE:
        parts.append(_FALLBACK_NOTE[action])
    else:
        parts.append(f"Politika kararı {action.value} olarak kaydedildi.")
    if action in CANDIDATE_LABELS:
        parts.append("Tarihsel gözlem: örnek küçük, belirsizlik var.")
    parts.append(f"EYLEM: {action.value}")
    return "\n".join(parts)
