"""Genelleme testi altyapısı: varyant üreticisi (sayı, çeşitlilik, belirlenimlilik, tarih/as_of tutarlılığı) ve koşucunun kayıt biçimi.

Tam koşu bir hata ARAMA aracıdır, pytest'in parçası DEĞİLDİR (bulguları raporlar, testi kırmaz): `python -m tests.generalization.run`.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from config.settings import SNAPSHOT_DIR
from tests.generalization import run as R
from tests.generalization.variants import DATA_END, N_PER_TYPE, TYPES, all_variants

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_FUNDAMENTALS").exists(), reason="gerçek snapshot/bilanço yok")


def test_at_least_eight_variants_per_type_and_ten_distinct_tickers():
    vs = all_variants()
    for t in TYPES:
        assert sum(1 for v in vs if v["type"] == t) >= 8
    assert N_PER_TYPE >= 8
    assert len({tk for v in vs for tk in v["tickers"]}) >= 10
    assert len({v["id"] for v in vs}) == len(vs)


def test_variants_are_deterministic_and_diverse_in_dates_and_parameters():
    a, b = all_variants(), all_variants()
    assert a == b
    for t in TYPES:
        grp = [v for v in a if v["type"] == t]
        assert len({v["as_of"] for v in grp}) >= 8                       # farklı as_of tarihleri
        assert len({str(v["params"]) for v in grp}) >= 5                 # farklı parametreler
    for t in ("Q2_weekday", "Q3_reversal", "Q4_fundamental", "Q5_macro_safety"):
        assert len({v["tickers"][0] for v in a if v["type"] == t}) == N_PER_TYPE      # tipte her varyant farklı hisse


def test_dates_are_business_days_within_data_and_consistent_across_text_and_calls():
    for v in all_variants():
        d = date.fromisoformat(v["as_of"])
        assert d.weekday() < 5 and d <= DATA_END
        assert v["text"].startswith(f"Analiz tarihi: {d.strftime('%d.%m.%Y')}\n"), v["id"]
        assert all(p["as_of"] == v["as_of"] for _, p in v["calls"]), v["id"]


def test_required_tickers_and_edge_cases_are_covered():
    vs = all_variants()
    assert any(v["type"] == "Q4_fundamental" and v["tickers"] == ["TUPRS"] for v in vs)      # Soru 4'ün hissesi
    assert any(v["type"] == "Q4_fundamental" and v["params"]["bank"] for v in vs)            # banka kümesi
    assert any(v["params"].get("early_date") for v in vs)                                    # bilanço görünür olmadan önceki tarih
    sectors = {v["params"]["sector"] for v in vs if v["type"] == "Q1_catch_up"}
    assert "retail" in sectors and len(sectors) >= 5                                         # 3 hisseli grup + 2 hisseli gruplar
    fams = {v["params"]["family"] for v in vs if v["type"] == "Q3_reversal"}
    assert {"BB_LOWER_TOUCH", "RSI_LOCAL_TROUGH"} <= fams and len(fams) >= 3


def test_summarize_groups_findings_by_category_and_counts_per_type():
    recs = [
        {"id": "Q1-00", "type": TYPES[0], "status": "DELIVERED", "categories": ["MISSING_DATA"], "findings": [{"category": "MISSING_DATA", "detail": "x MISSING_TRADING_DAYS: AKBNK: 3 işlem günü"}]},
        {"id": "Q1-01", "type": TYPES[0], "status": "CRASH", "categories": ["CRASH"], "findings": [{"category": "CRASH", "detail": "ValueError: boom"}]},
        {"id": "Q2-00", "type": TYPES[1], "status": "DELIVERED", "categories": [], "findings": []},
    ]
    for r in recs:
        r.update(tickers=["T"], label=None)
    s = R.summarize(recs)
    assert s["by_category"]["CRASH"]["variants"] == ["Q1-01"] and s["by_category"]["MISSING_DATA"]["n_variants"] == 1
    assert s["per_type"][TYPES[0]] == {"n": 2, "ran_ok": 1, "clean": 1, "with_findings": 2}
    assert s["per_type"][TYPES[1]]["clean"] == 1 and s["ran_ok"] == 2


def test_future_dates_helper_flags_only_dates_after_as_of():
    out = R._future_dates({"a": "2026-09-10", "b": ["2026-09-11", {"c": "2026-01-01"}], "d": "metin"}, date(2026, 9, 10))
    assert out == ["results.b[0]=2026-09-11"]


@needs_data
@pytest.mark.parametrize("prefix", ["Q1-00", "Q2-00", "Q3-00", "Q4-02", "Q5-00"])
def test_runner_returns_a_well_formed_record_and_never_raises(prefix):
    v = next(x for x in all_variants() if x["id"] == prefix)
    with R.tools_context():
        rec = R.execute(v)
    assert rec["id"] == prefix and rec["status"] and set(rec["categories"]) <= set(R.CATEGORIES)
    assert all(f["category"] in R.CATEGORIES for f in rec["findings"])
    assert "LEAK" not in rec["categories"]                     # sızıntı yok (ayrıca tam koşuda tüm varyantlarda denetlenir)
