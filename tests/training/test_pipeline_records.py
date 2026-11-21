"""v1 üretim hattı: öğretmen oturumu (GERÇEK araçlar) -> doğrulama -> kayıt biçimi ve kayıp maskesi; seçim kotaları ve veri kümesi denetimleri.

Gerçek araç testleri snapshot yoksa atlanır. Beklenen etiketler politikadan okunur (donmuş değer yok).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.text_protocol import TOOL_CALL_OPEN, TOOL_RESPONSE_OPEN
from training import spec
from training.build_dataset import LABEL_QUOTAS, _select
from training.format import build_record, dumps
from training.questions import build_questions
from training.teacher import RECOVERY_KINDS, generate, plan_calls, real_tools, recovery_kind
from training.validate import dataset_problems, session_problems

needs_data = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists(), reason="data/snapshots yok")


@pytest.fixture(scope="module")
def tools_on():
    with real_tools():
        yield


@pytest.fixture(scope="module")
def one_per_type():
    return {q.type: q for q in build_questions("train", spec.SEED, {t: 1 for t in spec.TYPE_SHARES})}


# =============================== her tip için temiz oturum ===============================
@needs_data
@pytest.mark.parametrize("qtype", list(spec.TYPE_SHARES))
def test_each_question_type_produces_a_valid_clean_session(tools_on, one_per_type, qtype):
    q = one_per_type[qtype]
    g = generate(q)
    assert session_problems(g) == [], (q.text, session_problems(g))
    rec = build_record(g)
    assert rec["label"] == g.session.machine.action.value == g.session.policy.label.value
    assert rec["versions"]["schema"] == "1.3.0" and rec["versions"]["data"] == ["snap_2026-11-20_v2"] and rec["split"] == "train"
    assert set(rec["tools"]) <= {t.value for t in spec.REAL_TOOLS} and "check_data_quality" not in rec["tools"]            # mock/harness araçları görünmez
    assert rec["token_source"] in ("gemma3", "estimate") and rec["tokens"] > 0


@needs_data
def test_the_stale_question_ends_in_safe_failure_and_analysis_unsafe(tools_on, one_per_type):
    g = generate(one_per_type["stale"])
    assert g.session.policy.label.value == "ANALYSIS_UNSAFE" and g.session.machine.safe_failure
    assert [e["tool"] for e in g.session.events if e["kind"] == "TOOL_CALL" and e["actor"] == "model"] == []          # modelin aracı çalışmadı


@needs_data
def test_unsupported_and_advice_sessions_contain_no_unsupported_numbers_and_refuse_advice(tools_on, one_per_type):
    for t in ("unsupported", "advice"):
        g = generate(one_per_type[t])
        text = g.session.machine.explanation
        assert "yatırım tavsiyesi" in text.lower() or t == "unsupported"
        assert session_problems(g) == []
    adv = generate(one_per_type["advice"]).session.machine.explanation
    assert "veremem" in adv and ("iddiası" in adv) == bool(one_per_type["advice"].plan["certainty"])


# =============================== kayıt biçimi ve maske ===============================
@needs_data
def test_record_text_messages_alternate_and_the_mask_covers_only_assistant_turns(tools_on, one_per_type):
    rec = build_record(generate(one_per_type["weekday"]))
    roles = [m["role"] for m in rec["text_messages"]]
    assert roles[0] == "system" and all(roles[i] != roles[i + 1] for i in range(1, len(roles) - 1)) and roles[1] == "user" and roles[-1] == "assistant"
    for m, train in zip(rec["text_messages"], rec["train_mask"]):
        assert train == (m["role"] == "assistant")
    assert rec["train_mask"][-1] is True                                                                        # nihai metin eğitilir
    tool_msgs = [m for m in rec["text_messages"] if m["content"].startswith(TOOL_RESPONSE_OPEN)]
    assert tool_msgs and not any(t for m, t in zip(rec["text_messages"], rec["train_mask"]) if m["content"].startswith(TOOL_RESPONSE_OPEN))
    calls = [m for m in rec["text_messages"] if m["role"] == "assistant" and TOOL_CALL_OPEN in m["content"]]
    assert calls and all(m["content"].startswith(TOOL_CALL_OPEN) for m in calls)


@needs_data
def test_the_system_message_carries_only_the_real_tools_block_and_the_prompt_version(tools_on, one_per_type):
    rec = build_record(generate(one_per_type["indicators"]))
    system = rec["text_messages"][0]["content"]
    assert "get_macro_context" not in system and "rank_sector_relative_strength" in system and TOOL_CALL_OPEN in system
    assert rec["versions"]["prompt"] == "3" and rec["versions"]["text_protocol"] == "1"


@needs_data
def test_generation_is_deterministic(tools_on, one_per_type):
    q = one_per_type["reversal"]
    assert dumps(build_record(generate(q, recovery=recovery_kind(q)))) == dumps(build_record(generate(q, recovery=recovery_kind(q))))


# =============================== hata-kurtarma yörüngeleri ===============================
@needs_data
@pytest.mark.parametrize("kind", RECOVERY_KINDS)
def test_recovery_trajectories_mask_exactly_the_bad_assistant_turn(tools_on, one_per_type, kind):
    q = one_per_type["indicators"]
    g = generate(q, recovery=kind)
    assert session_problems(g) == [], (kind, session_problems(g))
    rec = build_record(g)
    assert rec["recovery"] == kind and len(rec["bad_turns"]) == 1
    asst = [i for i, m in enumerate(rec["text_messages"]) if m["role"] == "assistant"]
    masked = [i for i in asst if not rec["train_mask"][i]]
    assert masked == [asst[rec["bad_turns"][0]]]                                                               # yalnızca hatalı tur maskeli
    assert rec["train_mask"][asst[-1]] is True
    follow = rec["text_messages"][masked[0] + 1]["content"]                                                    # hatadan sonra harness mesajı gelir
    marker = {"as_of": "AS_OF_MISMATCH", "malformed": "MALFORMED_TOOL_CALL", "early": "PRECONDITION_FAILED", "final_violation": "kurallara uymadı"}[kind]
    assert marker in follow
    if kind == "final_violation":
        assert rec["n_final_attempts"] == 2


def test_recovery_assignment_is_deterministic_close_to_ten_percent_and_stale_only_gets_final_violation():
    qs = build_questions("train", spec.SEED, spec.allocate("train"))
    kinds = [recovery_kind(q) for q in qs]
    assert kinds == [recovery_kind(q) for q in qs]
    share = sum(k is not None for k in kinds) / len(kinds)
    assert 0.05 <= share <= 0.15, share
    assert {k for q, k in zip(qs, kinds) if q.type == "stale" and k} <= {"final_violation"}
    assert set(k for k in kinds if k) == set(RECOVERY_KINDS)


# =============================== plan: araç sırası ve parametre kuralları ===============================
def test_plans_follow_the_tool_guide_rules_for_every_type():
    qs = build_questions("train", spec.SEED, {t: 2 for t in spec.TYPE_SHARES})
    for q in qs:
        calls = plan_calls(q)
        assert calls and all(p["as_of"] == q.as_of.isoformat() for _, p in calls)
        for name, p in calls:
            if name == "detect_reversal_events":
                assert p["split_date"] == f"{q.as_of.year}-01-01" and p["n_tests_declared"] == 1 + len(p.get("condition_sets", []))
            if name == "run_backtest":
                assert p["strategy"]["train_end"] == f"{q.as_of.year - 1}-12-31"
            if name == "test_weekday_pattern":
                assert p["out_of_sample_start"] == f"{q.as_of.year}-01-01" and p["in_sample_end"] < p["out_of_sample_start"]
            if name == "rank_sector_relative_strength":
                assert p["split_date"] == f"{q.as_of.year}-01-01"
    order = {"get_stock_history": 0, "get_index_history": 0, "calculate_indicators": 1, "find_support_resistance": 1,
             "rank_sector_relative_strength": 2, "detect_reversal_events": 3, "test_weekday_pattern": 3, "run_backtest": 4}
    for q in qs:
        seq = [order[n] for n, _ in plan_calls(q)]
        assert seq == sorted(seq), (q.type, [n for n, _ in plan_calls(q)])            # durum makinesi sırası (geri dönüş yok)


# =============================== seçim kotaları ve veri kümesi denetimleri ===============================
def fake(label, i, qtype="reversal", split="train"):
    return {"id": f"{split}-{qtype}-{i}-{label}", "split": split, "type": qtype, "label": label, "rule_id": "X", "tokens": 100, "token_source": "estimate",
            "recovery": None, "train_mask": [True], "text_messages": [{}], "versions": {"schema": "1.3.0", "data": ["snap_2026-11-20_v2"]}}


def test_selection_fills_label_quotas_first_then_the_rest_in_order():
    recs = [fake("INVESTIGATE", i) for i in range(30)] + [fake("TECHNICAL_REVERSAL_CANDIDATE", 100 + i) for i in range(3)] + [fake("REJECT_SIGNAL", 200 + i) for i in range(30)]
    got = _select(recs, "reversal", 20)
    labels = [r["label"] for r in got]
    assert len(got) == 20 and labels.count("TECHNICAL_REVERSAL_CANDIDATE") == 3                       # kota 4, yalnız 3 var: hepsi alınır
    assert labels.count("REJECT_SIGNAL") >= 7 and labels.count("INVESTIGATE") >= 5
    assert _select(recs, "reversal", 20) == got                                                          # belirlenimli


def test_types_without_quotas_take_candidates_in_order():
    recs = [fake("INVESTIGATE", i, "indicators") for i in range(10)]
    assert _select(recs, "indicators", 4) == recs[:4]
    assert "weekday" in LABEL_QUOTAS and abs(sum(LABEL_QUOTAS["weekday"].values()) - 1) < 1e-9


def test_dataset_problems_flag_a_dominant_label_and_wrong_sizes_and_duplicates():
    recs = [fake("INVESTIGATE", i, "indicators") for i in range(10)] + [fake("REJECT_SIGNAL", 99, "weekday")]
    probs = dataset_problems(recs, [])
    assert any("etiket payı" in p for p in probs) and any("hedef" in p for p in probs)
    dup = [fake("A", 1), fake("A", 1)]
    assert any("yinelenen" in p for p in dataset_problems(dup, []))


def test_record_json_line_is_valid_json_with_all_fields():
    r = fake("INVESTIGATE", 1)
    assert json.loads(dumps(r))["label"] == "INVESTIGATE"


def test_gemma_text_layout_folds_the_system_message_into_the_first_user_turn():
    from training.tokens import count_tokens, gemma_text

    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    assert gemma_text(msgs) == "<bos><start_of_turn>user\nS\n\nq<end_of_turn>\n<start_of_turn>model\na<end_of_turn>\n"
    assert count_tokens(msgs) > 5

