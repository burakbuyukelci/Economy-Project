"""check_data_quality: veri kalitesi ve risk kapısı (proje dokümanı §26). Snapshot'tan okur, ağ yok.

Yapı:
  * Kural fonksiyonları (saf, test edilebilir): her biri `list[DQIssue]` döndürür.
  * `decide_gate`: sorun listesinden kapı durumunu ve `gate_reason` metnini üretir.
  * Araç giriş noktası (en altta): params -> snapshot -> kurallar -> kapı -> zarf.

Kapı kararı yalnızca sorun KODUNA ve değerine bakar; uyarı sayısı kapıyı yükseltmez (retail demosunda FEW_EVENTS ve
küçük peer grubu birlikte çıkabilir; bu ANALYSIS_UNSAFE yapılmaz). Tablo docs/data_dictionary.md bölüm 15'tedir.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from config.settings import (
    MIN_EVENTS,
    MIN_WEEKDAY_IS_TRIGGER_WEEKS,
    MIN_WEEKDAY_OOS_TRIGGER_WEEKS,
    PRICE_JUMP_TOLERANCE_PP,
)
from config.universe import load_universe
from schemas.enums import DQCheck, DQCode, DQSeverity, GateStatus, ToolName, WarningCode
from schemas.envelope import make_warning
from schemas.params import BundleItem, CheckDataQualityParams
from schemas.results import CheckDataQualityResult, DQIssue, TickerQuality
from tools.common import Snapshot, ToolOutput, enforce_as_of, run_tool, trading_calendar
from tools.price_quality import classify_price_jumps

# --- Eşikler (bu modüle özgü; config/ ortak bölge olduğundan oraya KONMADI. Varsayım olanlar işaretli.) -------------
# Bayatlık: gün = as_of - (as_of'a kadarki son satır tarihi). <= GRACE: normal (hafta sonu/kısa tatil), uyarı yok;
# GRACE < gün <= WARN_MAX: PASS_WITH_WARNINGS; WARN_MAX < gün <= UNSAFE: INVESTIGATE; gün > UNSAFE: ANALYSIS_UNSAFE.
STALE_GRACE_DAYS = 4          # VARSAYIM: Cuma-Pazartesi tatili dahil 4 takvim günü normaldir
STALE_WARN_MAX_DAYS = 10      # onaylı (kullanıcı kademesi)
STALE_UNSAFE_DAYS = 30        # onaylı
MIN_FUNDAMENTAL_QUARTERS = 4  # onaylı: temel veri için en az 4 çeyrek
PEER_GROUP_MIN_SIZE = 3       # < 3 üye = küçük grup (rank aracı n==1 SOLO, n==2 SMALL der)
MACRO_MAX_GAP_DAYS = 7        # VARSAYIM: günlük seri için; aylık seriler çağıran tarafından geniş eşikle sorulmalı
NEWS_MIN_ITEMS = 3            # VARSAYIM: pencerede < 3 haber = seyrek
TRANSCRIPT_MIN_QUALITY = 0.6  # VARSAYIM: 0-1 ölçeğinde (GetSpeechFeatures.transcript_quality)


# --- FEW_EVENTS: araç bazlı birim ve minimum ------------------------------------------------------------------------
@dataclass(frozen=True)
class EventRule:
    unit: str      # zarfın n_events'inin birimi
    minimum: int   # bunun ALTI FEW_EVENTS
    basis: str     # minimumun kaynağı


# Birimler schemas/envelope.py ToolEnvelope.n_events açıklamasından. Tabloda OLMAYAN araç için kontrol çalışmaz.
EVENT_COUNT_RULES: dict[ToolName, EventRule] = {
    ToolName.DETECT_REVERSAL_EVENTS: EventRule("olay", MIN_EVENTS, "MIN_EVENTS"),
    ToolName.RANK_SECTOR_RELATIVE_STRENGTH: EventRule("olay", MIN_EVENTS, "MIN_EVENTS"),
    ToolName.RUN_BACKTEST: EventRule("sinyal", MIN_EVENTS, "MIN_EVENTS"),
    # zarf n_events = IS+OOS n_occurrences (hafta); araç kendi kararlılığını tetik haftalarıyla ölçer (results içinde),
    # kapı yalnızca zarfı görür: asgari = IS + OOS tetik haftası eşiklerinin toplamı (YAKLAŞIK; bkz. data_dictionary 15.5)
    ToolName.TEST_WEEKDAY_PATTERN: EventRule(
        "hafta", MIN_WEEKDAY_IS_TRIGGER_WEEKS + MIN_WEEKDAY_OOS_TRIGGER_WEEKS,
        "MIN_WEEKDAY_IS_TRIGGER_WEEKS + MIN_WEEKDAY_OOS_TRIGGER_WEEKS"),
    ToolName.CALCULATE_FUNDAMENTAL_CHANGE: EventRule("çeyrek", MIN_FUNDAMENTAL_QUARTERS, "MIN_FUNDAMENTAL_QUARTERS"),
}


def _tool_name(tool: ToolName | str) -> str:
    return str(getattr(tool, "value", tool))


# =============================================================== HARD kuralları
def check_as_of_consistency(bundle: Sequence[BundleItem], as_of: date) -> list[DQIssue]:
    """Bundle öğesinin as_of'u oturum as_of'unu aşarsa HARD (gelecek bilgi geçmiş analize girmiş demektir)."""
    return [
        DQIssue(code=DQCode.AS_OF_VIOLATION, severity=DQSeverity.HARD, date=b.as_of,
                message=f"{_tool_name(b.tool)} çıktısının as_of'u ({b.as_of}) oturum as_of'unu ({as_of}) aşıyor")
        for b in bundle if b.as_of > as_of
    ]


def check_lookahead(
    signal_lag_days_applied: int | None, max_result_date: date | None, as_of: date, tool: ToolName | str,
) -> list[DQIssue]:
    """signal_lag_days < 1 veya as_of sonrası tarihli sonuç -> HARD (LOOKAHEAD_SIGNAL).

    BundleItem'da bu iki alan henüz yok (docs/schema_wishlist.md §4); şimdilik saf fonksiyon.
    """
    out: list[DQIssue] = []
    t = _tool_name(tool)
    if signal_lag_days_applied is not None and signal_lag_days_applied < 1:
        out.append(DQIssue(code=DQCode.LOOKAHEAD_SIGNAL, severity=DQSeverity.HARD, value=float(signal_lag_days_applied),
                           message=f"{t}: signal_lag_days={signal_lag_days_applied} < 1; sinyal günü t'de t bilgisiyle işlem"))
    if max_result_date is not None and max_result_date > as_of:
        out.append(DQIssue(code=DQCode.LOOKAHEAD_SIGNAL, severity=DQSeverity.HARD, date=max_result_date,
                           message=f"{t}: sonuçlarda as_of ({as_of}) sonrası tarih var: {max_result_date}"))
    return out


@dataclass(frozen=True)
class TradeDates:
    signal_date: date
    entry_date: date
    exit_date: date


def check_backtest_information(trades: Sequence[TradeDates], as_of: date) -> list[DQIssue]:
    """Backtest karar anında olmayan bilgiyi kullanıyor mu: giriş <= sinyal günü, ya da çıkış > as_of -> HARD."""
    out: list[DQIssue] = []
    for t in trades:
        if t.entry_date <= t.signal_date:
            out.append(DQIssue(code=DQCode.BACKTEST_FUTURE_INFO, severity=DQSeverity.HARD, date=t.entry_date,
                               message=f"işlem girişi ({t.entry_date}) sinyal gününden ({t.signal_date}) sonra değil"))
        if t.exit_date > as_of:
            out.append(DQIssue(code=DQCode.BACKTEST_FUTURE_INFO, severity=DQSeverity.HARD, date=t.exit_date,
                               message=f"işlem çıkışı ({t.exit_date}) as_of ({as_of}) sonrası"))
    return out


@dataclass(frozen=True)
class FundamentalRow:
    period_end: date
    disclosure_date: date          # KAP açıklama tarihi (CLAUDE.md kural 7)
    used_on: date | None = None    # bu bilanço hangi tarihteki kararda kullanıldı (None = as_of)


def check_fundamental_alignment(rows: Sequence[FundamentalRow], as_of: date) -> list[DQIssue]:
    """Bilanço satırı: açıklama tarihi kullanım tarihinden (ya da as_of'tan) SONRA -> FUTURE_FUNDAMENTAL_LEAK;
    açıklama tarihi dönem sonundan ÖNCE (imkânsız hizalama, dönem sonuna göre hizalama izi) -> PERIOD_MISMATCH. İkisi de HARD.
    """
    out: list[DQIssue] = []
    for r in rows:
        ref = min(r.used_on or as_of, as_of)
        if r.disclosure_date > ref:
            out.append(DQIssue(
                code=DQCode.FUTURE_FUNDAMENTAL_LEAK, severity=DQSeverity.HARD, date=r.disclosure_date,
                message=f"{r.period_end} dönemi bilançosu {r.disclosure_date} tarihinde açıklandı; {ref} tarihli analize girmiş"))
        elif r.disclosure_date < r.period_end:
            out.append(DQIssue(
                code=DQCode.PERIOD_MISMATCH, severity=DQSeverity.HARD, date=r.disclosure_date,
                message=f"açıklama tarihi ({r.disclosure_date}) dönem sonundan ({r.period_end}) önce: fiyat/bilanço hizası bozuk"))
    return out


# =============================================================== SOFT kuralları
def check_event_counts(bundle: Sequence[BundleItem]) -> tuple[list[DQIssue], int]:
    """(sorunlar, değerlendirilen öğe sayısı). Tabloda olmayan araç ya da n_events=None değerlendirilmez."""
    out: list[DQIssue] = []
    evaluated = 0
    for b in bundle:
        rule = EVENT_COUNT_RULES.get(b.tool)
        if rule is None or b.n_events is None:
            continue
        evaluated += 1
        if b.n_events < rule.minimum:
            out.append(DQIssue(
                code=DQCode.FEW_EVENTS, severity=DQSeverity.SOFT, value=float(b.n_events),
                message=f"{_tool_name(b.tool)}: n_events={b.n_events} {rule.unit} < minimum {rule.minimum} ({rule.basis})"))
    return out, evaluated


def check_peer_group(
    bundle: Sequence[BundleItem], tickers: Sequence[str], peer_group_sizes: dict[str, int],
) -> tuple[list[DQIssue], bool]:
    """(sorunlar, çalıştı mı). Yalnızca bundle'da rank_sector_relative_strength varsa çalışır (peer bilgisi o zaman anlamlı)."""
    if not any(b.tool == ToolName.RANK_SECTOR_RELATIVE_STRENGTH for b in bundle):
        return [], False
    out = [
        DQIssue(code=DQCode.SMALL_PEER_GROUP, severity=DQSeverity.SOFT, ticker=t, value=float(peer_group_sizes[t]),
                message=f"{t}: peer grubu {peer_group_sizes[t]} hisse (< {PEER_GROUP_MIN_SIZE}); sektör göreli sonuç zayıf")
        for t in sorted(tickers) if t in peer_group_sizes and peer_group_sizes[t] < PEER_GROUP_MIN_SIZE
    ]
    return out, True


def check_data_version(bundle: Sequence[BundleItem], data_version: str) -> list[DQIssue]:
    return [
        DQIssue(code=DQCode.DATA_VERSION_MISMATCH, severity=DQSeverity.SOFT,
                message=f"{_tool_name(b.tool)} çıktısı {b.data_version} sürümünden; kapı {data_version} ile çalışıyor")
        for b in bundle if b.data_version != data_version
    ]


def check_staleness(label: str, last_date: date, as_of: date) -> list[DQIssue]:
    """Gün farkı <= STALE_GRACE_DAYS ise sorun yok; aksi halde STALE_DATA (kademe `decide_gate`'te, value = gün)."""
    age = (as_of - last_date).days
    if age <= STALE_GRACE_DAYS:
        return []
    return [DQIssue(code=DQCode.STALE_DATA, severity=DQSeverity.SOFT, ticker=label, date=last_date, value=float(age),
                    message=f"{label}: son satır {last_date}, as_of {as_of} ({age} gün); snapshot as_of'u tam kapsamıyor")]


def check_macro_coverage(
    obs_dates: Sequence[date], start: date, end: date, max_gap_days: int = MACRO_MAX_GAP_DAYS,
) -> list[DQIssue]:
    """[start, end] içinde ardışık gözlemler (ve uçlar) arasında > max_gap_days boşluk -> MACRO_GAP. `end` sonrası gözlem yok sayılır."""
    pts = sorted(d for d in obs_dates if start <= d <= end)
    if not pts:
        return [DQIssue(code=DQCode.MACRO_GAP, severity=DQSeverity.SOFT, value=float((end - start).days),
                        message=f"[{start}, {end}] aralığında makro gözlem yok")]
    anchors = [start, *pts, end]
    return [
        DQIssue(code=DQCode.MACRO_GAP, severity=DQSeverity.SOFT, date=b, value=float((b - a).days),
                message=f"makro seride {a} -> {b} arası {(b - a).days} gün boşluk (eşik {max_gap_days})")
        for a, b in zip(anchors, anchors[1:]) if (b - a).days > max_gap_days
    ]


def check_news_coverage(n_items: int, min_items: int = NEWS_MIN_ITEMS) -> list[DQIssue]:
    if n_items >= min_items:
        return []
    return [DQIssue(code=DQCode.NEWS_SPARSE, severity=DQSeverity.SOFT, value=float(n_items),
                    message=f"pencerede {n_items} haber (< {min_items}): haber kapsamı seyrek")]


def check_transcript_quality(quality: float | None, min_quality: float = TRANSCRIPT_MIN_QUALITY) -> list[DQIssue]:
    if quality is None or quality >= min_quality:
        return []
    return [DQIssue(code=DQCode.TRANSCRIPT_LOW_QUALITY, severity=DQSeverity.SOFT, value=float(quality),
                    message=f"transkript kalitesi {quality} (< {min_quality})")]


# =============================================================== kapı kararı
_INVESTIGATE_CODES = frozenset({DQCode.FEW_EVENTS, DQCode.SMALL_PEER_GROUP, DQCode.DATA_VERSION_MISMATCH})
_RANK = {GateStatus.PASS: 0, GateStatus.PASS_WITH_WARNINGS: 1, GateStatus.INVESTIGATE: 2,
         GateStatus.ANALYSIS_UNSAFE: 3, GateStatus.HARD_BLOCK: 4}


def _tier(i: DQIssue) -> GateStatus:
    if i.severity == DQSeverity.HARD:
        return GateStatus.HARD_BLOCK
    if i.code == DQCode.STALE_DATA:
        if i.value is None:
            raise ValueError("STALE_DATA için value (gün) zorunlu")
        if i.value > STALE_UNSAFE_DAYS:
            return GateStatus.ANALYSIS_UNSAFE
        return GateStatus.INVESTIGATE if i.value > STALE_WARN_MAX_DAYS else GateStatus.PASS_WITH_WARNINGS
    return GateStatus.INVESTIGATE if i.code in _INVESTIGATE_CODES else GateStatus.PASS_WITH_WARNINGS


def _count(issues: Sequence[DQIssue]) -> str:
    c = Counter(i.code.value for i in issues)
    return ", ".join(f"{k}×{c[k]}" for k in sorted(c))


def decide_gate(
    issues: Sequence[DQIssue], checks_run: Sequence[DQCheck], checks_not_run: Sequence[DQCheck],
) -> tuple[GateStatus, str]:
    """En yüksek kademe kazanır: HARD_BLOCK > ANALYSIS_UNSAFE > INVESTIGATE > PASS_WITH_WARNINGS > PASS."""
    status = max((_tier(i) for i in issues), key=_RANK.__getitem__, default=GateStatus.PASS)
    hard = [i for i in issues if i.severity == DQSeverity.HARD]
    soft = [i for i in issues if i.severity == DQSeverity.SOFT]
    parts = [f"{status.value}: hard {len(hard)}" + (f" ({_count(hard)})" if hard else ""),
             f"soft {len(soft)}" + (f" ({_count(soft)})" if soft else "")]
    reason = ", ".join(parts) + "."
    drivers = [i for i in issues if status not in (GateStatus.PASS, GateStatus.PASS_WITH_WARNINGS) and _tier(i) == status]
    if drivers:
        reason += f" Kapıyı belirleyen: {_count(drivers)}."
    if checks_run:
        reason += " Çalışan kontroller: " + ", ".join(c.value for c in checks_run) + "."
    if checks_not_run:
        reason += (" Çalışmayan kontroller (veri/şema yok, 'geçti' sayılmaz): "
                   + ", ".join(c.value for c in checks_not_run) + ".")
    return status, reason


# =============================================================== araç giriş noktası
TOOL = ToolName.CHECK_DATA_QUALITY
INDEX_LABEL = "XU100"
_ALWAYS_RUN = (DQCheck.PRICE_JUMPS, DQCheck.MISSING_DAYS, DQCheck.STALENESS, DQCheck.AS_OF_CONSISTENCY,
               DQCheck.TICKER_IDENTITY)
_SYMBOL_CHECK = {DQCode.MISSING_TRADING_DAYS: DQCheck.MISSING_DAYS, DQCode.STALE_DATA: DQCheck.STALENESS}


def _symbol_quality(
    label: str, df: pd.DataFrame, p: CheckDataQualityParams, eff_end: date, calendar: pd.Series,
) -> tuple[TickerQuality, list[DQIssue], bool]:
    """Tek sembolün (hisse veya XU100) rapor satırı + eksik gün/bayatlık sorunları. df zaten as_of ile kesilmiş.

    Dönüş: (rapor, sorunlar, pencerede_satır_var_mı). Pencere = [start, eff_end]; bayatlık pencereye değil as_of'a göre ölçülür
    (end < as_of iken pencere erken bitse de veri as_of'u kapsıyor mu sorusu aynıdır).
    """
    df = df.sort_values("date")
    ret = (df["adj_close"].pct_change() * 100).round(6)               # getiri önceki SATIRA göre (pencere başında da)
    in_win = (df["date"] >= pd.Timestamp(p.start)) & (df["date"] <= pd.Timestamp(eff_end))
    win = df[in_win]
    wret = ret[in_win].abs().dropna()
    thr = p.price_jump_limit_pct + PRICE_JUMP_TOLERANCE_PP            # price_quality ile AYNI kural (limit + tolerans)

    missing: list[pd.Timestamp] = []
    if len(df):
        lo = max(pd.Timestamp(p.start), df["date"].min())             # hissenin ilk satırından önceki günler eksik sayılmaz
        days = calendar[(calendar >= lo) & (calendar <= pd.Timestamp(eff_end))]
        have = set(win["date"])
        missing = [d for d in days if d not in have]

    last_any = df["date"].max().date() if len(df) else None
    report = TickerQuality(
        ticker=label, n_rows=len(win),
        first_date=win["date"].min().date() if len(win) else None,
        last_date=win["date"].max().date() if len(win) else None,
        n_missing_trading_days=len(missing),
        last_data_age_days=(p.as_of - last_any).days if last_any else None,
        max_abs_daily_return_pct=round(float(wret.max()), 4) if len(wret) else None,
        max_abs_daily_return_date=df.loc[wret.idxmax(), "date"].date() if len(wret) else None,
        n_price_jumps_over_limit=int((wret > thr).sum()),
    )

    issues: list[DQIssue] = []
    if missing:
        sample = ", ".join(d.date().isoformat() for d in missing[:5])
        more = f" (+{len(missing) - 5} gün daha)" if len(missing) > 5 else ""
        issues.append(DQIssue(code=DQCode.MISSING_TRADING_DAYS, severity=DQSeverity.SOFT, ticker=label,
                              value=float(len(missing)),
                              message=f"{label}: {len(missing)} işlem günü eksik (birleşik takvime göre): {sample}{more}"))
    if last_any is not None:
        issues += check_staleness(label, last_any, p.as_of)
    return report, issues, bool(len(win))


def _handler(p: CheckDataQualityParams, snap: Snapshot) -> ToolOutput:
    as_of = p.as_of
    eff_end = min(p.end, as_of)
    warnings: list[str] = []
    if p.end > as_of:
        warnings.append(make_warning(WarningCode.AS_OF_CLAMPED,
                                     f"end={p.end.isoformat()} as_of={as_of.isoformat()} tarihine kesildi"))

    wanted = set(p.checks) if p.checks is not None else set(DQCheck)
    stocks = enforce_as_of(snap.stocks, as_of)                        # as_of sonrası satır buradan öteye GEÇMEZ
    index = enforce_as_of(snap.index, as_of)
    calendar = enforce_as_of(pd.DataFrame({"date": trading_calendar(snap)}), as_of)["date"]
    known = set(snap.stocks["ticker"].unique())                       # yalnızca "bu ticker snapshot'ta var mı" için

    issues: list[DQIssue] = []
    reports: list[TickerQuality] = []
    symbols = [(t, stocks[stocks["ticker"] == t]) for t in p.tickers]
    if p.include_index:
        symbols.append((INDEX_LABEL, index))
    for label, df in symbols:
        rep, sym_issues, has_rows = _symbol_quality(label, df, p, eff_end, calendar)
        reports.append(rep)
        issues += [i for i in sym_issues if _SYMBOL_CHECK[i.code] in wanted]
        if not has_rows and DQCheck.TICKER_IDENTITY in wanted:
            if label != INDEX_LABEL and label not in known:
                why = "snapshot'ta yok"
            elif df.empty:
                why = f"as_of ({as_of}) tarihine kadar satır yok"
            else:
                why = f"[{p.start}, {eff_end}] pencerede satır yok"
            issues.append(DQIssue(code=DQCode.WRONG_TICKER_OR_BROKEN_HISTORY, severity=DQSeverity.HARD, ticker=label,
                                  message=f"{label}: {why}; yanlış ticker veya bozuk fiyat geçmişi"))

    if DQCheck.PRICE_JUMPS in wanted:
        issues += classify_price_jumps(stocks, list(p.tickers), p.start, p.end, as_of, limit_pct=p.price_jump_limit_pct)

    bundle = list(p.analysis_bundle)
    run: set[DQCheck] = {c for c in _ALWAYS_RUN if c in wanted}
    if DQCheck.AS_OF_CONSISTENCY in wanted:
        issues += check_as_of_consistency(bundle, as_of)
    if bundle and DQCheck.DATA_VERSION_CONSISTENCY in wanted:
        issues += check_data_version(bundle, snap.data_version)
        run.add(DQCheck.DATA_VERSION_CONSISTENCY)
    if DQCheck.EVENT_COUNT in wanted:
        ev, n_evaluated = check_event_counts(bundle)
        issues += ev
        if n_evaluated:
            run.add(DQCheck.EVENT_COUNT)
    if DQCheck.PEER_GROUP_SIZE in wanted:
        uni = load_universe()
        pe, ran = check_peer_group(bundle, list(p.tickers), dict(zip(uni["ticker"], uni["peer_group_size"].astype(int))))
        issues += pe
        if ran:
            run.add(DQCheck.PEER_GROUP_SIZE)

    checks_run = [c for c in DQCheck if c in run]
    not_run = [c for c in DQCheck if c in wanted and c not in run]

    def order(i: DQIssue):
        return (i.code.value, i.ticker or "", i.date or date.min, i.message)   # deterministik sıra

    hard = sorted((i for i in issues if i.severity == DQSeverity.HARD), key=order)
    soft = sorted((i for i in issues if i.severity == DQSeverity.SOFT), key=order)
    status, reason = decide_gate(hard + soft, checks_run, not_run)
    res = CheckDataQualityResult(
        gate_status=status, gate_reason=reason, hard_blocks=hard, soft_warnings=soft, checks_run=checks_run,
        price_jump_limit_pct=p.price_jump_limit_pct, ticker_reports=reports)
    return ToolOutput(results=res, warnings=warnings)


def run(params: dict) -> dict:
    """ARAÇ GİRİŞ NOKTASI SÖZLEŞMESİ: run(params: dict) -> dict (zarf). Harness bu imzayla çağırır."""
    return run_on(params)


def run_on(params: dict, *, snapshot_root: Path | None = None, data_version: str | None = None) -> dict:
    """Test/çevrimdışı kullanım: snapshot kökünü/sürümünü açıkça verir. Sözleşmenin parçası DEĞİLDİR."""
    return run_tool(TOOL, params, _handler, snapshot_root=snapshot_root, data_version=data_version)  # type: ignore[arg-type]
