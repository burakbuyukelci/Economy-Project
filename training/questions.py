"""v1 soru üretici: belirlenimli (tohumlu), şablon + slot; hisseler ve gruplar config/universe.csv'den (training/splits.py).

Her soru `Question`: kimlik, tip, bölme, metin ("Analiz tarihi: GG.AA.YYYY" ön metniyle), `as_of`, hisseler, şablon sırası ve öğretmen için `plan` (araç parametrelerini
belirleyen yapısal bilgi). Şablon sırası % 4 == 3 olanlar yalnızca test'te kullanılır. Yeni soru tipi eklemek için `BUILDERS`'a bir işlev ve `spec.TYPE_SHARES`'e pay eklenir.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Callable

from training import spec
from training.signal_dates import signal_dates
from training.splits import is_test_only_template, pick_trading_date, tickers_for

ANCHOR_SHARE = 0.5          # teknik dönüş sorularında sinyal gününe kurulanların payı
DAY_TR = {"MON": "Pazartesi", "TUE": "Salı", "WED": "Çarşamba", "THU": "Perşembe", "FRI": "Cuma"}
DAYS = list(DAY_TR)
DIR_TR = {"DOWN": "düşüş", "UP": "yükseliş"}


def fd(d: date) -> str:
    return d.strftime("%d.%m.%Y")


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    split: str
    text: str
    as_of: date
    tickers: tuple[str, ...]
    template_idx: int
    plan: dict[str, Any] = field(default_factory=dict)


def _head(as_of: date) -> str:
    return f"Analiz tarihi: {fd(as_of)}\n"


def _template_index(split: str, n_templates: int, rng: random.Random) -> int:
    """Bölmeye uygun şablon sırası: test yalnızca test-only şablonların ÇOĞUNLUĞUNU (%70) kullanır, diğerleri hiç test-only kullanmaz."""
    test_only = [i for i in range(n_templates) if is_test_only_template(i)]
    normal = [i for i in range(n_templates) if not is_test_only_template(i)]
    if split == "test" and rng.random() < 0.7:
        return rng.choice(test_only)
    return rng.choice(normal)


# =============================== haftanın günü ===============================
def _weekday_pattern(rng: random.Random) -> list[tuple[str, str, str]]:
    cut = rng.randint(1, 4)                                    # tetik günleri [0, cut), sonuç günleri [cut, 5)
    n_trig = rng.randint(1, min(3, cut))
    trig = sorted(rng.sample(range(cut), n_trig))
    n_out = rng.randint(1, min(2, 5 - cut))
    out = sorted(rng.sample(range(cut, 5), n_out))
    d_trig = rng.choice(["DOWN", "DOWN", "UP"])
    d_out = rng.choice(["UP", "UP", "DOWN"]) if d_trig == "DOWN" else rng.choice(["DOWN", "UP"])
    return [(DAYS[i], d_trig, "TRIGGER") for i in trig] + [(DAYS[i], d_out, "OUTCOME") for i in out]


def _pattern_text(pattern: list[tuple[str, str, str]]) -> str:
    """Tetik günleri ve sonuç günleri ayrı kümelenir: 'Pazartesi–Salı düşüş, ardından Perşembe–Cuma yükseliş' (aynı yön olsa bile)."""
    groups: list[tuple[tuple[str, str], list[str]]] = []
    for day, direction, role in pattern:
        if groups and groups[-1][0] == (direction, role):
            groups[-1][1].append(DAY_TR[day])
        else:
            groups.append(((direction, role), [DAY_TR[day]]))
    return ", ardından ".join(f"{'–'.join(days)} {DIR_TR[d]}" for (d, _), days in groups)


_WEEKDAY = [
    "{T} hissesinde {IS0} – {IS1} döneminde '{PAT}' örüntüsü var mı? Bu örüntü {OOS0} – {OOS1} döneminde de devam ediyor mu?",
    "{T} için {IS0} – {IS1} arasında {PAT} şeklinde bir haftalık örüntü görülüyor mu? {OOS0} – {OOS1} döneminde aynı örüntü geçerli mi?",
    "'{PAT}' örüntüsünü {T} hissesinde {IS0} – {IS1} verisiyle test et; {OOS0} – {OOS1} dönemindeki sonuçla karşılaştır. Örüntü kararlı mı?",
    "{T} hissesi haftanın günlerine göre '{PAT}' kalıbını izliyor mu? Örneklem içi dönem {IS0} – {IS1}, örneklem dışı dönem {OOS0} – {OOS1}.",
    "{T} hissesinde {PAT} örüntüsü istatistiksel olarak anlamlı mı? Örneklem içi: {IS0} – {IS1}. Örneklem dışı: {OOS0} – {OOS1}. İşlem maliyetini de dikkate al.",
    "Haftalık örüntü analizi: {T}, {PAT}. Örneklem içi {IS0} – {IS1}, örneklem dışı {OOS0} – {OOS1}. Sonuç tutarlı mı?",
    "{PAT} kalıbı {T} hissesinde tesadüf olabilir mi? {IS0} – {IS1} içinde ve {OOS0} – {OOS1} dışında sonuçları ver.",
    "{T} hissesi için {IS0} – {IS1} dönemini örneklem içi, {OOS0} – {OOS1} dönemini örneklem dışı kabul ederek '{PAT}' haftalık örüntüsünü değerlendir.",
]


def _q_weekday(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    pattern = _weekday_pattern(rng)
    oos0 = date(as_of.year, 1, 1)
    is0, is1 = date(2024, 1, 1), oos0 - timedelta(days=1)
    idx = _template_index(split, len(_WEEKDAY), rng)
    text = _WEEKDAY[idx].format(T=ticker, PAT=_pattern_text(pattern), IS0=fd(is0), IS1=fd(is1), OOS0=fd(oos0), OOS1=fd(as_of))
    return text, idx, {"pattern": pattern, "is_start": is0, "is_end": is1, "oos_start": oos0, "oos_end": as_of}


# =============================== teknik dönüş ===============================
_FAMILY_TEXT = {"BB_LOWER_TOUCH": "alt Bollinger bandına dokunuş", "RSI_LOCAL_TROUGH": "RSI dibi (yerel dip)"}
_REVERSAL = [
    "{T} hissesinde {S} – {D} döneminde {FT} kaç kez görüldü? Bunların kaçında fiyat 5 gün içinde yükseldi?{EXTRA}",
    "{T} için {S} – {D} arasındaki {FT} olaylarını incele: kaç olay var, ileri getiriler nasıl?{EXTRA}",
    "{T} hissesinde {FT} sinyali tarihsel olarak işe yaramış mı? Dönem: {S} – {D}.{EXTRA}",
    "{S} – {D} döneminde {T} hissesindeki {FT} olayları sonrası 1, 3, 5 ve 10 günlük getiriler nasıl? Son günlerde bir sinyal var mı?{EXTRA}",
    "{T}: {FT} sonrası 5 günde yükseliş oranı nedir? Veri dönemi {S} – {D}.{EXTRA}",
    "{T} hissesi için {FT} sinyalini örneklem içi ve dışı ayırarak değerlendir ({S} – {D}).{EXTRA}",
    "Bugün {T} hissesinde {FT} var mı? Geçmişte benzer olaylar sonrası ne olmuş? ({S} – {D}){EXTRA}",
    "{T} hissesinde {FT} olaylarının başarı ve yanlış pozitif sayıları nedir? ({S} – {D}){EXTRA}",
]
_COND = {
    "BB_LOWER_TOUCH": ("RSI dibi ve yüksek hacimle birlikte gerçekleşen olayları ayrıca karşılaştır.",
                       {"label": "RSI dip + yüksek hacim", "rsi_state": "LOCAL_LOW", "volume_regime": "HIGH"}),
    "RSI_LOCAL_TROUGH": ("Supertrend düşüş yönündeyken gerçekleşen olayları ayrıca karşılaştır.",
                         {"label": "Supertrend düşüş", "supertrend_state": "BEARISH"}),
}


def _q_reversal(split: str, rng: random.Random, as_of: date, ticker: str, family: str | None = None) -> tuple[str, int, dict[str, Any]]:
    family = family or rng.choice(list(_FAMILY_TEXT))
    with_backtest = rng.random() < 0.7
    conditions = [_COND[family][1]] if rng.random() < 0.3 else []
    extra = ""
    if conditions:
        extra += " " + _COND[family][0]
    if with_backtest:
        extra += " Sinyali backtest ile de doğrula."
    label_q = rng.random() < 0.2
    if label_q:
        extra += " TECHNICAL_REVERSAL_CANDIDATE olarak etiketlenebilir mi?"
    idx = _template_index(split, len(_REVERSAL), rng)
    text = _REVERSAL[idx].format(T=ticker, FT=_FAMILY_TEXT[family], S=fd(date(2024, 1, 1)), D=fd(as_of), EXTRA=extra)
    return text, idx, {"family": family, "with_backtest": with_backtest, "conditions": conditions, "label_question": label_q, "analysis_start": date(2024, 1, 1)}


# =============================== catch-up (retail) ===============================
_CATCH_UP = [
    "Perakende sektöründe (BIMAS, MGROS, MAVI) {D} tarihine kadar olan son {H} işlem gününde sektör medyanının en çok gerisinde kalan hisse hangisi? "
    "{S} – {D} döneminde benzer geride kalmalar 5, 10 ve 20 gün içinde kapanmış mı?{EXTRA}",
    "Perakende grubunda (BIMAS, MGROS, MAVI) son {H} işlem gününde medyanın gerisinde kalan hisse var mı? Geçmişte {S} – {D} arasında bu tür geride kalmalar toparlanmış mı?{EXTRA}",
    "{SUBJ} hissesi son {H} işlem gününde perakende sektörünün (BIMAS, MGROS, MAVI) gerisinde mi? Benzer durumlar {S} – {D} döneminde nasıl sonuçlanmış?{EXTRA}",
    "BIMAS, MGROS ve MAVI içinde son {H} günde en zayıf performans hangisinde? {S} – {D} dönemindeki geride kalmaların tarihsel isabetini ver.{EXTRA}",
    "Perakende sektörü (BIMAS, MGROS, MAVI): {D} itibarıyla {H} günlük getiri sıralaması nedir ve geride kalan hisse geçmişte toparlanmış mı? ({S} – {D}){EXTRA}",
    "{SUBJ} perakende sektöründeki akranlarına (BIMAS, MGROS, MAVI) göre {H} işlem gününde ne kadar geride? {S} – {D} arasındaki benzer olaylara bak.{EXTRA}",
    "Sektör medyanına göre {H} günlük geri kalma: BIMAS, MGROS, MAVI karşılaştır ve {S} – {D} tarihsel kapanma oranlarını ver.{EXTRA}",
    "{D} tarihinde perakende grubunda (BIMAS, MGROS, MAVI) geride kalan hisse için geçmiş {S} – {D} verisiyle kanıt çıkar; {H} günlük pencere kullan.{EXTRA}",
]


def _q_catch_up(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    horizon = rng.choice([5, 10, 20, 20])
    subject = rng.choice(["BIMAS", "MGROS", "MAVI"]) if rng.random() < 0.4 else None
    extra = " Hisse POTENTIAL_CATCH_UP_CANDIDATE olarak etiketlenebilir mi?" if rng.random() < 0.5 else ""
    idx = _template_index(split, len(_CATCH_UP), rng)
    if "{SUBJ}" in _CATCH_UP[idx] and subject is None:
        subject = rng.choice(["BIMAS", "MGROS", "MAVI"])
    text = _CATCH_UP[idx].format(H=horizon, D=fd(as_of), S=fd(date(2024, 1, 1)), SUBJ=subject, EXTRA=extra)
    return text, idx, {"horizon": horizon, "subject": subject if "{SUBJ}" in _CATCH_UP[idx] else None, "analysis_start": date(2024, 1, 1)}


# =============================== göstergeler ===============================
_IND_TEXT = {"RSI": "RSI", "BOLLINGER": "Bollinger bantları", "SUPERTREND": "Supertrend", "ICHIMOKU": "Ichimoku bulutu", "MACD": "MACD",
             "SMA": "hareketli ortalamalar (SMA)", "ATR": "ATR (oynaklık)", "KAMA": "KAMA", "VOLUME_ZSCORE": "hacim z-skoru"}
_INDICATORS = [
    "{T} hissesinde {D} itibarıyla {IND} durumu nedir?",
    "{T} için {D} tarihindeki {IND} ne söylüyor?{LAST}",
    "{D} itibarıyla {T} hissesinin {IND} değerlerini ve durumunu özetle.{LAST}",
    "{T} hissesinin teknik görünümü: {IND}. Analiz tarihi itibarıyla durum nedir?{LAST}",
    "{T}: {IND} hangi bölgede? Güncel durumu aç.{LAST}",
    "{T} hissesi için {IND} göstergelerini {D} itibarıyla yorumla.{LAST}",
    "{D} itibarıyla {T} fiyatı {IND} açısından nerede duruyor?{LAST}",
    "{T} hissesinde {IND} sinyalleri bugün ne durumda?{LAST}",
]


def _q_indicators(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    names = rng.sample(list(_IND_TEXT), rng.randint(1, 3))
    last_n = 5 if rng.random() < 0.3 else 0
    idx = _template_index(split, len(_INDICATORS), rng)
    ind = ", ".join(_IND_TEXT[n] for n in names)
    text = _INDICATORS[idx].format(T=ticker, D=fd(as_of), IND=ind, LAST=" Son 5 günlük seyri de göster." if last_n else "")
    return text, idx, {"indicators": names, "last_n_rows": last_n}


# =============================== destek / direnç ===============================
_SR = [
    "{T} için {D} itibarıyla en yakın destek ve direnç seviyeleri neler? Fiyat bu seviyelere ne kadar uzak?",
    "{T} hissesinde {D} tarihine göre önemli destek ve direnç bölgeleri nerede?",
    "{D} itibarıyla {T} fiyatı hangi destek ile hangi direnç arasında?",
    "{T} hissesinin güncel destek/direnç seviyelerini ve onlara olan yüzde uzaklığı ver ({D}).",
]


def _q_sr(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    idx = _template_index(split, len(_SR), rng)
    return _SR[idx].format(T=ticker, D=fd(as_of)), idx, {}


# =============================== fiyat geçmişi ===============================
_HISTORY = [
    "{T} hissesinin {S} – {D} dönemindeki ilk ve son kapanışı ile dönemin en yüksek ve en düşük kapanışı nedir?{REL}",
    "{T} için {S} – {D} arasında kapanış aralığı nasıl? En yüksek ve en düşük kapanışı tarihleriyle ver.{REL}",
    "{D} itibarıyla {T} hissesinin son kapanışı ve {S}'den bu yana en yüksek/en düşük kapanışı nedir?{REL}",
    "{T} hissesinin {S} – {D} fiyat seyrini özetle: başlangıç, bitiş, zirve ve dip kapanışlar.{REL}",
]


def _q_history(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    days = rng.choice([14, 21, 28, 42])
    start = as_of - timedelta(days=days)
    relative = rng.random() < 0.4
    idx = _template_index(split, len(_HISTORY), rng)
    text = _HISTORY[idx].format(T=ticker, S=fd(start), D=fd(as_of), REL=" XU100'ün aynı dönemdeki ilk ve son kapanışıyla karşılaştır." if relative else "")
    return text, idx, {"start": start, "relative": relative}


# =============================== tavsiye / kesinlik ===============================
_CLAIMS = ["kesin yükselir", "garanti kazandırır", "mutlaka sıçrar", "kesinlikle düşmez"]
_ADVICE_CERTAIN = [
    "{T} hissesi {CLAIM}, çünkü ihracatçı bir şirket. Yarın {T} alayım mı? Hedef fiyat ver.",
    "Bence {T} {CLAIM}. Bugün alıp tutsam olur mu? Hedef fiyatını da söyle.",
    "Herkes {T} hissesinin {CLAIM} diyor. Alayım mı, hedef fiyat ne olur?",
    "{T} hissesi için {CLAIM} diye duydum; yarın almalı mıyım? Hedef fiyat istiyorum.",
]
_ADVICE_PLAIN = [
    "{T} hissesini yarın alayım mı? Hedef fiyatı nedir?",
    "{T} için al-sat tavsiyesi verir misin? Hedef fiyat kaç?",
    "Elimdeki parayı {T} hissesine yatırsam mı? Ne kadar kazandırır, hedef fiyat ver.",
    "{T} hissesi bu seviyeden alınır mı? Net bir tavsiye ve hedef fiyat istiyorum.",
]
_ADVICE_SIGNAL = " Alt Bollinger bandına dokunuş sinyali var mı, backtest sonucuna göre alayım mı?"


def _q_advice(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    certainty = rng.random() < 0.55
    variant = "reversal" if rng.random() < 0.35 else "indicators"
    bank = _ADVICE_CERTAIN if certainty else _ADVICE_PLAIN
    idx = _template_index(split, len(bank), rng)
    claim = rng.choice(_CLAIMS) if certainty else None
    text = bank[idx].format(T=ticker, CLAIM=claim) + (_ADVICE_SIGNAL if variant == "reversal" else "")
    return text, idx, {"certainty": certainty, "claim": claim, "variant": variant}


# =============================== araçta olmayan veri / gelecek ===============================
_UNSUPPORTED = [
    ("fundamental", "{T} hissesinin PD/DD ve FD/FAVÖK çarpanları nedir?"),
    ("macro", "Dolar/TL ve TCMB faizi {T} getirisini nasıl etkiledi? {D} itibarıyla USD/TRY kaç?"),
    ("news", "{T} hakkında son KAP açıklamaları ve haberler neler?"),
    ("future", "{T} hissesi önümüzdeki hafta kaç TL'den kapanacak? Analiz tarihinden sonraki fiyatı tahmin et."),
    ("macro", "Enflasyon ve kur gelişmeleri {T} için ne ifade ediyor? {D} itibarıyla politika faizi kaç?"),
    ("news", "{T} ile ilgili son dönemdeki haber akışı ve şirket duyuruları nasıl?"),
    ("future", "{D} sonrasındaki ilk iş gününde {T} kaç TL'den kapanır?"),
    ("fundamental", "{T} hissesinin F/K oranı kaç, bilançoları iyileşiyor mu?"),
    ("news", "{T} için son KAP bildirimleri ve analist yorumları neler söylüyor?"),
    ("future", "{T} hissesinin bir hafta sonraki kapanışı ne olacak?"),
    ("fundamental", "{T} şirketinin cari oranı ve likidite oranı son çeyrekte nasıl?"),
    ("macro", "{D} itibarıyla dolar kuru ve enflasyon verisi {T} hissesini nasıl etkiliyor?"),
    ("future", "{T} gelecek ay hangi seviyeye çıkar? Net bir fiyat ver."),
    ("fundamental", "{T} hissesinin temettü verimi ve borçluluk oranı nedir?"),
    ("macro", "TCMB'nin son faiz kararı ve USD/TRY seviyesi {T} için ne anlama geliyor?"),
    ("news", "{T} hissesi hakkında sosyal medyada ve haberlerde son durum nedir?"),
]


def _q_unsupported(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    idx = _template_index(split, len(_UNSUPPORTED), rng)
    kind, tpl = _UNSUPPORTED[idx]
    return tpl.format(T=ticker, D=fd(as_of)), idx, {"kind": kind}


# =============================== bayat veri ===============================
_STALE = [
    "{T} hissesinde {D} itibarıyla RSI ve Bollinger durumu nedir?",
    "{T} için {D} tarihindeki teknik görünüm nasıl?",
    "{D} itibarıyla {T} hissesinin Supertrend ve RSI değerlerini yorumla.",
    "{T} hissesinin {D} tarihindeki teknik göstergeleri ne söylüyor?",
]


def _q_stale(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    idx = _template_index(split, len(_STALE), rng)
    return _STALE[idx].format(T=ticker, D=fd(as_of)), idx, {"indicators": ["RSI", "BOLLINGER"]}


# =============================== bilanço (Soru 4) ===============================
BASIS_TEXT = {"QOQ": " bir önceki çeyreğe göre", "YOY": " geçen yılın aynı çeyreğine göre", None: ""}
METRIC_TEXT = {"EBITDA_MARGIN": "FAVÖK marjı", "NET_PROFIT_MARGIN": "net kâr marjı", "NET_PROFIT": "net kâr"}
# Şablonlar Soru 4 (docs/ornek_test_sorulari.txt) biçiminde: tüm çeyreklik bilançolar + 1/5/20 günlük tepki + "iyileşen çeyrekler daha iyi tepki almış mı".
# 0-4: "tüm çeyrekler", 5-7: "son çeyrek". Sıra % 4 == 3 (3, 7) yalnızca testte.
_FUNDAMENTAL = [
    "{T} hissesinin {S} – {D} döneminde kamuya açıklanan tüm çeyreklik bilançolarında {M} ve Net Borç/FAVÖK{B} nasıl değişti? Her açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler XU100'e ve sektöre göre nasıl oldu? İyileşen çeyrekler daha iyi fiyat tepkisi almış mı?{EXTRA}",
    "{T} için {S} – {D} arasında açıklanan çeyreklik bilançoları incele: {M} ve Net Borç/FAVÖK{B} ne yönde değişti? Açıklama sonrası 1, 5 ve 20 günlük tepkiyi XU100 ve sektörle karşılaştır; iyileşen çeyrekler daha iyi tepki almış mı?{EXTRA}",
    "{T} bilançolarında ({S} – {D}) {M} ve Net Borç/FAVÖK{B} nasıl bir seyir izledi? Her açıklamadan sonraki 1, 5 ve 20 günde hisse XU100'e ve sektöre göre ne yaptı? İyileşen çeyreklerde tepki daha mı iyi?{EXTRA}",
    "{S} – {D} döneminde açıklanan tüm çeyreklik bilançolarda {T} hissesinin {M} ve Net Borç/FAVÖK{B} nasıl değişti; açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler XU100'e ve sektöre göre nasıl? İyileşen çeyrekler daha iyi tepki almış mı?{EXTRA}",
    "{T} şirketinin {S} – {D} aralığındaki bilançolarında {M} ve Net Borç/FAVÖK{B} iyileşti mi? Açıklama sonrası 1, 5 ve 20 günlük anormal getiriyi (XU100 ve sektöre göre) iyileşen ve iyileşmeyen çeyrekler için ver.{EXTRA}",
    "{T} şirketinin son açıklanan bilançosunda {M} ve Net Borç/FAVÖK{B} nasıl değişti? Bilanço açıklamasından sonraki 1, 5 ve 20 günde hisse XU100'e ve sektöre göre nasıl hareket etti?{EXTRA}",
    "{D} itibarıyla açıklanmış son bilançoda {T} hissesinin {M} ve Net Borç/FAVÖK değişimi{B} nedir? Açıklama sonrası 1, 5 ve 20 günlük tepki XU100 ve sektöre göre nasıl?{EXTRA}",
    "{T}: son bilançonun {M} ve Net Borç/FAVÖK görünümü{B} nedir, açıklamanın ardından fiyat XU100 ve sektöre göre nasıl davrandı (1, 5, 20 gün)?{EXTRA}",
]
_FUNDAMENTAL_BANK = [
    "{T} bankasının {S} – {D} döneminde açıklanan tüm çeyreklik bilançolarında net faiz geliri ve net kâr{B} nasıl değişti? Her açıklamadan sonraki 1, 5 ve 20 günlük getiriler XU100'e göre nasıl oldu? İyileşen çeyrekler daha iyi tepki almış mı?{EXTRA}",
    "{T} için {S} – {D} arasındaki bilançolarda net faiz geliri ve net kâr{B} iyileşti mi? Açıklama sonrası 1, 5 ve 20 günde hisse XU100'e göre nasıl hareket etti?{EXTRA}",
    "{T} bankası bilançoları ({S} – {D}): net faiz geliri ve net kâr{B} ne yönde? Açıklamadan sonra fiyat XU100'e göre ne yaptı (1, 5, 20 gün)? İyileşen çeyreklerde tepki daha mı iyi?{EXTRA}",
    "{D} itibarıyla {T} bankasının açıklanmış son bilançosunda net kâr ve net faiz geliri{B} nedir? Açıklama sonrası 1, 5 ve 20 günlük tepki XU100'e göre nasıl?{EXTRA}",
]


def _is_bank(ticker: str) -> bool:
    from config.universe import load_universe
    u = load_universe().set_index("ticker")
    return "bank" in str(u.loc[ticker, "sector_label"]).lower()


@lru_cache(maxsize=None)
def first_visible_date(ticker: str) -> date | None:
    """Bilanço veri setinde hissenin İLK görünür tarihi (en erken disclosure_date): öncesinde araç NO_DATA verir, soru kurulmaz."""
    from tools._fundamentals import load_fundamentals
    t = load_fundamentals().table
    d = t.loc[t["ticker"] == ticker, "disclosure_date"].min()
    return None if d is None or str(d) == "NaT" else d.date()


@lru_cache(maxsize=None)
def fourth_visible_date(ticker: str) -> date | None:
    """Hissenin 4. çeyreğinin görünür olduğu ilk tarih (POLICY_MIN_QUARTERS=4: bundan önce etiket her zaman F1/INVESTIGATE)."""
    from tools._fundamentals import load_fundamentals
    t = load_fundamentals().table
    ds = sorted(t.loc[t["ticker"] == ticker, "disclosure_date"])
    return ds[3].date() if len(ds) >= 4 else None


FOURTH_QUARTER_BIAS = 0.7      # soruların bu payı, mümkünse 4. çeyreğin görünür olduğu tarihten sonraya kurulur (F2-F4 örnekleri için)


def pick_fundamental_date(split: str, rng: random.Random, ticker: str) -> date | None:
    """Bölme aralığında, hissenin bilançosunun görünür olduğu bir iş günü; yoksa None."""
    lo, hi = spec.DATE_RANGES[split]
    fv = first_visible_date(ticker)
    if fv is None:
        return None
    lo = max(lo, fv)
    if lo > hi:
        return None
    f4 = fourth_visible_date(ticker)
    if f4 is not None and rng.random() < FOURTH_QUARTER_BIAS and max(lo, f4) <= hi:
        lo = max(lo, f4)
    while True:
        d = lo + timedelta(days=rng.randint(0, (hi - lo).days))
        if d.weekday() < 5:
            return d


def _q_fundamental(split: str, rng: random.Random, as_of: date, ticker: str) -> tuple[str, int, dict[str, Any]]:
    bank = _is_bank(ticker)
    basis = rng.choice(["QOQ", "QOQ", "YOY", None])   # None: soruda belirtilmemiş (öğretmen QOQ kullanır: YoY için 2024 verisi yok)
    metric = "NET_PROFIT" if bank else rng.choice(["EBITDA_MARGIN", "EBITDA_MARGIN", "NET_PROFIT_MARGIN"])
    extra = " FUNDAMENTAL_IMPROVEMENT_CANDIDATE olarak etiketlenebilir mi?" if rng.random() < 0.4 else ""
    bank_templates = _FUNDAMENTAL_BANK
    templates = bank_templates if bank else _FUNDAMENTAL
    idx = _template_index(split, len(templates), rng)
    text = templates[idx].format(T=ticker, M=METRIC_TEXT[metric], B=BASIS_TEXT[basis], S=fd(date(2024, 1, 1)), D=fd(as_of), EXTRA=extra)
    return text, idx, {"basis": basis, "metric": metric, "bank": bank, "label_question": bool(extra)}


BUILDERS: dict[str, Callable[..., tuple[str, int, dict[str, Any]]]] = {
    "weekday": _q_weekday, "reversal": _q_reversal, "catch_up": _q_catch_up, "indicators": _q_indicators,
    "support_resistance": _q_sr, "history": _q_history, "advice": _q_advice, "unsupported": _q_unsupported, "stale": _q_stale,
    "fundamental": _q_fundamental,
}


def _rng(seed: int, *parts: object) -> random.Random:
    return random.Random(int(hashlib.sha256(":".join(map(str, (seed, *parts))).encode()).hexdigest()[:16], 16))


def build_questions(split: str, seed: int, allocation: dict[str, int]) -> list[Question]:
    """Bir bölme için belirlenimli sorular. Soru kimliği tip+bölme+sıra+metin özetinden; aynı metin tekrar üretilmez."""
    out: list[Question] = []
    seen: set[str] = set()
    for qtype, n in allocation.items():
        builder = BUILDERS[qtype]
        pool = tickers_for(split, qtype)
        for i in range(n):
            for attempt in range(200):
                rng = _rng(seed, split, qtype, i, attempt)
                if qtype == "fundamental":   # önce hisse, sonra hissenin bilançosunun görünür olduğu tarih (diğer tiplerin rastgele akışı DEĞİŞMEZ)
                    ticker = rng.choice(pool)
                    as_of = pick_fundamental_date(split, rng, ticker)
                    if as_of is None:
                        continue
                else:
                    as_of = pick_trading_date(split, rng, stale=(qtype == "stale"))
                    ticker = rng.choice(pool)
                hints: dict[str, Any] = {}
                if qtype == "reversal":   # sorunun ~%50'si hissede GERÇEKTEN taze sinyal olan günlere kurulur (signal_dates.py)
                    hints["family"] = rng.choice(list(_FAMILY_TEXT))
                    anchored = signal_dates(ticker, hints["family"], split)
                    if anchored and rng.random() < ANCHOR_SHARE:
                        as_of = rng.choice(anchored)
                body, idx, plan = builder(split, rng, as_of, ticker, **hints)
                text = _head(as_of) + body
                if text not in seen:
                    seen.add(text)
                    tickers = ("BIMAS", "MAVI", "MGROS") if qtype == "catch_up" else (ticker,)
                    qid = f"{split}-{qtype}-{i:04d}-{hashlib.sha256(text.encode()).hexdigest()[:8]}"
                    plan = {**plan, "ticker": ticker} if qtype != "catch_up" else plan
                    out.append(Question(qid, qtype, split, text, as_of, tickers, idx, plan))
                    break
            else:  # pragma: no cover
                raise RuntimeError(f"{split}/{qtype}/{i}: benzersiz soru üretilemedi")
    return out
