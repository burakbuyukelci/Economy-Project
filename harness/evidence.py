"""Kanıt paketi (build_evidence_bundle) — HARNESS tarafı uygulaması (BİLGİSAYAR 2).

Neden harness'te: kanıt, oturumdaki araç çıktılarından kurulur (hash -> zarf); `tools/` tek tek araç
hesaplar, oturumu bilmez. Sözleşme (schemas) aynıdır: aynı params ve BuildEvidenceBundleResult.

İKİ AŞAMA (docs/harness_design.md):
  1. BUILD_EVIDENCE   : gözlemsel analiz çıktılarından kanıt (E1..En). `version` = 1.
  2. RISK_GATE        : backtest çıktısı AYNI paketin sonuna eklenir (E(n+1)..); `version` = 2; sonra `lock()`.
Kimlik ve numaralama:
  * `analysis_id` oturumdan türetilir (as_of + soru hash'i) ve İKİ AŞAMADA DEĞİŞMEZ; sürüm ayrı alandır.
  * Kanıt id'leri kaynağın İLK işlenişinde atanır ve bir daha değişmez (aşama 2 aşama 1'i yeniden numaralamaz).
  * Aynı params ile tekrar çağrı idempotenttir (yeni kaynak yoksa sürüm artmaz, çıktı aynı).
  * Çıktı yalnızca İSTENEN kaynakların kanıtını içerir; zarf, params ile tutarlı kalır.
Her kanıt değeri ve cümledeki her sayı doğrudan kaynak araç çıktısından alınır (CLAUDE.md kural 6);
harness yeni sayı TÜRETMEZ.

UYARI: kaynak zarflardan biri mock ise paketin data_version'ı da mock sentinelidir (eğitim verisine girmez).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from harness import settings
from harness.mock_tools import is_mock_envelope
from schemas.common import SCHEMA_VERSION
from schemas.enums import AllowedAction, GateStatus, ToolName as T, ToolStatus, WarningCode
from schemas.envelope import make_warning
from schemas.hashing import compute_input_hash
from schemas.registry import validate_envelope, validate_params


def make_analysis_id(as_of: date, question: str) -> str:
    """Oturuma bağlı SABİT kimlik: as_of + soru metninin sha256 öneki."""
    digest = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:12]
    return f"{as_of.isoformat()}-{digest}"


# =============================== zarf deposu ===============================================
@dataclass(frozen=True)
class Record:
    seq: int
    actor: str  # "model" | "harness"
    tool: T
    envelope: dict[str, Any]


class EnvelopeStore:
    """Oturumdaki tüm zarflar (hash -> zarf). Sıra numarası = üretim sırası (determinizm)."""

    def __init__(self) -> None:
        self.records: list[Record] = []
        self._by_hash: dict[str, Record] = {}

    def add(self, envelope: dict[str, Any], actor: str) -> Record:
        rec = Record(len(self.records) + 1, actor, T(envelope["tool"]), envelope)
        self.records.append(rec)
        self._by_hash.setdefault(envelope["input_hash"], rec)  # aynı çağrı = aynı hash = ilk kayıt geçerli
        return rec

    def by_hash(self, input_hash: str) -> Record | None:
        return self._by_hash.get(input_hash)


# =============================== başlık bölümleri (veri) ====================================
HEADLINES_PATH = Path(__file__).resolve().parent / "evidence_headlines.json"


@lru_cache(maxsize=1)
def headline_spec() -> dict[str, dict[str, list[str]]]:
    """Araç başına {"headline": [...], "context": [...], "excluded": [...]} (harness/evidence_headlines.json)."""
    return json.loads(HEADLINES_PATH.read_text(encoding="utf-8"))["tools"]


def is_headline(tool: T, section: str) -> bool:
    """Bölüm aracın başlık listesindeyse committed; listede olmayan/bildirilmemiş bölüm yalnızca full sette kalır."""
    return section in (headline_spec().get(tool.value) or {}).get("headline", [])


# =============================== çıkarıcılar ================================================
@dataclass
class Candidate:
    statement: str
    values: list[dict[str, Any]]
    section: str  # çıkarıcının verdiği bölüm adı; committed olup olmadığını harness/evidence_headlines.json belirler


def _v(name: str, value: Any, unit: str | None = None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        value = "true" if value else "false"
    return {"name": name, "value": value, "unit": unit}


def _vals(*pairs: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [p for p in pairs if p is not None]


def _fmt(x: Any) -> str:
    """Sayıyı kaynakta göründüğü gibi yazar (yuvarlama YOK; doğrulayıcı birebir eşleştirebilsin)."""
    if isinstance(x, bool):
        return "true" if x else "false"
    return "yok" if x is None else str(x)


def _rank_sector(res: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    h = res.get("horizon")
    out.append(Candidate(
        f"{res.get('sector')} grubu, {_fmt(h)} işlem günü: sektör medyan getirisi %{_fmt(res.get('sector_median_return_pct'))}, "
        f"XU100 %{_fmt(res.get('xu100_return_pct'))}, fark {_fmt(res.get('sector_median_vs_xu100_pp'))} pp, "
        f"sektör gücü {res.get('sector_strength')}",
        _vals(_v("sector_median_return_pct", res.get("sector_median_return_pct"), "pct"),
              _v("xu100_return_pct", res.get("xu100_return_pct"), "pct"),
              _v("sector_median_vs_xu100_pp", res.get("sector_median_vs_xu100_pp"), "pp"),
              _v("sector_strength", res.get("sector_strength"))), "sector"))
    ranking = res.get("ranking") or []
    if ranking:
        lag = min(ranking, key=lambda r: (r.get("lag_score_pp") is None, r.get("lag_score_pp")))
        flag = "geride kalan" if lag.get("is_laggard") else "geride kalan eşiğinde değil"
        out.append(Candidate(
            f"{lag.get('ticker')}: {_fmt(h)} işlem günü getirisi %{_fmt(lag.get('return_pct'))}, sektör medyanına göre "
            f"{_fmt(lag.get('lag_score_pp'))} pp ({flag}), sıra {_fmt(lag.get('rank'))}",
            _vals(_v("return_pct", lag.get("return_pct"), "pct"), _v("lag_score_pp", lag.get("lag_score_pp"), "pp"),
                  _v("rank", lag.get("rank"))), "laggard"))
    for row in res.get("historical_catch_up") or []:
        blk = row.get("block") or {}
        full = blk.get("full") or {}
        out.append(Candidate(
            f"Geçmiş geride kalma, ufuk {_fmt(blk.get('horizon'))}: tamamlanmış olay {_fmt(full.get('n_events_complete'))}, "
            f"başarı {_fmt(full.get('n_success'))}, yanlış pozitif {_fmt(full.get('n_false_positive'))}, "
            f"isabet %{_fmt(full.get('hit_rate_pct'))}, medyan kapanma {_fmt(row.get('median_catch_up_size_pp'))} pp, "
            f"örneklem dışı bozulma işareti {_fmt(blk.get('oos_degradation_flag'))}",
            _vals(_v("horizon", blk.get("horizon")), _v("n_events_complete", full.get("n_events_complete")),
                  _v("n_success", full.get("n_success")), _v("n_false_positive", full.get("n_false_positive")),
                  _v("hit_rate_pct", full.get("hit_rate_pct"), "pct"),
                  _v("median_catch_up_size_pp", row.get("median_catch_up_size_pp"), "pp"),
                  _v("oos_degradation_flag", blk.get("oos_degradation_flag"))), "historical_catch_up"))
    return out


def _reversal(res: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    fam = res.get("event_family")
    for g in res.get("groups") or []:
        label = g.get("label")
        out.append(Candidate(f"{fam} ({label}): tespit edilen olay {_fmt(g.get('n_events_detected'))}",
                             _vals(_v("n_events_detected", g.get("n_events_detected"))), "group_count"))
        for blk in g.get("per_horizon") or []:
            f = blk.get("full") or {}
            out.append(Candidate(
                f"{fam} ({label}), ufuk {_fmt(blk.get('horizon'))}: tamamlanmış olay {_fmt(f.get('n_events_complete'))}, "
                f"başarı {_fmt(f.get('n_success'))}, isabet %{_fmt(f.get('hit_rate_pct'))}, "
                f"ortalama getiri %{_fmt(f.get('mean_return_pct'))}, maliyet sonrası %{_fmt(f.get('cost_adjusted_mean_return_pct'))}, "
                f"ufku dolmamış dışlanan {_fmt(f.get('n_excluded_incomplete_horizon'))}",
                _vals(_v("horizon", blk.get("horizon")), _v("n_events_complete", f.get("n_events_complete")),
                      _v("n_success", f.get("n_success")), _v("hit_rate_pct", f.get("hit_rate_pct"), "pct"),
                      _v("mean_return_pct", f.get("mean_return_pct"), "pct"),
                      _v("cost_adjusted_mean_return_pct", f.get("cost_adjusted_mean_return_pct"), "pct"),
                      _v("n_excluded_incomplete_horizon", f.get("n_excluded_incomplete_horizon"))), "per_horizon"))
        for rb in g.get("regime_breakdown") or []:
            out.append(Candidate(
                f"{fam} ({label}), rejim {rb.get('regime')}, ufuk {_fmt(rb.get('horizon'))}: olay {_fmt(rb.get('n_events'))}, "
                f"isabet %{_fmt(rb.get('hit_rate_pct'))}",
                _vals(_v("horizon", rb.get("horizon")), _v("n_events", rb.get("n_events")),
                      _v("hit_rate_pct", rb.get("hit_rate_pct"), "pct")), "regime_breakdown"))
    return out


def _weekday(res: dict[str, Any]) -> list[Candidate]:
    label = res.get("pattern_label")
    out = [Candidate(
        f"{label}: kararlılık hükmü {res.get('stability_verdict')}, kodlar {', '.join(res.get('verdict_codes') or []) or 'yok'}",
        _vals(_v("stability_verdict", res.get("stability_verdict")), _v("verdict_reason", res.get("verdict_reason"))),
        "verdict")]
    for key, name in (("in_sample", "Örneklem içi"), ("out_of_sample", "Örneklem dışı")):
        w = res.get(key) or {}
        out.append(Candidate(
            f"{label}, {name}: tetik hafta {_fmt(w.get('n_trigger_weeks'))}, gerçekleşme {_fmt(w.get('n_occurrences'))}, "
            f"sonuç ortalama getirisi %{_fmt(w.get('outcome_mean_return_pct'))}, koşulsuza fark "
            f"{_fmt(w.get('outcome_mean_diff_vs_unconditional_pct'))}, maliyet sonrası %{_fmt(w.get('cost_adjusted_outcome_mean_return_pct'))}, "
            f"düzeltilmiş p {_fmt(w.get('p_value_adjusted'))}",
            _vals(_v("n_trigger_weeks", w.get("n_trigger_weeks")), _v("n_occurrences", w.get("n_occurrences")),
                  _v("outcome_mean_return_pct", w.get("outcome_mean_return_pct"), "pct"),
                  _v("outcome_mean_diff_vs_unconditional_pct", w.get("outcome_mean_diff_vs_unconditional_pct"), "pct"),
                  _v("cost_adjusted_outcome_mean_return_pct", w.get("cost_adjusted_outcome_mean_return_pct"), "pct"),
                  _v("p_value_adjusted", w.get("p_value_adjusted"))), "window"))
    return out


def _fundamental_change(res: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    quarters = res.get("quarters") or []
    if quarters:
        latest = max(quarters, key=lambda q: q.get("fiscal_period") or "")
        for m in latest.get("metrics") or []:
            out.append(Candidate(
                f"{res.get('ticker')} {latest.get('fiscal_period')}: {m.get('name')} {_fmt(m.get('value'))}, "
                f"yıllık değişim {_fmt(m.get('yoy_change'))} {m.get('change_unit')}, yön {m.get('yoy_direction')}",
                _vals(_v("fiscal_period", latest.get("fiscal_period")), _v("disclosure_date", latest.get("disclosure_date")),
                      _v(str(m.get("name")), m.get("value")), _v("yoy_change", m.get("yoy_change"), m.get("change_unit")),
                      _v("qoq_change", m.get("qoq_change"), m.get("change_unit"))), "latest_metrics"))
    out.append(Candidate(
        f"Açıklanmış çeyrek {_fmt(res.get('n_quarters_disclosed_by_as_of'))}, henüz açıklanmadığı için dışlanan "
        f"{_fmt(res.get('n_quarters_excluded_not_yet_disclosed'))}",
        _vals(_v("n_quarters_disclosed_by_as_of", res.get("n_quarters_disclosed_by_as_of")),
              _v("n_quarters_excluded_not_yet_disclosed", res.get("n_quarters_excluded_not_yet_disclosed"))), "disclosure_counts"))
    for r in res.get("reaction_summary") or []:
        out.append(Candidate(
            f"Açıklama sonrası ufuk {_fmt(r.get('horizon'))}, grup {r.get('group')}: gözlem {_fmt(r.get('n'))}, XU100'e göre "
            f"ortalama anormal getiri %{_fmt(r.get('mean_abnormal_vs_xu100_pct'))}, isabet %{_fmt(r.get('hit_rate_vs_xu100_pct'))}, "
            f"ufku dolmamış dışlanan {_fmt(r.get('n_excluded_incomplete_horizon'))}",
            _vals(_v("horizon", r.get("horizon")), _v("n", r.get("n")),
                  _v("mean_abnormal_vs_xu100_pct", r.get("mean_abnormal_vs_xu100_pct"), "pct"),
                  _v("hit_rate_vs_xu100_pct", r.get("hit_rate_vs_xu100_pct"), "pct"),
                  _v("n_excluded_incomplete_horizon", r.get("n_excluded_incomplete_horizon"))), "reaction_summary"))
    return out


def _fundamental_metrics(res: dict[str, Any]) -> list[Candidate]:
    return [Candidate(
        f"{res.get('ticker')} {res.get('fiscal_period')}: {m.get('name')} {_fmt(m.get('value'))} {m.get('unit') or ''}".rstrip(),
        _vals(_v("fiscal_period", res.get("fiscal_period")), _v("disclosure_date", res.get("disclosure_date")),
              _v(str(m.get("name")), m.get("value"), m.get("unit"))), "metrics") for m in res.get("metrics") or []]


def _macro(res: dict[str, Any]) -> list[Candidate]:
    out: list[Candidate] = []
    for s in res.get("series") or []:
        pts = s.get("points") or []
        if not pts:
            continue
        last = max(pts, key=lambda p: p.get("observation_date") or "")
        out.append(Candidate(
            f"{s.get('series')} son gözlem değeri {_fmt(last.get('value'))} ({s.get('source')})",
            _vals(_v("value", last.get("value")), _v("observation_date", last.get("observation_date")),
                  _v("publication_date", last.get("publication_date"))), "latest_point"))
    return out


def _news(res: dict[str, Any]) -> list[Candidate]:
    out = [Candidate(f"Haber/KAP olay sayısı {_fmt(res.get('n_events_returned'))}",
                     _vals(_v("n_events_returned", res.get("n_events_returned"))), "count")]
    for e in (res.get("events") or [])[:10]:
        out.append(Candidate(f"{e.get('source')}: {e.get('headline')}",
                             _vals(_v("event_id", e.get("event_id")), _v("published_date", e.get("published_date")),
                                   _v("category", e.get("category"))), "events"))
    return out


def _speech(res: dict[str, Any]) -> list[Candidate]:
    return [Candidate(f"Konuşma özellikleri yüklendi (kaynak {res.get('source_id')}), transkript kalitesi "
                      f"{_fmt(res.get('transcript_quality'))}",
                      _vals(_v("source_id", res.get("source_id")), _v("transcript_quality", res.get("transcript_quality"))),
                      "summary")]


def _indicators(res: dict[str, Any]) -> list[Candidate]:
    """schemas 1.1.0: sayılar `latest.values`, kategoriler `latest.states` (as_of günündeki durum).

    `latest` başlık bölümüdür (committed); `recent_rows` kasıtlı olarak kanıta HİÇ girmez (evidence_headlines.json: excluded)."""
    latest = res.get("latest")
    if not latest:
        return []
    numbers = {k: v for k, v in sorted((latest.get("values") or {}).items()) if v is not None}
    states = {k: v for k, v in sorted((latest.get("states") or {}).items()) if v is not None}
    shown = ", ".join([f"{k} {_fmt(v)}" for k, v in numbers.items()] + [f"{k} {v}" for k, v in states.items()])
    vals = [_v("close", latest.get("close"))] + [_v(k, v) for k, v in numbers.items()] + [_v(k, v) for k, v in states.items()]
    return [Candidate(f"{res.get('ticker')} son gün göstergeleri: kapanış {_fmt(latest.get('close'))}, {shown}",
                      _vals(*vals), "latest")]


def _support_resistance(res: dict[str, Any]) -> list[Candidate]:
    return [Candidate(
        f"{res.get('ticker')} son kapanış {_fmt(res.get('last_close'))}, en yakın destek {_fmt(res.get('nearest_support'))}, "
        f"en yakın direnç {_fmt(res.get('nearest_resistance'))}",
        _vals(_v("last_close", res.get("last_close")), _v("nearest_support", res.get("nearest_support")),
              _v("nearest_resistance", res.get("nearest_resistance"))), "levels")]


def _backtest(res: dict[str, Any]) -> list[Candidate]:
    strat = res.get("strategy") or {}
    net = res.get("strategy_net") or {}
    out = [Candidate(
        f"Backtest varyant {strat.get('variant')} ({strat.get('signal_type')}), maliyet sonrası: kümülatif getiri "
        f"%{_fmt(net.get('cumulative_return_pct'))}, Sharpe {_fmt(net.get('sharpe_ratio'))}, maksimum düşüş "
        f"%{_fmt(net.get('max_drawdown_pct'))}, isabet %{_fmt(net.get('win_rate_pct'))}, işlem {_fmt(net.get('n_trades'))}",
        _vals(_v("variant", strat.get("variant")), _v("cumulative_return_pct", net.get("cumulative_return_pct"), "pct"),
              _v("sharpe_ratio", net.get("sharpe_ratio")), _v("max_drawdown_pct", net.get("max_drawdown_pct"), "pct"),
              _v("win_rate_pct", net.get("win_rate_pct"), "pct"), _v("n_trades", net.get("n_trades"))), "strategy_net")]
    for b in res.get("benchmarks") or []:
        out.append(Candidate(
            f"Backtest, {b.get('name')} karşılaştırması: kümülatif getiri farkı {_fmt(b.get('cumulative_return_diff_pct'))}, "
            f"Sharpe farkı {_fmt(b.get('sharpe_diff'))}",
            _vals(_v("cumulative_return_diff_pct", b.get("cumulative_return_diff_pct"), "pct"),
                  _v("sharpe_diff", b.get("sharpe_diff"))), "benchmarks"))
    for sp in res.get("splits") or []:
        nm = sp.get("net_metrics") or {}
        out.append(Candidate(
            f"Backtest {sp.get('name')} bölümü: sinyal {_fmt(sp.get('n_signals'))}, net kümülatif getiri "
            f"%{_fmt(nm.get('cumulative_return_pct'))}, benchmark farkı {_fmt(sp.get('benchmark_diff_pct'))}",
            _vals(_v("n_signals", sp.get("n_signals")), _v("cumulative_return_pct", nm.get("cumulative_return_pct"), "pct"),
                  _v("benchmark_diff_pct", sp.get("benchmark_diff_pct"), "pct")), "splits"))
    out.append(Candidate(
        f"Backtest bayrakları: örneklem dışı bozulma {_fmt(res.get('oos_degradation_flag'))}, az sinyal "
        f"{_fmt(res.get('low_signal_flag'))}, sinyal {_fmt(res.get('n_signals'))}, ufku dolmamış dışlanan "
        f"{_fmt(res.get('n_excluded_incomplete_horizon'))}",
        _vals(_v("oos_degradation_flag", res.get("oos_degradation_flag")), _v("low_signal_flag", res.get("low_signal_flag")),
              _v("n_signals", res.get("n_signals")),
              _v("n_excluded_incomplete_horizon", res.get("n_excluded_incomplete_horizon"))), "flags"))
    return out


EXTRACTORS: dict[T, Callable[[dict[str, Any]], list[Candidate]]] = {
    T.RANK_SECTOR_RELATIVE_STRENGTH: _rank_sector,
    T.DETECT_REVERSAL_EVENTS: _reversal,
    T.TEST_WEEKDAY_PATTERN: _weekday,
    T.CALCULATE_FUNDAMENTAL_CHANGE: _fundamental_change,
    T.GET_FUNDAMENTAL_METRICS: _fundamental_metrics,
    T.GET_MACRO_CONTEXT: _macro,
    T.GET_NEWS_EVENTS: _news,
    T.GET_SPEECH_FEATURES: _speech,
    T.CALCULATE_INDICATORS: _indicators,
    T.FIND_SUPPORT_RESISTANCE: _support_resistance,
    T.RUN_BACKTEST: _backtest,
    # get_stock_history / get_index_history (ham veri), check_data_quality (kapı) kanıt cümlesi üretmez.
}


# =============================== paket ======================================================
def _action_for_gate(gate: str | None) -> str | None:
    """Kapıdan çıkan EN AZ önerilen eylem; asıl eylemi model seçer, action_guard denetler."""
    if gate in (GateStatus.HARD_BLOCK.value, GateStatus.ANALYSIS_UNSAFE.value):
        return AllowedAction.ANALYSIS_UNSAFE.value
    if gate == GateStatus.INVESTIGATE.value:
        return AllowedAction.INVESTIGATE.value
    return None


def _merge_data_version(versions: list[str]) -> tuple[str, bool]:
    if any(v == settings.MOCK_DATA_VERSION for v in versions):
        return settings.MOCK_DATA_VERSION, False  # mock bulaşır
    unique = sorted(set(versions))
    return unique[-1], len(unique) > 1


class EvidenceBundle:
    def __init__(self, analysis_id: str, store: EnvelopeStore) -> None:
        self.analysis_id = analysis_id
        self.store = store
        self.version = 0
        self.locked = False
        self.lock_hash: str | None = None
        self.gate_status: str | None = None
        self.proposed_action: str | None = None
        self._items: list[dict[str, Any]] = []
        self._committed: set[str] = set()
        self._processed: set[str] = set()

    # ---- aşama 1 ve 2: aynı çağrı, genişleyen kaynak kümesi -----------------------------------
    def build(self, params: dict[str, Any]) -> dict[str, Any]:
        parsed = validate_params(T.BUILD_EVIDENCE_BUNDLE, params)  # şema hatası -> ValidationError (oturum önceden doğrular)
        norm = parsed.model_dump(mode="json")
        if norm["analysis_id"] != self.analysis_id:
            return self._error(norm, "ANALYSIS_ID_MISMATCH",
                               f"analysis_id oturumunkiyle ({self.analysis_id}) aynı olmalı")
        if self.locked:
            return self._error(norm, "BUNDLE_LOCKED", "kanıt paketi kilitlendi; değiştirilemez")
        records: list[Record] = []
        for h in norm["source_input_hashes"]:
            rec = self.store.by_hash(h)
            if rec is None:
                return self._error(norm, "UNKNOWN_SOURCE_HASH", f"oturumda böyle bir araç çıktısı yok: {h}")
            if rec.tool == T.BUILD_EVIDENCE_BUNDLE:
                return self._error(norm, "INVALID_SOURCE_TOOL", "kanıt paketi başka bir kanıt paketini kaynak alamaz")
            records.append(rec)
        records.sort(key=lambda r: r.seq)  # üretim sırası: deterministik numaralama

        added = False
        for rec in records:
            h = rec.envelope["input_hash"]
            if h in self._processed:
                continue
            self._ingest(rec)
            self._processed.add(h)
            added = True
        if added:
            self.version += 1
        return self._envelope(norm, records)

    def _ingest(self, rec: Record) -> None:
        env = rec.envelope
        if env.get("status") != ToolStatus.OK.value:
            return  # hata zarfı kanıt üretmez
        extractor = EXTRACTORS.get(rec.tool)
        for cand in (extractor(env["results"]) if extractor else []):
            eid = f"E{len(self._items) + 1}"
            self._items.append({"evidence_id": eid, "statement": cand.statement, "source_tool": rec.tool.value,
                                "source_input_hash": env["input_hash"], "values": cand.values})
            if is_headline(rec.tool, cand.section):
                self._committed.add(eid)

    def _envelope(self, norm: dict[str, Any], records: list[Record]) -> dict[str, Any]:
        requested = {r.envelope["input_hash"] for r in records}
        full = [i for i in self._items if i["source_input_hash"] in requested]
        committed = [i for i in full if i["evidence_id"] in self._committed]
        gate = None
        for r in records:  # son (en büyük seq) başarılı kapı zarfı
            if r.tool == T.CHECK_DATA_QUALITY and r.envelope.get("status") == ToolStatus.OK.value:
                gate = r.envelope["results"].get("gate_status")
        dv, mismatch = _merge_data_version([r.envelope["data_version"] for r in records])
        warnings: list[str] = []
        for r in records:
            for w in r.envelope.get("warnings") or []:
                if w not in warnings:
                    warnings.append(w)
        if mismatch:
            warnings.append(make_warning(WarningCode.DATA_VERSION_MISMATCH,
                                         "kaynak araç çıktıları farklı veri sürümlerinden"))
        env = {
            "tool": T.BUILD_EVIDENCE_BUNDLE.value, "schema_version": SCHEMA_VERSION, "params": norm,
            "as_of": norm["as_of"], "data_version": dv,
            "input_hash": compute_input_hash(T.BUILD_EVIDENCE_BUNDLE.value, norm, dv),
            "results": {"analysis_id": self.analysis_id, "full_evidence_set": full, "committed_evidence_set": committed,
                        "gate_status": gate, "proposed_action": _action_for_gate(gate)},
            "n_events": len(full), "n_excluded_incomplete_horizon": 0, "warnings": warnings,
            "status": ToolStatus.OK.value, "error": None,
        }
        validate_envelope(env)
        return env

    def _error(self, norm: dict[str, Any], code: str, message: str) -> dict[str, Any]:
        dv = self.store.records[0].envelope["data_version"] if self.store.records else settings.MOCK_DATA_VERSION
        env = {
            "tool": T.BUILD_EVIDENCE_BUNDLE.value, "schema_version": SCHEMA_VERSION, "params": norm,
            "as_of": norm["as_of"], "data_version": dv,
            "input_hash": compute_input_hash(T.BUILD_EVIDENCE_BUNDLE.value, norm, dv),
            "results": None, "n_events": None, "n_excluded_incomplete_horizon": 0, "warnings": [],
            "status": ToolStatus.ERROR.value, "error": {"code": code, "message": message},
        }
        validate_envelope(env)
        return env

    # ---- kilit ---------------------------------------------------------------------------------
    def lock(self, gate_status: str | None) -> str:
        """Paketi KİLİTLER (RISK_GATE sonrası). Aynı kapıyla tekrar çağrı idempotenttir."""
        if self.locked:
            if gate_status != self.gate_status:
                raise ValueError("kilitli paket başka bir kapı durumuyla yeniden kilitlenemez")
            return self.lock_hash  # type: ignore[return-value]
        self.gate_status = gate_status
        self.proposed_action = _action_for_gate(gate_status)
        payload = {
            "analysis_id": self.analysis_id, "version": self.version, "gate_status": gate_status,
            "committed": [i for i in self._items if i["evidence_id"] in self._committed],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.lock_hash = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        self.locked = True
        return self.lock_hash

    def snapshot(self) -> dict[str, Any]:
        committed = [i for i in self._items if i["evidence_id"] in self._committed]
        return {
            "analysis_id": self.analysis_id, "version": self.version, "locked": self.locked,
            "lock_hash": self.lock_hash, "gate_status": self.gate_status, "proposed_action": self.proposed_action,
            "n_full": len(self._items), "n_committed": len(committed),
            "full_evidence_set": [dict(i) for i in self._items], "committed_evidence_set": committed,
        }
