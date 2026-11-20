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

# --- Maliyet modeli (docs/data_dictionary.md "Maliyet modeli") ---
# Her bacak (alım VEYA satım) için bps. Bir tur (alım+satım) toplam = 2 * (maliyet + slippage).
TRANSACTION_COST_BPS_PER_SIDE = 20.0
SLIPPAGE_BPS_PER_SIDE = 5.0  # ÖNERİ: ekip onayına tabi, parametre ile değiştirilebilir

# --- Sektör gücü eşikleri (rank_sector_relative_strength) ---
# sector_strength = (peer medyan getirisi) - (XU100 getirisi), aynı pencerede, yüzde puan.
SECTOR_STRONG_MIN_VS_XU100_PP = 2.0    # >= bu değer -> STRONG
SECTOR_WEAK_MAX_VS_XU100_PP = -2.0     # <= bu değer -> WEAK; arası NEUTRAL

# Laggard/leader varsayılan eşiği: lag_score (hisse - medyan) bu kadar pp altı/üstü.
LAG_THRESHOLD_PP_DEFAULT = 3.0

# --- Veri kalitesi ---
# BIST günlük fiyat limiti ±%10: bunu aşan günlük sıçrama düzeltilmemiş bedelsiz/bölünme şüphesi.
PRICE_JUMP_LIMIT_PCT = 10.0

# --- Backtest ---
BACKTEST_TRADE_LOG_MAX = 200
SHARPE_ANNUALIZATION_DAYS = 252
SHARPE_RISK_FREE_RATE = 0.0
