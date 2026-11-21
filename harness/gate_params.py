"""Harness'in çalıştırdığı check_data_quality için parametre türetme (saf fonksiyonlar).

Model kalite kapısını çağırmaz; harness, modelin ARAÇ ÇAĞRILARINDAN şu parametreleri türetir:
  tickers          : çağrılardaki `ticker` / `tickers` / `universe` birleşimi; `sector` ise peer grubunun üyeleri
                     (config/universe.csv). Hiçbiri yoksa SORU METNİNDEKİ hisse kodları (SELECT_UNIVERSE).
                     Yine belirsizse GateParamsError("TICKER_UNDETERMINED"): model çağrısı geçersiz sayılır.
  end              : oturum as_of'u (bayatlık/sızıntı kontrolü as_of'a göre yapılır)
  start            : ANALYSIS_START_DEFAULT ile çağrılardaki en erken start/analysis_start/in_sample_start'ın küçüğü
                     (pencere varsayılandan DAR olmaz; modelin kısa bir veri çağrısı kontrolü daraltmasın)
  analysis_bundle  : oturumdaki başarılı araç zarflarının künyesi (kalite kapısı ve kanıt paketi hariç)
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Sequence

from pydantic import ValidationError

from config.settings import ANALYSIS_START_DEFAULT
from config.universe import build_sector_peer_groups, load_universe
from harness.evidence import Record
from schemas.enums import ToolName as T
from schemas.registry import max_result_date, validate_params

_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")
_START_KEYS = ("start", "analysis_start", "in_sample_start")


class GateParamsError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def detect_question_tickers(question: str, universe: Iterable[str] | None = None) -> list[str]:
    """Soru metninde TAM kelime olarak geçen (büyük harf) evren hisse kodları, sıralı ve tekil."""
    codes = list(universe) if universe is not None else list(load_universe()["ticker"])
    return sorted(c for c in set(codes) if re.search(rf"(?<![A-Za-z0-9]){re.escape(c)}(?![A-Za-z0-9])", question))


def _valid(tickers: Iterable[Any]) -> list[str]:
    return [t for t in tickers if isinstance(t, str) and _TICKER_RE.match(t)]


def tickers_from_call(params: dict[str, Any], peer_groups: dict[str, list[str]]) -> list[str]:
    found: list[str] = []
    if isinstance(params.get("ticker"), str):
        found.append(params["ticker"])
    for key in ("tickers", "universe"):
        if isinstance(params.get(key), list):
            found.extend(params[key])
    sector = params.get("sector")
    if isinstance(sector, str):
        found.extend(peer_groups.get(sector, []))
    return _valid(found)


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def bundle_items(records: Sequence[Record]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for rec in records:
        env = rec.envelope
        if env.get("status") != "OK" or rec.tool in (T.CHECK_DATA_QUALITY, T.BUILD_EVIDENCE_BUNDLE):
            continue
        if env["input_hash"] in seen:
            continue
        seen.add(env["input_hash"])
        results = env.get("results") if isinstance(env.get("results"), dict) else {}
        # şema 1.2.0: kapının SIGNAL_SHIFT / LOOKAHEAD_SIGNAL / BACKTEST_FUTURE_INFO kontrolleri bu iki alana bakar; kopyalanmazsa "çalışmadı" derler
        lag = results.get("signal_lag_days_applied") if rec.tool == T.RUN_BACKTEST else None
        latest = max_result_date(results)
        items.append({"tool": env["tool"], "as_of": env["as_of"], "data_version": env["data_version"],
                      "input_hash": env["input_hash"], "n_events": env.get("n_events"),
                      "n_excluded_incomplete_horizon": env.get("n_excluded_incomplete_horizon"),
                      "signal_lag_days_applied": lag,
                      "max_result_date": latest.isoformat() if latest is not None else None})
    return items


def derive_gate_params(*, as_of: date, calls: Sequence[tuple[T, dict[str, Any]]],
                       question_tickers: Sequence[str], records: Sequence[Record],
                       peer_groups: dict[str, list[str]] | None = None) -> dict[str, Any]:
    peer_groups = peer_groups if peer_groups is not None else build_sector_peer_groups()
    tickers: set[str] = set()
    starts: list[date] = []
    for _, params in calls:
        tickers.update(tickers_from_call(params, peer_groups))
        for key in _START_KEYS:
            d = _as_date(params.get(key))
            if d is not None:
                starts.append(d)
    if not tickers:
        tickers.update(_valid(question_tickers))
    if not tickers:
        raise GateParamsError(
            "TICKER_UNDETERMINED",
            "kalite kapısı için hisse belirlenemedi: çağrınıza ticker/tickers/universe/sector ekleyin "
            "ya da soruda hisse kodunu belirtin")
    start = min([ANALYSIS_START_DEFAULT, *starts])
    params_out = {
        "as_of": as_of.isoformat(), "tickers": sorted(tickers), "include_index": True,
        "start": min(start, as_of).isoformat(), "end": as_of.isoformat(),
        "analysis_bundle": bundle_items(records),
    }
    try:
        validate_params(T.CHECK_DATA_QUALITY, params_out)
    except ValidationError as exc:
        raise GateParamsError("GATE_PARAMS_INVALID", str(exc.errors()[:3])) from exc
    return params_out
