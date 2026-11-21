"""Bölme kuralları (üretimden ÖNCE verilir) ve sızıntı denetimi.

* Hisse/grup: peer grupları (config/universe.csv) bölmelere TEK parça atanır (sha256(tohum, grup) sırası): ~%25 test, ~%15 doğrulama, kalanı eğitim.
  Retail tek ≥3 üyeli gruptur ve catch-up (rank) için gereklidir: stock-level tiplerde EĞİTİMDE, catch-up'ta her bölmede kullanılır (yalnızca tarih ve şablonla ayrılır).
* Tarih: bölmelerin `as_of` aralıkları ayrıktır (test en geç dönem); bayat-veri soruları kendi ayrık aralıklarından.
* Şablon: sırası % 4 == 3 olan şablonlar yalnızca TEST'te kullanılır.
"""
from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable

from config.universe import build_sector_peer_groups
from training import spec

RETAIL = "retail"
TEST_FRACTION, VAL_FRACTION = 0.25, 0.15


@lru_cache(maxsize=None)
def ticker_split_map() -> dict[str, str]:
    """ticker -> bölme (stock-level tipler için). Retail eğitime atanır; kalan gruplar tohumlu hash sırasına göre bölünür."""
    groups = build_sector_peer_groups()
    others = sorted((g for g in groups if g != RETAIL), key=lambda g: hashlib.sha256(f"{spec.SEED}:{g}".encode()).hexdigest())
    n_test, n_val = round(len(others) * TEST_FRACTION), round(len(others) * VAL_FRACTION)
    out: dict[str, str] = {t: "train" for t in groups.get(RETAIL, [])}
    for i, g in enumerate(others):
        split = "test" if i < n_test else "val" if i < n_test + n_val else "train"
        for t in groups[g]:
            out[t] = split
    return out


def tickers_for(split: str, qtype: str) -> list[str]:
    """Bir bölmede bir soru tipi için kullanılabilir hisseler (sıralı)."""
    if qtype == "catch_up":
        return sorted(build_sector_peer_groups()[RETAIL])
    return sorted(t for t, s in ticker_split_map().items() if s == split)


def is_test_only_template(index: int) -> bool:
    return index % spec.TEST_TEMPLATE_MOD == spec.TEST_TEMPLATE_MOD - 1


def split_of_date(d: date) -> str | None:
    for s in spec.SPLITS:
        for rng in (spec.DATE_RANGES[s], spec.STALE_RANGES[s]):
            if rng[0] <= d <= rng[1]:
                return s
    return None


def pick_trading_date(split: str, rng: random.Random, *, stale: bool = False) -> date:
    lo, hi = (spec.STALE_RANGES if stale else spec.DATE_RANGES)[split]
    days = (hi - lo).days
    while True:
        d = lo + timedelta(days=rng.randint(0, days))
        if d.weekday() < 5:
            return d


def leakage_problems(questions: Iterable) -> list[str]:
    """Bölmeler arası sızıntılar: aynı soru metni, yasak hisse/tarih/şablon. Boş liste = temiz."""
    qs = list(questions)
    problems: list[str] = []
    seen: dict[str, str] = {}
    for q in qs:
        if q.text in seen and seen[q.text] != q.split:
            problems.append(f"aynı soru metni iki bölmede: {q.id} / {seen[q.text]}")
        seen.setdefault(q.text, q.split)
        allowed = set(tickers_for(q.split, q.type))
        if not set(q.tickers) <= allowed:
            problems.append(f"{q.id}: hisse {sorted(set(q.tickers) - allowed)} bu bölmeye ait değil")
        if split_of_date(q.as_of) != q.split:
            problems.append(f"{q.id}: as_of {q.as_of} bu bölmenin tarih aralığında değil")
        if q.split != "test" and is_test_only_template(q.template_idx):
            problems.append(f"{q.id}: test şablonu {q.template_idx} {q.split} bölmesinde")
    return problems
