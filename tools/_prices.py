"""get_stock_history ve get_index_history için ortak fiyat dilimleme mantığı (ağ yok)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from schemas.common import SCHEMA_VERSION  # noqa: F401  (sözleşme sürümüyle birlikte anılması için)
from schemas.enums import PriceAdjustment, WarningCode
from schemas.envelope import make_warning
from schemas.results import OHLCVRow
from tools.common import Snapshot, enforce_as_of, trading_calendar

ROUND = 6  # JSON/hash kararlılığı için sabit yuvarlama


def slice_prices(
    frame: pd.DataFrame, start: date, end: date, as_of: date, adjustment: PriceAdjustment,
) -> tuple[list[OHLCVRow], date, list[str]]:
    """frame: tek sembolün tablosu. Dönüş: (satırlar, effective_end, uyarılar).

    Sıra ÖNEMLİ: önce as_of kesilir (enforce_as_of), sonra [start, end] filtresi.
    """
    warnings: list[str] = []
    effective_end = min(end, as_of)
    if end > as_of:
        warnings.append(make_warning(
            WarningCode.AS_OF_CLAMPED, f"end={end.isoformat()} as_of={as_of.isoformat()} tarihine kesildi"))

    df = enforce_as_of(frame, as_of)
    df = df.loc[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(effective_end))]
    df = df.sort_values("date")

    if adjustment == PriceAdjustment.ADJUSTED:
        f = df["adj_close"] / df["close"]
        o, h, l, c = df["open"] * f, df["high"] * f, df["low"] * f, df["adj_close"]
    else:
        o, h, l, c = df["open"], df["high"], df["low"], df["close"]

    rows = [
        OHLCVRow(date=d.date(), open=round(float(a), ROUND), high=round(float(b), ROUND), low=round(float(x), ROUND),
                 close=round(float(y), ROUND), adj_close=round(float(z), ROUND), volume=float(v))
        for d, a, b, x, y, z, v in zip(df["date"], o, h, l, c, df["adj_close"], df["volume"])
    ]
    return rows, effective_end, warnings


def _quality_warnings(
    snap: Snapshot, symbol: str, start: date, as_of: date, rows: list[OHLCVRow], effective_end: date,
) -> list[str]:
    """Eksik işlem günü (birleşik takvime göre) ve aralıktaki fiyat sıçramaları (manifest raporu).

    Sızıntı kuralı: yalnızca [start, effective_end] içindeki ve dolayısıyla <= as_of olan günler raporlanır.
    """
    w: list[str] = []
    if rows:
        cal = enforce_as_of(pd.DataFrame({"date": trading_calendar(snap)}), as_of)
        cal = cal.loc[(cal["date"] >= pd.Timestamp(start)) & (cal["date"] <= pd.Timestamp(effective_end))]
        have = {pd.Timestamp(r.date) for r in rows}
        missing = [d for d in cal["date"] if d not in have]
        if missing:
            sample = ", ".join(d.date().isoformat() for d in missing[:5])
            more = f" (+{len(missing) - 5} gün daha)" if len(missing) > 5 else ""
            w.append(make_warning(WarningCode.MISSING_TRADING_DAYS,
                                  f"{symbol}: {len(missing)} işlem günü eksik (birleşik takvime göre): {sample}{more}"))

    limit = snap.manifest.get("price_jump_limit_pct")
    tol = snap.manifest.get("price_jump_tolerance_pp", 0.0)
    jumps = [j for j in snap.manifest.get("price_jump_report", [])
             if j["ticker"] == symbol and start.isoformat() <= j["date"] <= effective_end.isoformat()]
    for j in jumps[:5]:
        w.append(make_warning(
            WarningCode.PRICE_JUMP_OVER_LIMIT,
            f"{symbol} {j['date']}: adj_close günlük getiri {j['return_pct']}% (limit {limit}% + tolerans {tol} pp; "
            f"önceki satır {j['prev_date']}); olası düzeltilmemiş bedelsiz/bölünme veya işlem durması"))
    if len(jumps) > 5:
        w.append(make_warning(WarningCode.PRICE_JUMP_OVER_LIMIT, f"{symbol}: +{len(jumps) - 5} sıçrama daha"))
    return w


def history_warnings_for_range(snap: Snapshot, symbol: str, start: date, as_of: date, rows: list[OHLCVRow],
                               effective_end: date) -> list[str]:
    w: list[str] = _quality_warnings(snap, symbol, start, as_of, rows, effective_end)
    download_start = snap.manifest.get("download_start")
    if download_start and start < date.fromisoformat(download_start):
        w.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                              f"start={start.isoformat()} snapshot başlangıcından ({download_start}) önce; veri yok"))
    if not rows:
        w.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                              f"[{start.isoformat()}, {effective_end.isoformat()}] aralığında satır yok (as_of={as_of.isoformat()})"))
    return w
