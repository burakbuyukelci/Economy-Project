"""Sayı doğrulayıcı (harness/number_verifier.py): çıkarma, maskeleme, izin listesi, yuvarlama, iki seviye, türetilmiş sayı.

Birim testler küçük elle yazılmış zarflarla, entegrasyon testleri THYAO 10.09.2026 GERÇEK zarflarıyla çalışır.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from harness.number_verifier import extract_claims, verify_numbers

D = Decimal
QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO için durum nedir?"


def env(results, *, tool="rank_sector_relative_strength", params=None, status="OK", h="a" * 64):
    return {"tool": tool, "params": params if params is not None else {"as_of": "2026-09-10"}, "as_of": "2026-09-10",
            "data_version": "snap_2026-11-20_v2", "input_hash": h, "results": results if status == "OK" else None,
            "status": status}


def one(text):
    claims = extract_claims(text)
    assert len(claims) == 1, [c.raw for c in claims]
    return claims[0]


def values(claim):
    return [c.value for c in claim.candidates]


# =============================== çıkarma: sayı biçimleri ===============================
@pytest.mark.parametrize("text,value,decimals", [
    ("fark 1.234,56 birim", D("1234.56"), 2),
    ("fark 8,5 birim", D("8.5"), 1),
    ("fark 8.5 birim", D("8.5"), 1),
    ("değer 0.123 oldu", D("0.123"), 3),       # baştaki 0: binlik ayracı olamaz
    ("değer 12.345.678 lot", D("12345678"), 0),  # birden çok binlik grubu
    ("değer 1,234.56 USD", D("1234.56"), 2),   # İngilizce biçim
    ("sayı 14 adet", D("14"), 0),
    ("oran 8,50 civarı", D("8.50"), 2),        # yazılan sıfırlar basamak sayısını belirler
])
def test_number_formats(text, value, decimals):
    c = one(text)
    assert values(c) == [value]
    assert c.candidates[0].decimals == decimals
    assert c.kind == "number"


def test_ambiguous_thousands_has_two_candidates():
    """'1.234' hem 1234 (Türkçe binlik) hem 1,234 (ondalık) olabilir; ikisi de aday."""
    c = one("hacim 1.234 lot")
    assert values(c) == [D("1234"), D("1.234")]
    assert [x.decimals for x in c.candidates] == [0, 3]


@pytest.mark.parametrize("text", ["isabet %8,5 oldu", "isabet % 8,5 oldu", "isabet 8,5% oldu", "isabet yüzde 8,5 oldu",
                                  "isabet Yüzde 8,5 oldu"])
def test_percent_forms(text):
    c = one(text)
    assert c.kind == "percent"
    assert values(c) == [D("8.5")]


@pytest.mark.parametrize("text", ["8,5 puan geride", "8,5 pp geride", "8,5 yüzde puan geride"])
def test_points_kind(text):
    assert one(text).kind == "pp"


@pytest.mark.parametrize("text,value", [("fark -8,5 puan", D("-8.5")), ("fark −8,5 puan", D("-8.5")),
                                        ("fark (-8,5) puan", D("-8.5")), ("fark +3,2 puan", D("3.2"))])
def test_signs(text, value):
    assert values(one(text)) == [value]


def test_range_dash_is_not_a_sign():
    assert [values(c)[0] for c in extract_claims("2024-2025 döneminde")] == [D("2024"), D("2025")]


@pytest.mark.parametrize("text,value", [("38,4 milyon lot", D("38400000")), ("2 milyar TL", D("2000000000")),
                                        ("12 bin adet", D("12000")), ("38.4 million shares", D("38400000"))])
def test_scale_words(text, value):
    """Gerçek hacim 38386110 olduğu için '38,4 milyon' yazılabilir: ölçek kelimesi değeri çarpar."""
    c = one(text)
    assert values(c) == [value]


def test_suffix_attached_numbers_still_count():
    assert values(one("20-günlük getiri")) == [D("20")]
    assert values(one("14'ü kazandı")) == [D("14")]
    assert values(one("%8,5'lik düşüş")) == [D("8.5")]


# =============================== çıkarma: tarihler ===============================
@pytest.mark.parametrize("text,d", [("tarih 10.09.2026", date(2026, 9, 10)), ("tarih 2026-09-10", date(2026, 9, 10)),
                                    ("tarih 10/09/2026", date(2026, 9, 10)), ("tarih 5.1.2026", date(2026, 1, 5)),
                                    ("tarih 10 Eylül 2026", date(2026, 9, 10)), ("tarih 3 şubat 2025", date(2025, 2, 3)),
                                    ("tarih 10 EYLÜL 2026", date(2026, 9, 10))])
def test_dates(text, d):
    c = one(text)
    assert c.kind == "date"
    assert c.date == d


def test_date_components_are_not_numbers():
    assert [c.kind for c in extract_claims("10.09.2026 ile 2026-09-10")] == ["date", "date"]


def test_invalid_date_is_a_date_claim_without_value():
    c = one("tarih 31.02.2026")
    assert c.kind == "date" and c.date is None


def test_day_month_without_year_is_a_number():
    assert values(one("oran 10.09 civarı")) == [D("10.09")]


# =============================== çıkarma: sayı SAYILMAYANLAR ===============================
@pytest.mark.parametrize("text", [
    "XU100 endeksi", "2025Q1 bilançosu", "2026H1 dönemi", "BB_LOWER_20_2.0 sütunu", "RSI_14 değeri", "SUPERTREND_10_3.0",
    "kanıt E7 gösteriyor", "kanıt [E12] gösteriyor", "snap_2026-11-20_v2 sürümü", "THYAO.IS sembolü", "olay kap-0001",
    "bkz. https://example.org/a/2026/09/10 sayfası", "kaynak [1] ve [2,3]", "saat 18:30 civarı", "RSI14 değeri",
    "2. çeyrek bilançosu", "3. sırada", "COVID-19 etkisi",
])
def test_not_counted(text):
    assert extract_claims(text) == []


def test_list_numbers_not_counted_but_content_is():
    text = "Bulgular:\n1) Kapanış 299,25 oldu.\n2. İkinci madde 8,5 puan.\n  (3) Üçüncü.\n- 4. Dördüncü"
    assert [values(c)[0] for c in extract_claims(text)] == [D("299.25"), D("8.5")]


def test_numbered_line_start_decimal_is_not_a_list_marker():
    assert values(one("8,5 puan geride kaldı")) == [D("8.5")]


def test_claims_are_ordered_by_position_and_have_spans():
    text = "önce 5 sonra 8,5 sonra %7"
    cs = extract_claims(text)
    assert [values(c)[0] for c in cs] == [D("5"), D("8.5"), D("7")]
    assert [text[c.start:c.end] for c in cs] == ["5", "8,5", "%7"]


# =============================== eşleştirme: yuvarlama kuralı ===============================
def verify(text, results, **kw):
    return verify_numbers(text, envelopes=[env(results)], question=kw.pop("question", ""), **kw)


def only(report):
    assert len(report.claims) == 1, [r.claim.raw for r in report.claims]
    return report.claims[0]


def test_exact_integer_and_float():
    assert only(verify("sayı 14", {"n": 14})).match_kind == "EXACT"
    assert only(verify("sayı 14", {"n": 14.0})).match_kind == "EXACT"
    assert only(verify("oran 8,5", {"x": 8.5})).match_kind == "EXACT"
    assert only(verify("oran 8,50", {"x": 8.5})).match_kind == "EXACT"       # fazladan sıfır aynı sayıdır
    assert only(verify("oran 8,5", {"x": 8.50})).verdict == "SUPPORTED"


def test_rounding_to_written_decimals():
    r = only(verify("oran 8,5", {"x": 8.46}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "ROUNDED")
    r = only(verify("RSI 44,83", {"RSI_14": 44.8273}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "ROUNDED")


def test_rounding_is_half_up_on_decimal_not_float():
    # round(8.45, 1) == 8.4 (ikili kayan nokta); Decimal(repr) yarıdan yukarı: 8.5
    assert only(verify("oran 8,5", {"x": 8.45})).verdict == "SUPPORTED"
    assert only(verify("oran 8,4", {"x": 8.45})).verdict == "HALLUCINATION"


def test_truncation_is_not_rounding():
    assert only(verify("oran 8,4", {"x": 8.469})).verdict == "HALLUCINATION"   # 8,469 -> 8,5
    assert only(verify("oran 8,5", {"x": 8.469})).verdict == "SUPPORTED"


def test_more_precision_than_tool_is_hallucination():
    assert only(verify("oran 8,46", {"x": 8.5})).verdict == "HALLUCINATION"


def test_integer_written_matches_only_same_integer_exactly():
    assert only(verify("sayı 8", {"x": 8.0})).match_kind == "EXACT"
    assert only(verify("sayı 8", {"x": 8})).match_kind == "EXACT"


def test_integer_written_vs_fractional_pool_is_rounded_coarse():
    r = only(verify("sayı 8", {"x": 8.46}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "ROUNDED_COARSE")


def test_integer_written_prefers_exact_over_coarse():
    r = only(verify("sayı 8", {"x": 8.46, "y": 8}))
    assert r.match_kind == "EXACT"


def test_coarse_does_not_cross_the_half():
    assert only(verify("sayı 8", {"x": 8.6})).verdict == "HALLUCINATION"   # 8,6 -> 9


def test_scale_words_match_scaled_pool_value():
    r = only(verify("hacim 38,4 milyon lot", {"volume": 38386110.0}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "ROUNDED")
    r = only(verify("hacim 38 milyon lot", {"volume": 38386110.0}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "ROUNDED_COARSE")
    assert only(verify("hacim 40 milyon lot", {"volume": 38386110.0})).verdict == "HALLUCINATION"


def test_sign_relaxed_is_labelled_separately():
    r = only(verify("8,5 puan geride", {"lag_score_pp": -8.5}))
    assert (r.verdict, r.match_kind) == ("SUPPORTED", "SIGN_RELAXED")
    r = only(verify("fark -8,5", {"x": 8.5}))
    assert r.match_kind == "SIGN_RELAXED"
    assert only(verify("fark -8,5", {"x": -8.5})).match_kind == "EXACT"       # işaret tutuyorsa gevşetme yok


def test_sign_relaxed_still_rejects_wrong_magnitude():
    assert only(verify("9,5 puan geride", {"lag_score_pp": -8.5})).verdict == "HALLUCINATION"


def test_unit_agnostic_percent_matches_any_field():
    assert only(verify("%8,5", {"anything_pp": 8.5})).verdict == "SUPPORTED"


def test_ambiguous_number_matches_either_reading():
    assert only(verify("hacim 1.234 lot", {"v": 1234})).verdict == "SUPPORTED"
    assert only(verify("oran 1.234", {"v": 1.234})).verdict == "SUPPORTED"
    assert only(verify("hacim 1.234 lot", {"v": 99})).verdict == "HALLUCINATION"


def test_bool_is_not_a_number():
    assert only(verify("sayı 1", {"flag": True})).verdict == "HALLUCINATION"


def test_numbers_inside_result_strings_are_in_pool():
    r = only(verify("eşik 10 olay", {"verdict_reason": "IS_TOO_FEW: n_trigger_weeks=3 < 10"}))
    assert r.verdict == "SUPPORTED"


def test_nested_structures_and_sources_are_reported():
    res = {"groups": [{"per_horizon": [{"full": {"hit_rate_pct": 66.7}}]}]}
    r = only(verify("isabet %66,7", res))
    assert r.verdict == "SUPPORTED"
    assert r.sources and r.sources[0].tool == "rank_sector_relative_strength"
    assert r.sources[0].path == "groups[0].per_horizon[0].full.hit_rate_pct"


def test_error_and_bundle_envelopes_are_not_in_pool():
    bad = env(None, status="ERROR")
    bundle = env({"x": 77}, tool="build_evidence_bundle")
    rep = verify_numbers("sayı 77", envelopes=[bad, bundle, env({"y": 1})], question="")
    assert only(rep).verdict == "HALLUCINATION"


# =============================== tarihler ===============================
def test_date_in_pool_supports_in_any_format():
    res = {"disclosure_date": "2026-08-12"}
    assert only(verify("açıklama 12.08.2026", res)).verdict == "SUPPORTED"
    assert only(verify("açıklama 2026-08-12", res)).match_kind == "DATE"
    assert only(verify("açıklama 12 Ağustos 2026", res)).verdict == "SUPPORTED"


def test_date_not_in_any_output_is_hallucination():
    assert only(verify("açıklama 13.08.2026", {"disclosure_date": "2026-08-12"})).verdict == "HALLUCINATION"


def test_invalid_date_is_hallucination():
    assert only(verify("açıklama 31.02.2026", {"d": "2026-08-12"})).verdict == "HALLUCINATION"


def test_date_components_do_not_match_as_numbers():
    # havuzda 12, 8, 2026 sayıları var ama tarih yok: tarih iddiası ayrı bir şeydir
    assert only(verify("açıklama 12.08.2026", {"a": 12, "b": 8, "c": 2026})).verdict == "HALLUCINATION"


# =============================== izin listesi ===============================
def test_question_numbers_and_dates_are_allowlisted():
    rep = verify_numbers("Soruda geçen 20 gün ve 01.01.2024 tarihi", question="son 20 işlem günü, 01.01.2024 başlangıç",
                         envelopes=[env({"x": 1})])
    assert [r.verdict for r in rep.claims] == ["ALLOWLISTED", "ALLOWLISTED"]
    assert rep.n_claims == 0 and rep.n_allowlisted == 2


def test_tool_call_params_are_allowlisted_including_nested_and_dates():
    params = {"as_of": "2026-09-10", "horizon": 20, "pattern": [{"weekday": "MON", "n": 3}], "config": {"std": 2.0},
              "start": "2024-01-01"}
    rep = verify_numbers("ufuk 20, std 2,0, üç değil 3, başlangıç 01.01.2024 ve 10.09.2026", question="",
                         envelopes=[env({"x": 1}, params=params)])
    assert [r.verdict for r in rep.claims] == ["ALLOWLISTED"] * 5


def test_allowlist_is_exact_not_rounded():
    rep = verify_numbers("ufuk 20,4", question="son 20 gün", envelopes=[env({"x": 1})])
    assert only(rep).verdict == "HALLUCINATION"


def test_allowlisted_claims_are_not_in_the_denominator():
    rep = verify_numbers("20 gün içinde %8,5 ve %99,9", question="son 20 gün", envelopes=[env({"x": 8.5})])
    assert (rep.n_claims, rep.n_allowlisted, rep.n_supported, rep.n_hallucinated) == (2, 1, 1, 1)
    assert rep.numerical_hallucination_rate == pytest.approx(0.5)


# =============================== iki seviye + metrikler ===============================
COMMITTED = [{"evidence_id": "E1", "statement": "Gözlem 14, isabet %66.7", "source_tool": "rank_sector_relative_strength",
              "source_input_hash": "a" * 64, "values": [{"name": "hit_rate_pct", "value": 66.7, "unit": "pct"}]}]
RES = {"hit_rate_pct": 66.7, "n": 14, "context_value": 3.21, "when": "2026-08-12"}


def test_two_levels():
    rep = verify_numbers("isabet %66,7, gözlem 14, bağlam 3,21 ve uydurma 55,5", question="",
                         envelopes=[env(RES)], committed_evidence=COMMITTED)
    by = {r.claim.raw: r.verdict for r in rep.claims}
    assert by == {"%66,7": "SUPPORTED", "14": "SUPPORTED", "3,21": "UNEVIDENCED", "55,5": "HALLUCINATION"}
    assert (rep.n_claims, rep.n_supported, rep.n_unevidenced, rep.n_hallucinated) == (4, 2, 1, 1)
    assert rep.numerical_hallucination_rate == pytest.approx(0.25)
    assert rep.unevidenced_rate == pytest.approx(0.25)
    assert rep.tier2_enabled is True


def test_committed_value_numbers_count_even_if_statement_lacks_them():
    committed = [{"evidence_id": "E1", "statement": "metin sayısız", "source_tool": "x", "source_input_hash": "a" * 64,
                  "values": [{"name": "n", "value": 14, "unit": None}]}]
    rep = verify_numbers("gözlem 14", question="", envelopes=[env(RES)], committed_evidence=committed)
    assert only(rep).verdict == "SUPPORTED"


def test_committed_dates_count():
    committed = [{"evidence_id": "E1", "statement": "x", "source_tool": "x", "source_input_hash": "a" * 64,
                  "values": [{"name": "disclosure_date", "value": "2026-08-12", "unit": None}]}]
    rep = verify_numbers("açıklama 12.08.2026", question="", envelopes=[env(RES)], committed_evidence=committed)
    assert only(rep).verdict == "SUPPORTED"
    rep = verify_numbers("açıklama 12.08.2026", question="", envelopes=[env(RES)], committed_evidence=[])
    assert only(rep).verdict == "UNEVIDENCED"


def test_no_evidence_set_disables_tier_two():
    rep = verify_numbers("bağlam 3,21", question="", envelopes=[env(RES)], committed_evidence=None)
    assert only(rep).verdict == "SUPPORTED"
    assert rep.tier2_enabled is False and rep.n_unevidenced == 0


def test_empty_committed_set_makes_everything_unevidenced():
    rep = verify_numbers("bağlam 3,21", question="", envelopes=[env(RES)], committed_evidence=[])
    assert only(rep).verdict == "UNEVIDENCED"


def test_hallucination_is_never_downgraded_to_unevidenced():
    rep = verify_numbers("uydurma 55,5", question="", envelopes=[env(RES)], committed_evidence=COMMITTED)
    assert only(rep).verdict == "HALLUCINATION"


def test_match_kind_counters_separate_and_total():
    res = {"a": 8.46, "b": 8.0, "c": 44.8273}
    rep = verify_numbers("RSI 44,83, tam 8, kaba 9 yok, sayı 8,5 ve kaba 45 ve işaret 8,5 değil 8", question="",
                         envelopes=[env(res)])
    # 44,83 ROUNDED; 8 EXACT; 9 HALLUCINATION; 8,5 ROUNDED (8.46); 45 ROUNDED_COARSE; 8,5 ROUNDED; 8 EXACT
    assert rep.n_rounded == 3
    assert rep.n_rounded_coarse == 1
    assert rep.n_rounded_total == 4
    assert rep.n_exact == 2
    assert rep.n_hallucinated == 1
    assert rep.n_sign_relaxed == 0


def test_sign_relaxed_counter():
    rep = verify_numbers("geride 8,5 puan", question="", envelopes=[env({"lag": -8.5})])
    assert rep.n_sign_relaxed == 1 and rep.n_supported == 1


def test_no_claims_gives_zero_rates():
    rep = verify_numbers("Sayı yok.", question="", envelopes=[env({"x": 1})])
    assert (rep.n_claims, rep.numerical_hallucination_rate, rep.unevidenced_rate) == (0, 0.0, 0.0)


def test_report_is_serialisable_and_deterministic():
    kw = dict(question="", envelopes=[env(RES)], committed_evidence=COMMITTED)
    a = verify_numbers("isabet %66,7 ve 55,5", **kw).to_dict()
    b = verify_numbers("isabet %66,7 ve 55,5", **kw).to_dict()
    assert a == b
    import json
    assert json.loads(json.dumps(a, ensure_ascii=False))["n_hallucinated"] == 1


# =============================== türetilmiş sayılar ===============================
BACKTEST = {"n_signals": 22, "n_winning_trades": 14, "n_losing_trades": 8}


def test_model_derived_percentage_is_hallucination_with_hint():
    """14/22 -> %64: araç çıktısında '64' yok => HALÜSİNASYON; ipucu nedenini gösterir ama aklamaz."""
    rep = verify_numbers("22 işlemin 14'ü kazandı (%64).", question="", envelopes=[env(BACKTEST)])
    by = {r.claim.raw: r for r in rep.claims}
    assert by["22"].verdict == "SUPPORTED" and by["14"].verdict == "SUPPORTED"
    assert by["%64"].verdict == "HALLUCINATION"
    assert "14/22" in by["%64"].derivation_hint and "63.6" in by["%64"].derivation_hint
    assert rep.n_hallucinated == 1 and rep.n_hallucinated_derivable == 1
    assert rep.numerical_hallucination_rate == pytest.approx(1 / 3)


def test_derived_ratio_and_differences():
    rep = verify_numbers("14 kazanç, 8 kayıp: fark 6 ve toplam 22", question="", envelopes=[env({"w": 14, "l": 8})])
    by = {r.claim.raw: r for r in rep.claims}
    assert by["6"].verdict == "HALLUCINATION" and "14-8" in by["6"].derivation_hint
    assert by["22"].verdict == "HALLUCINATION" and "14+8" in by["22"].derivation_hint


def test_percent_change_derivation():
    rep = verify_numbers("305,0 TL'den 299,25 TL'ye: %1,89 düşüş", question="",
                         envelopes=[env({"a": 305.0, "b": 299.25})])
    r = rep.claims[-1]
    assert r.verdict == "HALLUCINATION" and "299.25" in r.derivation_hint and "305" in r.derivation_hint


def test_no_hint_when_operands_are_not_in_the_text():
    rep = verify_numbers("başarı oranı %64", question="", envelopes=[env(BACKTEST)])
    r = only(rep)
    assert r.verdict == "HALLUCINATION" and r.derivation_hint is None
    assert rep.n_hallucinated_derivable == 0


def test_hint_is_deterministic():
    kw = dict(question="", envelopes=[env(BACKTEST)])
    a = verify_numbers("22 işlemin 14'ü kazandı (%64).", **kw)
    b = verify_numbers("22 işlemin 14'ü kazandı (%64).", **kw)
    assert [r.derivation_hint for r in a.claims] == [r.derivation_hint for r in b.claims]


# =============================== GERÇEK THYAO 10.09.2026 zarfları ===============================
GOOD = ("THYAO 10.09.2026 tarihinde 299,25 TL'den kapandı; 08.09.2026'daki kapanış 305,00 TL idi. "
        "RSI_14 44,83 seviyesinde. Fiyat alt Bollinger bandının (BB_LOWER_20_2.0 = 292,09) üzerinde, "
        "Supertrend düşüş yönünde (313,33). Günlük hacim 38,4 milyon lot.")


def test_real_good_answer_has_no_hallucination(thyao_history, thyao_indicators):
    rep = verify_numbers(GOOD, question=QUESTION, envelopes=[thyao_history, thyao_indicators])
    assert rep.n_hallucinated == 0, [(r.claim.raw, r.verdict) for r in rep.claims if r.verdict == "HALLUCINATION"]
    assert rep.numerical_hallucination_rate == 0.0
    by = {r.claim.raw: r for r in rep.claims}
    assert by["299,25"].match_kind == "EXACT"
    assert by["305,00"].match_kind == "EXACT"
    assert by["44,83"].match_kind == "ROUNDED"
    assert by["292,09"].match_kind == "ROUNDED"
    assert by["313,33"].match_kind == "ROUNDED"
    assert by["38,4 milyon"].match_kind == "ROUNDED"
    assert by["08.09.2026"].verdict == "ALLOWLISTED"   # get_stock_history çağrısının start parametresi
    assert by["10.09.2026"].verdict == "ALLOWLISTED"   # soru + as_of


def test_real_history_date_not_in_params_is_supported_from_results(thyao_history):
    rep = verify_numbers("09.09.2026 kapanışı 301,0 TL", question=QUESTION, envelopes=[thyao_history])
    by = {r.claim.raw: r for r in rep.claims}
    assert by["09.09.2026"].verdict == "SUPPORTED" and by["09.09.2026"].match_kind == "DATE"
    assert by["09.09.2026"].sources[0].path == "rows[1].date"
    assert by["301,0"].match_kind == "EXACT"


def test_real_fabricated_answer(thyao_history, thyao_indicators):
    bad = "THYAO 299,25 TL'den kapandı. RSI_14 31,2 ile aşırı satımda; kapanış 310,50, hacim 61 milyon lot."
    rep = verify_numbers(bad, question=QUESTION, envelopes=[thyao_history, thyao_indicators])
    by = {r.claim.raw: r.verdict for r in rep.claims}
    assert by == {"299,25": "SUPPORTED", "31,2": "HALLUCINATION", "310,50": "HALLUCINATION",
                  "61 milyon": "HALLUCINATION"}
    assert rep.numerical_hallucination_rate == pytest.approx(0.75)


def test_real_derived_change_is_hallucination(thyao_history):
    """08.09 kapanış 305,0 ve 10.09 kapanış 299,25 araçta var; aralarındaki %1,89 yoktur: model hesapladı."""
    text = "Kapanış 305,0 TL'den 299,25 TL'ye geriledi, yani %1,89 düştü."
    rep = verify_numbers(text, question=QUESTION, envelopes=[thyao_history])
    r = rep.claims[-1]
    assert r.claim.raw == "%1,89" and r.verdict == "HALLUCINATION"
    assert r.derivation_hint is not None


def test_real_indicator_latest_is_committed_but_recent_rows_are_not(thyao_history, thyao_indicators):
    """Gerçek kanıt paketi: göstergelerin `latest` bölümü committed (evidence_headlines.json); recent_rows kanıta hiç girmez.

    => as_of günü RSI SUPPORTED; önceki günün RSI'ı (recent_rows) araç çıktısında var ama committed'da yok => KANITSIZ."""
    from harness.evidence import EnvelopeStore, EvidenceBundle, make_analysis_id
    from datetime import date as _d

    store = EnvelopeStore()
    for e in (thyao_history, thyao_indicators):
        store.add(e, actor="model")
    aid = make_analysis_id(_d(2026, 9, 10), QUESTION)
    bundle = EvidenceBundle(aid, store)
    bundle.build({"as_of": "2026-09-10", "analysis_id": aid,
                  "source_input_hashes": [thyao_history["input_hash"], thyao_indicators["input_hash"]]})
    bundle.lock("PASS")
    committed = bundle.snapshot()["committed_evidence_set"]
    rep = verify_numbers("RSI_14 44,83, kapanış 299,25; bir önceki işlem günü RSI 40,64", question=QUESTION,
                         envelopes=[thyao_history, thyao_indicators], committed_evidence=committed)
    by = {r.claim.raw: r.verdict for r in rep.claims}
    assert by == {"44,83": "SUPPORTED", "299,25": "SUPPORTED", "40,64": "UNEVIDENCED"}
    assert rep.n_hallucinated == 0 and rep.unevidenced_rate == pytest.approx(1 / 3)


# =============================== ek: hash maskesi, oturum yardımcısı ===============================
def test_hashes_are_masked_but_long_plain_numbers_are_not():
    assert extract_claims("hash 6a63104b8101940ecedad90e6c44c0921e3707b5682fdf8879a98c04da53a24c") == []
    assert values(one("hacim 1234567890123456 lot")) == [D("1234567890123456")]


def test_verify_session_uses_session_envelopes_and_question(thyao_history):
    from harness.number_verifier import verify_session
    from harness.session import HarnessSession
    from schemas.enums import ToolName

    s = HarnessSession.from_question(QUESTION + " 08.09.2026'dan beri.", profile="B",
                                     runner=lambda tool, params: thyao_history)
    res = s.call_tool(ToolName.GET_STOCK_HISTORY.value,
                      {"ticker": "THYAO", "start": "2026-09-08", "end": "2026-09-10", "as_of": "2026-09-10"})
    assert res.ok, res.error
    rep = verify_session(s, "THYAO 299,25 TL'den kapandı, 08.09.2026'dan beri %7 değişti.")
    by = {r.claim.raw: r.verdict for r in rep.claims}
    assert by == {"299,25": "SUPPORTED", "08.09.2026": "ALLOWLISTED", "%7": "HALLUCINATION"}
    assert rep.tier2_enabled is False   # profil B: kanıt paketi yok
