"""Araç adı -> (params modeli, results modeli) kaydı ve tam zarf doğrulaması."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterator

from pydantic import BaseModel

from schemas import params as P
from schemas import results as R
from schemas.envelope import ToolEnvelope
from schemas.enums import ToolName, ToolStatus


@dataclass(frozen=True)
class ToolSpec:
    name: ToolName
    params_model: type[BaseModel]
    result_model: type[BaseModel]
    strict_result: bool  # True: results alan listesi bağlayıcı ve ayrıntılı; False: hafif


TOOL_REGISTRY: dict[ToolName, ToolSpec] = {
    s.name: s
    for s in [
        ToolSpec(ToolName.GET_STOCK_HISTORY, P.GetStockHistoryParams, R.GetStockHistoryResult, True),
        ToolSpec(ToolName.GET_INDEX_HISTORY, P.GetIndexHistoryParams, R.GetIndexHistoryResult, True),
        ToolSpec(ToolName.CALCULATE_INDICATORS, P.CalculateIndicatorsParams, R.CalculateIndicatorsResult, True),
        ToolSpec(ToolName.DETECT_REVERSAL_EVENTS, P.DetectReversalEventsParams, R.DetectReversalEventsResult, True),
        ToolSpec(ToolName.FIND_SUPPORT_RESISTANCE, P.FindSupportResistanceParams, R.FindSupportResistanceResult, False),
        ToolSpec(ToolName.RANK_SECTOR_RELATIVE_STRENGTH, P.RankSectorRelativeStrengthParams, R.RankSectorRelativeStrengthResult, True),
        ToolSpec(ToolName.TEST_WEEKDAY_PATTERN, P.TestWeekdayPatternParams, R.TestWeekdayPatternResult, True),
        ToolSpec(ToolName.GET_FUNDAMENTAL_METRICS, P.GetFundamentalMetricsParams, R.GetFundamentalMetricsResult, False),
        ToolSpec(ToolName.CALCULATE_FUNDAMENTAL_CHANGE, P.CalculateFundamentalChangeParams, R.CalculateFundamentalChangeResult, True),
        ToolSpec(ToolName.GET_MACRO_CONTEXT, P.GetMacroContextParams, R.GetMacroContextResult, False),
        ToolSpec(ToolName.GET_NEWS_EVENTS, P.GetNewsEventsParams, R.GetNewsEventsResult, False),
        ToolSpec(ToolName.GET_SPEECH_FEATURES, P.GetSpeechFeaturesParams, R.GetSpeechFeaturesResult, False),
        ToolSpec(ToolName.RUN_BACKTEST, P.RunBacktestParams, R.RunBacktestResult, True),
        ToolSpec(ToolName.CHECK_DATA_QUALITY, P.CheckDataQualityParams, R.CheckDataQualityResult, True),
        ToolSpec(ToolName.BUILD_EVIDENCE_BUNDLE, P.BuildEvidenceBundleParams, R.BuildEvidenceBundleResult, False),
    ]
}


def validate_params(tool: ToolName | str, params: dict[str, Any]) -> BaseModel:
    return TOOL_REGISTRY[ToolName(tool)].params_model.model_validate(params)


def validate_envelope(data: dict[str, Any]) -> ToolEnvelope:
    """Zarfı, params'ı ve (status=OK ise) results'ı tipli olarak doğrular.

    Ek çapraz kontroller: zarf.as_of == params.as_of; tarih içeren sonuçlarda as_of sonrası yok
    (genel tarama: results içindeki 'date' tipli bilinen alanlar as_of'u aşamaz).
    """
    env = ToolEnvelope.model_validate(data)
    spec = TOOL_REGISTRY[env.tool]
    # INVALID_PARAMS hata zarfında params, şemaya uymayan ham girdidir; tipli doğrulama atlanır
    # (zarfın as_of'u yine geçerli bir tarih olmak zorundadır, ToolEnvelope bunu zaten denetler).
    if env.status == ToolStatus.ERROR and env.error is not None and env.error.code == "INVALID_PARAMS":
        return env
    p = spec.params_model.model_validate(env.params)
    if p.as_of != env.as_of:  # type: ignore[attr-defined]
        raise ValueError(f"zarf as_of ({env.as_of}) != params.as_of ({p.as_of})")  # type: ignore[attr-defined]
    if env.status == ToolStatus.OK:
        res = spec.result_model.model_validate(env.results)
        _assert_no_dates_after(res.model_dump(mode="json"), env.as_of)
        if _version(env.schema_version) >= (1, 2, 0):
            _require_since_1_2_0(env.tool, res)
    return env


def _version(v: str) -> tuple[int, int, int]:
    major, minor, patch = (int(x) for x in v.split("."))
    return major, minor, patch


def _require_since_1_2_0(tool: ToolName, res: BaseModel) -> None:
    """Sürüm koşullu zorunluluk (docs/schema_1_2_0_plan.md D1): 1.2.0 sonuç alanları modelde Optional'dır ki 1.1.0 zarfları
    geçerli kalsın; fakat `schema_version >= 1.2.0` damgalı bir zarfta araç bunları DOLDURMAK zorundadır.
    Tek hisseli rank grubu (`insufficient_peers`) tarihsel olay üretmediği için muaftır."""

    def need(field: str) -> None:
        if getattr(res, field) is None:
            raise ValueError(f"schema_version >= 1.2.0: {tool.value} sonucunda {field} None olamaz")

    if tool == ToolName.RANK_SECTOR_RELATIVE_STRENGTH:
        if not res.insufficient_peers:  # type: ignore[attr-defined]
            for f in ("n_raw_laggard_observations", "cooldown_days", "outcome_benchmark_definition"):
                need(f)
            if not res.per_ticker:  # type: ignore[attr-defined]
                raise ValueError("schema_version >= 1.2.0: rank_sector_relative_strength sonucunda per_ticker boş olamaz (>= 2 üyeli grup)")
    elif tool == ToolName.CALCULATE_INDICATORS:
        need("invalid_columns_at_as_of")
    elif tool == ToolName.CHECK_DATA_QUALITY:
        need("issue_counts")


# as_of sonrası olamayacak tarih alanları (anahtar adına göre). Gelecek tarih içerebilen alanlar
# (ör. requested_end, end) bilinçli olarak dahil DEĞİL.
_PAST_ONLY_KEYS = {
    "date", "last_date", "first_date", "effective_end", "window_end", "analysis_end", "disclosure_date",
    "publication_date", "observation_date", "published_date", "signal_date", "entry_date", "exit_date",
    "last_publication_date", "last_touch_date", "window_end_date", "max_abs_daily_return_date",
    "state_date", "history_first_date", "first_valid_date",  # calculate_indicators (1.1.0)
}


def _past_only_dates(obj: Any, path: str = "results") -> Iterator[tuple[str, date]]:
    """results ağacındaki geçmiş-only tarih alanlarını (yol, tarih) olarak üretir (`_PAST_ONLY_KEYS`; tek tanım)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _PAST_ONLY_KEYS and isinstance(v, (str, date)):
                try:
                    yield f"{path}.{k}", (v if isinstance(v, date) else date.fromisoformat(v))
                except ValueError:
                    continue
            else:
                yield from _past_only_dates(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _past_only_dates(v, f"{path}[{i}]")


def _assert_no_dates_after(obj: Any, as_of: date, path: str = "results") -> None:
    for where, d in _past_only_dates(obj, path):
        if d > as_of:
            raise ValueError(f"{where}={d.isoformat()} as_of ({as_of}) sonrasında (look-ahead)")


def max_result_date(results: Any) -> date | None:
    """Bir aracın `results`'ındaki EN GEÇ geçmiş-only tarih (yoksa None). Kalite kapısı `BundleItem.max_result_date` için kullanır
    (harness `bundle_items` bunu çağırır). Saf ve belirlenimcidir; tarama `_assert_no_dates_after` ile aynı anahtar tablosunu paylaşır.

    run_backtest için `trade_log` kısaltılsa bile en geç çıkışı korumak üzere `last_exit_date` alanı eklenecek (docs/schema_wishlist.md §7);
    anahtar tabloya girince bu fonksiyon onu otomatik kapsar.
    """
    return max((d for _, d in _past_only_dates(results)), default=None)
