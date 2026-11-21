"""run_backtest: sinyal gecikmeli, maliyetli, benchmark'lı, IS/OOS bölünmeli geriye dönük doğrulama (+ as_of).

KAPSAM (onaylı plan; docs/data_dictionary.md §20):
  * Varyant: A (yalnızca teknik/sinyal), B (+ sektör gücü WEAK değil). C/D/E -> UNSUPPORTED_VARIANT.
  * Sinyal: CATCH_UP, WEEKDAY, REVERSAL (yalnız UZUN yönlü: BB_LOWER_TOUCH, RSI_LOCAL_TROUGH). FUNDAMENTAL -> UNSUPPORTED_SIGNAL_TYPE.
  * Parametre taraması / optimizasyon YOK: sinyal parametreleri çağırandan gelir (veri kazıma riski çağırana aittir).

ZAMANLAMA: sinyal t kapanışında yalnızca <= t verisiyle üretilir. Giriş = t + signal_lag_days kapanışı (adjusted), çıkış = giriş + holding_days
kapanışı (hissenin KENDİ barlarıyla). signal_date < entry_date <= exit_date. Aynı hissede önceki işlemin çıkış gününden ÖNCE gelen sinyal alınmaz
(çakışmasız işlem). Çıkışı dönem sonunu (min(end, as_of)) aşan sinyal sayılır ama istatistiğe girmez (n_excluded_incomplete_horizon).

MALİYET: işlem net = brüt − tur maliyeti (§5). Portföy eğrisinde maliyet, işlemin ilk ve son tutma gününe yarı yarıya yedirilir.
PORTFÖY: her gün açık pozisyonların eşit ağırlıklı ortalaması; pozisyon yoksa 0 (nakit, rf = 0).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config.settings import (
    BACKTEST_TRADE_LOG_MAX, LAG_THRESHOLD_PP_DEFAULT, MIN_EVENTS, SECTOR_STRONG_MIN_VS_XU100_PP, SECTOR_WEAK_MAX_VS_XU100_PP,
    SHARPE_ANNUALIZATION_DAYS, SHARPE_RISK_FREE_RATE,
)
from config.universe import load_universe
from schemas.common import HorizonStats, SampleWindow, make_cost_model
from schemas.enums import (
    BenchmarkName, Direction, EventFamily, PatternRole, PriceAdjustment, SignalType, SplitName, StrategyVariant, ToolName,
    WarningCode, Weekday,
)
from schemas.envelope import make_warning
from schemas.params import ConditionSet, IndicatorConfig, PatternDay, RunBacktestParams
from schemas.results import BenchmarkComparison, PerformanceMetrics, RunBacktestResult, SplitResult, Trade
from tools.calculate_indicators import _price_frame
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool
from tools.detect_reversal_events import build_events, matches_condition
from tools.rank_sector_relative_strength import leave_one_out_median  # noqa: F401  (aynı medyan ailesi; CATCH_UP tespiti dahil medyan kullanır)
from tools.stability import oos_degradation
from tools.test_weekday_pattern import _WD, _week_returns

TOOL = ToolName.RUN_BACKTEST
ROUND = 4
DEFAULT_WF_TEST_DAYS = 126
SHARPE_DEFINITION = f"günlük getiri, rf={SHARPE_RISK_FREE_RATE}, yıllıklandırma sqrt({SHARPE_ANNUALIZATION_DAYS})"
_ALLOWED_PARAMS = {
    SignalType.CATCH_UP: {"lag_window", "lag_threshold_pp", "sector_window", "wf_test_days"},
    SignalType.WEEKDAY: {"pattern", "sector_window", "wf_test_days"},
    SignalType.REVERSAL: {"event_family", "touch_mode", "condition", "sector_window", "wf_test_days"},
}
_LONG_REVERSAL = {EventFamily.BB_LOWER_TOUCH, EventFamily.RSI_LOCAL_TROUGH}


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0


# =====================================================================================================
# saf yardımcılar (testlerde doğrudan sınanır)
# =====================================================================================================
def build_trades(signal_idx: list[int], close: np.ndarray, lag: int, hold: int) -> tuple[list[tuple[int, int, int]], list[int], list[int]]:
    """Bir hisse için çakışmasız işlemler. Dönüş: ([(sinyal, giriş, çıkış) bar indeksleri, TAMAMLANMIŞ], kabul_edilen_sinyaller, dolmamış_sinyaller).
    Sinyal, önceki (kabul edilen) işlemin çıkış gününden ÖNCE geliyorsa alınmaz. Çıkış son barı aşıyorsa sinyal sayılır ama işlem yok.
    Örnek: lag=1, hold=2, sinyaller [5, 6, 7, 8]: 5 -> giriş 6, çıkış 8; 6 ve 7 çıkıştan önce (alınmaz); 8 >= 8 -> alınır."""
    last = len(close) - 1
    done: list[tuple[int, int, int]] = []
    accepted: list[int] = []
    incomplete: list[int] = []
    prev_exit = -1
    for t in sorted(set(signal_idx)):
        if t < prev_exit:
            continue
        e, x = t + lag, t + lag + hold
        accepted.append(t)
        prev_exit = x
        if x > last:
            incomplete.append(t)
            continue
        done.append((t, e, x))
    return done, accepted, incomplete


def portfolio_series(trades: list[dict], cal: pd.DatetimeIndex, cost_pct: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Günlük (brüt, net, aktif_sayısı). trade: {'dates': tutma günleri, 'rets': günlük getiri (kesir)}.
    Eşit ağırlık: gün başına açık pozisyonların ortalaması. Net: maliyet ilk ve son tutma gününe yarı yarıya (tek günlükte tamamı)."""
    pos = {d: i for i, d in enumerate(cal)}
    g = np.zeros(len(cal))
    nn = np.zeros(len(cal))
    cnt = np.zeros(len(cal))
    c = cost_pct / 100.0
    for t in trades:
        k_last = len(t["dates"]) - 1
        for k, (d, r) in enumerate(zip(t["dates"], t["rets"])):
            i = pos.get(d)
            if i is None:
                continue
            fee = (c / 2 if k == 0 else 0.0) + (c / 2 if k == k_last else 0.0)
            g[i] += r
            nn[i] += r - fee
            cnt[i] += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, g / cnt, 0.0), np.where(cnt > 0, nn / cnt, 0.0), cnt


def perf(daily: np.ndarray, trade_returns: list[float] | None, active: np.ndarray | None = None) -> PerformanceMetrics:
    """daily: günlük getiri (kesir). trade_returns: işlem getirileri (%); None = benchmark (işlem istatistiği yok)."""
    n = len(daily)
    tr = trade_returns or []
    nt = len(tr)
    base = dict(n_trades=nt, win_rate_pct=_r(100.0 * sum(1 for x in tr if x > 0) / nt) if nt else None,
                avg_trade_return_pct=_r(float(np.mean(tr))) if nt else None,
                median_trade_return_pct=_r(float(np.median(tr))) if nt else None,
                exposure_pct=_r(100.0 * float((active > 0).sum()) / n) if active is not None and n else None)
    if n == 0:
        return PerformanceMetrics(cumulative_return_pct=None, annualized_return_pct=None, sharpe_ratio=None, max_drawdown_pct=None, **base)
    equity = np.cumprod(1.0 + daily)
    cum = float(equity[-1] - 1.0)
    ann = float(equity[-1] ** (SHARPE_ANNUALIZATION_DAYS / n) - 1.0) if equity[-1] > 0 else None
    sd = float(np.std(daily, ddof=1)) if n > 1 else 0.0
    sharpe = (float(np.mean(daily)) - SHARPE_RISK_FREE_RATE / SHARPE_ANNUALIZATION_DAYS) / sd * math.sqrt(SHARPE_ANNUALIZATION_DAYS) if sd > 0 else None
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    mdd = float(np.min(equity / peak - 1.0))
    return PerformanceMetrics(
        cumulative_return_pct=_r(cum * 100), annualized_return_pct=_r(ann * 100) if ann is not None else None,
        sharpe_ratio=_r(sharpe) if sharpe is not None else None, max_drawdown_pct=_r(mdd * 100), **base)


def trade_stats(nets: list[float], grosses: list[float]) -> HorizonStats:
    """oos_degradation girdisi: n_events_complete = işlem; isabet = net > 0; mean = brüt ort.; cost_adjusted = net ort."""
    n = len(nets)
    if n == 0:
        return HorizonStats(n_events_complete=0, n_excluded_incomplete_horizon=0, n_success=0, n_false_positive=0)
    ok = sum(1 for x in nets if x > 0)
    return HorizonStats(n_events_complete=n, n_excluded_incomplete_horizon=0, n_success=ok, n_false_positive=n - ok,
                        hit_rate_pct=_r(100.0 * ok / n), false_positive_rate_pct=_r(100.0 * (n - ok) / n),
                        mean_return_pct=_r(float(np.mean(grosses))), median_return_pct=_r(float(np.median(grosses))),
                        cost_adjusted_mean_return_pct=_r(float(np.mean(nets))))


def split_windows(start: date, end: date, train_end: date | None, validation_end: date | None, walk_forward: bool,
                  cal: pd.DatetimeIndex, wf_days: int) -> list[tuple[SplitName, date, date]]:
    """Dilim pencereleri. TRAIN = [start, train_end]; VALIDATION = (train_end, validation_end]; TEST = sonrası, end'e kadar.
    walk_forward: TEST yerine, TEST başlangıcından itibaren ardışık wf_days işlem günlük WALK_FORWARD blokları (son blok kısmi olabilir)."""
    if train_end is None:
        return []
    out: list[tuple[SplitName, date, date]] = []
    te = min(train_end, end)
    if te >= start:
        out.append((SplitName.TRAIN, start, te))
    cursor = train_end
    if validation_end is not None:
        ve = min(validation_end, end)
        if ve > train_end:
            out.append((SplitName.VALIDATION, train_end + timedelta(days=1), ve))
        cursor = validation_end
    t0 = cursor + timedelta(days=1)
    if t0 > end:
        return out
    if not walk_forward:
        out.append((SplitName.TEST, t0, end))
        return out
    days = [d for d in cal if d.date() >= t0]
    for i in range(0, len(days), wf_days):
        blk = days[i:i + wf_days]
        out.append((SplitName.WALK_FORWARD, blk[0].date(), blk[-1].date()))
    return out


# =====================================================================================================
# sinyal üreticileri (her biri: hisse -> sinyal günü bar indeksleri; yalnızca <= t verisi)
# =====================================================================================================
def _check_params(spec_params: dict[str, Any], stype: SignalType) -> None:
    unknown = sorted(set(spec_params) - _ALLOWED_PARAMS[stype])
    if unknown:
        raise ToolFailure("INVALID_PARAMS", f"{stype.value} için bilinmeyen signal_params: {unknown}; geçerli: {sorted(_ALLOWED_PARAMS[stype])}")


def _catch_up_signals(wide: pd.DataFrame, sp: dict[str, Any]) -> dict[str, list[pd.Timestamp]]:
    """wide: ortak günlerde adj_close (üyeler). Laggard: lag_window getirisi − (kendisi DAHİL) üye medyanı <= −eşik."""
    L = int(sp.get("lag_window", 20))
    thr = float(sp.get("lag_threshold_pp", LAG_THRESHOLD_PP_DEFAULT))
    if L < 1 or thr <= 0:
        raise ToolFailure("INVALID_PARAMS", "lag_window >= 1 ve lag_threshold_pp > 0 olmalı")
    ret = (wide / wide.shift(L) - 1.0) * 100.0
    lag = ret.sub(ret.median(axis=1), axis=0)
    return {t: list(lag.index[(lag[t] <= -thr).to_numpy()]) for t in wide.columns}


def _weekday_signals(close: dict[date, float], dates: pd.DatetimeIndex, start: date, end: date, sp: dict[str, Any]) -> list[pd.Timestamp]:
    """Sinyal günü = son TRIGGER gününün tarihi; tüm TRIGGER günleri beklenen yönde ise. OUTCOME günleri sinyal üretmez (yalnız yön: UP)."""
    try:
        pat = sorted((PatternDay.model_validate(x) for x in sp.get("pattern", [])), key=lambda d: list(Weekday).index(d.weekday))
    except Exception as e:  # noqa: BLE001
        raise ToolFailure("INVALID_PARAMS", f"signal_params.pattern geçersiz: {e}") from e
    trig = [d for d in pat if d.role == PatternRole.TRIGGER]
    outs = [d for d in pat if d.role == PatternRole.OUTCOME]
    if not trig or not outs:
        raise ToolFailure("INVALID_PARAMS", "WEEKDAY için pattern en az bir TRIGGER ve bir OUTCOME günü içermeli")
    if any(d.direction != Direction.UP for d in outs):
        raise ToolFailure("UNSUPPORTED_DIRECTION", "yalnızca UZUN yönlü strateji desteklenir: OUTCOME günleri UP olmalı")
    wds = [_WD[d.weekday] for d in trig]
    last_wd = max(wds)
    out: list[pd.Timestamp] = []
    monday = start - timedelta(days=start.weekday())
    while monday + timedelta(days=last_wd) <= end:
        sig = monday + timedelta(days=last_wd)
        if sig >= start:
            wr = _week_returns(close, monday, wds)
            if wr is not None and all((wr[_WD[d.weekday]] > 0) == (d.direction == Direction.UP) and wr[_WD[d.weekday]] != 0 for d in trig):
                out.append(pd.Timestamp(sig))
        monday += timedelta(days=7)
    return out


def _sector_strength(snap: Snapshot, group: str, members: list[str], as_of: date, end: date, window: int) -> pd.Series:
    """Tarih -> 'STRONG'/'NEUTRAL'/'WEAK'/None. Sektör = üyelerin `window` getirisi medyanı − XU100 getirisi (aynı pencere), yalnızca <= t."""
    st = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"].isin(members)], as_of)
    wide = st.pivot(index="date", columns="ticker", values="adj_close").sort_index()
    wide = wide[wide.index <= pd.Timestamp(end)]
    xu = enforce_as_of(snap.index, as_of).set_index("date")["adj_close"].sort_index().reindex(wide.index)
    sec = ((wide / wide.shift(window) - 1.0) * 100.0).median(axis=1, skipna=True)
    rel = sec - (xu / xu.shift(window) - 1.0) * 100.0
    out = pd.Series([None] * len(rel), index=rel.index, dtype="object")
    for i, v in enumerate(rel.to_numpy()):
        if not np.isnan(v):
            out.iloc[i] = "STRONG" if v >= SECTOR_STRONG_MIN_VS_XU100_PP else ("WEAK" if v <= SECTOR_WEAK_MAX_VS_XU100_PP else "NEUTRAL")
    return out


# =====================================================================================================
# işleyici
# =====================================================================================================
def _handler(p: RunBacktestParams, snap: Snapshot) -> ToolOutput:
    s = p.strategy
    if s.variant not in (StrategyVariant.A_TECHNICAL_ONLY, StrategyVariant.B_TECHNICAL_SECTOR):
        raise ToolFailure("UNSUPPORTED_VARIANT", f"varyant {s.variant.value} desteklenmiyor: C/D/E bilanço, makro ve haber verisi gerektirir (henüz yok); desteklenen: A, B")
    if s.signal_type == SignalType.FUNDAMENTAL:
        raise ToolFailure("UNSUPPORTED_SIGNAL_TYPE", "FUNDAMENTAL sinyali bilanço verisi gerektirir (henüz yok); desteklenen: CATCH_UP, WEEKDAY, REVERSAL")
    sp = dict(s.signal_params)
    _check_params(sp, s.signal_type)
    if s.walk_forward and s.train_end is None:
        raise ToolFailure("INVALID_PARAMS", "walk_forward=True için strategy.train_end gerekli (ilk eğitim penceresinin sonu)")
    if p.start > p.as_of:
        raise ToolFailure("INVALID_WINDOW", f"start ({p.start}) as_of ({p.as_of}) sonrasında: veri kullanılamaz")

    eff_end = min(p.end, p.as_of)
    ts_end = pd.Timestamp(eff_end)
    universe = list(p.universe)
    have = set(snap.stocks["ticker"].unique())
    missing = [t for t in universe if t not in have]
    if missing:
        raise ToolFailure("NO_DATA", f"{', '.join(missing)} için snapshot {snap.data_version} içinde veri yok")

    uni = load_universe().set_index("ticker")
    group_of = {t: str(uni.loc[t, "peer_group"]) if t in uni.index else None for t in universe}
    cost = make_cost_model(s.transaction_cost_bps, s.slippage_bps)
    lag, hold = s.signal_lag_days, s.holding_days

    # fiyatlar: as_of'a, sonra dönem sonuna kesilmiş (nedensel; dönem sonrası bar hiçbir hesaba girmez)
    px: dict[str, pd.DataFrame] = {}
    for t in universe:
        f = _price_frame(enforce_as_of(snap.stocks.loc[snap.stocks["ticker"] == t], p.as_of), PriceAdjustment.ADJUSTED)
        px[t] = f.loc[f.index <= ts_end]
        if px[t].empty:
            raise ToolFailure("NO_DATA", f"{t}: as_of={p.as_of} öncesi veri yok")

    # --- sinyaller (hisse -> bar indeksleri) -------------------------------------------------------
    sig_ts: dict[str, list[pd.Timestamp]] = {}
    if s.signal_type == SignalType.CATCH_UP:
        if len(universe) < 2:
            raise ToolFailure("INVALID_PARAMS", "CATCH_UP için evren en az 2 hisse içermeli (peer medyanı)")
        wide = pd.DataFrame({t: px[t]["close"] for t in universe}).dropna().sort_index()
        sig_ts = _catch_up_signals(wide, sp)
    elif s.signal_type == SignalType.WEEKDAY:
        for t in universe:
            close_map = {ts.date(): float(c) for ts, c in px[t]["close"].items()}
            sig_ts[t] = _weekday_signals(close_map, px[t].index, p.start, eff_end, sp)
    else:
        fam = EventFamily(sp.get("event_family", "BB_LOWER_TOUCH"))
        if fam not in _LONG_REVERSAL:
            raise ToolFailure("UNSUPPORTED_DIRECTION" if fam in {EventFamily.BB_UPPER_TOUCH, EventFamily.RSI_LOCAL_PEAK} else "UNSUPPORTED_EVENT_FAMILY",
                              f"REVERSAL sinyali için {fam.value} desteklenmiyor; desteklenen (uzun yönlü): {sorted(f.value for f in _LONG_REVERSAL)}")
        cond = ConditionSet.model_validate({"label": "cond", **sp["condition"]}) if sp.get("condition") else None
        for t in universe:
            es = build_events(px[t], IndicatorConfig(), fam, str(sp.get("touch_mode", "close")), p.start)
            sig_ts[t] = [px[t].index[i] for i in es.ev_idx if cond is None or matches_condition(cond, es.states_at(i))]

    warnings: list[str] = []
    # --- B: sektör filtresi --------------------------------------------------------------------------
    n_sector_dropped = 0
    if s.variant == StrategyVariant.B_TECHNICAL_SECTOR:
        window = int(sp.get("sector_window", 20))
        cache: dict[str, pd.Series] = {}
        for t in universe:
            g = group_of[t]
            members = sorted(uni.index[uni["peer_group"] == g]) if g else []
            if not g or len(members) < 2:
                warnings.append(make_warning(WarningCode.SOLO_PEER_GROUP, f"{t}: tek hisseli grup; sektör filtresi uygulanmadı"))
                continue
            if g not in cache:
                cache[g] = _sector_strength(snap, g, members, p.as_of, eff_end, window)
            strength = cache[g]
            kept = [d for d in sig_ts[t] if strength.get(d) in ("STRONG", "NEUTRAL")]
            n_sector_dropped += len(sig_ts[t]) - len(kept)
            sig_ts[t] = kept

    # --- işlemler ---------------------------------------------------------------------------------
    trades: list[dict[str, Any]] = []
    n_signals = n_incomplete = n_ignored = 0
    acc_dates: list[date] = []  # kabul edilen tüm sinyallerin tarihi (dilim sayımı için)
    for t in universe:
        idx_all = px[t].index
        cl = px[t]["close"].to_numpy(float)
        sig_idx = [int(idx_all.get_loc(d)) for d in sig_ts.get(t, []) if p.start <= d.date() <= eff_end and d in idx_all]
        done, acc, inc = build_trades(sig_idx, cl, lag, hold)
        n_signals += len(acc)
        n_incomplete += len(inc)
        n_ignored += len(set(sig_idx)) - len(acc)
        acc_dates += [idx_all[i].date() for i in acc]
        for si, ei, xi in done:
            gross = (cl[xi] / cl[ei] - 1.0) * 100.0
            gross_r = _r(gross)
            trades.append({
                "ticker": t, "signal_date": idx_all[si].date(), "entry_date": idx_all[ei].date(), "exit_date": idx_all[xi].date(),
                "gross": gross_r, "net": _r(gross_r - cost.round_trip_cost_pct),
                "dates": list(idx_all[ei + 1:xi + 1]), "rets": list(cl[ei + 1:xi + 1] / cl[ei:xi] - 1.0)})
    trades.sort(key=lambda x: (x["entry_date"], x["ticker"]))

    cal = pd.DatetimeIndex(sorted({d for t in universe for d in px[t].index if d >= pd.Timestamp(p.start)}))
    g_d, n_d, cnt = portfolio_series(trades, cal, cost.round_trip_cost_pct)
    nets, grosses = [x["net"] for x in trades], [x["gross"] for x in trades]
    strat_gross = perf(g_d, grosses, cnt)
    strat_net = perf(n_d, nets, cnt)

    # --- benchmark'lar ----------------------------------------------------------------------------
    def stock_ret(t: str) -> pd.Series:
        return px[t]["close"].pct_change().reindex(cal)

    bench_daily: dict[BenchmarkName, np.ndarray] = {}
    for b in s.benchmarks:
        if b == BenchmarkName.BUY_AND_HOLD:
            bench_daily[b] = np.nan_to_num(pd.DataFrame({t: stock_ret(t) for t in universe}).mean(axis=1, skipna=True).to_numpy(), nan=0.0)
        elif b == BenchmarkName.XU100:
            xu = enforce_as_of(snap.index, p.as_of).set_index("date")["adj_close"].sort_index()
            xu = xu[xu.index <= ts_end]
            bench_daily[b] = np.nan_to_num(xu.pct_change().reindex(cal).to_numpy(), nan=0.0)
        else:
            groups = {group_of[t] for t in universe}
            if len(groups) != 1 or None in groups:
                raise ToolFailure("INVALID_PARAMS", "SECTOR benchmark'ı için evren tek bir peer grubunda olmalı")
            g = next(iter(groups))
            members = sorted(uni.index[uni["peer_group"] == g])
            st = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"].isin(members)], p.as_of)
            wide_m = st.pivot(index="date", columns="ticker", values="adj_close").sort_index()
            wide_m = wide_m[wide_m.index <= ts_end]
            bench_daily[b] = np.nan_to_num(wide_m.pct_change().median(axis=1, skipna=True).reindex(cal).to_numpy(), nan=0.0)
            if len(members) < 3:
                warnings.append(make_warning(WarningCode.SMALL_PEER_GROUP if len(members) == 2 else WarningCode.SOLO_PEER_GROUP,
                                             f"SECTOR benchmark: {g} grubunda {len(members)} üye"))
    benchmarks = []
    for b in s.benchmarks:
        m = perf(bench_daily[b], None)
        benchmarks.append(BenchmarkComparison(
            name=b, metrics=m,
            cumulative_return_diff_pct=_diff(strat_net.cumulative_return_pct, m.cumulative_return_pct),
            sharpe_diff=_diff(strat_net.sharpe_ratio, m.sharpe_ratio)))
    first_b = s.benchmarks[0]

    # --- bölünmeler ------------------------------------------------------------------------------
    wins = split_windows(p.start, eff_end, s.train_end, s.validation_end, s.walk_forward, cal, int(sp.get("wf_test_days", DEFAULT_WF_TEST_DAYS)))
    splits: list[SplitResult] = []
    for name, ws, we in wins:
        mask = (cal >= pd.Timestamp(ws)) & (cal <= pd.Timestamp(we))
        sub = [x for x in trades if ws <= x["signal_date"] <= we]
        n_sig = sum(1 for d in acc_dates if ws <= d <= we)  # dilimde sinyal tarihi olan kabul edilmiş sinyaller (dolmamışlar dahil)
        m = perf(n_d[mask], [x["net"] for x in sub], cnt[mask])
        bm = perf(bench_daily[first_b][mask], None)
        splits.append(SplitResult(name=name, window=SampleWindow(start=ws, end=we), n_signals=n_sig, net_metrics=m,
                                  benchmark_diff_pct=_diff(m.cumulative_return_pct, bm.cumulative_return_pct)))

    # --- oos_degradation (§9): IS = TRAIN(+VALIDATION), OOS = sonrası -----------------------------------
    flag: bool | None = None
    if s.train_end is not None:
        is_end = s.validation_end or s.train_end
        a = [x for x in trades if x["signal_date"] <= is_end]
        b_ = [x for x in trades if x["signal_date"] > is_end]
        flag, too_small = oos_degradation(trade_stats([x["net"] for x in a], [x["gross"] for x in a]),
                                          trade_stats([x["net"] for x in b_], [x["gross"] for x in b_]))
        if too_small:
            warnings.append(make_warning(WarningCode.OOS_TOO_SMALL, f"OOS işlem sayısı {len(b_)} < MIN_OOS_EVENTS; oos_degradation_flag=false"))
        elif flag:
            warnings.append(make_warning(WarningCode.OOS_DEGRADATION, f"OOS performansı bozuldu (IS {len(a)} işlem, OOS {len(b_)} işlem)"))

    n_win = sum(1 for x in nets if x > 0)
    last_exit = max((x["exit_date"] for x in trades), default=None)
    log = trades[-BACKTEST_TRADE_LOG_MAX:]
    res = RunBacktestResult(
        strategy=s, universe=universe, period=SampleWindow(start=p.start, end=eff_end), signal_lag_days_applied=lag, cost_model=cost,
        sharpe_definition=SHARPE_DEFINITION, n_signals=n_signals, n_excluded_incomplete_horizon=n_incomplete, n_winning_trades=n_win,
        n_losing_trades=len(nets) - n_win, strategy_gross=strat_gross, strategy_net=strat_net, benchmarks=benchmarks, splits=splits,
        oos_degradation_flag=flag, low_signal_flag=n_signals < MIN_EVENTS,
        trade_log=[Trade(ticker=x["ticker"], signal_date=x["signal_date"], entry_date=x["entry_date"], exit_date=x["exit_date"],
                         gross_return_pct=x["gross"], net_return_pct=x["net"]) for x in log],
        trade_log_truncated=len(trades) > len(log), last_exit_date=last_exit)

    if n_signals < MIN_EVENTS:
        warnings.append(make_warning(WarningCode.LOW_SIGNAL_COUNT, f"n_signals={n_signals} < MIN_EVENTS={MIN_EVENTS}; az sinyalden gelen getiri güvenilir değildir"))
    if n_incomplete:
        warnings.append(make_warning(WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
                                     f"{n_incomplete} sinyalin çıkışı dönem sonunu ({eff_end}) aşıyor; sayıldı, istatistiğe katılmadı"))
    warnings.append(make_warning(WarningCode.COST_ASSUMPTIONS,
                                 f"tur maliyeti {cost.round_trip_cost_pct} pp = 2 x ({cost.transaction_cost_bps_per_side} + {cost.slippage_bps_per_side} bps); "
                                 f"kayma varsayımdır; giriş/çıkış adjusted kapanışta, borç/vergi yok, yalnızca uzun yön"))
    warnings.append(make_warning(WarningCode.MULTIPLE_TESTING_RISK,
                                 "araç parametre taraması yapmaz; aynı veride birden çok strateji/parametre denendiyse seçim yanlılığı oluşur ve sonuç iyimser olur"))
    warnings.append(make_warning(WarningCode.HISTORICAL_ONLY,
                                 f"Geçmiş kanıt; gelecek getiri garantisi değildir. {n_ignored} sinyal açık pozisyon nedeniyle alınmadı"
                                 + (f"; {n_sector_dropped} sinyal sektör filtresiyle elendi" if n_sector_dropped else "")))
    return ToolOutput(results=res, n_events=n_signals, n_excluded_incomplete_horizon=n_incomplete, warnings=warnings)


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else _r(a - b)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
