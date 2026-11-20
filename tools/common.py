"""Araçların ortak altyapısı: as_of kesme, input_hash, snapshot okuma, zarf kurma.

Bu modül AĞ KULLANMAZ (CLAUDE.md kural 3); yalnızca data/snapshots altındaki dosyaları okur.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from pydantic import BaseModel, ValidationError

from config.settings import SNAPSHOT_DIR, TRADING_DAY_MIN_STOCK_SHARE
from schemas.common import SCHEMA_VERSION
from schemas.enums import ToolName, ToolStatus
from schemas.hashing import compute_input_hash
from schemas.registry import TOOL_REGISTRY


class InvalidToolCall(Exception):
    """`as_of` yok/bozuk: zarf (as_of zorunlu) kurulamaz. Harness bunu 'geçersiz araç çağrısı' sayar."""


class LookAheadError(Exception):
    """as_of sonrası veri tespit edildi (sızıntı)."""


class ToolFailure(Exception):
    """Araç mantığı kontrollü hata bildirir -> zarf status=ERROR, error={code, message}."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


@dataclass
class ToolOutput:
    results: BaseModel
    n_events: int | None = None
    n_excluded_incomplete_horizon: int = 0
    warnings: list[str] = field(default_factory=list)


# --- as_of ---------------------------------------------------------------------------------------
def _as_date(as_of: Any) -> date:
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    raise TypeError(f"as_of datetime.date olmalı, alındı: {type(as_of).__name__}")


def enforce_as_of(df: pd.DataFrame, as_of: date, date_col: str = "date") -> pd.DataFrame:
    """`date_col <= as_of` (as_of DAHİL) olan satırları döndürür; girdiyi DEĞİŞTİRMEZ (kopya).

    CLAUDE.md kural 1: as_of sonrası hiçbir satır araca giremez. Her araç, veriye dokunmadan önce
    bunu çağırır. Çıktıda sızıntı kalmadığı ayrıca doğrulanır (savunma amaçlı).
    """
    cutoff = pd.Timestamp(_as_date(as_of))
    if date_col not in df.columns:
        raise KeyError(f"'{date_col}' sütunu yok")
    out = df.loc[df[date_col] <= cutoff].copy()
    if len(out) and out[date_col].max() > cutoff:  # pragma: no cover - olmamalı
        raise LookAheadError(f"{out[date_col].max()} > as_of {cutoff.date()}")
    return out


# --- hash ----------------------------------------------------------------------------------------
def input_hash(tool: str | ToolName, params: dict[str, Any], data_version: str) -> str:
    """sha256(kanonik JSON {tool, params, data_version}); tanım schemas/hashing.py'de."""
    return compute_input_hash(str(getattr(tool, "value", tool)), params, data_version)


# --- snapshot ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Snapshot:
    data_version: str
    root: Path
    stocks: pd.DataFrame
    index: pd.DataFrame
    manifest: dict[str, Any]


def resolve_data_version(root: Path | None = None) -> str:
    """Öncelik: SNAPSHOT_VERSION ortam değişkeni, sonra <root>/LATEST dosyası."""
    env = os.environ.get("SNAPSHOT_VERSION")
    if env:
        return env.strip()
    latest = Path(root or SNAPSHOT_DIR) / "LATEST"
    if not latest.exists():
        raise FileNotFoundError(f"{latest} yok: önce `python -m scripts.download_prices` çalıştırın")
    return latest.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=4)
def _load(root: str, data_version: str) -> Snapshot:
    d = Path(root) / data_version
    if not d.is_dir():
        raise FileNotFoundError(f"snapshot yok: {d}")
    stocks = pd.read_parquet(d / "stocks.parquet")
    index = pd.read_parquet(d / "index.parquet")
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return Snapshot(data_version, Path(root), stocks, index, manifest)


_CALENDARS: dict[tuple[str, str], pd.DatetimeIndex] = {}


def trading_calendar(snap: Snapshot) -> pd.DatetimeIndex:
    """Birleşik işlem takvimi: XU100'de VEYA hisselerin >= TRADING_DAY_MIN_STOCK_SHARE'inde veri olan günler.

    Neden birleşik: Yahoo'da XU100 her 25 Aralık'ta (BIST açıkken) satır üretmiyor; 2024-04-09'da ise
    21 hissede satır yok. Tek kaynağa bağlı takvim yanlış 'eksik gün' üretirdi. Bir günün takvimde olması
    yalnızca O GÜNÜN verisine bağlıdır; gelecek bilgi gerektirmez. Kullanırken as_of ile kesin.
    """
    key = (str(snap.root.resolve()), snap.data_version)
    if key not in _CALENDARS:
        n_stocks = max(int(snap.stocks["ticker"].nunique()), 1)
        counts = snap.stocks.groupby("date")["ticker"].nunique()
        by_stocks = counts[counts >= TRADING_DAY_MIN_STOCK_SHARE * n_stocks].index
        _CALENDARS[key] = pd.DatetimeIndex(sorted(set(snap.index["date"]) | set(by_stocks)))
    return _CALENDARS[key]


def load_snapshot(data_version: str | None = None, root: Path | None = None) -> Snapshot:
    """Snapshot'ı okur (önbellekli). DÖNEN TABLOLAR PAYLAŞIMLIDIR: değiştirmeyin; enforce_as_of kopya döndürür."""
    root = Path(root or SNAPSHOT_DIR)
    return _load(str(root.resolve()), data_version or resolve_data_version(root))


# --- zarf ----------------------------------------------------------------------------------------
def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def build_envelope(
    tool: ToolName, params: BaseModel, data_version: str, out: ToolOutput,
) -> dict[str, Any]:
    p = params.model_dump(mode="json")
    return {
        "tool": tool.value,
        "schema_version": SCHEMA_VERSION,
        "params": p,
        "as_of": p["as_of"],
        "data_version": data_version,
        "input_hash": input_hash(tool, p, data_version),
        "results": out.results.model_dump(mode="json"),
        "n_events": out.n_events,
        "n_excluded_incomplete_horizon": out.n_excluded_incomplete_horizon,
        "warnings": list(out.warnings),
        "status": ToolStatus.OK.value,
        "error": None,
    }


def error_envelope(
    tool: ToolName, params: dict[str, Any], as_of: date, data_version: str, code: str, message: str,
) -> dict[str, Any]:
    return {
        "tool": tool.value,
        "schema_version": SCHEMA_VERSION,
        "params": params,
        "as_of": as_of.isoformat(),
        "data_version": data_version,
        "input_hash": input_hash(tool, params, data_version),
        "results": None,
        "n_events": None,
        "n_excluded_incomplete_horizon": 0,
        "warnings": [],
        "status": ToolStatus.ERROR.value,
        "error": {"code": code, "message": message},
    }


def run_tool(
    tool: ToolName,
    raw_params: dict[str, Any],
    handler: Callable[[BaseModel, Snapshot], ToolOutput],
    *,
    snapshot_root: Path | None = None,
    data_version: str | None = None,
) -> dict[str, Any]:
    """Ortak çağrı sarmalayıcı: params doğrula -> snapshot yükle -> handler -> zarf.

    * as_of yok/bozuk -> InvalidToolCall (zarf kurulamaz).
    * Diğer parametre hataları -> status=ERROR, code=INVALID_PARAMS.
    * handler ToolFailure fırlatırsa -> status=ERROR, error=(code, message).
    """
    snap = load_snapshot(data_version, snapshot_root)
    spec = TOOL_REGISTRY[tool]
    try:
        params = spec.params_model.model_validate(raw_params)
    except ValidationError as e:
        try:
            as_of = date.fromisoformat(str(raw_params.get("as_of")))
        except (ValueError, TypeError):
            raise InvalidToolCall(f"{tool.value}: as_of eksik veya geçersiz ({raw_params.get('as_of')!r})") from e
        msg = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:5])
        return error_envelope(tool, _jsonable(raw_params), as_of, snap.data_version, "INVALID_PARAMS", msg)

    try:
        out = handler(params, snap)
    except ToolFailure as f:
        return error_envelope(tool, params.model_dump(mode="json"), params.as_of,  # type: ignore[attr-defined]
                              snap.data_version, f.code, f.message)
    return build_envelope(tool, params, snap.data_version, out)
