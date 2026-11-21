"""HarnessSession.submit_final: nihai metin denetimi, sınırlı yeniden deneme, güvenli geri çekilme, ihlal sayımı.

İhlaller İKİ düzeyde ayrı raporlanır:
  deneme düzeyi  her denemedeki ihlaller (modelin kural ihlali eğilimi; yeniden denemeyle düzelse de sayılır)
  teslim düzeyi  son teslim edilen metindeki ihlaller (D/E'de zorlama sonrası 0; A–C'de ölçüm: modelin ham çıktısı)
Hiçbir test hash'e bağlı donmuş dosya okumaz; etiket ve metinler her seferinde yeniden üretilir.
"""
from __future__ import annotations

import pytest

from harness import settings
from harness.final_check import fallback_text
from harness.label_policy import decide_session
from harness.mock_tools import run_mock_tool
from harness.routing import State as S
from harness.session import FinalResult, HarnessSession
from harness.state_machine import HarnessRuleViolation
from schemas.enums import AllowedAction as A, ToolName as T
from schemas.examples import example_params

QUESTION = ("Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) son 20 işlem gününde "
            "sektör medyanının en çok gerisinde kalan hisse hangisi?")
GOOD = ("Perakende grubunda sektör medyan getirisi %12,0, XU100 getirisi %4,0; fark 8,0 pp. BIMAS geride kalan eşiğinde değil.\n"
        "EYLEM: {label}")
FABRICATED = "Sektör medyan getirisi %12,0, fark %300,0 oldu. BIMAS geride değil.\nEYLEM: HOLD"
ADVICE = "BIMAS'ı alın, hedef fiyat 350 TL.\nEYLEM: HOLD"
WRONG_LABEL = GOOD.format(label="POTENTIAL_CATCH_UP_CANDIDATE")


def started(stage="D", question=QUESTION, runner=None) -> HarnessSession:
    s = HarnessSession.from_question(question, profile=stage, runner=runner)
    tools = [T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST]
    if stage == "C":                       # C: kalite kontrolü ZORUNLU ama harness değil MODEL çağırır
        tools.insert(0, T.CHECK_DATA_QUALITY)
    for t in tools:
        assert s.call_tool(t.value, example_params(t)).ok
    assert s.request_explanation().allowed
    return s


def kinds(s, kind):
    return [e for e in s.events if e["kind"] == kind]


# =============================== politika bloğu: D/E'de gösterilir ===============================
def test_d_and_e_show_the_policy_block_but_d_prime_and_a_to_c_do_not():
    for stage, shown in (("D", True), ("E", True), ("D'", False), ("C", False), ("B", False)):
        s = started(stage)
        expected = A.INVESTIGATE if stage == "B" else A.HOLD                       # B'de kapı çağrısı yok => G2 (güvenli varsayılan)
        assert s.policy is not None and s.policy.label == expected                # politika HER profilde hesaplanır (ölçüm)
        assert bool(s.policy_text) is shown and (s.explanation_context() is not None) is shown, stage
        if shown:
            assert f"EYLEM: {expected.value}" in s.policy_text and s.policy.rule_id in s.policy_text


def test_explanation_context_is_stable_across_repeated_requests():
    s = started("D")
    text = s.policy_text
    assert s.request_explanation().allowed and s.policy_text == text


# =============================== D: zorlama ===============================
def test_clean_answer_is_accepted_on_the_first_attempt():
    s = started("D")
    r = s.submit_final(GOOD.format(label="HOLD"))
    assert isinstance(r, FinalResult) and r.status == "ACCEPTED" and r.attempt == 1 and r.max_attempts == 3
    assert r.action == A.HOLD and r.feedback is None and r.report.ok
    assert s.machine.state == S.HUMAN_REVIEW and s.machine.action == A.HOLD and s.machine.explanation == r.text
    m = s.final_metrics()
    assert m["attempt_level"]["n_violations"] == 0 and m["delivered_level"]["n_violations"] == 0
    assert m["delivered_level"]["fallback"] is False and m["delivered_level"]["policy_match"] is True
    assert [e["kind"] for e in s.events if e["kind"].startswith("FINAL_")] == ["FINAL_CHECK", "FINAL_DELIVERED"]


def test_failed_attempt_returns_feedback_stays_in_generate_explanation_and_counts_the_violation():
    s = started("D")
    r1 = s.submit_final(FABRICATED)
    assert r1.status == "RETRY" and r1.attempt == 1 and "%300,0" in r1.feedback and "EYLEM: HOLD" in r1.feedback
    assert r1.text is None and s.machine.state == S.GENERATE_EXPLANATION and s.machine.action is None
    r2 = s.submit_final(GOOD.format(label="HOLD"))
    assert r2.status == "ACCEPTED" and r2.attempt == 2
    m = s.final_metrics()
    assert m["n_attempts"] == 2
    assert m["attempt_level"]["by_code"] == {"NUMBER_HALLUCINATION": 1} and m["attempt_level"]["n_attempts_with_violation"] == 1
    assert m["delivered_level"]["n_violations"] == 0 and m["delivered_level"]["fallback"] is False
    ev = kinds(s, "RULE_VIOLATION")
    assert [(e["level"], e["attempt"], e["code"]) for e in ev] == [("attempt", 1, "NUMBER_HALLUCINATION")]


@pytest.mark.parametrize("bad,code", [(ADVICE, "ADVICE_LANGUAGE"), (WRONG_LABEL, "ACTION_MISMATCH_REQUIRED"),
                                      ("Açıklama, etiket yok.", "NO_ACTION")])
def test_each_kind_of_bad_answer_is_retried_and_recovers(bad, code):
    s = started("D")
    r = s.submit_final(bad)
    assert r.status == "RETRY" and code in r.report.codes
    assert s.submit_final(GOOD.format(label="HOLD")).status == "ACCEPTED"
    assert code in s.final_metrics()["attempt_level"]["by_code"]


def test_retries_are_bounded_then_the_safe_fallback_is_delivered():
    s = started("D")
    statuses = [s.submit_final(t).status for t in (FABRICATED, ADVICE, WRONG_LABEL)]
    assert statuses == ["RETRY", "RETRY", "FALLBACK"]                  # varsayılan: 2 yeniden deneme = 3 deneme
    assert s.machine.state == S.HUMAN_REVIEW and s.machine.action == A.HOLD         # D/E'de politika etiketi
    assert s.machine.explanation == fallback_text(A.HOLD)
    m = s.final_metrics()
    assert m["n_attempts"] == 3 and m["attempt_level"]["n_attempts_with_violation"] == 3
    assert m["attempt_level"]["by_code"]["NUMBER_HALLUCINATION"] >= 1 and m["attempt_level"]["by_code"]["ADVICE_LANGUAGE"] >= 1
    assert m["attempt_level"]["by_code"]["ACTION_MISMATCH_REQUIRED"] >= 1
    d = m["delivered_level"]                                          # teslim edilen = geri çekilme metni: temiz
    assert d["fallback"] is True and d["n_violations"] == 0 and d["action"] == "HOLD" and d["action_source"] == "fallback"
    assert len(kinds(s, "FINAL_FALLBACK")) == 1 and kinds(s, "FINAL_DELIVERED")[0]["metrics"]["delivered_level"]["fallback"] is True
    with pytest.raises(HarnessRuleViolation):                         # teslimden sonra yeni metin kabul edilmez
        s.submit_final(GOOD.format(label="HOLD"))


def test_retry_budget_comes_from_settings_and_environment(monkeypatch):
    assert settings.final_max_retries() == 2
    monkeypatch.setenv(settings.FINAL_RETRIES_ENV, "0")
    s = started("D")
    r = s.submit_final(FABRICATED)
    assert r.status == "FALLBACK" and r.attempt == 1 and r.max_attempts == 1
    monkeypatch.setenv(settings.FINAL_RETRIES_ENV, "1")
    s = started("D")
    assert [s.submit_final(FABRICATED).status, s.submit_final(FABRICATED).status] == ["RETRY", "FALLBACK"]
    monkeypatch.setenv(settings.FINAL_RETRIES_ENV, "-1")
    with pytest.raises(ValueError):
        settings.final_max_retries()
    monkeypatch.setenv(settings.FINAL_RETRIES_ENV, "çok")
    with pytest.raises(ValueError):
        settings.final_max_retries()


def test_d_prime_enforces_but_does_not_show_the_label():
    s = started("D'")
    assert s.policy_text == "" and s.submit_final(WRONG_LABEL).status == "RETRY"       # yine de zorlanır
    assert s.submit_final(GOOD.format(label="HOLD")).status == "ACCEPTED"


# =============================== güvenli hata yolu (kapı HARD_BLOCK) ===============================
def blocking_runner(tool, params):
    env = run_mock_tool(tool, params)
    if tool == T.CHECK_DATA_QUALITY:
        env["results"]["gate_status"] = "HARD_BLOCK"
        env["results"]["hard_blocks"] = [{"code": "AS_OF_VIOLATION", "severity": "HARD", "message": "sızıntı"}]
        env["results"]["soft_warnings"] = []
    return env


def test_safe_failure_requires_analysis_unsafe_and_the_fallback_uses_it():
    s = HarnessSession.from_question(QUESTION, profile="D", runner=blocking_runner)
    r = s.call_tool("rank_sector_relative_strength", example_params(T.RANK_SECTOR_RELATIVE_STRENGTH))
    assert r.error["type"] == "SAFE_FAILURE"
    assert s.request_explanation().allowed and s.policy.label == A.ANALYSIS_UNSAFE and "EYLEM: ANALYSIS_UNSAFE" in s.policy_text
    bad = s.submit_final("Veri güvenli değil gibi.\nEYLEM: WATCH")
    assert bad.status == "RETRY" and "ACTION_MISMATCH_REQUIRED" in bad.report.codes and "EYLEM: ANALYSIS_UNSAFE" in bad.feedback
    ok = s.submit_final("Veri kalitesi kapısı engelledi; analiz güvenli değil.\nEYLEM: ANALYSIS_UNSAFE")
    assert ok.status == "ACCEPTED" and s.machine.action == A.ANALYSIS_UNSAFE


def test_safe_failure_fallback_is_analysis_unsafe():
    s = HarnessSession.from_question(QUESTION, profile="D", runner=blocking_runner)
    s.call_tool("rank_sector_relative_strength", example_params(T.RANK_SECTOR_RELATIVE_STRENGTH))
    s.request_explanation()
    for _ in range(3):
        r = s.submit_final("Hep yanlış.\nEYLEM: WATCH")
    assert r.status == "FALLBACK" and s.machine.action == A.ANALYSIS_UNSAFE


# =============================== A–C: yalnızca ÖLÇÜM ===============================
@pytest.mark.parametrize("stage", ["A", "B", "C"])
def test_measure_only_profiles_deliver_the_raw_text_and_count_its_violations(stage):
    s = started(stage) if stage != "A" else _a_session()
    text = "BIMAS'ı alın, hedef fiyat 350 TL.\nEYLEM: POTENTIAL_CATCH_UP_CANDIDATE"
    r = s.submit_final(text)
    assert r.status == "RECORDED" and r.text == text and r.feedback is None and r.attempt == 1
    assert s.machine.state == S.HUMAN_REVIEW and s.machine.explanation == text
    m = s.final_metrics()
    assert m["enforced"] is False and m["n_attempts"] == 1
    assert m["attempt_level"] == {**m["attempt_level"], "n_violations": m["delivered_level"]["n_violations"]}
    assert m["delivered_level"]["n_violations"] >= 2 and m["delivered_level"]["fallback"] is False
    assert "ADVICE_LANGUAGE" in m["delivered_level"]["by_code"] and "ACTION_MISMATCH_REQUIRED" not in m["delivered_level"]["by_code"]
    assert m["delivered_level"]["policy_match"] is False                    # politika uyumu ÖLÇÜLÜR, zorlanmaz
    assert kinds(s, "FINAL_FALLBACK") == []


def _a_session() -> HarnessSession:
    s = HarnessSession.from_question(QUESTION, profile="A")
    assert s.request_explanation().allowed
    return s


def test_measure_only_without_an_action_line_defaults_the_machine_to_investigate_and_says_so():
    s = started("B")
    r = s.submit_final("Etiketsiz açıklama, %12,0 getiri.")
    assert r.status == "RECORDED" and r.action == A.INVESTIGATE and s.machine.action == A.INVESTIGATE
    d = s.final_metrics()["delivered_level"]
    assert d["action_source"] == "defaulted" and d["by_code"] == {"NO_ACTION": 1}
    assert kinds(s, "ACTION_DEFAULTED") and kinds(s, "ACTION_DEFAULTED")[0]["action"] == "INVESTIGATE"


# =============================== sıra ve determinizm ===============================
def test_submit_final_before_the_explanation_stage_is_a_rule_violation():
    s = HarnessSession.from_question(QUESTION, profile="D")
    with pytest.raises(HarnessRuleViolation) as e:
        s.submit_final(GOOD.format(label="HOLD"))
    assert e.value.code == "EXPLANATION_NOT_ALLOWED" and s.final_metrics()["n_attempts"] == 0


def test_same_script_gives_identical_metrics_and_delivered_text():
    def run():
        s = started("D")
        for t in (FABRICATED, ADVICE, WRONG_LABEL):
            s.submit_final(t)
        return s.final_metrics(), s.machine.explanation, [e["code"] for e in kinds(s, "RULE_VIOLATION")]
    assert run() == run()


def test_event_log_replays_without_reading_hashes_from_a_file(tmp_path):
    """Kayıt (JSONL) tekrar OKUNUP aynı sayımlar yeniden üretilir: beklenen değerler dosyadan DEĞİL, aynı betikten türetilir."""
    import json

    from harness.event_log import EventLog

    path = tmp_path / "events.jsonl"
    s = HarnessSession.from_question(QUESTION, profile="D", log=EventLog(path))
    for t in (T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST):
        s.call_tool(t.value, example_params(t))
    s.request_explanation()
    s.submit_final(FABRICATED)
    s.submit_final(GOOD.format(label="HOLD"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [r["code"] for r in rows if r["kind"] == "RULE_VIOLATION"] == ["NUMBER_HALLUCINATION"]
    delivered = [r for r in rows if r["kind"] == "FINAL_DELIVERED"][0]
    assert delivered["metrics"] == s.final_metrics()          # JSON gidiş-dönüşünde değişmez (yalnızca str anahtar, int, bool, list)


# =============================== orkestratör: döngü durunca güvenli geri çekilme ===============================
def test_deliver_fallback_is_for_enforcing_profiles_in_the_explanation_stage_only():
    s = started("D")
    r = s.deliver_fallback("TURN_LIMIT")
    assert r.status == "FALLBACK" and s.machine.action == A.HOLD and s.machine.explanation == fallback_text(A.HOLD)
    m = s.final_metrics()
    assert m["n_attempts"] == 0 and m["delivered_level"]["fallback"] is True and m["delivered_level"]["n_violations"] == 0
    assert [e["reason"] for e in kinds(s, "FINAL_FALLBACK")] == ["TURN_LIMIT"]
    with pytest.raises(HarnessRuleViolation):
        started("B").deliver_fallback("TURN_LIMIT")                      # A–C: zorlama yok, geri çekilme yok
    with pytest.raises(HarnessRuleViolation):
        HarnessSession.from_question(QUESTION, profile="D").deliver_fallback("x")     # açıklama aşamasında değil


def test_peek_explanation_does_not_count_an_invalid_call():
    s = HarnessSession.from_question(QUESTION, profile="D")
    before = s.machine.n_invalid_calls
    d = s.machine.peek_explanation()
    assert not d.allowed and s.machine.n_invalid_calls == before and not [e for e in s.events if e["kind"] == "INVALID_TOOL_CALL"]
    assert not s.request_explanation().allowed and s.machine.n_invalid_calls == before + 1     # gerçek istek sayılır
    s2 = HarnessSession.from_question(QUESTION, profile="D")
    for t in (T.RANK_SECTOR_RELATIVE_STRENGTH, T.RUN_BACKTEST):
        s2.call_tool(t.value, example_params(t))
    assert s2.machine.peek_explanation().allowed and s2.machine.state != S.GENERATE_EXPLANATION   # yalnızca bakar
