"""check_template (ham yol): harness istemi eğitim metniyle birebir aynı mı; BOS tek mi."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments import check_template as CT
from harness.text_protocol import render_gemma_prompt
from tests.harness.test_llm_backend import _Server

REC = {"id": "r1", "text_messages": [
    {"role": "system", "content": "SİSTEM"}, {"role": "user", "content": "Soru?"},
    {"role": "assistant", "content": '<tool_call>{"name": "x", "arguments": {}}</tool_call>'},
    {"role": "user", "content": '<tool_response name="x">{"status": "OK"}</tool_response>'},
    {"role": "assistant", "content": "Nihai.\nEYLEM: INVESTIGATE"}]}


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def _records(tmp_path, rec=REC):
    p = tmp_path / "val.jsonl"
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(p)


def test_every_prefix_renders_to_the_training_text():
    for prefix in CT.prefixes(REC, 5):
        assert render_gemma_prompt(prefix) == CT.raw_prompt(prefix)
    assert len(CT.prefixes(REC, 5)) == 2 and CT.raw_prompt(CT.prefixes(REC, 5)[0]).endswith("<start_of_turn>model\n")


def test_main_passes_when_bos_is_added_once(server, tmp_path, capsys):
    server.responses += [(200, {"response": "x", "prompt_eval_count": 10}, {})] * 2
    assert CT.main(["--model", "m", "--records", _records(tmp_path), "--n", "1", "--host", server.url]) == 0
    out = capsys.readouterr().out
    assert "metin AYNI" in out and "BOS tek kez" in out and "AYNI (ham yol)" in out
    assert all(r["path"] == "/api/generate" and r["body"]["raw"] is True and r["body"]["options"]["num_predict"] == 1 for r in server.requests)


def test_main_fails_when_bos_is_doubled(server, tmp_path, capsys):
    server.responses += [(200, {"response": "x", "prompt_eval_count": 10}, {}), (200, {"response": "x", "prompt_eval_count": 11}, {})]
    assert CT.main(["--model", "m", "--records", _records(tmp_path), "--n", "1", "--host", server.url]) == 1
    assert "BOS İKİ KEZ" in capsys.readouterr().out


@pytest.mark.skipif(not Path("data/training/v2_2/val.jsonl").exists(), reason="eğitim verisi yok")
def test_all_real_validation_prefixes_render_to_the_training_text():
    recs = [json.loads(line) for line in Path("data/training/v2_2/val.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    n = 0
    for rec in recs:
        for prefix in CT.prefixes(rec, 99):
            assert render_gemma_prompt(prefix) == CT.raw_prompt(prefix), rec["id"]
            n += 1
    assert n > 100
