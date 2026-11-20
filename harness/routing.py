"""Durum makinesinin YÖNLENDİRME VERİSİ (kod değil, tablo).

Hocadan teyit gelince değişecek olan her şey burada durur; `state_machine.py` bu tabloyu yalnızca okur.

Zorunlu durumlar SORU SINIFLANDIRMASINDAN değil, modelin gerçekten çağırdığı araçlardan türetilir:
  * ALWAYS_MANDATORY: soru ne olursa olsun geçilmesi gereken durumlar (ör. CHECK_DATA_QUALITY).
  * TOOL_TRIGGERS_MANDATORY: bir araç BAŞARIYLA çağrıldığında zorunlu hale gelen ek durumlar.
    Karar (ekip): run_backtest yalnızca catch-up analizinde zorunlu -> rank_sector_relative_strength
    çağrıldıysa RUN_BACKTEST zorunlu. Diğer analiz araçları (test_weekday_pattern, detect_reversal_events,
    calculate_fundamental_change) kendi IS/OOS + baz getiri + maliyet çıktılarını verir; onlar için
    RUN_BACKTEST opsiyoneldir. (Hocadan teyit bekleniyor.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from schemas.enums import GateStatus, ToolName as T


class State(str, Enum):
    START = "START"
    SELECT_UNIVERSE = "SELECT_UNIVERSE"
    LOAD_MARKET_DATA = "LOAD_MARKET_DATA"
    CHECK_DATA_QUALITY = "CHECK_DATA_QUALITY"
    CALCULATE_TECHNICALS = "CALCULATE_TECHNICALS"
    RUN_SECTOR_RELATIVE_ANALYSIS = "RUN_SECTOR_RELATIVE_ANALYSIS"
    RUN_PATTERN_AND_REVERSAL_ANALYSIS = "RUN_PATTERN_AND_REVERSAL_ANALYSIS"
    LOAD_FUNDAMENTALS = "LOAD_FUNDAMENTALS"
    LOAD_MACRO_CONTEXT = "LOAD_MACRO_CONTEXT"
    LOAD_NEWS_AND_SPEECH_CONTEXT = "LOAD_NEWS_AND_SPEECH_CONTEXT"
    BUILD_EVIDENCE = "BUILD_EVIDENCE"
    PREVIEW_STRATEGIES = "PREVIEW_STRATEGIES"
    RUN_BACKTEST = "RUN_BACKTEST"
    RISK_GATE = "RISK_GATE"
    GENERATE_EXPLANATION = "GENERATE_EXPLANATION"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    LOG_AND_CLOSE = "LOG_AND_CLOSE"


class ReviewStatus(str, Enum):
    PENDING_HUMAN_REVIEW = "PENDING_HUMAN_REVIEW"  # varsayılan; canlı testte hep bu kalır
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


S = State

# Proje dokümanı §23 sırası.
STATE_ORDER: tuple[State, ...] = (
    S.START, S.SELECT_UNIVERSE, S.LOAD_MARKET_DATA, S.CHECK_DATA_QUALITY, S.CALCULATE_TECHNICALS,
    S.RUN_SECTOR_RELATIVE_ANALYSIS, S.RUN_PATTERN_AND_REVERSAL_ANALYSIS, S.LOAD_FUNDAMENTALS,
    S.LOAD_MACRO_CONTEXT, S.LOAD_NEWS_AND_SPEECH_CONTEXT, S.BUILD_EVIDENCE, S.PREVIEW_STRATEGIES,
    S.RUN_BACKTEST, S.RISK_GATE, S.GENERATE_EXPLANATION, S.HUMAN_REVIEW, S.LOG_AND_CLOSE,
)

# Her durumun açtığı MCP araç alt kümesi (§23: "each state should expose only a defined subset").
# Araçsız durumlar harness-içidir (LLM bir şey çağırmaz).
# PREVIEW_STRATEGIES araçsızdır: stratejiler (A-E) RUN_BACKTEST durumunda run_backtest'in
# strategy.variant alanıyla önizlenir; aksi halde run_backtest iki durumda belirsiz kalırdı.
STATE_TOOLS: dict[State, frozenset[T]] = {
    S.START: frozenset(),
    S.SELECT_UNIVERSE: frozenset(),
    S.LOAD_MARKET_DATA: frozenset({T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY}),
    S.CHECK_DATA_QUALITY: frozenset({T.CHECK_DATA_QUALITY}),
    S.CALCULATE_TECHNICALS: frozenset({T.CALCULATE_INDICATORS, T.FIND_SUPPORT_RESISTANCE}),
    S.RUN_SECTOR_RELATIVE_ANALYSIS: frozenset({T.RANK_SECTOR_RELATIVE_STRENGTH}),
    S.RUN_PATTERN_AND_REVERSAL_ANALYSIS: frozenset({T.DETECT_REVERSAL_EVENTS, T.TEST_WEEKDAY_PATTERN}),
    S.LOAD_FUNDAMENTALS: frozenset({T.GET_FUNDAMENTAL_METRICS, T.CALCULATE_FUNDAMENTAL_CHANGE}),
    S.LOAD_MACRO_CONTEXT: frozenset({T.GET_MACRO_CONTEXT}),
    S.LOAD_NEWS_AND_SPEECH_CONTEXT: frozenset({T.GET_NEWS_EVENTS, T.GET_SPEECH_FEATURES}),
    S.BUILD_EVIDENCE: frozenset({T.BUILD_EVIDENCE_BUNDLE}),
    S.PREVIEW_STRATEGIES: frozenset(),
    S.RUN_BACKTEST: frozenset({T.RUN_BACKTEST}),
    S.RISK_GATE: frozenset({T.CHECK_DATA_QUALITY, T.BUILD_EVIDENCE_BUNDLE}),  # aşama 2: backtest kanıtı + kapı
    S.GENERATE_EXPLANATION: frozenset(),
    S.HUMAN_REVIEW: frozenset(),
    S.LOG_AND_CLOSE: frozenset(),
}

# Soru ne olursa olsun geçilmesi zorunlu (araçlı) durumlar.
ALWAYS_MANDATORY: frozenset[State] = frozenset({S.CHECK_DATA_QUALITY, S.BUILD_EVIDENCE, S.RISK_GATE})

# Başarılı bir araç çağrısı sonrası zorunlu hale gelen ek durumlar (soru sınıflandırması YOK).
TOOL_TRIGGERS_MANDATORY: dict[T, frozenset[State]] = {
    T.RANK_SECTOR_RELATIVE_STRENGTH: frozenset({S.RUN_BACKTEST}),
}

# Bir durumun "yerine getirildi" sayılması için BAŞARILI (status=OK) çağrılması gereken araç.
SATISFIED_BY: dict[State, T] = {
    S.CHECK_DATA_QUALITY: T.CHECK_DATA_QUALITY,
    S.BUILD_EVIDENCE: T.BUILD_EVIDENCE_BUNDLE,
    S.RUN_BACKTEST: T.RUN_BACKTEST,
    S.RISK_GATE: T.CHECK_DATA_QUALITY,
}

# Yerine getirilince harness'in OTOMATİK sonraki duruma geçtiği durumlar.
# RUN_BACKTEST burada YOK: strateji varyantları için birden çok run_backtest çağrısı yapılabilir.
AUTO_ADVANCE_STATES: frozenset[State] = frozenset({S.CHECK_DATA_QUALITY, S.BUILD_EVIDENCE, S.RISK_GATE})

# BUILD_EVIDENCE için: bu durumlardan en az bir BAŞARILI araç çağrısı olmadan kanıt paketi kurulamaz.
EVIDENCE_SOURCE_STATES: frozenset[State] = frozenset({
    S.CALCULATE_TECHNICALS, S.RUN_SECTOR_RELATIVE_ANALYSIS, S.RUN_PATTERN_AND_REVERSAL_ANALYSIS,
    S.LOAD_FUNDAMENTALS, S.LOAD_MACRO_CONTEXT, S.LOAD_NEWS_AND_SPEECH_CONTEXT,
})

# Kapı araçları: bu araç, bu durumlarda çağrılınca sonucundaki gate_status güvenli hata yolunu tetikleyebilir.
GATE_TOOL = T.CHECK_DATA_QUALITY
GATE_STATES: frozenset[State] = frozenset({S.CHECK_DATA_QUALITY, S.RISK_GATE})
# §26 güvenli hata yolu: bu kapı sonuçlarında doğrudan GENERATE_EXPLANATION'a (eylem ANALYSIS_UNSAFE) git.
SAFE_FAILURE_GATES: frozenset[str] = frozenset({GateStatus.HARD_BLOCK.value, GateStatus.ANALYSIS_UNSAFE.value})

# Harness'in KENDİSİ çalıştırdığı adımlar (profil D/E: auto_gates). Durum -> sırayla çağrılacak araçlar.
# RISK_GATE'te önce aşama-2 kanıt paketi (backtest kanıtı eklenir), sonra son kalite kapısı çalışır.
AUTO_STEPS: dict[State, tuple[T, ...]] = {
    S.CHECK_DATA_QUALITY: (T.CHECK_DATA_QUALITY,),
    S.BUILD_EVIDENCE: (T.BUILD_EVIDENCE_BUNDLE,),
    S.RISK_GATE: (T.BUILD_EVIDENCE_BUNDLE, T.CHECK_DATA_QUALITY),
}

# LLM'in araç çağıramadığı (açıklama/inceleme/kapanış) aşama.
POST_ANALYSIS_STATES: frozenset[State] = frozenset({S.GENERATE_EXPLANATION, S.HUMAN_REVIEW, S.LOG_AND_CLOSE})


@dataclass(frozen=True)
class Routing:
    """Yukarıdaki tabloları bir araya getirir; testler/deneyler farklı bir Routing verebilir."""

    order: tuple[State, ...] = STATE_ORDER
    state_tools: dict[State, frozenset[T]] = field(default_factory=lambda: STATE_TOOLS)
    always_mandatory: frozenset[State] = ALWAYS_MANDATORY
    tool_triggers: dict[T, frozenset[State]] = field(default_factory=lambda: TOOL_TRIGGERS_MANDATORY)
    satisfied_by: dict[State, T] = field(default_factory=lambda: SATISFIED_BY)
    auto_advance: frozenset[State] = AUTO_ADVANCE_STATES
    evidence_sources: frozenset[State] = EVIDENCE_SOURCE_STATES
    gate_tool: T = GATE_TOOL
    gate_states: frozenset[State] = GATE_STATES
    safe_failure_gates: frozenset[str] = SAFE_FAILURE_GATES
    post_analysis: frozenset[State] = POST_ANALYSIS_STATES
    # Boşsa kapıları model çağırır (manuel). Doluysa harness çalıştırır ve bu araçlar modele KAPALIDIR.
    auto_steps: dict[State, tuple[T, ...]] = field(default_factory=dict)

    @property
    def auto_states(self) -> frozenset[State]:
        return frozenset(self.auto_steps)


DEFAULT_ROUTING = Routing()
