"""(1) Oturumda modele AÇIK araç kümesi (`exposed_tools`): v1 eğitim verisi yalnızca gerçek araçlarla üretilir, mock araçlar modele hiç gösterilmez.
(2) get_stock_history / get_index_history için kanıt çıkarıcı: dönem özeti (ilk/son/en yüksek/en düşük kapanış; araç çıktısından SEÇİLEN satırlar, türetme yok).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from harness.agent_loop import build_system_prompt, tool_specs
from harness.evidence import EXTRACTORS, EnvelopeStore, EvidenceBundle, headline_spec, is_headline, make_analysis_id
from harness.number_verifier import verify_numbers
from harness.session import HarnessSession
from schemas.enums import ToolName as T
from schemas.examples import example_params

Q = "Analiz tarihi: 10.09.2026\nTHYAO için durum nedir?"
REAL = frozenset({T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY, T.CALCULATE_INDICATORS, T.FIND_SUPPORT_RESISTANCE, T.RANK_SECTOR_RELATIVE_STRENGTH,
                  T.DETECT_REVERSAL_EVENTS, T.TEST_WEEKDAY_PATTERN, T.RUN_BACKTEST})


# =============================== exposed_tools ===============================
def test_exposed_tools_limit_what_the_model_sees_in_every_profile():
    s = HarnessSession.from_question(Q, profile="D", exposed_tools=REAL)
    assert set(s.visible_tools) == REAL and {t["name"] for t in tool_specs(s)} == {t.value for t in REAL}
    c = HarnessSession.from_question(Q, profile="C", exposed_tools=REAL | {T.CHECK_DATA_QUALITY})
    assert T.CHECK_DATA_QUALITY in c.visible_tools and T.GET_MACRO_CONTEXT not in c.visible_tools
    assert HarnessSession.from_question(Q, profile="A", exposed_tools=REAL).visible_tools == []          # A'da araç hiç yok


def test_default_is_all_profile_tools_and_harness_only_tools_are_never_added():
    assert len(HarnessSession.from_question(Q, profile="D").visible_tools) == 13
    s = HarnessSession.from_question(Q, profile="D", exposed_tools=set(T))                                   # hepsi istense bile kapı/paket harness'in
    assert T.CHECK_DATA_QUALITY not in s.visible_tools and T.BUILD_EVIDENCE_BUNDLE not in s.visible_tools


def test_a_hidden_tool_call_is_rejected_as_not_exposed():
    s = HarnessSession.from_question(Q, profile="D", exposed_tools=REAL)
    r = s.call_tool("get_macro_context", example_params(T.GET_MACRO_CONTEXT))
    assert not r.ok and r.error["code"] == "TOOL_NOT_EXPOSED" and s.machine.n_invalid_calls == 1


def test_the_system_prompt_and_tool_block_do_not_mention_hidden_tools():
    s = HarnessSession.from_question(Q, profile="D", exposed_tools=REAL)
    from harness.text_protocol import render_tools_block
    block = render_tools_block(tool_specs(s))
    assert "get_macro_context" not in block and "get_fundamental_metrics" not in block and "rank_sector_relative_strength" in block
    assert "get_macro_context" not in build_system_prompt(s)


def test_exposed_tools_from_settings_apply_when_no_argument_is_given(monkeypatch):
    from harness import settings

    monkeypatch.setattr(settings, "EXPOSED_TOOLS", frozenset(REAL))
    assert set(HarnessSession.from_question(Q, profile="D").visible_tools) == REAL


# =============================== geçmiş kanıtı ===============================
@pytest.fixture(scope="module")
def histories():
    if not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists():
        pytest.skip("data/snapshots yok")
    from tools import get_index_history, get_stock_history

    st = get_stock_history.run({"ticker": "THYAO", "start": "2026-08-10", "end": "2026-09-10", "as_of": "2026-09-10"})
    ix = get_index_history.run({"index": "XU100", "start": "2026-08-10", "end": "2026-09-10", "as_of": "2026-09-10"})
    assert st["status"] == ix["status"] == "OK"
    return st, ix


def committed(env):
    store = EnvelopeStore()
    store.add(env, actor="model")
    aid = make_analysis_id(date(2026, 9, 10), Q)
    b = EvidenceBundle(aid, store)
    b.build({"as_of": "2026-09-10", "analysis_id": aid, "source_input_hashes": [env["input_hash"]]})
    b.lock("PASS")
    return [i for i in b.snapshot()["committed_evidence_set"] if i["source_input_hash"] == env["input_hash"]]


def value_of(item, name):
    return next((v["value"] for v in item["values"] if v["name"] == name), None)


def test_history_tools_now_have_extractors_and_a_headline_section():
    assert T.GET_STOCK_HISTORY in EXTRACTORS and T.GET_INDEX_HISTORY in EXTRACTORS
    for tool in (T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY):
        assert is_headline(tool, "range") and {"range"} == set(headline_spec()[tool.value]["headline"])


@pytest.mark.parametrize("which", [0, 1], ids=["stock", "index"])
def test_history_range_statement_quotes_rows_from_the_tool_output(histories, which):
    env = histories[which]
    res = env["results"]
    (item,) = committed(env)
    rows = res["rows"]
    hi, lo = max(rows, key=lambda r: r["close"]), min(rows, key=lambda r: r["close"])
    assert value_of(item, "first_close") == rows[0]["close"] and value_of(item, "last_close") == rows[-1]["close"]
    assert value_of(item, "high_close") == hi["close"] and value_of(item, "low_close") == lo["close"]
    assert value_of(item, "n_rows") == res["n_rows"] and value_of(item, "first_date") == res["first_date"] and value_of(item, "last_date") == res["last_date"]
    assert str(hi["close"]) in item["statement"] and hi["date"] in item["statement"]
    assert verify_numbers(item["statement"], envelopes=[env], question="Analiz tarihi: 10.09.2026").n_hallucinated == 0


def test_history_without_rows_gives_no_statement():
    c = EXTRACTORS[T.GET_STOCK_HISTORY]({"ticker": "THYAO", "rows": [], "n_rows": 0})
    assert c == []
