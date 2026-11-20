"""Harness ayarları (BİLGİSAYAR 2 bölgesi).

Mock/gerçek araç seçimi TEK yerden yapılır: `TOOL_BACKEND_OVERRIDES`.
Örnek: gerçek get_stock_history hazır olunca
    TOOL_BACKEND_OVERRIDES = {ToolName.GET_STOCK_HISTORY: "real"}
yazmak yeterlidir; diğer 14 araç mock kalır.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from schemas.enums import ToolName

# --- Araç arka ucu: "mock" | "real" -----------------------------------------
DEFAULT_TOOL_BACKEND = "mock"
TOOL_BACKEND_OVERRIDES: dict[ToolName, str] = {}
_VALID_BACKENDS = ("mock", "real")

# Gerçek araç sözleşmesi (BİLGİSAYAR 1 ile anlaşıldı): tools/<araç_adı>.py içinde run(params: dict) -> dict
REAL_TOOL_MODULE_TEMPLATE = "tools.{tool}"
REAL_TOOL_ENTRYPOINT = "run"


def backend_for(tool: ToolName) -> str:
    backend = TOOL_BACKEND_OVERRIDES.get(tool, DEFAULT_TOOL_BACKEND)
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"{tool.value}: bilinmeyen backend {backend!r}; geçerli: {_VALID_BACKENDS}")
    return backend


# --- Mock işareti -----------------------------------------------------------
# Mock zarfların data_version'ı bu sabittir (şema desenine uyar, gerçek snapshot ile karışmaz).
# Eğitim verisi üretimi `assert_not_mock()` ile bu işareti reddeder.
MOCK_DATA_VERSION = "snap_1900-01-01_v0"
# schemas/examples.py fixture'larındaki en geç tarih; as_of bundan öncesiyse mock ERROR döner.
MOCK_FIXTURE_LAST_DATE = date(2026, 9, 10)
MOCK_AS_OF_ERROR_CODE = "MOCK_FIXTURE_AFTER_AS_OF"  # ToolError.code serbest metindir, şema değişmedi

# --- Oturum / log -----------------------------------------------------------
# None ise olaylar yalnızca bellekte tutulur; yol verilirse her olay JSONL satırı olarak eklenir.
EVENT_LOG_PATH: Path | None = None
