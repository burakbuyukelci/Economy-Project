"""Kanıt başlık bölümleri (harness/evidence_headlines.json): hangi bölüm committed, hangisi yalnızca full sette."""
from __future__ import annotations

import json
from datetime import date

import pytest

from harness.evidence import EXTRACTORS, EnvelopeStore, EvidenceBundle, headline_spec, is_headline, make_analysis_id
from schemas.enums import ToolName as T
from schemas.examples import example_envelope

QUESTION = "Analiz tarihi: 10.09.2026\nTHYAO için durum nedir?"
AS_OF = date(2026, 9, 10)
SPEC = headline_spec()


def test_spec_covers_exactly_the_tools_that_have_an_extractor():
    assert set(SPEC) == {t.value for t in EXTRACTORS}


def test_spec_is_well_formed_and_sections_are_disjoint():
    for tool, spec in SPEC.items():
        assert set(spec) == {"headline", "context", "excluded"}, tool
        for key in spec:
            assert isinstance(spec[key], list) and all(isinstance(x, str) and x for x in spec[key]), (tool, key)
        names = spec["headline"] + spec["context"] + spec["excluded"]
        assert len(names) == len(set(names)), f"{tool}: bölümler çakışıyor/tekrar ediyor"


@pytest.mark.parametrize("tool", sorted(EXTRACTORS, key=lambda t: t.value), ids=lambda t: t.value)
def test_extractor_sections_match_the_declared_spec(tool):
    """Çıkarıcının ürettiği her bölüm bildirilmiş olmalı (yoksa sessizce bağlam sayılırdı); bildirilen her bölüm gerçekten üretilmeli (bayat ad yok)."""
    spec = SPEC[tool.value]
    produced = {c.section for c in EXTRACTORS[tool](example_envelope(tool)["results"])}
    declared = set(spec["headline"]) | set(spec["context"])
    assert produced <= declared, f"bildirilmemiş bölüm: {produced - declared}"
    assert declared <= produced, f"bayat bölüm adı: {declared - produced}"
    assert not (produced & set(spec["excluded"])), "excluded bölüm kanıt üretmemeli"


def test_is_headline_semantics():
    assert is_headline(T.CALCULATE_INDICATORS, "latest") is True
    assert is_headline(T.CALCULATE_INDICATORS, "recent_rows") is False   # excluded: hiç üretilmez
    assert is_headline(T.DETECT_REVERSAL_EVENTS, "regime_breakdown") is False   # bağlam
    assert is_headline(T.DETECT_REVERSAL_EVENTS, "per_horizon") is True
    assert is_headline(T.CALCULATE_INDICATORS, "undeclared-section") is False   # bildirilmemiş => yalnızca full
    assert is_headline(T.GET_STOCK_HISTORY, "rows") is False                    # çıkarıcısı olmayan araç


def test_previously_context_only_tools_stay_context():
    """Davranış korunur: haber, konuşma, destek/direnç, rejim kırılımı hâlâ yalnızca full sette."""
    for tool in (T.GET_NEWS_EVENTS, T.GET_SPEECH_FEATURES, T.FIND_SUPPORT_RESISTANCE):
        assert SPEC[tool.value]["headline"] == []
    assert SPEC[T.DETECT_REVERSAL_EVENTS.value]["context"] == ["regime_breakdown"]


# =============================== gerçek calculate_indicators zarfı ===============================
def _bundle(*envs):
    store = EnvelopeStore()
    for e in envs:
        store.add(e, actor="model")
    aid = make_analysis_id(AS_OF, QUESTION)
    b = EvidenceBundle(aid, store)
    out = b.build({"as_of": "2026-09-10", "analysis_id": aid, "source_input_hashes": [e["input_hash"] for e in envs]})
    return b, out["results"]


def test_real_indicators_latest_is_committed_with_values_and_states(thyao_indicators):
    _, res = _bundle(thyao_indicators)
    committed = res["committed_evidence_set"]
    assert len(committed) == 1 and committed[0]["source_tool"] == "calculate_indicators"
    names = {v["name"] for v in committed[0]["values"]}
    assert {"close", "RSI_14", "BB_LOWER_20_2.0", "SUPERTREND_10_3.0", "supertrend"} <= names
    vals = {v["name"]: v["value"] for v in committed[0]["values"]}
    assert vals["RSI_14"] == 44.8273 and vals["supertrend"] == "BEARISH"
    assert res["committed_evidence_set"] == res["full_evidence_set"]   # tek aday, tamamı başlık


def test_real_indicators_recent_rows_never_enter_the_evidence(thyao_indicators):
    _, res = _bundle(thyao_indicators)
    blob = json.dumps(res["full_evidence_set"], ensure_ascii=False)
    recent = thyao_indicators["results"]["recent_rows"]
    assert recent, "fixture recent_rows boş olmamalı"
    for row in recent:
        assert str(row["values"]["RSI_14"]) not in blob   # recent_rows değerleri full sette bile yok


def test_committed_is_a_subset_of_full_for_all_example_tools():
    tools = [t for t in EXTRACTORS if t not in (T.CALCULATE_INDICATORS,)]
    envs = [example_envelope(t) for t in tools]
    _, res = _bundle(*envs)
    full_ids = {e["evidence_id"] for e in res["full_evidence_set"]}
    committed_ids = {e["evidence_id"] for e in res["committed_evidence_set"]}
    assert committed_ids and committed_ids < full_ids   # bağlam kanıtı olduğu için kesin alt küme
