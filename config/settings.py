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

# --- Örneklem içi / dışı kararlılık eşikleri ---
# Haftalık örüntü (test_weekday_pattern): n = TRIGGER koşulu tutan hafta sayısı.
MIN_WEEKDAY_IS_TRIGGER_WEEKS = 10
MIN_WEEKDAY_OOS_TRIGGER_WEEKS = 5
# Olay tabanlı araçlar (reversal, catch-up, backtest): OOS'ta tamamlanmış olay sayısı bunun altındaysa
# oos_degradation_flag=False + OOS_TOO_SMALL uyarısı. (VARSAYIM: 5; ekip değiştirebilir.)
MIN_OOS_EVENTS = 5
# oos_degradation_flag: OOS isabet oranı IS'den bu kadar yüzde puandan fazla düşükse True.
OOS_DEGRADATION_HIT_RATE_DROP_PP = 15.0
# STABLE koşulu (e): OOS etki büyüklüğü, IS etkisinin en az bu oranı olmalı.
WEEKDAY_OOS_MIN_EFFECT_RATIO = 0.5
# STABLE koşulu (d): OOS isabet oranı alt sınırı (yüzde).
WEEKDAY_OOS_MIN_HIT_RATE_PCT = 50.0

# --- Veri kalitesi ---
# BIST günlük fiyat limiti ±%10: bunu aşan günlük sıçrama düzeltilmemiş bedelsiz/bölünme şüphesi.
PRICE_JUMP_LIMIT_PCT = 10.0
# Tick yuvarlaması ve düzeltme katsayısı yuvarlaması limitin hemen üstünde (ör. %10,0001) değer üretebilir.
# Bayrak: |günlük adj_close getirisi| > PRICE_JUMP_LIMIT_PCT + PRICE_JUMP_TOLERANCE_PP.
PRICE_JUMP_TOLERANCE_PP = 0.5
# Sıçrama şiddeti: aynı gün evrenin en az bu oranında hisse sıçradıysa "piyasa geneli olay" (SOFT);
# yoksa tek hisseye özgü -> olası düzeltilmemiş kurumsal işlem / bozuk geçmiş (HARD, WRONG_TICKER_OR_BROKEN_HISTORY).
PRICE_JUMP_MARKET_WIDE_SHARE = 0.5
# Fiyat düzeltme tablosu (docs/data_dictionary.md §12)
PRICE_CORRECTIONS_CSV = CONFIG_DIR / "price_corrections.csv"
# Birleşik işlem takvimi: bir gün, XU100'de VEYA hisselerin en az bu oranında veri varsa işlem günüdür.
TRADING_DAY_MIN_STOCK_SHARE = 0.5

# --- Gösterge durum eşikleri (calculate_indicators) ---
# Seçim: YALNIZCA KAMA eğimi ve hacim z-skoru dağılımına göre; ileri getiriye bakılmadan. Sonradan olay sonuçlarına
# bakılarak DEĞİŞTİRİLMEZ. Tablolar: docs/calibration_thresholds.md (scripts/calibrate_indicator_thresholds.py).
# KAMA eğimi birimi: yüzde. kama_slope_pct_t = (KAMA_t / KAMA_{t-1} - 1) * 100 (KAMA'nın 1 günlük % değişimi).
# slope > +eşik -> RISING ; slope < -eşik -> FALLING ; aksi halde FLATTENING.
KAMA_FLAT_SLOPE_PCT = 0.10
# Hacim z-skoru (IndicatorConfig.volume_zscore_window gün, bugün dahil, ddof=0): z > HIGH -> HIGH ; z < LOW -> LOW ; aksi NORMAL.
VOLUME_HIGH_Z = 1.0
VOLUME_LOW_Z = -1.0
# Gerçekleşen volatilite penceresi (gün) ve getiri ufukları (gün) — yalnızca tools/indicators kütüphanesi.
VOLATILITY_WINDOW = 20
RETURN_HORIZONS = [1, 5, 20]

# --- Backtest ---
BACKTEST_TRADE_LOG_MAX = 200
SHARPE_ANNUALIZATION_DAYS = 252
SHARPE_RISK_FREE_RATE = 0.0
