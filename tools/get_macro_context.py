"""get_macro_context (MİNİMUM sürüm): seçili makro serilerin [start, end] aralığındaki noktaları. `relate_to` bu sürümde YOK.

Veri: data/snapshots/macro_<tarih>_v<N>/macro.parquet (scripts/download_macro.py, TCMB/EVDS). Ağ yok.
Hizalama YAYIN tarihine göredir (`publication_date <= as_of`); gözlem tarihi aralık filtresidir. Böylece ay sonu gözlemi (ör. Ağustos TÜFE)
TÜİK açıklamasına (izleyen ayın 3'ü) kadar görünmez. `end > as_of` ise as_of'a kesilir (AS_OF_CLAMPED). İstenen ama veri setinde olmayan seri
(ör. FED_*, kodu verilmemiş politika faizi) veya aralıkta noktası olmayan seri MACRO_DATA_MISSING uyarısı verir; hiçbiri yoksa (ya da makro veri seti yoksa) zarf YİNE OK: series=[] + MACRO_DATA_MISSING; aralık as_of sonrasındaysa NO_DATA.
Boşluk (gap): ardışık noktalar arası > eşik (günlük 7, aylık 40 takvim günü) ile aralık başı/sonu boşlukları.

Günlük seriler (şema 1.4.0 davranışı): serinin ilk gözlemi ile `as_of`'a kesilmiş aralık sonu arasındaki her HAFTA İÇİ gün için
  * günde gözlem varsa aynen alınır;
  * yoksa ve gün işlem takviminde (`tools.common.trading_calendar`) YOKSA = resmî tatil: son gözlem İLERİ taşınır (geriye doldurma yok;
    taşınan noktanın yayın tarihi tatil günüdür; bilgi o gün zaten biliniyordu). Eksik veri sayılmaz;
  * yoksa ve gün işlem takviminde VARSA = tatil dışı boşluk: DOLDURULMAZ, `MACRO_DATA_MISSING` uyarısı (gün listesi) verilir.
Hafta sonları doldurulmaz. Aylık seriler asla doldurulmaz.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd

from config.settings import MIN_EVENTS, SNAPSHOT_DIR
from config.universe import load_universe
from schemas.common import MultipleTesting, make_cost_model
from schemas.enums import MacroSeries, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import GetMacroContextParams
from schemas.results import GetMacroContextResult, MacroGap, MacroPoint, MacroSeriesData
from tools.macro_relation import compute_relation, macro_value_on
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool, trading_calendar

TOOL = ToolName.GET_MACRO_CONTEXT
GAP_DAYS = {"daily": 7, "monthly": 40}
MONTHLY_SERIES = {MacroSeries.CPI_MONTHLY, MacroSeries.CPI_ANNUAL}
ROUND = 6
MISSING_LIST_LIMIT = 5   # uyarıda en çok bu kadar tatil dışı eksik gün yazılır (toplam sayı her zaman yazılır)


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


def fill_holidays(full: pd.DataFrame, end: date, trading_days: set[date], first_trading_day: date | None
                  ) -> tuple[pd.DataFrame, list[date], list[date]]:
    """Günlük seri için resmî tatil iş günlerini son gözlemle ileri doldurur (saf fonksiyon).

    `full`: observation_date/publication_date/value (sıralı, tümü <= end). Dönüş: (doldurulmuş tablo, taşınan tatil günleri, tatil dışı eksik günler).
    Kural: gün (hafta içi) `trading_days`'te yoksa VE `first_trading_day`'den önce değilse tatildir; takvimin başlamadığı günler sınıflanamaz -> eksik.
    """
    if full.empty:
        return full, [], []
    have = {t.date(): float(v) for t, v in zip(full["observation_date"], full["value"])}
    carried: list[date] = []
    missing: list[date] = []
    new_rows = []
    last = None
    for ts in pd.bdate_range(full["observation_date"].min(), pd.Timestamp(end)):
        d = ts.date()
        if d in have:
            last = have[d]
        elif last is None:
            continue
        elif first_trading_day is not None and d >= first_trading_day and d not in trading_days:
            carried.append(d)
            new_rows.append({"observation_date": ts, "publication_date": ts, "value": last})
        else:
            missing.append(d)
    if not new_rows:
        return full, carried, missing
    out = pd.concat([full[["observation_date", "publication_date", "value"]], pd.DataFrame(new_rows)], ignore_index=True)
    return out.sort_values("observation_date").reset_index(drop=True), carried, missing


def _handler(p: GetMacroContextParams, snap: Snapshot, macro_version: str | None = None) -> ToolOutput:
    warnings: list[str] = []
    try:
        m: MacroData | None = load_macro(snap.root, macro_version)
    except ToolFailure:
        m = None                     # makro veri seti yok: boş sonuç + MACRO_DATA_MISSING (aşağıda)
    eff_end = min(p.end, p.as_of)
    if p.end > p.as_of:
        warnings.append(make_warning(WarningCode.AS_OF_CLAMPED, f"end={p.end.isoformat()} as_of={p.as_of.isoformat()} tarihine kesildi"))
    if p.start > eff_end:
        raise ToolFailure("NO_DATA", f"start={p.start} as_of={p.as_of} sonrası: aralık boş")
    if m is None:
        warnings.append(make_warning(WarningCode.MACRO_DATA_MISSING,
                                     f"makro veri seti yok (data/snapshots/LATEST_MACRO; python -m scripts.download_macro); hiçbir seri döndürülmedi: "
                                     f"{', '.join(x.value for x in p.series)}"))
        return ToolOutput(results=GetMacroContextResult(start=p.start, end=eff_end, series=[]), warnings=warnings)
    vis = enforce_as_of(m.table, p.as_of, "publication_date")  # YAYIN tarihine göre kes (revizyon/gelecek açıklama girmez)
    cal = trading_calendar(snap)
    cal = cal[cal <= pd.Timestamp(p.as_of)]                       # takvim de as_of'a kesilir (kural 1)
    trading_days = {t.date() for t in cal}
    first_td = cal.min().date() if len(cal) else None
    out: list[MacroSeriesData] = []
    missing: list[str] = []
    gap_notes: list[str] = []
    carried_notes: list[str] = []
    for s in p.series:
        info = m.manifest.get("series", {}).get(s.value)
        full = vis.loc[(vis["series"] == s.value) & (vis["observation_date"] <= pd.Timestamp(eff_end)),
                       ["observation_date", "publication_date", "value"]].sort_values("observation_date").reset_index(drop=True)
        if info is not None and str(info["frequency"]) == "daily" and not full.empty:
            full, carried, gap_days = fill_holidays(full, eff_end, trading_days, first_td)
            in_range = lambda ds: [d for d in ds if p.start <= d <= eff_end]  # noqa: E731
            carried, gap_days = in_range(carried), in_range(gap_days)
            if carried:
                carried_notes.append(f"{s.value} {len(carried)} gün (ilk: {', '.join(d.isoformat() for d in carried[:MISSING_LIST_LIMIT])})")
            if gap_days:
                gap_notes.append(f"{s.value}: tatil dışı eksik iş günü {len(gap_days)} (ilk: {', '.join(d.isoformat() for d in gap_days[:MISSING_LIST_LIMIT])})")
        sub = full.loc[(full["observation_date"] >= pd.Timestamp(p.start)) & (full["observation_date"] <= pd.Timestamp(eff_end))]
        if info is None or sub.empty:
            missing.append(s.value)
            continue
        obs = [x.date() for x in sub["observation_date"]]
        out.append(MacroSeriesData(
            series=s, source=str(info["source"]), frequency=str(info["frequency"]), n_points=len(sub),
            last_publication_date=sub["publication_date"].max().date(), gaps=_gaps(obs, p.start, eff_end, str(info["frequency"])),
            points=[MacroPoint(observation_date=o.date(), publication_date=q.date(), value=round(float(v), ROUND))
                    for o, q, v in zip(sub["observation_date"], sub["publication_date"], sub["value"])]))
    if missing:
        warnings.append(make_warning(WarningCode.MACRO_DATA_MISSING,
                                     f"veri setinde yok veya aralıkta/as_of'ta yayımlanmış nokta yok: {', '.join(missing)}"))
    if gap_notes:
        warnings.append(make_warning(WarningCode.MACRO_DATA_MISSING, "; ".join(gap_notes) + " (doldurulmadı)"))
    relations, rel_missing, rel_warn = [], [], []
    if p.relate_to:
        cost = make_cost_model()
        uni = load_universe().set_index("ticker")
        for spec in p.relate_to:
            if spec.macro_series in MONTHLY_SERIES:
                raise ToolFailure("UNSUPPORTED_RELATION", f"{spec.macro_series.value} aylık bir seridir: relate_to yalnızca günlük serileri destekler "
                                  f"(USDTRY, EURTRY, TCMB_FUNDING_COST)")
            if spec.ticker not in uni.index:
                raise ToolFailure("UNKNOWN_TICKER", f"{spec.ticker} evrende (config/universe.csv) yok")
            mrows = vis.loc[(vis["series"] == spec.macro_series.value) & (vis["observation_date"] <= pd.Timestamp(eff_end))].sort_values("publication_date")
            if mrows.empty:
                rel_missing.append(spec.macro_series.value)
                continue
            stock = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"] == spec.ticker], p.as_of)
            stock = stock.loc[stock["date"] <= pd.Timestamp(eff_end)].sort_values("date")
            if stock.empty:
                raise ToolFailure("NO_DATA", f"{spec.ticker} için snapshot {snap.data_version} içinde aralıkta veri yok")
            days = stock["date"].to_numpy(dtype="datetime64[D]")
            mon = macro_value_on(days, mrows["publication_date"].to_numpy(dtype="datetime64[D]"), mrows["value"].to_numpy(float))
            rel, info = compute_relation(spec, days, stock["adj_close"].to_numpy(float), mon, start=p.start, eff_end=eff_end,
                                         n_tests=p.n_tests_declared, alpha=p.alpha, cost_pct=cost.round_trip_cost_pct)
            relations.append(rel)
            tag = f"{spec.ticker}~{spec.macro_series.value} h={spec.horizon} lag={spec.lag_days}"
            if info["few_events"]:
                rel_warn.append(make_warning(WarningCode.FEW_EVENTS, f"{tag}: n_obs={rel.full.n_obs} < MIN_EVENTS={MIN_EVENTS}"))
            if info["oos_too_small"]:
                rel_warn.append(make_warning(WarningCode.OOS_TOO_SMALL, f"{tag}: örneklem dışı n_obs={rel.out_of_sample.n_obs} küçük; oos_degradation_flag=false bozulma yok demek değildir"))
            if rel.oos_degradation_flag:
                rel_warn.append(make_warning(WarningCode.OOS_DEGRADATION, f"{tag}: örneklem dışı ilişki işaret değiştirdi ya da belirgin zayıfladı"))
            if rel.full.n_excluded_incomplete_horizon:
                rel_warn.append(make_warning(WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
                                             f"{tag}: aralık sonunu ({eff_end.isoformat()}) aşan kısmi blok istatistiğe katılmadı"))
        if rel_missing:
            warnings.append(make_warning(WarningCode.MACRO_DATA_MISSING, f"relate_to: veri setinde yok veya aralıkta nokta yok: {', '.join(sorted(set(rel_missing)))}"))
        if relations:
            warnings.extend(rel_warn)
            warnings.append(make_warning(WarningCode.ASSOCIATION_NOT_CAUSATION, "ilişki gözlemidir, nedensellik iddiası değildir; makro blok değişimi ve hisse blok getirisi arasındadır"))
            warnings.append(make_warning(WarningCode.MULTIPLE_TESTING_RISK,
                                         f"n_tests_declared={p.n_tests_declared}; aynı veride başka ilişki/koşul denendiyse bu sayı artırılmalı "
                                         f"(Bonferroni: p_düzeltilmiş = min(1, p x n_tests_declared)); örtüşmeyen bloklar kullanıldı"))
            warnings.append(make_warning(WarningCode.COST_ASSUMPTIONS,
                                         f"koşullu getiriler uzun pozisyon ve tur maliyeti {cost.round_trip_cost_pct} pp = 2 x "
                                         f"({cost.transaction_cost_bps_per_side} + {cost.slippage_bps_per_side} bps) ile; kayma varsayımdır"))
    note = f"makro veri seti {m.version}; kaynak TCMB/EVDS; yayın tarihi kurallı türetilmiştir (bkz. data_dictionary §22)"
    if carried_notes:
        note += "; resmî tatil iş günleri son gözlemle ileri dolduruldu (geriye doldurma yok): " + "; ".join(carried_notes)
    if any(x.series == MacroSeries.TCMB_FUNDING_COST for x in out):
        note += "; TCMB_FUNDING_COST politika faizi değil, TCMB'nin fiili ağırlıklı ortalama fonlama maliyetidir"
    warnings.append(make_warning(WarningCode.HISTORICAL_ONLY, note))
    n_excl = max((r.full.n_excluded_incomplete_horizon for r in relations), default=0)
    res = GetMacroContextResult(start=p.start, end=eff_end, series=out, relations=relations,
                                multiple_testing=MultipleTesting(n_tests_declared=p.n_tests_declared, alpha=p.alpha, adjusted_alpha=p.alpha / p.n_tests_declared) if relations else None,
                                cost_model=cost if relations else None)
    return ToolOutput(results=res, n_events=min((r.full.n_obs for r in relations), default=None), n_excluded_incomplete_horizon=n_excl, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None,
           macro_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım (sözleşmenin parçası DEĞİL)."""
    return run_tool(TOOL, params, lambda p, s: _handler(p, s, macro_version),  # type: ignore[arg-type]
                    snapshot_root=snapshot_root, data_version=data_version)
