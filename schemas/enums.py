"""Ortak enum'lar (SÖZLEŞME: insan onayı olmadan değiştirme)."""
from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.11 StrEnum'u yerine; JSON'da düz string olarak serileşir."""

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


# --- CLAUDE.md kural 5 ---------------------------------------------------
class AllowedAction(StrEnum):
    HOLD = "HOLD"
    WATCH = "WATCH"
    INVESTIGATE = "INVESTIGATE"
    POTENTIAL_CATCH_UP_CANDIDATE = "POTENTIAL_CATCH_UP_CANDIDATE"
    TECHNICAL_REVERSAL_CANDIDATE = "TECHNICAL_REVERSAL_CANDIDATE"
    FUNDAMENTAL_IMPROVEMENT_CANDIDATE = "FUNDAMENTAL_IMPROVEMENT_CANDIDATE"
    REJECT_SIGNAL = "REJECT_SIGNAL"
    ANALYSIS_UNSAFE = "ANALYSIS_UNSAFE"


class GateStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    INVESTIGATE = "INVESTIGATE"
    ANALYSIS_UNSAFE = "ANALYSIS_UNSAFE"
    HARD_BLOCK = "HARD_BLOCK"


class ToolStatus(StrEnum):
    OK = "OK"
    ERROR = "ERROR"


class ToolName(StrEnum):
    GET_STOCK_HISTORY = "get_stock_history"
    GET_INDEX_HISTORY = "get_index_history"
    CALCULATE_INDICATORS = "calculate_indicators"
    DETECT_REVERSAL_EVENTS = "detect_reversal_events"
    FIND_SUPPORT_RESISTANCE = "find_support_resistance"
    RANK_SECTOR_RELATIVE_STRENGTH = "rank_sector_relative_strength"
    TEST_WEEKDAY_PATTERN = "test_weekday_pattern"
    GET_FUNDAMENTAL_METRICS = "get_fundamental_metrics"
    CALCULATE_FUNDAMENTAL_CHANGE = "calculate_fundamental_change"
    GET_MACRO_CONTEXT = "get_macro_context"
    GET_NEWS_EVENTS = "get_news_events"
    GET_SPEECH_FEATURES = "get_speech_features"
    RUN_BACKTEST = "run_backtest"
    CHECK_DATA_QUALITY = "check_data_quality"
    BUILD_EVIDENCE_BUNDLE = "build_evidence_bundle"


class WarningCode(StrEnum):
    """`warnings` listesindeki her eleman "KOD: açıklama" biçimindedir; KOD bu enum'dan olmalı."""

    FEW_EVENTS = "FEW_EVENTS"                                  # n_events < MIN_EVENTS
    SMALL_PEER_GROUP = "SMALL_PEER_GROUP"                      # peer grubu çok küçük (2)
    SOLO_PEER_GROUP = "SOLO_PEER_GROUP"                        # peer_group_size == 1
    INCOMPLETE_HORIZON_EXCLUDED = "INCOMPLETE_HORIZON_EXCLUDED"  # kural 2
    AS_OF_CLAMPED = "AS_OF_CLAMPED"                            # end > as_of ise as_of'a kesildi
    MULTIPLE_TESTING_RISK = "MULTIPLE_TESTING_RISK"
    OOS_DEGRADATION = "OOS_DEGRADATION"                        # örneklem dışı bozulma
    MACRO_DATA_MISSING = "MACRO_DATA_MISSING"
    NEWS_COVERAGE_SPARSE = "NEWS_COVERAGE_SPARSE"
    TRANSCRIPT_LOW_QUALITY = "TRANSCRIPT_LOW_QUALITY"
    PRE_TMS29_NOT_COMPARABLE = "PRE_TMS29_NOT_COMPARABLE"
    BANK_METRIC_SET = "BANK_METRIC_SET"                        # banka: sanayi oranları kullanılmadı
    NOT_YET_DISCLOSED_EXCLUDED = "NOT_YET_DISCLOSED_EXCLUDED"  # disclosure_date > as_of
    PRICE_JUMP_OVER_LIMIT = "PRICE_JUMP_OVER_LIMIT"
    MISSING_TRADING_DAYS = "MISSING_TRADING_DAYS"
    LOW_SIGNAL_COUNT = "LOW_SIGNAL_COUNT"
    ASSOCIATION_NOT_CAUSATION = "ASSOCIATION_NOT_CAUSATION"
    HISTORICAL_ONLY = "HISTORICAL_ONLY"                        # geçmiş kanıt, gelecek garantisi değil
    COST_ASSUMPTIONS = "COST_ASSUMPTIONS"
    HOLIDAY_WEEKS_EXCLUDED = "HOLIDAY_WEEKS_EXCLUDED"
    UNSTABLE_PATTERN = "UNSTABLE_PATTERN"
    DATA_VERSION_MISMATCH = "DATA_VERSION_MISMATCH"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"


# --- Evren ---------------------------------------------------------------
class PeerGroup(StrEnum):
    """config/universe.csv `peer_group` kimlikleri (test: universe.csv ile birebir)."""

    RETAIL = "retail"
    AIRLINES = "airlines"
    TELECOM = "telecom"
    ELECTRIC_UTILITIES = "electric_utilities"
    STEEL = "steel"
    AUTOMOTIVE = "automotive"
    CHEMICALS = "chemicals"
    HEALTHCARE = "healthcare"
    ENERGY_PETROCHEM = "energy_petrochem"
    SOLO_ASELS = "solo_asels"
    SOLO_AKBNK = "solo_akbnk"
    SOLO_KCHOL = "solo_kchol"
    SOLO_CCOLA = "solo_ccola"
    SOLO_TRALT = "solo_tralt"
    SOLO_ENKAI = "solo_enkai"
    SOLO_EKGYO = "solo_ekgyo"
    SOLO_TURSG = "solo_tursg"
    SOLO_OYAKC = "solo_oyakc"
    SOLO_ISMEN = "solo_ismen"
    SOLO_ARCLK = "solo_arclk"


class IndexId(StrEnum):
    XU100 = "XU100"


class PriceAdjustment(StrEnum):
    ADJUSTED = "adjusted"      # varsayılan: Adj Close tabanlı
    UNADJUSTED = "unadjusted"


class MetricSet(StrEnum):
    INDUSTRIAL = "INDUSTRIAL"
    BANK = "BANK"


# --- Teknik analiz -------------------------------------------------------
class IndicatorName(StrEnum):
    SMA = "SMA"
    EMA = "EMA"
    KAMA = "KAMA"
    RSI = "RSI"
    MACD = "MACD"
    BOLLINGER = "BOLLINGER"
    ATR = "ATR"
    SUPERTREND = "SUPERTREND"
    ICHIMOKU = "ICHIMOKU"
    VOLUME_ZSCORE = "VOLUME_ZSCORE"


class EventFamily(StrEnum):
    BB_LOWER_TOUCH = "BB_LOWER_TOUCH"
    BB_MID_TEST = "BB_MID_TEST"
    BB_UPPER_TOUCH = "BB_UPPER_TOUCH"
    RSI_LOCAL_TROUGH = "RSI_LOCAL_TROUGH"
    RSI_LOCAL_PEAK = "RSI_LOCAL_PEAK"
    SUPERTREND_FLIP = "SUPERTREND_FLIP"
    KAMA_SLOPE_CHANGE = "KAMA_SLOPE_CHANGE"
    KAMA_PRICE_CROSS = "KAMA_PRICE_CROSS"
    ICHIMOKU_BREAKOUT = "ICHIMOKU_BREAKOUT"
    ICHIMOKU_REJECTION = "ICHIMOKU_REJECTION"
    ICHIMOKU_RETURN_INTO_CLOUD = "ICHIMOKU_RETURN_INTO_CLOUD"
    SR_TOUCH = "SR_TOUCH"


class TouchMode(StrEnum):
    """Bollinger bant teması tanımı (docs/data_dictionary.md "touch_mode")."""

    CLOSE = "close"  # alt: close <= alt bant; üst: close >= üst bant
    LOW = "low"      # alt: low <= alt bant;  üst: high >= üst bant


class Direction(StrEnum):
    UP = "UP"
    DOWN = "DOWN"


class RsiState(StrEnum):
    LOCAL_LOW = "LOCAL_LOW"
    LOCAL_HIGH = "LOCAL_HIGH"
    NEUTRAL = "NEUTRAL"


class SupertrendState(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class KamaSlope(StrEnum):
    RISING = "RISING"
    FLATTENING = "FLATTENING"
    FALLING = "FALLING"


class IchimokuState(StrEnum):
    ABOVE_CLOUD = "ABOVE_CLOUD"
    IN_CLOUD = "IN_CLOUD"
    BELOW_CLOUD = "BELOW_CLOUD"


class VolumeRegime(StrEnum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MarketRegime(StrEnum):
    XU100_UP = "XU100_UP"
    XU100_DOWN = "XU100_DOWN"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class LevelType(StrEnum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


# --- Sektör / haftanın günü ---------------------------------------------
class SectorStrength(StrEnum):
    STRONG = "STRONG"
    NEUTRAL = "NEUTRAL"
    WEAK = "WEAK"


class Weekday(StrEnum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"


class PatternRole(StrEnum):
    TRIGGER = "TRIGGER"  # örüntünün koşul günleri (ör. Pzt-Sal-Çar düşüş)
    OUTCOME = "OUTCOME"  # sonuç günleri (ör. Per-Cum yükseliş)


class Conditioning(StrEnum):
    NONE = "NONE"
    XU100_UP = "XU100_UP"      # haftalık XU100 getirisi > 0 olan haftalar
    XU100_DOWN = "XU100_DOWN"


class StabilityVerdict(StrEnum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# --- Temel analiz --------------------------------------------------------
class FundamentalMetricName(StrEnum):
    # Sanayi
    REVENUE = "REVENUE"
    EBITDA = "EBITDA"
    NET_PROFIT = "NET_PROFIT"
    EBITDA_MARGIN = "EBITDA_MARGIN"
    NET_PROFIT_MARGIN = "NET_PROFIT_MARGIN"
    ROE = "ROE"
    ROA = "ROA"
    NET_DEBT_EBITDA = "NET_DEBT_EBITDA"
    DEBT_EQUITY = "DEBT_EQUITY"
    CURRENT_RATIO = "CURRENT_RATIO"
    QUICK_RATIO = "QUICK_RATIO"
    PE = "PE"
    PB = "PB"
    EV_EBITDA = "EV_EBITDA"
    OPERATING_CASH_FLOW = "OPERATING_CASH_FLOW"
    CASH_CONVERSION = "CASH_CONVERSION"
    # Banka (sanayi oranları bankada kullanılmaz; hangi set hangi hisse için: araç belirler)
    NET_INTEREST_INCOME = "NET_INTEREST_INCOME"
    NET_INTEREST_MARGIN = "NET_INTEREST_MARGIN"
    COST_TO_INCOME = "COST_TO_INCOME"
    NPL_RATIO = "NPL_RATIO"
    CAPITAL_ADEQUACY = "CAPITAL_ADEQUACY"


class ChangeBasis(StrEnum):
    QOQ = "QOQ"
    YOY = "YOY"


class ChangeUnit(StrEnum):
    PCT = "PCT"  # göreli değişim, yüzde
    PP = "PP"    # oran/marj metrikleri için yüzde puan farkı
    ABS = "ABS"  # mutlak fark (ör. Net Borç/FAVÖK katsayısı)


class MetricDirection(StrEnum):
    IMPROVED = "IMPROVED"
    DETERIORATED = "DETERIORATED"
    FLAT = "FLAT"


class ReactionGroup(StrEnum):
    IMPROVED = "IMPROVED"
    NOT_IMPROVED = "NOT_IMPROVED"
    ALL = "ALL"


# --- Makro / haber / konuşma --------------------------------------------
class MacroSeries(StrEnum):
    USDTRY = "USDTRY"
    EURTRY = "EURTRY"
    TCMB_POLICY_RATE = "TCMB_POLICY_RATE"
    FED_FUNDS_UPPER = "FED_FUNDS_UPPER"
    FED_FUNDS_LOWER = "FED_FUNDS_LOWER"
    CPI_MONTHLY = "CPI_MONTHLY"
    CPI_ANNUAL = "CPI_ANNUAL"


class NewsCategory(StrEnum):
    EARNINGS = "EARNINGS"
    REGULATION = "REGULATION"
    FX = "FX"
    RATES = "RATES"
    COMMODITY_SHOCK = "COMMODITY_SHOCK"
    CONTRACT_AWARD = "CONTRACT_AWARD"
    GEOPOLITICAL_RISK = "GEOPOLITICAL_RISK"
    MATERIAL_EVENT = "MATERIAL_EVENT"
    OTHER = "OTHER"


class ClaimType(StrEnum):
    OPINION = "OPINION"
    CLAIM = "CLAIM"
    VERIFIED_FACT = "VERIFIED_FACT"


# --- Backtest / kalite ---------------------------------------------------
class StrategyVariant(StrEnum):
    A_TECHNICAL_ONLY = "A"
    B_TECHNICAL_SECTOR = "B"
    C_TECHNICAL_SECTOR_FUNDAMENTAL = "C"
    D_FULL_STRUCTURED = "D"
    E_FULL_CONTEXTUAL = "E"


class SignalType(StrEnum):
    CATCH_UP = "CATCH_UP"
    REVERSAL = "REVERSAL"
    WEEKDAY = "WEEKDAY"
    FUNDAMENTAL = "FUNDAMENTAL"


class BenchmarkName(StrEnum):
    BUY_AND_HOLD = "BUY_AND_HOLD"
    XU100 = "XU100"
    SECTOR = "SECTOR"


class SplitName(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"
    WALK_FORWARD = "WALK_FORWARD"


class DQCheck(StrEnum):
    PRICE_JUMPS = "PRICE_JUMPS"
    MISSING_DAYS = "MISSING_DAYS"
    STALENESS = "STALENESS"
    AS_OF_CONSISTENCY = "AS_OF_CONSISTENCY"
    DATA_VERSION_CONSISTENCY = "DATA_VERSION_CONSISTENCY"
    TICKER_IDENTITY = "TICKER_IDENTITY"
    FUNDAMENTAL_DISCLOSURE_ALIGNMENT = "FUNDAMENTAL_DISCLOSURE_ALIGNMENT"
    SIGNAL_SHIFT = "SIGNAL_SHIFT"
    EVENT_COUNT = "EVENT_COUNT"
    PEER_GROUP_SIZE = "PEER_GROUP_SIZE"
    MACRO_COVERAGE = "MACRO_COVERAGE"
    NEWS_COVERAGE = "NEWS_COVERAGE"
    TRANSCRIPT_QUALITY = "TRANSCRIPT_QUALITY"


class DQSeverity(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class DQCode(StrEnum):
    # Hard block (proje dokümanı §26)
    FUTURE_FUNDAMENTAL_LEAK = "FUTURE_FUNDAMENTAL_LEAK"
    LOOKAHEAD_SIGNAL = "LOOKAHEAD_SIGNAL"
    WRONG_TICKER_OR_BROKEN_HISTORY = "WRONG_TICKER_OR_BROKEN_HISTORY"
    PERIOD_MISMATCH = "PERIOD_MISMATCH"
    BACKTEST_FUTURE_INFO = "BACKTEST_FUTURE_INFO"
    AS_OF_VIOLATION = "AS_OF_VIOLATION"
    # Soft warning
    MACRO_GAP = "MACRO_GAP"
    NEWS_SPARSE = "NEWS_SPARSE"
    TRANSCRIPT_LOW_QUALITY = "TRANSCRIPT_LOW_QUALITY"
    FEW_EVENTS = "FEW_EVENTS"
    SMALL_PEER_GROUP = "SMALL_PEER_GROUP"
    PRICE_JUMP_OVER_LIMIT = "PRICE_JUMP_OVER_LIMIT"  # olası düzeltilmemiş bedelsiz/bölünme
    MISSING_TRADING_DAYS = "MISSING_TRADING_DAYS"
    STALE_DATA = "STALE_DATA"
    DATA_VERSION_MISMATCH = "DATA_VERSION_MISMATCH"
