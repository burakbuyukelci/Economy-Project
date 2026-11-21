"""15 aracın PARAMETRE şemaları (SÖZLEŞME, kesin).

Genel kurallar:
  * `as_of` her araçta zorunlu (ToolParams tabanı). Dahil: date <= as_of.
  * `end`/`start` as_of'u aşarsa araç as_of'a KESER ve AS_OF_CLAMPED uyarısı verir (şema reddetmez).
  * Liste parametreleri sıralı-tekil normalize edilir (aynı küme -> aynı input_hash).
  * Bilinmeyen alan yasak (extra=forbid).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import Field, field_validator, model_validator

from config.settings import (
    ANALYSIS_START_DEFAULT,
    LAG_THRESHOLD_PP_DEFAULT,
    PRICE_JUMP_LIMIT_PCT,
)
from schemas.common import (
    CostParams,
    FiscalPeriod,
    ColumnName,
    Horizon,
    Strict,
    Ticker,
    ToolParams,
    DataVersion,
    InputHash,
    sorted_unique,
)
from schemas.enums import (
    BenchmarkName,
    ChangeBasis,
    Conditioning,
    DQCheck,
    EventFamily,
    FundamentalMetricName,
    IchimokuState,
    IndexId,
    IndicatorName,
    KamaSlope,
    MacroSeries,
    PatternRole,
    PeerGroup,
    PriceAdjustment,
    RsiState,
    SignalType,
    StrategyVariant,
    SupertrendState,
    ToolName,
    TouchMode,
    VolumeRegime,
    Weekday,
    Direction,
)


def _norm_horizons(v: list[int]) -> list[int]:
    if not v:
        raise ValueError("ufuk listesi boş olamaz")
    return sorted_unique(v)


def _check_range(start: date, end: date) -> None:
    if start > end:
        raise ValueError("start > end")


# 1 ---------------------------------------------------------------------
class GetStockHistoryParams(ToolParams):
    ticker: Ticker
    start: date
    end: date
    price_adjustment: PriceAdjustment = PriceAdjustment.ADJUSTED

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 2 ---------------------------------------------------------------------
class GetIndexHistoryParams(ToolParams):
    index: IndexId
    start: date
    end: date

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 3 ---------------------------------------------------------------------
class IndicatorConfig(Strict):
    sma_windows: list[int] = Field(default_factory=lambda: [20, 50, 200])
    ema_windows: list[int] = Field(default_factory=lambda: [12, 26])
    rsi_period: int = Field(default=14, ge=2)
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_window: int = Field(default=20, ge=2)
    bollinger_std: float = Field(default=2.0, gt=0)
    atr_period: int = Field(default=14, ge=1)
    kama_er_window: int = Field(default=10, ge=2)
    kama_fast: int = 2
    kama_slow: int = 30
    supertrend_atr_period: int = Field(default=10, ge=1)
    supertrend_multiplier: float = Field(default=3.0, gt=0)
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou_b: int = 52
    volume_zscore_window: int = Field(default=20, ge=2)

    @field_validator("sma_windows", "ema_windows")
    @classmethod
    def _sorted(cls, v: list[int]) -> list[int]:
        return sorted_unique(v)


class CalculateIndicatorsParams(ToolParams):
    ticker: Ticker
    indicators: list[IndicatorName] = Field(min_length=1)
    config: IndicatorConfig = Field(default_factory=IndicatorConfig)
    price_adjustment: PriceAdjustment = PriceAdjustment.ADJUSTED
    last_n_rows: int = Field(default=0, ge=0, le=30, description="latest'ten önceki kaç gün satırı dönsün (0 = yalnızca durum; varsayılan hafif)")
    include_columns_meta: bool = Field(default=False, description="True: sonuca kolon ısınma bilgisi (columns) eklenir; varsayılan False (hafif zarf)")
    value_columns: list[ColumnName] | None = Field(
        default=None, description="None = istenen göstergelerin tüm kolonları; verilirse values yalnızca bu kolon adlarını taşır (ör. RSI_14)")
    start: date = ANALYSIS_START_DEFAULT
    end: date

    @field_validator("indicators")
    @classmethod
    def _uniq(cls, v: list[IndicatorName]) -> list[IndicatorName]:
        return sorted(set(v), key=lambda x: x.value)

    @field_validator("value_columns")
    @classmethod
    def _cols(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("value_columns boş olamaz (hepsi için None verin)")
        return sorted(set(v))

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 4 ---------------------------------------------------------------------
class ConditionSet(Strict):
    """Birleşik koşul (hepsi VE'lenir). Belirtilmeyen alan = koşul yok."""

    label: str = Field(min_length=1, max_length=80)
    rsi_state: RsiState | None = None
    supertrend_state: SupertrendState | None = None
    ichimoku_state: IchimokuState | None = None
    volume_regime: VolumeRegime | None = None
    kama_slope: KamaSlope | None = None


class DetectReversalEventsParams(ToolParams, CostParams):
    ticker: Ticker
    event_family: EventFamily
    touch_mode: TouchMode = TouchMode.CLOSE
    condition_sets: list[ConditionSet] = Field(default_factory=list, description="Boşsa yalnızca tekli (koşulsuz) olay")
    forward_horizons: list[Horizon] = Field(default_factory=lambda: [1, 3, 5, 10])
    indicator_config: IndicatorConfig = Field(default_factory=IndicatorConfig)
    analysis_start: date = ANALYSIS_START_DEFAULT
    split_date: date | None = Field(default=None, description="Örneklem içi < split_date <= örneklem dışı")
    n_tests_declared: int = Field(default=1, ge=1)

    @field_validator("forward_horizons")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        return _norm_horizons(v)

    @model_validator(mode="after")
    def _s(self):
        if self.split_date is not None:
            if self.split_date <= self.analysis_start:
                raise ValueError("split_date analysis_start'tan sonra olmalı")
            if self.split_date > self.as_of:
                raise ValueError("split_date as_of'tan sonra olamaz")
        if self.analysis_start > self.as_of:
            raise ValueError("analysis_start as_of'tan sonra olamaz")
        return self


# 5 ---------------------------------------------------------------------
class FindSupportResistanceParams(ToolParams):
    ticker: Ticker
    start: date = ANALYSIS_START_DEFAULT
    end: date
    tolerance_pct: float = Field(default=1.0, gt=0, le=10, description="Seviye kümeleme toleransı, yüzde")
    min_touches: int = Field(default=2, ge=2)
    pivot_window: int = Field(default=5, ge=2)

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 6 ---------------------------------------------------------------------
class RankSectorRelativeStrengthParams(ToolParams):
    """`sector` = config/universe.csv `peer_group` kimliği (enum). Serbest metin `sector_label` DEĞİL."""

    sector: PeerGroup
    horizon: Horizon = Field(default=20, description="Lag penceresi, işlem günü")
    forward_horizons: list[Horizon] = Field(default_factory=lambda: [5, 10, 20])
    lag_threshold_pp: float = Field(default=LAG_THRESHOLD_PP_DEFAULT, gt=0)
    analysis_start: date = ANALYSIS_START_DEFAULT
    split_date: date | None = None

    @field_validator("forward_horizons")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        return _norm_horizons(v)

    @model_validator(mode="after")
    def _s(self):
        if self.split_date is not None:
            if self.split_date <= self.analysis_start:
                raise ValueError("split_date analysis_start'tan sonra olmalı")
            if self.split_date > self.as_of:
                raise ValueError("split_date as_of'tan sonra olamaz")
        return self


# 7 ---------------------------------------------------------------------
class PatternDay(Strict):
    weekday: Weekday
    direction: Direction
    role: PatternRole = PatternRole.TRIGGER


class TestWeekdayPatternParams(ToolParams, CostParams):
    __test__ = False  # pytest bu sınıfı test sanmasın

    ticker: Ticker
    pattern: list[PatternDay] = Field(min_length=1)
    in_sample_start: date
    in_sample_end: date
    out_of_sample_start: date
    out_of_sample_end: date
    conditioning: Conditioning = Conditioning.NONE
    n_tests_declared: int = Field(default=1, ge=1)
    alpha: float = Field(default=0.05, gt=0, lt=1)

    @field_validator("pattern")
    @classmethod
    def _pattern(cls, v: list[PatternDay]) -> list[PatternDay]:
        days = [p.weekday for p in v]
        if len(days) != len(set(days)):
            raise ValueError("aynı gün birden fazla kez verilemez")
        if not any(p.role == PatternRole.OUTCOME for p in v):
            raise ValueError("en az bir OUTCOME günü gerekli")
        order = list(Weekday)
        return sorted(v, key=lambda p: order.index(p.weekday))

    @model_validator(mode="after")
    def _periods(self):
        _check_range(self.in_sample_start, self.in_sample_end)
        _check_range(self.out_of_sample_start, self.out_of_sample_end)
        if self.in_sample_end >= self.out_of_sample_start:
            raise ValueError("örneklem içi örneklem dışından ÖNCE bitmeli (çakışma yok)")
        return self


# 8 ---------------------------------------------------------------------
class GetFundamentalMetricsParams(ToolParams):
    ticker: Ticker
    period: FiscalPeriod | None = Field(default=None, description="None = as_of'a kadar açıklanan en son dönem")


# 9 ---------------------------------------------------------------------
class CalculateFundamentalChangeParams(ToolParams):
    ticker: Ticker
    periods: list[FiscalPeriod] | None = Field(default=None, description="None = as_of'a kadar açıklanan tüm dönemler")
    metrics: list[FundamentalMetricName] | None = Field(default=None, description="None = sektöre uygun varsayılan set")
    reaction_horizons: list[Horizon] = Field(default_factory=lambda: [1, 5, 20])
    improvement_metric: FundamentalMetricName = FundamentalMetricName.EBITDA_MARGIN
    improvement_basis: ChangeBasis = ChangeBasis.YOY

    @field_validator("reaction_horizons")
    @classmethod
    def _h(cls, v: list[int]) -> list[int]:
        return _norm_horizons(v)

    @field_validator("periods")
    @classmethod
    def _p(cls, v):
        return None if v is None else sorted(set(v))

    @field_validator("metrics")
    @classmethod
    def _m(cls, v):
        return None if v is None else sorted(set(v), key=lambda x: x.value)


# 10 --------------------------------------------------------------------
class GetMacroContextParams(ToolParams):
    start: date
    end: date
    series: list[MacroSeries] = Field(default_factory=lambda: list(MacroSeries))

    @field_validator("series")
    @classmethod
    def _s(cls, v: list[MacroSeries]) -> list[MacroSeries]:
        if not v:
            raise ValueError("series boş olamaz")
        return sorted(set(v), key=lambda x: x.value)

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 11 --------------------------------------------------------------------
class GetNewsEventsParams(ToolParams):
    ticker: Ticker | None = None
    topic: str | None = Field(default=None, min_length=2, max_length=80)
    start: date
    end: date

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        if self.ticker is None and self.topic is None:
            raise ValueError("ticker veya topic en az biri verilmeli")
        return self


# 12 --------------------------------------------------------------------
class GetSpeechFeaturesParams(ToolParams):
    source_id: str = Field(min_length=1, max_length=120, description="Hoca onaylı kaynak listesindeki video/segment kimliği")


# 13 --------------------------------------------------------------------
class StrategySpec(CostParams):
    variant: StrategyVariant
    signal_type: SignalType
    signal_params: dict[str, Any] = Field(default_factory=dict)
    holding_days: int = Field(default=5, ge=1, le=120)
    signal_lag_days: int = Field(
        default=1, ge=1, description="Sinyal t'de üretilir, işlem EN GEÇ t+1'de (signal shifting). 0 yasak."
    )
    benchmarks: list[BenchmarkName] = Field(default_factory=lambda: [BenchmarkName.BUY_AND_HOLD, BenchmarkName.XU100])
    train_end: date | None = None
    validation_end: date | None = None
    walk_forward: bool = False

    @field_validator("benchmarks")
    @classmethod
    def _b(cls, v: list[BenchmarkName]) -> list[BenchmarkName]:
        if not v:
            raise ValueError("en az bir benchmark gerekli")
        return sorted(set(v), key=lambda x: x.value)

    @model_validator(mode="after")
    def _splits(self):
        if self.validation_end is not None and (self.train_end is None or self.validation_end <= self.train_end):
            raise ValueError("validation_end için train_end gerekli ve ondan sonra olmalı")
        return self


class RunBacktestParams(ToolParams):
    strategy: StrategySpec
    universe: list[Ticker] = Field(min_length=1, max_length=30)
    start: date
    end: date

    @field_validator("universe")
    @classmethod
    def _u(cls, v: list[str]) -> list[str]:
        return sorted(set(v))

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 14 --------------------------------------------------------------------
class BundleItem(Strict):
    """Harness'ın doldurduğu özet: bir araç çağrısının künyesi (tam çıktı değil)."""

    tool: ToolName
    as_of: date
    data_version: DataVersion
    input_hash: InputHash
    n_events: int | None = None
    n_excluded_incomplete_horizon: int | None = None
    # 1.2.0: kalite kapısı için (None = künyede yok; "geçti" sayılmaz, kapı çalışmadı der). `ge=1` KASITLI YOK:
    # kapı 0'ı görüp HARD verebilsin (StrategySpec/RunBacktestResult içindeki ge=1 kalır).
    signal_lag_days_applied: int | None = Field(default=None, description="Yalnız run_backtest: uygulanan sinyal gecikmesi (RunBacktestResult.signal_lag_days_applied)")
    max_result_date: date | None = Field(default=None, description="Aracın sonuçlarındaki en geç tarih (schemas.registry.max_result_date); as_of'u aşıyorsa kapı HARD verir")


class CheckDataQualityParams(ToolParams):
    tickers: list[Ticker] = Field(min_length=1, max_length=30)
    include_index: bool = True
    start: date = ANALYSIS_START_DEFAULT
    end: date
    checks: list[DQCheck] | None = Field(default=None, description="None = tüm kontroller")
    price_jump_limit_pct: float = Field(default=PRICE_JUMP_LIMIT_PCT, gt=0)
    analysis_bundle: list[BundleItem] = Field(default_factory=list)

    @field_validator("tickers")
    @classmethod
    def _t(cls, v: list[str]) -> list[str]:
        return sorted(set(v))

    @field_validator("checks")
    @classmethod
    def _c(cls, v):
        return None if v is None else sorted(set(v), key=lambda x: x.value)

    @model_validator(mode="after")
    def _r(self):
        _check_range(self.start, self.end)
        return self


# 15 --------------------------------------------------------------------
class BuildEvidenceBundleParams(ToolParams):
    analysis_id: str = Field(min_length=1, max_length=80)
    source_input_hashes: list[InputHash] = Field(min_length=1, description="Kanıtın dayandığı araç çıktılarının input_hash'leri")

    @field_validator("source_input_hashes")
    @classmethod
    def _h(cls, v: list[str]) -> list[str]:
        return sorted(set(v))
