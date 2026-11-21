"""v1 eğitim verisi: bölme (hisse/grup + tarih + şablon) ve soru üreticisi. Araç çalıştırmaz; yalnızca belirlenimci üretim ve sızıntı kuralları.

Bölme KURALI üretimden ÖNCE verilir: test = hiç görülmeyen hisse grupları + hiç görülmeyen tarihler + eğitimde görülmeyen soru şablonları.
Retail tek ≥3 üyeli peer grubudur: catch-up soruları grup bazında tutulamaz, yalnızca TARİHE ve şablona göre ayrılır (meta: group_held_out=False).
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from config.universe import build_sector_peer_groups
from training import spec
from training.questions import Question, build_questions
from training.splits import (is_test_only_template, leakage_problems, pick_trading_date, split_of_date, tickers_for)

SEED = 42


def all_questions():
    return {s: build_questions(s, SEED, spec.allocate(s)) for s in spec.SPLITS}


# =============================== spec ===============================
def test_sizes_and_type_allocation_match_the_agreed_totals():
    assert spec.SIZES == {"train": 600, "val": 50, "test": 100}
    for split, n in spec.SIZES.items():
        alloc = spec.allocate(split)
        assert sum(alloc.values()) == n and set(alloc) == set(spec.TYPE_SHARES) and all(v >= 1 for v in alloc.values())
    assert abs(sum(spec.TYPE_SHARES.values()) - 1.0) < 1e-9


def test_only_real_tools_are_exposed_and_gate_tools_are_not():
    from schemas.enums import ToolName as T

    assert spec.REAL_TOOLS == frozenset({T.GET_STOCK_HISTORY, T.GET_INDEX_HISTORY, T.CALCULATE_INDICATORS, T.FIND_SUPPORT_RESISTANCE,
                                         T.RANK_SECTOR_RELATIVE_STRENGTH, T.DETECT_REVERSAL_EVENTS, T.TEST_WEEKDAY_PATTERN, T.RUN_BACKTEST})


# =============================== hisse/grup bölmesi ===============================
def test_ticker_groups_are_disjoint_across_splits_and_cover_the_universe_read_from_the_csv():
    groups = build_sector_peer_groups()
    universe = {t for ts in groups.values() for t in ts}
    sets = {s: set(tickers_for(s, "weekday")) for s in spec.SPLITS}
    assert sets["train"] | sets["val"] | sets["test"] == universe
    assert not (sets["train"] & sets["val"]) and not (sets["train"] & sets["test"]) and not (sets["val"] & sets["test"])
    assert 5 <= len(sets["test"]) <= 10 and 3 <= len(sets["val"]) <= 8 and len(sets["train"]) >= 14
    for ts in groups.values():                                 # bir peer grubu TEK bölmede (grup bazında tutma)
        assert len({s for s in spec.SPLITS if set(ts) & sets[s]}) == 1, ts


def test_retail_is_kept_in_train_for_stock_level_types_and_catch_up_uses_it_in_every_split():
    groups = build_sector_peer_groups()
    assert set(groups["retail"]) <= set(tickers_for("train", "weekday"))
    for s in spec.SPLITS:
        assert tickers_for(s, "catch_up") == ["BIMAS", "MAVI", "MGROS"]


def test_ticker_assignment_is_deterministic_and_changes_with_the_seed(monkeypatch):
    a = {s: tickers_for(s, "weekday") for s in spec.SPLITS}
    assert a == {s: tickers_for(s, "weekday") for s in spec.SPLITS}
    monkeypatch.setattr(spec, "SEED", 7)
    from training import splits
    splits.ticker_split_map.cache_clear()
    b = {s: tickers_for(s, "weekday") for s in spec.SPLITS}
    assert b != a
    monkeypatch.setattr(spec, "SEED", 42)
    splits.ticker_split_map.cache_clear()


# =============================== tarih bölmesi ===============================
def test_date_ranges_are_ordered_and_disjoint_and_trading_dates_are_weekdays_in_range():
    import random

    ranges = [spec.DATE_RANGES[s] for s in spec.SPLITS]
    assert all(a[1] < b[0] for a, b in zip(ranges, ranges[1:]))
    stale = [spec.STALE_RANGES[s] for s in spec.SPLITS]
    assert all(a[1] < b[0] for a, b in zip(stale, stale[1:])) and stale[0][0] > date(2027, 1, 14)       # kapı gerçekten ANALYSIS_UNSAFE verir
    rng = random.Random(1)
    for s in spec.SPLITS:
        for stale_flag in (False, True):
            lo, hi = (spec.STALE_RANGES if stale_flag else spec.DATE_RANGES)[s]
            for _ in range(50):
                d = pick_trading_date(s, rng, stale=stale_flag)
                assert lo <= d <= hi and d.weekday() < 5 and split_of_date(d) == s


# =============================== şablon bölmesi ===============================
def test_template_holdout_rule():
    assert [is_test_only_template(i) for i in range(8)] == [False, False, False, True, False, False, False, True]


# =============================== sorular ===============================
def test_questions_are_deterministic_unique_and_sized():
    a, b = all_questions(), all_questions()
    assert a == b
    for s, qs in a.items():
        assert len(qs) == spec.SIZES[s] and len({q.text for q in qs}) == len(qs) and len({q.id for q in qs}) == len(qs)
        assert Counter(q.type for q in qs) == Counter(spec.allocate(s))


def test_every_question_starts_with_the_analysis_date_line_and_the_date_is_inside_the_split():
    for s, qs in all_questions().items():
        for q in qs:
            assert q.text.startswith(f"Analiz tarihi: {q.as_of.strftime('%d.%m.%Y')}\n"), q.text[:60]
            assert split_of_date(q.as_of) == s and q.split == s


def test_split_rules_hold_for_tickers_dates_and_templates():
    qs = all_questions()
    groups = build_sector_peer_groups()
    for s, items in qs.items():
        for q in items:
            allowed = set(tickers_for(s, q.type))
            assert set(q.tickers) <= allowed, (q.id, q.tickers)
            if s != "test":
                assert not is_test_only_template(q.template_idx), q.id                       # test şablonları eğitimde/doğrulamada YOK
    assert leakage_problems([q for items in qs.values() for q in items]) == []
    assert any(is_test_only_template(q.template_idx) for q in qs["test"])
    assert groups["retail"]


def test_leakage_checker_catches_each_kind_of_leak():
    qs = all_questions()
    train, test = qs["train"][0], qs["test"][0]
    leaked_text = Question(**{**test.__dict__, "text": train.text})
    assert leakage_problems([train, leaked_text])
    bad_ticker = Question(**{**train.__dict__, "tickers": (next(iter(tickers_for("test", "weekday"))),), "type": "weekday"})
    assert leakage_problems([bad_ticker])
    bad_date = Question(**{**train.__dict__, "as_of": date(2026, 10, 1)})
    assert leakage_problems([bad_date])


def test_type_specific_plans_carry_what_the_teacher_needs():
    qs = [q for items in all_questions().values() for q in items]
    by = {t: [q for q in qs if q.type == t] for t in spec.TYPE_SHARES}
    w = by["weekday"][0].plan
    assert {"pattern", "is_start", "is_end", "oos_start", "oos_end"} <= set(w) and w["oos_start"].month == 1 and w["oos_start"].day == 1
    assert w["is_end"] < w["oos_start"] and w["oos_end"] == by["weekday"][0].as_of
    assert all(q.plan["family"] in ("BB_LOWER_TOUCH", "RSI_LOCAL_TROUGH") for q in by["reversal"])
    assert all(q.plan["horizon"] in (5, 10, 20) for q in by["catch_up"])
    assert all(q.plan["indicators"] for q in by["indicators"])
    assert any(q.plan["with_backtest"] for q in by["reversal"]) and any(not q.plan["with_backtest"] for q in by["reversal"])
    assert any(q.plan["certainty"] for q in by["advice"]) and any(not q.plan["certainty"] for q in by["advice"])
    assert {q.plan["kind"] for q in by["unsupported"]} == {"fundamental", "macro", "news", "future"}
    assert all(q.as_of >= date(2027, 1, 18) for q in by["stale"])
    for q in by["advice"]:
        if q.plan["certainty"]:
            assert q.plan["claim"] in q.text


def test_unsupported_and_weekday_questions_never_mention_internal_tool_names_or_labels_unexpectedly():
    for items in all_questions().values():
        for q in items:
            assert "run_backtest" not in q.text and "calculate_indicators" not in q.text


def test_pattern_text_separates_trigger_and_outcome_groups_even_with_the_same_direction():
    from training.questions import _pattern_text

    assert _pattern_text([("MON", "DOWN", "TRIGGER"), ("TUE", "DOWN", "TRIGGER"), ("THU", "UP", "OUTCOME"), ("FRI", "UP", "OUTCOME")])         == "Pazartesi–Salı düşüş, ardından Perşembe–Cuma yükseliş"
    assert _pattern_text([("MON", "DOWN", "TRIGGER"), ("THU", "DOWN", "OUTCOME")]) == "Pazartesi düşüş, ardından Perşembe düşüş"

