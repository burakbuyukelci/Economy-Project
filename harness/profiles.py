"""Deney aşaması profilleri (proje dokümanı §30, hoca_qa.md Soru 5): A–E, VERİ olarak.

  A Raw LLM            araç yok
  B LLM + Tools        araçlar açık; durum makinesi/zorunlu adım/kapı YOK (yalnızca as_of ve şema doğrulaması)
  C Tools + Stateful   araçlar + durum sırası ve zorunlu adımlar (kalite kontrolü, backtest) — çağıran MODEL;
                       kanıt paketi ve kalite KAPISI (güvenli hata yolu) yok
  D C + Evidence/Gate  kalite kapısı ve kanıt paketi HARNESS tarafından çalıştırılır (otomatik kapılar)
  E D + Memory/Review  D + insan incelemesi/hafıza (deney iskeleti madde 7'de bağlanacak)
  D′ (EXTRA_PROFILES)  D, ama politika etiketi/gerekçesi modele GÖSTERİLMEZ (yalnızca denetlenir + yeniden deneme); A–E'ye girmez

Nihai çıktı ÖLÇÜMÜ (sayı + eylem + politika karşılaştırması) her profilde yapılır ve raporlanır; ZORLAMA (yeniden deneme,
güvenli geri çekilme, required_action) yalnızca `enforce_final_check` açıksa. Etiket/gerekçenin modele verilmesi `show_policy_label`.

Aşama `settings.EXPERIMENT_STAGE` ile seçilir. Bu dosya yalnızca bayrak tablosu ve bayraklardan
Routing/araç görünürlüğü türetir; kural mantığı state_machine.py / session.py içindedir.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from harness.routing import DEFAULT_ROUTING, AUTO_STEPS, STATE_TOOLS, Routing, State as S
from schemas.enums import ToolName as T


@dataclass(frozen=True)
class StageProfile:
    name: str
    tools_enabled: bool   # MCP araçları modele açık mı
    enforce_states: bool  # durum sırası + zorunlu adımlar
    auto_gates: bool      # CHECK_DATA_QUALITY / BUILD_EVIDENCE / RISK_GATE'i harness çalıştırır
    evidence: bool        # kanıt paketi + kalite kapısı (güvenli hata yolu) var mı
    human_review: bool    # insan incelemesi/hafıza (experiments iskeletinde kullanılır)
    enforce_final_check: bool = False  # nihai çıktı ihlalinde yeniden deneme + güvenli geri çekilme + politika etiketi zorunlu
    show_policy_label: bool = False    # GENERATE_EXPLANATION'da izinli etiket + gerekçe modele verilir

    def __post_init__(self) -> None:
        if self.enforce_states and not self.tools_enabled:
            raise ValueError("enforce_states için tools_enabled gerekir")
        if self.auto_gates and not (self.enforce_states and self.evidence):
            raise ValueError("auto_gates için enforce_states ve evidence gerekir")
        if self.evidence and not self.enforce_states:
            raise ValueError("evidence için enforce_states gerekir")
        if (self.enforce_final_check or self.show_policy_label) and not self.evidence:
            raise ValueError("enforce_final_check/show_policy_label için evidence gerekir (politika etiketi kapı + kanıttan gelir)")


PROFILES: dict[str, StageProfile] = {
    "A": StageProfile("A", tools_enabled=False, enforce_states=False, auto_gates=False, evidence=False, human_review=False),
    "B": StageProfile("B", tools_enabled=True, enforce_states=False, auto_gates=False, evidence=False, human_review=False),
    "C": StageProfile("C", tools_enabled=True, enforce_states=True, auto_gates=False, evidence=False, human_review=False),
    "D": StageProfile("D", tools_enabled=True, enforce_states=True, auto_gates=True, evidence=True, human_review=False,
                      enforce_final_check=True, show_policy_label=True),
    "E": StageProfile("E", tools_enabled=True, enforce_states=True, auto_gates=True, evidence=True, human_review=True,
                      enforce_final_check=True, show_policy_label=True),
}
# A–E karşılaştırmasının dışındaki ek deney profilleri (deney şimdilik KOŞULMAZ; bayrak hazır).
EXTRA_PROFILES: dict[str, StageProfile] = {
    "D'": replace(PROFILES["D"], name="D'", show_policy_label=False),
}


def get_profile(name: str) -> StageProfile:
    key = name.upper()
    if key in PROFILES:
        return PROFILES[key]
    if key in EXTRA_PROFILES:
        return EXTRA_PROFILES[key]
    raise ValueError(f"bilinmeyen deney aşaması {name!r}; geçerli: {', '.join([*PROFILES, *EXTRA_PROFILES])}")


def routing_for(profile: StageProfile) -> Routing:
    """Profil bayraklarından yönlendirme tablosu türetir."""
    routing = DEFAULT_ROUTING
    if not profile.evidence:
        # Kanıt/kapı yok: BUILD_EVIDENCE ve RISK_GATE araçsız (sessizce geçilir), yalnızca kalite kontrolü zorunlu.
        routing = replace(
            routing,
            state_tools={**STATE_TOOLS, S.BUILD_EVIDENCE: frozenset(), S.RISK_GATE: frozenset()},
            always_mandatory=frozenset({S.CHECK_DATA_QUALITY}),
            satisfied_by={S.CHECK_DATA_QUALITY: T.CHECK_DATA_QUALITY, S.RUN_BACKTEST: T.RUN_BACKTEST},
            auto_advance=frozenset({S.CHECK_DATA_QUALITY}),
            safe_failure_gates=frozenset(),
        )
    if profile.auto_gates:
        routing = replace(routing, auto_steps=dict(AUTO_STEPS))
    return routing


def harness_only_tools(profile: StageProfile) -> set[T]:
    """Kapıları harness çalıştırıyorsa (auto_gates) yalnızca harness'in çağırdığı araçlar."""
    if not profile.auto_gates:
        return set()
    routing = routing_for(profile)
    only: set[T] = set()
    for tool in T:
        states = [s for s in routing.order if tool in routing.state_tools[s]]
        if states and all(s in routing.auto_states for s in states):
            only.add(tool)
    return only


def visible_tools(profile: StageProfile) -> list[T]:
    """MODELE gösterilen araçlar (MCP listesi). Harness-içi araçlar ve kapalı özellikler çıkarılır."""
    if not profile.tools_enabled:
        return []
    hidden = harness_only_tools(profile)
    if not profile.evidence:
        hidden.add(T.BUILD_EVIDENCE_BUNDLE)
    return [t for t in T if t not in hidden]
