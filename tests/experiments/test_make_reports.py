"""Senaryo raporları (experiments/make_reports.py): her sayı araç çıktısıyla aynı, belirlenimli, `as_of` sonrası tarih yok, sütun-anahtar eşlemesi doğru."""
from __future__ import annotations

import re

import pytest

from config.settings import SNAPSHOT_DIR
from experiments import make_reports as MR
from tools import get_macro_context as MC

needs_data = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists() or not (SNAPSHOT_DIR / "LATEST_MACRO").exists(), reason="gerçek snapshot/makro yok")
AS_OF = "2026-09-10"


@pytest.fixture(scope="module")
def reports(tmp_path_factory):
    out = tmp_path_factory.mktemp("reports")
    assert MR.main(["--out", str(out), "--as-of", AS_OF]) == 0
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(out.glob("*.md"))}


@needs_data
def test_all_six_reports_exist_with_the_disclaimer_and_method(reports):
    assert sorted(reports) == sorted(MR.REPORTS)
    for name, text in reports.items():
        assert text.startswith("# Rapor 0") and "yatırım tavsiyesi ve gelecek getiri garantisi değildir" in text and "## Yöntem" in text and "Yorum sınırı" in text, name


@needs_data
def test_no_report_mentions_a_date_after_as_of_outside_the_version_line(reports):
    for name, text in reports.items():
        for line in text.splitlines():
            if "Veri sürümleri" in line:
                continue
            for d in re.findall(r"\b(20\d\d-\d\d-\d\d)\b", line):
                assert d <= AS_OF, (name, d, line[:80])


@needs_data
def test_macro_report_matches_the_tool_for_eregl_and_maps_columns_by_key_not_order(reports):
    """Araç relate_to'yu ALFABETİK sıralar (TCMB_FUNDING_COST < USDTRY); rapor sıraya değil anahtara bağlıdır (önceki sürümde sütunlar kaymıştı)."""
    spec = lambda lag: {"ticker": "EREGL", "macro_series": "USDTRY", "horizon": 5, "lag_days": lag, "split_date": "2026-01-01"}  # noqa: E731
    r = MC.run({"start": "2024-01-01", "end": AS_OF, "as_of": AS_OF, "series": ["USDTRY"], "relate_to": [spec(0), spec(5)], "n_tests_declared": 90})["results"]["relations"]
    by = {x["lag_days"]: x["full"]["correlation"] for x in r}
    row = next(line for line in reports["05_makro_baglam.md"].splitlines() if line.startswith("| EREGL |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1] == MR.f(by[0]) and cells[3] == MR.f(by[5])
    assert f"eş zamanlı korelasyon {MR.f(by[0])}" in reports["05_makro_baglam.md"]
    assert "CPI_ANNUAL" in reports["05_makro_baglam.md"]                      # TÜFE son gözlemi tabloda


@needs_data
def test_weekday_report_declares_the_total_number_of_tests_and_chance_expectation(reports):
    t = reports["02_haftanin_gunu.md"]
    assert "**60**" in t and "tesadüfle" in t and "Bonferroni" in t


@needs_data
def test_generation_is_deterministic(reports, tmp_path):
    assert MR.main(["--out", str(tmp_path), "--as-of", AS_OF, "--only", "05_makro_baglam.md", "06_backtest_ozeti.md"]) == 0
    for name in ("05_makro_baglam.md", "06_backtest_ozeti.md"):
        assert (tmp_path / name).read_text(encoding="utf-8") == reports[name]
