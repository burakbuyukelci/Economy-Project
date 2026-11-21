"""Teknik dönüş soruları için sinyal günleri (bkz. tests/training/test_signal_dates.py).

Bir hissede olay oluşan günler araçla AYNI tanımla (`build_events`) tüm seriden hesaplanır (olaylar nedenseldir: t günü yalnızca <= t verisini kullanır); soru tarihi
olay günü ve sonraki 2 iş günüdür. Araç çıktıları yine as_of'a kesilmiş veriyle üretilir: bu yalnızca soru tarihi SEÇİMİDİR.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from schemas.enums import EventFamily, PriceAdjustment
from schemas.params import IndicatorConfig
from tools.calculate_indicators import _price_frame
from tools.common import enforce_as_of, load_snapshot
from tools.detect_reversal_events import build_events
from training import spec
from training.splits import split_of_date

ANALYSIS_START = date(2024, 1, 1)
DAYS_AFTER = 2          # olay günü + sonraki 2 iş günü (politika: son olay en çok 3 iş günü önce)


def _next_business_days(d: date, n: int) -> list[date]:
    out, cur = [d], d
    while len(out) < n + 1:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            out.append(cur)
    return out


@lru_cache(maxsize=None)
def _event_dates(ticker: str, family: str) -> tuple[date, ...]:
    snap = load_snapshot()
    last = snap.stocks["date"].max()
    last_date = last.date() if hasattr(last, "date") else last
    px = _price_frame(enforce_as_of(snap.stocks.loc[snap.stocks["ticker"] == ticker], last_date), PriceAdjustment.ADJUSTED)
    es = build_events(px, IndicatorConfig(), EventFamily(family), "close", ANALYSIS_START)
    return tuple(px.index[i].date() for i in es.ev_idx)


def signal_dates(ticker: str, family: str, split: str, *, raw_events: bool = False) -> list[date]:
    """Bölme aralığındaki sinyal günleri (sıralı, tekil). raw_events=True: yalnızca olay günleri."""
    events = _event_dates(ticker, family)
    days = sorted({e for e in events} if raw_events else {d for e in events for d in _next_business_days(e, DAYS_AFTER)})
    return [d for d in days if d.weekday() < 5 and split_of_date(d) == split and spec.DATE_RANGES[split][0] <= d <= spec.DATE_RANGES[split][1]]
