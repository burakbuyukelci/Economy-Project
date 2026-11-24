"""Kapsam koruması: soru BIST/finans analizi ile hiçbir ilgisi yoksa (ör. hava durumu) model hiç çalıştırılmadan hemen kısa bir "kapsam dışı" cevabı verilir.

Neden: kapsam dışı soruda model, ilgisiz bir araç (örn. XU100 geçmişi) çağırıp sorudan bağımsız veri döküyordu ve kapıdan HARD_BLOCK alıyordu (yerelde ölçüldü:
~18 dk CPU, ilgisiz çıktı). Bu koruma ucuz, belirlenimli ve MUHAFAZAKÂRdır: yalnızca evren hisse kodu YOK ve finans anahtar sözcüğü YOK ise kapsam dışı sayılır
(yanlış reddetmek, yanlış geçirmekten pahalıdır; şüphede soru modele gider). Eğitim/değerlendirme hattına dokunmaz; yalnızca `experiments.ask` / `experiments.chat` kullanır.
Eylem: ANALYSIS_UNSAFE (izinli enum; "analiz yapılamaz"), tavsiye/hedef fiyat yok.
"""
from __future__ import annotations

from harness.gate_params import detect_question_tickers

OUT_OF_SCOPE_ACTION = "ANALYSIS_UNSAFE"

# Alt dizgi eşleşmesi (küçük harf, Türkçe i/ı normalize). Geniş tutulur: şüphede soru modele gider.
_KEYWORDS = (
    "hisse", "borsa", "bist", "xu0", "xu1", "xbank", "endeks", "sektör", "sektor", "bilanço", "bilanco", "favök", "favok", "borç", "borc",
    "rsi", "bollinger", "supertrend", "ichimoku", "macd", "kama", "atr", "destek", "direnç", "direnc", "getiri", "kazanç", "temettü",
    "dolar", "euro", "usd", "kur ", "enflasyon", "faiz", "tcmb", "merkez banka", "döviz", "makro", "tüfe", "cpi",
    "fiyat", "backtest", "yatırım", "yatirim", "portföy", "alayım", "alayim", "satayım", "satayim", "ne almalı", "ne satmalı", "ne alayım", "hacim", "trend",
    "düşüş", "yüksel", "piyasa", "şirket", "sirket", "çeyrek", "ceyrek", "kâr", "kar marj", "marj", "oran", "analiz", "sinyal", "örüntü", "oruntu",
    "gösterge", "gosterge", "indikatör", "haftanın", "pazartesi", "banka", "perakende", "geride kal", "toparlan", "dönüş", "donus", "bollinger",
    "açıklama", "tahmin", "volatil", "risk", "olay", "ufuk", "gün sonra", "günlük", "haftalık", "aylık", "hedef fiyat", "lot",
)

MESSAGE = (
    "Bu soru kapsam dışı: sistem yalnızca BIST 100 hisseleri, sektörler, endeksler, teknik ve temel göstergeler, bilanço tepkileri ve makro veriler "
    "(kur, enflasyon, TCMB fonlama maliyeti) üzerine tarihsel analiz yapar; bu konu için aracım yok ve cevap üretmedim. "
    "Bu bir yatırım tavsiyesi değildir; hedef fiyat verilmez.\nEYLEM: " + OUT_OF_SCOPE_ACTION
)


def _norm(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def is_out_of_scope(question: str, universe: list[str] | None = None) -> bool:
    """True = soruda ne evren hisse kodu ne de finans anahtar sözcüğü var."""
    if detect_question_tickers(question, universe):
        return False
    q = _norm(question)
    return not any(k in q for k in _KEYWORDS)
