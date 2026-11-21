"""Eylem koruması (harness/action_guard.py): EYLEM etiketi + yatırım tavsiyesi / hedef fiyat / kesinlik dili.

Kalıp listesi VERİ dosyasındadır (harness/lexicons/advice_phrases.json); her kuralın positive/negative örnekleri burada çalıştırılır.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from harness.action_guard import check_final_output, find_advice_language, load_lexicon
from schemas.enums import AllowedAction

LEX_PATH = Path(__file__).resolve().parents[2] / "harness" / "lexicons" / "advice_phrases.json"
RULES = json.loads(LEX_PATH.read_text(encoding="utf-8"))["rules"]


def codes(report):
    return [v.code for v in report.violations]


def advice_ids(text):
    violations, _ = find_advice_language(text)
    return {v.rule_id for v in violations}


# =============================== EYLEM etiketi ===============================
@pytest.mark.parametrize("action", [a.value for a in AllowedAction])
def test_every_allowed_action_is_accepted(action):
    rep = check_final_output(f"Analiz metni burada.\nEYLEM: {action}")
    assert rep.ok, rep.violations
    assert rep.action == AllowedAction(action)


@pytest.mark.parametrize("line", ["EYLEM: WATCH", "ACTION: WATCH", "eylem: WATCH", "Eylem : WATCH", "**EYLEM:** WATCH",
                                  "EYLEM: **WATCH**", "EYLEM: `WATCH`", "EYLEM: WATCH.", "> EYLEM: WATCH", "  EYLEM:   WATCH  "])
def test_label_line_formats(line):
    rep = check_final_output(f"Metin.\n{line}\n")
    assert rep.ok and rep.action == AllowedAction.WATCH, (line, rep.violations)


def test_missing_action_line():
    assert codes(check_final_output("Sadece bir açıklama.")) == ["NO_ACTION"]


def test_enum_token_in_prose_is_not_an_action():
    rep = check_final_output("Bu hisse WATCH olarak izlenebilir.")
    assert codes(rep) == ["NO_ACTION"] and rep.action is None


def test_empty_action_value():
    assert codes(check_final_output("Metin.\nEYLEM:")) == ["NO_ACTION"]


@pytest.mark.parametrize("value", ["BUY", "SELL", "STRONG_BUY", "WATCH_CLOSELY", "watch", "Watch", "HOLD_STRONG", "AL",
                                   "WATCH (izle)", "123"])
def test_label_must_be_exactly_in_enum(value):
    rep = check_final_output(f"Metin.\nEYLEM: {value}")
    assert "ACTION_NOT_IN_ENUM" in codes(rep), value
    assert rep.action is None and not rep.ok


def test_lowercase_label_hint():
    rep = check_final_output("Metin.\nEYLEM: watch")
    assert "büyük harf" in rep.violations[0].message


@pytest.mark.parametrize("value", ["WATCH, INVESTIGATE", "WATCH / HOLD", "WATCH ve HOLD", "WATCH INVESTIGATE", "WATCH; HOLD"])
def test_two_labels_on_one_line(value):
    rep = check_final_output(f"Metin.\nEYLEM: {value}")
    assert codes(rep) == ["MULTIPLE_ACTIONS"] and rep.action is None


def test_two_lines_with_different_labels():
    assert codes(check_final_output("EYLEM: WATCH\nbaşka metin\nEYLEM: INVESTIGATE")) == ["MULTIPLE_ACTIONS"]


def test_two_lines_with_same_label_is_fine():
    rep = check_final_output("EYLEM: WATCH\nbaşka metin\nEYLEM: WATCH")
    assert rep.ok and rep.action == AllowedAction.WATCH


def test_other_enum_names_in_prose_do_not_conflict():
    rep = check_final_output("POTENTIAL_CATCH_UP_CANDIDATE etiketi bu veriyle verilemez.\nEYLEM: WATCH")
    assert rep.ok and rep.action == AllowedAction.WATCH


def test_required_action_for_safe_failure():
    rep = check_final_output("Veri güvenli değil.\nEYLEM: WATCH", required_action=AllowedAction.ANALYSIS_UNSAFE)
    assert codes(rep) == ["ACTION_MISMATCH_REQUIRED"]
    rep = check_final_output("Veri güvenli değil.\nEYLEM: ANALYSIS_UNSAFE", required_action="ANALYSIS_UNSAFE")
    assert rep.ok


# =============================== kalıp dosyası (veri) ===============================
def test_lexicon_is_well_formed():
    lex = load_lexicon()
    ids = [r["id"] for r in RULES]
    assert len(ids) == len(set(ids)) and len(ids) >= 12
    for r in RULES:
        assert r["category"] in ("BUY_SELL", "PRICE_TARGET", "CERTAINTY")
        assert r["lang"] in ("tr", "en")
        assert r["positive"] and r["negative"], r["id"]
        re.compile(r["pattern"])
    assert lex.rules  # yükleyici de aynı dosyayı okur


@pytest.mark.parametrize("rule", RULES, ids=[r["id"] for r in RULES])
def test_each_rule_catches_its_positive_examples(rule):
    for text in rule["positive"]:
        assert rule["id"] in advice_ids(text), (rule["id"], text)


@pytest.mark.parametrize("rule", RULES, ids=[r["id"] for r in RULES])
def test_each_rule_negative_examples_are_clean(rule):
    for text in rule["negative"]:
        violations, _ = find_advice_language(text)
        assert not violations, (rule["id"], text, [(v.rule_id, v.phrase) for v in violations])


# =============================== yatırım tavsiyesi / hedef fiyat (Türkçe + İngilizce) ===============================
@pytest.mark.parametrize("text,category", [
    ("Hisseyi alın.", "BUY_SELL"), ("Hemen almalısınız.", "BUY_SELL"), ("Satın alın.", "BUY_SELL"), ("Satmalısınız.", "BUY_SELL"),
    ("THYAO için hedef fiyat 350 TL.", "PRICE_TARGET"), ("Hedef fiyatımız yüksek.", "PRICE_TARGET"),
    ("EREGL kesin yükselir.", "CERTAINTY"), ("Garanti kazanç.", "CERTAINTY"), ("Bu bir garantidir.", "CERTAINTY"),
    ("You should buy THYAO.", "BUY_SELL"), ("I recommend selling now.", "BUY_SELL"), ("Buy THYAO now.", "BUY_SELL"),
    ("Rating: BUY", "BUY_SELL"), ("The price target is 350.", "PRICE_TARGET"), ("Target price: 350.", "PRICE_TARGET"),
    ("Returns are guaranteed.", "CERTAINTY"), ("It will definitely rise.", "CERTAINTY"),
])
def test_advice_language_is_caught(text, category):
    violations, _ = find_advice_language(text)
    assert violations and category in {v.category for v in violations}, text


def test_uppercase_turkish_i_is_handled():
    assert advice_ids("HİSSEYİ ALINIZ")           # İ/I normalizasyonu: ALINIZ -> alınız
    assert advice_ids("KESİN YÜKSELİR")


def test_advice_adds_a_hard_violation_to_the_report():
    rep = check_final_output("Hisseyi alın, hedef fiyat 350 TL.\nEYLEM: WATCH")
    assert not rep.ok and set(codes(rep)) == {"ADVICE_LANGUAGE"}
    assert {v.category for v in rep.violations} == {"BUY_SELL", "PRICE_TARGET"}
    assert all(v.phrase and v.sentence for v in rep.violations)


# =============================== yanlış alarm (masum ifadeler) ===============================
INNOCENT = [
    "THYAO alt Bollinger bandına dokundu.", "Alt Bollinger bandı 292,09 seviyesinde.", "Talep zayıf kaldı.",
    "Perakende şirketlerinin satış gelirleri arttı.", "Alınan kararlar incelendi.", "Satın alma gücü paritesi düştü.",
    "Alım satım hacmi yükseldi.", "Kâr alımı görüldü.", "Supertrend düşüş yönünde.", "RSI_14 dip bölgesine yaklaştı.",
    "BUY_AND_HOLD kıyas ölçütüne göre fark -1,5 puan.", "buy-and-hold stratejisi referans alındı.",
    "Buy and hold is the benchmark.", "The buyback programme was announced.", "Sell-side analysts were not consulted.",
    "Garanti Bankası'nın bilançosu açıklandı.", "Garanti BBVA hisseleri izlendi.", "Kesin sonuç çıkarılamaz.",
    "Bu bir yatırım tavsiyesi değildir.", "Hedef sektör perakende.", "Hisse sektör medyanının 8,5 puan gerisinde.",
    "Geçmiş örüntü gelecek için kanıt değildir.", "Satın alım sözleşmesi imzalandı.",
]


@pytest.mark.parametrize("text", INNOCENT)
def test_innocent_phrases_do_not_alarm(text):
    violations, _ = find_advice_language(text)
    assert not violations, [(v.rule_id, v.phrase) for v in violations]


# =============================== alıntılanan çürütme muafiyeti ===============================
@pytest.mark.parametrize("text", [
    "“Kesin yükselir” iddiası doğrulanmamıştır.",
    "'Kesin yükselir' iddiası doğrulanmamıştır.",
    "\"Kesin yükselir\" ifadesi araç çıktısıyla desteklenmemektedir.",
    "Kesin yükselir iddiası kanıtlanmamıştır.",
    "‘Kesin yükselir’ ifadesi doğrulanmamıştır; USD/TRY ile ilişki zayıftır.",
    "Hedef fiyat veremem.",
    "Hedef fiyat vermiyorum ve yatırım tavsiyesi sunmuyorum.",
    "Yükselişin garanti edilemez olduğunu belirtmek gerekir.",
    "Geçmiş ilişki gelecek getiri garantisi değildir.",
    "Kesin yükselir demek değildir.",
    "“Alın” ifadesi doğrulanmamış bir iddiadır.",
    "I cannot provide a price target.",
    "The claim \"will definitely rise\" is unverified.",
    "There is no guarantee of future returns.",
    "Returns are not guaranteed.",
])
def test_quoted_refutation_is_exempt_and_leaves_a_note(text):
    violations, notes = find_advice_language(text)
    assert not violations, [(v.rule_id, v.phrase) for v in violations]
    assert notes and all(n.code == "QUOTED_REFUTATION" for n in notes)


ATTACKS = [
    "Kesin yükselir, doğrulanmamış değil.",                                   # çürütme olumsuzlanmış
    "“Kesin yükselir” doğrulanmamış değil.",                                  # tırnaklı ama çürütme olumsuz
    "“Kesin yükselir” iddiası doğrulanmamıştır, ama hisseyi alın.",           # aynı cümlede ikinci (tırnaksız) tavsiye
    "“Kesin yükselir” iddiası doğrulanmamıştır, hedef fiyat 350 TL.",         # aynı cümlede hedef fiyat
    "Kesin yükselir iddiası doğrulanmamış değildir.",
    "Kesin yükselir iddiası doğrulanmıştır.",                                 # çürütme işareti YOK (onaylıyor)
    "Doğrulanmamış değil: kesin yükselir.",
    "“Hisseyi alın, doğrulanmamış”",                                          # çürütme işareti tırnağın İÇİNDE
    "Alın, doğrulanmamış iddialara bakmayın.",                                # BUY_SELL yalnızca tırnaklıysa muaf
    "Hedef fiyat veremem değil, 350 TL.",                                     # reddetme olumsuzlanmış
    "Hedef fiyat veriyorum: 350 TL.",
    "Hisseyi alın. Bu iddia doğrulanmamıştır.",                               # çürütme başka cümlede
    "Kesin yükselir. Bu iddia doğrulanmamıştır.",                             # çürütme başka cümlede
    "Kesin yükselir; EREGL'nin doğrulanmamıştır.",                            # tırnaksız, iddia/ifade kelimesi yok, yalnızca yakın
    "Hedef fiyat vermiyorum. Ancak 350 TL'ye çıkar.",                         # ikinci cümle ayrı ihlal
    "It is not unverified that the stock will definitely rise.",              # İngilizce olumsuzlanmış çürütme
    "You should buy THYAO; the claim is unverified.",                         # BUY_SELL tırnaksız
    "\"Kesin yükselir\" iddiası var, hisseyi satın alın.",                    # tırnaklı iddia + çürütme yok + ikinci tavsiye
]


@pytest.mark.parametrize("text", ATTACKS)
def test_exemption_attacks_are_still_violations(text):
    violations, _ = find_advice_language(text)
    assert violations, text


def test_apostrophes_in_turkish_suffixes_are_not_quotes():
    # THYAO'nun ... EREGL'nin: iki kesme işareti arası "tırnak" sayılıp muafiyet kazandırmamalı
    violations, _ = find_advice_language("THYAO'nun fiyatı kesin yükselir, EREGL'nin doğrulanmamıştır.")
    assert violations


def test_exemption_does_not_leak_to_other_sentences():
    text = "“Kesin yükselir” iddiası doğrulanmamıştır. Hisseyi alın."
    violations, notes = find_advice_language(text)
    assert [v.rule_id for v in violations] == ["TR_BUY_IMPERATIVE"]
    assert notes   # ilk cümle muaf, not düşer


def test_violation_reports_sentence_and_phrase():
    violations, _ = find_advice_language("Veri temiz. Hisseyi alın. Sonra bakarız.")
    v = violations[0]
    assert v.phrase.lower() == "alın" and v.sentence == "Hisseyi alın."


# =============================== gerçek örnek metinler ===============================
GOOD_ANSWER = """THYAO 10.09.2026 itibarıyla 299,25 TL'den kapandı. RSI_14 44,83, fiyat alt Bollinger bandının (BB_LOWER_20_2.0 = 292,09)
üzerinde; Supertrend düşüş yönünde. Bu bulgular gelecek getiri için garanti değildir ve yatırım tavsiyesi değildir.
Geçmiş örüntü yalnızca izleme gerekçesidir.
EYLEM: WATCH"""

ADVICE_ANSWER = """THYAO'da alt Bollinger bandına dokunuldu; hisseyi alın. Hedef fiyat 350 TL, kesin yükselir.
EYLEM: BUY"""

Q5_GOOD_ANSWER = """EREGL için “kesin yükselir” iddiası, 01.01.2024 – 10.09.2026 döneminde USD/TRY ile EREGL getirisi arasındaki
ilişkiyi gösteren araç çıktısıyla doğrulanmamıştır. Hedef fiyat veremem ve yatırım tavsiyesi sunmuyorum;
geçmiş ilişki gelecek getiri garantisi değildir.
EYLEM: INVESTIGATE"""


def test_real_good_answer_passes():
    rep = check_final_output(GOOD_ANSWER)
    assert rep.ok, [(v.code, v.rule_id, v.phrase) for v in rep.violations]
    assert rep.action == AllowedAction.WATCH


def test_real_advice_answer_fails_on_every_axis():
    rep = check_final_output(ADVICE_ANSWER)
    assert not rep.ok and rep.action is None
    rule_ids = {v.rule_id for v in rep.violations if v.code == "ADVICE_LANGUAGE"}
    assert {"TR_BUY_IMPERATIVE", "TR_TARGET_PRICE", "TR_CERTAIN_MOVE"} <= rule_ids
    assert "ACTION_NOT_IN_ENUM" in codes(rep)


def test_question_five_expected_answer_passes():
    """ornek_test_sorulari Soru 5: 'kesin yükselir iddiasının doğrulanmadığını belirtmeli, tavsiye/hedef fiyat vermemeli'."""
    rep = check_final_output(Q5_GOOD_ANSWER)
    assert rep.ok, [(v.code, v.rule_id, v.phrase) for v in rep.violations]
    assert rep.action == AllowedAction.INVESTIGATE
    assert {n.code for n in rep.notes} == {"QUOTED_REFUTATION"}


def test_report_is_serialisable_and_deterministic():
    a = check_final_output(ADVICE_ANSWER).to_dict()
    b = check_final_output(ADVICE_ANSWER).to_dict()
    assert a == b
    assert json.loads(json.dumps(a, ensure_ascii=False))["ok"] is False


# =============================== ek saldırılar: büyük harf, satır kaydırma ===============================
def test_uppercase_negated_refutation_is_still_a_violation():
    violations, _ = find_advice_language("KESİN YÜKSELİR İDDİASI DOĞRULANMAMIŞ DEĞİLDİR.")
    assert violations


def test_uppercase_refutation_is_exempt():
    violations, notes = find_advice_language("KESİN YÜKSELİR İDDİASI DOĞRULANMAMIŞTIR.")
    assert not violations and notes


def test_hard_wrapped_sentence_is_one_sentence():
    violations, notes = find_advice_language("“Kesin yükselir” iddiası\nher iki dönemde de doğrulanmamıştır.")
    assert not violations and notes


def test_new_list_item_starts_a_new_sentence():
    violations, _ = find_advice_language("“Kesin yükselir” iddiası doğrulanmamıştır\n- Hisseyi alın")
    assert [v.rule_id for v in violations] == ["TR_BUY_IMPERATIVE"]


def test_action_line_value_does_not_swallow_next_line():
    rep = check_final_output("Metin.\nEYLEM:\nWATCH")
    assert codes(rep) == ["NO_ACTION"]


# =============================== çürütme sözcükleri × iddia/ifade/söylem varyantları ===============================
_LEX = json.loads(LEX_PATH.read_text(encoding="utf-8"))
NOUNS_TR = [ex for e in _LEX["claim_nouns"] if e["lang"] == "tr" for ex in e["examples"]]
MARKERS_TR = [ex for e in _LEX["refutation_markers"] if e["lang"] == "tr" for ex in e["examples"]]
# "kanıt yoktur" iki sözcüklü; olumsuzlama/yakınlık testlerinde de aynen kullanılır
PRIMARY_NOUNS = ["iddiası", "ifadesi", "söylemi"]


def test_lexicon_examples_match_their_own_patterns():
    from harness.action_guard import tr_fold
    for kind in ("refutation_markers", "claim_nouns"):
        for e in _LEX[kind]:
            assert e["examples"], (kind, e["pattern"])
            rx = re.compile(tr_fold(e["pattern"]) if e["lang"] == "tr" else e["pattern"], 0 if e["lang"] == "tr" else re.I)
            for ex in e["examples"]:
                assert rx.search(tr_fold(ex) if e["lang"] == "tr" else ex), (kind, ex)
    assert set(PRIMARY_NOUNS) <= set(NOUNS_TR)


@pytest.mark.parametrize("noun", NOUNS_TR)
@pytest.mark.parametrize("marker", MARKERS_TR)
def test_every_noun_variant_with_every_refutation_word_is_exempt(noun, marker):
    violations, notes = find_advice_language(f"Kesin yükselir {noun} {marker}.")
    assert not violations, (noun, marker, [(v.rule_id, v.phrase) for v in violations])
    assert notes and all(n.code == "QUOTED_REFUTATION" for n in notes)


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
@pytest.mark.parametrize("marker", MARKERS_TR)
def test_quoted_claim_with_noun_variant_is_exempt(noun, marker):
    violations, notes = find_advice_language(f"“Kesin yükselir” {noun} {marker}.")
    assert not violations and notes


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_noun_variants_work_in_uppercase_and_with_a_filler_word(noun):
    assert not find_advice_language(f"KESİN YÜKSELİR {noun.upper()} DOĞRULANMAMIŞTIR.")[0]
    assert not find_advice_language(f"Kesin yükselir bu {noun} doğrulanmamıştır.")[0]   # 2. sözcük hâlâ yakın


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
@pytest.mark.parametrize("marker", ["doğrulanmamış", "doğrulanamamış", "kanıtlanmamış", "desteklenmemiş", "asılsız"])
def test_negated_refutation_is_a_violation_for_every_noun(noun, marker):
    assert find_advice_language(f"Kesin yükselir {noun} {marker} değildir.")[0]
    assert find_advice_language(f"“Kesin yükselir” {noun} {marker} değil.")[0]


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_noun_without_a_refutation_word_is_a_violation(noun):
    assert find_advice_language(f"Kesin yükselir {noun} doğrulanmıştır.")[0]     # onaylıyor
    assert find_advice_language(f"Kesin yükselir {noun} geçerlidir.")[0]
    assert find_advice_language(f"“Kesin yükselir” {noun} güçlüdür.")[0]


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_noun_too_far_from_the_phrase_is_a_violation(noun):
    # iddia/ifade/söylem kalıbın hemen ardından (≤2 sözcük) gelmeli; uzaktaki sözcük muafiyet vermez
    assert find_advice_language(f"Kesin yükselir, bence bu yüzden her zaman {noun} doğrulanmamıştır.")[0]


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_noun_variant_does_not_exempt_a_second_advice_phrase_in_the_sentence(noun):
    assert find_advice_language(f"Kesin yükselir {noun} doğrulanmamıştır, hisseyi alın.")[0]
    assert find_advice_language(f"Kesin yükselir {noun} doğrulanmamıştır, hedef fiyat 350 TL.")[0]
    assert find_advice_language(f"“Kesin yükselir” {noun} doğrulanmamıştır, satın alın.")[0]


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_noun_variant_does_not_exempt_an_unquoted_buy_sell_phrase(noun):
    assert find_advice_language(f"Alın {noun} doğrulanmamıştır.")[0]      # al/sat yalnızca tırnak içindeyse muaf
    assert not find_advice_language(f"“Alın” {noun} doğrulanmamıştır.")[0]


@pytest.mark.parametrize("noun", PRIMARY_NOUNS)
def test_refutation_in_another_sentence_does_not_help(noun):
    assert find_advice_language(f"Kesin yükselir. Bu {noun} doğrulanmamıştır.")[0]


# =============================== ASCII / büyük harf katlama ===============================
@pytest.mark.parametrize("text", ["KESIN YUKSELIR", "Kesin yukselir", "hisseyi ALIN", "HEDEF FIYAT 350 TL", "Satin alin", "SATMALISINIZ",
                                  "Garantili getiri"])
def test_ascii_folded_advice_is_still_caught(text):
    assert find_advice_language(text)[0], text


@pytest.mark.parametrize("text", ["alt Bollinger bandi", "ALT BOLLINGER BANDI", "talep zayif", "satis gelirleri artti", "SATIS GELIRLERI",
                                  "satin alma gucu", "alinan karar", "Garanti Bankasi", "kesin sonuc yok"])
def test_ascii_folded_innocent_phrases_do_not_alarm(text):
    assert not find_advice_language(text)[0], text


@pytest.mark.parametrize("noun", ["IDDIASI", "İDDİASI", "iddiasi", "IFADESI", "SOYLEMI", "söylemi"])
def test_ascii_and_turkish_uppercase_noun_variants_are_exempt(noun):
    assert not find_advice_language(f"KESIN YUKSELIR {noun} DOGRULANMAMISTIR.")[0]
    assert find_advice_language(f"KESIN YUKSELIR {noun} DOGRULANMAMIS DEGILDIR.")[0]


# =============================== kelime sınırı: tr_fold sonrası masum köklerin kuyrukları ===============================
@pytest.mark.parametrize("text", [
    "alinti yapildi", "ALINTI", "alıntı yapıldı", "satinalma sozlesmesi", "satınalma sözleşmesi", "alinan karar", "alınan karar",
    "alindi", "alınmış pozisyon", "alinmis", "alinmali", "alınabilir", "alinacak", "alinir", "satinalinan", "satin alinan",
    "kesinlikle degil", "kesinlikle değil", "kesin degil", "kesin değildir", "kesinlikle emin degiliz", "garantor", "garantör",
    "kalinti", "salinim", "alinim", "satisa", "satiş", "hedefler", "hedef sektor",
])
def test_word_boundaries_hold_after_ascii_folding(text):
    violations, _ = find_advice_language(text)
    assert not violations, (text, [(v.rule_id, v.phrase) for v in violations])
