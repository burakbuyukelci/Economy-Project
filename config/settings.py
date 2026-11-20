"""Ortak ayarlar (ORTAK bölge: iki bilgisayar da bunu kullanır)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
UNIVERSE_CSV = CONFIG_DIR / "universe.csv"

# Az olay uyarı eşiği (CLAUDE.md kural 10). Ekip değiştirebilir.
MIN_EVENTS = 20

# Fiyat indirme başlangıcı: indikatör ısınması (KAMA, Ichimoku 52 gün vb.) için 2023'ten.
DOWNLOAD_START = date(2023, 1, 1)
# Analiz penceresi varsayılan başlangıcı (araç parametresi olarak geçilebilir).
ANALYSIS_START_DEFAULT = date(2024, 1, 1)

# Varsayılan fiyat sütunu: düzeltilmiş kapanış (bkz. docs/data_dictionary.md).
DEFAULT_PRICE_FIELD = "adj_close"

# Rastgelelik gerekirse sabit seed (kural 8).
RANDOM_SEED = 42
