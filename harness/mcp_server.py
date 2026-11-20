"""MCP sunucusu: HarnessSession'ın üstünde İNCE bir adaptör (mcp==2.3.0).

Bu dosyada hiçbir kural mantığı yok: araç listesi `schemas.registry.TOOL_REGISTRY`'den, çağrılar
`HarnessSession.call_tool`'a gider. SDK değişirse yalnızca bu dosya değişir.

Doğrulanan SDK API'si (mcp 2.3.0): `FastMCP` 2.x'te `MCPServer` olarak yeniden adlandırıldı. Araç şemasını
pydantic modellerinden vermek için düşük seviyeli `mcp.server.Server` (on_list_tools / on_call_tool) kullanıldı.

LLM'e yalnızca profilin gösterdiği ALAN araçları açılır (D/E'de 13: kalite kapısı ve kanıt paketi harness'indir).
Durum geçişi (advance_state) ve get_state AÇILMAZ: durumu harness yönetir.

Çalıştırma (stdio):
    python -m harness.mcp_server --question "Analiz tarihi: 10.09.2026 ... soru metni"
    python -m harness.mcp_server --question "..." --as-of 2026-09-10          # eval seti açıkça verir
    python -m harness.mcp_server --question "..." --default-as-of 2026-09-10  # yedek (AS_OF_ASSUMED uyarısı)
"""
from __future__ import annotations

import argparse
import json
from typing import Any

import anyio
import mcp_types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from harness import settings
from harness.as_of import parse_date
from harness.session import HarnessSession
from schemas.enums import ToolName
from schemas.registry import TOOL_REGISTRY

SERVER_NAME = "bist-harness"

# Kısa, İngilizce araç açıklamaları (proje dokümanı §22). as_of uyarısı her şemada tekrar edilir.
_AS_OF_NOTE = " `as_of` must equal the analysis date stated in the question."
TOOL_DESCRIPTIONS: dict[ToolName, str] = {
    ToolName.GET_STOCK_HISTORY: "OHLCV history and metadata for one BIST ticker.",
    ToolName.GET_INDEX_HISTORY: "Benchmark index (XU100) time series.",
    ToolName.CALCULATE_INDICATORS: "SMA/EMA/RSI/MACD/Bollinger/ATR/KAMA/Supertrend/Ichimoku for a ticker.",
    ToolName.DETECT_REVERSAL_EVENTS: "Timestamped technical reversal events with forward-return statistics.",
    ToolName.FIND_SUPPORT_RESISTANCE: "Support/resistance levels, zones, touch counts and strength.",
    ToolName.RANK_SECTOR_RELATIVE_STRENGTH: "Peer-group returns, lag score and rank for a sector and horizon.",
    ToolName.TEST_WEEKDAY_PATTERN: "Weekday pattern occurrences, conditional returns, in/out-of-sample stability.",
    ToolName.GET_FUNDAMENTAL_METRICS: "Point-in-time financial metrics aligned to the disclosure date.",
    ToolName.CALCULATE_FUNDAMENTAL_CHANGE: "Quarterly/annual metric changes and post-disclosure price reaction.",
    ToolName.GET_MACRO_CONTEXT: "FX, rates and inflation series with publication metadata.",
    ToolName.GET_NEWS_EVENTS: "Timestamped, legally accessible news/KAP event metadata.",
    ToolName.GET_SPEECH_FEATURES: "Timestamped transcript-derived topics, claims and stance.",
    ToolName.RUN_BACKTEST: "Historical verification of a strategy spec on a universe and period.",
    ToolName.CHECK_DATA_QUALITY: "Data quality / leakage checks and the risk-gate status.",
    ToolName.BUILD_EVIDENCE_BUNDLE: "Full and committed evidence sets for an analysis.",
}


def _tool_list(visible: list[ToolName]) -> list[types.Tool]:
    """Yalnızca oturum profilinin MODELE gösterdiği araçlar (harness-içi kapı araçları listelenmez)."""
    return [
        types.Tool(
            name=spec.name.value,
            description=TOOL_DESCRIPTIONS[spec.name] + _AS_OF_NOTE,
            input_schema=spec.params_model.model_json_schema(),
        )
        for spec in TOOL_REGISTRY.values()
        if spec.name in visible
    ]


def _text(payload: dict[str, Any]) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, sort_keys=True))]


def build_server(session: HarnessSession) -> Server[Any]:
    """Verilen oturumu, profilin görünür kıldığı araçlarla sunan MCP sunucusu kurar (bir bağlantı = bir oturum)."""
    tools = _tool_list(session.visible_tools)

    async def on_list_tools(ctx: ServerRequestContext[Any], params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: ServerRequestContext[Any], params: types.CallToolRequestParams) -> types.CallToolResult:
        result = session.call_tool(params.name, dict(params.arguments or {}))
        if result.ok:
            return types.CallToolResult(content=_text(result.envelope or {}), structured_content=result.envelope,
                                        is_error=False)
        return types.CallToolResult(content=_text(result.error or {}), structured_content=result.error, is_error=True)

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def serve_stdio(session: HarnessSession) -> None:
    server = build_server(session)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def session_from_args(argv: list[str] | None = None) -> HarnessSession:
    parser = argparse.ArgumentParser(description="BIST harness MCP sunucusu (stdio)")
    parser.add_argument("--question", required=True, help="Soru metni (ön metinde 'Analiz tarihi: GG.AA.YYYY' olmalı)")
    parser.add_argument("--as-of", help="Açık analiz tarihi (eval seti verir); sorudaki tarihle çelişemez")
    parser.add_argument("--default-as-of",
                        help=f"Soruda işaret yoksa yedek tarih (ya da {settings.DEFAULT_AS_OF_ENV} ortam değişkeni); AS_OF_ASSUMED uyarısı üretir")
    args = parser.parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.as_of:
        kwargs["explicit_as_of"] = parse_date(args.as_of)
    if args.default_as_of:
        kwargs["default_as_of"] = parse_date(args.default_as_of)
    return HarnessSession.from_question(args.question, **kwargs)


def main(argv: list[str] | None = None) -> None:
    anyio.run(serve_stdio, session_from_args(argv))


if __name__ == "__main__":
    main()
