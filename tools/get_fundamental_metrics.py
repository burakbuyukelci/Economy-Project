"""get_fundamental_metrics: hisse (+ dönem) + as_of -> as_of'ta AÇIKLANMIŞ en son (veya istenen) dönemin metrikleri.

Hizalama KAP açıklama tarihine göredir (`disclosure_date <= as_of`); dönem sonuna göre DEĞİL (kural 7). as_of'tan sonra
açıklanan dönem araca girmez. Banka için ayrı küçük küme (sanayi oranları yok). Ağ yok; bilanço veri setinden okur.
"""
from __future__ import annotations

from pathlib import Path

from config.universe import load_universe
from schemas.enums import MetricSet, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import GetFundamentalMetricsParams
from schemas.results import GetFundamentalMetricsResult, MetricValue
from tools import _fundamentals as F
from tools.common import Snapshot, ToolFailure, ToolOutput, run_tool

TOOL = ToolName.GET_FUNDAMENTAL_METRICS


def common_checks(ticker: str, snap: Snapshot, fund_version: str | None):
    """Ortak: evren kontrolü + veri seti + as_of'a kesilmiş satırlar. Dönüş (fund, metric_set, uni_row)."""
    uni = load_universe().set_index("ticker")
    if ticker not in uni.index:
        raise ToolFailure("UNKNOWN_TICKER", f"{ticker} evrende (config/universe.csv) yok")
    fund = F.load_fundamentals(snap.root, fund_version)
    sub = fund.table.loc[fund.table["ticker"] == ticker]
    if sub.empty:
        raise ToolFailure("NO_DATA", f"{ticker} için bilanço veri setinde ({fund.version}) satır yok")
    return fund, MetricSet(str(sub["metric_set"].iloc[0])), uni.loc[ticker]


def _handler(p: GetFundamentalMetricsParams, snap: Snapshot, fund_version: str | None = None) -> ToolOutput:
    fund, mset, _ = common_checks(p.ticker, snap, fund_version)
    rows = F.visible(fund.table, p.ticker, p.as_of)
    warnings: list[str] = []
    n_pending = F.pending_count(fund.table, p.ticker, p.as_of)
    if n_pending:
        warnings.append(make_warning(
            WarningCode.NOT_YET_DISCLOSED_EXCLUDED,
            f"{p.ticker}: dönem sonu as_of'a kadar geçmiş {n_pending} dönemin bilançosu as_of'ta henüz açıklanmamış; dışlandı"))
    if rows.empty:
        raise ToolFailure("NO_DATA", f"{p.ticker}: as_of={p.as_of} itibarıyla açıklanmış bilanço yok")
    if p.period is not None:
        if p.period not in rows.index:
            raise ToolFailure("NOT_YET_DISCLOSED", f"{p.ticker} {p.period}: as_of={p.as_of} itibarıyla açıklanmış değil veya veride yok")
        fp = p.period
    else:
        fp = str(rows.sort_values("period_end_date")["fiscal_period"].iloc[-1])
    metrics, basis = F.quarter_metrics(rows, fp, mset)
    r = rows.loc[fp]
    pe = r["period_end_date"].date()
    if mset == MetricSet.BANK:
        warnings.append(make_warning(WarningCode.BANK_METRIC_SET,
                                     "banka: sanayi oranları (FAVÖK marjı, Net Borç/FAVÖK vb.) kullanılmadı; küme NET_INTEREST_INCOME, NET_PROFIT, ROE"))
    if basis == "ANNUALISED" and F.M.NET_DEBT_EBITDA in metrics:
        warnings.append(make_warning(WarningCode.INSUFFICIENT_HISTORY,
                                     "NET_DEBT_EBITDA: 4 ardışık çeyrek yok; çeyreklik FAVÖK x4 (yıllıklandırılmış) ile hesaplandı"))
    if not F.tms29_comparable(pe):
        warnings.append(make_warning(WarningCode.PRE_TMS29_NOT_COMPARABLE, f"{fp} TMS 29 öncesi; sonraki dönemlerle karşılaştırılamaz"))
    warnings += F.provenance_warnings(fund.version, rows.loc[[fp]])
    res = GetFundamentalMetricsResult(
        ticker=p.ticker, metric_set=mset, fiscal_period=fp, period_end_date=pe, disclosure_date=r["disclosure_date"].date(),
        tms29_comparable=F.tms29_comparable(pe),
        metrics=[MetricValue(name=m, value=metrics[m], unit=F.UNITS[m]) for m in F.METRIC_SETS[mset]])
    return ToolOutput(results=res, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None,
           fundamentals_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım (sözleşmenin parçası DEĞİL)."""
    return run_tool(TOOL, params, lambda p, s: _handler(p, s, fundamentals_version),  # type: ignore[arg-type]
                    snapshot_root=snapshot_root, data_version=data_version)
