"""MODELE görünen araç tanımları: kısa description + sadeleştirilmiş input_schema, gelişmiş parametreler gizli.

Bağlam hedefi ≤ 8192 token (docs/harness_design.md 13.2). Tam pydantic şeması (`schemas/`) DOĞRULAMA için aynen kalır:
  * gizli parametreler çağrıda yoksa varsayılanlarıyla dolar (varsayılan = örneklerin/eğitim verisinin değeri; testle denetlenir);
  * model yine de gizli bir parametre gönderirse tam şema doğrular (kısıt yok), yalnızca ona bu görünümde yer verilmez.
Sadeleştirme: $ref satır içine açılır, başlık/uzun açıklama/desen/min-maks atılır (kısıtları doğrulama zaten uygular ve hata mesajıyla geri bildirir),
`null` dalı atılır, `format: date` ve enum'lar kalır. Yalnızca OOS başlangıcı, analiz tarihi ve çoklu test sayısı gibi kritik alanlara kısa not konur.
MCP sunucusu (`mcp_server.py`) ve orkestratör (`agent_loop.py`) AYNI görünümü kullanır.
"""
from __future__ import annotations

import json
import math
from typing import Any, Sequence

from schemas.enums import ToolName as T
from schemas.registry import TOOL_REGISTRY

# 13 araç (D/E görünümü) için üst sınır; ölçüm: tests/harness/test_tool_view.py (karakter/3 tahmini)
TOOL_SPEC_CHAR_BUDGET = 8700   # ölçülen: 8504 (13 araç); sadeleştirmesiz 23739
CONTEXT_TARGET_TOKENS = 6000   # hedef bağlam (Gemma 3 4B, T4; sahibin kararı); ölçüm şimdilik karakter/3, sonra prompt_eval_count
CHARS_PER_TOKEN = 3        # Türkçe/JSON için kaba tahmin; Ollama kurulunca prompt_eval_count ile DEĞİŞTİRİLİR

TOOL_DESCRIPTIONS: dict[T, str] = {
    T.GET_STOCK_HISTORY: "OHLCV history for one BIST ticker.",
    T.GET_INDEX_HISTORY: "Benchmark index (XU100) history.",
    T.CALCULATE_INDICATORS: "Indicator values and states (RSI, BOLLINGER, SUPERTREND, ICHIMOKU...) for a ticker.",
    T.DETECT_REVERSAL_EVENTS: "Technical reversal events (e.g. lower Bollinger touch) with forward-return stats.",
    T.FIND_SUPPORT_RESISTANCE: "Support/resistance levels for a ticker.",
    T.RANK_SECTOR_RELATIVE_STRENGTH: "Peer-group lag ranking and historical catch-up stats for a sector.",
    T.TEST_WEEKDAY_PATTERN: "Weekday pattern test, in-sample vs out-of-sample.",
    T.GET_FUNDAMENTAL_METRICS: "Point-in-time financial metrics.",
    T.CALCULATE_FUNDAMENTAL_CHANGE: "Quarterly metric changes and post-disclosure price reaction.",
    T.GET_MACRO_CONTEXT: "FX, rates and inflation series.",
    T.GET_NEWS_EVENTS: "Timestamped news/KAP events.",
    T.GET_SPEECH_FEATURES: "Transcript-derived features.",
    T.RUN_BACKTEST: "Historical backtest of a strategy on a universe.",
    T.CHECK_DATA_QUALITY: "Data quality checks and the risk gate.",
    T.BUILD_EVIDENCE_BUNDLE: "Evidence sets for an analysis.",
}

# Modele GÖSTERİLMEYEN parametreler (noktalı yol). Hepsi isteğe bağlıdır ve varsayılanı örneklerle aynıdır (testle denetlenir).
HIDDEN_PARAMS: dict[T, tuple[str, ...]] = {
    T.GET_STOCK_HISTORY: ("price_adjustment",),
    T.CALCULATE_INDICATORS: ("config", "price_adjustment", "include_columns_meta", "start"),
    T.DETECT_REVERSAL_EVENTS: ("transaction_cost_bps", "slippage_bps", "indicator_config", "analysis_start", "forward_horizons", "touch_mode"),
    T.FIND_SUPPORT_RESISTANCE: ("tolerance_pct", "min_touches", "pivot_window"),
    T.RANK_SECTOR_RELATIVE_STRENGTH: ("forward_horizons", "lag_threshold_pp", "analysis_start"),
    T.TEST_WEEKDAY_PATTERN: ("transaction_cost_bps", "slippage_bps", "alpha", "conditioning"),
    T.CALCULATE_FUNDAMENTAL_CHANGE: ("periods", "metrics", "reaction_horizons"),
    T.RUN_BACKTEST: ("strategy.transaction_cost_bps", "strategy.slippage_bps", "strategy.signal_lag_days",
                     "strategy.benchmarks", "strategy.validation_end", "strategy.walk_forward"),
    T.CHECK_DATA_QUALITY: ("include_index", "checks", "price_jump_limit_pct", "analysis_bundle"),
}

# Parametre adına göre kısa notlar (kritik kurallar; ayrıntı system prompt'ta ve docs/tool_usage_guide.md'de)
_OOS = "out-of-sample start: Jan 1 of the as_of year, or as stated in the question"
PARAM_NOTES: dict[str, str] = {
    "as_of": "analysis date",
    "split_date": _OOS,
    "out_of_sample_start": _OOS,
    "train_end": "day before the out-of-sample start",
    "n_tests_declared": "patterns/conditions tried in total",
    "signal_params": 'REVERSAL: {"event_family": "BB_LOWER_TOUCH"|"RSI_LOCAL_TROUGH"}; WEEKDAY: {"pattern": [...]}; CATCH_UP: {}',
}

_KEEP_SCALAR_DEFAULT = (bool, int, float, str)


def _deref(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """$ref'i aç; anyOf [X, null] -> X (isteğe bağlılık zaten `required` dışı kalmasından anlaşılır)."""
    while True:
        if "$ref" in node:
            target = defs[node["$ref"].split("/")[-1]]
            node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
            continue
        if "anyOf" in node:
            branches = [b for b in node["anyOf"] if b.get("type") != "null"]
            if len(branches) == 1:
                node = {**{k: v for k, v in node.items() if k != "anyOf"}, **branches[0]}
                continue
        return node


def _compact(node: dict[str, Any], defs: dict[str, Any], hide: set[str], prefix: str) -> dict[str, Any]:
    node = _deref(node, defs)
    out: dict[str, Any] = {}
    if "enum" in node:
        out["enum"] = node["enum"]
    if node.get("type") is not None:
        out["type"] = node["type"]
    if node.get("format") == "date":
        out["format"] = "date"
    default = node.get("default")
    if isinstance(default, _KEEP_SCALAR_DEFAULT) and not isinstance(node.get("default"), dict):
        out["default"] = default
    if "items" in node:
        out["items"] = _compact(node["items"], defs, hide, prefix)
    props = node.get("properties")
    if props:
        shown = {}
        for name, sub in props.items():
            path = f"{prefix}{name}"
            if path in hide:
                continue
            c = _compact(sub, defs, hide, path + ".")
            note = PARAM_NOTES.get(name)
            if note:
                c["description"] = note
            shown[name] = c
        out["properties"] = shown
        req = [r for r in node.get("required", []) if r in shown]
        if req:
            out["required"] = req
    return out


def compact_schema(tool: T) -> dict[str, Any]:
    """Aracın modele görünen (sadeleştirilmiş, gizlemeli) `input_schema`'sı."""
    full = TOOL_REGISTRY[tool].params_model.model_json_schema()
    view = _compact(full, full.get("$defs", {}), set(HIDDEN_PARAMS.get(tool, ())), "")
    view["type"] = "object"
    return view


def model_tool_specs(visible: Sequence[T]) -> list[dict[str, Any]]:
    """Profilin modele gösterdiği araçlar: [{"name", "description", "parameters"}] (MCP'den bağımsız yalın biçim)."""
    return [{"name": spec.name.value, "description": TOOL_DESCRIPTIONS[spec.name], "parameters": compact_schema(spec.name)}
            for spec in TOOL_REGISTRY.values() if spec.name in visible]


def estimate_tokens(*, messages: Sequence[dict[str, Any]] | None = None, tools: Sequence[dict[str, Any]] | None = None,
                    chars: int | None = None) -> int:
    """Karakter/3 tahmini (Ollama kurulana kadar). `prompt_eval_count` gelince gerçek değer bu tahminin yerine konur."""
    if chars is None:
        chars = len(json.dumps(list(messages or []), ensure_ascii=False)) + (len(json.dumps(list(tools), ensure_ascii=False)) if tools else 0)
    return math.ceil(chars / CHARS_PER_TOKEN)
