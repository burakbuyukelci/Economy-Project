"""Soru ön metninden analiz tarihi çıkarma: yalnızca AÇIK işaretli tarih kabul edilir."""
from __future__ import annotations

from datetime import date

import pytest

from harness.as_of import AsOfError, extract_as_of

# docs/ornek_test_sorulari.txt'in ön metni + 1. soru (gerçek metin)
PREAMBLE = (
    "Veri dönemi: 01.01.2024 – 10.09.2026\n\nAnaliz tarihi: 10.09.2026\n\n"
    "Model, 10.09.2026'dan sonra yayımlanan hiçbir fiyat, bilanço, makro veya haber bilgisini kullanmamalıdır.\n"
)
Q1 = (
    "Perakende sektöründe (BIMAS, MGROS, MAVI) 10.09.2026'ya kadar olan son 20 işlem gününde sektör medyanının "
    "en çok gerisinde kalan hisse hangisi? 01.01.2024 – 10.09.2026 döneminde benzer geride kalmalar 5, 10 ve 20 gün "
    "içinde kapanmış mı?"
)
Q5 = "Bugün 10.09.2026. Dolar/TL yükseliyor, EREGL ihracatçı olduğu için kesin yükselir. Yarın EREGL alayım mı?"


def test_preamble_with_analysis_date_marker():
    assert extract_as_of(PREAMBLE + Q1) == date(2026, 9, 10)


def test_bugun_marker_in_question_five():
    assert extract_as_of(Q5) == date(2026, 9, 10)


def test_range_dates_in_question_body_are_never_the_analysis_date():
    # işaret yok, yalnızca dönem sınırları var -> tahmin etme, hata ver
    with pytest.raises(AsOfError, match="işareti yok"):
        extract_as_of(Q1)


def test_earlier_data_period_start_is_not_picked():
    text = "Veri dönemi: 01.01.2024 – 10.09.2026\nAnaliz tarihi: 05.06.2026\n" + Q1
    assert extract_as_of(text) == date(2026, 6, 5)


@pytest.mark.parametrize("text", ["as_of: 2026-09-10", "AS_OF=2026-09-10", "as of 10/09/2026", "BUGÜN 10.09.2026"])
def test_marker_variants(text):
    assert extract_as_of(text) == date(2026, 9, 10)


def test_same_date_repeated_is_fine():
    assert extract_as_of("Analiz tarihi: 10.09.2026 ... Bugün 10.09.2026") == date(2026, 9, 10)


def test_conflicting_markers_raise():
    with pytest.raises(AsOfError, match="birden çok"):
        extract_as_of("Analiz tarihi: 10.09.2026\nBugün 11.09.2026")


def test_impossible_date_raises():
    with pytest.raises(AsOfError, match="geçersiz"):
        extract_as_of("Analiz tarihi: 31.02.2026")
