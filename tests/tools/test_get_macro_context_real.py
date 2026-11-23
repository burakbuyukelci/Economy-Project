"""Gerçek makro snapshot'ı üzerinde as_of sızıntısı ve tatil davranışı. Makro snapshot'ı (LATEST_MACRO) yoksa atlanır."""
from __future__ import annotations

import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from tools import get_macro_context as MC

pytestmark = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST_MACRO").exists() or not (SNAPSHOT_DIR / "LATEST").exists(),
                                reason="gerçek makro/fiyat snapshot'ı yok")

AS_OF = "2026-09-10"
DAILY = ["USDTRY", "EURTRY", "TCMB_FUNDING_COST"]


def _run(**p):
    base = {"start": "2024-01-01", "end": "2026-12-31", "as_of": AS_OF, "series": DAILY + ["CPI_MONTHLY", "CPI_ANNUAL"]}
    return MC.run({**base, **p})


def test_real_nothing_after_as_of_enters_any_output():
    e = _run()
    validate_envelope(e)
    assert e["status"] == "OK" and e["results"]["end"] == AS_OF
    assert {s["series"] for s in e["results"]["series"]} == set(DAILY + ["CPI_MONTHLY", "CPI_ANNUAL"])
    for s in e["results"]["series"]:
        assert s["points"], s["series"]
        assert all(p["observation_date"] <= AS_OF and p["publication_date"] <= AS_OF for p in s["points"]), s["series"]
        assert s["last_publication_date"] <= AS_OF
    blob = str(e["results"])  # uyarılar sürüm adı (macro_<tarih>) içerebilir; yalnızca sonuçlara bakılır
    assert "2026-09-11" not in blob and "2026-10-29" not in blob and "2026-11-09" not in blob  # as_of sonrası gün/tatil çıktıda yok


def test_real_2026_07_15_holiday_is_carried_not_missing():
    e = _run(series=DAILY)
    for s in e["results"]["series"]:
        pts = {p["observation_date"]: p for p in s["points"]}
        assert pts["2026-07-15"]["value"] == pts["2026-07-14"]["value"], s["series"]
        assert pts["2026-07-15"]["publication_date"] == "2026-07-15"
    assert not [w for w in e["warnings"] if w.startswith("MACRO_DATA_MISSING")]  # tatil dışı boşluk yok (gözlemlenen: yalnızca resmî tatiller)


def test_real_2026_10_29_holiday_carried_only_when_as_of_allows():
    e = _run(series=DAILY, as_of="2026-11-09")
    for s in e["results"]["series"]:
        pts = {p["observation_date"]: p for p in s["points"]}
        assert pts["2026-10-29"]["value"] == pts["2026-10-28"]["value"], s["series"]
    assert not [w for w in e["warnings"] if w.startswith("MACRO_DATA_MISSING")]


def test_real_deterministic():
    assert _run() == _run()
