"""Araç zarfı (CLAUDE.md "Araç sözleşmesi") + doğrulama."""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import Field, field_validator, model_validator

from schemas.common import SCHEMA_VERSION, DataVersion, InputHash, Strict
from schemas.enums import ToolName, ToolStatus, WarningCode

_WARNING_RE = re.compile(r"^([A-Z][A-Z0-9_]*): .+")


class ToolError(Strict):
    code: str = Field(min_length=1, description="ör. UNKNOWN_TICKER, NO_DATA, INVALID_PARAMS, INTERNAL")
    message: str = Field(min_length=1)


class ToolEnvelope(Strict):
    """Tüm araçlar bu zarfı döndürür.

    n_events: aracın ana olay/gözlem sayısı (reversal: koşulsuz grup n_events_detected; weekday:
      IS+OOS n_occurrences; backtest: n_signals; rank: en uzun ufuk için catch-up olay sayısı;
      fundamental: çeyrek sayısı). Anlamsızsa None.
    n_excluded_incomplete_horizon: EN UZUN ufuk için ufku as_of'u aşıp dışlanan olay sayısı;
      ufuk bazlı ayrıntı `results` içindedir.
    warnings: "KOD: açıklama"; KOD schemas.enums.WarningCode içinden.
    """

    tool: ToolName
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    params: dict[str, Any]
    as_of: date
    data_version: DataVersion
    input_hash: InputHash
    results: dict[str, Any] | None
    n_events: int | None = Field(default=None, ge=0)
    n_excluded_incomplete_horizon: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    status: ToolStatus
    error: ToolError | None = None

    @field_validator("warnings")
    @classmethod
    def _warnings(cls, v: list[str]) -> list[str]:
        for w in v:
            m = _WARNING_RE.match(w)
            if not m:
                raise ValueError(f"uyarı 'KOD: açıklama' biçiminde olmalı: {w!r}")
            if m.group(1) not in {c.value for c in WarningCode}:
                raise ValueError(f"bilinmeyen uyarı kodu: {m.group(1)}")
        return v

    @model_validator(mode="after")
    def _status_consistency(self):
        if self.status == ToolStatus.OK:
            if self.error is not None or self.results is None:
                raise ValueError("status=OK: results dolu, error None olmalı")
        else:
            if self.error is None:
                raise ValueError("status=ERROR: error dolu olmalı")
            if self.results is not None:
                raise ValueError("status=ERROR: results None olmalı")
        return self


def make_warning(code: WarningCode, message: str) -> str:
    return f"{code.value}: {message}"
