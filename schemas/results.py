"""15 aracın SONUÇ (`results`) şemaları (SÖZLEŞME).

KESİN (alan listesi bağlayıcı): rank_sector_relative_strength (1.2.0: per_ticker vb.), test_weekday_pattern,
detect_reversal_events, calculate_indicators (1.1.0; 1.2.0: hafif varsayılanlar), calculate_fundamental_change, run_backtest,
check_data_quality, get_stock_history, get_index_history.
HAFİF (iskelet kesin, iç ayrıntı gevşek): find_support_resistance,
get_fundamental_metrics, get_macro_context, get_news_events, get_speech_features,
build_evidence_bundle.

Birim kuralları için bkz. schemas/common.py başlığı (`_pct`, 0-100 ölçeği, as_of dahil).
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Annotated, Any

from pydantic import Field, StringConstraints, model_validator

from schemas.common import (
    BaselineStats,
    BenchmarkDefinition,
    ColumnName,
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
    IndicatorName,
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
    VerdictCode,
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
# 3  calculate_indicators (KESİN; 1.1.0, 1.2.0'da hafif varsayılanlar)
# ======================================================================
# Kompakt zarf: tüm zaman serisi DEĞİL; `latest` (as_of günü durumu) + `recent_rows` (önceki en fazla N gün).
# Sayılar `values` içinde (yalnızca float|None; NaN/inf yasak, ısınma = None), kategoriler `states` içinde.
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class IndicatorColumn(Strict):
    name: ColumnName = Field(description="ör. RSI_14, BB_LOWER_20_2.0, SMA_200")
    indicator: IndicatorName
    warmup_bars: int = Field(ge=0, description="İlk geçerli değer için gereken bar sayısı (ısınma)")
    first_valid_date: date | None = Field(description="Bu kolonun (as_of'a kadar) ilk geçerli değerinin tarihi")
    valid_at_as_of: bool = Field(description="state_date günündeki değer None değil mi")


class IndicatorStates(Strict):
    """Kategorik durumlar; None = ilgili gösterge istenmedi veya ısınmada. Tanımlar: docs/data_dictionary.md."""

    supertrend: SupertrendState | None = None
    ichimoku_position: IchimokuState | None = None
    kama_slope: KamaSlope | None = None
    volume_regime: VolumeRegime | None = None


class IndicatorRow(Strict):
    date: date
    close: FiniteFloat = Field(description="Seçilen fiyat modunda kapanış")
    values: dict[ColumnName, FiniteFloat | None] = Field(
        description="YALNIZCA sayısal; anahtarlar columns[].name ile birebir aynı; None = ısınma")
    states: IndicatorStates


class CalculateIndicatorsResult(Strict):
    ticker: Ticker
    price_adjustment: PriceAdjustment
    state_date: date | None = Field(description="min(end, as_of) günü veya öncesindeki son işlem günü")
    n_bars_used: int = Field(ge=0, description="Hesapta kullanılan toplam bar (ısınma dahil, <= as_of)")
    history_first_date: date | None = Field(description="Hesapta kullanılan ilk bar (snapshot başı)")
    first_valid_date: date | None = Field(description="İstenen TÜM kolonların geçerli olduğu ilk gün")
    columns_meta_included: bool = Field(
        default=True, description="False: columns boş (include_columns_meta=False); 1.1.0 zarfları True sayılır")
    columns: list[IndicatorColumn] = Field(description="columns_meta_included=False iken boş")
    invalid_columns_at_as_of: list[ColumnName] | None = Field(
        default=None, description="latest.values'ı None (ısınma) olan kolon adları, sıralı; 1.2.0+ zarflarında None olamaz")
    latest: IndicatorRow | None = Field(description="state_date günündeki gösterge durumu (as_of durumu)")
    recent_rows: list[IndicatorRow] = Field(description="latest'ten ÖNCEKİ en fazla last_n_rows gün, eskiden yeniye")

    @model_validator(mode="after")
    def _consistent(self):
        names = [c.name for c in self.columns]
        if len(set(names)) != len(names):
            raise ValueError("kolon adları tekil olmalı")
        if not self.columns_meta_included and self.columns:
            raise ValueError("columns_meta_included=False iken columns boş olmalı")
        for c in self.columns:
            if c.first_valid_date is None and c.valid_at_as_of:
                raise ValueError(f"{c.name}: first_valid_date yok ama valid_at_as_of=True")
        if self.latest is None:
            if self.state_date is not None or self.recent_rows:
                raise ValueError("latest yoksa state_date None ve recent_rows boş olmalı")
            if any(c.valid_at_as_of for c in self.columns):
                raise ValueError("latest yoksa hiçbir kolonda valid_at_as_of=True olamaz")
            if self.invalid_columns_at_as_of:
                raise ValueError("latest yoksa invalid_columns_at_as_of boş olmalı")
            return self
        if self.state_date != self.latest.date:
            raise ValueError("state_date, latest.date ile aynı olmalı")
        rows = [*self.recent_rows, self.latest]
        keys = set(self.latest.values)
        if self.columns_meta_included:
            for r in rows:
                if set(r.values) != set(names):
                    raise ValueError(f"{r.date}: values anahtarları columns ile birebir aynı olmalı")
        for r in rows:
            if set(r.values) != keys:
                raise ValueError(f"{r.date}: values anahtarları latest ile aynı olmalı")
        dates = [r.date for r in rows]
        if dates != sorted(set(dates)):
            raise ValueError("recent_rows tarihleri artan ve tekil olmalı, hepsi latest.date'ten önce")
        if self.recent_rows and self.recent_rows[-1].date >= self.latest.date:
            raise ValueError("recent_rows latest'ten önce olmalı")
        for c in self.columns:
            if c.valid_at_as_of != (self.latest.values[c.name] is not None):
                raise ValueError(f"{c.name}: valid_at_as_of, latest değeriyle tutarsız")
        if self.invalid_columns_at_as_of is not None:
            expected = sorted(k for k, v in self.latest.values.items() if v is None)
            if list(self.invalid_columns_at_as_of) != expected:
                raise ValueError("invalid_columns_at_as_of, latest.values içindeki None kolonlarla (sıralı) aynı olmalı")
        return self


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

    @model_validator(mode="after")
    def _complete_consistency(self):
        # Ufku dolmamışsa hiçbir sonuç alanı dolu olamaz (look-ahead sızıntısı olmasın).
        vals = (self.return_pct, self.reversal_success, self.reversal_strength_pct)
        if not self.complete and any(v is not None for v in vals):
            raise ValueError("complete=False iken return_pct/reversal_success/reversal_strength_pct None olmalı")
        if self.complete and self.return_pct is None:
            raise ValueError("complete=True iken return_pct dolu olmalı")
        return self


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


class TickerCatchUp(Strict):
    """1.2.0: tek hissenin tarihsel catch-up kırılımı. Havuzlu `historical_catch_up`'ın PARÇASIDIR (toplamları havuza eşit).

    IS/OOS yoktur (hisse başına 9-21 olay bölünemez); `per_horizon[].block.in_sample/out_of_sample` None olmalıdır.
    `is_laggard` ve `lag_score_pp` `ranking` satırının aynasıdır (tek kaynak: aynı dizi).
    """

    ticker: Ticker
    is_laggard: bool
    lag_score_pp: float
    n_raw_laggard_observations: int = Field(ge=0, description="Ham laggard hisse-günü (cooldown ÖNCESİ)")
    n_independent_events: int = Field(ge=0, description="Cooldown sonrası kabul edilen olay (tamamlanmamış ufuklar dahil)")
    n_excluded_incomplete_horizon: int = Field(ge=0, description="EN UZUN ufukta ufku as_of'u aşıp dışlanan olay")
    per_horizon: list[CatchUpHorizon]

    @model_validator(mode="after")
    def _own(self):
        hs = [row.block.horizon for row in self.per_horizon]
        if len(set(hs)) != len(hs):
            raise ValueError(f"{self.ticker}: per_horizon ufukları tekil olmalı")
        for row in self.per_horizon:
            if row.block.in_sample is not None or row.block.out_of_sample is not None:
                raise ValueError(f"{self.ticker}: per_ticker blokları in_sample/out_of_sample taşıyamaz")
        if self.n_independent_events > self.n_raw_laggard_observations:
            raise ValueError(f"{self.ticker}: n_independent_events ham gözlem sayısını aşamaz")
        return self


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
    n_raw_laggard_observations: int | None = Field(
        default=None, ge=0, description="1.2.0: tüm üyelerin ham laggard hisse-günü toplamı (cooldown öncesi); tek hisseli grupta None")
    cooldown_days: int | None = Field(
        default=None, ge=1, description="1.2.0: bağımsızlaştırma süresi, işlem günü (= max(forward_horizons)); tek hisseli grupta None")
    outcome_benchmark_definition: BenchmarkDefinition | None = Field(
        default=None, description="1.2.0: tarihsel SONUÇ ölçütü: peer medyanı, hisse HARİÇ (members = grup üyeleri; her hisse için kendisi çıkarılır)")
    per_ticker: list[TickerCatchUp] = Field(
        default_factory=list, description="1.2.0: hisse bazlı kırılım (ticker sıralı); tek hisseli grupta boş")
    cost_model: CostModel
    structural_vs_temporary: str | None = Field(default=None, description="Temel/makro araçlar gelince doldurulacak; şimdilik None")

    @model_validator(mode="after")
    def _per_ticker_sums_to_pool(self):
        """Havuz = parçaların toplamı: ham sayı, olay sayıları ve başarı/yanlış pozitif sayıları hisse bazında toplanınca havuzlu değere eşit."""
        if not self.per_ticker:
            return self
        rank = {r.ticker: r for r in self.ranking}
        tickers = [t.ticker for t in self.per_ticker]
        if len(set(tickers)) != len(tickers):
            raise ValueError("per_ticker ticker'ları tekil olmalı")
        if set(tickers) != set(rank):
            raise ValueError("per_ticker ticker'ları ranking ile aynı olmalı")
        for t in self.per_ticker:
            r = rank[t.ticker]
            if t.is_laggard != r.is_laggard or t.lag_score_pp != r.lag_score_pp:
                raise ValueError(f"{t.ticker}: per_ticker is_laggard/lag_score_pp ranking ile aynı olmalı")
        if self.n_raw_laggard_observations is not None and \
                sum(t.n_raw_laggard_observations for t in self.per_ticker) != self.n_raw_laggard_observations:
            raise ValueError("Σ per_ticker.n_raw_laggard_observations != n_raw_laggard_observations")
        pooled = {row.block.horizon: row.block.full for row in self.historical_catch_up}
        by_ticker = {}
        for t in self.per_ticker:
            by_h = {row.block.horizon: row.block.full for row in t.per_horizon}
            if set(by_h) != set(pooled):
                raise ValueError(f"{t.ticker}: per_horizon ufukları historical_catch_up ile aynı olmalı")
            for h, f in by_h.items():
                if t.n_independent_events != f.n_events_complete + f.n_excluded_incomplete_horizon:
                    raise ValueError(f"{t.ticker}: n_independent_events != n_events_complete + n_excluded (ufuk {h})")
            if by_h and t.n_excluded_incomplete_horizon != by_h[max(by_h)].n_excluded_incomplete_horizon:
                raise ValueError(f"{t.ticker}: n_excluded_incomplete_horizon en uzun ufuk bloğuyla aynı olmalı")
            by_ticker[t.ticker] = by_h
        for h, p in pooled.items():
            for attr in ("n_events_complete", "n_excluded_incomplete_horizon", "n_success", "n_false_positive"):
                total = sum(getattr(by_ticker[t][h], attr) for t in by_ticker)
                if total != getattr(p, attr):
                    raise ValueError(f"ufuk {h}: Σ per_ticker.{attr} ({total}) != havuz ({getattr(p, attr)})")
        return self


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
    cost_adjusted_outcome_mean_return_pct: float | None = Field(
        description="YÖNLÜ: OUTCOME yönü UP ise ortalama - tur maliyeti; DOWN ise (-ortalama) - tur maliyeti"
    )
    t_stat: float | None
    p_value_raw: float | None = Field(ge=0, le=1)
    p_value_adjusted: float | None = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _counts(self):
        # Sayısal alanlar, verdict ne olursa olsun hesaplanabiliyorsa DOLU döner (None ancak n=0 iken).
        if self.n_trigger_weeks > 0 and (self.outcome_mean_return_pct is None or self.outcome_median_return_pct is None):
            raise ValueError("n_trigger_weeks > 0 iken outcome ortalama/medyan dolu olmalı")
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
    verdict_codes: list[VerdictCode] = Field(description="Kararın nedenleri; STABLE ise boş")
    verdict_reason: str = Field(description="Her kod için 'KOD: sayılı açıklama', ';' ile ayrılmış")
    multiple_testing: MultipleTesting

    @model_validator(mode="after")
    def _verdict_consistency(self):
        codes = set(self.verdict_codes)
        too_few = {VerdictCode.IS_TOO_FEW, VerdictCode.OOS_TOO_FEW}
        v = self.stability_verdict
        if v == StabilityVerdict.STABLE and codes:
            raise ValueError("STABLE iken verdict_codes boş olmalı")
        if v == StabilityVerdict.INSUFFICIENT_DATA and not (codes and codes <= too_few):
            raise ValueError("INSUFFICIENT_DATA yalnızca IS_TOO_FEW/OOS_TOO_FEW kodlarını içerebilir")
        if v == StabilityVerdict.UNSTABLE and (not codes or codes & too_few):
            raise ValueError("UNSTABLE: en az bir neden kodu gerekli ve *_TOO_FEW içeremez")
        for c in codes:
            if c.value not in self.verdict_reason:
                raise ValueError(f"verdict_reason {c.value} kodunu içermeli")
        return self


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

    @model_validator(mode="after")
    def _complete_consistency(self):
        # complete=False (pencere as_of'u aşıyor): tarih ve tüm getiri alanları None.
        vals = (self.stock_return_pct, self.xu100_return_pct, self.sector_return_pct,
                self.abnormal_vs_xu100_pct, self.abnormal_vs_sector_pct)
        if not self.complete:
            if self.window_end_date is not None or any(v is not None for v in vals):
                raise ValueError("complete=False iken window_end_date ve getiri alanları None olmalı")
        else:
            if self.window_end_date is None or self.stock_return_pct is None:
                raise ValueError("complete=True iken window_end_date ve stock_return_pct dolu olmalı")
        return self


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
    last_data_age_days: int | None = Field(
        ge=0, description="as_of - (as_of'a kadarki son satır tarihi), takvim günü; last_date pencere sonudur, "
                          "bu yüzden end < as_of iken as_of - last_date'e eşit olmayabilir")
    max_abs_daily_return_pct: float | None
    max_abs_daily_return_date: date | None
    n_price_jumps_over_limit: int = Field(
        ge=0, description="|günlük adj_close getirisi| > price_jump_limit_pct + PRICE_JUMP_TOLERANCE_PP olan gün sayısı; "
                          "pencere [start, min(end, as_of)]; classify_price_jumps ile aynı kural")


class CheckDataQualityResult(Strict):
    gate_status: GateStatus
    gate_reason: str
    hard_blocks: list[DQIssue]
    soft_warnings: list[DQIssue]
    checks_run: list[DQCheck]
    price_jump_limit_pct: float
    ticker_reports: list[TickerQuality]
    issue_counts: dict[DQCode, int] | None = Field(
        default=None, description="1.2.0: kod -> adet (hard ve soft birlikte; sıfır girdi yok). None = raporlanmadı (1.1.0); 1.2.0+ zarflarında None olamaz")

    @model_validator(mode="after")
    def _consistency(self):
        if self.issue_counts is not None:
            actual = dict(Counter(i.code for i in [*self.hard_blocks, *self.soft_warnings]))
            if any(v < 1 for v in self.issue_counts.values()) or self.issue_counts != actual:
                raise ValueError(f"issue_counts hard_blocks+soft_warnings ile birebir aynı olmalı (beklenen {actual})")
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
