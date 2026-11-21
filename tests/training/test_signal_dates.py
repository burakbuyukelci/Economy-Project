"""Sinyal günü hedefleme: teknik dönüş sorularının bir kısmı, hissede GERÇEKTEN taze bir olay oluşan günlere (olay günü ve sonraki 2 iş günü) kurulur.

Aksi halde güncel sinyal (TECHNICAL_REVERSAL_CANDIDATE koşulu) rastgele tarihte nadirdir (~%2,5). Tarih seçimi için tüm seriden yararlanmak sızıntı DEĞİLDİR: araçlar yine as_of'a kesilmiş
veriyle çalışır; yalnızca SORU tarihi seçilir. Olay tanımı araçla aynıdır (`tools.detect_reversal_events.build_events`).
"""
from __future__ import annotations

import random
from datetime import date

import pytest

from training import spec
from training.questions import Question, build_questions
from training.signal_dates import signal_dates
from training.splits import split_of_date, tickers_for


def test_signal_dates_are_weekdays_inside_the_requested_split_and_deterministic():
    for split in spec.SPLITS:
        t = tickers_for(split, "reversal")[0]
        ds = signal_dates(t, "RSI_LOCAL_TROUGH", split)
        assert ds == signal_dates(t, "RSI_LOCAL_TROUGH", split)
        assert all(d.weekday() < 5 and split_of_date(d) == split for d in ds)


def test_each_signal_date_is_within_two_business_days_after_a_real_event():
    from datetime import timedelta

    t = tickers_for("train", "reversal")[0]
    ds = signal_dates(t, "RSI_LOCAL_TROUGH", "train")
    assert ds, "eğitim aralığında en az bir sinyal günü olmalı"
    events = signal_dates(t, "RSI_LOCAL_TROUGH", "train", raw_events=True)
    for d in ds:
        assert any(0 <= (d - e).days <= 4 and d.weekday() < 5 for e in events), d      # olay + 2 iş günü (hafta sonu dahil en çok 4 takvim günü)


def test_a_share_of_reversal_questions_is_anchored_on_signal_dates():
    qs = build_questions("train", 42, {"reversal": 120})
    anchored = 0
    for q in qs:
        fam = q.plan["family"]
        if q.as_of in set(signal_dates(q.plan["ticker"], fam, "train")):
            anchored += 1
    assert 0.3 * len(qs) <= anchored <= 0.8 * len(qs)


def test_anchoring_keeps_the_split_rules_and_determinism():
    from training.splits import leakage_problems

    a = build_questions("test", 42, {"reversal": 20})
    assert a == build_questions("test", 42, {"reversal": 20})
    assert leakage_problems(a) == []
    assert all(isinstance(q, Question) and q.as_of >= date(2026, 9, 1) for q in a)
