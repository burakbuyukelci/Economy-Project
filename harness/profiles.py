"""Deney aşaması profilleri (proje dokümanı §30, hoca_qa.md Soru 5): A–E, VERİ olarak.

  A Raw LLM            araç yok
  B LLM + Tools        araçlar açık; durum makinesi/zorunlu adım/kapı YOK (yalnızca as_of ve şema doğrulaması)
  C Tools + Stateful   araçlar + durum sırası ve zorunlu adımlar (kalite kontrolü, backtest) — çağıran MODEL;
                       kanıt paketi ve kalite KAPISI (güvenli hata yolu) yok
  D C + Evidence/Gate  kalite kapısı ve kanıt paketi HARNESS tarafından çalıştırılır (otomatik kapılar)
  E D + Memory/Review  D + insan incelemesi/hafıza (deney iskeleti madde 7'de bağlanacak)

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

    def __post_init__(self) -> None:
        if self.enforce_states and not self.tools_enabled:
            raise ValueError("enforce_states için tools_enabled gerekir")
        if self.auto_gates and not (self.enforce_states and self.evidence):
            raise ValueError("auto_gates için enforce_states ve evidence gerekir")
        if self.evidence and not self.enforce_states:
            raise ValueError("evidence için enforce_states gerekir")


PROFILES: dict[str, StageProfile] = {
    "A": StageProfile("A", tools_enabled=False, enforce_states=False, auto_gates=False, evidence=False, human_review=False),
    "B": StageProfile("B", tools_enabled=True, enforce_states=False, auto_gates=False, evidence=False, human_review=False),
    "C": StageProfile("C", tools_enabled=True, enforce_states=True, auto_gates=False, evidence=False, human_review=False),
    "D": StageProfile("D", tools_enabled=True, enforce_states=True, auto_gates=True, evidence=True, human_review=False),
    "E": StageProfile("E", tools_enabled=True, enforce_states=True, auto_gates=True, evidence=True, human_review=True),
}


def get_profile(name: str) -> StageProfile:
    try:
        return PROFILES[name.upper()]
    except KeyError:
        raise ValueError(f"bilinmeyen deney aşaması {name!r}; geçerli: {', '.join(PROFILES)}") from None


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


def visible_tools(profile: StageProfile) -> list[T]:
    """MODELE gösterilen araçlar (MCP listesi). Harness-içi araçlar ve kapalı özellikler çıkarılır."""
    if not profile.tools_enabled:
        return []
    routing = routing_for(profile)
    hidden: set[T] = set()
    if not profile.evidence:
        hidden.add(T.BUILD_EVIDENCE_BUNDLE)
    for tool in T:
        states = [s for s in routing.order if tool in routing.state_tools[s]]
        if profile.auto_gates and states and all(s in routing.auto_states for s in states):
            hidden.add(tool)
    return [t for t in T if t not in hidden]
