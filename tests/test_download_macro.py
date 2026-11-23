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


def test_fold_handles_turkish_letters():
    assert D.fold("Politika FAİZİ") == "politika faizi" and D.fold("İHALE Işık") == "ihale isik" and D.fold("Şeker Öğün") == "seker ogun"


def test_match_items_is_case_and_diacritic_insensitive():
    items = [{"DATAGROUP_NAME": "Bir Hafta Vadeli REPO İhale Faiz Oranları"}, {"DATAGROUP_NAME": "Döviz Kurları"}, {"DATAGROUP_NAME": None}]
    assert D.match_items(items, "repo", ("DATAGROUP_NAME",)) == items[:1]
    assert D.match_items(items, "IHALE", ("DATAGROUP_NAME",)) == items[:1]
    assert D.match_items(items, "doviz", ("DATAGROUP_NAME",)) == items[1:2]
    assert len(D.match_items(items, "", ("DATAGROUP_NAME",))) == 3


def test_describe_series_and_unexpected_fields():
    assert D.describe_series({"SERIE_CODE": "TP.X", "SERIE_NAME": "Ad", "FREQUENCY_STR": "GÜNLÜK", "START_DATE": "01-01-2020"}) == "TP.X | Ad | GÜNLÜK | 01-01-2020"
    assert "beklenmeyen" in D.describe_series({"FOO": 1})


def test_list_series_never_prints_key(monkeypatch, capsys):
    monkeypatch.setenv("EVDS_API_KEY", "GIZLI-ANAHTAR-123")
    monkeypatch.setattr(D, "evds_get", lambda path: ([{"DATAGROUP_CODE": "bie_x", "DATAGROUP_NAME": "Repo ihale"}] if path.startswith("datagroups")
                                                     else [{"SERIE_CODE": "TP.A", "SERIE_NAME": "Faiz"}]))
    D.list_series("repo")
    out = capsys.readouterr().out
    assert "bie_x" in out and "TP.A | Faiz" in out and "GIZLI-ANAHTAR-123" not in out


def test_series_table_funding_cost_and_current_cpi_codes(monkeypatch):
    for k in ("EVDS_CODE_TCMB_FUNDING_COST", "EVDS_CODE_CPI_MONTHLY", "EVDS_CODE_CPI_ANNUAL", "EVDS_CODE_TCMB_POLICY_RATE"):
        monkeypatch.delenv(k, raising=False)
    assert set(D.SERIES) == {"USDTRY", "EURTRY", "CPI_MONTHLY", "CPI_ANNUAL", "TCMB_POLICY_RATE", "TCMB_FUNDING_COST"}
    f = D.SERIES["TCMB_FUNDING_COST"]
    assert f["code"] == "TP.APIFON4" and f["frequency"] == "daily" and f["formulas"] is None
    assert D.publication_date("TCMB_FUNDING_COST", date(2026, 9, 4)) == date(2026, 9, 4)   # gözlem günü
    # TP.FG.J0 arşivlenmiş (2003=100) seridir: 2023 sonrası 0 gözlem; güncel TÜFE (2025=100) kodu EVDS katalogundan doğrulandı
    assert D.SERIES["CPI_MONTHLY"]["code"] == D.SERIES["CPI_ANNUAL"]["code"] == "TP.TUKFIY2025.GENEL"
    assert D.series_code("TCMB_POLICY_RATE") is None                                        # politika faizi İNDİRİLMEZ
    codes = {v["code"] for v in D.SERIES.values() if v["code"]}
    assert not any("ANKET" in c.upper() or c.startswith("TP.PKAUO") for c in codes)          # anket beklentisi serisi yok


def test_manifest_documents_funding_cost_note(tmp_path):
    df = D.parse_items([{"Tarih": "01-09-2026", "X": "40.0"}], "TCMB_FUNDING_COST")
    d = D.write_macro_snapshot(df, tmp_path, "macro_2026-11-23_v1", {})
    import json
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    note = man["series"]["TCMB_FUNDING_COST"]["note"]
    assert "politika faizi değil" in note and "Toplam fonlamanın gerçekleşmediği günlerde AOFM verisi olarak bir hafta repo faiz oranı kullanılmaktadır." in note
    assert man["series"]["TCMB_FUNDING_COST"]["evds_code"] == "TP.APIFON4"


# --- EVDS tek istekte en çok 1000 satır döndürür ve FAZLASINDA ESKİ UCU KESER (macro_2026-11-09_v1'de USDTRY 2024-02-14'te başladı) ---------
def test_chunk_ranges_cover_exactly_and_stay_below_row_cap():
    ws = D.chunk_ranges(date(2023, 1, 1), date(2026, 11, 9))
    assert ws[0][0] == date(2023, 1, 1) and ws[-1][1] == date(2026, 11, 9)
    for (a, b), (c, _) in zip(ws, ws[1:]):
        assert c == b + pd.Timedelta(days=1).to_pytimedelta()          # bitişik, örtüşme/boşluk yok
    assert all((b - a).days + 1 <= D.CHUNK_DAYS < D.EVDS_ROW_CAP for a, b in ws)
    assert D.chunk_ranges(date(2026, 1, 5), date(2026, 1, 5)) == [(date(2026, 1, 5), date(2026, 1, 5))]


def test_fetch_series_merges_windows_dedupes_and_guards_cap(monkeypatch):
    calls = []

    def fake(name, a, b):
        calls.append((a, b))
        return [{"Tarih": a.strftime("%d-%m-%Y"), "X": "1.0"}, {"Tarih": b.strftime("%d-%m-%Y"), "X": "2.0"}]

    monkeypatch.setattr(D, "_fetch_window", fake)
    items = D.fetch_series("USDTRY", date(2023, 1, 1), date(2026, 11, 9))
    assert len(calls) >= 4 and calls[0][0] == date(2023, 1, 1) and calls[-1][1] == date(2026, 11, 9)
    assert len({i["Tarih"] for i in items}) == len(items)               # yinelenen tarih yok
    monkeypatch.setattr(D, "_fetch_window", lambda n, a, b: [{"Tarih": "01-01-2023", "X": "1"}] * D.EVDS_ROW_CAP)
    with pytest.raises(SystemExit, match="1000"):                       # sınıra dayanan yanıt = olası kesilme -> sessiz geçilmez
        D.fetch_series("USDTRY", date(2023, 1, 1), date(2023, 12, 31))
