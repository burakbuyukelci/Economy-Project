"""test_weekday_pattern: haftanın günü / çok günlü örüntü testi (IS/OOS ayrımı, maliyet, çoklu test).

HAFTA MODELİ (docs/data_dictionary.md §17):
  * Gün getirisi = adj_close[d] / adj_close[bir önceki HAFTA İÇİ günü] - 1 (Pzt için önceki Cuma). İki gün de snapshot'ta
    yoksa (tatil / veri boşluğu) getiri tanımsızdır ve o gün örüntüde ise hafta DIŞLANIR (`n_excluded_holiday_weeks`).
  * Hafta, İLK örüntü gününün tarihi pencerede ise o pencereye atanır. Son örüntü günü pencere sonunu aşarsa:
    `as_of`'u da aşıyorsa "ufku dolmamış" (`n_excluded_incomplete_horizon`), aşmıyorsa pencere sınırını aşan hafta
    hiçbir pencereye girmez (IS/OOS verisi karışmasın) ve `n_excluded_holiday_weeks` içinde sayılır.
  * TRIGGER haftası: tüm TRIGGER günleri beklenen yönde (+ varsa XU100 koşulu). OUTCOME getirisi = OUTCOME günlerinin
    bileşik getirisi. Tur maliyeti TRIGGER haftası başına bir kez düşülür; DOWN çıktıda işaret çevrilir (yönlü).

ANLAMLILIK: permütasyon testi. Tüm tam haftalardan rastgele `k` hafta (k = tetik haftası sayısı) çekilir; istatistik
`ort(k hafta) - ort(tüm haftalar)` (şemadaki `outcome_mean_diff_vs_unconditional_pct` ile aynı fark, aynı baz). Tek yönlü
(beklenen yön), B = 10 000, sabit seed. Dağılım varsayımı yok; scipy gerekmez.

as_of: hisse ve endeks `enforce_as_of` ile kesilir; as_of sonrası hiçbir satır hesaba girmez. Ağ yok.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from schemas.common import MultipleTesting, SampleWindow, make_cost_model
from schemas.enums import Conditioning, Direction, PatternRole, StabilityVerdict, ToolName, Weekday, WarningCode
from schemas.envelope import make_warning
from schemas.params import TestWeekdayPatternParams
from schemas.results import PatternDayStats, TestWeekdayPatternResult, WeekdayPeriodResult
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool, trading_calendar
from tools.stability import weekday_stability_verdict

TOOL = ToolName.TEST_WEEKDAY_PATTERN
ROUND = 4
P_ROUND = 6
N_PERMUTATIONS = 10_000   # B
PERMUTATION_SEED = 481    # sabit seed: aynı girdi -> aynı p-değeri
_CHUNK = 1_000
_WD = {Weekday.MON: 0, Weekday.TUE: 1, Weekday.WED: 2, Weekday.THU: 3, Weekday.FRI: 4}


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0  # "+ 0.0": -0.0 -> 0.0


# =====================================================================================================
# saf yardımcılar (testlerde doğrudan sınanır)
# =====================================================================================================
def permutation_pvalue(y: np.ndarray, trig: np.ndarray, n_perm: int = N_PERMUTATIONS,
                       seed: int = PERMUTATION_SEED) -> float | None:
    """Tek yönlü permütasyon p-değeri: P(ort(rastgele k hafta) - ort(hepsi) >= gözlenen fark).

    y: yönlü çıktı getirisi (UP: getiri, DOWN: -getiri), tüm tam haftalar. trig: bool maske (k = trig.sum()).
    (sayım + 1) / (B + 1): p asla 0 olmaz. k = 0 ise None.
    Örnek: y=[1,0,0,0], tetik = ilk hafta -> gözlenen fark 0,75; k=1 çekimde 0,75 ancak o hafta seçilince -> p ~ 0,25.
    """
    y = np.asarray(y, float)
    n, k = len(y), int(np.sum(trig))
    if k == 0 or n == 0:
        return None
    mean_all = float(y.mean())
    obs = float(y[trig].mean()) - mean_all
    rng = np.random.default_rng(seed)
    count = 0
    for start in range(0, n_perm, _CHUNK):
        m = min(_CHUNK, n_perm - start)
        idx = np.argpartition(rng.random((m, n)), k - 1, axis=1)[:, :k]  # her satır: n haftadan k'sı (iadesiz)
        count += int(np.sum(y[idx].mean(axis=1) - mean_all >= obs - 1e-9))
    return (count + 1) / (n_perm + 1)


def _t_stat(y: np.ndarray, trig: np.ndarray) -> float | None:
    """Standartlaştırılmış fark: fark / (s_tüm x sqrt(1/k - 1/N)) (iadesiz örnekleme). YÖNLÜ: pozitif = beklenen yönde."""
    n, k = len(y), int(np.sum(trig))
    if k == 0 or n < 2 or k >= n:
        return None
    s = float(y.std(ddof=1))
    if s == 0:
        return None
    return (float(y[trig].mean()) - float(y.mean())) / (s * np.sqrt(1 / k - 1 / n))


# =====================================================================================================
# hafta tablosu
# =====================================================================================================
def _week_returns(close: dict[date, float], monday: date, wds: list[int]) -> dict[int, float] | None:
    """Örüntü günlerinin bir günlük getirisi (%); herhangi biri tanımsızsa None."""
    out: dict[int, float] = {}
    for wd in wds:
        d = monday + timedelta(days=wd)
        prev = d - timedelta(days=3 if wd == 0 else 1)
        if d not in close or prev not in close:
            return None
        out[wd] = (close[d] / close[prev] - 1.0) * 100.0
    return out


def _index_return(idx_dates: np.ndarray, idx_close: np.ndarray, base_day: date, end_day: date) -> float | None:
    """XU100 getirisi (%): base_day'e (dahil) kadarki SON satırdan end_day'e (dahil) kadarki SON satıra. Yalnızca geçmiş."""
    b = np.searchsorted(idx_dates, np.datetime64(base_day), side="right") - 1
    e = np.searchsorted(idx_dates, np.datetime64(end_day), side="right") - 1
    if b < 0 or e < 0 or e <= b:
        return None
    return (idx_close[e] / idx_close[b] - 1.0) * 100.0


def _period(p: TestWeekdayPatternParams, start: date, end: date, *, close: dict[date, float], all_days: pd.Series,
            calendar: set[date], idx: tuple[np.ndarray, np.ndarray] | None) -> tuple[WeekdayPeriodResult, dict]:
    eff_end = min(end, p.as_of)
    days = sorted(p.pattern, key=lambda d: _WD[d.weekday])
    wds = [_WD[d.weekday] for d in days]
    trig_days = [d for d in days if d.role == PatternRole.TRIGGER]
    out_days = [d for d in days if d.role == PatternRole.OUTCOME]
    out_sign = 1.0 if out_days[0].direction == Direction.UP else -1.0
    first_wd, last_wd = min(wds), max(wds)
    last_trig_wd = max(_WD[d.weekday] for d in trig_days)

    def match(d, r: float) -> bool:
        return r > 0 if d.direction == Direction.UP else r < 0

    monday = start - timedelta(days=start.weekday())
    n_total = n_holiday = n_incomplete = n_gap_only = 0
    rows: list[dict[int, float]] = []
    triggered: list[bool] = []
    while monday + timedelta(days=first_wd) <= eff_end:
        first_day = monday + timedelta(days=first_wd)
        last_day = monday + timedelta(days=last_wd)
        if first_day >= start:
            n_total += 1
            if last_day > eff_end:
                if last_day > p.as_of:
                    n_incomplete += 1
                else:
                    n_holiday += 1  # pencere sınırını aşan hafta: hiçbir pencereye girmez
            else:
                wr = _week_returns(close, monday, wds)
                if wr is None:
                    n_holiday += 1
                    if all((monday + timedelta(days=wd)) in calendar for wd in wds):
                        n_gap_only += 1  # takvimde var, hissede yok: veri boşluğu (tatil değil)
                else:
                    ok = all(match(d, wr[_WD[d.weekday]]) for d in trig_days)
                    if ok and p.conditioning != Conditioning.NONE:
                        base = monday - timedelta(days=3)  # önceki Cuma (yoksa o güne kadarki son satır)
                        xr = _index_return(*idx, base, monday + timedelta(days=last_trig_wd)) if idx else None
                        ok = xr is not None and (xr > 0 if p.conditioning == Conditioning.XU100_UP else xr < 0)
                    rows.append(wr)
                    triggered.append(ok)
        monday += timedelta(days=7)

    n_complete = len(rows)
    trig = np.array(triggered, bool)

    def compound(wr: dict[int, float]) -> float:
        v = 1.0
        for d in out_days:
            v *= 1.0 + wr[_WD[d.weekday]] / 100.0
        return (v - 1.0) * 100.0

    outcome = np.array([compound(wr) for wr in rows], float)
    occ = np.array([all(match(d, wr[_WD[d.weekday]]) for d in out_days) for wr in rows], bool) & trig
    n_trig, n_occ = int(trig.sum()), int(occ.sum())

    # günlük istatistikler (tam haftalar) ve koşulsuz gün ortalaması (penceredeki TÜM işlem günleri)
    window_days = all_days[(all_days.index >= pd.Timestamp(start)) & (all_days.index <= pd.Timestamp(eff_end))].dropna()
    unc_mean = _r(window_days.mean()) if len(window_days) else None
    unc_med = _r(window_days.median()) if len(window_days) else None
    per_day: list[PatternDayStats] = []
    rates: list[float] = []
    for d in days:
        vals = np.array([wr[_WD[d.weekday]] for wr in rows], float)
        rate = float(np.mean([match(d, v) for v in vals]) * 100) if len(vals) else None
        if rate is not None:
            rates.append(rate / 100)
        per_day.append(PatternDayStats(
            weekday=d.weekday, expected_direction=d.direction, role=d.role, n_obs=len(vals),
            mean_return_pct=_r(vals.mean()) if len(vals) else None,
            median_return_pct=_r(np.median(vals)) if len(vals) else None,
            direction_match_rate_pct=_r(rate) if rate is not None else None,
            unconditional_mean_return_pct=unc_mean, unconditional_median_return_pct=unc_med))
    expected = _r(n_complete * float(np.prod(rates))) if n_complete else None

    cost = make_cost_model(p.transaction_cost_bps, p.slippage_bps).round_trip_cost_pct
    y = out_sign * outcome
    p_raw = permutation_pvalue(y, trig) if n_complete else None
    p_raw = round(p_raw, P_ROUND) if p_raw is not None else None  # düzeltilmiş p yuvarlanmış ham p'den türer (zarf içi tutarlılık)
    t = _t_stat(y, trig) if n_complete else None
    mean_t = _r(outcome[trig].mean()) if n_trig else None
    mean_all = _r(outcome.mean()) if n_complete else None
    result = WeekdayPeriodResult(
        window=SampleWindow(start=start, end=eff_end), n_weeks_total=n_total, n_excluded_holiday_weeks=n_holiday,
        n_excluded_incomplete_horizon=n_incomplete, n_weeks_complete=n_complete, n_trigger_weeks=n_trig,
        n_occurrences=n_occ, n_false_positive=n_trig - n_occ,
        occurrence_rate_pct=_r(n_occ / n_complete * 100) if n_complete else None,
        hit_rate_pct=_r(n_occ / n_trig * 100) if n_trig else None,
        expected_occurrences_if_independent=expected, per_day=per_day,
        outcome_mean_return_pct=mean_t, outcome_median_return_pct=_r(np.median(outcome[trig])) if n_trig else None,
        unconditional_outcome_mean_return_pct=mean_all,
        unconditional_outcome_median_return_pct=_r(np.median(outcome)) if n_complete else None,
        outcome_mean_diff_vs_unconditional_pct=_r(mean_t - mean_all) if n_trig and n_complete else None,
        cost_adjusted_outcome_mean_return_pct=_r(out_sign * mean_t - _r(cost)) if n_trig else None,
        t_stat=_r(t) if t is not None else None,
        p_value_raw=p_raw,
        p_value_adjusted=round(min(1.0, p_raw * p.n_tests_declared), P_ROUND) if p_raw is not None else None)
    return result, {"gap_only": n_gap_only}


def _handler(p: TestWeekdayPatternParams, snap: Snapshot) -> ToolOutput:
    days = sorted(p.pattern, key=lambda d: _WD[d.weekday])
    if not any(d.role == PatternRole.TRIGGER for d in days):
        raise ToolFailure("UNSUPPORTED_PATTERN", "örüntüde TRIGGER günü yok: yalnızca TRIGGER içeren örüntüler desteklenir "
                          "(TRIGGER'sız tek gün etkisi için sıfıra karşı test henüz yok)")
    out_dirs = {d.direction for d in days if d.role == PatternRole.OUTCOME}
    if len(out_dirs) > 1:
        raise ToolFailure("UNSUPPORTED_PATTERN", "OUTCOME günleri karışık yönlü (UP ve DOWN birlikte): yönlü maliyet tanımsız; "
                          "tüm OUTCOME günleri aynı yönde olmalı")
    for label, s, e in (("örneklem içi", p.in_sample_start, p.in_sample_end), ("örneklem dışı", p.out_of_sample_start, p.out_of_sample_end)):
        if s > p.as_of:
            raise ToolFailure("INVALID_WINDOW", f"{label} pencere as_of ({p.as_of}) sonrasında başlıyor ({s}): veri kullanılamaz")

    stock = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"] == p.ticker], p.as_of).sort_values("date")
    if stock.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker} için snapshot {snap.data_version} içinde as_of={p.as_of} öncesi veri yok")
    close = {ts.date(): float(c) for ts, c in zip(stock["date"], stock["adj_close"])}
    all_days = (stock.set_index("date")["adj_close"].pct_change() * 100.0)
    calendar = {ts.date() for ts in enforce_as_of(pd.DataFrame({"date": trading_calendar(snap)}), p.as_of)["date"]}
    idx = None
    if p.conditioning != Conditioning.NONE:
        ix = enforce_as_of(snap.index, p.as_of).sort_values("date")
        idx = (ix["date"].to_numpy(dtype="datetime64[D]"), ix["adj_close"].to_numpy(float))

    kw = dict(close=close, all_days=all_days, calendar=calendar, idx=idx)
    is_res, is_info = _period(p, p.in_sample_start, p.in_sample_end, **kw)
    oos_res, oos_info = _period(p, p.out_of_sample_start, p.out_of_sample_end, **kw)

    out_dir = next(d.direction for d in days if d.role == PatternRole.OUTCOME)
    verdict, codes, reason = weekday_stability_verdict(is_res, oos_res, out_dir, p.alpha)
    cm = make_cost_model(p.transaction_cost_bps, p.slippage_bps)
    label = lambda role: ",".join(f"{d.weekday.value}-{d.direction.value}" for d in days if d.role == role)  # noqa: E731
    results = TestWeekdayPatternResult(
        ticker=p.ticker, pattern_label=f"{label(PatternRole.TRIGGER)} | {label(PatternRole.OUTCOME)}",
        conditioning=p.conditioning, cost_model=cm, in_sample=is_res, out_of_sample=oos_res, stability_verdict=verdict,
        verdict_codes=codes, verdict_reason=reason,
        multiple_testing=MultipleTesting(n_tests_declared=p.n_tests_declared, alpha=p.alpha,
                                         adjusted_alpha=p.alpha / p.n_tests_declared))

    w: list[str] = []
    for label_, end in (("örneklem içi", p.in_sample_end), ("örneklem dışı", p.out_of_sample_end)):
        if end > p.as_of:
            w.append(make_warning(WarningCode.AS_OF_CLAMPED, f"{label_} bitiş {end} as_of={p.as_of} tarihine kesildi"))
    n_hol = is_res.n_excluded_holiday_weeks + oos_res.n_excluded_holiday_weeks
    n_inc = is_res.n_excluded_incomplete_horizon + oos_res.n_excluded_incomplete_horizon
    if n_hol:
        gap = is_info["gap_only"] + oos_info["gap_only"]
        w.append(make_warning(WarningCode.HOLIDAY_WEEKS_EXCLUDED,
                              f"örneklem içi {is_res.n_excluded_holiday_weeks}, dışı {oos_res.n_excluded_holiday_weeks} hafta dışlandı "
                              f"(tatil, veri boşluğu veya pencere sınırını aşan hafta; {gap} tanesi takvimde olup hissede veri yok)"))
    if n_inc:
        w.append(make_warning(WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
                              f"{n_inc} hafta as_of={p.as_of} itibarıyla tamamlanmadı (son örüntü günü as_of sonrası) ve dışlandı"))
    if verdict == StabilityVerdict.INSUFFICIENT_DATA:
        w.append(make_warning(WarningCode.FEW_EVENTS, reason))
    if verdict == StabilityVerdict.UNSTABLE:
        w.append(make_warning(WarningCode.UNSTABLE_PATTERN, reason))
    w.append(make_warning(WarningCode.MULTIPLE_TESTING_RISK,
                          f"n_tests_declared={p.n_tests_declared}; aynı veride başka örüntü/koşul denendiyse bu sayı artırılmalı "
                          f"(Bonferroni: p_düzeltilmiş = min(1, p x n_tests_declared)); beş günlük örüntü TEK birleşik testtir"))
    w.append(make_warning(WarningCode.COST_ASSUMPTIONS,
                          f"tur maliyeti {cm.round_trip_cost_pct} pp = 2 x ({cm.transaction_cost_bps_per_side} + "
                          f"{cm.slippage_bps_per_side} bps); kayma kaynaklı bir ölçüm değil, varsayımdır"))
    w.append(make_warning(WarningCode.HISTORICAL_ONLY, "Geçmiş kanıt; gelecek getiri garantisi değildir. "
                          "İlişki gözlemidir, nedensellik iddiası değildir."))
    return ToolOutput(results=results, n_events=is_res.n_occurrences + oos_res.n_occurrences,
                      n_excluded_incomplete_horizon=n_inc, warnings=w)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
