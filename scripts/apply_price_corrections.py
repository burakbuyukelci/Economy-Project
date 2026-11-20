"""Fiyat düzeltme katmanı: v2 = f(v1, config/price_corrections.csv). AĞ KULLANMAZ, saattten bağımsızdır.

Kaynak snapshot'a (v1) DOKUNMAZ; düzeltilmiş veriyi YENİ bir sürüm olarak yazar. Manifest'e düzeltmeler,
csv'nin sha256'sı ve kaynak snapshot'ın sha256'ları yazılır. Aynı (v1, csv) çifti her zaman aynı veriyi üretir.

Kullanım:
    python -m scripts.apply_price_corrections --src snap_2026-11-20_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import pandas as pd

from config.settings import (
    PRICE_CORRECTIONS_CSV,
    PRICE_JUMP_LIMIT_PCT,
    PRICE_JUMP_TOLERANCE_PP,
    SNAPSHOT_DIR,
)
from config.universe import load_universe
from scripts.download_prices import write_snapshot
from tools.price_quality import price_jump_report

REQUIRED_COLUMNS = ["ticker", "date_from", "date_to", "price_divisor", "volume_multiplier", "source"]
# Fiyat birimindeki alanlar bölünür; hacim çarpılır; `stock_splits` (Yahoo kaydı) dokunulmaz.
PRICE_FIELDS = ["open", "high", "low", "close", "adj_close", "dividends"]
_DERIVED_DROP = {"data_version", "created_utc", "files", "per_ticker", "index_summary", "price_jump_report"}
_VERSION_RE = re.compile(r"^snap_(\d{4}-\d{2}-\d{2})_v(\d+)$")


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def load_corrections(csv_path: Path, valid_tickers: set[str] | None = None) -> pd.DataFrame:
    """csv'yi okuyup doğrular. Boş date_from/date_to = sınırsız. Aralıklar dahildir."""
    raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"{csv_path}: eksik sütun(lar): {missing}")
    tickers = valid_tickers if valid_tickers is not None else set(load_universe()["ticker"])

    rows = []
    for n, r in raw.iterrows():
        where = f"{Path(csv_path).name} satır {n + 2}"
        if r["ticker"] not in tickers:
            raise ValueError(f"{where}: ticker '{r['ticker']}' evrende (config/universe.csv) yok")
        if not r["source"].strip():
            raise ValueError(f"{where}: source boş olamaz (ör. 'KAP bildirim <no>')")
        vals = {}
        for col in ("price_divisor", "volume_multiplier"):
            try:
                vals[col] = float(r[col])
            except ValueError:
                raise ValueError(f"{where}: {col} sayı olmalı: {r[col]!r}") from None
            if not vals[col] > 0:
                raise ValueError(f"{where}: {col} > 0 olmalı: {r[col]!r}")
        dts = {}
        for col in ("date_from", "date_to"):
            try:
                dts[col] = pd.Timestamp(r[col]) if r[col].strip() else pd.NaT
            except ValueError:
                raise ValueError(f"{where}: {col} geçerli bir tarih olmalı: {r[col]!r}") from None
        if pd.notna(dts["date_from"]) and pd.notna(dts["date_to"]) and dts["date_from"] > dts["date_to"]:
            raise ValueError(f"{where}: date_from > date_to")
        rows.append({"ticker": r["ticker"], **dts, **vals, "source": r["source"].strip()})
    out = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)

    # Aynı hissede çakışan kural olmasın (çifte düzeltme riski)
    for tk, g in out.groupby("ticker"):
        spans = sorted((r.date_from if pd.notna(r.date_from) else pd.Timestamp.min,
                        r.date_to if pd.notna(r.date_to) else pd.Timestamp.max) for r in g.itertuples())
        for (a0, a1), (b0, b1) in zip(spans, spans[1:]):
            if b0 <= a1:
                raise ValueError(f"{tk}: kurallar çakışıyor ({a0.date()}..{a1.date()} ile {b0.date()}..{b1.date()})")
    return out


def _iso(ts) -> str | None:
    return None if pd.isna(ts) else ts.date().isoformat()


def _num(x: float):
    return int(x) if float(x).is_integer() else float(x)


def apply_corrections(stocks: pd.DataFrame, corrections: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """Düzeltilmiş KOPYA ve uygulanan kuralların özeti. Girdiyi değiştirmez."""
    out = stocks.copy()
    applied: list[dict] = []
    for r in corrections.itertuples():
        mask = out["ticker"] == r.ticker
        if pd.notna(r.date_from):
            mask &= out["date"] >= r.date_from
        if pd.notna(r.date_to):
            mask &= out["date"] <= r.date_to
        n = int(mask.sum())
        if n == 0:
            raise ValueError(f"{r.ticker}: kural hiç satır etkilemiyor ({_iso(r.date_from)}..{_iso(r.date_to)})")
        out.loc[mask, PRICE_FIELDS] = out.loc[mask, PRICE_FIELDS] / r.price_divisor
        out.loc[mask, "volume"] = out.loc[mask, "volume"] * r.volume_multiplier
        applied.append({
            "ticker": r.ticker, "date_from": _iso(r.date_from), "date_to": _iso(r.date_to),
            "price_divisor": _num(r.price_divisor), "volume_multiplier": _num(r.volume_multiplier),
            "source": r.source, "n_rows_affected": n,
            "price_fields_divided": list(PRICE_FIELDS), "volume_multiplied": True,
            "untouched_fields": ["stock_splits"],
        })
    return out, applied


def build_corrected_snapshot(
    src_root: Path, src_version: str, csv_path: Path, out_root: Path, out_version: str | None = None,
) -> str:
    """Kaynak snapshot'tan düzeltilmiş yeni sürüm üretir. Kaynak dosyalar yalnızca OKUNUR."""
    src_dir = Path(src_root) / src_version
    man_path = src_dir / "manifest.json"
    src_man = json.loads(man_path.read_text(encoding="utf-8"))
    for name, info in src_man["files"].items():  # kaynak bütünlüğü: bozulmuş/oynanmış v1'den türetme
        if _sha256(src_dir / name) != info["sha256"]:
            raise ValueError(f"{src_version}/{name} sha256 manifest ile uyuşmuyor; kaynak bozulmuş")

    stocks = pd.read_parquet(src_dir / "stocks.parquet")
    index = pd.read_parquet(src_dir / "index.parquet")
    corrections = load_corrections(csv_path)
    fixed, applied = apply_corrections(stocks, corrections)

    if out_version is None:
        m = _VERSION_RE.match(src_version)
        if not m:
            raise ValueError(f"data_version biçimi tanınmadı: {src_version}")
        n = int(m.group(2)) + 1
        while (Path(out_root) / f"snap_{m.group(1)}_v{n}").exists():
            n += 1
        out_version = f"snap_{m.group(1)}_v{n}"

    limit = src_man.get("price_jump_limit_pct", PRICE_JUMP_LIMIT_PCT)
    tol = src_man.get("price_jump_tolerance_pp", PRICE_JUMP_TOLERANCE_PP)
    policy = dict(src_man.get("price_policy", {}))
    policy["corrections"] = (
        "config/price_corrections.csv kurallarına göre belirtilen hisse/tarih aralığında open/high/low/close/"
        "adj_close/dividends ÷ price_divisor, volume × volume_multiplier; stock_splits dokunulmaz. "
        "Ayrıntı: corrections_applied ve docs/data_dictionary.md §12."
    )
    meta = {k: v for k, v in src_man.items() if k not in _DERIVED_DROP}
    meta.update({
        "price_policy": policy,
        # Duvar saati yok: türetme deterministik olsun diye kaynağın zamanı miras alınır.
        "created_utc": src_man["created_utc"],
        "created_utc_note": "kaynak snapshot'tan miras; türetme deterministiktir, duvar saati içermez",
        "derived_from": {
            "data_version": src_version,
            "manifest_sha256": _sha256(man_path),
            "stocks_sha256": src_man["files"]["stocks.parquet"]["sha256"],
            "index_sha256": src_man["files"]["index.parquet"]["sha256"],
        },
        "corrections_csv": {"file": Path(csv_path).name, "sha256": _sha256(csv_path)},
        "corrections_applied": applied,
        "price_jump_report": price_jump_report(fixed, limit, tol)
        + [dict(r, ticker="XU100") for r in price_jump_report(index, limit, tol)],
    })
    return write_snapshot(fixed, index, Path(out_root), out_version, meta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, help="kaynak data_version (ör. snap_2026-11-20_v1)")
    ap.add_argument("--csv", type=Path, default=PRICE_CORRECTIONS_CSV)
    ap.add_argument("--root", type=Path, default=SNAPSHOT_DIR)
    ap.add_argument("--out-version", default=None, help="varsayılan: kaynağın tarihi için sıradaki sürüm numarası")
    args = ap.parse_args(argv)
    v = build_corrected_snapshot(args.root, args.src, args.csv, args.root, args.out_version)
    man = json.loads((args.root / v / "manifest.json").read_text(encoding="utf-8"))
    print(f"Yazıldı: {args.root / v}  (LATEST -> {v})")
    for c in man["corrections_applied"]:
        print(f"  {c['ticker']}: {c['n_rows_affected']} satır, bölen {c['price_divisor']}, hacim x{c['volume_multiplier']}, kaynak {c['source']}")
    print(f"Sıçrama bayrağı: {len(man['price_jump_report'])} (kaynakta {len(json.loads((args.root / args.src / 'manifest.json').read_text(encoding='utf-8'))['price_jump_report'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
