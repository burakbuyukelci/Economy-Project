"""scripts/download_macro.py: saf mantık (ağsız)."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

from scripts import download_macro as D


def test_parse_obs_date_formats():
    assert D.parse_obs_date("05-09-2026") == date(2026, 9, 5)
    assert D.parse_obs_date("2026-8") == date(2026, 8, 31)  # aylık -> ay sonu
    assert D.parse_obs_date("2024-2") == date(2024, 2, 29)
    assert D.parse_obs_date("2026-09-05") == date(2026, 9, 5)


def test_publication_date_rules():
    assert D.publication_date("USDTRY", date(2026, 9, 4)) == date(2026, 9, 4)
    assert D.publication_date("TCMB_POLICY_RATE", date(2026, 9, 4)) == date(2026, 9, 4)
    assert D.publication_date("CPI_ANNUAL", date(2026, 8, 31)) == date(2026, 9, 3)   # Perşembe
    assert D.publication_date("CPI_MONTHLY", date(2026, 9, 30)) == date(2026, 10, 5)  # 3 Ekim 2026 Cumartesi -> Pazartesi 5
    assert D.publication_date("CPI_MONTHLY", date(2026, 12, 31)) == date(2027, 1, 4)  # 3 Oca 2027 Pazar -> Pazartesi


def test_parse_items_skips_empty_and_rejects_unexpected_columns():
    items = [{"Tarih": "01-09-2026", "TP_DK_USD_A_YTL": "41.5", "UNIXTIME": {"$numberLong": "1"}},
             {"Tarih": "02-09-2026", "TP_DK_USD_A_YTL": None},
             {"Tarih": "03-09-2026", "TP_DK_USD_A_YTL": "41.7"}]
    df = D.parse_items(items, "USDTRY")
    assert list(df["value"]) == [41.5, 41.7] and list(df.columns) == D.COLUMNS
    with pytest.raises(ValueError, match="beklenmeyen"):
        D.parse_items([{"Tarih": "01-09-2026", "A": "1", "B": "2"}], "USDTRY")


def test_env_loader_does_not_override_and_ignores_comments(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text('# yorum\nEVDS_API_KEY=abc\nEVDS_CODE_TCMB_POLICY_RATE="TP.X"\nBOS\n', encoding="utf-8")
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    monkeypatch.setenv("EVDS_CODE_TCMB_POLICY_RATE", "ONCEDEN")
    D.load_env(p)
    assert os.environ["EVDS_API_KEY"] == "abc" and os.environ["EVDS_CODE_TCMB_POLICY_RATE"] == "ONCEDEN"
    monkeypatch.delenv("EVDS_API_KEY")


def test_policy_rate_code_not_guessed_but_env_overridable(monkeypatch):
    monkeypatch.delenv("EVDS_CODE_TCMB_POLICY_RATE", raising=False)
    assert D.series_code("TCMB_POLICY_RATE") is None
    monkeypatch.setenv("EVDS_CODE_TCMB_POLICY_RATE", "TP.DOGRULANMIS")
    assert D.series_code("TCMB_POLICY_RATE") == "TP.DOGRULANMIS"


def test_write_snapshot_lf_immutable_and_manifest(tmp_path):
    df = D.parse_items([{"Tarih": "01-09-2026", "X": "41.5"}], "USDTRY")
    v = "macro_2026-11-21_v1"
    d = D.write_macro_snapshot(df, tmp_path, v, {})
    assert (tmp_path / "LATEST_MACRO").read_text().strip() == v
    for f in (d / "manifest.json", tmp_path / "LATEST_MACRO"):
        assert chr(13).encode() not in f.read_bytes()
    assert pd.read_parquet(d / "macro.parquet").shape[0] == 1
    with pytest.raises(FileExistsError):
        D.write_macro_snapshot(df, tmp_path, v, {})
    with pytest.raises(ValueError):
        D.write_macro_snapshot(df, tmp_path, "snap_2026-11-21_v1", {})
