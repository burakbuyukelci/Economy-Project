"""Nihai çıktı denetimi (harness/final_check.py): sayı doğrulama + eylem koruması + politika etiketi tek raporda.

Oturumlar mock araçlarla kurulur; sayılar mock zarflardaki sabit değerlerdir (HOLD / C2_NOT_LAGGARD: BIMAS geride değil).
Hiçbir test hash'e bağlı donmuş değer okumaz; politika etiketi her seferinde `decide_session` ile yeniden üretilir.
"""
from __future__ import annotations

import json

import pytest

from harness.action_guard import check_final_output
from harness.final_check import (FinalReport, build_feedback, check_final, fallback_text, render_policy_block)
from harness.label_policy import decide_session
from harness.session import HarnessSession
from schemas.enums import AllowedAction as A, ToolName as T
from schemas.examples import example_params

QUESTION = ("Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) son 20 işlem gününde "
            "sektör medyanının en çok gerisinde kalan hisse hangisi?")
GOOD = ("Perakende grubunda sektör medyan getirisi %12,0, XU100 getirisi %4,0; fark 8,0 pp. BIMAS geride kalan eşiğinde değil.\n"
        "EYLEM: {label}")


def explanation_session(stage="D", question=QUESTION) -> HarnessSession:
    """Mock rank + backtest çağrılmış ve açıklama aşamasına geçilmiş oturum (D/E'de kanıt kilitli)."""
    s = HarnessSession.from_question(question, profile=stage)
    for t in (T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST):
        assert s.call_tool(t.value, example_params(t)).ok
    assert s.request_explanation().allowed
    return s


def shown(s: HarnessSession) -> HarnessSession:
    """D/E'de model politika bloğunu görür: blok metni oturumda tutulur (1d'de otomatik kurulur)."""
    s.policy_text = render_policy_block(decide_session(s))
    return s


def codes(rep: FinalReport) -> list[str]:
    return [v.code for v in rep.violations]


# =============================== politika bloğu ===============================
def test_policy_block_carries_label_rule_gate_and_reason_codes():
    s = explanation_session()
    d = decide_session(s)
    block = render_policy_block(d)
    assert d.label == A.HOLD and d.rule_id == "C2_NOT_LAGGARD"
    assert f"EYLEM: {d.label.value}" in block and d.rule_id in block and "PASS_WITH_WARNINGS" in block
    for r in d.reasons:
        assert r.code in block and r.message in block
    assert render_policy_block(d) == block                       # deterministik


def test_policy_block_is_free_of_tool_numbers_beyond_the_reason_messages():
    """Blokta yalnızca politika gerekçelerinin metni var: araç değerleri (isabet oranı vb.) modele bu yoldan sızmaz."""
    s = explanation_session()
    block = render_policy_block(decide_session(s))
    assert "12" not in block and "hit_rate" not in block


# =============================== temiz cevap ===============================
def test_clean_answer_passes_in_d_with_the_policy_label():
    s = shown(explanation_session())
    rep = check_final(s, GOOD.format(label=decide_session(s).label.value))
    assert rep.ok and rep.enforced and rep.required_action == A.HOLD and rep.policy_match is True
    assert rep.action == A.HOLD and rep.numbers.n_hallucinated == 0 and rep.numbers.n_supported == 3


def test_report_is_serialisable_and_deterministic():
    s = shown(explanation_session())
    text = GOOD.format(label="HOLD")
    a, b = check_final(s, text).to_dict(), check_final(s, text).to_dict()
    assert a == b and json.dumps(a, ensure_ascii=False, sort_keys=True)
    assert set(a) >= {"ok", "enforced", "required_action", "policy_label", "policy_rule_id", "policy_match", "action", "violations",
                      "notes", "n_number_claims", "n_hallucinated", "n_allowlisted_policy"}


# =============================== ihlaller ===============================
def test_fabricated_number_is_a_violation_with_derivation_hint():
    s = shown(explanation_session())
    text = ("Sektör medyan getirisi %12,0, XU100 %4,0, fark 8,0 pp; bu da yaklaşık %300,0 oranında bir farktır. BIMAS geride değil.\n"
            "EYLEM: HOLD")
    rep = check_final(s, text)
    assert codes(rep) == ["NUMBER_HALLUCINATION"] and not rep.ok
    v = rep.violations[0]
    assert v.source == "numbers" and v.detail["raw"] == "%300,0" and "300" in v.message
    assert rep.numbers.n_hallucinated == 1


def test_advice_language_is_a_violation_even_with_the_right_label():
    s = shown(explanation_session())
    rep = check_final(s, "BIMAS'ı alın, hedef fiyat 350 TL.\nEYLEM: HOLD")
    assert "ADVICE_LANGUAGE" in codes(rep) and "NUMBER_HALLUCINATION" in codes(rep)     # 350 de uydurma sayı
    assert {v.source for v in rep.violations} == {"advice", "numbers"}


def test_wrong_label_is_a_violation_in_d_but_only_measured_in_b():
    text = GOOD.format(label="POTENTIAL_CATCH_UP_CANDIDATE")
    rep_d = check_final(shown(explanation_session("D")), text)
    assert codes(rep_d) == ["ACTION_MISMATCH_REQUIRED"] and rep_d.policy_match is False and rep_d.required_action == A.HOLD
    rep_b = check_final(explanation_session("B"), text)
    assert rep_b.enforced is False and rep_b.required_action is None and rep_b.ok       # B: zorlama yok
    assert rep_b.policy_match is False and rep_b.policy_label is not None                # ama ÖLÇÜLÜR


@pytest.mark.parametrize("text,code", [
    ("Açıklama var ama etiket satırı yok.", "NO_ACTION"),
    ("Metin.\nEYLEM: HOLD\nEYLEM: WATCH", "MULTIPLE_ACTIONS"),
    ("Metin.\nEYLEM: AL", "ACTION_NOT_IN_ENUM"),
])
def test_action_line_problems_are_reported_with_the_guard_codes(text, code):
    rep = check_final(shown(explanation_session()), text)
    assert code in codes(rep) and all(v.source in ("action", "numbers") for v in rep.violations)
    assert rep.policy_match is None                              # etiket çözümlenemedi: uyum belirsiz


def test_unevidenced_number_is_a_note_not_a_violation():
    """Araç çıktısında var ama kilitli kanıt kümesinde yok => yumuşak uyarı (bölüm 9.1)."""
    s = shown(explanation_session())
    text = GOOD.format(label="HOLD") + "\nBIMAS getirisi XU100'e göre 11,0 pp öndeydi."   # 11,0: sıralama satırında var, committed'ta yok
    rep = check_final(s, text)
    assert rep.numbers.by_raw("11,0 pp").verdict == "UNEVIDENCED"
    assert rep.ok and rep.numbers.n_unevidenced == 1
    assert [n["raw"] for n in rep.notes if n["code"] == "NUMBER_UNEVIDENCED"] == ["11,0 pp"]


def test_quoted_refutation_note_is_carried_over():
    s = shown(explanation_session())
    text = "“kesin yükselir” iddiası doğrulanmamıştır; veri bunu desteklemiyor.\nEYLEM: HOLD"
    rep = check_final(s, text)
    assert rep.ok and any(n["code"] == "QUOTED_REFUTATION" for n in rep.notes)


# =============================== ALLOWLISTED_POLICY (D/E gösterir, D′ göstermez) ===============================
def test_policy_threshold_numbers_in_the_shown_block_are_allowlisted_policy():
    s = shown(explanation_session("D"))
    s.policy_text += "\n- FEW_EVENTS: tamamlanmış olay sayısı MIN_EVENTS (23) altında"       # gösterilen bloğa eşik sayısı girdi
    rep = check_final(s, "Tamamlanmış olay 23 eşiğinin altında.\nEYLEM: HOLD")
    assert rep.ok and rep.numbers.n_allowlisted_policy == 1 and rep.to_dict()["n_allowlisted_policy"] == 1
    assert rep.numbers.n_hallucinated == 0


def test_d_prime_does_not_show_the_block_so_the_same_number_is_a_hallucination():
    s = explanation_session("D'")
    rep = check_final(s, "Tamamlanmış olay 23 eşiğinin altında.\nEYLEM: HOLD")     # D′: blok yok (session testinde ayrıca denetlenir)
    assert codes(rep) == ["NUMBER_HALLUCINATION"] and rep.enforced and rep.required_action == A.HOLD


# =============================== geri besleme ===============================
def test_feedback_lists_every_problem_and_the_required_label():
    s = shown(explanation_session())
    text = "BIMAS'ı alın, hedef fiyat 350 TL.\nEYLEM: POTENTIAL_CATCH_UP_CANDIDATE"
    rep = check_final(s, text)
    fb = build_feedback(rep, attempt=1, max_attempts=3)
    assert "deneme 1/3" in fb and "350" in fb and "alın" in fb.lower()
    assert "EYLEM: HOLD" in fb                                   # D/E'de izinli etiket zaten modele verilmiş
    assert build_feedback(rep, attempt=1, max_attempts=3) == fb  # deterministik


def test_feedback_shows_the_derivation_hint_when_there_is_one():
    s = shown(explanation_session())
    rep = check_final(s, "Medyan %12,0, XU100 %4,0; fark 8,0 pp, yani XU100'ün %200,0 üstü.\nEYLEM: HOLD")
    fb = build_feedback(rep, attempt=1, max_attempts=3)
    hallu = [v for v in rep.violations if v.code == "NUMBER_HALLUCINATION"]
    assert [v.detail["raw"] for v in hallu] == ["%200,0"]
    assert hallu[0].detail["derivation_hint"] and hallu[0].detail["derivation_hint"] in fb


# =============================== güvenli geri çekilme metni ===============================
@pytest.mark.parametrize("action", list(A))
def test_fallback_text_always_passes_the_guard_for_every_label(action):
    text = fallback_text(action)
    rep = check_final_output(text, required_action=action)
    assert rep.ok, [(v.code, v.phrase) for v in rep.violations]
    assert rep.action == action
    from harness.number_verifier import extract_claims
    assert extract_claims(text) == []                            # geri çekilme metninde sayı yok


def test_fallback_text_for_candidate_labels_carries_the_caveat():
    assert "örnek küçük" in fallback_text(A.POTENTIAL_CATCH_UP_CANDIDATE)
    assert "örnek küçük" not in fallback_text(A.HOLD)
