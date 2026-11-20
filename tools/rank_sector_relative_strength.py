"""rank_sector_relative_strength: peer grubu + lag penceresi (+ as_of) -> hisse sıralaması ve tarihsel catch-up istatistiği.

İKİ AYRI MEDYAN TANIMI (docs/data_dictionary.md §14):
  * TESPİT (lag skoru, is_laggard/is_leader, sector_median): grubun TÜM üyeleri DAHİL (kendisi dahil) peer medyanı.
    Şema tanımı budur (`benchmark_definition.includes_subject_stock = true`).
  * SONUÇ (tarihsel ileri getiri farkı, `excess`): hisse getirisi - KENDİSİ HARİÇ diğer üyelerin medyanı (leave-one-out).
    Kendisi dahil medyan, 3 hisseli grupta başarıyı "grubun en iyisi olmak"a indirir (baz isabet oranı ~%33).

Bağımsızlaştırma: aynı hissede ardışık günlerde geride kalma, ileri pencereleri örtüştürüp olay sayısını şişirir. Her hissede
kabul edilen bir olaydan sonra `max(forward_horizons)` işlem günü yeni olay kabul edilmez (cooldown).

as_of'tan sonra hiçbir satır hesaba girmez (enforce_as_of). Ağ yok; yalnızca snapshot okur.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import (
    MIN_EVENTS,
    SECTOR_STRONG_MIN_VS_XU100_PP,
    SECTOR_WEAK_MAX_VS_XU100_PP,
)
from config.universe import load_universe
from schemas.common import (
    BaselineStats,
    BenchmarkDefinition,
    HorizonBlock,
    HorizonStats,
    make_cost_model,
)
from schemas.enums import SectorStrength, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import RankSectorRelativeStrengthParams
from schemas.results import CatchUpHorizon, RankingRow, RankSectorRelativeStrengthResult, StrengthThresholds
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool, trading_calendar
from tools.stability import oos_degradation

TOOL = ToolName.RANK_SECTOR_RELATIVE_STRENGTH
ROUND = 4  # zarfta getiriler 4 ondalık; tüm türetilmiş sayılar yuvarlanmış girdilerden hesaplanır (zarf içi tutarlılık)
MAX_LISTED_DAYS = 5


def _r(x: float) -> float:
    return float(np.round(x, ROUND)) + 0.0  # "+ 0.0": -0.0 -> 0.0 (JSON'da "-0.0" çıkmasın)


# =====================================================================================================
# saf yardımcılar (testlerde doğrudan sınanır)
# =====================================================================================================
def leave_one_out_median(m: np.ndarray) -> np.ndarray:
    """Her (satır, sütun) için o sütun HARİÇ diğer sütunların medyanı. m: (T, n), n >= 2.

    Örnek: [[6, 4, 1]] -> [[2.5, 3.5, 5.0]] (4 için diğerleri 6 ve 1 -> medyan 3,5)."""
    if m.ndim != 2 or m.shape[1] < 2:
        raise ValueError("leave_one_out_median en az 2 sütun ister")
    out = np.empty(m.shape, dtype=float)
    for i in range(m.shape[1]):
        out[:, i] = np.median(np.delete(m, i, axis=1), axis=1)
    return out


def independent_events(laggard: np.ndarray, first_t: int, last_t: int, cooldown: int) -> list[tuple[int, int]]:
    """Örtüşmeyen olaylar. laggard: (T, n) bool. Her sütun (hisse) için t = first_t..last_t kronolojik taranır;
    laggard[t, i] doğruysa ve t >= (son kabul edilen olay + cooldown) ise olay kabul edilir. Dönüş: (t, i), (t, i) sıralı.

    Cooldown KABUL EDİLEN olaydan sayılır (aradaki günlerin laggard olup olmaması fark etmez). Yalnızca geçmiş olaylara
    bağlıdır; bu yüzden as_of'tan sonraki veri kabul kararını etkileyemez."""
    events: list[tuple[int, int]] = []
    for i in range(laggard.shape[1]):
        next_ok = first_t
        for t in range(first_t, last_t + 1):
            if t >= next_ok and laggard[t, i]:
                events.append((t, i))
                next_ok = t + cooldown
    return sorted(events)


# =====================================================================================================
# istatistik
# =====================================================================================================
def _stats(ex: np.ndarray, n_excluded: int, round_trip_cost_pct: float) -> HorizonStats:
    """ex: tamamlanmış olayların excess değerleri (pp). Başarı: excess > 0 (eşitlik başarı değil)."""
    n = int(len(ex))
    n_ok = int((ex > 0).sum())
    if n == 0:
        return HorizonStats(n_events_complete=0, n_excluded_incomplete_horizon=n_excluded, n_success=0, n_false_positive=0)
    mean = _r(float(np.mean(ex)))
    return HorizonStats(
        n_events_complete=n, n_excluded_incomplete_horizon=n_excluded, n_success=n_ok, n_false_positive=n - n_ok,
        hit_rate_pct=_r(100.0 * n_ok / n), false_positive_rate_pct=_r(100.0 * (n - n_ok) / n),
        mean_return_pct=mean, median_return_pct=_r(float(np.median(ex))),
        cost_adjusted_mean_return_pct=_r(mean - round_trip_cost_pct))


def _baseline(ex: np.ndarray) -> BaselineStats:
    if len(ex) == 0:
        return BaselineStats(n_obs=0)
    return BaselineStats(n_obs=int(len(ex)), mean_return_pct=_r(float(np.mean(ex))), median_return_pct=_r(float(np.median(ex))),
                         hit_rate_pct=_r(100.0 * float((ex > 0).sum()) / len(ex)))


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else _r(a - b)


def _strength(vs_xu100_pp: float) -> SectorStrength:
    if vs_xu100_pp >= SECTOR_STRONG_MIN_VS_XU100_PP:
        return SectorStrength.STRONG
    if vs_xu100_pp <= SECTOR_WEAK_MAX_VS_XU100_PP:
        return SectorStrength.WEAK
    return SectorStrength.NEUTRAL


def _counts_text(members: list[str], counts: Counter) -> str:
    return ", ".join(f"{m} {counts.get(m, 0)}" for m in members) + f" (toplam {sum(counts.values())})"


def _days_text(days: list[pd.Timestamp]) -> str:
    s = ", ".join(x.date().isoformat() for x in days[:MAX_LISTED_DAYS])
    return s + (f" (+{len(days) - MAX_LISTED_DAYS} gün daha)" if len(days) > MAX_LISTED_DAYS else "")


# =====================================================================================================
# araç
# =====================================================================================================
def _panel(snap: Snapshot, members: list[str], as_of) -> pd.DataFrame:
    """Üyeler + XU100 adj_close, as_of'a kesilmiş, ORTAK günler (inner join; doldurma yok). Sütunlar: members + 'XU100'."""
    stocks = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"].isin(members)], as_of)
    absent = [m for m in members if m not in set(stocks["ticker"])]
    if absent:
        raise ToolFailure("NO_DATA", f"{', '.join(absent)} için snapshot {snap.data_version} içinde veri yok (as_of={as_of})")
    index = enforce_as_of(snap.index, as_of)
    if index.empty:
        raise ToolFailure("NO_DATA", f"XU100 için snapshot {snap.data_version} içinde as_of={as_of} öncesi veri yok")
    wide = stocks.pivot(index="date", columns="ticker", values="adj_close").reindex(columns=members)
    wide = wide.join(index.set_index("date")["adj_close"].rename("XU100"), how="inner").dropna().sort_index()
    return wide


def _handler(p: RankSectorRelativeStrengthParams, snap: Snapshot) -> ToolOutput:
    if p.analysis_start > p.as_of:
        raise ToolFailure("INVALID_PARAMS", f"analysis_start={p.analysis_start} as_of={p.as_of} tarihinden sonra")
    uni = load_universe()
    members = sorted(uni.loc[uni["peer_group"] == p.sector.value, "ticker"])
    if not members:
        raise ToolFailure("UNKNOWN_SECTOR", f"{p.sector.value} peer grubunda hisse yok (config/universe.csv)")
    n = len(members)
    h = p.horizon
    warnings: list[str] = []

    panel = _panel(snap, members, p.as_of)
    T = len(panel)
    if T < h + 1:
        raise ToolFailure("INSUFFICIENT_HISTORY", f"ortak panelde {T} gün var; horizon={h} için en az {h + 1} gerekli (as_of={p.as_of})")
    dates = panel.index
    P = panel[members].to_numpy(float)
    X = panel["XU100"].to_numpy(float)
    e = T - 1

    # --- lag penceresi getirileri: p[t]/p[t-h] - 1 (yüzde, 4 ondalık) ------------------------------------------
    R = np.full((T, n), np.nan)
    R[h:] = np.round((P[h:] / P[:-h] - 1.0) * 100.0, ROUND)
    xu = _r((X[e] / X[e - h] - 1.0) * 100.0)
    r_now = R[e]

    if n >= 2:
        med = _r(float(np.median(r_now)))
        lag_now = np.round(r_now - med, ROUND)
        vs = _r(med - xu)
        strength: SectorStrength | None = _strength(vs)
    else:
        med, vs, strength = None, None, None
        lag_now = np.zeros(n)
    order = sorted(range(n), key=lambda i: (-r_now[i], members[i]))
    ranking = [
        RankingRow(rank=k + 1, ticker=members[i], return_pct=float(r_now[i]), lag_score_pp=float(lag_now[i]),
                   return_vs_xu100_pp=_r(r_now[i] - xu),
                   is_laggard=bool(n >= 2 and lag_now[i] <= -p.lag_threshold_pp),
                   is_leader=bool(n >= 2 and lag_now[i] >= p.lag_threshold_pp))
        for k, i in enumerate(order)]

    cost = make_cost_model()
    if n == 1:
        warnings.append(make_warning(WarningCode.SOLO_PEER_GROUP,
                                     f"{p.sector.value}: tek hisseli grup ({members[0]}); sektör medyanı ve sıralama anlamsız, "
                                     "tarihsel catch-up üretilmedi"))
    elif n == 2:
        warnings.append(make_warning(WarningCode.SMALL_PEER_GROUP,
                                     f"{p.sector.value}: 2 hisseli grup; medyan iki hissenin ortalamasıdır, lag skorları birbirinin "
                                     "aynasıdır (A = -B) ve tarihsel olaylar birbirine bağımlıdır"))

    # --- veri kalitesi: ortak panelden düşen günler, fiyat sıçramaları ------------------------------------------
    range_start = min(p.analysis_start, dates[e - h + 1].date())
    cal = enforce_as_of(pd.DataFrame({"date": trading_calendar(snap)}), p.as_of)
    cal = cal.loc[cal["date"] >= pd.Timestamp(range_start), "date"]
    dropped = [d for d in cal if d not in dates]
    if dropped:
        warnings.append(make_warning(
            WarningCode.MISSING_TRADING_DAYS,
            f"ortak panelden (üyeler + XU100) {len(dropped)} işlem günü düşürüldü (en az bir seride veri yok; doldurma yok): "
            f"{_days_text(dropped)}"))
    syms = {*members, "XU100"}
    jumps = [j for j in snap.manifest.get("price_jump_report", [])
             if j["ticker"] in syms and range_start.isoformat() <= j["date"] <= p.as_of.isoformat()]
    for j in jumps[:MAX_LISTED_DAYS]:
        warnings.append(make_warning(
            WarningCode.PRICE_JUMP_OVER_LIMIT,
            f"{j['ticker']} {j['date']}: adj_close günlük getiri {j['return_pct']}% (önceki satır {j['prev_date']}); "
            "olası düzeltilmemiş bedelsiz/bölünme veya işlem durması"))
    if len(jumps) > MAX_LISTED_DAYS:
        warnings.append(make_warning(WarningCode.PRICE_JUMP_OVER_LIMIT, f"+{len(jumps) - MAX_LISTED_DAYS} sıçrama daha"))

    base = dict(
        sector=p.sector, peer_group_size=n, insufficient_peers=n < 2, horizon=h,
        window_start=dates[e - h + 1].date(), window_end=dates[e].date(),
        benchmark_definition=BenchmarkDefinition(type="peer_median", includes_subject_stock=True, price_field="adj_close",
                                                 return_type="simple", peer_group=p.sector.value, members=members),
        sector_median_return_pct=med, xu100_return_pct=xu, sector_median_vs_xu100_pp=vs, sector_strength=strength,
        strength_thresholds=StrengthThresholds(strong_min_vs_xu100_pp=SECTOR_STRONG_MIN_VS_XU100_PP,
                                               weak_max_vs_xu100_pp=SECTOR_WEAK_MAX_VS_XU100_PP),
        lag_threshold_pp=p.lag_threshold_pp, ranking=ranking, cost_model=cost, structural_vs_temporary=None)
    if n == 1:
        return ToolOutput(results=RankSectorRelativeStrengthResult(historical_catch_up=[], **base), warnings=warnings)

    # --- tarihsel olaylar: aynı kural her t günü (yalnızca t'ye kadar veri) --------------------------------------
    fh = p.forward_horizons
    cooldown = max(fh)
    med_all = np.round(np.median(R[h:], axis=1), ROUND)
    laggard = np.zeros((T, n), bool)
    laggard[h:] = np.round(R[h:] - med_all[:, None], ROUND) <= -p.lag_threshold_pp
    first_t = max(h, int(dates.searchsorted(pd.Timestamp(p.analysis_start))))
    raw = Counter({m: int(laggard[first_t:, i].sum()) for i, m in enumerate(members)})
    events = independent_events(laggard, first_t, e, cooldown) if first_t <= e else []
    kept = Counter({m: 0 for m in members})
    for _, i in events:
        kept[members[i]] += 1
    ev_t = np.array([t for t, _ in events], int)
    ev_i = np.array([i for _, i in events], int)
    ev_date = [dates[t].date() for t in ev_t]

    catch_up: list[CatchUpHorizon] = []
    oos_small: list[int] = []
    oos_bad: list[int] = []
    excluded_by_h: dict[int, int] = {}
    n_complete_by_h: dict[int, int] = {}
    for f in fh:
        # baz: aynı dönem ve ufuk, TÜM (hisse, gün) gözlemleri; sonuç = kendisi hariç medyana göre excess
        last_obs = e - f
        if first_t <= last_obs:
            F = np.round((P[first_t + f:e + 1] / P[first_t:last_obs + 1] - 1.0) * 100.0, ROUND)
            E = np.round(F - leave_one_out_median(F), ROUND)  # satır k = t = first_t + k
        else:
            E = np.empty((0, n))
        complete = ev_t + f <= e if len(ev_t) else np.zeros(0, bool)
        ex = E[ev_t[complete] - first_t, ev_i[complete]] if complete.any() else np.empty(0)

        def part(mask: np.ndarray) -> HorizonStats:
            sel = complete & mask
            vals = E[ev_t[sel] - first_t, ev_i[sel]] if sel.any() else np.empty(0)
            return _stats(vals, int((~complete & mask).sum()), cost.round_trip_cost_pct)

        everything = np.ones(len(ev_t), bool)
        full = part(everything)
        in_s = out_s = None
        flag = None
        if p.split_date is not None:
            is_mask = np.array([d < p.split_date for d in ev_date], bool) if len(ev_t) else np.zeros(0, bool)
            in_s, out_s = part(is_mask), part(~is_mask)
            flag, too_small = oos_degradation(in_s, out_s)
            if too_small:
                oos_small.append(f)
            if flag:
                oos_bad.append(f)
        bl = _baseline(E.ravel())
        catch_up.append(CatchUpHorizon(
            block=HorizonBlock(horizon=f, full=full, in_sample=in_s, out_of_sample=out_s, baseline=bl,
                               mean_diff_vs_baseline_pct=_diff(full.mean_return_pct, bl.mean_return_pct),
                               median_diff_vs_baseline_pct=_diff(full.median_return_pct, bl.median_return_pct),
                               oos_degradation_flag=flag),
            median_catch_up_size_pp=_r(float(np.median(ex[ex > 0]))) if (ex > 0).any() else None))
        excluded_by_h[f] = full.n_excluded_incomplete_horizon
        n_complete_by_h[f] = full.n_events_complete

    longest = max(fh)
    n_events, n_excl = n_complete_by_h[longest], excluded_by_h[longest]
    if n_events < MIN_EVENTS:
        warnings.append(make_warning(
            WarningCode.FEW_EVENTS,
            f"n_events={n_events} < MIN_EVENTS={MIN_EVENTS} (en uzun ufuk {longest} gün için tamamlanmış bağımsız olay); "
            "istatistikler güvenilir değil"))
    if any(excluded_by_h.values()):
        warnings.append(make_warning(
            WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
            "ufku as_of'u aşan olaylar istatistiğe katılmadı (ufuk: dışlanan): "
            + ", ".join(f"{f}g: {excluded_by_h[f]}" for f in fh)))
    if oos_small:
        warnings.append(make_warning(
            WarningCode.OOS_TOO_SMALL, f"örneklem dışı tamamlanmış olay sayısı küçük (ufuk {', '.join(map(str, oos_small))} gün); "
                                       "oos_degradation_flag=false güvenilir değil"))
    if oos_bad:
        warnings.append(make_warning(
            WarningCode.OOS_DEGRADATION, f"örneklem dışı bozulma (ufuk {', '.join(map(str, oos_bad))} gün)"))
    warnings.append(make_warning(
        WarningCode.HISTORICAL_ONLY,
        "geçmiş kanıt, gelecek garantisi değil; tespit: grup medyanı (kendisi dahil); sonuç: kendisi hariç peer medyanı; "
        f"ham laggard hisse-günü: {_counts_text(members, raw)}; bağımsızlaştırma sonrası olay "
        f"(hisse bazında cooldown={cooldown} gün): {_counts_text(members, kept)}; "
        "sektörün güçlü olup olmadığı olay kuralında aranmadı; hisseler arası olay bağımlılığı kalır"))
    warnings.append(make_warning(
        WarningCode.MULTIPLE_TESTING_RISK,
        f"{len(fh)} ileri ufuk aynı veride denendi (ayrıca lag penceresi ve eşik seçimi); çoklu test düzeltmesi uygulanmadı"))

    return ToolOutput(results=RankSectorRelativeStrengthResult(historical_catch_up=catch_up, **base), n_events=n_events,
                      n_excluded_incomplete_horizon=n_excl, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
