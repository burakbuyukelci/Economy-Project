"""check_data_quality: saf kural fonksiyonları ve kapı kararı (ağ yok, veri dosyası yok).

Her HARD ve SOFT koşul için en az bir test. Veri kaynağı henüz olmayan kontroller (bilanço, makro, haber, transkript,
backtest tarihleri) saf fonksiyon olarak sentetik girdiyle sınanır; `params` üzerinden çalışmazlar.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from config import settings
from schemas.enums import DQCheck, DQCode, DQSeverity, GateStatus, ToolName as T
from schemas.params import BundleItem
from schemas.results import CheckDataQualityResult, DQIssue
from tools import check_data_quality as cdq

AS_OF = date(2026, 9, 10)
V2 = "snap_2026-11-20_v2"
V1 = "snap_2026-11-20_v1"


def item(tool=T.DETECT_REVERSAL_EVENTS, n_events=30, as_of=AS_OF, data_version=V2):
    return BundleItem(tool=tool, as_of=as_of, data_version=data_version, input_hash="0" * 64, n_events=n_events)


def issue(code, severity=DQSeverity.SOFT, value=None):
    return DQIssue(code=code, severity=severity, message="x", value=value)


def codes(issues):
    return [i.code for i in issues]


# ----------------------------------------------------------------------------------------------- HARD kuralları
def test_bundle_item_as_of_after_session_as_of_is_hard():
    out = cdq.check_as_of_consistency([item(as_of=AS_OF + timedelta(days=1))], AS_OF)
    assert codes(out) == [DQCode.AS_OF_VIOLATION]
    assert out[0].severity == DQSeverity.HARD
    assert out[0].date is None and (AS_OF + timedelta(days=1)).isoformat() in out[0].message  # tarih message'ta (date geçmiş-only)
    assert "detect_reversal_events" in out[0].message


def test_bundle_item_as_of_equal_or_before_is_fine():
    assert cdq.check_as_of_consistency([item(as_of=AS_OF), item(as_of=AS_OF - timedelta(days=30))], AS_OF) == []


def test_each_violating_bundle_item_is_reported_separately():
    bad = [item(as_of=AS_OF + timedelta(days=d)) for d in (1, 5)]
    assert len(cdq.check_as_of_consistency(bad + [item()], AS_OF)) == 2


@pytest.mark.parametrize("lag", [0, -1, -5])
def test_signal_lag_below_one_is_lookahead_hard(lag):
    out = cdq.check_lookahead(signal_lag_days_applied=lag, max_result_date=None, as_of=AS_OF, tool=T.RUN_BACKTEST)
    assert codes(out) == [DQCode.LOOKAHEAD_SIGNAL] and out[0].severity == DQSeverity.HARD and out[0].value == lag


def test_signal_lag_one_or_none_is_fine():
    assert cdq.check_lookahead(1, None, AS_OF, T.RUN_BACKTEST) == []
    assert cdq.check_lookahead(None, None, AS_OF, T.DETECT_REVERSAL_EVENTS) == []


def test_result_dated_after_as_of_is_hard_but_as_of_day_is_fine():
    assert cdq.check_lookahead(1, AS_OF, AS_OF, T.RUN_BACKTEST) == []
    late = AS_OF + timedelta(days=1)
    # D6: backtest çıkışı as_of sonrası -> BACKTEST_FUTURE_INFO; diğer araçlarda as_of sonrası sonuç -> LOOKAHEAD_SIGNAL
    out = cdq.check_lookahead(1, late, AS_OF, T.RUN_BACKTEST)
    assert codes(out) == [DQCode.BACKTEST_FUTURE_INFO] and out[0].severity == DQSeverity.HARD
    assert out[0].date is None and late.isoformat() in out[0].message
    out = cdq.check_lookahead(None, late, AS_OF, T.DETECT_REVERSAL_EVENTS)
    assert codes(out) == [DQCode.LOOKAHEAD_SIGNAL] and out[0].severity == DQSeverity.HARD
    assert out[0].date is None and late.isoformat() in out[0].message


def test_lag_and_late_result_are_two_separate_issues():
    late = AS_OF + timedelta(days=3)
    assert codes(cdq.check_lookahead(0, late, AS_OF, T.RUN_BACKTEST)) == [DQCode.LOOKAHEAD_SIGNAL, DQCode.BACKTEST_FUTURE_INFO]
    assert codes(cdq.check_lookahead(0, late, AS_OF, T.CALCULATE_FUNDAMENTAL_CHANGE)) == [
        DQCode.LOOKAHEAD_SIGNAL, DQCode.LOOKAHEAD_SIGNAL]


def test_backtest_trade_entered_on_signal_day_uses_unavailable_info():
    t = cdq.TradeDates(signal_date=date(2026, 3, 2), entry_date=date(2026, 3, 2), exit_date=date(2026, 3, 9))
    out = cdq.check_backtest_information([t], AS_OF)
    assert codes(out) == [DQCode.BACKTEST_FUTURE_INFO] and out[0].severity == DQSeverity.HARD


def test_backtest_trade_entry_before_signal_is_hard():
    t = cdq.TradeDates(date(2026, 3, 2), date(2026, 3, 1), date(2026, 3, 9))
    assert codes(cdq.check_backtest_information([t], AS_OF)) == [DQCode.BACKTEST_FUTURE_INFO]


def test_backtest_trade_exit_after_as_of_is_hard():
    t = cdq.TradeDates(date(2026, 9, 8), date(2026, 9, 9), date(2026, 9, 17))
    assert codes(cdq.check_backtest_information([t], AS_OF)) == [DQCode.BACKTEST_FUTURE_INFO]


def test_valid_backtest_trades_pass():
    t = cdq.TradeDates(date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 10))
    assert cdq.check_backtest_information([t], AS_OF) == []


def test_fundamental_disclosed_after_use_date_is_future_leak_hard():
    row = cdq.FundamentalRow(period_end=date(2026, 3, 31), disclosure_date=date(2026, 5, 20), used_on=date(2026, 4, 30))
    out = cdq.check_fundamental_alignment([row], AS_OF)
    assert codes(out) == [DQCode.FUTURE_FUNDAMENTAL_LEAK] and out[0].severity == DQSeverity.HARD


def test_fundamental_disclosed_after_as_of_is_leak_even_without_use_date():
    row = cdq.FundamentalRow(period_end=date(2026, 6, 30), disclosure_date=date(2026, 9, 11), used_on=None)
    assert codes(cdq.check_fundamental_alignment([row], AS_OF)) == [DQCode.FUTURE_FUNDAMENTAL_LEAK]


def test_fundamental_disclosure_before_period_end_is_period_mismatch_hard():
    row = cdq.FundamentalRow(period_end=date(2026, 6, 30), disclosure_date=date(2026, 6, 1), used_on=None)
    out = cdq.check_fundamental_alignment([row], AS_OF)
    assert codes(out) == [DQCode.PERIOD_MISMATCH] and out[0].severity == DQSeverity.HARD


def test_aligned_fundamentals_pass():
    row = cdq.FundamentalRow(date(2026, 3, 31), date(2026, 5, 12), date(2026, 5, 12))
    assert cdq.check_fundamental_alignment([row], AS_OF) == []


# ----------------------------------------------------------------------------------------------- SOFT kuralları
def test_event_rule_table_is_tied_to_config_constants():
    r = cdq.EVENT_COUNT_RULES
    assert r[T.DETECT_REVERSAL_EVENTS].minimum == settings.MIN_EVENTS and r[T.DETECT_REVERSAL_EVENTS].unit == "olay"
    assert r[T.RANK_SECTOR_RELATIVE_STRENGTH].minimum == settings.MIN_EVENTS
    assert r[T.RUN_BACKTEST].minimum == settings.MIN_EVENTS and r[T.RUN_BACKTEST].unit == "sinyal"
    assert r[T.TEST_WEEKDAY_PATTERN].unit == "hafta"
    assert r[T.TEST_WEEKDAY_PATTERN].minimum == settings.MIN_WEEKDAY_IS_TRIGGER_WEEKS + settings.MIN_WEEKDAY_OOS_TRIGGER_WEEKS
    assert r[T.CALCULATE_FUNDAMENTAL_CHANGE].unit == "çeyrek" and r[T.CALCULATE_FUNDAMENTAL_CHANGE].minimum == 4


@pytest.mark.parametrize("tool,minimum", [
    (T.DETECT_REVERSAL_EVENTS, 20), (T.RANK_SECTOR_RELATIVE_STRENGTH, 20), (T.RUN_BACKTEST, 20),
    (T.TEST_WEEKDAY_PATTERN, 15), (T.CALCULATE_FUNDAMENTAL_CHANGE, 4),
])
def test_few_events_boundary_per_tool(tool, minimum):
    below, n_below = cdq.check_event_counts([item(tool, minimum - 1)])
    assert n_below == 1 and codes(below) == [DQCode.FEW_EVENTS]
    assert below[0].severity == DQSeverity.SOFT and below[0].value == minimum - 1
    assert cdq.check_event_counts([item(tool, minimum)]) == ([], 1)


def test_zero_events_is_few_events_soft_not_a_data_error():
    out, n = cdq.check_event_counts([item(T.RANK_SECTOR_RELATIVE_STRENGTH, 0)])
    assert n == 1 and codes(out) == [DQCode.FEW_EVENTS] and out[0].value == 0
    assert cdq.decide_gate(out, [DQCheck.EVENT_COUNT], [])[0] == GateStatus.INVESTIGATE


def test_event_count_skips_unknown_tools_and_missing_n_events():
    bundle = [item(T.GET_STOCK_HISTORY, None), item(T.GET_NEWS_EVENTS, 1), item(T.DETECT_REVERSAL_EVENTS, None)]
    assert cdq.check_event_counts(bundle) == ([], 0)           # hiçbiri değerlendirilmedi -> checks_run'a girmez
    assert cdq.check_event_counts([]) == ([], 0)


def test_event_count_evaluates_only_the_known_items_of_a_mixed_bundle():
    out, n = cdq.check_event_counts([item(T.GET_NEWS_EVENTS, 1), item(T.DETECT_REVERSAL_EVENTS, 3),
                                     item(T.CALCULATE_FUNDAMENTAL_CHANGE, 6)])
    assert n == 2 and len(out) == 1 and "detect_reversal_events" in out[0].message


def test_small_peer_group_only_when_rank_tool_in_bundle():
    sizes = {"THYAO": 2, "CCOLA": 1, "BIMAS": 3}
    out, ran = cdq.check_peer_group([item(T.RANK_SECTOR_RELATIVE_STRENGTH, 10)], ["BIMAS", "CCOLA", "THYAO"], sizes)
    assert ran and [(i.ticker, i.value) for i in out] == [("CCOLA", 1), ("THYAO", 2)]
    assert all(i.code == DQCode.SMALL_PEER_GROUP and i.severity == DQSeverity.SOFT for i in out)
    assert cdq.check_peer_group([item(T.DETECT_REVERSAL_EVENTS)], ["CCOLA"], sizes) == ([], False)
    assert cdq.check_peer_group([], ["CCOLA"], sizes) == ([], False)


def test_peer_group_of_three_is_not_small():
    assert cdq.check_peer_group([item(T.RANK_SECTOR_RELATIVE_STRENGTH)], ["BIMAS"], {"BIMAS": 3}) == ([], True)


def test_data_version_mismatch_is_soft():
    out = cdq.check_data_version([item(data_version=V1), item(data_version=V2)], V2)
    assert codes(out) == [DQCode.DATA_VERSION_MISMATCH] and out[0].severity == DQSeverity.SOFT
    assert V1 in out[0].message and V2 in out[0].message
    assert cdq.check_data_version([item()], V2) == []


@pytest.mark.parametrize("age,expect", [(0, False), (4, False), (5, True), (10, True), (11, True), (31, True)])
def test_staleness_grace_period_then_soft(age, expect):
    out = cdq.check_staleness("THYAO", AS_OF - timedelta(days=age), AS_OF)
    assert bool(out) is expect
    if expect:
        assert out[0].code == DQCode.STALE_DATA and out[0].severity == DQSeverity.SOFT and out[0].value == age
        assert out[0].ticker == "THYAO"


def test_staleness_uses_calendar_days_between_last_row_and_as_of():
    out = cdq.check_staleness("XU100", date(2026, 11, 20), date(2026, 12, 31))
    assert out[0].value == 41 and out[0].ticker == "XU100"


def test_macro_gap_is_soft_and_boundary_inclusive():
    start, end = date(2026, 1, 1), date(2026, 1, 31)
    full = [start + timedelta(days=i) for i in range(0, 31, 7)] + [end]
    assert cdq.check_macro_coverage(full, start, end, max_gap_days=7) == []
    gap = [date(2026, 1, 1), date(2026, 1, 20), end]
    out = cdq.check_macro_coverage(gap, start, end, max_gap_days=7)
    assert codes(out) == [DQCode.MACRO_GAP, DQCode.MACRO_GAP]          # 01-01 -> 01-20 (19 gün), 01-20 -> 01-31 (11 gün)
    assert [i.value for i in out] == [19, 11] and out[0].severity == DQSeverity.SOFT


def test_macro_gap_threshold_depends_on_series_frequency():
    assert cdq.MACRO_MAX_GAP_DAYS_BY_FREQUENCY == {"daily": 7, "monthly": 45}
    start, end = date(2026, 1, 1), date(2026, 6, 30)
    monthly = [date(2026, m, 15) for m in range(1, 7)]       # ay ortasında açıklanan aylık seri: boşluklar 31 gün
    assert cdq.check_macro_coverage(monthly, start, end, frequency="monthly") == []
    out = cdq.check_macro_coverage(monthly, start, end)      # varsayılan günlük: aynı seri 7 günü aşar -> uyarı
    assert out and all(i.code == DQCode.MACRO_GAP for i in out)
    skipped = [date(2026, 1, 15), date(2026, 4, 15), date(2026, 6, 15)]   # 90 günlük boşluk, aylık eşiği (45) aşar
    gaps = cdq.check_macro_coverage(skipped, start, end, frequency="monthly")
    assert [i.value for i in gaps] == [90, 61] and gaps[0].date == date(2026, 4, 15)
    assert cdq.check_macro_coverage(skipped, start, end, max_gap_days=100) == []     # açık değer frekansı ezer


def test_macro_unknown_frequency_is_rejected():
    with pytest.raises(ValueError):
        cdq.check_macro_coverage([date(2026, 1, 1)], date(2026, 1, 1), date(2026, 1, 2), frequency="weekly")


def test_macro_series_empty_is_a_gap_and_observations_after_end_are_ignored():
    start, end = date(2026, 1, 1), date(2026, 1, 10)
    assert codes(cdq.check_macro_coverage([], start, end)) == [DQCode.MACRO_GAP]
    leak = [date(2026, 1, 1), date(2026, 1, 5), date(2026, 1, 10), date(2026, 3, 1)]
    assert cdq.check_macro_coverage(leak, start, end, max_gap_days=7) == []


def test_sparse_news_is_soft_with_boundary():
    n = cdq.NEWS_MIN_ITEMS
    out = cdq.check_news_coverage(n - 1)
    assert codes(out) == [DQCode.NEWS_SPARSE] and out[0].severity == DQSeverity.SOFT and out[0].value == n - 1
    assert cdq.check_news_coverage(n) == []


def test_low_transcript_quality_is_soft_unknown_quality_is_not_evaluated():
    q = cdq.TRANSCRIPT_MIN_QUALITY
    out = cdq.check_transcript_quality(q - 0.01)
    assert codes(out) == [DQCode.TRANSCRIPT_LOW_QUALITY] and out[0].severity == DQSeverity.SOFT
    assert cdq.check_transcript_quality(q) == [] and cdq.check_transcript_quality(None) == []


# ----------------------------------------------------------------------------------------------- kapı kararı
def gate(issues, run=(), not_run=()):
    return cdq.decide_gate(issues, list(run), list(not_run))


def test_no_issues_is_pass():
    assert gate([])[0] == GateStatus.PASS


@pytest.mark.parametrize("code,value", [
    (DQCode.MACRO_GAP, 19), (DQCode.NEWS_SPARSE, 1), (DQCode.TRANSCRIPT_LOW_QUALITY, 0.4),
    (DQCode.MISSING_TRADING_DAYS, 2), (DQCode.PRICE_JUMP_OVER_LIMIT, 11.4), (DQCode.STALE_DATA, 7), (DQCode.STALE_DATA, 10),
])
def test_informational_soft_codes_give_pass_with_warnings(code, value):
    assert gate([issue(code, value=value)])[0] == GateStatus.PASS_WITH_WARNINGS


@pytest.mark.parametrize("code,value", [
    (DQCode.FEW_EVENTS, 3), (DQCode.FEW_EVENTS, 0), (DQCode.SMALL_PEER_GROUP, 2), (DQCode.DATA_VERSION_MISMATCH, None),
    (DQCode.STALE_DATA, 11), (DQCode.STALE_DATA, 30),
])
def test_evidence_weakening_soft_codes_give_investigate(code, value):
    assert gate([issue(code, value=value)])[0] == GateStatus.INVESTIGATE


def test_staleness_over_30_days_is_analysis_unsafe():
    assert gate([issue(DQCode.STALE_DATA, value=31)])[0] == GateStatus.ANALYSIS_UNSAFE


def test_zero_events_never_gives_analysis_unsafe():
    assert gate([issue(DQCode.FEW_EVENTS, value=0)] * 3)[0] == GateStatus.INVESTIGATE


def test_warnings_are_not_counted_up_into_a_higher_gate():
    many = [issue(DQCode.FEW_EVENTS, value=5), issue(DQCode.SMALL_PEER_GROUP, value=2),
            issue(DQCode.DATA_VERSION_MISMATCH)]
    assert gate(many)[0] == GateStatus.INVESTIGATE


def test_priority_hard_over_unsafe_over_investigate_over_warnings():
    hard = issue(DQCode.WRONG_TICKER_OR_BROKEN_HISTORY, DQSeverity.HARD, -90.0)
    unsafe, inv, warn = issue(DQCode.STALE_DATA, value=40), issue(DQCode.FEW_EVENTS, value=2), issue(DQCode.MACRO_GAP, value=9)
    assert gate([warn, inv, unsafe, hard])[0] == GateStatus.HARD_BLOCK
    assert gate([warn, inv, unsafe])[0] == GateStatus.ANALYSIS_UNSAFE
    assert gate([warn, inv])[0] == GateStatus.INVESTIGATE
    assert gate([warn])[0] == GateStatus.PASS_WITH_WARNINGS


def test_stale_issue_without_value_is_rejected():
    with pytest.raises(ValueError):
        gate([issue(DQCode.STALE_DATA, value=None)])


def test_gate_reason_counts_codes_and_names_checks_that_did_not_run():
    issues = [issue(DQCode.WRONG_TICKER_OR_BROKEN_HISTORY, DQSeverity.HARD, -90.7), issue(DQCode.MISSING_TRADING_DAYS, value=1),
              issue(DQCode.MISSING_TRADING_DAYS, value=1), issue(DQCode.MACRO_GAP, value=9)]
    status, reason = gate(issues, run=[DQCheck.PRICE_JUMPS], not_run=[DQCheck.SIGNAL_SHIFT, DQCheck.MACRO_COVERAGE])
    assert status == GateStatus.HARD_BLOCK
    assert "hard 1" in reason and "WRONG_TICKER_OR_BROKEN_HISTORY×1" in reason
    assert "soft 3" in reason and "MISSING_TRADING_DAYS×2" in reason and "MACRO_GAP×1" in reason
    assert "Çalışmayan kontroller" in reason and "SIGNAL_SHIFT" in reason and "MACRO_COVERAGE" in reason


def test_gate_reason_for_pass_still_lists_unrun_checks():
    status, reason = gate([], run=[DQCheck.PRICE_JUMPS], not_run=[DQCheck.NEWS_COVERAGE])
    assert status == GateStatus.PASS and "hard 0" in reason and "soft 0" in reason and "NEWS_COVERAGE" in reason


def test_decide_output_satisfies_result_schema_consistency():
    for iss in ([], [issue(DQCode.MACRO_GAP, value=9)], [issue(DQCode.FEW_EVENTS, value=2)],
                [issue(DQCode.STALE_DATA, value=40)]):
        status, reason = gate(iss, run=[DQCheck.PRICE_JUMPS])
        CheckDataQualityResult(gate_status=status, gate_reason=reason, hard_blocks=[], soft_warnings=iss,
                               checks_run=[DQCheck.PRICE_JUMPS], price_jump_limit_pct=10.0, ticker_reports=[])


def test_staleness_thresholds_are_the_agreed_tiers():
    assert (cdq.STALE_GRACE_DAYS, cdq.STALE_WARN_MAX_DAYS, cdq.STALE_UNSAFE_DAYS) == (4, 10, 30)


# --- DQIssue.date as_of'u aşamaz (schemas look-ahead taraması geçersiz zarf üretirdi) ---------------------------------
def test_no_issue_ever_carries_a_date_after_as_of():
    late = AS_OF + timedelta(days=4)
    trade = cdq.TradeDates(signal_date=late, entry_date=late, exit_date=late)
    issues = [
        *cdq.check_as_of_consistency([item(as_of=late)], AS_OF),
        *cdq.check_lookahead(0, late, AS_OF, T.RUN_BACKTEST),
        *cdq.check_lookahead(None, late, AS_OF, T.GET_MACRO_CONTEXT),
        *cdq.check_backtest_information([trade], AS_OF),
        *cdq.check_fundamental_alignment([cdq.FundamentalRow(period_end=date(2026, 6, 30), disclosure_date=late)], AS_OF),
    ]
    assert len(issues) >= 6 and all(i.date is None or i.date <= AS_OF for i in issues)
    assert all(late.isoformat() in i.message for i in issues if "signal_lag_days" not in i.message)  # tarih message'ta kalır


def test_dates_up_to_as_of_are_still_reported_in_the_date_field():
    ok_day = AS_OF - timedelta(days=2)
    out = cdq.check_fundamental_alignment([cdq.FundamentalRow(period_end=date(2026, 6, 30), disclosure_date=date(2026, 6, 1))], AS_OF)
    assert codes(out) == [DQCode.PERIOD_MISMATCH] and out[0].date == date(2026, 6, 1)
    t = cdq.TradeDates(signal_date=ok_day, entry_date=ok_day, exit_date=AS_OF)
    assert [i.date for i in cdq.check_backtest_information([t], AS_OF)] == [ok_day]
