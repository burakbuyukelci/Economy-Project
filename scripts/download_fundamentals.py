"""Bilanço veri seti indirici (AĞ KULLANAN TEK YER; araçlar çalışma zamanında ağ kullanmaz, kural 3).

Çıktı: data/snapshots/fundamentals_<tarih>_v<N>/{fundamentals.parquet, manifest.json} + data/snapshots/LATEST_FUNDAMENTALS.
Kaynaklar (satır bazında `data_source`):
  * YAHOO      : yfinance çeyreklik gelir tablosu/bilanço, 2025Q1+ (delikli olabilir; boş satırlar atlanır).
  * KAP_MANUAL : data/raw/fundamentals_kap.csv (elle, resmî KAP). Aynı (ticker, dönem) için CSV, Yahoo'yu EZER (satır bazında).
Açıklama tarihi: Yahoo `earnings_dates` ABD saatiyle damgalı -> Europe/Istanbul'a çevrilir, `disclosure_source=YAHOO_APPROX`,
saat BELİRSİZ kabul edilir (disclosure_time boş; tepki bazı muhafazakâr). Eşleşmeyen dönemde `STATUTORY_DEADLINE`:
görünürlük tarihi = dönem sonu + yasal süre (geç olan; muhafazakâr); bu satırlar fiyat tepkisine GİRMEZ. KAP_MANUAL satırlarda tarih/saat resmî KAP'tan.
Kullanım: python -m scripts.download_fundamentals [--date 2026-11-21] [--no-yahoo] [--tickers TUPRS,AKBNK]
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import REPO_ROOT, SNAPSHOT_DIR
from tools._fundamentals import COLUMNS, FLOW_COLS, FUNDAMENTALS_VERSION_RE, fp_period_end, fp_shift

FIRST_PERIOD_END = pd.Timestamp("2025-01-01")  # kural 7: ana analiz TMS 29 sonrası
MANUAL_CSV = REPO_ROOT / "data" / "raw" / "fundamentals_kap.csv"
MANUAL_COLUMNS = ["ticker", "fiscal_period", "period_end_date", "disclosure_date", "disclosure_time", "source", "report_basis",
                  "tms29_restated", "revenue", "ebitda", "net_profit", "total_financial_debt", "cash_and_equivalents", "equity"]
NUMERIC = ["revenue", "ebitda", "net_profit", "total_financial_debt", "cash_and_equivalents", "equity", "net_interest_income"]
# Yahoo satır adı adayları (öncelik sırasıyla) -> bizim sütun; birim: TL -> milyon TL
YAHOO_ROWS = {
    "revenue": ["Total Revenue"], "ebitda": ["EBITDA", "Normalized EBITDA"], "net_profit": ["Net Income", "Net Income Common Stockholders"],
    "total_financial_debt": ["Total Debt"], "cash_and_equivalents": ["Cash And Cash Equivalents"],
    "equity": ["Stockholders Equity", "Common Stock Equity"], "net_interest_income": ["Net Interest Income"],
}
# Çeyreğe göre azami açıklama gecikmesi (gün): SPK yasal süreleri (konsolide: 3/9 ay 40, 6 ay 60, yıllık 70 gün) + küçük pay.
# Daha geç görünen Yahoo tarihi o dönemin değil başka dönemin (veya projeksiyonun) tarihi sayılır, eşleştirilmez.
MAX_DISCLOSURE_LAG_DAYS = {1: 45, 2: 65, 3: 45, 4: 75}


def fiscal_period_of(period_end: pd.Timestamp) -> str:
    return f"{period_end.year}Q{(period_end.month - 1) // 3 + 1}"


# --- elle CSV --------------------------------------------------------------------------------------
def read_manual_csv(path: Path, universe: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Elle CSV'yi doğrular ve standart sütunlara çevirir. Dönüş (tablo, atlanan_satır_notları).

    Atlanan: disclosure_date boş veya hiçbir finansal alanı dolu olmayan satırlar (şablonun boş satırları Yahoo'yu EZMEZ)."""
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS), []
    raw = pd.read_csv(path, dtype=str).apply(lambda s: s.str.strip() if s.dtype == object else s)
    miss = [c for c in MANUAL_COLUMNS if c not in raw.columns]
    if miss:
        raise ValueError(f"{path.name}: eksik sütun(lar): {miss}")
    notes: list[str] = []
    out = []
    mset = dict(zip(universe["ticker"], np.where(universe["sector_label"].str.contains("Bank", case=False), "BANK", "INDUSTRIAL")))
    for i, r in raw.iterrows():
        fin = [r[c] for c in ("revenue", "ebitda", "net_profit", "total_financial_debt", "cash_and_equivalents", "equity")]
        if pd.isna(r["disclosure_date"]) or all(pd.isna(x) for x in fin):
            notes.append(f"satır {i + 2} ({r['ticker']} {r['fiscal_period']}): boş, atlandı")
            continue
        if r["ticker"] not in mset:
            raise ValueError(f"satır {i + 2}: {r['ticker']} evrende yok")
        fp = r["fiscal_period"]
        pe = pd.Timestamp(r["period_end_date"])
        if pd.Timestamp(fp_period_end(fp)) != pe:
            raise ValueError(f"satır {i + 2}: {fp} dönem sonu {fp_period_end(fp)} olmalı, CSV'de {r['period_end_date']}")
        dd = pd.Timestamp(r["disclosure_date"])
        if dd <= pe:
            raise ValueError(f"satır {i + 2}: disclosure_date ({dd.date()}) dönem sonundan ({pe.date()}) sonra olmalı")
        basis = (r["report_basis"] or "STANDALONE").upper() if pd.notna(r["report_basis"]) else "STANDALONE"
        if basis not in ("STANDALONE", "YTD"):
            raise ValueError(f"satır {i + 2}: report_basis STANDALONE|YTD olmalı")
        t = r["disclosure_time"] if pd.notna(r["disclosure_time"]) else None
        if t is not None:
            datetime.strptime(t, "%H:%M")
        row = {"ticker": r["ticker"], "fiscal_period": fp, "period_end_date": pe, "disclosure_date": dd, "disclosure_time": t,
               "disclosure_source": "KAP_MANUAL", "data_source": "KAP_MANUAL", "report_basis": basis,
               "tms29_restated": (str(r["tms29_restated"]).lower() == "true") if pd.notna(r["tms29_restated"]) else None,
               "metric_set": mset[r["ticker"]], "net_interest_income": np.nan}
        for c in ("revenue", "ebitda", "net_profit", "total_financial_debt", "cash_and_equivalents", "equity"):
            row[c] = float(r[c]) if pd.notna(r[c]) else np.nan
        out.append(row)
    df = pd.DataFrame(out, columns=COLUMNS) if out else pd.DataFrame(columns=COLUMNS)
    return derive_standalone(df), notes


def derive_standalone(df: pd.DataFrame) -> pd.DataFrame:
    """report_basis=YTD satırlarda akış kalemlerini çeyreklik farka çevirir: Q2 = YTD(Q2) - YTD(Q1) vb. (Q1 aynen).

    Önceki YTD satırı yoksa akışlar NaN olur. Sonuç report_basis='YTD_DIFFERENCED'. UYARI: TMS 29'da her rapor kendi dönem sonu
    satın alma gücündedir; farklı raporların YTD'lerinin farkı birim karışımı içerir (docs/fundamentals_toplama.md)."""
    if df.empty or not (df["report_basis"] == "YTD").any():
        return df
    df = df.copy()
    ytd = df.loc[df["report_basis"] == "YTD"].set_index(["ticker", "fiscal_period"])
    for idx in df.index[df["report_basis"] == "YTD"]:
        t, fp = df.at[idx, "ticker"], df.at[idx, "fiscal_period"]
        if fp.endswith("Q1"):
            df.at[idx, "report_basis"] = "YTD_DIFFERENCED"
            continue
        prev = (t, fp_shift(fp, -1))
        for c in FLOW_COLS:
            cur = df.at[idx, c]
            df.at[idx, c] = cur - ytd.at[prev, c] if prev in ytd.index and pd.notna(cur) and pd.notna(ytd.at[prev, c]) else np.nan
        df.at[idx, "report_basis"] = "YTD_DIFFERENCED"
    return df


# --- Yahoo -----------------------------------------------------------------------------------------
def assign_disclosures(period_ends: list[pd.Timestamp], earnings_dates: list[pd.Timestamp],
                       cutoff: pd.Timestamp | None = None) -> dict[pd.Timestamp, pd.Timestamp]:
    """Her dönem sonu için, dönem sonundan SONRA ve çeyreğin azami gecikmesi içindeki İLK Yahoo tarihini (İstanbul tarihi) seçer.

    Kurallar (Yahoo tarihleri güvenilmezdir; ARCLK 2026Q3 -> 2027 projeksiyonu, ASELS 2026Q2 -> başka çeyreğin tarihi görüldü):
      * `cutoff` (indirme günü) SONRASI tarih projeksiyondur -> kullanılmaz.
      * Bir tarih yalnızca BİR döneme atanır (önce eski dönem).
    earnings_dates: tz-naive İstanbul zamanı. Eşleşme yoksa dönem eşleşmez (çağıran yasal süre görünürlüğüne düşer). Örn. TUPRS 2025Q2 (30 Haz) -> 2025-07-29."""
    out: dict[pd.Timestamp, pd.Timestamp] = {}
    used: set[pd.Timestamp] = set()
    eds = sorted({e.normalize() for e in earnings_dates if cutoff is None or e.normalize() <= cutoff})
    for pe in sorted(period_ends):
        q = (pe.month - 1) // 3 + 1
        for ed in eds:
            if ed > pe and (ed - pe).days <= MAX_DISCLOSURE_LAG_DAYS[q] and ed not in used:
                out[pe] = ed
                used.add(ed)
                break
    return out


def _pick(frame: pd.DataFrame, names: list[str], col) -> float:
    for n in names:
        if n in frame.index and pd.notna(frame.at[n, col]):
            return float(frame.at[n, col]) / 1e6
    return np.nan


def statutory_date(period_end: pd.Timestamp) -> pd.Timestamp:
    """Açıklama tarihi bilinmeyen dönem için GÖRÜNÜRLÜK tarihi = dönem sonu + yasal süre (muhafazakâr: geç olan; MAX_DISCLOSURE_LAG_DAYS).

    Gerçek açıklama bundan önce olmuş olabilir; veri as_of'ta bu tarihe kadar GİZLENİR (sızıntıdan kaçınmak için). Bu satırlar fiyat tepkisine girmez."""
    return period_end.normalize() + pd.Timedelta(days=MAX_DISCLOSURE_LAG_DAYS[(period_end.month - 1) // 3 + 1])


def rows_from_frames(ticker: str, metric_set: str, inc: pd.DataFrame, bal: pd.DataFrame, ed_ist: list[pd.Timestamp],
                     cutoff: pd.Timestamp) -> pd.DataFrame:
    """Yahoo tabloları + İstanbul saatli earnings tarihleri -> satırlar (saf; testlerde sınanır).

    Tarih eşleşirse `YAHOO_APPROX`; eşleşmezse `STATUTORY_DEADLINE` (görünürlük = dönem sonu + yasal süre). Finansal değeri olmayan dönem alınmaz."""
    cols = sorted(set(inc.columns) | set(bal.columns))
    period_ends = [pd.Timestamp(c) for c in cols if pd.Timestamp(c) >= FIRST_PERIOD_END]
    disc = assign_disclosures(period_ends, ed_ist, cutoff)
    rows = []
    for pe in period_ends:
        vals = {}
        for k, names in YAHOO_ROWS.items():
            src = inc if k in ("revenue", "ebitda", "net_profit", "net_interest_income") else bal
            vals[k] = _pick(src, names, pe) if pe in src.columns else np.nan
        if all(pd.isna(vals[k]) for k in ("revenue", "ebitda", "net_profit", "total_financial_debt", "equity", "net_interest_income")):
            continue
        matched = pe in disc
        rows.append({"ticker": ticker, "fiscal_period": fiscal_period_of(pe), "period_end_date": pe,
                     "disclosure_date": disc[pe] if matched else statutory_date(pe), "disclosure_time": None,
                     "disclosure_source": "YAHOO_APPROX" if matched else "STATUTORY_DEADLINE", "data_source": "YAHOO",
                     "report_basis": "STANDALONE", "tms29_restated": None, "metric_set": metric_set, **vals})
    return pd.DataFrame(rows, columns=COLUMNS)


def yahoo_rows(ticker: str, yahoo_symbol: str, metric_set: str) -> pd.DataFrame:  # pragma: no cover - ağ
    import warnings
    import yfinance as yf
    warnings.filterwarnings("ignore")
    t = yf.Ticker(yahoo_symbol)
    ed = t.get_earnings_dates(limit=24)
    ed_ist = [] if ed is None or ed.empty else [x.tz_convert("Europe/Istanbul").tz_localize(None) for x in ed.index]
    return rows_from_frames(ticker, metric_set, t.quarterly_income_stmt, t.quarterly_balance_sheet, ed_ist, pd.Timestamp(date.today()))


# --- birleştirme + yazım ---------------------------------------------------------------------------
def merge_sources(yahoo: pd.DataFrame, manual: pd.DataFrame) -> pd.DataFrame:
    """CSV varsa Yahoo'yu EZER (aynı ticker+dönem, satır bazında). Yalnızca 2025+ dönemler. Sıralı, tekrarsız."""
    both = pd.concat([x for x in (yahoo, manual) if len(x)], ignore_index=True) if (len(yahoo) or len(manual)) else pd.DataFrame(columns=COLUMNS)
    if both.empty:
        return both
    both["_pri"] = (both["data_source"] == "KAP_MANUAL").astype(int)
    both = both.sort_values(["ticker", "fiscal_period", "_pri"]).drop_duplicates(["ticker", "fiscal_period"], keep="last").drop(columns="_pri")
    both = both.loc[pd.to_datetime(both["period_end_date"]) >= FIRST_PERIOD_END]
    return both[COLUMNS].sort_values(["ticker", "period_end_date"]).reset_index(drop=True)


def write_fundamentals_snapshot(df: pd.DataFrame, root: Path, version: str, meta: dict) -> Path:
    if not FUNDAMENTALS_VERSION_RE.match(version):
        raise ValueError(f"sürüm biçimi fundamentals_YYYY-MM-DD_vN olmalı: {version}")
    d = Path(root) / version
    if d.exists():
        raise FileExistsError(f"{d} zaten var (snapshot'lar değişmez; yeni sürüm numarası kullanın)")
    d.mkdir(parents=True)
    out = df.copy()
    for c in ("period_end_date", "disclosure_date"):
        out[c] = pd.to_datetime(out[c])
    out["tms29_restated"] = out["tms29_restated"].astype("object")
    out.to_parquet(d / "fundamentals.parquet", index=False)
    manifest = {"data_version": version, "n_rows": int(len(out)), "tickers": sorted(set(out["ticker"])),
                "sources": {k: int(v) for k, v in out["data_source"].value_counts().items()},
                "disclosure_sources": {k: int(v) for k, v in out["disclosure_source"].value_counts().items()}, "unit": "TRY_mn",
                "first_period_end": str(out["period_end_date"].min().date()) if len(out) else None, **meta}
    # LF zorunlu: Windows'ta write_text CRLF üretir; hash/karşılaştırma her makinede aynı olmalı
    with open(d / "manifest.json", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(manifest, indent=2, ensure_ascii=False, default=str) + "\n")
    with open(Path(root) / "LATEST_FUNDAMENTALS", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(version + "\n")
    return d


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - ağ
    from config.universe import load_universe
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--version-no", type=int, default=1)
    ap.add_argument("--no-yahoo", action="store_true")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--manual", default=str(MANUAL_CSV))
    a = ap.parse_args(argv)
    uni = load_universe()
    if a.tickers:
        uni = uni[uni["ticker"].isin(a.tickers.split(","))]
    manual, notes = read_manual_csv(Path(a.manual), load_universe())
    frames = []
    if not a.no_yahoo:
        for _, u in uni.iterrows():
            ms = "BANK" if "bank" in str(u["sector_label"]).lower() else "INDUSTRIAL"
            try:
                f = yahoo_rows(u["ticker"], u["yahoo_symbol"], ms)
            except Exception as e:  # tek hissenin hatası tümünü durdurmasın; manifest'e yazılır
                notes.append(f"{u['ticker']}: Yahoo hatası {type(e).__name__}")
                continue
            frames.append(f)
            print(f"{u['ticker']}: Yahoo {len(f)} dönem")
    yahoo = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
    df = merge_sources(yahoo, manual)
    version = f"fundamentals_{a.date}_v{a.version_no}"
    meta = {"created": a.date, "yahoo_used": not a.no_yahoo, "manual_csv": Path(a.manual).name, "notes": notes,
            "disclosure_rule": "YAHOO_APPROX: Yahoo earnings_dates ABD->Istanbul, saat belirsiz; KAP_MANUAL: resmi KAP"}
    d = write_fundamentals_snapshot(df, SNAPSHOT_DIR, version, meta)
    print(f"yazıldı: {d} ({len(df)} satır)")


if __name__ == "__main__":  # pragma: no cover
    main()
