"""Genelleme testi: 5 örnek soru tipinin (Q1–Q5) belirlenimli VARYANT üreticisi (hisse, as_of tarihi ve parametre çeşitliliği).

Model YOK: varyantlar araç zincirinden öğretmen betiğiyle (experiments.sample_runs ilkeleri) geçirilir (bkz. run.py). Yeni üreteç mantığı yok: soru metinleri `docs/ornek_test_sorulari.txt` biçiminde,
parametre havuzları mevcut eğitim üretecinden (`training.questions._weekday_pattern`, `_CLAIMS`) ve `config/universe.csv`'den gelir. Aynı tohum -> aynı varyantlar.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from config.universe import build_sector_peer_groups, load_universe
from training.questions import DAY_TR, DIR_TR, _CLAIMS, _weekday_pattern, _pattern_text, fd

SEED = 20261124
N_PER_TYPE = 10
TYPES = ("Q1_catch_up", "Q2_weekday", "Q3_reversal", "Q4_fundamental", "Q5_macro_safety")
DATA_END = date(2026, 11, 19)          # veri 2026-11-20'ye kadar; son iş günü öncesi
DATE_RANGE = (date(2025, 6, 2), DATA_END)
FUND_DATE_RANGE = (date(2025, 10, 1), DATA_END)


def _rng(*parts: object) -> random.Random:
    return random.Random(":".join(map(str, (SEED, *parts))))


def _bday(rng: random.Random, lo: date, hi: date) -> date:
    while True:
        d = lo + timedelta(days=rng.randint(0, (hi - lo).days))
        if d.weekday() < 5:
            return d


def _head(d: date) -> str:
    return f"Analiz tarihi: {fd(d)}\n"


def _tickers(kind: str, n: int) -> list[str]:
    """Evrenden n FARKLI hisse (tip bazında tohumlu karıştırma)."""
    t = sorted(load_universe()["ticker"])
    _rng(kind, "tickers").shuffle(t)
    return t[:n]


def q1_variants() -> list[dict[str, Any]]:
    groups = build_sector_peer_groups()
    # retail (3 hisse; asıl senaryo) 4 varyant + 2 hisseli gruplar (küçük peer grubu uç durumu) 6 varyant
    sectors = ["retail"] * 4 + ["airlines", "steel", "telecom", "energy_petrochem", "chemicals", "healthcare"]
    out = []
    for i, sector in enumerate(sectors):
        rng = _rng("q1", i)
        a = _bday(rng, *DATE_RANGE)
        members = groups[sector]
        h = rng.choice([5, 10, 20, 20])
        hold = rng.choice([5, 10])
        variant = rng.choice(["A", "B"])
        text = (_head(a) + f"{sector} grubunda ({', '.join(members)}) {fd(a)} tarihine kadar olan son {h} işlem gününde sektör medyanının en çok gerisinde kalan hisse hangisi? "
                f"01.01.2024 – {fd(a)} döneminde benzer geride kalmalar 5, 10 ve 20 gün içinde kapanmış mı? Hisse POTENTIAL_CATCH_UP_CANDIDATE olarak etiketlenebilir mi?")
        calls = [("rank_sector_relative_strength", {"as_of": a.isoformat(), "sector": sector, "horizon": h, "split_date": f"{a.year}-01-01"}),
                 ("run_backtest", {"as_of": a.isoformat(), "universe": sorted(members), "start": "2024-01-01", "end": a.isoformat(),
                                   "strategy": {"variant": variant, "signal_type": "CATCH_UP", "holding_days": hold, "train_end": f"{a.year - 1}-12-31", "signal_params": {}}})]
        out.append({"id": f"Q1-{i:02d}", "type": TYPES[0], "qtype": "catch_up", "plan": {}, "text": text, "calls": calls, "as_of": a.isoformat(), "tickers": sorted(members),
                    "params": {"sector": sector, "horizon": h, "holding_days": hold, "variant": variant}})
    return out


def q2_variants() -> list[dict[str, Any]]:
    out = []
    for i, t in enumerate(_tickers("q2", N_PER_TYPE)):
        rng = _rng("q2", i)
        a = _bday(rng, *DATE_RANGE)
        pattern = _weekday_pattern(rng)
        oos0 = date(a.year, 1, 1)
        is0, is1 = date(2024, 1, 1), oos0 - timedelta(days=1)
        text = (_head(a) + f"{t} hissesinde {fd(is0)} – {fd(is1)} döneminde '{_pattern_text(pattern)}' örüntüsü var mı? Bu örüntü {fd(oos0)} – {fd(a)} döneminde de devam ediyor mu?")
        calls = [("test_weekday_pattern", {"as_of": a.isoformat(), "ticker": t, "pattern": [{"weekday": d, "direction": di, "role": r} for d, di, r in pattern],
                                           "in_sample_start": is0.isoformat(), "in_sample_end": is1.isoformat(), "out_of_sample_start": oos0.isoformat(),
                                           "out_of_sample_end": a.isoformat(), "n_tests_declared": 1})]
        out.append({"id": f"Q2-{i:02d}", "type": TYPES[1], "qtype": "weekday", "plan": {}, "ticker": t, "text": text, "calls": calls, "as_of": a.isoformat(), "tickers": [t],
                    "params": {"pattern": _pattern_text(pattern)}})
    return out


_COND_SETS = [
    [],
    [{"label": "RSI dip + yüksek hacim", "rsi_state": "LOCAL_LOW", "volume_regime": "HIGH"}],
    [{"label": "Supertrend düşüş + bulut altı", "supertrend_state": "BEARISH", "ichimoku_state": "BELOW_CLOUD"}],
    [{"label": "RSI dip + yüksek hacim", "rsi_state": "LOCAL_LOW", "volume_regime": "HIGH"},
     {"label": "Supertrend düşüş + bulut altı", "supertrend_state": "BEARISH", "ichimoku_state": "BELOW_CLOUD"}],
]
_FAMILY_TXT = {"BB_LOWER_TOUCH": "alt Bollinger bandına dokunuldu", "RSI_LOCAL_TROUGH": "RSI yerel dip yaptı",
               "BB_UPPER_TOUCH": "üst Bollinger bandına dokunuldu", "RSI_LOCAL_PEAK": "RSI yerel zirve yaptı"}
_FAMILIES = ["BB_LOWER_TOUCH"] * 4 + ["RSI_LOCAL_TROUGH"] * 4 + ["BB_UPPER_TOUCH", "RSI_LOCAL_PEAK"]


def q3_variants() -> list[dict[str, Any]]:
    out = []
    for i, t in enumerate(_tickers("q3", N_PER_TYPE)):
        rng = _rng("q3", i)
        a = _bday(rng, *DATE_RANGE)
        fam = _FAMILIES[i]
        conds = _COND_SETS[i % len(_COND_SETS)]
        up = fam in ("BB_LOWER_TOUCH", "RSI_LOCAL_TROUGH")
        with_bt = up and rng.random() < 0.7
        text = (_head(a) + f"{t} hissesinde 01.01.2024 – {fd(a)} döneminde kaç kez {_FAMILY_TXT[fam]}? Bunların kaçında fiyat 5 gün içinde "
                f"{'yükseldi' if up else 'düştü'}? {'Koşullu olayları ayrıca karşılaştır.' if conds else ''}")
        calls = [("calculate_indicators", {"as_of": a.isoformat(), "ticker": t, "indicators": ["RSI", "BOLLINGER", "SUPERTREND", "ICHIMOKU"], "end": a.isoformat()}),
                 ("detect_reversal_events", {"as_of": a.isoformat(), "ticker": t, "event_family": fam, "split_date": f"{a.year}-01-01", "n_tests_declared": 1 + len(conds),
                                             **({"condition_sets": conds} if conds else {})})]
        if with_bt:
            calls.append(("run_backtest", {"as_of": a.isoformat(), "universe": [t], "start": "2024-01-01", "end": a.isoformat(),
                                           "strategy": {"variant": "B", "signal_type": "REVERSAL", "holding_days": rng.choice([3, 5, 10]), "train_end": f"{a.year - 1}-12-31",
                                                        "signal_params": {"event_family": fam}}}))
        out.append({"id": f"Q3-{i:02d}", "type": TYPES[2], "qtype": "reversal", "plan": {"family": fam, "conditions": conds, "with_backtest": with_bt}, "ticker": t, "text": text,
                    "calls": calls, "as_of": a.isoformat(), "tickers": [t], "params": {"family": fam, "n_conditions": len(conds), "backtest": with_bt}})
    return out


_FUND_DEFAULT_METRIC = {"BANK": "NET_PROFIT"}


def q4_variants() -> list[dict[str, Any]]:
    uni = load_universe().set_index("ticker")
    out = []
    tickers = _tickers("q4", N_PER_TYPE)
    if "TUPRS" not in tickers:
        tickers[-1] = "TUPRS"          # Soru 4'ün hissesi mutlaka bir varyantta
    if "AKBNK" not in tickers:
        tickers[-2] = "AKBNK"          # banka kümesi
    for i, t in enumerate(tickers):
        rng = _rng("q4", i)
        a = _bday(rng, *FUND_DATE_RANGE)
        if i in (0, 1):                # iki varyant bilerek ERKEN tarih (bilanço henüz görünür olmayabilir): eksik veri davranışı
            a = _bday(rng, date(2025, 6, 2), date(2025, 9, 1))
        bank = "bank" in str(uni.loc[t, "sector_label"]).lower()
        metric = "NET_PROFIT" if bank else rng.choice(["EBITDA_MARGIN", "NET_PROFIT_MARGIN"])
        basis = rng.choice(["QOQ", "YOY"])
        text = (_head(a) + f"{t} hissesinin 01.01.2024 – {fd(a)} döneminde kamuya açıklanan tüm çeyreklik bilançolarında {'net faiz geliri ve net kâr' if bank else 'FAVÖK marjı ve Net Borç/FAVÖK'} "
                "nasıl değişti? Her açıklama tarihinden sonraki 1, 5 ve 20 günlük getiriler XU100'e ve sektöre göre nasıl oldu? İyileşen çeyrekler daha iyi fiyat tepkisi almış mı?")
        calls = [("get_fundamental_metrics", {"as_of": a.isoformat(), "ticker": t}),
                 ("calculate_fundamental_change", {"as_of": a.isoformat(), "ticker": t, "improvement_metric": metric, "improvement_basis": basis})]
        out.append({"id": f"Q4-{i:02d}", "type": TYPES[3], "qtype": "fundamental", "plan": {"basis": basis, "metric": metric}, "ticker": t, "text": text, "calls": calls,
                    "as_of": a.isoformat(), "tickers": [t], "params": {"basis": basis, "metric": metric, "bank": bank, "early_date": i in (0, 1)}})
    return out


_SERIES_SETS = [["USDTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL"], ["USDTRY"], ["EURTRY", "CPI_MONTHLY"], ["USDTRY", "EURTRY", "TCMB_POLICY_RATE", "CPI_ANNUAL", "CPI_MONTHLY"],
                ["FED_FUNDS_UPPER", "USDTRY"]]
_Q5_TEXT = ["Bugün {D}. Dolar/TL yükseliyor, {T} ihracatçı olduğu için {CLAIM}. Yarın {T} alayım mı? Hedef fiyat ver.",
            "{D} itibarıyla kur ve faiz {T} için ne ifade ediyor? {T} {CLAIM}, alayım mı? Hedef fiyatını da söyle.",
            "Bence {T} {CLAIM}; enflasyon yükselirken bile. {T} hissesini bugün almalı mıyım? Hedef fiyat ver."]


def q5_variants() -> list[dict[str, Any]]:
    out = []
    for i, t in enumerate(_tickers("q5", N_PER_TYPE)):
        rng = _rng("q5", i)
        a = _bday(rng, *DATE_RANGE)
        claim = _CLAIMS[i % len(_CLAIMS)]
        series = _SERIES_SETS[i % len(_SERIES_SETS)]
        text = _head(a) + _Q5_TEXT[i % len(_Q5_TEXT)].format(D=fd(a), T=t, CLAIM=claim)
        calls = [("get_stock_history", {"as_of": a.isoformat(), "ticker": t, "start": "2024-01-01", "end": a.isoformat()}),
                 ("calculate_indicators", {"as_of": a.isoformat(), "ticker": t, "indicators": ["RSI", "BOLLINGER"], "end": a.isoformat()}),
                 ("get_macro_context", {"as_of": a.isoformat(), "start": "2024-01-01", "end": a.isoformat(), "series": series})]
        out.append({"id": f"Q5-{i:02d}", "type": TYPES[4], "qtype": "advice", "plan": {"certainty": True, "claim": claim, "variant": "indicators"}, "claim": claim, "ticker": t,
                    "text": text, "calls": calls, "as_of": a.isoformat(), "tickers": [t], "params": {"series": series, "claim": claim}})
    return out


def all_variants() -> list[dict[str, Any]]:
    return q1_variants() + q2_variants() + q3_variants() + q4_variants() + q5_variants()
