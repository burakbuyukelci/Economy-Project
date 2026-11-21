"""Orkestratör (harness/agent_loop.py): model <-> HarnessSession döngüsü, betikli sahte modelle (mock araçlar).

Protokol: model araç çağırır; araç çağrısız metin verince "hazırım" sayılır. D/E'de (politika bloğu gösterilen profiller) harness açıklama aşamasına
geçer, bloğu ve nihai biçimi verip modelden nihai metni ister; A–C ve D′'de araç çağrısız ilk metin doğrudan nihai metindir.
"""
from __future__ import annotations

import json

import pytest

from harness.agent_loop import RunResult, build_system_prompt, run_session, tool_specs
from harness.llm_backend import LLMError, ModelReply, ScriptedBackend, ToolCall
from harness.mock_tools import run_mock_tool
from harness.routing import State as S
from harness.session import HarnessSession
from schemas.enums import AllowedAction as A, ToolName as T
from schemas.examples import example_params

QUESTION = ("Analiz tarihi: 10.09.2026\nPerakende sektöründe (BIMAS, MGROS, MAVI) son 20 işlem gününde "
            "sektör medyanının en çok gerisinde kalan hisse hangisi?")
GOOD = ("Perakende grubunda sektör medyan getirisi %12,0, XU100 getirisi %4,0; fark 8,0 pp. Geride kalan hisse için tamamlanmış olay sayısı yetersiz.\n"
        "EYLEM: INVESTIGATE")
FABRICATED = "Sektör medyan getirisi %12,0, fark %300,0 oldu.\nEYLEM: INVESTIGATE"


def call(tool: T, **over) -> ModelReply:
    return ModelReply(tool_calls=(ToolCall(tool.value, {**example_params(tool), **over}),))


RANK, BACKTEST = call(T.RANK_SECTOR_RELATIVE_STRENGTH), call(T.RUN_BACKTEST)


def run(steps, stage="D", **kw) -> tuple[RunResult, ScriptedBackend]:
    backend = ScriptedBackend(steps)
    return run_session(QUESTION, backend, profile=stage, **kw), backend


def roles(res: RunResult) -> list[str]:
    return [m["role"] for m in res.messages]


# =============================== D/E: iki aşamalı protokol ===============================
def test_d_happy_path_gate_tools_are_hidden_and_the_policy_block_arrives_before_the_final_text():
    res, backend = run([RANK, BACKTEST, "HAZIR", GOOD])
    assert res.status == "DELIVERED" and res.final.status == "ACCEPTED" and res.n_model_turns == 4
    assert res.session.machine.state == S.LOG_AND_CLOSE and res.session.machine.action == A.INVESTIGATE
    first_tools = {t["name"] for t in backend.calls[0]["tools"]}
    assert len(first_tools) == 13 and "check_data_quality" not in first_tools and "build_evidence_bundle" not in first_tools
    assert backend.calls[3]["tools"] is None                                    # nihai aşamada araç yok
    last_user = backend.calls[3]["messages"][-1]
    assert last_user["role"] == "user" and "EYLEM: INVESTIGATE" in last_user["content"] and "POLİTİKA KARARI" in last_user["content"]
    assert not any("POLİTİKA KARARI" in m["content"] for m in backend.calls[2]["messages"])    # blok daha önce gösterilmedi
    assert backend.calls[0]["messages"][0]["role"] == "system" and backend.calls[0]["messages"][1] == {"role": "user", "content": QUESTION}


def test_tool_results_reach_the_model_as_tool_messages_with_the_validated_envelope():
    res, backend = run([RANK, BACKTEST, "HAZIR", GOOD])
    tool_msgs = [m for m in backend.calls[1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 1 and tool_msgs[0]["name"] == "rank_sector_relative_strength"
    env = json.loads(tool_msgs[0]["content"])
    assert env["status"] == "OK" and "tool" not in env and "params" not in env and "results" in env      # model görünümü: yankı alanları yok
    from harness.model_view import model_view
    assert env == model_view(res.session.tool_envelopes[0], subject=None)       # modele giden = oturumun doğrulanmış zarfının GÖRÜNÜMÜ (null atılmış)


def test_failed_final_attempt_feedback_goes_back_to_the_model_and_it_can_recover():
    res, backend = run([RANK, BACKTEST, "HAZIR", FABRICATED, GOOD])
    assert res.final.status == "ACCEPTED" and res.final.attempt == 2 and res.n_model_turns == 5
    fb = backend.calls[4]["messages"][-1]
    assert fb["role"] == "user" and "%300,0" in fb["content"] and "EYLEM: INVESTIGATE" in fb["content"]
    assert backend.calls[4]["messages"][-2] == {"role": "assistant", "content": FABRICATED}
    m = res.session.final_metrics()
    assert m["attempt_level"]["n_violations"] == 1 and m["delivered_level"]["n_violations"] == 0


def test_exhausted_attempts_deliver_the_fallback_and_the_run_still_closes():
    res, _ = run([RANK, BACKTEST, "HAZIR", FABRICATED, FABRICATED, FABRICATED])
    assert res.status == "DELIVERED" and res.final.status == "FALLBACK" and res.session.machine.state == S.LOG_AND_CLOSE
    assert res.session.final_metrics()["delivered_level"]["fallback"] is True


def test_tool_calls_in_the_final_phase_are_refused_without_spending_an_attempt():
    res, backend = run([RANK, BACKTEST, "HAZIR", call(T.GET_MACRO_CONTEXT), GOOD])
    assert res.final.status == "ACCEPTED" and res.final.attempt == 1
    refusal = backend.calls[4]["messages"][-1]
    assert refusal["role"] == "user" and "araç" in refusal["content"].lower()
    assert res.session.machine.n_invalid_calls == 0 and len(res.session.tool_envelopes) == 2


def test_too_early_finish_is_answered_with_the_missing_steps_and_the_loop_continues():
    res, backend = run(["hemen cevap", RANK, BACKTEST, "HAZIR", GOOD])
    assert res.final.status == "ACCEPTED"
    msg = backend.calls[1]["messages"][-1]
    assert msg["role"] == "user" and any(c in msg["content"] for c in ("PRECONDITION_FAILED", "MANDATORY_STATE_NOT_REACHED"))
    assert res.session.machine.n_invalid_calls >= 1                                # erken bitirme de sayılır (PRECONDITION/MANDATORY)


def test_invalid_tool_call_is_reported_back_as_a_tool_message_and_counted():
    bad = call(T.RANK_SECTOR_RELATIVE_STRENGTH, as_of="2026-09-09")
    res, backend = run([bad, RANK, BACKTEST, "HAZIR", GOOD])
    assert res.final.status == "ACCEPTED" and res.session.machine.n_invalid_calls == 1
    err = json.loads([m for m in backend.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
    assert err["type"] == "INVALID_TOOL_CALL" and err["code"] == "AS_OF_MISMATCH"


def test_several_tool_calls_in_one_reply_run_in_order():
    two = ModelReply(tool_calls=(ToolCall("rank_sector_relative_strength", example_params(T.RANK_SECTOR_RELATIVE_STRENGTH)),
                                 ToolCall("run_backtest", example_params(T.RUN_BACKTEST))))
    res, backend = run([two, "HAZIR", GOOD])
    assert res.final.status == "ACCEPTED"
    assert [m["name"] for m in backend.calls[1]["messages"] if m["role"] == "tool"] == ["rank_sector_relative_strength", "run_backtest"]


# =============================== güvenli hata yolu ===============================
def blocking_runner(tool, params):
    env = run_mock_tool(tool, params)
    if tool == T.CHECK_DATA_QUALITY:
        env["results"]["gate_status"] = "HARD_BLOCK"
        env["results"]["hard_blocks"] = [{"code": "AS_OF_VIOLATION", "severity": "HARD", "message": "sızıntı"}]
        env["results"]["soft_warnings"] = []
        env["results"]["issue_counts"] = {"AS_OF_VIOLATION": 1}   # 1.2.0: hard+soft listelerle birebir
    return env


def test_safe_failure_is_reported_to_the_model_and_the_required_action_is_analysis_unsafe():
    res, backend = run([RANK, "HAZIR", "Veri kalitesi kapısı engelledi; analiz güvenli değil.\nEYLEM: ANALYSIS_UNSAFE"], runner=blocking_runner)
    assert res.final.status == "ACCEPTED" and res.session.machine.action == A.ANALYSIS_UNSAFE
    tool_msg = json.loads([m for m in backend.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
    assert tool_msg["type"] == "SAFE_FAILURE" and tool_msg["required_action"] == "ANALYSIS_UNSAFE"
    assert "EYLEM: ANALYSIS_UNSAFE" in backend.calls[2]["messages"][-1]["content"]


# =============================== A–C ve D′ ===============================
def test_a_has_no_tools_and_the_first_text_is_the_final_answer():
    res, backend = run(["THYAO için %5 yükseliş bekliyorum.\nEYLEM: INVESTIGATE"], stage="A")
    assert backend.calls[0]["tools"] is None and res.final.status == "RECORDED" and res.n_model_turns == 1
    assert res.session.machine.state == S.LOG_AND_CLOSE
    assert res.session.final_metrics()["delivered_level"]["n_hallucinated"] == 1          # araç yok: her sayı uydurma


def test_b_measures_without_retry_and_without_the_policy_block():
    res, backend = run([RANK, "Rapor: BIMAS'ı alın.\nEYLEM: WATCH"], stage="B")
    assert res.final.status == "RECORDED" and res.n_model_turns == 2
    assert "ADVICE_LANGUAGE" in res.session.final_metrics()["delivered_level"]["by_code"]
    assert not any("POLİTİKA KARARI" in m["content"] for call_ in backend.calls for m in call_["messages"])


def test_c_model_calls_the_gate_itself():
    res, _ = run([call(T.CHECK_DATA_QUALITY), RANK, BACKTEST, GOOD], stage="C")
    assert res.final.status == "RECORDED" and res.session.machine.n_invalid_calls == 0


def test_d_prime_enforces_but_the_first_text_is_final_without_a_block():
    res, backend = run([RANK, BACKTEST, FABRICATED, GOOD], stage="D'")
    assert res.final.status == "ACCEPTED" and res.final.attempt == 2 and res.n_model_turns == 4
    assert not any("POLİTİKA KARARI" in m["content"] for call_ in backend.calls for m in call_["messages"])


# =============================== durdurma: tur sınırı ve model hatası ===============================
def test_turn_limit_after_all_mandatory_steps_delivers_the_safe_fallback_in_d():
    loop = call(T.GET_MACRO_CONTEXT)
    res, _ = run([RANK, BACKTEST, loop, loop, loop, loop], max_turns=4)
    assert res.status == "ABORTED" and res.abort_reason == "TURN_LIMIT"
    assert res.final is not None and res.final.status == "FALLBACK" and res.session.machine.state == S.LOG_AND_CLOSE
    assert res.session.events and [e for e in res.session.events if e["kind"] == "LOOP_ABORTED"][0]["reason"] == "TURN_LIMIT"


def test_turn_limit_with_mandatory_steps_pending_delivers_nothing():
    res, _ = run([RANK, call(T.GET_MACRO_CONTEXT), call(T.GET_MACRO_CONTEXT)], max_turns=3)
    assert res.status == "ABORTED" and res.final is None and res.session.machine.state != S.LOG_AND_CLOSE


def test_model_error_aborts_cleanly_and_is_logged():
    def boom(msgs, tools):
        raise LLMError("Ollama kapalı")
    res, _ = run([RANK, BACKTEST, boom])
    assert res.status == "ABORTED" and res.abort_reason == "MODEL_ERROR" and res.final.status == "FALLBACK"
    ev = [e for e in res.session.events if e["kind"] == "LOOP_ABORTED"][0]
    assert ev["reason"] == "MODEL_ERROR" and "Ollama kapalı" in ev["message"]


def test_model_error_in_a_measure_only_profile_delivers_nothing():
    def boom(msgs, tools):
        raise LLMError("yok")
    res, _ = run([boom], stage="A")
    assert res.status == "ABORTED" and res.final is None


# =============================== yardımcılar ===============================
def test_tool_specs_follow_the_profile():
    s = HarnessSession.from_question(QUESTION, profile="D")
    specs = tool_specs(s)
    assert len(specs) == 13 and all(set(t) == {"name", "description", "parameters"} for t in specs)
    assert tool_specs(HarnessSession.from_question(QUESTION, profile="A")) == []
    assert len(tool_specs(HarnessSession.from_question(QUESTION, profile="C"))) == 14       # kapıyı C'de model çağırır


def test_system_prompt_states_the_rules_without_numbers_from_tools():
    for stage in ("A", "B", "D"):
        p = build_system_prompt(HarnessSession.from_question(QUESTION, profile=stage))
        assert "EYLEM:" in p and "yatırım tavsiyesi" in p.lower() and all(a.value in p for a in A)
        assert ("ARAÇ KULLANIMI" in p) == (stage != "A")


def test_run_is_deterministic_and_json_serialisable():
    def once():
        res, _ = run([RANK, BACKTEST, "HAZIR", FABRICATED, GOOD])
        return json.dumps(res.messages, ensure_ascii=False, sort_keys=True), res.session.final_metrics(), res.n_model_turns
    assert once() == once()


def test_system_prompt_version_and_the_oos_rule_live_in_the_system_prompt():
    from harness.agent_loop import SYSTEM_PROMPT_VERSION

    assert SYSTEM_PROMPT_VERSION == "3"
    p = build_system_prompt(HarnessSession.from_question(QUESTION, profile="D"))
    assert "split_date" in p and "out_of_sample_start" in p and "1 Ocak" in p and "varsayılan" in p
    assert "split_date" not in build_system_prompt(HarnessSession.from_question(QUESTION, profile="A"))      # A'da araç yok


def test_every_model_turn_logs_the_estimated_prompt_tokens_next_to_the_real_ones():
    res, _ = run([RANK, BACKTEST, "HAZIR", GOOD])
    turns = [e for e in res.session.events if e["kind"] == "MODEL_TURN"]
    assert [e["turn"] for e in turns] == [1, 2, 3, 4] and all(e["estimated_prompt_tokens"] > 0 for e in turns)
    assert all(e["prompt_tokens"] is None for e in turns)                      # betikli model gerçek sayı vermez (Ollama verir)
    assert turns[0]["estimated_prompt_tokens"] < turns[2]["estimated_prompt_tokens"]    # araç sonuçları geldikçe bağlam büyür
    assert [e["n_tool_calls"] for e in turns] == [1, 1, 0, 0]

