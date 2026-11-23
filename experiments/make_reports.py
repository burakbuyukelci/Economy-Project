"""Senaryo raporları (proje dokümanı §36 teslimatları): gerçek araç çıktılarından OTOMATİK, belirlenimli Markdown raporları.

    python -m experiments.make_reports [--out reports] [--as-of 2026-09-10]

Her sayı doğrudan bir araç çıktısından gelir (kural 6); rapor yeni sayı türetmez, yalnızca sayar (kaç hisse, kaçı anlamlı vb.) ve bunu açıkça "sayım" diye yazar. Hiçbir araç `as_of` sonrası veri görmez.
Çoklu test: her raporda aynı veride denenen TOPLAM test sayısı `n_tests_declared` olarak araca beyan edilir (Bonferroni); tesadüfi bulgu beklentisi ayrıca yazılır.
Raporlar: 01 sektör catch-up, 02 haftanın günü, 03 teknik dönüş, 04 bilanço ve fiyat tepkisi, 05 makro (kur–hisse ilişkisi), 06 backtest ve benchmark özeti.
Kullanım amacı: eğitim/araştırma. Yatırım tavsiyesi ve gelecek getiri garantisi DEĞİLDİR.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from config.settings import MIN_EVENTS
from config.universe import build_sector_peer_groups, load_universe
from tools import calculate_fundamental_change as FC
from tools import detect_reversal_events as DR
from tools import get_macro_context as MC
from tools import rank_sector_relative_strength as RK
from tools import run_backtest as BT
from tools import test_weekday_pattern as WD

DEFAULT_AS_OF = "2026-09-10"
START = "2024-01-01"
FAMILIES = ("BB_LOWER_TOUCH", "BB_UPPER_TOUCH", "RSI_LOCAL_TROUGH", "RSI_LOCAL_PEAK")
PATTERNS = {   # (ad, [(gün, yön, rol)])
    "P1 Pzt–Sal–Çar düşüş → Per–Cum yükseliş": [("MON", "DOWN", "TRIGGER"), ("TUE", "DOWN", "TRIGGER"), ("WED", "DOWN", "TRIGGER"), ("THU", "UP", "OUTCOME"), ("FRI", "UP", "OUTCOME")],
    "P2 Pzt düşüş → Cum yükseliş": [("MON", "DOWN", "TRIGGER"), ("FRI", "UP", "OUTCOME")],
}


def f(x: Any) -> str:
    return "–" if x is None else (f"{x:.4f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x))


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(f(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def header(title: str, as_of: str, scenario: str, versions: str) -> str:
    return (f"# {title}\n\n> **Otomatik üretildi** (`python -m experiments.make_reports`, model yok): her sayı bir araç çıktısındandır; analiz tarihi **{as_of}**, "
            f"veri dönemi {START} – {as_of}. {versions}\n> Eğitim/araştırma amaçlıdır; **yatırım tavsiyesi ve gelecek getiri garantisi değildir**. Senaryo: {scenario}.\n")


def _ok(env: dict[str, Any]) -> dict[str, Any] | None:
    return env["results"] if env["status"] == "OK" else None


def _versions() -> str:
    from tools.get_macro_context import load_macro
    from tools.common import load_snapshot
    s = load_snapshot()
    m = load_macro(s.root)
    try:
        from tools._fundamentals import load_fundamentals
        fv = load_fundamentals().version
    except Exception:
        fv = "?"
    return f"Veri sürümleri: fiyat `{s.data_version}`, bilanço `{fv}`, makro `{m.version}`."


def _tickers() -> list[str]:
    return sorted(load_universe()["ticker"])


# =============================== 01 sektör catch-up ===============================
def report_catch_up(a: str) -> str:
    year = date.fromisoformat(a).year
    groups = {k: sorted(v) for k, v in build_sector_peer_groups().items() if len(v) >= 2}
    rows_s, rows_h, rows_b = [], [], []
    for name, members in sorted(groups.items()):
        r = _ok(RK.run({"as_of": a, "sector": name, "horizon": 20, "split_date": f"{year}-01-01"}))
        if r is None:
            continue
        rk = r["ranking"]
        lag = min(rk, key=lambda x: (x["lag_score_pp"], x["ticker"]))
        rows_s.append([name, ", ".join(members), r["sector_strength"], r["sector_median_vs_xu100_pp"], lag["ticker"], lag["lag_score_pp"], lag["is_laggard"]])
        for h in r["historical_catch_up"]:
            b = h["block"]
            fu, oos = b["full"], b.get("out_of_sample") or {}
            rows_h.append([name, b["horizon"], fu["n_events_complete"], fu["n_false_positive"], fu["hit_rate_pct"], (b.get("baseline") or {}).get("hit_rate_pct"), fu["mean_return_pct"],
                           fu["cost_adjusted_mean_return_pct"], oos.get("n_events_complete"), oos.get("hit_rate_pct"), b.get("oos_degradation_flag"), fu["n_excluded_incomplete_horizon"]])
        for variant in ("A", "B"):
            bt = _ok(BT.run({"as_of": a, "universe": members, "start": START, "end": a,
                             "strategy": {"variant": variant, "signal_type": "CATCH_UP", "holding_days": 5, "train_end": f"{year - 1}-12-31", "signal_params": {}}}))
            if bt is None:
                continue
            n, bm = bt["strategy_net"], {x["name"]: x for x in bt["benchmarks"]}
            rows_b.append([name, variant, bt["n_signals"], n["cumulative_return_pct"], n["sharpe_ratio"], n["max_drawdown_pct"], n["win_rate_pct"],
                           (bm.get("BUY_AND_HOLD") or {}).get("cumulative_return_diff_pct"), (bm.get("XU100") or {}).get("cumulative_return_diff_pct"), bt["oos_degradation_flag"], bt["low_signal_flag"]])
    n_h = len(rows_h)
    fp = sum(r[3] for r in rows_h)
    out = [header("Rapor 01 — Sektör geride kalanı / catch-up", a, "Senaryo 1 (§11)", _versions()),
           "## Yöntem\nPeer grupları `config/universe.csv`'den (en az 2 üyeli 9 grup). Geride kalma: hisse getirisi − grup medyanı (20 işlem günü). Tarihsel catch-up: geride kalma olayları cooldown ile bağımsızlaştırılır, "
           f"ufku `as_of`'u aşan olaylar dışlanır; OOS = {year}-01-01 ve sonrası. Backtest: sinyal kaydırmalı, tur maliyeti 0,5 pp, 5 gün tutma; varyant A (yalnızca sinyal), B (+ sektör gücü filtresi).\n",
           "## 1. Güncel durum (20 işlem günü)\n" + table(["Grup", "Üyeler", "Sektör gücü", "Sektör medyanı − XU100 (pp)", "En çok geride", "Gecikme skoru (pp)", "Eşikte mi"], rows_s) + "\n",
           "## 2. Tarihsel catch-up (havuzlu, tüm üyeler)\n" + table(["Grup", "Ufuk (gün)", "Tamamlanmış olay", "Yanlış pozitif", "İsabet %", "Taban isabet %", "Ort. getiri %", "Maliyet sonrası %", "OOS olay", "OOS isabet %", "OOS bozulma", "Ufku dolmamış dışlanan"], rows_h) + "\n",
           "## 3. Backtest (A/B) ve benchmark farkları\n" + table(["Grup", "Varyant", "Sinyal", "Net kümülatif %", "Sharpe", "Maks. düşüş %", "Kazanma %", "Fark: Al-Tut (pp)", "Fark: XU100 (pp)", "OOS bozulma", "Az sinyal"], rows_b) + "\n",
           f"## Sayımlar\n* {len(rows_s)} grup, {n_h} grup×ufuk bloğu; toplam yanlış pozitif olay: **{fp}** (geride kalıp toparlanmayan olaylar raporlanır).\n"
           f"* Taban isabeti aşan blok sayısı: **{sum(1 for r in rows_h if r[4] is not None and r[5] is not None and r[4] > r[5])}/{n_h}**; OOS bozulma bayrağı olan blok sayısı: **{sum(1 for r in rows_h if r[10])}/{n_h}**.\n"
           f"* `MIN_EVENTS` = {MIN_EVENTS}: bunun altındaki bloklar zayıf kanıttır. Çoklu test: grup × ufuk × varyant denemesi tek düzeltmeyle kapsanmaz (limitations L24–L25).\n",
           "## Yorum sınırı\nSonuçlar ilişki gözlemidir; \"geride kalan toparlanır\" nedensellik iddiası değildir. Sektör gücü ve gecikme eşikleri varsayımdır. 11 hisse tek başına olduğundan sektör karşılaştırması yoktur (L19).\n"]
    return "\n".join(out)


# =============================== 02 haftanın günü ===============================
def report_weekday(a: str) -> str:
    year = date.fromisoformat(a).year
    tickers = _tickers()
    n_tests = len(tickers) * len(PATTERNS)
    sections, summary = [], []
    for pname, pat in PATTERNS.items():
        rows = []
        for t in tickers:
            r = _ok(WD.run({"as_of": a, "ticker": t, "pattern": [{"weekday": d, "direction": di, "role": ro} for d, di, ro in pat], "in_sample_start": START,
                            "in_sample_end": f"{year - 1}-12-31", "out_of_sample_start": f"{year}-01-01", "out_of_sample_end": a, "n_tests_declared": n_tests}))
            if r is None:
                continue
            i, o = r["in_sample"], r["out_of_sample"]
            rows.append([t, i["n_trigger_weeks"], i["n_occurrences"], i["outcome_mean_return_pct"], i["p_value_raw"], i["p_value_adjusted"], o["n_trigger_weeks"], o["n_occurrences"],
                         o["outcome_mean_return_pct"], r["stability_verdict"]])
        raw05 = sum(1 for r in rows if r[4] is not None and r[4] < 0.05)
        adj05 = sum(1 for r in rows if r[5] is not None and r[5] < 0.05)
        stable = sum(1 for r in rows if r[9] == "STABLE")
        summary.append((pname, len(rows), raw05, adj05, stable))
        sections.append(f"## {pname}\n" + table(["Hisse", "IS tetik hafta", "IS gerçekleşme", "IS ort. sonuç getirisi %", "IS ham p", f"IS düzeltilmiş p (×{n_tests})", "OOS tetik hafta", "OOS gerçekleşme", "OOS ort. sonuç getirisi %", "Karar"], rows) + "\n")
    s = ["## Sayımlar (tesadüf beklentisiyle birlikte)", table(["Örüntü", "Test edilen hisse", "IS ham p < 0,05", "Bonferroni sonrası p < 0,05", "STABLE (IS+OOS)"], [list(x) for x in summary]),
         f"\nSadece tesadüfle, {len(tickers)} bağımsız testte ham p < 0,05 için beklenen sayı ≈ {len(tickers) * 0.05:.1f} hisse/örüntüdür. Bu raporda araca beyan edilen toplam test sayısı **{n_tests}** "
         "(30 hisse × 2 örüntü); düzeltilmiş p bununla hesaplanır. Aranan örüntü sayısı arttıkça tesadüfi 'keşif' riski artar (§12)."]
    return "\n".join([header("Rapor 02 — Haftanın günü ve çok günlü örüntüler", a, "Senaryo 2 (§12)", _versions()),
                      f"## Yöntem\nPermütasyon testi (B=10 000, sabit tohum 481), tek yönlü; örneklem içi (IS) {START} – {year - 1}-12-31, örneklem dışı (OOS) {year}-01-01 – {a}. Tatil haftaları dışlanır; son tamamlanmamış hafta `as_of` sonrasına taşarsa dışlanır. "
                      "İşlem maliyeti tetik haftası başına bir kez düşülür. Örüntüler **keşif amaçlı seçilmedi**, dokümandaki örneklerdir.\n", *sections, *s,
                      "\n## Yorum sınırı\nKararlılık = IS'te anlamlı ve OOS'ta aynı yönde. IS'te anlamlı çıkan bir örüntü OOS'ta yoksa tesadüf adayıdır. Hiçbir örüntü tek başına işlem kuralı değildir (L24–L25, L30).\n"])


# =============================== 03 teknik dönüş ===============================
def report_reversal(a: str) -> str:
    year = date.fromisoformat(a).year
    tickers = _tickers()
    n_tests = len(tickers) * len(FAMILIES)
    parts, agg = [], []
    for fam in FAMILIES:
        rows = []
        for t in tickers:
            r = _ok(DR.run({"as_of": a, "ticker": t, "event_family": fam, "split_date": f"{year}-01-01", "n_tests_declared": n_tests}))
            if r is None:
                continue
            g = r["groups"][0]
            blk = next((b for b in g["per_horizon"] if b["horizon"] == 5), None)
            if blk is None:
                continue
            fu = blk["full"]
            rows.append([t, g["n_events_detected"], fu["n_events_complete"], fu["hit_rate_pct"], (blk.get("baseline") or {}).get("hit_rate_pct"), fu["mean_return_pct"],
                         fu["cost_adjusted_mean_return_pct"], fu["n_excluded_incomplete_horizon"], blk.get("oos_degradation_flag")])
        enough = sum(1 for r in rows if r[2] >= MIN_EVENTS)
        above = sum(1 for r in rows if r[2] >= MIN_EVENTS and r[3] is not None and r[4] is not None and r[3] > r[4])
        agg.append([fam, len(rows), sum(r[2] for r in rows), enough, above, sum(1 for r in rows if r[8])])
        parts.append(f"## {fam}: 5 günlük ileri getiri\n" + table(["Hisse", "Tespit edilen olay", "Tamamlanmış olay", "İsabet %", "Taban isabet %", "Ort. getiri %", "Maliyet sonrası %", "Ufku dolmamış dışlanan", "OOS bozulma"], rows) + "\n")
    asels = _ok(DR.run({"as_of": a, "ticker": "ASELS", "event_family": "BB_LOWER_TOUCH", "split_date": f"{year}-01-01", "n_tests_declared": 3,
                        "condition_sets": [{"label": "RSI dip + yüksek hacim", "rsi_state": "LOCAL_LOW", "volume_regime": "HIGH"},
                                           {"label": "Supertrend düşüş + bulut altı", "supertrend_state": "BEARISH", "ichimoku_state": "BELOW_CLOUD"}]}))
    cmp_rows = []
    if asels:
        for g in asels["groups"]:
            blk = next((b for b in g["per_horizon"] if b["horizon"] == 5), None)
            if blk:
                cmp_rows.append([g["label"], g["n_events_detected"], g.get("n_raw_event_days"), blk["full"]["n_events_complete"], blk["full"]["hit_rate_pct"], blk["full"]["mean_return_pct"], blk["full"]["n_excluded_incomplete_horizon"]])
    return "\n".join([header("Rapor 03 — Teknik dönüş olayları", a, "Senaryo 3 (§8, §13)", _versions()),
                      f"## Yöntem\nBollinger (20, 2) alt/üst bant teması ve RSI yerel dip/zirve olayları; ardışık gün serileri tek olaydır (ilk gün); olay `t`'de tespit edilir, ileri getiri `t` kapanışından sonra ölçülür; ufku `as_of`'u aşan olaylar "
                      f"dışlanır. OOS = {year}-01-01 ve sonrası. Beyan edilen toplam test sayısı **{n_tests}** (30 hisse × 4 aile).\n",
                      "## Özet sayımlar\n" + table(["Aile", "Hisse", "Toplam tamamlanmış olay", f"≥ {MIN_EVENTS} olaylı hisse", "…bunların taban isabetini aşanı", "OOS bozulma bayraklı hisse"], agg) + "\n",
                      "## ASELS: tekli ve birleşik koşullar (5 gün, alt Bollinger teması)\n" + table(["Grup", "Tespit edilen olay", "Ham olay günü", "Tamamlanmış olay", "İsabet %", "Ort. getiri %", "Ufku dolmamış dışlanan"], cmp_rows) + "\n",
                      *parts, "## Yorum sınırı\nOlay sayısı `MIN_EVENTS` altında ise (az olay) sonuç zayıf kanıttır; birleşik koşullar olay sayısını daha da küçültür. Bir bandın 'işe yaradığı' iddiası, taban oranla ve OOS ile karşılaştırılmadan yapılamaz (L24, L27).\n"])


# =============================== 04 bilanço ===============================
def report_fundamental(a: str) -> str:
    banks = {t for t, s in load_universe().set_index("ticker")["sector_label"].items() if "bank" in str(s).lower()}
    rows, reac = [], []
    for t in _tickers():
        r = _ok(FC.run({"as_of": a, "ticker": t, "improvement_metric": "NET_PROFIT" if t in banks else "EBITDA_MARGIN", "improvement_basis": "QOQ"}))
        if r is None:
            rows.append([t, 0, "–", "–", "–", "–", "–"])
            continue
        q = max(r["quarters"], key=lambda x: x["fiscal_period"]) if r["quarters"] else None
        mm = {m["name"]: m for m in (q or {}).get("metrics", [])}
        key = "NET_PROFIT" if t in banks else "EBITDA_MARGIN"
        rows.append([t, r["n_quarters_disclosed_by_as_of"], (q or {}).get("fiscal_period"), (q or {}).get("disclosure_date"), (mm.get(key) or {}).get("value"),
                     (mm.get(key) or {}).get("qoq_change"), (mm.get(key) or {}).get("qoq_direction")])
        for s in r["reaction_summary"]:
            if s["group"] == "ALL" and s["horizon"] in (1, 5, 20) and s["n"]:
                reac.append([t, s["horizon"], s["n"], s["mean_abnormal_vs_xu100_pct"], s["hit_rate_vs_xu100_pct"], s["n_excluded_incomplete_horizon"]])
    return "\n".join([header("Rapor 04 — Çeyreklik bilanço değişimi ve açıklama sonrası fiyat tepkisi", a, "Senaryo 4 (§14)", _versions()),
                      "## Yöntem\nBilanço satırları **KAP açıklama tarihine** (bilinmiyorsa dönem sonu + yasal süre) göre hizalanır, dönem sonuna göre değil; yalnızca TMS 29 sonrası dönemler (2025+). Tepki: açıklamadan önceki son kapanıştan 1/5/20 işlem günü sonrası getiri, "
                      "XU100'e göre anormal getiri; pencere `as_of`'u aşarsa dışlanır. Banka için sanayi oranları kullanılmaz (net kâr). Karşılaştırma bir önceki çeyreğe göre (QoQ), mevsim arındırılmamıştır.\n",
                      "## 1. Son açıklanmış çeyrek\n" + table(["Hisse", "Açıklanmış çeyrek", "Son çeyrek", "Açıklama tarihi", "İyileşme metriği değeri", "QoQ değişim", "Yön"], rows) + "\n",
                      "## 2. Açıklama sonrası ortalama anormal getiri (tüm çeyrekler, XU100'e göre)\n" + table(["Hisse", "Ufuk (gün)", "Gözlem (çeyrek)", "Ort. anormal getiri %", "İsabet %", "Ufku dolmamış dışlanan"], reac) + "\n",
                      "## Yorum sınırı\nGözlem sayısı çeyrek sayısıdır (en çok 4–6): istatistik zayıftır ve IS/OOS ayrımı yapılamaz. \"İyi bilanço = fiyat artar\" nedensellik iddiası YAPILMAZ. Yahoo kaynaklı değerler KAP'a karşı doğrulanmamıştır; "
                      "yalnızca TUPRS açıklama tarihleri haber/KAP'tan doğrulandı (L10–L17).\n"])


# =============================== 05 makro ===============================
def report_macro(a: str) -> str:
    year = date.fromisoformat(a).year
    tickers = _tickers()
    n_tests = len(tickers) * 3
    snap = _ok(MC.run({"start": (date.fromisoformat(a) - timedelta(days=75)).isoformat(), "end": a, "as_of": a, "series": ["USDTRY", "EURTRY", "TCMB_FUNDING_COST", "CPI_ANNUAL", "CPI_MONTHLY"]}))
    last = []
    for s in (snap or {}).get("series", []):
        p = max(s["points"], key=lambda x: x["observation_date"])
        last.append([s["series"], p["observation_date"], p["publication_date"], p["value"]])
    rows = []
    for t in tickers:
        rel = [{"ticker": t, "macro_series": "USDTRY", "horizon": 5, "lag_days": 0, "split_date": f"{year}-01-01"},
               {"ticker": t, "macro_series": "USDTRY", "horizon": 5, "lag_days": 5, "split_date": f"{year}-01-01"},
               {"ticker": t, "macro_series": "TCMB_FUNDING_COST", "horizon": 5, "lag_days": 0, "transform": "LEVEL_DIFF", "split_date": f"{year}-01-01"}]
        r = _ok(MC.run({"start": START, "end": a, "as_of": a, "series": ["USDTRY"], "relate_to": rel, "n_tests_declared": n_tests}))
        if r is None:
            continue
        by = {(x["macro_series"], x["lag_days"]): x for x in r["relations"]}      # araç relate_to'yu ALFABETİK sıralar: sıraya değil anahtara güven
        k0, k5, kf = by[("USDTRY", 0)], by[("USDTRY", 5)], by[("TCMB_FUNDING_COST", 0)]
        rows.append([t, k0["full"]["correlation"], k0["full"]["p_value_adjusted"], k5["full"]["correlation"], k5["full"]["p_value_adjusted"],
                     kf["full"]["correlation"], kf["full"]["p_value_adjusted"], k0["oos_degradation_flag"], k0["full"]["n_obs"]])
    sig = [sum(1 for r in rows if r[2 + 2 * k] is not None and r[2 + 2 * k] < 0.05) for k in range(3)]
    pos0 = sum(1 for r in rows if r[1] is not None and r[1] > 0)
    neg0 = sum(1 for r in rows if r[1] is not None and r[1] < 0)
    ereg = next((r for r in rows if r[0] == "EREGL"), None)
    return "\n".join([header("Rapor 05 — Makro bağlam ve kur/faiz–hisse ilişkisi", a, "Makro katman (§15) ve Soru 5", _versions()),
                      "## Yöntem\nMakro seriler TCMB/EVDS'den, **yayın tarihine** göre hizalanır; resmî tatil günleri son gözlemle ileri doldurulur (geriye doldurma yok). İlişki: 5 işlem günlük örtüşmeyen bloklarda kur değişimi (%) ile hisse getirisi; "
                      "eş zamanlı (gecikme 0) ve öncü (gecikme 5) korelasyon; faiz için seviye farkı. **TCMB serisi politika faizi değil, fiili ağırlıklı ortalama fonlama maliyetidir.** "
                      f"Permütasyon p-değeri (B=10 000), Bonferroni için beyan edilen toplam test sayısı **{n_tests}** (30 hisse × 3 ilişki).\n",
                      "## 1. Son gözlemler (analiz tarihi itibarıyla yayımlanmış)\n" + table(["Seri", "Gözlem tarihi", "Yayın tarihi", "Değer"], last) + "\n",
                      "## 2. Hisse bazında ilişki (düzeltilmiş p = ham p × test sayısı)\n" + table(["Hisse", "USDTRY eş zamanlı korelasyon", "düzeltilmiş p", "USDTRY öncü korelasyon", "düzeltilmiş p", "Fonlama maliyeti (fark) korelasyon", "düzeltilmiş p", "OOS bozulma (eş zamanlı)", "Gözlem (blok)"], rows) + "\n",
                      f"## Sayımlar\n* Düzeltme sonrası p < 0,05: USDTRY eş zamanlı **{sig[0]}/{len(rows)}**, USDTRY öncü **{sig[1]}/{len(rows)}**, fonlama maliyeti **{sig[2]}/{len(rows)}**.\n"
                      f"* USDTRY eş zamanlı korelasyon işareti: pozitif **{pos0}**, negatif **{neg0}** hisse (aynı yönde bir 'ihracatçı hisseler kurla yükselir' kuralı yoktur).\n"
                      + (f"* **EREGL (Soru 5)**: USDTRY eş zamanlı korelasyon {f(ereg[1])} (düzeltilmiş p {f(ereg[2])}), öncü {f(ereg[3])} (düzeltilmiş p {f(ereg[4])}). 'Dolar yükselince EREGL kesin yükselir' iddiası doğrulanmaz.\n" if ereg else ""),
                      "## Yorum sınırı\nKorelasyon nedensellik değildir. Kısa örneklem (≈134 blok; OOS ≈33), hisse getirisi enflasyon ve kur rejimine duyarlıdır. Politika faizi serisi veri setinde yoktur (L22, L43)."])


# =============================== 06 backtest özeti ===============================
def report_backtest(a: str) -> str:
    year = date.fromisoformat(a).year
    tickers = _tickers()
    rows = []
    for sig, params in (("REVERSAL BB_LOWER_TOUCH", {"signal_type": "REVERSAL", "signal_params": {"event_family": "BB_LOWER_TOUCH"}}),
                        ("REVERSAL RSI_LOCAL_TROUGH", {"signal_type": "REVERSAL", "signal_params": {"event_family": "RSI_LOCAL_TROUGH"}})):
        for variant in ("A", "B"):
            r = _ok(BT.run({"as_of": a, "universe": tickers, "start": START, "end": a,
                            "strategy": {"variant": variant, "holding_days": 5, "train_end": f"{year - 1}-12-31", **params}}))
            if r is None:
                continue
            n, bm = r["strategy_net"], {x["name"]: x for x in r["benchmarks"]}
            sp = {s["name"]: s for s in r["splits"]}
            rows.append([sig, variant, r["n_signals"], n["cumulative_return_pct"], n["sharpe_ratio"], n["max_drawdown_pct"], n["win_rate_pct"],
                         (bm.get("BUY_AND_HOLD") or {}).get("cumulative_return_diff_pct"), (bm.get("XU100") or {}).get("cumulative_return_diff_pct"),
                         (sp.get("TEST") or {}).get("n_signals"), r["oos_degradation_flag"], r["low_signal_flag"]])
    return "\n".join([header("Rapor 06 — Backtest ve benchmark karşılaştırması (30 hisse, eşit ağırlıklı)", a, "Doğrulama katmanı (§18)", _versions()),
                      f"## Yöntem\nSinyal `t` kapanışında oluşur, giriş `t+1` (sinyal kaydırma); 5 gün tutma; tur maliyeti 0,5 pp (20 + 5 bps × 2); çakışmasız işlem; eşit ağırlıklı portföy. Benchmark: Al-Tut (aynı evren) ve XU100. Eğitim ≤ {year - 1}-12-31, test sonrası.\n",
                      "## Sonuçlar\n" + table(["Sinyal", "Varyant", "Sinyal sayısı", "Net kümülatif %", "Sharpe", "Maks. düşüş %", "Kazanma %", "Fark: Al-Tut (pp)", "Fark: XU100 (pp)", "Test dilimi sinyal", "OOS bozulma", "Az sinyal"], rows) + "\n",
                      "## Yorum sınırı\nBacktest geleceği garanti etmez; getiri/Sharpe ile tahmin doğruluğu farklı kavramlardır. Yalnızca uzun yön; kayma maliyeti varsayımdır (L28). Birden çok sinyal/varyant denendiği için seçim yanlılığı riski vardır (`MULTIPLE_TESTING_RISK`).\n"])


REPORTS: dict[str, Callable[[str], str]] = {
    "01_sektor_catch_up.md": report_catch_up, "02_haftanin_gunu.md": report_weekday, "03_teknik_donus.md": report_reversal,
    "04_bilanco_fiyat_tepkisi.md": report_fundamental, "05_makro_baglam.md": report_macro, "06_backtest_ozeti.md": report_backtest,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Senaryo raporlarını araç çıktılarından üret")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--as-of", default=DEFAULT_AS_OF)
    ap.add_argument("--only", nargs="*", default=None, help="yalnızca bu dosya adları (örn. 05_makro_baglam.md)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in REPORTS.items():
        if args.only and name not in args.only:
            continue
        (out / name).write_text(fn(args.as_of).rstrip("\n") + "\n", encoding="utf-8", newline="\n")
        print(f"yazıldı: {out / name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
