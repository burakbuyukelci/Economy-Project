"""Harness ayarları (BİLGİSAYAR 2 bölgesi).

Mock/gerçek araç seçimi TEK yerden yapılır: `TOOL_BACKEND_OVERRIDES`.
Örnek: gerçek get_stock_history hazır olunca
    TOOL_BACKEND_OVERRIDES = {ToolName.GET_STOCK_HISTORY: "real"}
yazmak yeterlidir; diğer 14 araç mock kalır.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from harness.as_of import AsOfError, parse_date
from schemas.enums import ToolName

# --- Araç arka ucu: "mock" | "real" -----------------------------------------
DEFAULT_TOOL_BACKEND = "mock"
TOOL_BACKEND_OVERRIDES: dict[ToolName, str] = {}
_VALID_BACKENDS = ("mock", "real")

# Gerçek araç sözleşmesi (BİLGİSAYAR 1 ile anlaşıldı): tools/<araç_adı>.py içinde run(params: dict) -> dict
REAL_TOOL_MODULE_TEMPLATE = "tools.{tool}"
REAL_TOOL_ENTRYPOINT = "run"


def backend_for(tool: ToolName) -> str:
    backend = TOOL_BACKEND_OVERRIDES.get(tool, DEFAULT_TOOL_BACKEND)
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"{tool.value}: bilinmeyen backend {backend!r}; geçerli: {_VALID_BACKENDS}")
    return backend


# --- Mock işareti -----------------------------------------------------------
# Mock zarfların data_version'ı bu sabittir (şema desenine uyar, gerçek snapshot ile karışmaz).
# Eğitim verisi üretimi `assert_not_mock()` ile bu işareti reddeder.
MOCK_DATA_VERSION = "snap_1900-01-01_v0"
# CLAUDE.md kural 12: eğitim verisi yalnızca snap_<tarih>_v<N> ile N >= bu değer olan sürümlerden (v1 ham kaynaktır).
MIN_TRAINING_SNAPSHOT_VERSION = 2
# schemas/examples.py fixture'larındaki en geç tarih; as_of bundan öncesiyse mock ERROR döner.
MOCK_FIXTURE_LAST_DATE = date(2026, 9, 10)
MOCK_AS_OF_ERROR_CODE = "MOCK_FIXTURE_AFTER_AS_OF"  # ToolError.code serbest metindir, şema değişmedi

# --- Oturum / log -----------------------------------------------------------
# None ise olaylar yalnızca bellekte tutulur; yol verilirse her olay JSONL satırı olarak eklenir.
EVENT_LOG_PATH: Path | None = None

# --- Analiz tarihi yedeği ---------------------------------------------------
# Soruda "Analiz tarihi" işareti ve açık as_of yoksa kullanılacak tarih. Varsayılan YOK (None): sessizce
# tarih uydurmayız. Ortam değişkeni (HARNESS_DEFAULT_AS_OF) ya da komut satırı (--default-as-of) ile verilir.
# Yedek kullanılırsa oturum "AS_OF_ASSUMED" uyarısı üretir (yalnızca harness düzeyinde; zarfa girmez).
DEFAULT_AS_OF: date | None = None
DEFAULT_AS_OF_ENV = "HARNESS_DEFAULT_AS_OF"


def default_as_of() -> date | None:
    raw = os.environ.get(DEFAULT_AS_OF_ENV, "").strip()
    if raw:
        try:
            return parse_date(raw)
        except AsOfError as exc:
            raise AsOfError(f"{DEFAULT_AS_OF_ENV}={raw!r}: {exc}") from exc
    return DEFAULT_AS_OF

# --- Deney aşaması ve durum sırası sertliği ------------------------------------------------
# Aşama (A-E) profili harness/profiles.py'de tablo olarak durur; burada yalnızca seçilir.
EXPERIMENT_STAGE = "D"
EXPERIMENT_STAGE_ENV = "HARNESS_STAGE"

# "strict": geçilmiş bir duruma ait araç çağrısı REDDEDİLİR (invalid call).
# "lenient": aynı çağrı ÇALIŞIR, durum geri gitmez. Her iki modda ORDER_VIOLATION olayı loglanır.
# Zorunlu adım atlama, as_of ve şema hataları iki modda da SERTTİR.
STATE_ORDER_MODE = "strict"
STATE_ORDER_MODE_ENV = "HARNESS_ORDER_MODE"
_ORDER_MODES = ("strict", "lenient")


def experiment_stage() -> str:
    return os.environ.get(EXPERIMENT_STAGE_ENV, "").strip().upper() or EXPERIMENT_STAGE


def state_order_mode() -> str:
    mode = os.environ.get(STATE_ORDER_MODE_ENV, "").strip().lower() or STATE_ORDER_MODE
    if mode not in _ORDER_MODES:
        raise ValueError(f"STATE_ORDER_MODE {mode!r} geçersiz; geçerli: {_ORDER_MODES}")
    return mode

# --- Nihai çıktı denetimi (harness/final_check.py, HarnessSession.submit_final) ----------------------------------------
# Zorlama açık profilde (D/E) ihlalli nihai metin için en çok bu kadar YENİDEN DENEME; hepsi başarısızsa güvenli geri çekilme.
# Toplam deneme sayısı = 1 + FINAL_MAX_RETRIES. Ortam değişkeniyle ezilebilir.
FINAL_MAX_RETRIES = 2
FINAL_RETRIES_ENV = "HARNESS_FINAL_RETRIES"


def final_max_retries() -> int:
    raw = os.environ.get(FINAL_RETRIES_ENV, "").strip()
    if not raw:
        return FINAL_MAX_RETRIES
    try:
        n = int(raw)
    except ValueError:
        raise ValueError(f"{FINAL_RETRIES_ENV}={raw!r} tam sayı olmalı") from None
    if n < 0:
        raise ValueError(f"{FINAL_RETRIES_ENV}={raw!r} negatif olamaz")
    return n

# --- Etiket politikası eşikleri (harness/label_policy.py; docs/harness_design.md bölüm 11) ----------------------------
# Eşikler getiriye bakılmadan seçildi (retail örneği +0,12 pp'de bile her marjda aynı sonucu verir) ve sonradan sonuçlara
# bakılarak DEĞİŞTİRİLMEZ. MIN_EVENTS / MIN_OOS_EVENTS / OOS_DEGRADATION_* config.settings'ten (ORTAK) çağrı anında okunur.
POLICY_HIT_MARGIN_PP = 5.0               # isabet oranı, bazı en az bu kadar yüzde puan aşmalı (aday için)
POLICY_MIN_PASSING_HORIZONS = 2          # aday için "geçen ufuk" sayısı alt sınırı (5/10/20 ya da 1/3/5/10 içinden)
POLICY_MIN_PEERS = 3                     # catch-up için peer grubu alt sınırı
POLICY_SIGNAL_RECENCY_TRADING_DAYS = 3   # teknik dönüşte "güncel sinyal": son olay as_of'tan en çok bu kadar iş günü önce
                                         # (hafta sonları hariç; resmi tatiller sayılmaz: yaklaşıklık)
POLICY_MIN_QUARTERS = 4                  # GEÇİCİ (temel veri): açıklanmış çeyrek alt sınırı; gerçek veri gelince gözden geçirilecek
