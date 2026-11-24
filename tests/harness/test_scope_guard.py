"""Kapsam koruması: kapsam dışı sorular (hava durumu...) hemen reddedilir; HİÇBİR finans sorusu reddedilmemeli (yanlış reddetme yasak)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.scope_guard import MESSAGE, is_out_of_scope

OFF_TOPIC = [
    "Yarın İstanbul'da hava nasıl olacak, şemsiye almalı mıyım?",
    "Bana bir çikolatalı kek tarifi ver.",
    "Fransa'nın başkenti neresidir?",
    "Bugün hangi film izlemeliyim?",
    "Merhaba, nasılsın?",
]
IN_SCOPE = [
    "THYAO hissesi Pzt–Sal–Çar düşüş, ardından Per–Cum yükseliş örüntüsü 2024–2025'te var mıydı?",
    "Perakende sektöründe en çok geride kalan hisse hangisi?",
    "Dolar/TL yükseliyor, ihracatçı olduğu için kesin yükselir. Yarın alayım mı? Hedef fiyat ver.",
    "TUPRS bilançolarında FAVÖK marjı nasıl değişti?",
    "ASELS alt Bollinger bandına kaç kez dokundu?",
    "Bugün ne almalıyım?",
    "Bu hisse yükselir mi?",
    "Portföyümü nasıl dengelemeliyim?",
    "Enflasyon açıklandıktan sonra endeks nasıl tepki verdi?",
]


@pytest.mark.parametrize("q", OFF_TOPIC)
def test_off_topic_is_out_of_scope(q):
    assert is_out_of_scope(q)


@pytest.mark.parametrize("q", IN_SCOPE)
def test_finance_questions_are_never_rejected(q):
    assert not is_out_of_scope(q)


def test_message_has_allowed_action_and_no_advice():
    assert MESSAGE.rstrip().endswith("EYLEM: ANALYSIS_UNSAFE") and "yatırım tavsiyesi değildir" in MESSAGE


def test_no_training_or_test_question_is_rejected():
    """Eğitim/doğrulama/test sorularının HİÇBİRİ kapsam dışı sayılmamalı (varsa yanlış reddetme)."""
    root = Path("data/training/v2_2")
    files = [root / f"{s}.jsonl" for s in ("train", "val", "test")]
    if not all(f.exists() for f in files):
        pytest.skip("eğitim verisi yok (git'te değil)")
    bad = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if is_out_of_scope(r["question"]):
                bad.append(r["id"])
    assert not bad, bad[:5]
