"""Fiyat sıçraması tespiti ve şiddet sınıflandırması (check_data_quality'nin yapı taşı; ağ yok).

check_data_quality aracının tamamı henüz yazılmadı; bu modül onun fiyat sıçraması bölümüdür ve
snapshot manifest'indeki `price_jump_report`'u üretmek için de kullanılır (scripts/ buradan import eder).
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from config.settings import (
    PRICE_JUMP_LIMIT_PCT,
    PRICE_JUMP_MARKET_WIDE_SHARE,
    PRICE_JUMP_TOLERANCE_PP,
)
from schemas.enums import DQCode, DQSeverity, GateStatus
from schemas.results import DQIssue
from tools.common import enforce_as_of


def price_jump_report(
    df: pd.DataFrame, limit_pct: float = PRICE_JUMP_LIMIT_PCT, tolerance_pp: float = PRICE_JUMP_TOLERANCE_PP,
) -> list[dict]:
    """|günlük adj_close getirisi| > limit_pct + tolerance_pp olan günler.

    Olası düzeltilmemiş bedelsiz/bölünme, uzun işlem durması sonrası açılış veya veri hatası. BIST günlük
    limiti ±%10'dur. `adj_close` kullanılır: temettü günlerindeki ham `close` düşüşü (ör. ISMEN 2025-03-28)
    düzeltilmiş seride görünmez; bölünme DÜZELTİLMEMİŞSE (ör. CCOLA 2024-08-01, v1) görünür.
    Her kayıtta önceki satırın tarihi ve takvim günü farkı vardır (çok günlük boşluk = işlem durması işareti).
    """
    out: list[dict] = []
    for tk, g in (df.groupby("ticker") if "ticker" in df.columns else [("", df)]):
        g = g.sort_values("date")
        ret = (g["adj_close"].pct_change() * 100).round(6)
        prev_adj = g["adj_close"].shift(1)
        prev_date = g["date"].shift(1)
        for i in g.index[ret.abs() > limit_pct + tolerance_pp]:
            out.append({
                "ticker": str(tk), "date": g.loc[i, "date"].date().isoformat(),
                "return_pct": round(float(ret.loc[i]), 4),
                "adj_close_prev": round(float(prev_adj.loc[i]), 6), "adj_close": round(float(g.loc[i, "adj_close"]), 6),
                "prev_date": prev_date.loc[i].date().isoformat(),
                "calendar_gap_days": int((g.loc[i, "date"] - prev_date.loc[i]).days),
            })
    return sorted(out, key=lambda r: (r["ticker"], r["date"]))


def classify_price_jumps(
    stocks: pd.DataFrame,
    tickers: list[str],
    start: date,
    end: date,
    as_of: date,
    limit_pct: float = PRICE_JUMP_LIMIT_PCT,
    tolerance_pp: float = PRICE_JUMP_TOLERANCE_PP,
    market_wide_share: float = PRICE_JUMP_MARKET_WIDE_SHARE,
) -> list[DQIssue]:
    """İstenen hisse ve aralıktaki sıçramaları şiddetine göre sınıflandırır.

    * Aynı gün, o gün verisi olan hisselerin >= market_wide_share'i sıçradıysa: piyasa geneli olay
      (ör. 2023-02-15 işlem durması sonrası açılış) -> SOFT, PRICE_JUMP_OVER_LIMIT.
    * Aksi halde tek hisseye özgü (olası düzeltilmemiş bedelsiz/bölünme) -> HARD, WRONG_TICKER_OR_BROKEN_HISTORY.
    Look-ahead: veri ÖNCE as_of ile kesilir; as_of sonrası hiçbir gün hesaba girmez.
    """
    df = enforce_as_of(stocks, as_of)
    report = price_jump_report(df, limit_pct, tolerance_pp)
    n_with_data = df.groupby("date")["ticker"].nunique()
    n_flagged = pd.Series([r["date"] for r in report]).value_counts()
    effective_end = min(end, as_of)
    wanted = set(tickers)

    issues: list[DQIssue] = []
    for r in report:
        d = date.fromisoformat(r["date"])
        if r["ticker"] not in wanted or not (start <= d <= effective_end):
            continue
        share = float(n_flagged[r["date"]]) / float(n_with_data[pd.Timestamp(d)])
        market_wide = share >= market_wide_share
        detail = (f"adj_close günlük getiri {r['return_pct']}% (limit {limit_pct}% + tolerans {tolerance_pp} pp; "
                  f"önceki satır {r['prev_date']}); aynı gün sıçrayan hisse oranı %{round(share * 100, 1)}")
        issues.append(DQIssue(
            code=DQCode.PRICE_JUMP_OVER_LIMIT if market_wide else DQCode.WRONG_TICKER_OR_BROKEN_HISTORY,
            severity=DQSeverity.SOFT if market_wide else DQSeverity.HARD,
            message=("Piyasa geneli sıçrama: " if market_wide else "Hisseye özgü sıçrama, olası düzeltilmemiş bedelsiz/bölünme: ")
                    + detail,
            ticker=r["ticker"], date=d, value=r["return_pct"],
        ))
    return issues


def gate_from_issues(issues: list[DQIssue]) -> GateStatus:
    """En az kural: HARD varsa HARD_BLOCK; yalnız SOFT varsa PASS_WITH_WARNINGS; hiçbiri yoksa PASS.

    check_data_quality (tam araç) bunu diğer kontrollerle birleştirip INVESTIGATE/ANALYSIS_UNSAFE ayrımını ekleyecek.
    """
    if any(i.severity == DQSeverity.HARD for i in issues):
        return GateStatus.HARD_BLOCK
    if issues:
        return GateStatus.PASS_WITH_WARNINGS
    return GateStatus.PASS
