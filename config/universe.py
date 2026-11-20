"""universe.csv yükleyici (proje dokümanı §32: load_universe, build_sector_peer_groups)."""
from __future__ import annotations

import pandas as pd

from config.settings import UNIVERSE_CSV


def load_universe() -> pd.DataFrame:
    """30 hissenin ticker/yahoo_symbol/sector/peer_group/peer_group_size tablosu."""
    return pd.read_csv(UNIVERSE_CSV, dtype={"peer_group_size": "int64"})


def build_sector_peer_groups() -> dict[str, list[str]]:
    """peer_group -> [ticker, ...]. Her hisse yalnızca BİR grupta."""
    df = load_universe()
    return {g: sorted(sub["ticker"]) for g, sub in df.groupby("peer_group")}


def solo_tickers() -> list[str]:
    """peer_group_size == 1 olan hisseler (araçlar bunlar için uyarı üretmeli)."""
    df = load_universe()
    return sorted(df.loc[df["peer_group_size"] == 1, "ticker"])
