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

from config.settings import RANDOM_SEED
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
# Bilanço/makro veri setleri fiyat snapshot'ından AYRI sürümlenir; zarfta ikincil sürüm alanı yok, sürüm `HISTORICAL_ONLY` uyarı metninde taşınır
# (docs/schema_wishlist.md §12). Eğitim uygunluğu: uyarıdan regex ile çekilen sürüm bu kabul listesinde olmalı (CLAUDE.md kural 12'nin bilanço/makro karşılığı).
# `fundamentals_2026-11-21_v1` KABUL EDİLMEZ (yalnızca 10 hisse, açıklama tarihi eşleşmesiyle sınırlı; yasal süre görünürlüğü yok).
ACCEPTED_FUNDAMENTALS_VERSIONS: frozenset[str] = frozenset({"fundamentals_2026-11-23_v1", "fundamentals_2026-11-23_v2"})
ACCEPTED_MACRO_VERSIONS: frozenset[str] = frozenset({"macro_2026-11-09_v2"})   # v1 KABUL EDİLMEZ (EVDS 1000 satır sınırı: USDTRY/EURTRY 2024-02-14'te başlıyordu; silindi, commit edilmedi)
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

# --- Yerel model (harness/llm_backend.py) -----------------------------------------------------------------------------
# Final sistemde bulut AI API'si YOK (CLAUDE.md kural 4): yalnızca yerel Ollama, yalnızca loopback adres.
# `config/` ortak bölge olduğundan model ayarları burada durur; ortam değişkenleriyle ezilir.
# NOT: model adı YER TUTUCUDUR (temel model kararı ekibindir; fine-tune sonrası kendi model adı yazılır).
LLM_MODEL = "gemma3:4b"
LLM_MODEL_ENV = "HARNESS_MODEL"
LLM_TEMPERATURE = 0.0              # determinizm (CLAUDE.md kural 8)
LLM_TEMPERATURE_ENV = "HARNESS_TEMPERATURE"
LLM_NUM_CTX = 8192                # bağlam sınırı (token); aşılırsa Ollama sessizce kırpar: istemci bunu hata sayar.
                                   # ÖLÇÜM (Q1/Q3, 3 karakter/token yaklaşığı): 13 araç şeması ~23 bin karakter + bir oturumun mesajları 10-12 bin karakter
                                   # => ~11-12 bin token; 8192 yetmez. Gerçek tokenizer ile doğrulanmadı; VRAM'e göre env ile ezilir.
LLM_NUM_CTX_ENV = "HARNESS_NUM_CTX"
LLM_SEED = RANDOM_SEED             # config.settings.RANDOM_SEED (ortak, 42)
OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_HOST_ENV = "HARNESS_OLLAMA_HOST"
LLM_TIMEOUT_S = 300.0
LLM_TIMEOUT_ENV = "HARNESS_LLM_TIMEOUT"     # saniye; CPU'da Ollama yavaştır (prompt ~27 token/sn ölçüldü): uzun oturumlar için artırılır
# Araç çağırma biçimi: "text" = araç tanımları istemde METİN, çağrılar yanıt metninden ayrıştırılır (harness/text_protocol.py; Gemma 3 için varsayılan,
# çünkü Ollama gemma3 şablonunda yerel `tools` desteği yok/güvenilmez); "native" = Ollama'nın `tools` alanı (Qwen/Llama gibi destekleyen modeller).
LLM_TOOL_MODE = "text"
LLM_TOOL_MODE_ENV = "HARNESS_TOOL_MODE"
_TOOL_MODES = ("text", "native")


def llm_tool_mode() -> str:
    mode = os.environ.get(LLM_TOOL_MODE_ENV, "").strip().lower() or LLM_TOOL_MODE
    if mode not in _TOOL_MODES:
        raise ValueError(f"{LLM_TOOL_MODE_ENV}={mode!r} geçersiz; geçerli: {_TOOL_MODES}")
    return mode


LLM_RAW_ENV = "HARNESS_RAW_PROMPT"


def llm_raw() -> bool:
    """Metin-protokolü modunda istem biçimi. True (varsayılan): harness konuşmayı EĞİTİM metniyle birebir biçimlendirip `/api/generate raw=true` gönderir
    (Ollama `/api/chat` yolu eğitim metninden fazla token üretiyordu: tek mesajda +3, asistan turu başına +4). False: `/api/chat` (Modelfile şablonu)."""
    v = os.environ.get(LLM_RAW_ENV, "").strip().lower()
    if v in ("", "1", "true", "evet"):
        return True
    if v in ("0", "false", "hayir", "hayır"):
        return False
    raise ValueError(f"{LLM_RAW_ENV}={v!r} geçersiz; geçerli: 1/0")


NORMALIZE_PARAMS_ENV = "HARNESS_NORMALIZE_PARAMS"


def normalize_params() -> bool:
    """Parametre düzeltici (harness/param_fixer.py): biçim hatalı çağrıları (dönem yazımı, enum harfi, fazla alan) araçtan önce onarır. Varsayılan AÇIK; 0 = kapalı (A/B ölçümü için)."""
    v = os.environ.get(NORMALIZE_PARAMS_ENV, "").strip().lower()
    if v in ("", "1", "true", "evet"):
        return True
    if v in ("0", "false", "hayir", "hayır"):
        return False
    raise ValueError(f"{NORMALIZE_PARAMS_ENV}={v!r} geçersiz; geçerli: 1/0")


def llm_model() -> str:
    return os.environ.get(LLM_MODEL_ENV, "").strip() or LLM_MODEL


def llm_temperature() -> float:
    raw = os.environ.get(LLM_TEMPERATURE_ENV, "").strip()
    if not raw:
        return LLM_TEMPERATURE
    try:
        t = float(raw)
    except ValueError:
        raise ValueError(f"{LLM_TEMPERATURE_ENV}={raw!r} sayı olmalı") from None
    if t < 0:
        raise ValueError(f"{LLM_TEMPERATURE_ENV}={raw!r} negatif olamaz")
    return t


def llm_timeout() -> float:
    """Tek Ollama isteğinin zaman aşımı (sn). Ortam değişkeni `HARNESS_LLM_TIMEOUT` varsa o; yoksa `LLM_TIMEOUT_S`."""
    raw = os.environ.get(LLM_TIMEOUT_ENV, "").strip()
    if not raw:
        return LLM_TIMEOUT_S
    try:
        t = float(raw)
    except ValueError:
        raise ValueError(f"{LLM_TIMEOUT_ENV}={raw!r} sayı olmalı") from None
    if t <= 0:
        raise ValueError(f"{LLM_TIMEOUT_ENV}={raw!r} pozitif olmalı")
    return t


def llm_num_ctx() -> int:
    raw = os.environ.get(LLM_NUM_CTX_ENV, "").strip()
    if not raw:
        return LLM_NUM_CTX
    try:
        n = int(raw)
    except ValueError:
        raise ValueError(f"{LLM_NUM_CTX_ENV}={raw!r} tam sayı olmalı") from None
    if n <= 0:
        raise ValueError(f"{LLM_NUM_CTX_ENV}={raw!r} pozitif olmalı")
    return n


def ollama_host() -> str:
    return os.environ.get(OLLAMA_HOST_ENV, "").strip() or OLLAMA_HOST

# --- Modele açık araç kümesi ---------------------------------------------------------------------------------------------
# None = profilin tüm araçları. Küme verilirse yalnızca bunlar modele görünür (harness-içi kapı/paket araçları yine hariç). v1 eğitim verisi ve canlı sistem
# yalnızca GERÇEK araçları gösterir; yeni araç (bilanço, makro, haber) gerçek olunca buraya eklenir ve veri yeniden üretilir.
EXPOSED_TOOLS: frozenset[ToolName] | None = None

# Model görünümü SIKI MOD (docs/harness_design.md 14.3): ufuk blokları yalnızca kanıtın seçtiği ufuklarla. Varsayılan KAPALI; 8192 bağlam OOM verirse
# 6144 geri dönüşünde (training/README.md) `python -m training.build_dataset --tight --max-tokens 6144` ile kullanılır; CANLIDA da aynı değer kullanılmalıdır (HARNESS_VIEW_TIGHT=1).
MODEL_VIEW_TIGHT = os.environ.get("HARNESS_VIEW_TIGHT", "") == "1"

# --- Orkestratör (harness/agent_loop.py) ---------------------------------------------------------------------------------
AGENT_MAX_TURNS = 40               # bir oturumdaki en çok model turu (araç döngüsü + nihai deneme); aşılırsa LOOP_ABORTED

# --- Etiket politikası eşikleri (harness/label_policy.py; docs/harness_design.md bölüm 11) ----------------------------
# Eşikler getiriye bakılmadan seçildi (retail örneği +0,12 pp'de bile her marjda aynı sonucu verir) ve sonradan sonuçlara
# bakılarak DEĞİŞTİRİLMEZ. MIN_EVENTS / MIN_OOS_EVENTS / OOS_DEGRADATION_* config.settings'ten (ORTAK) çağrı anında okunur.
POLICY_HIT_MARGIN_PP = 5.0               # isabet oranı, bazı en az bu kadar yüzde puan aşmalı (aday için)
POLICY_MIN_PASSING_HORIZONS = 2          # aday için "geçen ufuk" sayısı alt sınırı (5/10/20 ya da 1/3/5/10 içinden)
POLICY_MIN_PEERS = 3                     # catch-up için peer grubu alt sınırı
POLICY_SIGNAL_RECENCY_TRADING_DAYS = 3   # teknik dönüşte "güncel sinyal": son olay as_of'tan en çok bu kadar iş günü önce
                                         # (hafta sonları hariç; resmi tatiller sayılmaz: yaklaşıklık)
POLICY_MIN_QUARTERS = 4                  # GEÇİCİ (temel veri): açıklanmış çeyrek alt sınırı; gerçek veri gelince gözden geçirilecek
