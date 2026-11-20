"""BIST fiyat verisini Yahoo Finance'ten BİR KEZ indirir ve sürümlü snapshot olarak yazar.

TEK AĞ ERİŞİMİ olan yerlerden biri budur (CLAUDE.md kural 3): araçlar (tools/) yalnızca snapshot okur.

Kullanım:
    python -m scripts.download_prices                 # 2023-01-01'den bugüne, 30 hisse + XU100
    python -m scripts.download_prices --start 2023-01-01 --allow-partial

Çıktı: data/snapshots/<data_version>/{stocks.parquet, index.parquet, manifest.json} ve data/snapshots/LATEST.
Politikalar (adjusted/unadjusted, eksik gün, yarım mum) docs/data_dictionary.md §11'de.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from config.settings import (
    ANALYSIS_START_DEFAULT,
    DOWNLOAD_START,
    PRICE_JUMP_LIMIT_PCT,
    PRICE_JUMP_TOLERANCE_PP,
    SNAPSHOT_DIR,
)
from config.universe import load_universe
from tools.price_quality import price_jump_report  # noqa: F401  (tek tanım tools/price_quality.py'de)

INDEX_SYMBOL = "XU100.IS"  # '^XU100' Yahoo'da yok (404); doğrulandı: XU100.IS çalışıyor.
ISTANBUL = ZoneInfo("Europe/Istanbul")
# BIST seansı 18:00'de biter; kapanış işlemleri ve veri oturması için güvenli sınır 18:30.
SESSION_FINALIZED_AT = dtime(18, 30)

CANONICAL_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]
INDEX_COLUMNS = [c for c in CANONICAL_COLUMNS if c != "ticker"]

_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
           "Volume": "volume", "Dividends": "dividends", "Stock Splits": "stock_splits"}
_PRICE_COLS = ["open", "high", "low", "close", "adj_close"]

PRICE_POLICY = {
    "default_price_field": "adj_close",
    "adjusted": "Yahoo 'Adj Close' (bölünme + temettü düzeltmeli). Araçlarda adjusted modda open/high/low/close "
                "= ham değer * (adj_close/close); close = adj_close.",
    "unadjusted": "Yahoo 'Close/Open/High/Low' (bölünme/bedelsiz düzeltmeli, TEMETTÜ düzeltmesiz). Yahoo gerçek "
                  "'ham' (hiç düzeltilmemiş) fiyat vermez.",
    "missing_days": "Eksik günler DOLDURULMAZ (forward-fill yok). Close/OHLC NaN veya close <= 0 satırlar atılır; "
                    "yinelenen tarihlerde son satır tutulur. Eksik işlem günü, check_data_quality ile XU100 "
                    "takvimine göre raporlanır.",
    "incomplete_bar": "İndirme günü, seans sonu (18:30 İstanbul) öncesi alınan o güne ait yarım mum atılır.",
}


def normalize_frame(raw: pd.DataFrame, ticker: str | None) -> pd.DataFrame:
    """Yahoo history çıktısını kanonik, saat dilimsiz, sıralı ve temiz tabloya çevirir.

    ticker=None ise (endeks) 'ticker' sütunu olmaz. Atılan satır sayıları df.attrs['dropped'] içinde.
    """
    df = raw.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)  # yerel (İstanbul) duvar saati korunur -> tarih kayması yok
    df.index = idx.normalize()
    df = df.rename(columns=_RENAME)
    for c in ("dividends", "stock_splits"):
        if c not in df.columns:
            df[c] = 0.0
    df = df[["open", "high", "low", "close", "adj_close", "volume", "dividends", "stock_splits"]].astype("float64")
    df = df.rename_axis("date").reset_index()
    df["date"] = df["date"].astype("datetime64[ns]")

    n0 = len(df)
    bad = df[_PRICE_COLS].isna().any(axis=1) | (df["close"] <= 0) | (df["adj_close"] <= 0)
    df = df.loc[~bad]
    n_bad = n0 - len(df)
    df = df.sort_values("date", kind="stable")
    n1 = len(df)
    df = df.drop_duplicates(subset="date", keep="last")
    n_dup = n1 - len(df)
    df["volume"] = df["volume"].fillna(0.0)
    df["dividends"] = df["dividends"].fillna(0.0)
    df["stock_splits"] = df["stock_splits"].fillna(0.0)
    if ticker is not None:
        df.insert(0, "ticker", ticker)
    df = df.reset_index(drop=True)
    df.attrs["dropped"] = {"nan_or_nonpositive_price": int(n_bad), "duplicate_date": int(n_dup)}
    return df


def drop_incomplete_last_bar(df: pd.DataFrame, now_local: datetime) -> pd.DataFrame:
    """İndirme günü seans bitmeden alınan (yarım) mumu atar; geçmiş günlere dokunmaz."""
    if df.empty:
        return df
    today = pd.Timestamp(now_local.astimezone(ISTANBUL).date())
    if now_local.astimezone(ISTANBUL).time() < SESSION_FINALIZED_AT:
        return df.loc[df["date"] < today].reset_index(drop=True)
    return df


def next_data_version(root: Path, today: date) -> str:
    """snap_YYYY-MM-DD_vN; aynı gün için N, mevcut klasörlere göre artar."""
    n = 1
    while (Path(root) / f"snap_{today.isoformat()}_v{n}").exists():
        n += 1
    return f"snap_{today.isoformat()}_v{n}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(df: pd.DataFrame) -> dict:
    return {"rows": int(len(df)), "first_date": df["date"].min().date().isoformat() if len(df) else None,
            "last_date": df["date"].max().date().isoformat() if len(df) else None}


def write_snapshot(stocks: pd.DataFrame, index: pd.DataFrame, root: Path, data_version: str, meta: dict) -> str:
    """Snapshot klasörünü yazar; var olan sürümün üzerine ASLA yazmaz. LATEST'i günceller."""
    root = Path(root)
    d = root / data_version
    if d.exists():
        raise FileExistsError(f"{d} zaten var; snapshot sürümleri değiştirilemez")
    stocks = stocks[CANONICAL_COLUMNS].sort_values(["ticker", "date"]).reset_index(drop=True)
    index = index.drop(columns=["ticker"], errors="ignore")[INDEX_COLUMNS].sort_values("date").reset_index(drop=True)
    d.mkdir(parents=True)
    stocks.to_parquet(d / "stocks.parquet", index=False)
    index.to_parquet(d / "index.parquet", index=False)
    manifest = {
        "data_version": data_version,
        "created_utc": datetime.now(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **meta,
        "files": {
            "stocks.parquet": {"rows": int(len(stocks)), "sha256": _sha256(d / "stocks.parquet")},
            "index.parquet": {"rows": int(len(index)), "sha256": _sha256(d / "index.parquet")},
        },
        "per_ticker": {tk: _summary(g) for tk, g in stocks.groupby("ticker")},
        "index_summary": _summary(index),
    }
    # LF'e sabit, bayt düzeyinde yaz: manifest'lerin sha256'sı başka manifest'lere yazılıyor (derived_from);
    # Windows'ta write_text CRLF üretir ve hash makineler arasında tutmaz.
    (d / "manifest.json").write_bytes(
        (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    (root / "LATEST").write_bytes((data_version + "\n").encode("utf-8"))
    return data_version


# --- Ağ (yalnızca burada) ---------------------------------------------------------------------
def fetch_yahoo(symbol: str, start: date, retries: int = 3) -> pd.DataFrame:
    import yfinance as yf  # ağ kütüphanesi yalnızca scripts/ içinde import edilir

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = yf.Ticker(symbol).history(start=start.isoformat(), auto_adjust=False, actions=True)
            if len(raw):
                return raw
            last_err = RuntimeError("boş yanıt")
        except Exception as e:  # noqa: BLE001
            last_err = e
        time.sleep(2 * attempt)
    raise RuntimeError(f"{symbol}: indirilemedi ({last_err!r})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, default=DOWNLOAD_START,
                    help="indirme başlangıcı (indikatör ısınması için analiz penceresinden önce)")
    ap.add_argument("--analysis-start", type=date.fromisoformat, default=ANALYSIS_START_DEFAULT)
    ap.add_argument("--out", type=Path, default=SNAPSHOT_DIR)
    ap.add_argument("--allow-partial", action="store_true", help="bazı semboller inmezse de snapshot yaz")
    args = ap.parse_args(argv)

    import yfinance as yf

    now_local = datetime.now(ISTANBUL)
    universe = load_universe()
    stocks_frames, failed, dropped = [], {}, {}
    for _, r in universe.iterrows():
        try:
            f = normalize_frame(fetch_yahoo(r["yahoo_symbol"], args.start), r["ticker"])
            stocks_frames.append(drop_incomplete_last_bar(f, now_local))
            dropped[r["ticker"]] = f.attrs.get("dropped", {})
            print(f"  {r['ticker']:6s} {len(f):4d} satır  {f['date'].min().date()} -> {f['date'].max().date()}")
        except Exception as e:  # noqa: BLE001
            failed[r["ticker"]] = repr(e)
            print(f"  {r['ticker']:6s} HATA: {e}", file=sys.stderr)
    try:
        idx = normalize_frame(fetch_yahoo(INDEX_SYMBOL, args.start), None)
        idx = drop_incomplete_last_bar(idx, now_local)
        print(f"  XU100  {len(idx):4d} satır  {idx['date'].min().date()} -> {idx['date'].max().date()}")
    except Exception as e:  # noqa: BLE001
        failed["XU100"] = repr(e)
        idx = pd.DataFrame(columns=INDEX_COLUMNS)

    if failed and not args.allow_partial:
        print(f"\nİNDİRİLEMEYENLER: {failed}\nSnapshot YAZILMADI (--allow-partial ile zorlanabilir).", file=sys.stderr)
        return 1

    stocks = pd.concat(stocks_frames, ignore_index=True)
    version = next_data_version(args.out, now_local.date())
    meta = {
        "source": f"Yahoo Finance via yfinance {yf.__version__}",
        "download_start": args.start.isoformat(),
        "analysis_start_default": args.analysis_start.isoformat(),
        "downloaded_at_istanbul": now_local.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "index_symbol": INDEX_SYMBOL,
        "price_policy": PRICE_POLICY,
        "price_jump_limit_pct": PRICE_JUMP_LIMIT_PCT,
        "price_jump_tolerance_pp": PRICE_JUMP_TOLERANCE_PP,
        "price_jump_report": price_jump_report(stocks) + [dict(r, ticker="XU100") for r in price_jump_report(idx)],
        "dropped_rows": dropped,
        "failed_symbols": failed,
    }
    write_snapshot(stocks, idx, args.out, version, meta)
    print(f"\nSnapshot yazıldı: {args.out / version}  (LATEST -> {version})")
    print(f"Limit aşan günlük sıçrama sayısı: {len(meta['price_jump_report'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
