"""detect_reversal_events: teknik dönüş olayları, ileri getiriler, tekli ve birleşik koşul karşılaştırması (+ as_of).

KAPSAM: tek yönlü dört aile (BB_LOWER_TOUCH, BB_UPPER_TOUCH, RSI_LOCAL_TROUGH, RSI_LOCAL_PEAK). Karışık yönlü aileler
`UNSUPPORTED_EVENT_FAMILY` döner (docs/schema_wishlist.md §11: event_direction önerisi).

TANIMLAR (docs/data_dictionary.md §19):
  * Ham olay günü: Bollinger'da temas günü (§4, `touch_mode`); RSI'da "yerel dip/zirve teyit günü" (aşağıda).
  * OLAY = ardışık ham gün serisinin İLK günü (seri, o gün öncesinde ham gün yoksa başlar). Ham gün sayısı `n_raw_event_days`.
  * RSI durumu (w = 5, TEYİT GÜNÜ olay günüdür): `RSI[t-1]`, `RSI[t-w..t-1]` pencerenin en küçüğü ve `RSI[t] > RSI[t-1]` ise LOCAL_LOW;
    `RSI[t-1]` pencerenin en büyüğü ve `RSI[t] < RSI[t-1]` ise LOCAL_HIGH; aksi NEUTRAL. t günü yalnızca <= t verisini kullanır.
  * İleri getiri: olay günü kapanışından t+h kapanışına (adjusted). Başarı: beklenen yönde > 0 (eşitlik başarı değil).
    MFE (`reversal_strength_pct`): t+1..t+h kapanışları boyunca beklenen yönde en büyük hareket, en az 0.
  * İstatistikler (HorizonStats) YÖNLÜDÜR: DOWN beklentisinde getiri işareti çevrilir (pozitif = beklenen yönde).
    `ForwardReturn.return_pct` ham getiridir (işaret çevrilmez).
  * Baz: aynı dönem (t >= analysis_start), aynı ufuk, tüm günler (yönlü getiri).
  * Birleşik koşul: olayın KENDİ gününde gösterge durumları (olay, koşuldan bağımsız belirlenir; koşul olayı süzer).
  * Rejim kırılımı (en uzun ufuk): XU100_UP/DOWN = olay gününe kadar son 20 işlem günü XU100 getirisi > 0 / <= 0;
    HIGH/LOW_VOLATILITY = hissenin 20 günlük volatilitesi, o güne kadarki (bugün dahil) tüm 20 günlük volatiliteler medyanının üstünde/altında.
Ağ yok; as_of sonrası satır hiçbir hesaba girmez.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import (
    KAMA_FLAT_SLOPE_PCT, MIN_EVENTS, VOLATILITY_WINDOW, VOLUME_HIGH_Z, VOLUME_LOW_Z,
)
from schemas.common import BaselineStats, HorizonBlock, HorizonStats, MultipleTesting, make_cost_model
from schemas.enums import (
    Direction, EventFamily, IndicatorName, MarketRegime, PriceAdjustment, RsiState, ToolName, WarningCode,
)
from schemas.envelope import make_warning
from schemas.params import ConditionSet, DetectReversalEventsParams
from schemas.results import (
    DetectReversalEventsResult, EventStates, ForwardReturn, RegimeBreakdown, ReversalEventRecord, ReversalGroup,
)
from tools.calculate_indicators import _price_frame
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool
from tools.indicators.catalog import compute
from tools.stability import oos_degradation

TOOL = ToolName.DETECT_REVERSAL_EVENTS
ROUND = 4
RSI_LOCAL_WINDOW = 5      # docs/calibration_thresholds.md: getirilere bakılmadan seçildi
REGIME_WINDOW = VOLATILITY_WINDOW  # 20 işlem günü
MAX_EVENTS_LISTED = 100
SINGLE_LABEL = "single_indicator"
SUPPORTED = {
    EventFamily.BB_LOWER_TOUCH: Direction.UP, EventFamily.BB_UPPER_TOUCH: Direction.DOWN,
    EventFamily.RSI_LOCAL_TROUGH: Direction.UP, EventFamily.RSI_LOCAL_PEAK: Direction.DOWN,
}
_ALL_IND = [IndicatorName.BOLLINGER, IndicatorName.RSI, IndicatorName.SUPERTREND, IndicatorName.KAMA,
            IndicatorName.ICHIMOKU, IndicatorName.VOLUME_ZSCORE]


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0


# =====================================================================================================
# saf yardımcılar (testlerde doğrudan sınanır)
# =====================================================================================================
def rsi_local_state(rsi: np.ndarray, w: int = RSI_LOCAL_WINDOW) -> list[RsiState | None]:
    """Gün başına RSI durumu (teyit günü). Örnek (w=3): rsi=[50,40,30,35] -> t=3: RSI[2]=30 son 3 değerin (50,40,30) en küçüğü
    ve RSI[3]=35 > 30 -> LOCAL_LOW. t < w veya pencerede NaN varsa None."""
    out: list[RsiState | None] = []
    for t in range(len(rsi)):
        if t < w:
            out.append(None)
            continue
        win, cur = rsi[t - w:t], rsi[t]
        if np.isnan(win).any() or np.isnan(cur):
            out.append(None)
            continue
        prev = win[-1]
        if prev == win.min() and cur > prev:
            out.append(RsiState.LOCAL_LOW)
        elif prev == win.max() and cur < prev:
            out.append(RsiState.LOCAL_HIGH)
        else:
            out.append(RsiState.NEUTRAL)
    return out


def series_starts(raw: np.ndarray) -> list[tuple[int, int]]:
    """Ardışık True serileri: (ilk gün indeksi, uzunluk). Örnek: [F,T,T,F,T] -> [(1, 2), (4, 1)]."""
    out: list[tuple[int, int]] = []
    i, n = 0, len(raw)
    while i < n:
        if raw[i]:
            j = i
            while j + 1 < n and raw[j + 1]:
                j += 1
            out.append((i, j - i + 1))
            i = j + 1
        else:
            i += 1
    return out


def count_overlapping(event_idx: list[int], max_horizon: int) -> int:
    """Bir sonraki olay en fazla max_horizon işlem günü sonraysa (ileri penceresi çakışır) sayılır. Son olay sayılmaz."""
    ev = sorted(event_idx)
    return sum(1 for a, b in zip(ev, ev[1:]) if b - a <= max_horizon)


def forward(close: np.ndarray, t: int, h: int, sign: float) -> tuple[float, float, float] | None:
    """(ham getiri %, yönlü getiri %, MFE %) ya da ufuk veri sonunu aşıyorsa None.
    MFE = max(0, max_k sign x (close[t+k]/close[t] - 1) x 100, k = 1..h)."""
    if t + h > len(close) - 1:
        return None
    path = (close[t + 1:t + h + 1] / close[t] - 1.0) * 100.0
    raw = float(path[-1])
    return raw, sign * raw, max(0.0, float(np.max(sign * path)))


def _hstats(dirret: list[float], mfe: list[float], n_excl: int, cost: float) -> HorizonStats:
    n = len(dirret)
    if n == 0:
        return HorizonStats(n_events_complete=0, n_excluded_incomplete_horizon=n_excl, n_success=0, n_false_positive=0)
    a = np.array(dirret)
    ok = int((a > 0).sum())
    mean = _r(float(a.mean()))
    return HorizonStats(
        n_events_complete=n, n_excluded_incomplete_horizon=n_excl, n_success=ok, n_false_positive=n - ok,
        hit_rate_pct=_r(100.0 * ok / n), false_positive_rate_pct=_r(100.0 * (n - ok) / n), mean_return_pct=mean,
        median_return_pct=_r(float(np.median(a))), cost_adjusted_mean_return_pct=_r(mean - cost),
        mean_reversal_strength_pct=_r(float(np.mean(mfe))), median_reversal_strength_pct=_r(float(np.median(mfe))))


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else _r(a - b)


def _matches(cond: ConditionSet, st: dict[str, object]) -> bool:
    pairs = ((cond.rsi_state, st["rsi"]), (cond.supertrend_state, st["supertrend"]), (cond.ichimoku_state, st["ichimoku"]),
             (cond.volume_regime, st["volume"]), (cond.kama_slope, st["kama_slope"]))
    return all(want is None or want == have for want, have in pairs)


# =====================================================================================================
# işleyici
# =====================================================================================================
def _handler(p: DetectReversalEventsParams, snap: Snapshot) -> ToolOutput:
    if p.event_family not in SUPPORTED:
        raise ToolFailure("UNSUPPORTED_EVENT_FAMILY",
                          f"{p.event_family.value} desteklenmiyor: olayları hem yukarı hem aşağı yönlü olabilen aileler için tek bir "
                          f"expected_direction tanımsız; desteklenenler: {sorted(f.value for f in SUPPORTED)} (öneri: event_direction parametresi)")
    labels = [c.label for c in p.condition_sets]
    if SINGLE_LABEL in labels or len(set(labels)) != len(labels):
        raise ToolFailure("INVALID_PARAMS", f"condition_sets etiketleri tekil olmalı ve '{SINGLE_LABEL}' kullanılamaz")
    frame = snap.stocks.loc[snap.stocks["ticker"] == p.ticker]
    if frame.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker} için snapshot {snap.data_version} içinde veri yok")

    direction = SUPPORTED[p.event_family]
    sign = 1.0 if direction == Direction.UP else -1.0
    horizons = list(p.forward_horizons)
    H = max(horizons)
    cost = make_cost_model(p.transaction_cost_bps, p.slippage_bps)

    px = _price_frame(enforce_as_of(frame, p.as_of), PriceAdjustment.ADJUSTED)
    n = len(px)
    dates = px.index
    close = px["close"].to_numpy(float)
    try:
        comp = compute(px, p.indicator_config, _ALL_IND, kama_flat_pct=KAMA_FLAT_SLOPE_PCT,
                       volume_high_z=VOLUME_HIGH_Z, volume_low_z=VOLUME_LOW_Z)
    except ValueError as e:
        raise ToolFailure("INVALID_PARAMS", f"gösterge config geçersiz: {e}") from e
    col = {c.name: c.values.to_numpy(float) for c in comp.columns}

    def pick(prefix: str) -> np.ndarray:
        return col[next(k for k in col if k.startswith(prefix))]

    lower, upper, rsi = pick("BB_LOWER_"), pick("BB_UPPER_"), pick(f"RSI_")
    rsi_state = rsi_local_state(rsi)
    st = {k: v.tolist() for k, v in comp.states.items()}

    # ham olay günleri
    low, high = px["low"].to_numpy(float), px["high"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        if p.event_family == EventFamily.BB_LOWER_TOUCH:
            raw = (close if p.touch_mode.value == "close" else low) <= lower
        elif p.event_family == EventFamily.BB_UPPER_TOUCH:
            raw = (close if p.touch_mode.value == "close" else high) >= upper
        elif p.event_family == EventFamily.RSI_LOCAL_TROUGH:
            raw = np.array([s == RsiState.LOCAL_LOW for s in rsi_state])
        else:
            raw = np.array([s == RsiState.LOCAL_HIGH for s in rsi_state])
    raw = np.asarray(raw, bool) & ~np.isnan(lower) if p.event_family in (EventFamily.BB_LOWER_TOUCH, EventFamily.BB_UPPER_TOUCH) else raw

    a_start = int(np.searchsorted(dates.to_numpy(), np.datetime64(p.analysis_start), side="left"))
    series = [(i, ln) for i, ln in series_starts(raw) if i >= a_start]
    ev_idx = [i for i, _ in series]
    ln_of = dict(series)

    def states_at(i: int) -> dict[str, object]:
        return {"rsi": rsi_state[i], "supertrend": st.get("supertrend", [None] * n)[i], "kama_slope": st.get("kama_slope", [None] * n)[i],
                "ichimoku": st.get("ichimoku_position", [None] * n)[i], "volume": st.get("volume_regime", [None] * n)[i]}

    # rejim bayrakları (nedensel)
    xu = enforce_as_of(snap.index, p.as_of).set_index("date")["adj_close"].sort_index()
    xu_ret = (xu / xu.shift(REGIME_WINDOW) - 1.0).reindex(dates)
    vol = pd.Series(close, index=dates).pct_change().rolling(REGIME_WINDOW).std(ddof=1)
    vol_med = vol.expanding().median()
    regime_of: dict[int, set[MarketRegime]] = {}
    for i in ev_idx:
        s: set[MarketRegime] = set()
        xr = xu_ret.iloc[i]
        if not np.isnan(xr):
            s.add(MarketRegime.XU100_UP if xr > 0 else MarketRegime.XU100_DOWN)
        if not np.isnan(vol.iloc[i]) and not np.isnan(vol_med.iloc[i]):
            s.add(MarketRegime.HIGH_VOLATILITY if vol.iloc[i] > vol_med.iloc[i] else MarketRegime.LOW_VOLATILITY)
        regime_of[i] = s

    # baz (yönlü, tüm günler)
    baselines: dict[int, BaselineStats] = {}
    for h in horizons:
        ex = [sign * (close[t + h] / close[t] - 1.0) * 100.0 for t in range(a_start, n - h)]
        baselines[h] = (BaselineStats(n_obs=len(ex), mean_return_pct=_r(float(np.mean(ex))), median_return_pct=_r(float(np.median(ex))),
                                      hit_rate_pct=_r(100.0 * sum(1 for x in ex if x > 0) / len(ex)))
                        if ex else BaselineStats(n_obs=0))

    split = pd.Timestamp(p.split_date) if p.split_date else None
    warn_oos: dict[tuple[WarningCode, str], list[str]] = {}  # (kod, grup etiketi) -> ufuk açıklamaları
    warn_few: list[str] = []
    groups: list[ReversalGroup] = []
    candidates: list[tuple[str, ConditionSet | None, list[int]]] = [(SINGLE_LABEL, None, ev_idx)]
    for c in p.condition_sets:
        candidates.append((c.label, c, [i for i in ev_idx if _matches(c, states_at(i))]))

    for label, cond, idxs in candidates:
        fwd = {i: {h: forward(close, i, h, sign) for h in horizons} for i in idxs}
        blocks: list[HorizonBlock] = []
        for h in horizons:
            def sel(pred) -> HorizonStats:
                done = [i for i in idxs if pred(i) and fwd[i][h] is not None]
                n_ex = sum(1 for i in idxs if pred(i) and fwd[i][h] is None)
                return _hstats([fwd[i][h][1] for i in done], [fwd[i][h][2] for i in done], n_ex, cost.round_trip_cost_pct)  # type: ignore[index]
            full = sel(lambda i: True)
            is_s = oos_s = flag = None
            if split is not None:
                is_s, oos_s = sel(lambda i: dates[i] < split), sel(lambda i: dates[i] >= split)
                flag, too_small = oos_degradation(is_s, oos_s)
                if too_small:
                    warn_oos.setdefault((WarningCode.OOS_TOO_SMALL, label), []).append(f"h={h}: n={oos_s.n_events_complete}")
                elif flag:
                    warn_oos.setdefault((WarningCode.OOS_DEGRADATION, label), []).append(
                        f"h={h}: IS isabet {is_s.hit_rate_pct}%, OOS {oos_s.hit_rate_pct}%")
            base = baselines[h]
            blocks.append(HorizonBlock(
                horizon=h, full=full, in_sample=is_s, out_of_sample=oos_s, baseline=base,
                mean_diff_vs_baseline_pct=_diff(full.mean_return_pct, base.mean_return_pct),
                median_diff_vs_baseline_pct=_diff(full.median_return_pct, base.median_return_pct), oos_degradation_flag=flag))
        # rejim kırılımı (en uzun ufuk)
        rb: list[RegimeBreakdown] = []
        for reg in MarketRegime:
            rows = [fwd[i][H][1] for i in idxs if reg in regime_of[i] and fwd[i][H] is not None]  # type: ignore[index]
            rb.append(RegimeBreakdown(
                regime=reg, horizon=H, n_events=len(rows),
                hit_rate_pct=_r(100.0 * sum(1 for x in rows if x > 0) / len(rows)) if rows else None,
                mean_return_pct=_r(float(np.mean(rows))) if rows else None))
        listed = idxs[-MAX_EVENTS_LISTED:]
        records = []
        for i in listed:
            f = []
            for h in horizons:
                x = fwd[i][h]
                f.append(ForwardReturn(horizon=h, complete=False, return_pct=None) if x is None else
                         ForwardReturn(horizon=h, complete=True, return_pct=_r(x[0]), reversal_success=x[1] > 0,
                                       reversal_strength_pct=_r(x[2])))
            s = states_at(i)
            records.append(ReversalEventRecord(date=dates[i].date(), close=_r(close[i]), states=EventStates(**s), forward_returns=f))
        n_det = len(idxs)
        if n_det < MIN_EVENTS:
            warn_few.append(f"{label}: n_events_detected={n_det} < MIN_EVENTS={MIN_EVENTS}")
        groups.append(ReversalGroup(
            label=label, conditions=cond, n_events_detected=n_det, per_horizon=blocks, regime_breakdown=rb, events=records,
            events_truncated=len(idxs) > MAX_EVENTS_LISTED, n_raw_event_days=sum(ln_of[i] for i in idxs),
            n_overlapping_forward_windows=count_overlapping(idxs, H)))

    uncond = groups[0]
    longest = next(b for b in uncond.per_horizon if b.horizon == H)
    n_excl = longest.full.n_excluded_incomplete_horizon
    res = DetectReversalEventsResult(
        ticker=p.ticker, event_family=p.event_family, touch_mode=p.touch_mode, expected_direction=direction,
        analysis_start=p.analysis_start, analysis_end=dates[-1].date() if n else p.analysis_start, split_date=p.split_date,
        cost_model=cost, groups=groups,
        multiple_testing=MultipleTesting(n_tests_declared=p.n_tests_declared, alpha=0.05, adjusted_alpha=0.05 / p.n_tests_declared))

    w: list[str] = [make_warning(WarningCode.FEW_EVENTS, m) for m in warn_few]
    if n_excl:
        per_h = ", ".join(f"h={b.horizon}: {b.full.n_excluded_incomplete_horizon}" for b in uncond.per_horizon)
        w.append(make_warning(WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
                              f"ufku as_of={p.as_of} içinde dolmamış olaylar ilgili ufkun istatistiğine katılmadı (koşulsuz grup: {per_h})"))
    for (code, label), items in warn_oos.items():
        what = "OOS tamamlanmış olay sayısı MIN_OOS_EVENTS altında" if code == WarningCode.OOS_TOO_SMALL else "OOS bozulması"
        w.append(make_warning(code, f"{label}: {what} ({'; '.join(items)})"))
    w.append(make_warning(WarningCode.MULTIPLE_TESTING_RISK,
                          f"n_tests_declared={p.n_tests_declared}; {len(p.condition_sets)} birleşik koşul aynı olay kümesinde ek karşılaştırmadır "
                          f"(çağıran sayıyı beyan eder; Bonferroni alpha/n). Bu araç p-değeri üretmez"))
    w.append(make_warning(WarningCode.COST_ASSUMPTIONS,
                          f"tur maliyeti {cost.round_trip_cost_pct} pp = 2 x ({cost.transaction_cost_bps_per_side} + "
                          f"{cost.slippage_bps_per_side} bps); kayma varsayımdır. Olay kapanıştan ölçülür (işlem varsayımı değil)"))
    w.append(make_warning(WarningCode.HISTORICAL_ONLY,
                          f"Geçmiş kanıt; gelecek getiri garantisi değildir. Koşulsuz grupta {uncond.n_raw_event_days} ham olay gününden "
                          f"{uncond.n_events_detected} olay (ardışık serinin ilk günü); {uncond.n_overlapping_forward_windows} olayın ileri penceresi "
                          f"bir sonraki olayla çakışıyor, bu yüzden olaylar tam bağımsız değildir"))
    w.append(make_warning(WarningCode.ASSOCIATION_NOT_CAUSATION, "Olay sonrası getiri ilişki gözlemidir; nedensellik iddiası değildir"))
    return ToolOutput(results=res, n_events=uncond.n_events_detected, n_excluded_incomplete_horizon=n_excl, warnings=w)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
