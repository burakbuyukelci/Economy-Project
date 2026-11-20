"""15 aracın SONUÇ (`results`) şemaları (SÖZLEŞME).

KESİN (alan listesi bağlayıcı): rank_sector_relative_strength, test_weekday_pattern,
detect_reversal_events, calculate_fundamental_change, run_backtest, check_data_quality,
get_stock_history, get_index_history.
HAFİF (iskelet kesin, iç ayrıntı gevşek): calculate_indicators, find_support_resistance,
get_fundamental_metrics, get_macro_context, get_news_events, get_speech_features,
build_evidence_bundle.

Birim kuralları için bkz. schemas/common.py başlığı (`_pct`, 0-100 ölçeği, as_of dahil).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field, model_validator

from schemas.common import (
    BaselineStats,
    BenchmarkDefinition,
    CostModel,
    FiscalPeriod,
    Horizon,
    HorizonBlock,
    HorizonStats,
    InputHash,
    MultipleTesting,
    SampleWindow,
    Strict,
    Ticker,
)
from schemas.enums import (
    AllowedAction,
    BenchmarkName,
    ChangeUnit,
    ClaimType,
    Conditioning,
    DQCheck,
    DQCode,
    DQSeverity,
    Direction,
    EventFamily,
    FundamentalMetricName,
    GateStatus,
    IchimokuState,
    IndexId,
    KamaSlope,
    LevelType,
    MacroSeries,
    MarketRegime,
    MetricDirection,
    MetricSet,
    NewsCategory,
    PatternRole,
    PeerGroup,
    PriceAdjustment,
    ReactionGroup,
    RsiState,
    SectorStrength,
    SplitName,
    StabilityVerdict,
    StrategyVariant,
    SupertrendState,
    ToolName,
    TouchMode,
    VolumeRegime,
    Weekday,
)
from schemas.params import ConditionSet, StrategySpec


# ======================================================================
# 1-2  get_stock_history / get_index_history
# ======================================================================
class OHLCVRow(Strict):
    date: date
    open: float
    high: float
    low: float
    close: float = Field(description="Ham kapanış")
    adj_close: float = Field(description="Düzeltilmiş kapanış (varsayılan analiz fiyatı)")
    volume: float = Field(ge=0)


class GetStockHistoryResult(Strict):
    ticker: Ticker
    yahoo_symbol: str
    price_adjustment: PriceAdjustment
    requested_start: date
    requested_end: date
    effective_end: date = Field(description="min(end, as_of)")
    first_date: date | None
    last_date: date | None
    n_rows: int = Field(ge=0)
    rows: list[OHLCVRow]


class GetIndexHistoryResult(Strict):
    index: IndexId
    yahoo_symbol: str
    requested_start: date
    requested_end: date
    effective_end: date
    first_date: date | None
    last_date: date | None
    n_rows: int = Field(ge=0)
    rows: list[OHLCVRow]


# ======================================================================
# 3  calculate_indicators (HAFİF)
# ======================================================================
class IndicatorRow(Strict):
    date: date
    values: dict[str, float | str | None] = Field(description="ör. {'RSI_14': 41.2, 'BB_LOWER_20_2': 273.4, 'SUPERTREND_DIR': 'BEARISH'}")


class CalculateIndicatorsResult(Strict):
    ticker: Ticker
    first_valid_date: date | None = Field(description="Isınma sonrası tüm istenen göstergelerin geçerli olduğu ilk gün")
    last_date: date | None
    columns: list[str]
    n_rows: int = Field(ge=0)
    rows: list[IndicatorRow]


# ======================================================================
# 4  detect_reversal_events (KESİN)
# ======================================================================
class EventStates(Strict):
    rsi: RsiState | None = None
    supertrend: SupertrendState | None = None
    kama_slope: KamaSlope | None = None
    ichimoku: IchimokuState | None = None
    volume: VolumeRegime | None = None


class ForwardReturn(Strict):
    horizon: Horizon
    complete: bool = Field(description="False: ufuk as_of'u aşıyor; bu olay o ufuk istatistiğine katılmaz")
    return_pct: float | None = Field(description="Olay günü kapanışından t+h kapanışına; complete=False ise None")
    reversal_success: bool | None = None
    reversal_strength_pct: float | None = Field(default=None, description="Ufuk içi maksimum lehte hareket (MFE)")


class ReversalEventRecord(Strict):
    date: date
    close: float
    states: EventStates
    forward_returns: list[ForwardReturn]


class RegimeBreakdown(Strict):
    regime: MarketRegime
    horizon: Horizon = Field(description="Rejim kırılımının hesaplandığı ufuk (en uzun ufuk)")
    n_events: int = Field(ge=0)
    hit_rate_pct: float | None = Field(default=None, ge=0, le=100)
    mean_return_pct: float | None = None


class ReversalGroup(Strict):
    label: str = Field(description="'single_indicator' = koşulsuz; diğerleri condition_sets etiketleri")
    conditions: ConditionSet | None = None
    n_events_detected: int = Field(ge=0, description="Koşulu sağlayan toplam olay (tamamlanmamış ufuklar dahil)")
    per_horizon: list[HorizonBlock]
    regime_breakdown: list[RegimeBreakdown] = Field(default_factory=list)
    events: list[ReversalEventRecord] = Field(default_factory=list, description="Üst sınırlı (en son 100)")
    events_truncated: bool = False


class DetectReversalEventsResult(Strict):
    ticker: Ticker
    event_family: EventFamily
    touch_mode: TouchMode
    expected_direction: Direction = Field(description="Alt bant/dip: UP; üst bant/tepe: DOWN")
    analysis_start: date
    analysis_end: date = Field(description="min(as_of, son veri günü)")
    split_date: date | None
    cost_model: CostModel
    groups: list[ReversalGroup] = Field(min_length=1)
    multiple_testing: MultipleTesting


# ======================================================================
# 6  rank_sector_relative_strength (KESİN)
# ======================================================================
class RankingRow(Strict):
    rank: int = Field(ge=1, description="1 = en güçlü (en yüksek getiri)")
    ticker: Ticker
    return_pct: float
    lag_score_pp: float = Field(description="return_pct - sector_median_return_pct (peer medyan, hisse dahil)")
    return_vs_xu100_pp: float
    is_laggard: bool = Field(description="lag_score_pp <= -lag_threshold_pp")
    is_leader: bool = Field(description="lag_score_pp >= +lag_threshold_pp")


class StrengthThresholds(Strict):
    strong_min_vs_xu100_pp: float
    weak_max_vs_xu100_pp: float


class CatchUpHorizon(Strict):
    """Tarihsel: benzer geride kalma olaylarından sonra laggard, peer medyanını yakaladı mı?"""

    block: HorizonBlock
    median_catch_up_size_pp: float | None = Field(
        default=None, description="Başarılı olaylarda (laggard > peer medyan) medyan göreli getiri farkı"
    )


class RankSectorRelativeStrengthResult(Strict):
    sector: PeerGroup
    peer_group_size: int = Field(ge=1)
    insufficient_peers: bool = Field(description="peer_group_size < 2: medyan/rank anlamlı değil")
    horizon: Horizon
    window_start: date = Field(description="Lag penceresinin ilk işlem günü (getiri bu günün bir önceki kapanışından)")
    window_end: date = Field(description="<= as_of")
    benchmark_definition: BenchmarkDefinition
    sector_median_return_pct: float | None
    xu100_return_pct: float | None
    sector_median_vs_xu100_pp: float | None
    sector_strength: SectorStrength | None
    strength_thresholds: StrengthThresholds
    lag_threshold_pp: float
    ranking: list[RankingRow]
    historical_catch_up: list[CatchUpHorizon]
    cost_model: CostModel
    structural_vs_temporary: str | None = Field(default=None, description="Temel/makro araçlar gelince doldurulacak; şimdilik None")


# ======================================================================
# 7  test_weekday_pattern (KESİN)
# ======================================================================
class PatternDayStats(Strict):
    weekday: Weekday
    expected_direction: Direction
    role: PatternRole
    n_obs: int = Field(ge=0)
    mean_return_pct: float | None
    median_return_pct: float | None
    direction_match_rate_pct: float | None = Field(ge=0, le=100)
    unconditional_mean_return_pct: float | None = Field(description="Aynı dönemde TÜM işlem günleri ortalaması")
    unconditional_median_return_pct: float | None


class WeekdayPeriodResult(Strict):
    window: SampleWindow
    n_weeks_total: int = Field(ge=0)
    n_excluded_holiday_weeks: int = Field(ge=0, description="Örüntü günlerinden biri tatil olduğu için dışlanan haftalar")
    n_excluded_incomplete_horizon: int = Field(ge=0, description="as_of'ta henüz tamamlanmamış hafta(lar)")
    n_weeks_complete: int = Field(ge=0)
    n_trigger_weeks: int = Field(ge=0, description="TRIGGER günleri beklenen yönde olan hafta (TRIGGER yoksa tüm tam haftalar)")
    n_occurrences: int = Field(ge=0, description="TRIGGER + OUTCOME günlerinin hepsi eşleşen hafta")
    n_false_positive: int = Field(ge=0, description="n_trigger_weeks - n_occurrences")
    occurrence_rate_pct: float | None = Field(ge=0, le=100)
    hit_rate_pct: float | None = Field(ge=0, le=100, description="n_occurrences / n_trigger_weeks")
    expected_occurrences_if_independent: float | None = Field(description="Günler bağımsızmış gibi beklenen tesadüfi sayı")
    per_day: list[PatternDayStats]
    outcome_mean_return_pct: float | None = Field(description="TRIGGER haftalarında OUTCOME günleri bileşik getirisi")
    outcome_median_return_pct: float | None
    unconditional_outcome_mean_return_pct: float | None = Field(description="Aynı OUTCOME günleri, TÜM tam haftalar")
    unconditional_outcome_median_return_pct: float | None
    outcome_mean_diff_vs_unconditional_pct: float | None
    cost_adjusted_outcome_mean_return_pct: float | None
    t_stat: float | None
    p_value_raw: float | None = Field(ge=0, le=1)
    p_value_adjusted: float | None = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _counts(self):
        if self.n_false_positive != self.n_trigger_weeks - self.n_occurrences:
            raise ValueError("n_false_positive != n_trigger_weeks - n_occurrences")
        if self.n_weeks_complete + self.n_excluded_holiday_weeks + self.n_excluded_incomplete_horizon != self.n_weeks_total:
            raise ValueError("n_weeks_complete + dışlananlar != n_weeks_total")
        return self


class TestWeekdayPatternResult(Strict):
    __test__ = False

    ticker: Ticker
    pattern_label: str = Field(description="ör. 'MON-DOWN,TUE-DOWN,WED-DOWN | THU-UP,FRI-UP'")
    conditioning: Conditioning
    cost_model: CostModel
    in_sample: WeekdayPeriodResult
    out_of_sample: WeekdayPeriodResult
    stability_verdict: StabilityVerdict
    verdict_reason: str
    multiple_testing: MultipleTesting


# ======================================================================
# 8  get_fundamental_metrics (HAFİF)
# ======================================================================
class MetricValue(Strict):
    name: FundamentalMetricName
    value: float | None
    unit: str = Field(description="ör. 'TRY_mn', 'PCT', 'RATIO'")


class GetFundamentalMetricsResult(Strict):
    ticker: Ticker
    metric_set: MetricSet
    fiscal_period: FiscalPeriod | None
    period_end_date: date | None
    disclosure_date: date | None = Field(description="KAP açıklama tarihi; <= as_of")
    tms29_comparable: bool | None = Field(description="2025 ve sonrası dönemler True; öncesi False")
    metrics: list[MetricValue]


# ======================================================================
# 9  calculate_fundamental_change (KESİN)
# ======================================================================
class MetricChange(Strict):
    name: FundamentalMetricName
    value: float | None
    qoq_change: float | None
    yoy_change: float | None
    change_unit: ChangeUnit
    qoq_direction: MetricDirection | None
    yoy_direction: MetricDirection | None


class QuarterReaction(Strict):
    horizon: Horizon
    window_end_date: date | None = Field(description="disclosure_date + horizon işlem günü; as_of'u aşıyorsa None")
    complete: bool
    stock_return_pct: float | None
    xu100_return_pct: float | None
    sector_return_pct: float | None = Field(description="Peer medyan (hisse dahil); tek hisseli grupta None")
    abnormal_vs_xu100_pct: float | None
    abnormal_vs_sector_pct: float | None


class QuarterRow(Strict):
    fiscal_period: FiscalPeriod
    period_end_date: date
    disclosure_date: date = Field(description="KAP açıklama tarihi (hizalama bunun üzerinden; dönem sonu DEĞİL)")
    tms29_comparable: bool
    metrics: list[MetricChange]
    reactions: list[QuarterReaction]


class ReactionSummary(Strict):
    horizon: Horizon
    group: ReactionGroup
    n: int = Field(ge=0, description="Ufku tamamlanmış çeyrek sayısı")
    n_excluded_incomplete_horizon: int = Field(ge=0)
    mean_abnormal_vs_xu100_pct: float | None
    median_abnormal_vs_xu100_pct: float | None
    hit_rate_vs_xu100_pct: float | None = Field(ge=0, le=100, description="abnormal > 0 olan çeyrek oranı")
    mean_abnormal_vs_sector_pct: float | None
    median_abnormal_vs_sector_pct: float | None


class CalculateFundamentalChangeResult(Strict):
    ticker: Ticker
    metric_set: MetricSet
    benchmark_definition: BenchmarkDefinition = Field(description="Sektör ölçütü tanımı (peer medyan, hisse dahil)")
    improvement_metric: FundamentalMetricName
    improvement_basis: str = Field(description="QOQ | YOY")
    n_quarters_disclosed_by_as_of: int = Field(ge=0)
    n_quarters_excluded_not_yet_disclosed: int = Field(ge=0, description="disclosure_date > as_of olanlar")
    quarters: list[QuarterRow]
    reaction_summary: list[ReactionSummary]


# ======================================================================
# 5  find_support_resistance (HAFİF)
# ======================================================================
class SRLevel(Strict):
    type: LevelType
    price: float
    zone_low: float
    zone_high: float
    touch_count: int = Field(ge=0)
    last_touch_date: date | None
    strength: float = Field(description="Dokunuş sayısı, yenilik ve hacme dayalı skor (tanım data_dictionary'de)")


class FindSupportResistanceResult(Strict):
    ticker: Ticker
    last_close: float | None
    last_date: date | None
    nearest_support: float | None
    nearest_resistance: float | None
    levels: list[SRLevel]


# ======================================================================
# 10  get_macro_context (HAFİF)
# ======================================================================
class MacroPoint(Strict):
    observation_date: date
    publication_date: date = Field(description="<= as_of; yayın tarihine göre hizalama (revizyon sonradan eklenmez)")
    value: float


class MacroGap(Strict):
    start: date
    end: date


class MacroSeriesData(Strict):
    series: MacroSeries
    source: str
    frequency: str
    n_points: int = Field(ge=0)
    last_publication_date: date | None
    gaps: list[MacroGap] = Field(default_factory=list)
    points: list[MacroPoint]


class GetMacroContextResult(Strict):
    start: date
    end: date
    series: list[MacroSeriesData]


# ======================================================================
# 11  get_news_events (HAFİF)
# ======================================================================
class NewsEvent(Strict):
    event_id: str
    published_date: date = Field(description="<= as_of")
    published_time: str | None = Field(default=None, description="HH:MM (yerel saat) biliniyorsa")
    headline: str
    source: str
    url: str | None = None
    tickers: list[Ticker] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    category: NewsCategory = NewsCategory.OTHER
    stance: str | None = Field(default=None, description="İsteğe bağlı basit duygu etiketi; ham kaynak korunur")


class GetNewsEventsResult(Strict):
    n_events_returned: int = Field(ge=0)
    events: list[NewsEvent]


# ======================================================================
# 12  get_speech_features (HAFİF)
# ======================================================================
class SpeechClaim(Strict):
    text: str
    claim_type: ClaimType
    numerical_claim_verified: bool | None = Field(default=None, description="Sayısal iddia araçla doğrulandı mı")


class SpeechSegment(Strict):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(ge=0)
    topics: list[str] = Field(default_factory=list)
    stance: str | None = None
    uncertainty: str | None = None
    claims: list[SpeechClaim] = Field(default_factory=list)


class GetSpeechFeaturesResult(Strict):
    source_id: str
    video_url: str
    speaker_channel: str
    published_date: date = Field(description="<= as_of")
    transcript_quality: float | None = Field(default=None, ge=0, le=1)
    segments: list[SpeechSegment]


# ======================================================================
# 13  run_backtest (KESİN)
# ======================================================================
class PerformanceMetrics(Strict):
    cumulative_return_pct: float | None
    annualized_return_pct: float | None
    sharpe_ratio: float | None = Field(description="Günlük getiri, rf=config SHARPE_RISK_FREE_RATE, yıllıklandırma sqrt(252)")
    max_drawdown_pct: float | None = Field(description="Negatif veya 0 (ör. -18.4)")
    win_rate_pct: float | None = Field(ge=0, le=100)
    n_trades: int = Field(ge=0)
    avg_trade_return_pct: float | None
    median_trade_return_pct: float | None
    exposure_pct: float | None = Field(default=None, ge=0, le=100)


class BenchmarkComparison(Strict):
    name: BenchmarkName
    metrics: PerformanceMetrics
    cumulative_return_diff_pct: float | None = Field(description="net strateji - benchmark (yüzde puan)")
    sharpe_diff: float | None


class SplitResult(Strict):
    name: SplitName
    window: SampleWindow
    n_signals: int = Field(ge=0)
    net_metrics: PerformanceMetrics
    benchmark_diff_pct: float | None = Field(description="net kümülatif getiri - ilk benchmark")


class Trade(Strict):
    ticker: Ticker
    signal_date: date
    entry_date: date
    exit_date: date
    gross_return_pct: float
    net_return_pct: float = Field(description="gross - CostModel.round_trip_cost_pct")

    @model_validator(mode="after")
    def _shift(self):
        if not (self.signal_date < self.entry_date <= self.exit_date):
            raise ValueError("signal_date < entry_date <= exit_date olmalı (signal shifting)")
        return self


class RunBacktestResult(Strict):
    strategy: StrategySpec
    universe: list[Ticker]
    period: SampleWindow = Field(description="Etkin dönem: [start, min(end, as_of)]")
    signal_lag_days_applied: int = Field(ge=1)
    cost_model: CostModel
    sharpe_definition: str
    n_signals: int = Field(ge=0)
    n_excluded_incomplete_horizon: int = Field(ge=0, description="Çıkışı as_of'tan sonraya taşan sinyaller")
    n_winning_trades: int = Field(ge=0)
    n_losing_trades: int = Field(ge=0, description="Yanlış pozitif: net getirisi <= 0 işlem")
    strategy_gross: PerformanceMetrics
    strategy_net: PerformanceMetrics = Field(description="Maliyet ve slippage sonrası")
    benchmarks: list[BenchmarkComparison]
    splits: list[SplitResult]
    oos_degradation_flag: bool | None
    low_signal_flag: bool = Field(description="n_signals < MIN_EVENTS")
    trade_log: list[Trade]
    trade_log_truncated: bool = False


# ======================================================================
# 14  check_data_quality (KESİN)
# ======================================================================
_Date = date  # DQIssue içinde `date` alan adı tipi gölgelemesin diye takma ad


class DQIssue(Strict):
    code: DQCode
    severity: DQSeverity
    message: str
    ticker: Ticker | None = None
    date: _Date | None = None
    value: float | None = None


class TickerQuality(Strict):
    ticker: str = Field(description="Hisse veya 'XU100'")
    n_rows: int = Field(ge=0)
    first_date: date | None
    last_date: date | None
    n_missing_trading_days: int = Field(ge=0)
    last_data_age_days: int | None = Field(ge=0, description="as_of - last_date (takvim günü)")
    max_abs_daily_return_pct: float | None
    max_abs_daily_return_date: date | None
    n_price_jumps_over_limit: int = Field(ge=0, description="|günlük getiri| > price_jump_limit_pct olan gün sayısı")


class CheckDataQualityResult(Strict):
    gate_status: GateStatus
    gate_reason: str
    hard_blocks: list[DQIssue]
    soft_warnings: list[DQIssue]
    checks_run: list[DQCheck]
    price_jump_limit_pct: float
    ticker_reports: list[TickerQuality]

    @model_validator(mode="after")
    def _consistency(self):
        if any(i.severity != DQSeverity.HARD for i in self.hard_blocks):
            raise ValueError("hard_blocks yalnızca severity=HARD içerebilir")
        if any(i.severity != DQSeverity.SOFT for i in self.soft_warnings):
            raise ValueError("soft_warnings yalnızca severity=SOFT içerebilir")
        if self.hard_blocks and self.gate_status != GateStatus.HARD_BLOCK:
            raise ValueError("hard_blocks varsa gate_status HARD_BLOCK olmalı")
        if not self.hard_blocks and not self.soft_warnings and self.gate_status != GateStatus.PASS:
            raise ValueError("sorun yoksa gate_status PASS olmalı")
        if not self.hard_blocks and self.gate_status == GateStatus.HARD_BLOCK:
            raise ValueError("HARD_BLOCK için en az bir hard_block gerekli")
        return self


# ======================================================================
# 15  build_evidence_bundle (HAFİF)
# ======================================================================
class EvidenceValue(Strict):
    name: str
    value: float | str
    unit: str | None = None


class EvidenceItem(Strict):
    evidence_id: str = Field(pattern=r"^E\d+$")
    statement: str
    source_tool: ToolName
    source_input_hash: InputHash
    values: list[EvidenceValue] = Field(default_factory=list)


class BuildEvidenceBundleResult(Strict):
    analysis_id: str
    full_evidence_set: list[EvidenceItem] = Field(description="Gözlenen tüm bağlam")
    committed_evidence_set: list[EvidenceItem] = Field(description="Sonucu gerçekten gerekçelendiren alt küme")
    gate_status: GateStatus | None = None
    proposed_action: AllowedAction | None = None

    @model_validator(mode="after")
    def _subset(self):
        full_ids = {e.evidence_id for e in self.full_evidence_set}
        if not {e.evidence_id for e in self.committed_evidence_set} <= full_ids:
            raise ValueError("committed_evidence_set, full_evidence_set'in alt kümesi olmalı")
        return self
