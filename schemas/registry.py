"""Araç adı -> (params modeli, results modeli) kaydı ve tam zarf doğrulaması."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

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
        ToolSpec(ToolName.CALCULATE_INDICATORS, P.CalculateIndicatorsParams, R.CalculateIndicatorsResult, False),
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
    return env


# as_of sonrası olamayacak tarih alanları (anahtar adına göre). Gelecek tarih içerebilen alanlar
# (ör. requested_end, end) bilinçli olarak dahil DEĞİL.
_PAST_ONLY_KEYS = {
    "date", "last_date", "first_date", "effective_end", "window_end", "analysis_end", "disclosure_date",
    "publication_date", "observation_date", "published_date", "signal_date", "entry_date", "exit_date",
    "last_publication_date", "last_touch_date", "window_end_date", "max_abs_daily_return_date",
}


def _assert_no_dates_after(obj: Any, as_of: date, path: str = "results") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _PAST_ONLY_KEYS and isinstance(v, str):
                try:
                    d = date.fromisoformat(v)
                except ValueError:
                    continue
                if d > as_of:
                    raise ValueError(f"{path}.{k}={v} as_of ({as_of}) sonrasında (look-ahead)")
            else:
                _assert_no_dates_after(v, as_of, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_dates_after(v, as_of, f"{path}[{i}]")
