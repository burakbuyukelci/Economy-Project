"""get_macro_context (MİNİMUM sürüm): seçili makro serilerin [start, end] aralığındaki noktaları. `relate_to` bu sürümde YOK.

Veri: data/snapshots/macro_<tarih>_v<N>/macro.parquet (scripts/download_macro.py, TCMB/EVDS). Ağ yok.
Hizalama YAYIN tarihine göredir (`publication_date <= as_of`); gözlem tarihi aralık filtresidir. Böylece ay sonu gözlemi (ör. Ağustos TÜFE)
TÜİK açıklamasına (izleyen ayın 3'ü) kadar görünmez. `end > as_of` ise as_of'a kesilir (AS_OF_CLAMPED). İstenen ama veri setinde olmayan seri
(ör. FED_*, kodu verilmemiş politika faizi) veya aralıkta noktası olmayan seri MACRO_DATA_MISSING uyarısı verir; hiçbiri yoksa NO_DATA.
Boşluk (gap): ardışık noktalar arası > eşik (günlük 7, aylık 40 takvim günü) ile aralık başı/sonu boşlukları.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config.settings import SNAPSHOT_DIR
from schemas.enums import MacroSeries, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import GetMacroContextParams
from schemas.results import GetMacroContextResult, MacroGap, MacroPoint, MacroSeriesData
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool

TOOL = ToolName.GET_MACRO_CONTEXT
GAP_DAYS = {"daily": 7, "monthly": 40}
ROUND = 6


@dataclass(frozen=True)
class MacroData:
    version: str
    table: pd.DataFrame
    manifest: dict


def resolve_macro_version(root: Path | None = None) -> str:
    env = os.environ.get("MACRO_VERSION")
    if env:
        return env.strip()
    latest = Path(root or SNAPSHOT_DIR) / "LATEST_MACRO"
    if not latest.exists():
        raise FileNotFoundError(f"{latest} yok")
    return latest.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=4)
def _load(root: str, version: str) -> MacroData:
    d = Path(root) / version
    t = pd.read_parquet(d / "macro.parquet")
    for c in ("observation_date", "publication_date"):
        t[c] = pd.to_datetime(t[c])
    return MacroData(version, t, json.loads((d / "manifest.json").read_text(encoding="utf-8")))


def load_macro(root: Path | None = None, version: str | None = None) -> MacroData:
    root = Path(root or SNAPSHOT_DIR)
    try:
        return _load(str(root.resolve()), version or resolve_macro_version(root))
    except FileNotFoundError as e:
        raise ToolFailure("NO_DATA", "makro veri seti yok (python -m scripts.download_macro)") from e


def _gaps(obs: list[date], start: date, end: date, freq: str) -> list[MacroGap]:
    lim = timedelta(days=GAP_DAYS[freq])
    edges = [start - timedelta(days=1), *obs, end + timedelta(days=1)]
    out = []
    for a, b in zip(edges, edges[1:]):
        if b - a > lim:
            out.append(MacroGap(start=a + timedelta(days=1), end=b - timedelta(days=1)))
    return out


def _handler(p: GetMacroContextParams, snap: Snapshot, macro_version: str | None = None) -> ToolOutput:
    m = load_macro(snap.root, macro_version)
    warnings: list[str] = []
    eff_end = min(p.end, p.as_of)
    if p.end > p.as_of:
        warnings.append(make_warning(WarningCode.AS_OF_CLAMPED, f"end={p.end.isoformat()} as_of={p.as_of.isoformat()} tarihine kesildi"))
    if p.start > eff_end:
        raise ToolFailure("NO_DATA", f"start={p.start} as_of={p.as_of} sonrası: aralık boş")
    vis = enforce_as_of(m.table, p.as_of, "publication_date")  # YAYIN tarihine göre kes (revizyon/gelecek açıklama girmez)
    out: list[MacroSeriesData] = []
    missing: list[str] = []
    for s in p.series:
        info = m.manifest.get("series", {}).get(s.value)
        sub = vis.loc[(vis["series"] == s.value) & (vis["observation_date"] >= pd.Timestamp(p.start))
                      & (vis["observation_date"] <= pd.Timestamp(eff_end))].sort_values("observation_date")
        if info is None or sub.empty:
            missing.append(s.value)
            continue
        obs = [x.date() for x in sub["observation_date"]]
        out.append(MacroSeriesData(
            series=s, source=str(info["source"]), frequency=str(info["frequency"]), n_points=len(sub),
            last_publication_date=sub["publication_date"].max().date(), gaps=_gaps(obs, p.start, eff_end, str(info["frequency"])),
            points=[MacroPoint(observation_date=o.date(), publication_date=q.date(), value=round(float(v), ROUND))
                    for o, q, v in zip(sub["observation_date"], sub["publication_date"], sub["value"])]))
    if not out:
        raise ToolFailure("NO_DATA", f"istenen serilerin hiçbiri için [{p.start}, {eff_end}] aralığında as_of={p.as_of} itibarıyla yayımlanmış veri yok")
    if missing:
        warnings.append(make_warning(WarningCode.MACRO_DATA_MISSING,
                                     f"veri setinde yok veya aralıkta/as_of'ta yayımlanmış nokta yok: {', '.join(missing)}"))
    warnings.append(make_warning(WarningCode.HISTORICAL_ONLY,
                                 f"makro veri seti {m.version}; kaynak TCMB/EVDS; yayın tarihi kurallı türetilmiştir (bkz. data_dictionary §22)"))
    return ToolOutput(results=GetMacroContextResult(start=p.start, end=eff_end, series=out), warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None,
           macro_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım (sözleşmenin parçası DEĞİL)."""
    return run_tool(TOOL, params, lambda p, s: _handler(p, s, macro_version),  # type: ignore[arg-type]
                    snapshot_root=snapshot_root, data_version=data_version)
