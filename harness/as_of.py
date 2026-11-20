"""Soru ön metnindeki ANALİZ TARİHİNİ çıkarır (oturum as_of'u buradan gelir).

Yalnızca AÇIK işaretli tarih kabul edilir: "Analiz tarihi: 10.09.2026", "as_of: 2026-09-10",
"Bugün 10.09.2026". Sorunun gövdesindeki dönem sınırları ("01.01.2024 – 10.09.2026") işaretsizdir
ve ASLA analiz tarihi sayılmaz. İşaret yoksa ya da işaretler çelişiyorsa tahmin edilmez, hata verilir.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

_DATE = r"(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})"
# İşaret sözcüğü + (isteğe bağlı ayraç) + tarih. Türkçe büyük/küçük harf için (?i).
_MARKERS = re.compile(
    r"(?i)(?:analiz\s+tarihi|as[_\s]?of|bug[uü]n)\s*[:=]?\s*" + _DATE
)


class AsOfError(ValueError):
    """Analiz tarihi bulunamadı, geçersiz ya da çelişkili."""


def parse_date(text: str) -> date:
    text = text.strip()
    try:
        if "-" in text:
            return date.fromisoformat(text)
        d, m, y = (int(x) for x in re.split(r"[./]", text))
        return date(y, m, d)
    except ValueError as exc:
        raise AsOfError(f"geçersiz tarih: {text!r}") from exc


def _markers(question: str) -> set[date]:
    return {parse_date(m.group(1)) for m in _MARKERS.finditer(question)}


def extract_as_of(question: str) -> date:
    found = _markers(question)
    if not found:
        raise AsOfError("soruda açık bir analiz tarihi işareti yok ('Analiz tarihi: GG.AA.YYYY')")
    if len(found) > 1:
        listed = ", ".join(sorted(d.isoformat() for d in found))
        raise AsOfError(f"soruda birden çok farklı analiz tarihi var: {listed}")
    return found.pop()


@dataclass(frozen=True)
class ResolvedAsOf:
    date: date
    source: Literal["question", "explicit", "default"]


def resolve_as_of(question: str, *, explicit: date | None = None, default: date | None = None) -> ResolvedAsOf:
    """Öncelik: sorudaki işaret > açık parametre (eval seti) > varsayılan (settings) > hata.

    Yalnızca VARSAYILANA düşülürse çağıran "AS_OF_ASSUMED" uyarısı üretmelidir.
    Çelişkili işaretler hiçbir zaman varsayılana düşmez (hata).
    """
    found = _markers(question)
    if len(found) > 1:  # extract_as_of aynı hatayı verir
        extract_as_of(question)
    if found:
        marker = next(iter(found))
        if explicit is not None and explicit != marker:
            raise AsOfError(f"açık as_of ({explicit.isoformat()}) soru metnindeki tarihle ({marker.isoformat()}) çelişiyor")
        return ResolvedAsOf(marker, "question")
    if explicit is not None:
        return ResolvedAsOf(explicit, "explicit")
    if default is not None:
        return ResolvedAsOf(default, "default")
    raise AsOfError("soruda açık bir analiz tarihi işareti yok ('Analiz tarihi: GG.AA.YYYY'); "
                    "açık as_of ya da DEFAULT_AS_OF de verilmemiş")
