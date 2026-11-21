"""Etiket politikası: kilitli kanıt + kapı sonucu -> İZİNLİ EYLEM (deterministik, kural kodda; model yalnızca açıklar).

Tasarım ilkesi (CLAUDE.md): LLM yorumlar, Python hesaplar, harness kontrol eder. Bu modül harness'in "hangi etiket verilebilir"
kararıdır; eğitim verisi üretimi, değerlendirme ve canlı test AYNI politikayı kullanır. Eylem koruması (action_guard) modelin
etiketini bu politikanınkiyle karşılaştırır (`check_final_output(..., required_action=decision.label)`).

Kural tablosu ve gerekçeler: docs/harness_design.md bölüm 11. Özet (ilk eşleşen kazanır):
  G1 kapı HARD_BLOCK/ANALYSIS_UNSAFE            -> ANALYSIS_UNSAFE
  G2 kapı yok/bilinmiyor                        -> INVESTIGATE (güvenli varsayılan)
  senaryo kuralları (C: catch-up, W: haftanın günü, T: teknik dönüş, F: temel veri), her biri bir etiket üretir
  G3 kapı INVESTIGATE: yalnızca ADAY etiketler INVESTIGATE'e düşer (HOLD/WATCH/REJECT_SIGNAL aynen geçer)
  G5 senaryo etiketlerini en temkinli kazanacak biçimde birleştirir (aşağıda CAUTION_ORDER; özel durumlar)
  G6 tavsiye niyeti (soruda al/sat/hedef fiyat): aday etiketler ve HOLD -> WATCH
  G7 senaryo aracı yok: INVESTIGATE (soruda doğrulanmamış kesinlik iddiası varsa gerekçesi ayrı)

Politika zarflardaki `results`'tan okur (kilitli paketin kaynak zarfları); her kural kontrolü `Check` olarak araç/hash/alan yolunu taşır.
İsabet oranının standart hatası yalnızca BİLGİ olarak checks'e yazılır (kural değildir). Aday etiketlerde "tarihsel gözlem, örnek küçük,
belirsizlik var" notu ZORUNLUDUR. Temel veri (F1–F4) eşikleri GEÇİCİDİR: gerçek veri gelince gözden geçirilecek.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Sequence

import numpy as np

import config.settings as cfg
from harness import settings
from harness.action_guard import find_advice_language, load_lexicon, tr_fold
from schemas.enums import AllowedAction as A

# =============================== sabitler ===============================
CU, TR, FI = A.POTENTIAL_CATCH_UP_CANDIDATE, A.TECHNICAL_REVERSAL_CANDIDATE, A.FUNDAMENTAL_IMPROVEMENT_CANDIDATE
CANDIDATE_LABELS = frozenset({CU, TR, FI})
# En temkinliden en az temkinliye: önce gelen kazanır. Adaylar en sonda (en az temkinli); aralarında sıra anlamsızdır.
CAUTION_ORDER: tuple[A, ...] = (A.ANALYSIS_UNSAFE, A.INVESTIGATE, A.REJECT_SIGNAL, A.WATCH, A.HOLD, CU, TR, FI)
_RANK = {label: i for i, label in enumerate(CAUTION_ORDER)}

UNSAFE_GATES = frozenset({"HARD_BLOCK", "ANALYSIS_UNSAFE"})
CANDIDATE_GATES = frozenset({"PASS", "PASS_WITH_WARNINGS"})
VALID_GATES = CANDIDATE_GATES | UNSAFE_GATES | {"INVESTIGATE"}

RULE_IDS = frozenset({
    "G1_GATE_UNSAFE", "G2_GATE_MISSING", "G3_GATE_INVESTIGATE", "G5_COMBINE", "G5_CANDIDATE_VS_REJECT",
    "G5_DIFFERENT_CANDIDATES", "G6_ADVICE_CAP", "G7_NO_SCENARIO", "G7_UNVERIFIED_CLAIM",
    "C1_PEERS_OR_STRENGTH", "C2_NOT_LAGGARD", "C3_FEW_EVENTS", "C4_REJECT_HISTORY", "C5_CANDIDATE", "C6_VALIDATION_MISSING",
    "C7_WATCH",
    "W1_STABLE", "W2_INSUFFICIENT", "W3_UNSTABLE",
    "T0_NO_PRIMARY_GROUP", "T6_NO_EVENTS", "T1_FEW_EVENTS", "T2_REJECT_HISTORY", "T4_VALIDATION_MISSING", "T3_CANDIDATE", "T5_WATCH",
    "F1_INSUFFICIENT", "F2_REJECT", "F3_CANDIDATE", "F4_WATCH",
})

CAVEAT_TEXT = ("Tarihsel gözlem: örnek küçük, belirsizlik var (isabet oranı standart hatası checks içinde bilgi olarak yazılıdır); "
               "geçmiş kanıt gelecek getiri garantisi değildir.")
_NO_TOOLS = frozenset({"build_evidence_bundle", "check_data_quality"})
_SCENARIO_ORDER = {"CATCH_UP": 0, "WEEKDAY": 1, "REVERSAL": 2, "FUNDAMENTAL": 3}


# =============================== tipler ===============================
@dataclass(frozen=True)
class PolicyThresholds:
    """Eşikler: settings.py (POLICY_*) ve config.settings (MIN_EVENTS vb.) çağrı anında okunur (ekip değiştirirse yansır)."""

    hit_margin_pp: float = field(default_factory=lambda: settings.POLICY_HIT_MARGIN_PP)
    min_passing_horizons: int = field(default_factory=lambda: settings.POLICY_MIN_PASSING_HORIZONS)
    min_peers: int = field(default_factory=lambda: settings.POLICY_MIN_PEERS)
    min_quarters: int = field(default_factory=lambda: settings.POLICY_MIN_QUARTERS)          # GEÇİCİ (temel veri)
    signal_recency_trading_days: int = field(default_factory=lambda: settings.POLICY_SIGNAL_RECENCY_TRADING_DAYS)
    min_events: int = field(default_factory=lambda: cfg.MIN_EVENTS)
    min_oos_events: int = field(default_factory=lambda: cfg.MIN_OOS_EVENTS)


@dataclass(frozen=True)
class Check:
    id: str
    description: str
    ok: bool | None          # None => bilgi (kural değil)
    actual: Any
    threshold: Any = None
    tool: str | None = None
    input_hash: str | None = None
    path: str | None = None
    info: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("id", "description", "ok", "actual", "threshold", "tool", "input_hash", "path", "info")}


@dataclass(frozen=True)
class Reason:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class ScenarioDecision:
    scenario: str                # CATCH_UP | WEEKDAY | REVERSAL | FUNDAMENTAL
    tool: str
    input_hash: str
    subject: str | None
    label: A                     # G3 sonrası
    rule_id: str
    raw_label: A                 # G3 öncesi (kural tablosunun ürettiği)
    base_rule_id: str
    provisional: bool = False
    checks: list[Check] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)

    def check(self, check_id: str) -> Check:
        return next(c for c in self.checks if c.id == check_id)

    def to_dict(self) -> dict[str, Any]:
        return {"scenario": self.scenario, "tool": self.tool, "input_hash": self.input_hash, "subject": self.subject,
                "label": self.label.value, "rule_id": self.rule_id, "raw_label": self.raw_label.value,
                "base_rule_id": self.base_rule_id, "provisional": self.provisional,
                "checks": [c.to_dict() for c in self.checks], "reasons": [r.to_dict() for r in self.reasons]}


@dataclass
class PolicyDecision:
    label: A
    rule_id: str
    gate_status: str | None
    advice_intent: bool
    certainty_claim: bool
    scenarios: list[ScenarioDecision] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)

    @property
    def checks(self) -> list[Check]:
        out = [Check("gate_status", "kalite kapısı sonucu", None, self.gate_status, info=True)]
        for s in self.scenarios:
            out.extend(s.checks)
        return out

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label.value, "rule_id": self.rule_id, "gate_status": self.gate_status,
                "advice_intent": self.advice_intent, "certainty_claim": self.certainty_claim,
                "scenarios": [s.to_dict() for s in self.scenarios], "reasons": [r.to_dict() for r in self.reasons],
                "trace": list(self.trace)}


# =============================== G5: birleştirme ===============================
def combine_scenario_labels(items: Sequence[tuple[A | str, str | None]]) -> tuple[A, str]:
    """(etiket, özne) listesinden tek etiket. EN TEMKİNLİ kazanır: ANALYSIS_UNSAFE > INVESTIGATE > REJECT_SIGNAL > WATCH > HOLD > adaylar.

    Özel durumlar: aynı (bilinen) özne için aday ile REJECT_SIGNAL çelişirse INVESTIGATE; yalnızca aday etiketler kaldıysa ve
    birden çok FARKLI aday varsa WATCH. Sıradan bağımsızdır (deterministik)."""
    if not items:
        raise ValueError("birleştirilecek senaryo etiketi yok")
    pairs = [(A(label), subject) for label, subject in items]
    labels = [l for l, _ in pairs]
    conflict = any(
        l in CANDIDATE_LABELS and any(l2 == A.REJECT_SIGNAL and s2 == s for l2, s2 in pairs)
        for l, s in pairs if s is not None
    )
    pool = labels + ([A.INVESTIGATE] if conflict else [])
    best = min(pool, key=lambda l: _RANK[l])
    if conflict and best == A.INVESTIGATE:
        return A.INVESTIGATE, "G5_CANDIDATE_VS_REJECT"
    if best in CANDIDATE_LABELS and len({l for l in labels if l in CANDIDATE_LABELS}) > 1:
        return A.WATCH, "G5_DIFFERENT_CANDIDATES"
    return best, "G5_COMBINE"


# =============================== tavsiye niyeti ===============================
def detect_advice_intent(question: str) -> tuple[bool, bool]:
    """(tavsiye_niyeti, kesinlik_iddiası): soruda al/sat/hedef fiyat isteği; soruda 'kesin yükselir/garanti' gibi kesinlik iddiası."""
    q = question or ""
    if not q.strip():
        return False, False
    violations, _ = find_advice_language(q)
    certain = any(v.category == "CERTAINTY" for v in violations)
    advice = any(v.category in ("BUY_SELL", "PRICE_TARGET") for v in violations)
    if not advice:
        folded = tr_fold(q)
        advice = any(p.search(folded if lang == "tr" else q) for lang, p in load_lexicon().question_advice)
    return advice, certain


# =============================== yardımcılar ===============================
def _usable(env: dict[str, Any]) -> bool:
    return env.get("status") == "OK" and isinstance(env.get("results"), dict) and str(env.get("tool")) not in _NO_TOOLS


def _se_pp(hit: float | None, n: int | None) -> float | None:
    """İsabet oranının standart hatası (yüzde puan): 100*sqrt(p(1-p)/n). Yalnızca BİLGİ."""
    if hit is None or not n:
        return None
    p = hit / 100.0
    return round(100.0 * math.sqrt(max(p * (1.0 - p), 0.0) / n), 4)


class _Ctx:
    """Bir senaryo değerlendirmesinin kontrol/gerekçe toplayıcısı."""

    def __init__(self, env: dict[str, Any], th: PolicyThresholds) -> None:
        self.env, self.th = env, th
        self.tool = str(env["tool"])
        self.hash = str(env["input_hash"])
        self.res = env["results"]
        self.checks: list[Check] = []
        self.reasons: list[Reason] = []

    def chk(self, cid: str, desc: str, ok: bool | None, actual: Any, threshold: Any = None, path: str | None = None,
            tool: str | None = None, input_hash: str | None = None, info: bool = False) -> Check:
        c = Check(cid, desc, None if info else ok, actual, threshold, tool or self.tool, input_hash or self.hash, path, info)
        self.checks.append(c)
        return c

    def why(self, code: str, message: str) -> None:
        if all(r.code != code for r in self.reasons):
            self.reasons.append(Reason(code, message))


def _finish(ctx: _Ctx, scenario: str, subject: str | None, label: A, rule: str, gate: str | None, *, provisional: bool = False,
            candidate_note: bool = True) -> ScenarioDecision:
    """G3 uygular (kapı INVESTIGATE: yalnızca adaylar düşer) ve zorunlu notları ekler."""
    raw, raw_rule, final_rule = label, rule, rule
    if gate == "INVESTIGATE" and label in CANDIDATE_LABELS:
        label, final_rule = A.INVESTIGATE, "G3_GATE_INVESTIGATE"
        ctx.why("GATE_INVESTIGATE_CAP", "kalite kapısı INVESTIGATE: aday etiket verilemez, INVESTIGATE'e indirildi")
    if provisional:
        ctx.why("THRESHOLDS_PROVISIONAL", "temel veri eşikleri GEÇİCİDİR; gerçek veri gelince gözden geçirilecek")
    if raw in CANDIDATE_LABELS and candidate_note:
        ctx.why("CANDIDATE_CAVEAT", CAVEAT_TEXT)
    return ScenarioDecision(scenario, ctx.tool, ctx.hash, subject, label, final_rule, raw, raw_rule, provisional,
                            ctx.checks, ctx.reasons)


# ---------------------------------------------------------------- ufuk bloklarının ortak değerlendirmesi
@dataclass
class _Horizon:
    h: int
    events_ok: bool
    margin_ok: bool
    below_base: bool
    validation_present: bool
    flag_true: bool
    passes: bool


def _eval_horizons(ctx: _Ctx, blocks: list[dict[str, Any]], paths: list[str]) -> list[_Horizon]:
    th = ctx.th
    out: list[_Horizon] = []
    for b, path in zip(blocks, paths):
        h = b["horizon"]
        full, ins, oos = b["full"], b.get("in_sample"), b.get("out_of_sample")
        n, hit = full["n_events_complete"], full.get("hit_rate_pct")
        base = (b.get("baseline") or {}).get("hit_rate_pct")
        cost = full.get("cost_adjusted_mean_return_pct")
        flag = b.get("oos_degradation_flag")
        diff = None if hit is None or base is None else round(hit - base, 4)
        is_cost = None if ins is None else ins.get("cost_adjusted_mean_return_pct")
        oos_cost = None if oos is None else oos.get("cost_adjusted_mean_return_pct")
        oos_n = None if oos is None else oos["n_events_complete"]

        events_ok = n >= th.min_events
        margin_ok = diff is not None and diff >= th.hit_margin_pp
        cost_ok = cost is not None and cost > 0
        is_ok = is_cost is not None and is_cost > 0
        oos_ok = oos_cost is not None and oos_cost > 0
        present = ins is not None and oos is not None and oos_n is not None and oos_n >= th.min_oos_events
        flag_true = flag is True
        passes = events_ok and margin_ok and cost_ok and present and is_ok and oos_ok and not flag_true

        ctx.chk(f"h{h}.n_events_complete", f"{h}g tamamlanmış olay sayısı", events_ok, n, f">= {th.min_events}", f"{path}.full.n_events_complete")
        ctx.chk(f"h{h}.hit_minus_baseline_pp", f"{h}g isabet oranı - baz (yüzde puan)", margin_ok, diff, f">= {th.hit_margin_pp}",
                f"{path}.full.hit_rate_pct - {path}.baseline.hit_rate_pct")
        ctx.chk(f"h{h}.cost_adjusted_mean_full", f"{h}g maliyet sonrası ortalama getiri (tüm örneklem)", cost_ok, cost, "> 0",
                f"{path}.full.cost_adjusted_mean_return_pct")
        ctx.chk(f"h{h}.is_cost_adjusted_mean", f"{h}g maliyet sonrası ortalama (örneklem içi)", is_ok, is_cost, "> 0",
                f"{path}.in_sample.cost_adjusted_mean_return_pct")
        ctx.chk(f"h{h}.oos_cost_adjusted_mean", f"{h}g maliyet sonrası ortalama (örneklem dışı)", oos_ok, oos_cost, "> 0",
                f"{path}.out_of_sample.cost_adjusted_mean_return_pct")
        ctx.chk(f"h{h}.oos_n", f"{h}g örneklem dışı olay sayısı", oos_n is not None and oos_n >= th.min_oos_events, oos_n,
                f">= {th.min_oos_events}", f"{path}.out_of_sample.n_events_complete")
        ctx.chk(f"h{h}.oos_degradation_flag", f"{h}g örneklem dışı bozulma bayrağı", not flag_true, flag, "!= True",
                f"{path}.oos_degradation_flag")
        ctx.chk(f"h{h}.hit_rate_se_pp", f"{h}g isabet oranı standart hatası (bilgi)", None, _se_pp(hit, n), None,
                f"{path}.full.hit_rate_pct", info=True)
        ctx.chk(f"h{h}.passes", f"{h}g ufku tüm koşulları sağlıyor", passes, passes, True, path)
        out.append(_Horizon(h, events_ok, margin_ok, diff is not None and diff < 0, present, flag_true, passes))
    return out


@dataclass
class _Backtest:
    found: bool = False
    no_test_split: bool = False
    low_signal: bool = False
    flag_true: bool = False
    diff_ok: bool = False


def _eval_backtest(ctx: _Ctx, backtests: list[dict[str, Any]]) -> _Backtest:
    """Uygulanabilir (aynı sinyal türü ve evrende özne) backtest'lerin EN TEMKİNLİ birleşimi."""
    bt = _Backtest()
    if not backtests:
        ctx.chk("backtest.present", "uygun run_backtest zarfı", False, False, True, "(yok)", tool="run_backtest", input_hash="")
        ctx.why("BACKTEST_MISSING", "uygun backtest yok (aynı sinyal türü ve evren)")
        return bt
    bt.found = True
    worst = min(backtests, key=lambda e: _test_diff(e) if _test_diff(e) is not None else float("-inf"))
    h = str(worst["input_hash"])
    diffs = [_test_diff(e) for e in backtests]
    bt.no_test_split = any(d is None for d in diffs)
    bt.low_signal = any(e["results"].get("low_signal_flag") is True for e in backtests)
    bt.flag_true = any(e["results"].get("oos_degradation_flag") is True for e in backtests)
    diff = None if bt.no_test_split else min(d for d in diffs if d is not None)
    bt.diff_ok = diff is not None and diff > 0
    ctx.chk("backtest.present", "uygun run_backtest zarfı", True, True, True, "strategy.signal_type, universe",
            tool="run_backtest", input_hash=h)
    ctx.chk("backtest.test_benchmark_diff_pct", "backtest TEST dilimi net getiri - benchmark (yüzde puan)", bt.diff_ok, diff, "> 0",
            "splits[TEST].benchmark_diff_pct", tool="run_backtest", input_hash=h)
    ctx.chk("backtest.low_signal_flag", "backtest sinyal sayısı yeterli", not bt.low_signal,
            any(e["results"].get("low_signal_flag") for e in backtests), "False", "low_signal_flag", tool="run_backtest", input_hash=h)
    ctx.chk("backtest.oos_degradation_flag", "backtest örneklem dışı bozulma bayrağı", not bt.flag_true,
            [e["results"].get("oos_degradation_flag") for e in backtests][0], "!= True", "oos_degradation_flag",
            tool="run_backtest", input_hash=h)
    if bt.no_test_split:
        ctx.why("BACKTEST_NO_TEST_SPLIT", "backtest'te TEST dilimi yok (strategy.train_end verilmemiş)")
    if bt.low_signal:
        ctx.why("BACKTEST_LOW_SIGNAL", "backtest sinyal sayısı MIN_EVENTS altında")
    return bt


def _test_diff(env: dict[str, Any]) -> float | None:
    for s in env["results"].get("splits") or []:
        if s.get("name") == "TEST":
            return s.get("benchmark_diff_pct")
    return None


def _find_backtests(envs: Iterable[dict[str, Any]], signal_type: str, ticker: str) -> list[dict[str, Any]]:
    out = []
    for e in envs:
        r = e["results"]
        if str(e["tool"]) == "run_backtest" and (r.get("strategy") or {}).get("signal_type") == signal_type and ticker in (r.get("universe") or []):
            out.append(e)
    return sorted(out, key=lambda e: str(e["input_hash"]))


def _history_flags(ctx: _Ctx, hz: list[_Horizon], bt: _Backtest) -> dict[str, Any]:
    n = len(hz)
    below = sum(1 for x in hz if x.below_base)
    passing = sum(1 for x in hz if x.passes)
    ctx.chk("passing_horizons", "tüm koşulları sağlayan ufuk sayısı", passing >= ctx.th.min_passing_horizons, passing,
            f">= {ctx.th.min_passing_horizons}", "(ufuk bazlı kontroller)")
    ctx.chk("horizons_below_baseline", "isabet oranı bazın ALTINDA olan ufuk sayısı", below * 2 <= n, below, f"<= {n // 2} (çoğunluk değil)",
            "(ufuk bazlı kontroller)")
    missing_oos = any(not x.validation_present for x in hz)
    if missing_oos:
        ctx.why("OOS_VALIDATION_MISSING", "OOS doğrulaması yapılmadı")
    return {
        "few": any(not x.events_ok for x in hz),
        "reject": below * 2 > n or any(x.flag_true for x in hz) or bt.flag_true,
        "missing": missing_oos or not bt.found or bt.no_test_split or bt.low_signal,
        "passing_ok": passing >= ctx.th.min_passing_horizons,
        "backtest_ok": bt.found and bt.diff_ok,
    }


# =============================== senaryo: catch-up (C1–C7) ===============================
def _catch_up(env: dict[str, Any], envs: list[dict[str, Any]], th: PolicyThresholds, gate: str | None,
              subject_hint: str | None) -> ScenarioDecision:
    ctx = _Ctx(env, th)
    res = ctx.res
    ranking = res.get("ranking") or []
    row = None
    if subject_hint is not None:
        row = next((r for r in ranking if r["ticker"] == subject_hint), None)
    elif ranking:
        row = min(ranking, key=lambda r: (r["lag_score_pp"], r["ticker"]))
    subject = row["ticker"] if row else subject_hint
    size, insufficient, strength = res.get("peer_group_size"), res.get("insufficient_peers"), res.get("sector_strength")

    ctx.chk("peer_group_size", "peer grubu büyüklüğü", size is not None and size >= th.min_peers and not insufficient, size,
            f">= {th.min_peers}", "peer_group_size")
    ctx.chk("sector_strength", "sektör gücü STRONG", strength == "STRONG", strength, "STRONG", "sector_strength")
    if row is None:
        ctx.why("SUBJECT_NOT_IN_RANKING", f"özne {subject_hint!r} sıralamada yok")
        return _finish(ctx, "CATCH_UP", subject, A.INVESTIGATE, "C1_PEERS_OR_STRENGTH", gate)
    ridx = ranking.index(row)
    ctx.chk("subject_is_laggard", f"{subject} geride kalan (lag <= -eşik)", row["is_laggard"], row["is_laggard"], True,
            f"ranking[{ridx}].is_laggard")
    ctx.chk("lag_score_pp", f"{subject} lag skoru (pp)", None, row["lag_score_pp"], f"<= -{res.get('lag_threshold_pp')}",
            f"ranking[{ridx}].lag_score_pp", info=True)

    if size is None or size < th.min_peers or insufficient or strength is None:
        ctx.why("SMALL_PEER_GROUP" if (size is None or size < th.min_peers or insufficient) else "SECTOR_STRENGTH_MISSING",
                "peer grubu yetersiz ya da sektör gücü hesaplanamadı")
        return _finish(ctx, "CATCH_UP", subject, A.INVESTIGATE, "C1_PEERS_OR_STRENGTH", gate)
    if not row["is_laggard"]:
        ctx.why("NOT_LAGGARD", f"{subject} geride kalan eşiğinde değil: sinyal koşulu oluşmadı")
        return _finish(ctx, "CATCH_UP", subject, A.HOLD, "C2_NOT_LAGGARD", gate)

    blocks = [x["block"] for x in res.get("historical_catch_up") or []]
    paths = [f"historical_catch_up[{i}].block" for i in range(len(blocks))]
    hz = _eval_horizons(ctx, blocks, paths)
    bt = _eval_backtest(ctx, _find_backtests(envs, "CATCH_UP", subject))
    if not hz:
        ctx.why("NO_HISTORICAL_BLOCKS", "tarihsel catch-up bloğu yok")
        return _finish(ctx, "CATCH_UP", subject, A.INVESTIGATE, "C3_FEW_EVENTS", gate)
    f = _history_flags(ctx, hz, bt)
    if f["few"]:
        ctx.why("FEW_EVENTS", f"tamamlanmış olay sayısı MIN_EVENTS ({th.min_events}) altında")
        return _finish(ctx, "CATCH_UP", subject, A.INVESTIGATE, "C3_FEW_EVENTS", gate)
    if f["reject"]:
        ctx.why("HISTORICAL_VALIDATION_FAILED", "tarihsel doğrulama başarısız: isabet çoğu ufukta bazın altında ve/veya OOS bozulması")
        return _finish(ctx, "CATCH_UP", subject, A.REJECT_SIGNAL, "C4_REJECT_HISTORY", gate)
    if f["missing"]:
        return _finish(ctx, "CATCH_UP", subject, A.INVESTIGATE, "C6_VALIDATION_MISSING", gate)
    if strength == "STRONG" and f["passing_ok"] and f["backtest_ok"]:
        return _finish(ctx, "CATCH_UP", subject, CU, "C5_CANDIDATE", gate)
    ctx.why("EVIDENCE_MIXED", "kanıt karışık ya da aday koşulları sağlanmadı (sektör STRONG değil / yetersiz geçen ufuk / backtest)")
    return _finish(ctx, "CATCH_UP", subject, A.WATCH, "C7_WATCH", gate)


# =============================== senaryo: haftanın günü (W1–W3) ===============================
def _weekday(env: dict[str, Any], th: PolicyThresholds, gate: str | None) -> ScenarioDecision:
    ctx = _Ctx(env, th)
    res = ctx.res
    verdict = res.get("stability_verdict")
    ctx.chk("stability_verdict", "örüntü kararlılık hükmü STABLE", verdict == "STABLE", verdict, "STABLE", "stability_verdict")
    ctx.chk("verdict_codes", "kararlılık hüküm kodları (bilgi)", None, list(res.get("verdict_codes") or []), None, "verdict_codes", info=True)
    for key in ("in_sample", "out_of_sample"):
        ctx.chk(f"{key}.n_trigger_weeks", f"{key} tetik hafta sayısı (bilgi)", None, (res.get(key) or {}).get("n_trigger_weeks"),
                None, f"{key}.n_trigger_weeks", info=True)
    subject = res.get("ticker")
    if verdict == "STABLE":
        ctx.why("PATTERN_STABLE", "örüntü örneklem içinde ve dışında kararlı; haftalık örüntü için aday etiketi yoktur: yalnızca izleme")
        return _finish(ctx, "WEEKDAY", subject, A.WATCH, "W1_STABLE", gate)
    if verdict == "INSUFFICIENT_DATA":
        ctx.why("PATTERN_INSUFFICIENT_DATA", "örüntü için örneklem yetersiz")
        return _finish(ctx, "WEEKDAY", subject, A.INVESTIGATE, "W2_INSUFFICIENT", gate)
    ctx.why("PATTERN_UNSTABLE", "örüntü örneklem dışında devam etmiyor / anlamsız")
    return _finish(ctx, "WEEKDAY", subject, A.REJECT_SIGNAL, "W3_UNSTABLE", gate)


# =============================== senaryo: teknik dönüş (T0–T6) ===============================
def _signal_is_current(events: list[dict[str, Any]], as_of: date, th: PolicyThresholds) -> tuple[bool, str | None, int | None]:
    dates = [date.fromisoformat(str(e["date"])) for e in events]
    dates = [d for d in dates if d <= as_of]
    if not dates:
        return False, None, None
    last = max(dates)
    days = int(np.busday_count(last, as_of))   # hafta sonları hariç; resmi tatiller sayılmaz (yaklaşıklık)
    return days <= th.signal_recency_trading_days, last.isoformat(), days


def _reversal(env: dict[str, Any], envs: list[dict[str, Any]], th: PolicyThresholds, gate: str | None) -> ScenarioDecision:
    ctx = _Ctx(env, th)
    res = ctx.res
    subject = res.get("ticker")
    gi = next((i for i, g in enumerate(res.get("groups") or []) if g.get("label") == "single_indicator" and not g.get("conditions")), None)
    ctx.chk("primary_group", "koşulsuz (single_indicator) grup var", gi is not None,
            "single_indicator" if gi is not None else None, "single_indicator", "groups[].label")
    if gi is None:
        ctx.why("NO_PRIMARY_GROUP", "koşulsuz grup yok; birleşik gruplar etiketi belirlemez (çoklu test riski)")
        return _finish(ctx, "REVERSAL", subject, A.INVESTIGATE, "T0_NO_PRIMARY_GROUP", gate)
    g = res["groups"][gi]
    n_det = g["n_events_detected"]
    ctx.chk("n_events_detected", "tespit edilen olay sayısı", n_det > 0, n_det, "> 0", f"groups[{gi}].n_events_detected")
    if n_det == 0:
        ctx.why("NO_EVENTS", "geçerli taramada hiç olay yok: sinyal koşulu oluşmadı")
        # SE bilgisi için ufuk blokları da yazılır
        _eval_horizons(ctx, g.get("per_horizon") or [], [f"groups[{gi}].per_horizon[{i}]" for i in range(len(g.get("per_horizon") or []))])
        return _finish(ctx, "REVERSAL", subject, A.HOLD, "T6_NO_EVENTS", gate)
    blocks = g.get("per_horizon") or []
    hz = _eval_horizons(ctx, blocks, [f"groups[{gi}].per_horizon[{i}]" for i in range(len(blocks))])
    bt = _eval_backtest(ctx, _find_backtests(envs, "REVERSAL", subject))
    current, last, days = _signal_is_current(g.get("events") or [], date.fromisoformat(str(env["as_of"])), th)
    ctx.chk("current_signal", "güncel sinyal (son olay as_of'a yakın)", current, {"last_event": last, "trading_days_ago": days},
            f"<= {th.signal_recency_trading_days} iş günü", f"groups[{gi}].events[].date")
    if not hz:
        ctx.why("NO_HISTORICAL_BLOCKS", "ufuk bloğu yok")
        return _finish(ctx, "REVERSAL", subject, A.INVESTIGATE, "T1_FEW_EVENTS", gate)
    f = _history_flags(ctx, hz, bt)
    if f["few"]:
        ctx.why("FEW_EVENTS", f"tamamlanmış olay sayısı MIN_EVENTS ({th.min_events}) altında")
        return _finish(ctx, "REVERSAL", subject, A.INVESTIGATE, "T1_FEW_EVENTS", gate)
    if f["reject"]:
        ctx.why("HISTORICAL_VALIDATION_FAILED", "tarihsel doğrulama başarısız: isabet çoğu ufukta bazın altında ve/veya OOS bozulması")
        return _finish(ctx, "REVERSAL", subject, A.REJECT_SIGNAL, "T2_REJECT_HISTORY", gate)
    if f["missing"]:
        return _finish(ctx, "REVERSAL", subject, A.INVESTIGATE, "T4_VALIDATION_MISSING", gate)
    if current and f["passing_ok"] and f["backtest_ok"]:
        return _finish(ctx, "REVERSAL", subject, TR, "T3_CANDIDATE", gate)
    ctx.why("EVIDENCE_MIXED", "güncel sinyal yok ya da kanıt karışık")
    return _finish(ctx, "REVERSAL", subject, A.WATCH, "T5_WATCH", gate)


# =============================== senaryo: temel veri (F1–F4) — GEÇİCİ eşikler ===============================
def _fundamental(env: dict[str, Any], th: PolicyThresholds, gate: str | None) -> ScenarioDecision:
    ctx = _Ctx(env, th)
    res = ctx.res
    subject = res.get("ticker")
    n = res.get("n_quarters_disclosed_by_as_of", 0)
    quarters = res.get("quarters") or []
    ctx.chk("n_quarters_disclosed", "açıklanmış çeyrek sayısı (GEÇİCİ eşik)", n >= th.min_quarters, n, f">= {th.min_quarters}",
            "n_quarters_disclosed_by_as_of")
    # fiyat tepkisi yalnızca BİLGİ (nedensellik iddiasından kaçınmak için kural değildir)
    for r in res.get("reaction_summary") or []:
        ctx.chk(f"reaction.mean_abnormal_vs_xu100_pct.h{r['horizon']}.{r['group']}",
                f"açıklama sonrası {r['horizon']}g XU100'e göre ortalama anormal getiri, {r['group']} grubu (bilgi)", None,
                r.get("mean_abnormal_vs_xu100_pct"), None, "reaction_summary[]", info=True)
    latest = max(quarters, key=lambda q: q.get("fiscal_period") or "") if quarters else None
    if latest is not None and any(not r.get("complete", True) for r in latest.get("reactions") or []):
        ctx.why("LATEST_REACTION_INCOMPLETE", "son çeyreğin bazı fiyat tepki ufukları as_of itibarıyla tamamlanmadı (eksik veri; etiketi etkilemez)")
    if latest is None or n < th.min_quarters:
        ctx.why("FEW_QUARTERS", f"açıklanmış çeyrek sayısı yetersiz (< {th.min_quarters})")
        return _finish(ctx, "FUNDAMENTAL", subject, A.INVESTIGATE, "F1_INSUFFICIENT", gate, provisional=True)
    comparable = bool(latest.get("tms29_comparable"))
    ctx.chk("tms29_comparable", "son çeyrek TMS 29 sonrası karşılaştırılabilir", comparable, latest.get("tms29_comparable"), True,
            "quarters[latest].tms29_comparable")
    if not comparable:
        ctx.why("PRE_TMS29_NOT_COMPARABLE", "son çeyrek TMS 29 karşılaştırılabilirlik koşulunu sağlamıyor")
        return _finish(ctx, "FUNDAMENTAL", subject, A.INVESTIGATE, "F1_INSUFFICIENT", gate, provisional=True)
    basis = "yoy_direction" if res.get("improvement_basis") == "YOY" else "qoq_direction"
    metrics = {m["name"]: m for m in latest.get("metrics") or []}
    im = res.get("improvement_metric")
    entry = metrics.get(im)
    ctx.chk("improvement_metric_direction", f"{im} yönü ({res.get('improvement_basis')})", None if entry else False,
            entry.get(basis) if entry else None, "IMPROVED", f"quarters[latest].metrics[{im}].{basis}", info=entry is not None)
    if entry is None:
        ctx.why("IMPROVEMENT_METRIC_MISSING", f"iyileşme metriği {im} son çeyrekte yok")
        return _finish(ctx, "FUNDAMENTAL", subject, A.INVESTIGATE, "F1_INSUFFICIENT", gate, provisional=True)
    direction = entry.get(basis)
    sec = metrics.get("NET_DEBT_EBITDA") if im != "NET_DEBT_EBITDA" else None
    sec_dir = sec.get(basis) if sec else None
    ctx.chk("secondary_metric_direction", "NET_DEBT_EBITDA yönü (ikinci ana metrik)", None, sec_dir, "!= DETERIORATED",
            f"quarters[latest].metrics[NET_DEBT_EBITDA].{basis}", info=True)
    if direction == "DETERIORATED" and (sec_dir is None or sec_dir == "DETERIORATED"):
        ctx.why("FUNDAMENTALS_DETERIORATING", "iyileşme metriği kötüleşiyor ve ikinci ana metrik de iyileşmiyor")
        return _finish(ctx, "FUNDAMENTAL", subject, A.REJECT_SIGNAL, "F2_REJECT", gate, provisional=True)
    if direction == "IMPROVED" and sec_dir != "DETERIORATED":
        return _finish(ctx, "FUNDAMENTAL", subject, FI, "F3_CANDIDATE", gate, provisional=True)
    ctx.why("EVIDENCE_MIXED", "temel veri karışık ya da düz")
    return _finish(ctx, "FUNDAMENTAL", subject, A.WATCH, "F4_WATCH", gate, provisional=True)


# =============================== ana fonksiyon ===============================
def decide_label(*, gate_status: str | None, envelopes: Iterable[dict[str, Any]], question: str = "", subject: str | None = None,
                 thresholds: PolicyThresholds | None = None) -> PolicyDecision:
    """Kilitli kanıt paketinin kaynak zarfları + kapı sonucu + soru -> izinli etiket (deterministik).

    envelopes: oturumdaki araç zarfları (yalnızca status=OK; kapı/kanıt paketi zarfları yok sayılır).
    subject  : catch-up için özne hisse (örn. sorudaki tek hisse); None => sıralamadaki en çok geride kalan.
    """
    th = thresholds or PolicyThresholds()
    advice, certain = detect_advice_intent(question)
    gate = gate_status if gate_status else None
    dec = PolicyDecision(A.INVESTIGATE, "G2_GATE_MISSING", gate, advice, certain)

    if gate in UNSAFE_GATES:
        dec.label, dec.rule_id = A.ANALYSIS_UNSAFE, "G1_GATE_UNSAFE"
        dec.reasons.append(Reason("GATE_UNSAFE", f"kalite kapısı {gate}: analiz güvenli değil"))
        dec.trace.append(f"G1: kapı {gate} -> ANALYSIS_UNSAFE")
        return dec
    if gate not in VALID_GATES:
        dec.reasons.append(Reason("GATE_MISSING", "kalite kapısı sonucu yok ya da bilinmiyor: güvenli varsayılan INVESTIGATE"))
        dec.trace.append(f"G2: kapı {gate!r} geçersiz -> INVESTIGATE")
        return dec

    uniq: dict[str, dict[str, Any]] = {}
    for e in envelopes:
        if _usable(e):
            uniq.setdefault(str(e["input_hash"]), e)
    envs = sorted(uniq.values(), key=lambda e: (str(e["tool"]), str(e["input_hash"])))

    scenarios: list[ScenarioDecision] = []
    for e in envs:
        tool = str(e["tool"])
        if tool == "rank_sector_relative_strength":
            scenarios.append(_catch_up(e, envs, th, gate, subject))
        elif tool == "test_weekday_pattern":
            scenarios.append(_weekday(e, th, gate))
        elif tool == "detect_reversal_events":
            scenarios.append(_reversal(e, envs, th, gate))
        elif tool == "calculate_fundamental_change":
            scenarios.append(_fundamental(e, th, gate))
    scenarios.sort(key=lambda s: (_SCENARIO_ORDER[s.scenario], s.tool, s.input_hash))
    dec.scenarios = scenarios

    if not scenarios:
        dec.label = A.INVESTIGATE
        if certain:
            dec.rule_id = "G7_UNVERIFIED_CLAIM"
            dec.reasons.append(Reason("UNVERIFIED_CERTAINTY_CLAIM", "soruda kesinlik iddiası var ve araç çıktıları bunu doğrulamıyor"))
        else:
            dec.rule_id = "G7_NO_SCENARIO"
            dec.reasons.append(Reason("NO_SCENARIO_EVIDENCE", "etiketi belirleyecek senaryo aracı çıktısı yok: güvenli varsayılan INVESTIGATE"))
        dec.trace.append(f"G7: senaryo yok -> INVESTIGATE ({dec.rule_id})")
        return dec

    label, crule = combine_scenario_labels([(s.label, s.subject) for s in scenarios])
    if crule == "G5_COMBINE":
        rule = next(s.rule_id for s in scenarios if s.label == label)
    else:
        rule = crule
    dec.trace.extend(f"{s.scenario}/{s.subject}: {s.raw_label.value} ({s.base_rule_id})"
                     + (f" -> {s.label.value} ({s.rule_id})" if s.label != s.raw_label else "") for s in scenarios)
    dec.trace.append(f"G5: {crule} -> {label.value}")
    if advice and (label in CANDIDATE_LABELS or label == A.HOLD):
        dec.trace.append(f"G6: tavsiye niyeti, {label.value} -> WATCH")
        dec.reasons.append(Reason("ADVICE_INTENT_CAP", "soruda al/sat/hedef fiyat isteği var: tavsiye verilmez, etiket WATCH'a indirildi"))
        label, rule = A.WATCH, "G6_ADVICE_CAP"
    dec.label, dec.rule_id = label, rule

    seen: set[tuple[str, str]] = {(r.code, r.message) for r in dec.reasons}
    for s in scenarios:
        for r in s.reasons:
            if (r.code, r.message) not in seen:
                seen.add((r.code, r.message))
                dec.reasons.append(r)
    if label in CANDIDATE_LABELS and "CANDIDATE_CAVEAT" not in dec.reason_codes:
        dec.reasons.append(Reason("CANDIDATE_CAVEAT", CAVEAT_TEXT))
    return dec


def decide_session(session: Any, *, thresholds: PolicyThresholds | None = None) -> PolicyDecision:
    """Bir HarnessSession için: kilitli paketin kaynak zarfları + son kapı sonucu + soru. (session.py'ye bağlanmaz.)

    Özne: soruda TEK evren hissesi geçiyorsa o; aksi halde sıralamadaki en çok geride kalan."""
    records = list(session.store.records)
    gate = None
    for r in records:
        if str(r.tool.value) == "check_data_quality" and r.envelope["status"] == "OK":
            gate = r.envelope["results"].get("gate_status")
    envs = [r.envelope for r in records]
    bundle = getattr(session, "bundle", None)
    if bundle is not None:
        allowed = {i["source_input_hash"] for i in bundle.snapshot()["full_evidence_set"]}
        envs = [e for e in envs if e["input_hash"] in allowed]
    tickers = list(getattr(session, "question_tickers", []) or [])
    subject = tickers[0] if len(tickers) == 1 else None
    return decide_label(gate_status=gate, envelopes=envs, question=session.question, subject=subject, thresholds=thresholds)
