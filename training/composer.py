"""Açıklama kurucu (öğretmen): nihai metin, KİLİTLİ kanıt cümlelerinden + politika gerekçe kodlarından kurulur. LLM YOK, belirlenimli.

Kurallar (training/RULES.md): sayılar yalnızca committed kanıttan ve AYNEN (türetme yok; UNEVIDENCED 0); etiket politikadan; aday etiketlerde
"tarihsel gözlem, örnek küçük, belirsizlik var" notu; kesinlik iddiasında `“…” iddiası … doğrulanmamıştır` biçimi; yatırım tavsiyesi/hedef fiyat yok.
Eşik sayıları (politika gerekçe metinleri) açıklamaya ALINMAZ: gerekçe KODLARI sayısız cümlelere eşlenir.
"""
from __future__ import annotations

import random
from typing import Any

from schemas.enums import AllowedAction as A

CAVEAT = "Bu yalnızca tarihsel bir gözlemdir: örnek küçük, belirsizlik var; geçmiş kanıt gelecek getiri garantisi değildir."

RULE_SENTENCES: dict[str, list[str]] = {
    "W1_STABLE": ["Örüntü örneklem içinde ve dışında kararlı görünüyor; haftalık örüntü için aday etiketi yoktur, bu yüzden yalnızca izleme (WATCH) verilir."],
    "W2_INSUFFICIENT": ["Örüntü için örneklem yetersiz; sonuç çıkarılamaz, daha fazla inceleme gerekir (INVESTIGATE).",
                        "Örneklem içinde yeterli tetik hafta yok; örüntü hakkında hüküm verilemez (INVESTIGATE)."],
    "W3_UNSTABLE": ["Örüntü istatistiksel olarak anlamlı değil ya da örneklem dışında devam etmiyor; sinyal reddedilir (REJECT_SIGNAL).",
                    "Örneklem içi bulgu örneklem dışında doğrulanmadı; örüntü kararsız, sinyal reddedilir (REJECT_SIGNAL)."],
    "T0_NO_PRIMARY_GROUP": ["Koşulsuz (tekli) olay grubu yok; birleşik gruplar tek başına etiket belirlemez (INVESTIGATE)."],
    "T1_FEW_EVENTS": ["Tamamlanmış olay sayısı yetersiz; sinyal güvenilir biçimde değerlendirilemez (INVESTIGATE).",
                      "Olay sayısı alt sınırın altında; sonuçlar belirsiz, daha fazla inceleme gerekir (INVESTIGATE)."],
    "T2_REJECT_HISTORY": ["Tarihsel doğrulama başarısız: isabet oranı çoğu ufukta taban oranın altında ve/veya örneklem dışında bozulma var; sinyal reddedilir (REJECT_SIGNAL).",
                          "Geçmiş veride sinyal taban oranı aşamıyor ya da örneklem dışında bozuluyor; sinyal reddedilir (REJECT_SIGNAL)."],
    "T3_CANDIDATE": ["Güncel bir sinyal var; tarihsel doğrulama ve backtest koşulları sağlanıyor. Bu nedenle TECHNICAL_REVERSAL_CANDIDATE etiketi verilir.",
                     "Son günlerde sinyal oluşmuş ve geçmiş doğrulama ile backtest olumlu; etiket TECHNICAL_REVERSAL_CANDIDATE."],
    "T4_VALIDATION_MISSING": ["Örneklem dışı doğrulama ya da uygun backtest eksik (OOS doğrulaması yapılmadı); aday etiket verilemez (INVESTIGATE).",
                              "Doğrulama adımları tamamlanmadı; kanıt aday etiketi desteklemiyor (INVESTIGATE)."],
    "T5_WATCH": ["Güncel sinyal yok ya da kanıt karışık; yalnızca izleme (WATCH) uygundur.", "Kanıt karışık: aday koşulları sağlanmıyor, izleme (WATCH) etiketi verilir."],
    "T6_NO_EVENTS": ["Geçerli taramada olay yok; sinyal koşulu oluşmadı (HOLD)."],
    "C1_PEERS_OR_STRENGTH": ["Peer grubu ya da sektör gücü yetersiz; karşılaştırma güvenilir değil (INVESTIGATE)."],
    "C2_NOT_LAGGARD": ["Hisse geride kalan eşiğinde değil; sinyal koşulu oluşmadı (HOLD).", "İncelenen hisse sektör medyanının yeterince gerisinde değil; sinyal oluşmadı (HOLD)."],
    "C3_FEW_EVENTS": ["Geçmiş geride kalma olaylarının tamamlanmış sayısı yetersiz; aday etiket verilemez (INVESTIGATE)."],
    "C4_REJECT_HISTORY": ["Tarihsel doğrulama başarısız: geride kalmalar çoğu ufukta taban oranı aşamadı ve/veya örneklem dışında bozuldu; sinyal reddedilir (REJECT_SIGNAL).",
                          "Geçmişte benzer geride kalmaların toparlanma isabeti taban oranın altında; sinyal reddedilir (REJECT_SIGNAL)."],
    "C5_CANDIDATE": ["Sektör güçlü, hisse geride ve geçmiş doğrulama ile backtest olumlu; etiket POTENTIAL_CATCH_UP_CANDIDATE."],
    "C5S_SUBJECT_CAP": ["Havuzlu kanıt olumlu olsa da hisse bazlı tutarlılık denetimi başarısız (olay sayısı az ya da kendi geçmişi bazın altında); aday etiket verilmez, izleme (WATCH)."],
    "C6_VALIDATION_MISSING": ["Örneklem dışı doğrulama ya da uygun backtest eksik (OOS doğrulaması yapılmadı); aday etiket verilemez (INVESTIGATE)."],
    "C7_WATCH": ["Kanıt karışık: aday koşulları sağlanmıyor, izleme (WATCH) etiketi verilir."],
    "G1_GATE_UNSAFE": ["Veri kalitesi kapısı analizin güvenli olmadığını gösteriyor; araç sonucu üretilmedi ve etiket ANALYSIS_UNSAFE olur."],
    "G2_GATE_MISSING": ["Kalite kapısı sonucu yok; güvenli varsayılan INVESTIGATE."],
    "G3_GATE_INVESTIGATE": ["Kalite kapısı INVESTIGATE verdiği için aday etiket verilemez; etiket INVESTIGATE."],
    "G5_CANDIDATE_VS_REJECT": ["Aynı hisse için aday sinyal ile ret çelişiyor; çelişkili kanıtta temkinli etiket INVESTIGATE verilir."],
    "G5_DIFFERENT_CANDIDATES": ["Birden çok farklı aday sinyal çıktı; tek aday seçilemediği için izleme (WATCH) verilir."],
    "G6_ADVICE_CAP": ["Soruda al/sat ve hedef fiyat isteği var; yatırım tavsiyesi verilmez, aday etiket izleme (WATCH) düzeyine indirilir."],
    "G7_NO_SCENARIO": ["Bu soru için etiketi belirleyecek bir senaryo analizi (haftalık örüntü, teknik dönüş, catch-up) yok; çıktı bilgi amaçlıdır (INVESTIGATE).",
                       "Eldeki araç çıktıları durum bilgisi veriyor, ama bir sinyali doğrulamıyor; etiket INVESTIGATE."],
    "G7_UNVERIFIED_CLAIM": ["Kullanıcının kesinlik iddiası araç çıktılarıyla doğrulanmıyor; etiket INVESTIGATE."],
}

REASON_SENTENCES = {
    "FEW_EVENTS": "Olay sayısı az olduğundan sonuçlar belirsizdir.",
    "OOS_VALIDATION_MISSING": "Örneklem dışı doğrulama yapılmadı.",
    "BACKTEST_MISSING": "Aynı sinyal türü için uygun backtest bulunamadı.",
    "BACKTEST_NO_TEST_SPLIT": "Backtest'te test dilimi yok.",
    "BACKTEST_LOW_SIGNAL": "Backtest'te sinyal sayısı az; getiri güvenilir değil.",
    "HISTORICAL_VALIDATION_FAILED": "Tarihsel doğrulama başarısız oldu.",
    "SUBJECT_FEW_EVENTS": "Hisse bazında tamamlanmış olay sayısı çok az.",
    "SUBJECT_BELOW_BASELINE": "Hisse kendi geçmişinde çoğu ufukta kendi taban oranının altında kaldı.",
    "SUBJECT_BREAKDOWN_MISSING": "Hisse bazlı kırılım olmadığından tutarlılık doğrulanamadı.",
    "SMALL_PEER_GROUP": "Peer grubu küçük olduğundan karşılaştırma zayıf.",
}
DISCLAIMER = ["Bu çıktı yatırım tavsiyesi değildir; yalnızca araç çıktılarına dayalı tarihsel bir değerlendirmedir.",
              "Not: bu bir yatırım tavsiyesi değil, geçmiş verilerin özetidir."]
OPENINGS = {
    "weekday": ["{T} için istenen haftalık örüntü örneklem içi ve dışı ayrılarak test edildi.", "{T} hissesindeki haftalık örüntü araçla test edildi; bulgular aşağıda."],
    "reversal": ["{T} hissesinde istenen teknik dönüş sinyali tarihsel olarak incelendi.", "{T} için sinyal olayları ve ileri getiriler araçla hesaplandı."],
    "catch_up": ["Perakende grubunda geride kalma ve tarihsel toparlanma araçla incelendi.", "Sektör içi göreli performans ve geçmiş geride kalmalar hesaplandı."],
    "indicators": ["{T} için teknik gösterge durumu araçla hesaplandı.", "{T} hissesinin istenen göstergeleri analiz tarihi itibarıyla incelendi."],
    "support_resistance": ["{T} için destek ve direnç seviyeleri araçla hesaplandı.", "{T} fiyatının en yakın seviyelere göre konumu incelendi."],
    "history": ["{T} için fiyat geçmişi ve teknik durum araçlarla alındı.", "{T} hissesinin dönem içi kapanış aralığı araç çıktısından okundu."],
    "advice": ["{T} için araçla elde edilen veriler aşağıda; ancak yatırım tavsiyesi ve hedef fiyat veremem.", "{T} hakkında tarihsel veriler incelendi; bunlar yatırım tavsiyesi değildir ve hedef fiyat veremem."],
    "unsupported": ["Sorulan bilgi bu sistemde mevcut araçlarla doğrulanamıyor; yalnızca {T} için teknik durum alınabildi.",
                    "Bu soru mevcut araç çıktılarıyla yanıtlanamıyor; elde yalnızca {T} için teknik gösterge verisi var."],
    "stale": ["{T} için analiz denendi ancak veri kalitesi kapısı engelledi.", "{T} analizi için çağrı yapıldı; kalite kapısı veriyi güvenli bulmadı."],
}
UNSUPPORTED_NOTE = {
    "fundamental": "Bilanço ve oran verileri (FAVÖK, F/K, kâr, borçluluk) için kullanılabilir bir araç yok; bu nedenle bu sayılar verilemez.",
    "macro": "Kur, faiz ve enflasyon verileri için kullanılabilir bir araç yok; bu nedenle makro etkiler değerlendirilemez ve bu sayılar verilemez.",
    "news": "Haber ve KAP açıklamaları için kullanılabilir bir araç yok; bu nedenle haber akışı hakkında bilgi verilemez.",
    "future": "Analiz tarihinden sonraki fiyat bilgisi kullanılamaz ve gelecek fiyatı tahmin edilemez; kesin bir seviye vermek mümkün değil.",
}
STALE_NOTE = "Analiz tarihi eldeki verinin bitişinden çok sonra; veri güncel değil. Bu yüzden araç sonucu üretilmedi ve sayı verilemez."
MULTIPLE_TESTING_NOTE = "Çoklu test riski (MULTIPLE_TESTING_RISK): örüntü tek hipotezdir; aynı veride başka örüntüler denenirse tesadüfi bulgu riski artar."
LATEST_QUALIFIER = "Göstergeler yalnızca analiz günü itibarıyla durumu gösterir; nedensellik ya da gelecek getiri iddiası içermez."


def _val(item: dict[str, Any], name: str) -> Any:
    return next((v["value"] for v in item["values"] if v["name"] == name), None)


def _pick(items: list[dict[str, Any]], qtype: str, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Türe göre kanıt cümleleri (sıra korunur). Hepsi committed kanıttır."""
    by_tool: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        by_tool.setdefault(it["source_tool"], []).append(it)
    out: list[dict[str, Any]] = []

    def horizons(tool_items: list[dict[str, Any]], want: tuple[int, ...]) -> list[dict[str, Any]]:
        hz = [i for i in tool_items if _val(i, "horizon") is not None and _val(i, "n_events_complete") is not None]
        chosen = [i for i in hz if _val(i, "horizon") in want]
        return chosen or hz[:2]

    for tool, its in by_tool.items():
        if tool == "test_weekday_pattern":
            out += its
        elif tool == "detect_reversal_events":
            out += [i for i in its if _val(i, "n_events_detected") is not None][:1] + horizons(its, (5,))[:1]
        elif tool == "run_backtest":
            out += [i for i in its if _val(i, "cumulative_return_pct") is not None and _val(i, "variant") is not None][:1]
            out += [i for i in its if _val(i, "last_exit_date") is not None][:1]
        elif tool == "rank_sector_relative_strength":
            sector = [i for i in its if _val(i, "peer_group_size") is not None and _val(i, "horizon") is None][:1]
            lag = [i for i in its if _val(i, "lag_score_pp") is not None][:1]
            out += sector + lag + horizons(its, (20, 5))[:1]
        elif tool == "calculate_indicators":
            out += its[:1]
        elif tool in ("get_stock_history", "get_index_history"):
            out += its[:1]
        else:
            out += its[:1]
    return out


def compose_final(*, qtype: str, plan: dict[str, Any], ticker: str, label: A, rule_id: str, reasons: list[tuple[str, str]], evidence: list[dict[str, Any]],
                  rng: random.Random, claim: str | None = None) -> str:
    """Nihai metin: açılış, kanıt maddeleri, değerlendirme, sınırlamalar, uyarı, `EYLEM:` satırı."""
    lines = [rng.choice(OPENINGS[qtype]).format(T=ticker)]
    picked = _pick(evidence, qtype, plan)
    if picked:
        lines.append("Kanıt (araç çıktıları):")
        lines += [f"- {it['statement']}" for it in picked]
    verdict = [rng.choice(RULE_SENTENCES[rule_id])] if rule_id in RULE_SENTENCES else []
    codes = [c for c, _ in reasons]
    extra = [REASON_SENTENCES[c] for c in codes if c in REASON_SENTENCES]
    if "ADVICE_INTENT_CAP" in codes and rule_id != "G6_ADVICE_CAP":
        extra.append("Soruda al/sat ve hedef fiyat isteği var; tavsiye verilmediği için aday etiket izleme düzeyine indirildi.")
    block = ["Değerlendirme: " + " ".join(verdict)] if verdict else []
    block += extra
    if qtype == "weekday" or any(i["source_tool"] == "test_weekday_pattern" for i in evidence):
        block.append(MULTIPLE_TESTING_NOTE)
    if qtype in ("indicators", "support_resistance", "history", "advice", "unsupported") and any(i["source_tool"] == "calculate_indicators" for i in evidence):
        block.append(LATEST_QUALIFIER)
    if qtype == "advice":
        block.append("Yatırım tavsiyesi ve hedef fiyat veremem.")
        if claim:
            block.append(f"“{claim}” iddiası araç çıktılarıyla doğrulanmamıştır; veri bunu desteklemiyor.")
    if qtype == "unsupported":
        block.append(UNSUPPORTED_NOTE[plan["kind"]])
    if qtype == "stale":
        block.append(STALE_NOTE)
    if label in (A.POTENTIAL_CATCH_UP_CANDIDATE, A.TECHNICAL_REVERSAL_CANDIDATE, A.FUNDAMENTAL_IMPROVEMENT_CANDIDATE) or "CANDIDATE_CAVEAT" in codes:
        block.append(CAVEAT)
    if not (qtype == "stale"):
        block.append(rng.choice(DISCLAIMER))
    lines += block
    lines.append(f"EYLEM: {label.value}")
    return "\n".join(lines)
