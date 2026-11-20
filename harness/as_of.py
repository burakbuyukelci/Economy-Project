"""Soru ön metnindeki ANALİZ TARİHİNİ çıkarır (oturum as_of'u buradan gelir).

Yalnızca AÇIK işaretli tarih kabul edilir: "Analiz tarihi: 10.09.2026", "as_of: 2026-09-10",
"Bugün 10.09.2026". Sorunun gövdesindeki dönem sınırları ("01.01.2024 – 10.09.2026") işaretsizdir
ve ASLA analiz tarihi sayılmaz. İşaret yoksa ya da işaretler çelişiyorsa tahmin edilmez, hata verilir.
"""
from __future__ import annotations

import re
from datetime import date

_DATE = r"(\d{1,2}[./]\d{1,2}[./]\d{4}|\d{4}-\d{2}-\d{2})"
# İşaret sözcüğü + (isteğe bağlı ayraç) + tarih. Türkçe büyük/küçük harf için (?i).
_MARKERS = re.compile(
    r"(?i)(?:analiz\s+tarihi|as[_\s]?of|bug[uü]n)\s*[:=]?\s*" + _DATE
)


class AsOfError(ValueError):
    """Analiz tarihi bulunamadı, geçersiz ya da çelişkili."""


def _parse(text: str) -> date:
    text = text.strip()
    try:
        if "-" in text:
            return date.fromisoformat(text)
        d, m, y = (int(x) for x in re.split(r"[./]", text))
        return date(y, m, d)
    except ValueError as exc:
        raise AsOfError(f"geçersiz tarih: {text!r}") from exc


def extract_as_of(question: str) -> date:
    found = {_parse(m.group(1)) for m in _MARKERS.finditer(question)}
    if not found:
        raise AsOfError("soruda açık bir analiz tarihi işareti yok ('Analiz tarihi: GG.AA.YYYY')")
    if len(found) > 1:
        listed = ", ".join(sorted(d.isoformat() for d in found))
        raise AsOfError(f"soruda birden çok farklı analiz tarihi var: {listed}")
    return found.pop()
