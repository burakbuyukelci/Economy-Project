"""Gösterge durum eşiklerinin (KAMA eğimi, hacim z-skoru) dağılım tabanlı kalibrasyonu.

YALNIZCA eğim ve hacim z-skoru dağılımına bakar; İLERİ GETİRİYE HİÇ BAKMAZ (eşik seçiminde getiri sızıntısı olmasın).
Ağ yok; snapshot'tan okur. Kullanım:  python -m scripts.calibrate_indicator_thresholds [--start 2024-01-01 --end 2026-09-10]

KAMA eğimi (birim): kama_slope_pct_t = (KAMA_t / KAMA_{t-1} - 1) * 100  (KAMA'nın 1 günlük % değişimi).
Sınıf: slope > +eşik -> RISING ; slope < -eşik -> FALLING ; aksi halde FLATTENING.
Hacim: z > hi -> HIGH ; z < lo -> LOW ; aksi halde NORMAL.
"""
from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from schemas.params import IndicatorConfig
from tools.common import enforce_as_of, load_snapshot
from tools.indicators import kama, volume_zscore

SLOPE_CANDIDATES = [0.02, 0.05, 0.10, 0.15, 0.20, 0.30]
VOLUME_CANDIDATES = [(1.0, -1.0), (1.5, -1.0), (1.0, -0.5), (2.0, -1.0), (1.5, -0.5)]


def collect(start: date, end: date, data_version: str | None = None) -> pd.DataFrame:
    """Her hisse için [start, end] günlük kama_slope_pct ve volume_z (adjusted fiyat; ısınma tüm geçmişten)."""
    snap = load_snapshot(data_version)
    cfg = IndicatorConfig()
    frames = []
    for ticker, g in snap.stocks.groupby("ticker"):
        g = enforce_as_of(g, end).sort_values("date").set_index("date")
        close = g["adj_close"]
        k = kama(close, cfg.kama_er_window, cfg.kama_fast, cfg.kama_slow)
        out = pd.DataFrame({
            "ticker": ticker,
            "kama_slope_pct": (k / k.shift(1) - 1.0) * 100.0,
            "volume_z": volume_zscore(g["volume"], cfg.volume_zscore_window),
        })
        frames.append(out.loc[pd.Timestamp(start):pd.Timestamp(end)].dropna())
    return pd.concat(frames)


def slope_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for thr in SLOPE_CANDIDATES:
        s = df["kama_slope_pct"]
        share = pd.DataFrame({"R": s > thr, "F": s < -thr})
        share["N"] = ~(share["R"] | share["F"])
        per = share.groupby(df["ticker"]).mean() * 100
        rows.append({"esik_pct": thr, "RISING_%": share["R"].mean() * 100, "FLATTENING_%": share["N"].mean() * 100,
                     "FALLING_%": share["F"].mean() * 100, "FLAT_min_hisse_%": per["N"].min(),
                     "FLAT_max_hisse_%": per["N"].max()})
    return pd.DataFrame(rows)


def volume_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for hi, lo in VOLUME_CANDIDATES:
        z = df["volume_z"]
        h, l = z > hi, z < lo
        n = ~(h | l)
        per = pd.DataFrame({"H": h, "L": l, "N": n}).groupby(df["ticker"]).mean() * 100
        rows.append({"hi": hi, "lo": lo, "HIGH_%": h.mean() * 100, "NORMAL_%": n.mean() * 100, "LOW_%": l.mean() * 100,
                     "HIGH_min_hisse_%": per["H"].min(), "HIGH_max_hisse_%": per["H"].max(),
                     "LOW_min_hisse_%": per["L"].min(), "LOW_max_hisse_%": per["L"].max()})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-09-10")
    a = ap.parse_args()
    df = collect(date.fromisoformat(a.start), date.fromisoformat(a.end))
    pd.set_option("display.width", 200, "display.float_format", "{:.2f}".format)
    print(f"{df['ticker'].nunique()} hisse, {len(df)} hisse-gün, {a.start} -> {a.end}\n")
    q = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
    print("KAMA 1g % değişim — işaretli dağılım:\n", df["kama_slope_pct"].quantile(q).to_frame("kama_slope_pct"))
    print("\nKAMA |1g % değişim| dağılımı:\n", df["kama_slope_pct"].abs().quantile(q).to_frame("abs_slope_pct"))
    print("\nKAMA eğim eşiği adayları:\n", slope_table(df).to_string(index=False))
    print("\nHacim z-skoru dağılımı:\n", df["volume_z"].quantile(q).to_frame("volume_z"))
    print("\nHacim eşiği adayları:\n", volume_table(df).to_string(index=False))


if __name__ == "__main__":
    main()
