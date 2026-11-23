"""Şema 1.5.0 makro ilişkisi: kanıt cümleleri kaynaktan AYNEN, model görünümü kırpması ve görünürlük değişmezi (kanıtın alıntıladığı her sayı modelin görünümünde)."""
from __future__ import annotations

import copy
import json
import re

import pytest

from harness.evidence import EXTRACTORS, headline_spec
from harness.model_view import model_view
from schemas.enums import ToolName as T
from schemas.examples import example_envelope

NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _env(n_points: int = 700):
    env = copy.deepcopy(example_envelope(T.GET_MACRO_CONTEXT))
    s = env["results"]["series"][0]
    s["points"] = [{"observation_date": f"2024-01-{(i % 28) + 1:02d}", "publication_date": f"2024-01-{(i % 28) + 1:02d}", "value": 30.0 + i * 0.01}
                   for i in range(n_points)] + s["points"]
    s["n_points"] = len(s["points"])
    env["warnings"] = ["HISTORICAL_ONLY: makro veri seti macro_2026-11-09_v2; kaynak TCMB/EVDS; resmî tatil iş günleri ... USDTRY 31 gün (ilk: 2024-01-01, 2024-04-10)",
                       "COST_ASSUMPTIONS: tur maliyeti 0.5 pp", "ASSOCIATION_NOT_CAUSATION: ilişki gözlemidir"]
    return env


def _cands():
    return EXTRACTORS[T.GET_MACRO_CONTEXT](_env()["results"])


def test_sections_are_declared_headline_and_unique_per_relation():
    spec = headline_spec()["get_macro_context"]
    sections = [c.section for c in _cands()]
    assert set(sections) == {"latest_point", "relation", "relation_groups", "relation_split", "multiple_testing"}
    assert set(sections) <= set(spec["headline"]) and "points" in spec["excluded"]


def test_every_number_in_a_statement_comes_from_the_source_envelope():
    src = set(NUM.findall(json.dumps(_env()["results"])))
    for c in _cands():
        for n in NUM.findall(c.statement):
            assert n in src, (c.statement, n)
        for v in c.values:                                   # değerler de kaynakta aynen
            if isinstance(v["value"], (int, float)):
                assert str(v["value"]) in src or str(float(v["value"])) in src, v


def test_view_keeps_only_what_evidence_can_quote_and_hides_the_dataset_note():
    env = _env()
    v = model_view(env, subject="EREGL")
    res = v["results"]
    assert [len(s["points"]) for s in res["series"]] == [1] and res["series"][0]["points"][-1]["value"] == 41.0   # yalnızca SON nokta (kanıt son gözlemi alıntılar)
    assert "gaps" not in res["series"][0] and "cost_model" not in res and "view_trimmed" in v and "macro_view" in v["view_trimmed"]
    rel = res["relations"][0]
    assert set(rel) == {"ticker", "macro_series", "horizon", "lag_days", "transform", "full", "in_sample", "out_of_sample", "oos_degradation_flag"}
    assert set(rel["in_sample"]) == {"n_obs", "correlation"} and "median_return_pct" not in rel["full"]["macro_up"]
    assert set(res["multiple_testing"]) == {"n_tests_declared", "alpha", "adjusted_alpha", "method"}
    assert not any(w.startswith(("HISTORICAL_ONLY", "COST_ASSUMPTIONS")) for w in v["warnings"]) and any(w.startswith("ASSOCIATION") for w in v["warnings"])
    assert len(json.dumps(v)) < 3000 < len(json.dumps(env))     # 700+ nokta modele gitmez
    assert env == _env()                                          # girdi değişmez


def test_visibility_invariant_every_evidence_number_is_in_the_model_view():
    view_text = json.dumps(model_view(_env(), subject="EREGL"))
    seen = set(NUM.findall(view_text))
    for c in _cands():
        for n in NUM.findall(c.statement):
            assert n in seen, (c.statement, n)


def test_view_of_envelope_without_relations_still_slims_points():
    env = _env()
    env["results"]["relations"], env["results"]["multiple_testing"], env["results"]["cost_model"] = [], None, None
    v = model_view(env, subject=None)
    assert "relations" not in v["results"] and len(v["results"]["series"][0]["points"]) == 1
