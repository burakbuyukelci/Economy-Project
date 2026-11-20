"""Ortak tipler ve yapı taşları (SÖZLEŞME).

Birim kuralları (sayı doğrulayıcı için önemli):
  * Yüzde değerli her alanın adı `_pct` (veya fark için `_pp`) ile biter ve 0-100 ölçeğindedir
    (ör. 12.5 = %12,5). Oranlar da (hit_rate_pct, occurrence_rate_pct) aynı ölçekte yüzdedir.
  * Tarihler saat dilimsiz düz tarihtir (YYYY-MM-DD). `as_of` DAHİLDİR: date <= as_of.
  * Tanımsız istatistikler (n=0) `None` döner; 0 yazılmaz.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from config.settings import SLIPPAGE_BPS_PER_SIDE, TRANSACTION_COST_BPS_PER_SIDE

SCHEMA_VERSION = "1.0.0"

# Ticker burada enum DEĞİL: bilinmeyen ticker -> araç status=ERROR döner (şema hatası değil).
Ticker = Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{3,6}$")]
FiscalPeriod = Annotated[str, StringConstraints(pattern=r"^\d{4}Q[1-4]$")]
DataVersion = Annotated[str, StringConstraints(pattern=r"^snap_\d{4}-\d{2}-\d{2}_v\d+$")]
InputHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Horizon = Annotated[int, Field(ge=1, le=120)]


class Strict(BaseModel):
    """Tüm sözleşme modellerinin tabanı: bilinmeyen alan yasak."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class ToolParams(Strict):
    """Tüm araç parametrelerinin tabanı. `as_of` ZORUNLUDUR (CLAUDE.md kural 1)."""

    as_of: date = Field(description="Analiz tarihi, dahil. Bu tarihten sonraki hiçbir veri kullanılamaz.")


def sorted_unique(values: list[int]) -> list[int]:
    """Liste parametrelerini normalize eder: aynı küme -> aynı input_hash."""
    return sorted(set(values))


# --- Maliyet modeli ------------------------------------------------------
class CostModel(Strict):
    """Bir tur (alım + satım) maliyeti = 2 * (transaction_cost + slippage), docs/data_dictionary.md."""

    transaction_cost_bps_per_side: float = Field(ge=0)
    slippage_bps_per_side: float = Field(ge=0)
    round_trip_cost_pct: float = Field(ge=0, description="2*(tc+slip)/100, yüzde puan")

    @model_validator(mode="after")
    def _check_round_trip(self) -> "CostModel":
        expected = 2 * (self.transaction_cost_bps_per_side + self.slippage_bps_per_side) / 100
        if abs(expected - self.round_trip_cost_pct) > 1e-9:
            raise ValueError(f"round_trip_cost_pct {self.round_trip_cost_pct} != beklenen {expected}")
        return self


def make_cost_model(
    transaction_cost_bps: float = TRANSACTION_COST_BPS_PER_SIDE,
    slippage_bps: float = SLIPPAGE_BPS_PER_SIDE,
) -> CostModel:
    return CostModel(
        transaction_cost_bps_per_side=transaction_cost_bps,
        slippage_bps_per_side=slippage_bps,
        round_trip_cost_pct=2 * (transaction_cost_bps + slippage_bps) / 100,
    )


class CostParams(Strict):
    """Maliyet parametreleri (bps, TEK YÖN). Tur maliyeti araç içinde 2x uygulanır."""

    transaction_cost_bps: float = Field(default=TRANSACTION_COST_BPS_PER_SIDE, ge=0, le=500)
    slippage_bps: float = Field(default=SLIPPAGE_BPS_PER_SIDE, ge=0, le=500)


# --- Çoklu test ----------------------------------------------------------
class MultipleTesting(Strict):
    n_tests_declared: int = Field(ge=1, description="Aynı veri üzerinde denenen toplam örüntü/koşul sayısı (çağıran beyan eder)")
    alpha: float = Field(gt=0, lt=1)
    adjusted_alpha: float = Field(gt=0, lt=1, description="Bonferroni: alpha / n_tests_declared")
    method: str = "bonferroni"
    note: str = "Çok sayıda kombinasyon denendiğinde tesadüfi örüntü bulma riski artar."


# --- Ufuk bazlı istatistikler (reversal, catch-up) -----------------------
class HorizonStats(Strict):
    """Tek ufuk, tek örneklem (tüm dönem / örneklem içi / örneklem dışı) için istatistik.

    Yalnızca ufku `as_of` içinde TAMAMLANMIŞ olaylar sayılır (kural 2); diğerleri
    `n_excluded_incomplete_horizon` içinde raporlanır.
    n_success + n_false_positive == n_events_complete. Başarı: getiri > 0 (yönlü olaylarda
    beklenen yönde). Eşitlik başarı sayılmaz.
    """

    n_events_complete: int = Field(ge=0)
    n_excluded_incomplete_horizon: int = Field(ge=0)
    n_success: int = Field(ge=0)
    n_false_positive: int = Field(ge=0)
    hit_rate_pct: float | None = Field(default=None, ge=0, le=100)
    false_positive_rate_pct: float | None = Field(default=None, ge=0, le=100)
    mean_return_pct: float | None = None
    median_return_pct: float | None = None
    cost_adjusted_mean_return_pct: float | None = Field(
        default=None, description="mean_return_pct - CostModel.round_trip_cost_pct"
    )
    mean_reversal_strength_pct: float | None = Field(default=None, description="Yalnız reversal: ufuk içi MFE ortalaması")
    median_reversal_strength_pct: float | None = None

    @model_validator(mode="after")
    def _counts(self) -> "HorizonStats":
        if self.n_success + self.n_false_positive != self.n_events_complete:
            raise ValueError("n_success + n_false_positive != n_events_complete")
        return self


class BaselineStats(Strict):
    """Koşulsuz karşılaştırma: aynı dönem, aynı ufuk, tüm uygun günler."""

    n_obs: int = Field(ge=0)
    mean_return_pct: float | None = None
    median_return_pct: float | None = None
    hit_rate_pct: float | None = Field(default=None, ge=0, le=100)


class HorizonBlock(Strict):
    horizon: Horizon
    full: HorizonStats
    in_sample: HorizonStats | None = None
    out_of_sample: HorizonStats | None = None
    baseline: BaselineStats
    mean_diff_vs_baseline_pct: float | None = None
    median_diff_vs_baseline_pct: float | None = None
    oos_degradation_flag: bool | None = Field(
        default=None, description="Örneklem dışı performans örneklem içinden belirgin kötüyse True"
    )


class SampleWindow(Strict):
    start: date
    end: date

    @model_validator(mode="after")
    def _order(self) -> "SampleWindow":
        if self.start > self.end:
            raise ValueError("start > end")
        return self


class BenchmarkDefinition(Strict):
    """Karşılaştırma ölçütünün açık tanımı (kanıt bütünlüğü için)."""

    type: str = Field(description="ör. 'peer_median'")
    includes_subject_stock: bool = Field(description="True: değerlendirilen hisse medyana DAHİL")
    price_field: str = Field(description="'adj_close' | 'close'")
    return_type: str = Field(description="'simple' (basit getiri)")
    peer_group: str | None = None
    members: list[str] = Field(default_factory=list)


