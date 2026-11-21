"""Colab eğitim verisi hazırlığı (training/colab/data.py): torch/transformers GEREKTİRMEYEN saf mantık. Kayıp maskesi, bağlam süzgeci, Gemma biçimi.

Gerçek tokenizer varsa (training/.cache/tokenizer.json) parça parça kodlamanın bütün metni kodlamayla AYNI olduğu da doğrulanır.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from training.colab.data import IGNORE, build_examples, encode_record, load_jsonl, segments
from training.tokens import DEFAULT_PATH, gemma_text

SYSTEM = {"role": "system", "content": "SİSTEM"}


def record(*msgs, mask=None, rid="r1"):
    text = [SYSTEM, *msgs]
    return {"id": rid, "text_messages": text, "train_mask": mask if mask is not None else [m["role"] == "assistant" for m in text]}


U = lambda c: {"role": "user", "content": c}      # noqa: E731
A = lambda c: {"role": "assistant", "content": c}  # noqa: E731


def char_encode(text: str) -> list[int]:
    """Sahte kodlayıcı: her karakter bir token (parça sınırı testleri için)."""
    return [ord(c) for c in text]


# =============================== parçalar ===============================
def test_segments_follow_the_gemma_layout_and_train_only_assistant_content_and_its_end_tag():
    segs = segments(record(U("soru"), A("cevap"), U("sonuç"), A("nihai")))
    assert segs[0] == ("<bos>", False)
    assert segs[1] == ("<start_of_turn>user\nSİSTEM\n\nsoru<end_of_turn>\n", False)                  # system ilk user'a katıldı
    assert ("<start_of_turn>model\n", False) in segs and ("cevap<end_of_turn>", True) in segs and ("nihai<end_of_turn>", True) in segs
    assert ("<start_of_turn>user\nsonuç<end_of_turn>\n", False) in segs
    assert "".join(t for t, _ in segs) == gemma_text(record(U("soru"), A("cevap"), U("sonuç"), A("nihai"))["text_messages"])


def test_a_masked_assistant_turn_is_not_trained_but_still_in_the_context():
    r = record(U("q"), A("HATALI"), U("geri bildirim"), A("doğru"), mask=[False, False, False, False, True])
    segs = segments(r)
    assert ("HATALI<end_of_turn>", False) in segs and ("doğru<end_of_turn>", True) in segs
    ex = encode_record(r, char_encode, max_len=10_000)
    assert ex is not None and len(ex["input_ids"]) == len(ex["labels"]) == len(ex["attention_mask"])
    trained = "".join(chr(t) for t, lab in zip(ex["input_ids"], ex["labels"]) if lab != IGNORE)
    assert trained == "doğru<end_of_turn>" and "HATALI" not in trained


def test_labels_equal_ids_where_trained_and_ignore_elsewhere():
    ex = encode_record(record(U("a"), A("b")), char_encode, max_len=10_000)
    for tid, lab in zip(ex["input_ids"], ex["labels"]):
        assert lab in (IGNORE, tid)
    assert ex["n_train_tokens"] == sum(1 for lab in ex["labels"] if lab != IGNORE) > 0


def test_tool_responses_and_policy_blocks_are_never_trained():
    r = record(U("soru"), A("<tool_call>x</tool_call>"), U('<tool_response name="a">\n{}\n</tool_response>'), A("HAZIR"), U("POLİTİKA KARARI"), A("nihai"))
    trained = "".join(chr(t) for t, lab in zip(encode_record(r, char_encode, 10_000)["input_ids"], encode_record(r, char_encode, 10_000)["labels"]) if lab != IGNORE)
    assert "tool_response" not in trained and "POLİTİKA" not in trained and "SİSTEM" not in trained and "soru" not in trained
    assert trained.count("<end_of_turn>") == 3


# =============================== bağlam süzgeci ===============================
def test_records_longer_than_the_limit_are_dropped_and_counted():
    long = record(U("x" * 500), A("y"), rid="long")
    short = record(U("q"), A("a"), rid="short")
    assert encode_record(long, char_encode, max_len=300) is None
    exs, stats = build_examples([long, short, record(U("q2"), A("a2"), rid="s2")], char_encode, max_len=300)
    assert [e["id"] for e in exs] == ["short", "s2"] and stats["n_in"] == 3 and stats["n_kept"] == 2 and stats["n_dropped_long"] == 1
    assert 0 < stats["train_token_share"] < 1 and stats["max_len"] == 300


def test_a_record_with_nothing_to_train_is_rejected():
    with pytest.raises(ValueError):
        encode_record(record(U("q"), A("a"), mask=[False, False, False]), char_encode, 10_000)


def test_load_jsonl_reads_one_record_per_line(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("\n".join(json.dumps(record(U(f"q{i}"), A("a"), rid=f"r{i}"), ensure_ascii=False) for i in range(3)) + "\n", encoding="utf-8")
    assert [r["id"] for r in load_jsonl(p)] == ["r0", "r1", "r2"]


# =============================== gerçek tokenizer: parçalı = bütün ===============================
@pytest.mark.skipif(not DEFAULT_PATH.exists(), reason="training/.cache/tokenizer.json yok")
def test_segment_wise_encoding_equals_whole_text_encoding_with_the_real_gemma_tokenizer():
    from tokenizers import Tokenizer

    tok = Tokenizer.from_file(str(DEFAULT_PATH))
    enc = lambda t: tok.encode(t, add_special_tokens=False).ids   # noqa: E731
    r = record(U("THYAO için RSI nedir?"), A('<tool_call>{"name":"calculate_indicators","arguments":{"ticker":"THYAO"}}</tool_call>'),
               U('<tool_response name="calculate_indicators">\n{"status":"OK","results":{"latest":{"RSI_14":44.8273}}}\n</tool_response>'),
               A("HAZIR"), U("POLİTİKA KARARI (harness hesapladı)\nEYLEM: INVESTIGATE"), A("Açıklama.\nEYLEM: INVESTIGATE"))
    ex = encode_record(r, enc, max_len=10_000)
    assert ex["input_ids"] == enc(gemma_text(r["text_messages"]))
    assert ex["input_ids"][0] == tok.token_to_id("<bos>")
    trained = tok.decode([t for t, lab in zip(ex["input_ids"], ex["labels"]) if lab != IGNORE], skip_special_tokens=False)
    assert trained.count("<end_of_turn>") == 3 and "RSI_14" not in trained and "<tool_call>" in trained
