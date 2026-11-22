"""calculate_fundamental_change: bilanço metrik değişimi (QoQ/YoY) + açıklama sonrası 1/5/20 günlük fiyat tepkisi.

KURALLAR
* Hizalama KAP açıklama tarihine (`disclosure_date`) göre; yalnızca disclosure_date <= as_of olan dönemler girer (kural 7).
* Dönem sonu as_of'a kadar geçmiş ama açıklaması as_of'tan sonra olan dönemler dışlanır, yalnızca SAYISI raporlanır.
* TMS 29: yalnızca 2025+ dönemler tutulur; önceki yıl/çeyrek 2025 öncesine düşüyorsa değişim None + PRE_TMS29 uyarısı.
* Tepki penceresi: BAZ = açıklama günü işlem günüyse ve saat BİLİNİYORSA ve >= 18:00 (kapanış sonrası) açıklama günü kapanışı;
  aksi halde (saat yok/seans içi/tatil günü) açıklamadan ÖNCEKİ son işlem günü kapanışı (muhafazakâr: tüm tepki pencerede).
  h günlük tepki = baz kapanışından baz+h işlem günü sonraki kapanışa basit getiri (adj_close). Pencere sonu as_of'u aşıyorsa
  complete=False (kural 2). Anormal getiri = hisse - XU100 ve hisse - peer medyanı (hisse DAHİL; tek hisseli grupta None).
* Nedensellik iddiası yok: ilişki gözlemidir (ASSOCIATION_NOT_CAUSATION). Ağ yok.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config.settings import MIN_EVENTS
from config.universe import load_universe
from schemas.common import BenchmarkDefinition
from schemas.enums import MetricSet, ReactionGroup, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import CalculateFundamentalChangeParams
from schemas.results import (
    CalculateFundamentalChangeResult, MetricChange, QuarterReaction, QuarterRow, ReactionSummary,
)
from tools import _fundamentals as F
from tools.common import Snapshot, ToolFailure, ToolOutput, enforce_as_of, run_tool, trading_calendar
from tools.get_fundamental_metrics import common_checks

TOOL = ToolName.CALCULATE_FUNDAMENTAL_CHANGE
M = F.M
POST_CLOSE_TIME = "18:00"  # BIST seans sonu; bu saat ve sonrası "kapanış sonrası" açıklama


def _r(x: float | None) -> float | None:
    return None if x is None else float(np.round(x, 4)) + 0.0


def reaction_base_pos(cal: pd.DatetimeIndex, disclosure: pd.Timestamp, time: str | None) -> int:
    """Baz kapanışın takvimdeki konumu. Örn. 12 Ağu (işlem günü) saat yok -> 11 Ağu; saat 19:00 -> 12 Ağu."""
    pos = int(cal.searchsorted(disclosure, side="left"))  # D'ye eşit veya sonraki ilk işlem günü
    is_td = pos < len(cal) and cal[pos] == disclosure
    post = is_td and bool(time) and str(time) >= POST_CLOSE_TIME
    return pos if post else pos - 1


def _price_panel(snap: Snapshot, members: list[str], as_of, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """Üyeler + XU100 adj_close'u ortak takvime hizalı (eksik gün: son değer taşınır). as_of'a kesilmiş."""
    st = enforce_as_of(snap.stocks.loc[snap.stocks["ticker"].isin(members)], as_of)
    cols = {m: st.loc[st["ticker"] == m].set_index("date")["adj_close"] for m in members if m in set(st["ticker"])}
    cols["XU100"] = enforce_as_of(snap.index, as_of).set_index("date")["adj_close"]
    return pd.DataFrame({k: v.reindex(cal, method="ffill") for k, v in cols.items()})


def window_returns(panel: pd.DataFrame, base: int, h: int) -> dict[str, float | None] | None:
    """Pencere [base, base+h] basit getiri (%) her sütun için; pencere takvim dışıysa None."""
    end = base + h
    if base < 0 or end > len(panel) - 1:
        return None
    a, b = panel.iloc[base], panel.iloc[end]
    return {c: (None if pd.isna(a[c]) or pd.isna(b[c]) else _r((b[c] / a[c] - 1) * 100)) for c in panel.columns}


def load_members(ticker: str) -> list[str]:
    u = load_universe()
    g = u.loc[u["ticker"] == ticker, "peer_group"].iloc[0]
    return list(u.loc[u["peer_group"] == g, "ticker"])


def _handler(p: CalculateFundamentalChangeParams, snap: Snapshot, fund_version: str | None = None) -> ToolOutput:
    fund, mset, urow = common_checks(p.ticker, snap, fund_version)
    allowed = F.METRIC_SETS[mset]
    warnings: list[str] = []
    if p.metrics is not None:
        bad = [m.value for m in p.metrics if m not in allowed]
        if bad:
            raise ToolFailure("METRIC_NOT_APPLICABLE", f"{p.ticker} ({mset.value}) için geçersiz metrik(ler): {', '.join(bad)}")
    imp = p.improvement_metric
    if imp not in allowed:
        if mset == MetricSet.BANK:
            imp = M.NET_PROFIT
            warnings.append(make_warning(WarningCode.BANK_METRIC_SET,
                                         f"{p.improvement_metric.value} banka için geçersiz; iyileşme metriği NET_PROFIT alındı"))
        else:
            raise ToolFailure("METRIC_NOT_APPLICABLE", f"{p.improvement_metric.value} {mset.value} kümesinde yok")
    metrics = sorted(set(p.metrics or allowed) | {imp}, key=allowed.index)
    if mset == MetricSet.BANK:
        warnings.append(make_warning(WarningCode.BANK_METRIC_SET,
                                     "banka: sanayi oranları kullanılmadı; küme NET_INTEREST_INCOME, NET_PROFIT, ROE"))

    rows = F.visible(fund.table, p.ticker, p.as_of).sort_values("period_end_date")
    rows = rows.set_index("fiscal_period", drop=False)
    n_pending = F.pending_count(fund.table, p.ticker, p.as_of)
    if n_pending:
        warnings.append(make_warning(WarningCode.NOT_YET_DISCLOSED_EXCLUDED,
                                     f"{p.ticker}: dönem sonu geçmiş {n_pending} dönemin bilançosu as_of'ta açıklanmamış; dışlandı"))
    if rows.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker}: as_of={p.as_of} itibarıyla açıklanmış bilanço yok")
    fps = list(rows.index)
    if p.periods is not None:
        missing = [x for x in p.periods if x not in fps]
        if missing:
            warnings.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                                         f"istenen dönem(ler) {', '.join(missing)} as_of'ta açıklanmış değil/veride yok; atlandı"))
        fps = [x for x in fps if x in p.periods]

    qm: dict[str, dict] = {}
    annualised: list[str] = []
    for fp in rows.index:
        qm[fp], basis = F.quarter_metrics(rows, fp, mset)
        if basis == "ANNUALISED" and qm[fp].get(M.NET_DEBT_EBITDA) is not None:
            annualised.append(fp)
    ann_shown = [a for a in annualised if a in fps]
    if M.NET_DEBT_EBITDA in metrics and ann_shown:
        warnings.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                                     f"NET_DEBT_EBITDA {', '.join(ann_shown)}: 4 ardışık çeyrek yok; "
                                     "çeyreklik FAVÖK x4 (yıllıklandırılmış) kullanıldı"))

    # --- fiyat paneli ---
    members = sorted(load_members(p.ticker))
    cal_all = trading_calendar(snap)
    cal = pd.DatetimeIndex(cal_all[cal_all <= pd.Timestamp(p.as_of)])
    panel = _price_panel(snap, members, p.as_of, cal)
    sector_cols = [m for m in members if m in panel.columns]
    solo = len(sector_cols) < 2
    if len(members) == 1:
        warnings.append(make_warning(WarningCode.SOLO_PEER_GROUP, f"{p.ticker} tek hisseli grup: sektör tepkisi hesaplanmadı"))
    elif len(members) == 2:
        warnings.append(make_warning(WarningCode.SMALL_PEER_GROUP, f"{p.ticker} peer grubu 2 hisse: sektör medyanı zayıf ölçüt"))

    quarters: list[QuarterRow] = []
    group_of: dict[str, str | None] = {}
    pre_tms: list[str] = []
    n_incomplete = 0
    n_statutory = 0
    basis_key = p.improvement_basis.value
    for fp in fps:
        r = rows.loc[fp]
        pe = r["period_end_date"].date()
        prev_fp = {"QOQ": F.fp_shift(fp, -1), "YOY": F.fp_shift(fp, -4)}
        comparable = {k: F.tms29_comparable(F.fp_period_end(v)) for k, v in prev_fp.items()}
        if not all(comparable.values()):
            pre_tms.append(fp)
        mc: list[MetricChange] = []
        dirs: dict[str, dict] = {}
        for m in metrics:
            cur = qm[fp][m]
            res = {}
            for key, pf in prev_fp.items():
                pv = qm[pf][m] if comparable[key] and pf in qm else None
                chg, unit = F.change(m, cur, pv)
                res[key] = (chg, unit, F.direction(m, chg, unit))
            mc.append(MetricChange(name=m, value=cur, qoq_change=res["QOQ"][0], yoy_change=res["YOY"][0],
                                   change_unit=res["QOQ"][1], qoq_direction=res["QOQ"][2], yoy_direction=res["YOY"][2]))
            dirs[m.value] = res
        group_of[fp] = dirs[imp.value][basis_key][2]
        # tepki (açıklama tarihi yasal süreden VARSAYILDIYSA tepki hesaplanmaz: tarih gerçek değil)
        if r["disclosure_source"] == "STATUTORY_DEADLINE":
            n_statutory += 1
            quarters.append(QuarterRow(fiscal_period=fp, period_end_date=pe, disclosure_date=r["disclosure_date"].date(),
                                       tms29_comparable=F.tms29_comparable(pe), metrics=mc, reactions=[]))
            continue
        base = reaction_base_pos(cal, r["disclosure_date"], r["disclosure_time"] if pd.notna(r["disclosure_time"]) else None)
        reacts: list[QuarterReaction] = []
        for h in p.reaction_horizons:
            w = window_returns(panel, base, h)
            stock = None if w is None else w.get(p.ticker)
            if w is None or stock is None:
                n_incomplete += 1
                reacts.append(QuarterReaction(horizon=h, window_end_date=None, complete=False, stock_return_pct=None,
                                              xu100_return_pct=None, sector_return_pct=None,
                                              abnormal_vs_xu100_pct=None, abnormal_vs_sector_pct=None))
                continue
            xu = w.get("XU100")
            peers = [w[c] for c in sector_cols if w.get(c) is not None]
            sec = None if solo or len(peers) < 2 else _r(float(np.median(peers)))
            reacts.append(QuarterReaction(
                horizon=h, window_end_date=cal[base + h].date(), complete=True, stock_return_pct=stock, xu100_return_pct=xu,
                sector_return_pct=sec, abnormal_vs_xu100_pct=None if xu is None else _r(stock - xu),
                abnormal_vs_sector_pct=None if sec is None else _r(stock - sec)))
        quarters.append(QuarterRow(fiscal_period=fp, period_end_date=pe, disclosure_date=r["disclosure_date"].date(),
                                   tms29_comparable=F.tms29_comparable(pe), metrics=mc, reactions=reacts))

    if pre_tms:
        warnings.append(make_warning(
            WarningCode.PRE_TMS29_NOT_COMPARABLE,
            f"{', '.join(pre_tms)}: önceki çeyrek/yıl TMS 29 öncesi (2025 öncesi) olduğundan ilgili QoQ/YoY değişim None (karşılaştırılamaz)"))

    # --- özet ---
    summary: list[ReactionSummary] = []
    react_qs = [q for q in quarters if q.reactions]  # yasal süre görünürlüklü çeyrekler tepki istatistiğine girmez
    for h in p.reaction_horizons:
        for g in (ReactionGroup.IMPROVED, ReactionGroup.NOT_IMPROVED, ReactionGroup.ALL):
            sel = [q for q in react_qs if g == ReactionGroup.ALL
                   or (g == ReactionGroup.IMPROVED and group_of[q.fiscal_period] == "IMPROVED")
                   or (g == ReactionGroup.NOT_IMPROVED and group_of[q.fiscal_period] in ("DETERIORATED", "FLAT"))]
            rs = [next(x for x in q.reactions if x.horizon == h) for q in sel]
            done = [x for x in rs if x.complete]
            ax = [x.abnormal_vs_xu100_pct for x in done if x.abnormal_vs_xu100_pct is not None]
            asec = [x.abnormal_vs_sector_pct for x in done if x.abnormal_vs_sector_pct is not None]
            summary.append(ReactionSummary(
                horizon=h, group=g, n=len(done), n_excluded_incomplete_horizon=len(rs) - len(done),
                mean_abnormal_vs_xu100_pct=_r(float(np.mean(ax))) if ax else None,
                median_abnormal_vs_xu100_pct=_r(float(np.median(ax))) if ax else None,
                hit_rate_vs_xu100_pct=_r(100.0 * sum(a > 0 for a in ax) / len(ax)) if ax else None,
                mean_abnormal_vs_sector_pct=_r(float(np.mean(asec))) if asec else None,
                median_abnormal_vs_sector_pct=_r(float(np.median(asec))) if asec else None))

    n_q = len(quarters)
    n_react = len(react_qs)
    n_nodir = sum(1 for q in react_qs if group_of[q.fiscal_period] is None)
    if n_nodir:
        warnings.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"{n_nodir}/{n_react} çeyrekte {imp.value} {basis_key} değişimi hesaplanamadı (karşılaştırma dönemi yok/TMS 29 öncesi); "
            "bu çeyrekler IMPROVED/NOT_IMPROVED gruplarına girmedi, yalnız ALL'a girdi"))
    if n_incomplete:
        warnings.append(make_warning(WarningCode.INCOMPLETE_HORIZON_EXCLUDED,
                                     f"{n_incomplete} (çeyrek x ufuk) penceresi as_of'u aşıyor; istatistiğe katılmadı"))
    if n_statutory:
        warnings.append(make_warning(
            WarningCode.INSUFFICIENT_HISTORY,
            f"{n_statutory}/{n_q} çeyreğin açıklama tarihi bilinmiyor, yasal süre sonu varsayıldı; bu çeyrekler metrik/değişim hesabında "
            "görünür, fiyat tepkisine ve tepki istatistiklerine girmedi"))
    if n_react < MIN_EVENTS:
        warnings.append(make_warning(WarningCode.FEW_EVENTS,
                                     f"n_quarters={n_react} < MIN_EVENTS={MIN_EVENTS}; istatistik zayıf, örneklem dışı ayrımı yapılamaz"))
    warnings.append(make_warning(WarningCode.MULTIPLE_TESTING_RISK,
                                 f"{len(p.reaction_horizons)} ufuk x 3 grup özet; çoklu karşılaştırma düzeltmesi yapılmadı"))
    warnings.append(make_warning(WarningCode.ASSOCIATION_NOT_CAUSATION,
                                 "bilanço iyileşmesi ile fiyat tepkisi arasındaki ilişki gözlemdir; nedensellik iddia edilmez"))
    warnings += F.provenance_warnings(fund.version, rows.loc[fps])

    bench = BenchmarkDefinition(type="peer_median", includes_subject_stock=True, price_field="adj_close", return_type="simple",
                                peer_group=str(urow["peer_group"]), members=members)
    res = CalculateFundamentalChangeResult(
        ticker=p.ticker, metric_set=mset, benchmark_definition=bench, improvement_metric=imp, improvement_basis=basis_key,
        n_quarters_disclosed_by_as_of=len(rows), n_quarters_excluded_not_yet_disclosed=n_pending,
        quarters=quarters, reaction_summary=summary)
    return ToolOutput(results=res, n_events=n_react, n_excluded_incomplete_horizon=n_incomplete, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None,
           fundamentals_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım (sözleşmenin parçası DEĞİL)."""
    return run_tool(TOOL, params, lambda p, s: _handler(p, s, fundamentals_version),  # type: ignore[arg-type]
                    snapshot_root=snapshot_root, data_version=data_version)
