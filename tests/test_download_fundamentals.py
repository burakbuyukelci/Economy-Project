"""scripts/download_fundamentals.py: saf mantık (ağsız) testleri."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.universe import load_universe
from scripts import download_fundamentals as D
from tools._fundamentals import COLUMNS, load_fundamentals

HEADER = ",".join(D.MANUAL_COLUMNS)


def _csv(tmp_path, lines):
    p = tmp_path / "f.csv"
    p.write_text(HEADER + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_assign_disclosures_picks_first_date_after_period_end():
    pe = [pd.Timestamp("2025-06-30"), pd.Timestamp("2025-09-30")]
    ed = [pd.Timestamp("2025-04-29 03:00"), pd.Timestamp("2025-07-29 03:00"), pd.Timestamp("2025-10-31 03:00"), pd.Timestamp("2026-02-06")]
    got = D.assign_disclosures(pe, ed)
    assert got == {pd.Timestamp("2025-06-30"): pd.Timestamp("2025-07-29"), pd.Timestamp("2025-09-30"): pd.Timestamp("2025-10-31")}


def test_assign_disclosures_skips_period_without_date_in_window():
    assert D.assign_disclosures([pd.Timestamp("2025-03-31")], [pd.Timestamp("2025-10-01")]) == {}


def test_assign_disclosures_rejects_future_projection_and_late_lag_and_reused_dates():
    # gelecek (projeksiyon) tarih: cutoff sonrası -> eşleşmez
    assert D.assign_disclosures([pd.Timestamp("2026-09-30")], [pd.Timestamp("2027-01-29")], pd.Timestamp("2026-11-21")) == {}
    # 2026Q2'nin kendi tarihi listede yok; Q3'ün tarihi (119 gün sonra) Q2'ye atanmamalı (azami 65 gün)
    got = D.assign_disclosures([pd.Timestamp("2026-06-30"), pd.Timestamp("2026-09-30")], [pd.Timestamp("2026-10-27")])
    assert got == {pd.Timestamp("2026-09-30"): pd.Timestamp("2026-10-27")}


def test_manual_csv_skips_blank_template_rows_and_validates(tmp_path):
    p = _csv(tmp_path, ["TUPRS,2025Q1,2025-03-31,,,,,,,,,,,", "TUPRS,2025Q2,2025-06-30,2025-08-05,18:40,KAP,STANDALONE,true,1000,100,50,500,100,900"])
    df, notes = D.read_manual_csv(p, load_universe())
    assert len(df) == 1 and df.iloc[0]["fiscal_period"] == "2025Q2" and df.iloc[0]["disclosure_time"] == "18:40"
    assert df.iloc[0]["data_source"] == "KAP_MANUAL" and df.iloc[0]["metric_set"] == "INDUSTRIAL" and len(notes) == 1


@pytest.mark.parametrize("line,msg", [
    ("TUPRS,2025Q2,2025-06-29,2025-08-05,,KAP,STANDALONE,true,1,1,1,1,1,1", "dönem sonu"),
    ("TUPRS,2025Q2,2025-06-30,2025-06-30,,KAP,STANDALONE,true,1,1,1,1,1,1", "sonra olmalı"),
    ("TUPRS,2025Q2,2025-06-30,2025-08-05,,KAP,QUARTER,true,1,1,1,1,1,1", "report_basis"),
    ("ZZZZZ,2025Q2,2025-06-30,2025-08-05,,KAP,STANDALONE,true,1,1,1,1,1,1", "evrende yok"),
])
def test_manual_csv_rejects_bad_rows(tmp_path, line, msg):
    with pytest.raises(ValueError, match=msg):
        D.read_manual_csv(_csv(tmp_path, [line]), load_universe())


def test_ytd_rows_are_differenced_into_standalone(tmp_path):
    p = _csv(tmp_path, ["TUPRS,2025Q1,2025-03-31,2025-05-06,,KAP,YTD,true,100,10,5,50,10,90",
                        "TUPRS,2025Q2,2025-06-30,2025-08-05,,KAP,YTD,true,250,30,12,60,20,95"])
    df, _ = D.read_manual_csv(p, load_universe())
    q2 = df.set_index("fiscal_period").loc["2025Q2"]
    assert (q2["revenue"], q2["ebitda"], q2["net_profit"]) == (150, 20, 7)  # 250-100, 30-10, 12-5
    assert q2["total_financial_debt"] == 60  # bilanço kalemi fark alınmaz
    assert set(df["report_basis"]) == {"YTD_DIFFERENCED"}


def test_ytd_without_previous_quarter_gives_nan_flows(tmp_path):
    df, _ = D.read_manual_csv(_csv(tmp_path, ["TUPRS,2025Q2,2025-06-30,2025-08-05,,KAP,YTD,true,250,30,12,60,20,95"]), load_universe())
    assert np.isnan(df.iloc[0]["revenue"]) and df.iloc[0]["equity"] == 95


def _yahoo_row(fp, rev):
    r = dict.fromkeys(COLUMNS, np.nan)
    r.update(ticker="TUPRS", fiscal_period=fp, period_end_date=pd.Timestamp(D.fp_period_end(fp)), disclosure_date=pd.Timestamp("2026-01-01"),
             disclosure_time=None, disclosure_source="YAHOO_APPROX", data_source="YAHOO", report_basis="STANDALONE",
             tms29_restated=None, metric_set="INDUSTRIAL", revenue=rev)
    return r


def test_manual_overrides_yahoo_per_row_and_pre_2025_dropped(tmp_path):
    y = pd.DataFrame([_yahoo_row("2025Q2", 1.0), _yahoo_row("2025Q3", 2.0), _yahoo_row("2024Q4", 9.0)], columns=COLUMNS)
    m, _ = D.read_manual_csv(_csv(tmp_path, ["TUPRS,2025Q2,2025-06-30,2025-08-05,,KAP,STANDALONE,true,111,1,1,1,1,1"]), load_universe())
    out = D.merge_sources(y, m).set_index("fiscal_period")
    assert list(out.index) == ["2025Q2", "2025Q3"]  # 2024Q4 atıldı (TMS 29 öncesi)
    assert out.loc["2025Q2", "data_source"] == "KAP_MANUAL" and out.loc["2025Q2", "revenue"] == 111
    assert out.loc["2025Q3", "data_source"] == "YAHOO"


def test_snapshot_write_is_immutable_and_loadable(tmp_path):
    y = pd.DataFrame([_yahoo_row("2025Q2", 1.0)], columns=COLUMNS)
    v = "fundamentals_2026-11-21_v1"
    D.write_fundamentals_snapshot(y, tmp_path, v, {"x": 1})
    assert (tmp_path / "LATEST_FUNDAMENTALS").read_text().strip() == v
    f = load_fundamentals(tmp_path)
    assert f.version == v and len(f.table) == 1 and f.manifest["sources"] == {"YAHOO": 1}
    for f in (tmp_path / v / "manifest.json", tmp_path / "LATEST_FUNDAMENTALS"):
        assert chr(13).encode() not in f.read_bytes()  # LF zorunlu
    with pytest.raises(FileExistsError):
        D.write_fundamentals_snapshot(y, tmp_path, v, {})
    with pytest.raises(ValueError):
        D.write_fundamentals_snapshot(y, tmp_path, "snap_2026-11-21_v1", {})


def _frames(cols):
    idx = ["Total Revenue", "EBITDA", "Net Income"]
    inc = pd.DataFrame({pd.Timestamp(c): [1e9 * (i + 1), 1e8, 5e7] for i, c in enumerate(cols)}, index=idx)
    bal = pd.DataFrame({pd.Timestamp(c): [2e9, 1e9, 3e9] for c in cols}, index=["Total Debt", "Cash And Cash Equivalents", "Stockholders Equity"])
    return inc, bal


def test_statutory_date_uses_latest_plausible_deadline_per_quarter():
    assert D.statutory_date(pd.Timestamp("2026-03-31")) == pd.Timestamp("2026-05-15")  # +45
    assert D.statutory_date(pd.Timestamp("2026-06-30")) == pd.Timestamp("2026-09-03")  # +65
    assert D.statutory_date(pd.Timestamp("2026-09-30")) == pd.Timestamp("2026-11-14")  # +45
    assert D.statutory_date(pd.Timestamp("2025-12-31")) == pd.Timestamp("2026-03-16")  # +75


def test_rows_from_frames_matched_get_yahoo_approx_unmatched_get_statutory():
    inc, bal = _frames(["2026-03-31", "2026-06-30", "2025-06-30"])
    ed = [pd.Timestamp("2026-08-04 03:00"), pd.Timestamp("2027-01-01")]  # yalnız 2026Q2 eşleşir; 2027 projeksiyonu
    df = D.rows_from_frames("THYAO", "INDUSTRIAL", inc, bal, ed, pd.Timestamp("2026-11-21")).set_index("fiscal_period")
    assert df.loc["2026Q2", "disclosure_source"] == "YAHOO_APPROX" and df.loc["2026Q2", "disclosure_date"] == pd.Timestamp("2026-08-04")
    assert df.loc["2026Q1", "disclosure_source"] == "STATUTORY_DEADLINE" and df.loc["2026Q1", "disclosure_date"] == pd.Timestamp("2026-05-15")
    assert df.loc["2025Q2", "disclosure_source"] == "STATUTORY_DEADLINE" and df.loc["2025Q2", "disclosure_date"] == pd.Timestamp("2025-09-03")
    assert set(df["data_source"]) == {"YAHOO"} and df["disclosure_time"].isna().all()
    assert df.loc["2026Q2", "revenue"] == 2000.0 and df.loc["2026Q2", "total_financial_debt"] == 2000.0  # TL -> milyon TL


def test_rows_from_frames_skips_periods_without_financials_and_pre_2025():
    inc = pd.DataFrame({pd.Timestamp("2026-03-31"): [None, None, None], pd.Timestamp("2024-12-31"): [1e9, 1e8, 5e7]},
                       index=["Total Revenue", "EBITDA", "Net Income"])
    bal = pd.DataFrame({pd.Timestamp("2026-03-31"): [None, None, None]}, index=["Total Debt", "Cash And Cash Equivalents", "Stockholders Equity"])
    assert D.rows_from_frames("THYAO", "INDUSTRIAL", inc, bal, [], pd.Timestamp("2026-11-21")).empty


def test_manual_kap_row_overrides_statutory_row(tmp_path):
    inc, bal = _frames(["2026-03-31"])
    y = D.rows_from_frames("TUPRS", "INDUSTRIAL", inc, bal, [], pd.Timestamp("2026-11-21"))
    m, _ = D.read_manual_csv(_csv(tmp_path, ["TUPRS,2026Q1,2026-03-31,2026-05-06,18:30,KAP,STANDALONE,true,111,1,1,1,1,1"]), load_universe())
    out = D.merge_sources(y, m).iloc[0]
    assert out["disclosure_source"] == "KAP_MANUAL" and out["disclosure_date"] == pd.Timestamp("2026-05-06")
