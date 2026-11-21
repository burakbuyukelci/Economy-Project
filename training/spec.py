"""v1 eğitim/değerlendirme verisi: sabitler (boyutlar, tarih aralıkları, soru tipi payları, gerçek araç kümesi).

Üreteç ARTIMLIDIR: yeni araç (bilanço, makro, haber) gerçek olunca `REAL_TOOLS`'a eklenir, `TYPE_SHARES`'e yeni tip ve `questions.py`/`teacher.py`'ye
şablon/plan eklenir; mevcut tiplerin soruları ve tohumları DEĞİŞMEZ (soru kimliği tip+bölme+sıra+tohumdan türer).
"""
from __future__ import annotations

from datetime import date

from schemas.enums import ToolName as T

GENERATOR_VERSION = "1"
SEED = 42
SPLITS = ("train", "val", "test")
SIZES = {"train": 600, "val": 50, "test": 100}

# Bölmeler arası tarih kümeleri ayrıktır (test = en geç dönem, 10.09.2026 dahil). Veri 2026-11-20'ye kadar.
DATE_RANGES = {
    "train": (date(2025, 3, 3), date(2026, 5, 29)),
    "val": (date(2026, 6, 1), date(2026, 8, 31)),
    "test": (date(2026, 9, 1), date(2026, 11, 19)),
}
# Veri bitişinden çok sonraki analiz tarihleri: gerçek kapı STALE_DATA ile ANALYSIS_UNSAFE verir (2027-01-15 ve sonrası; ölçüldü).
STALE_RANGES = {
    "train": (date(2027, 1, 18), date(2027, 4, 30)),
    "val": (date(2027, 5, 3), date(2027, 7, 30)),
    "test": (date(2027, 8, 2), date(2027, 12, 31)),
}

# Gerçek (mock olmayan) araçlar: modele yalnızca bunlar gösterilir. Kapı ve kanıt paketi harness'indir.
REAL_TOOLS = frozenset({T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY, T.CALCULATE_INDICATORS, T.FIND_SUPPORT_RESISTANCE,
                        T.RANK_SECTOR_RELATIVE_STRENGTH, T.DETECT_REVERSAL_EVENTS, T.TEST_WEEKDAY_PATTERN, T.RUN_BACKTEST})

# Soru tipi payları (toplam 1). Etiket dağılımı üretimde kota ile dengelenir (training/build_dataset.py).
TYPE_SHARES = {
    "weekday": 0.18,
    "reversal": 0.20,
    "catch_up": 0.10,
    "indicators": 0.12,
    "support_resistance": 0.07,
    "history": 0.07,
    "advice": 0.10,
    "unsupported": 0.08,
    "stale": 0.08,
}
RECOVERY_SHARE = 0.10          # hata-kurtarma yörüngeleri (hatalı asistan turu kayıptan MASKELİ)
TEST_TEMPLATE_MOD = 4          # şablon sırası % 4 == 3 olanlar yalnızca TEST'te kullanılır

MAX_TOKENS = 6144              # Colab seq len; gerçek Gemma tokenizer ile Colab'da yeniden süzülür
TOP_K_STATEMENTS = 4           # açıklamaya alınan en çok kanıt cümlesi


def allocate(split: str) -> dict[str, int]:
    """Bölme boyutunu tip paylarına en büyük kalan yöntemiyle dağıtır (her tipe en az 1)."""
    n = SIZES[split]
    raw = {t: n * s for t, s in TYPE_SHARES.items()}
    out = {t: max(1, int(v)) for t, v in raw.items()}
    rest = n - sum(out.values())
    order = sorted(raw, key=lambda t: (-(raw[t] - int(raw[t])), t))
    i = 0
    while rest != 0:
        t = order[i % len(order)]
        step = 1 if rest > 0 else -1
        if out[t] + step >= 1:
            out[t] += step
            rest -= step
        i += 1
    return out
