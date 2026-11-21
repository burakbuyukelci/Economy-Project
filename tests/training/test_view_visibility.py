"""Görünürlük değişmezi: nihai metinde alıntılanan HER sayı/tarih, modelin gördüğü araç görünümünde (kırpılmış `tool` mesajları + soru) bulunur.

Model görünümü kırpıldıkça (`harness/model_view.py`) model, kanıtın alıntıladığı bir sayıyı göremeyebilir; o zaman "doğru" etiketli eğitim örneği modele sayı UYDURMAYI öğretirdi.
Bu test her soru tipinde gerçek oturum üretir ve sayı doğrulayıcıyı yalnızca GÖRÜNÜMLERLE çalıştırır (hem varsayılan hem sıkı mod).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import settings
from harness.number_verifier import verify_numbers
from training import spec
from training.questions import build_questions
from training.teacher import generate, real_tools

needs_data = pytest.mark.skipif(not (Path(__file__).resolve().parents[2] / "data" / "snapshots" / "LATEST").exists(), reason="data/snapshots yok")


def visible_envelopes(messages):
    envs = []
    for m in messages:
        if m["role"] == "tool":
            d = json.loads(m["content"])
            if d.get("status") == "OK":
                envs.append({"tool": m["name"], "status": "OK", "results": d.get("results"), "warnings": d.get("warnings", []), "n_events": d.get("n_events"),
                             "n_excluded_incomplete_horizon": d.get("n_excluded_incomplete_horizon"), "params": {}, "input_hash": "x"})
    return envs


def hallucinations(g):
    rep = verify_numbers(g.result.messages[-1]["content"], envelopes=visible_envelopes(g.result.messages), question=g.question.text)
    return [c.claim.raw for c in rep.claims if c.verdict == "HALLUCINATION"]


@needs_data
@pytest.mark.parametrize("tight", [False, True])
def test_every_quoted_number_is_visible_in_the_models_tool_views(monkeypatch, tight):
    monkeypatch.setattr(settings, "MODEL_VIEW_TIGHT", tight)
    qs = build_questions("train", spec.SEED, {t: 4 for t in spec.TYPE_SHARES})
    problems = {}
    with real_tools():
        for q in qs:
            g = generate(q)
            bad = hallucinations(g)
            if bad:
                problems[q.id] = bad[:4]
    assert problems == {}, problems
