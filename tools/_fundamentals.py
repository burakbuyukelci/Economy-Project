"""Bilanço veri seti okuyucu + metrik hesapları (get_fundamental_metrics / calculate_fundamental_change ortak kodu).

Ağ YOK. Veri `data/snapshots/fundamentals_<tarih>_v<N>/fundamentals.parquet` (+ manifest.json) içinden okunur;
fiyat snapshot'ından (snap_..._vN) AYRI sürümlenir (CLAUDE.md kural 12 fiyat sürümüne bağlı kalır).

Satır = hisse x dönem (fiscal_period "2026Q2"). Akış kalemleri (revenue, ebitda, net_profit, net_interest_income) TEK ÇEYREK
(standalone) değerdir; bilanço kalemleri (borç, nakit, özkaynak) dönem sonu stokudur. Birim: milyon TL.
Hizalama KAP açıklama tarihine (`disclosure_date`) göredir, dönem sonuna DEĞİL (kural 7).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import SNAPSHOT_DIR
from schemas.enums import FundamentalMetricName as M
from schemas.enums import MetricSet

FUNDAMENTALS_VERSION_RE = re.compile(r"^fundamentals_\d{4}-\d{2}-\d{2}_v\d+$")
TMS29_FIRST_PERIOD_END = date(2025, 1, 1)  # kural 7: ana analiz 2025 ve sonrası
ROUND = 4

COLUMNS = [
    "ticker", "fiscal_period", "period_end_date", "disclosure_date", "disclosure_time", "disclosure_source",
    "data_source", "report_basis", "tms29_restated", "metric_set",
    "revenue", "ebitda", "net_profit", "total_financial_debt", "cash_and_equivalents", "equity", "net_interest_income",
]
FLOW_COLS = ["revenue", "ebitda", "net_profit", "net_interest_income"]

# Metrik kümeleri (banka: en küçük küme; sanayi oranları bankada KULLANILMAZ, kural 7)
INDUSTRIAL_METRICS = [M.REVENUE, M.EBITDA, M.NET_PROFIT, M.EBITDA_MARGIN, M.NET_PROFIT_MARGIN, M.NET_DEBT_EBITDA, M.DEBT_EQUITY]
BANK_METRICS = [M.NET_INTEREST_INCOME, M.NET_PROFIT, M.ROE]
METRIC_SETS = {MetricSet.INDUSTRIAL: INDUSTRIAL_METRICS, MetricSet.BANK: BANK_METRICS}
UNITS = {M.REVENUE: "TRY_mn", M.EBITDA: "TRY_mn", M.NET_PROFIT: "TRY_mn", M.NET_INTEREST_INCOME: "TRY_mn",
         M.EBITDA_MARGIN: "PCT", M.NET_PROFIT_MARGIN: "PCT", M.ROE: "PCT_QUARTERLY",
         M.NET_DEBT_EBITDA: "RATIO", M.DEBT_EQUITY: "RATIO"}
# Değişim birimi: seviye -> PCT (göreli %), marj/oran yüzdesi -> PP (puan farkı), katsayı -> ABS
LEVEL_METRICS = {M.REVENUE, M.EBITDA, M.NET_PROFIT, M.NET_INTEREST_INCOME}
PP_METRICS = {M.EBITDA_MARGIN, M.NET_PROFIT_MARGIN, M.ROE}
LOWER_IS_BETTER = {M.NET_DEBT_EBITDA, M.DEBT_EQUITY}


# --- dönem aritmetiği ------------------------------------------------------------------------------
def fp_parse(fp: str) -> tuple[int, int]:
    return int(fp[:4]), int(fp[5])


def fp_shift(fp: str, n_quarters: int) -> str:
    y, q = fp_parse(fp)
    k = y * 4 + (q - 1) + n_quarters
    return f"{k // 4}Q{k % 4 + 1}"


def fp_period_end(fp: str) -> date:
    y, q = fp_parse(fp)
    return {1: date(y, 3, 31), 2: date(y, 6, 30), 3: date(y, 9, 30), 4: date(y, 12, 31)}[q]


def tms29_comparable(period_end: date) -> bool:
    return period_end >= TMS29_FIRST_PERIOD_END


# --- okuma -----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Fundamentals:
    version: str
    table: pd.DataFrame
    manifest: dict


def resolve_fundamentals_version(root: Path | None = None) -> str:
    env = os.environ.get("FUNDAMENTALS_VERSION")
    if env:
        return env.strip()
    latest = Path(root or SNAPSHOT_DIR) / "LATEST_FUNDAMENTALS"
    if not latest.exists():
        raise FileNotFoundError(f"{latest} yok: önce `python -m scripts.download_fundamentals` çalıştırın")
    return latest.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=4)
def _load(root: str, version: str) -> Fundamentals:
    d = Path(root) / version
    if not d.is_dir():
        raise FileNotFoundError(f"bilanço veri seti yok: {d}")
    t = pd.read_parquet(d / "fundamentals.parquet")
    for c in ("period_end_date", "disclosure_date"):
        t[c] = pd.to_datetime(t[c])
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return Fundamentals(version, t.sort_values(["ticker", "period_end_date"]).reset_index(drop=True), manifest)


def load_fundamentals(root: Path | None = None, version: str | None = None) -> Fundamentals:
    root = Path(root or SNAPSHOT_DIR)
    return _load(str(root.resolve()), version or resolve_fundamentals_version(root))


# --- metrikler -------------------------------------------------------------------------------------
def _val(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x) else float(x)


def _r(x: float | None) -> float | None:
    return None if x is None else float(np.round(x, ROUND)) + 0.0


def ltm_ebitda(rows: pd.DataFrame, fp: str) -> tuple[float | None, str]:
    """Son 4 ardışık çeyreğin FAVÖK toplamı; yoksa çeyreklik x4 (yıllıklandırma). Dönüş (değer, 'LTM'|'ANNUALISED'|'NONE').

    rows: `fp` dahil, yalnızca as_of'ta AÇIKLANMIŞ satırlar (fiscal_period indeksli)."""
    fps = [fp_shift(fp, -i) for i in range(4)]
    if all(f in rows.index and _val(rows.at[f, "ebitda"]) is not None for f in fps):
        return float(sum(rows.at[f, "ebitda"] for f in fps)), "LTM"
    own = _val(rows.at[fp, "ebitda"]) if fp in rows.index else None
    if own is not None:
        return own * 4.0, "ANNUALISED"
    return None, "NONE"


def quarter_metrics(rows: pd.DataFrame, fp: str, metric_set: MetricSet) -> tuple[dict[M, float | None], str]:
    """Bir dönemin metrikleri (yuvarlanmış) ve Net Borç/FAVÖK tabanı ('LTM'|'ANNUALISED'|'NONE').

    rows: hisse satırları, fiscal_period indeksli, as_of'ta açıklanmış olanlar."""
    r = rows.loc[fp]
    rev, ebitda, np_ = _val(r["revenue"]), _val(r["ebitda"]), _val(r["net_profit"])
    debt, cash, eq, nii = _val(r["total_financial_debt"]), _val(r["cash_and_equivalents"]), _val(r["equity"]), _val(r["net_interest_income"])
    out: dict[M, float | None] = {}
    basis = "NONE"
    if metric_set == MetricSet.BANK:
        out[M.NET_INTEREST_INCOME] = _r(nii)
        out[M.NET_PROFIT] = _r(np_)
        out[M.ROE] = _r(np_ / eq * 100) if np_ is not None and eq else None  # çeyreklik, yıllıklandırılmamış
    else:
        out[M.REVENUE], out[M.EBITDA], out[M.NET_PROFIT] = _r(rev), _r(ebitda), _r(np_)
        out[M.EBITDA_MARGIN] = _r(ebitda / rev * 100) if ebitda is not None and rev else None
        out[M.NET_PROFIT_MARGIN] = _r(np_ / rev * 100) if np_ is not None and rev else None
        out[M.DEBT_EQUITY] = _r(debt / eq) if debt is not None and eq else None
        e, basis = ltm_ebitda(rows, fp)
        out[M.NET_DEBT_EBITDA] = (
            _r((debt - cash) / e) if debt is not None and cash is not None and e is not None and e > 0 else None)
    return out, basis


def change(name: M, cur: float | None, prev: float | None) -> tuple[float | None, str]:
    """(değişim, birim). Seviye: göreli %, taban <= 0 ise None (anlamsız). Marj: puan farkı. Katsayı: mutlak fark."""
    if cur is None or prev is None:
        return None, _unit(name)
    if name in LEVEL_METRICS:
        return (_r((cur / prev - 1) * 100) if prev > 0 else None), "PCT"
    return _r(cur - prev), _unit(name)


def _unit(name: M) -> str:
    return "PCT" if name in LEVEL_METRICS else ("PP" if name in PP_METRICS else "ABS")


FLAT_EPS = {"PCT": 0.5, "PP": 0.5, "ABS": 0.05}  # |değişim| bu eşiğin altı FLAT (VARSAYIM; docs/data_dictionary.md)


def direction(name: M, chg: float | None, unit: str) -> str | None:
    if chg is None:
        return None
    if abs(chg) < FLAT_EPS[unit]:
        return "FLAT"
    good = chg < 0 if name in LOWER_IS_BETTER else chg > 0
    return "IMPROVED" if good else "DETERIORATED"


def visible(table: pd.DataFrame, ticker: str, as_of: date) -> pd.DataFrame:
    """Hissenin as_of'ta AÇIKLANMIŞ satırları (disclosure_date <= as_of; enforce_as_of), fiscal_period indeksli."""
    from tools.common import enforce_as_of
    sub = table.loc[table["ticker"] == ticker]
    return enforce_as_of(sub, as_of, "disclosure_date").set_index("fiscal_period", drop=False)


def pending_count(table: pd.DataFrame, ticker: str, as_of: date) -> int:
    """Dönem sonu as_of'a kadar GEÇMİŞ ama açıklaması as_of'tan SONRA olan dönem sayısı.

    Sızıntı kuralı: yalnızca SAYI döner (gelecek açıklama tarihi/değerleri asla dışarı çıkmaz). Dönem sonu as_of'tan sonra olan
    çeyrek (henüz bitmemiş) sayılmaz: as_of'ta var olmayan bir dönemin bilgisini vermemek için."""
    ts = pd.Timestamp(as_of)
    sub = table.loc[table["ticker"] == ticker]
    return int(((sub["disclosure_date"] > ts) & (sub["period_end_date"] <= ts)).sum())


def provenance_warnings(version: str, rows: pd.DataFrame) -> list[str]:
    """Veri sürümü/kaynak notu (HISTORICAL_ONLY) + Yahoo yaklaşık açıklama tarihi notu.

    Not: sözleşmede ikincil veri sürümü alanı yok; sürüm bu uyarıda taşınır (docs/schema_wishlist.md §12)."""
    from schemas.enums import WarningCode
    from schemas.envelope import make_warning
    srcs = sorted(set(rows["data_source"])) if len(rows) else []
    out = [make_warning(WarningCode.HISTORICAL_ONLY,
                        f"bilanço veri seti {version}; kaynak: {', '.join(srcs) or '-'}; geçmiş kanıt, gelecek garantisi değil")]
    approx = sorted(rows.loc[rows["disclosure_source"] == "YAHOO_APPROX", "fiscal_period"])
    if approx:
        out.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"YAHOO_APPROX: {', '.join(approx)} dönemlerinin açıklama tarihi Yahoo'dan (ABD saatinden İstanbul'a çevrilmiş, "
            "yaklaşık) alındı; resmî KAP tarihi/saati değil"))
    news = sorted(rows.loc[rows["disclosure_source"] == "KAP_DATE_VIA_NEWS", "fiscal_period"])
    if news:
        out.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"KAP_DATE_VIA_NEWS: {', '.join(news)} dönemlerinin açıklama tarihi haber/KAP kaynaklarından doğrulandı; açıklama saati bilinmiyor "
            "(tepki bazı muhafazakâr: açıklamadan önceki son kapanış)"))
    stat = sorted(rows.loc[rows["disclosure_source"] == "STATUTORY_DEADLINE", "fiscal_period"])
    if stat:
        out.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"STATUTORY_DEADLINE: {', '.join(stat)} dönemlerinin açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı "
            "(dönem sonu + yasal süre; gerçek açıklama daha erken olabilir); bu dönemler fiyat tepkisi analizine girmez"))
    return out
