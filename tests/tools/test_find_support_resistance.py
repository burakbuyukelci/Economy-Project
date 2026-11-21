"""find_support_resistance aracı testleri.

(A) Saf yardımcılar: nedensel pivot tespiti, kümeleme.
(B) Sentetik snapshot, ELLE hesaplanabilir seviyeler (pivot_window=3):
    dirençler 110 / 110,5 / 109,8 (3 dokunuş, ort 110,1), destekler 90 / 90,4 (2 dokunuş, ort 90,2), kapanış 100.
(C) Nedensellik: son `w` bardaki pivot onaylanmamıştır; as_of sonrası şok sonucu değiştirmez; önek değişmezliği.
(D) Determinizm, parametreler (min_touches, tolerans), rol değişimi (kırılan direnç destek olur), hata zarfları.
(E) Gerçek v2 snapshot (THYAO).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from schemas import validate_envelope
from schemas.results import FindSupportResistanceResult
from scripts.download_prices import CANONICAL_COLUMNS
from tests.conftest import make_snapshot
from tools import find_support_resistance as tool

VERSION = "snap_2026-11-20_v2"
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")

N = 60
DATES = pd.bdate_range("2024-01-01", periods=N)


# =====================================================================================================
# (A) saf yardımcılar
# =====================================================================================================
def test_pivots_are_strict_on_the_left_and_non_strict_on_the_right():
    high = np.array([1, 1, 1, 5, 1, 1, 1, 1, 1, 1], float)
    ph, _ = tool.find_pivots(high, np.zeros(10), 2)
    assert ph == [3]
    flat = np.full(10, 1.0)
    assert tool.find_pivots(flat, flat, 2) == ([], [])  # düz bölge pivot üretmez


def test_pivot_needs_w_bars_on_both_sides():
    high = np.array([9, 1, 1, 1, 1, 1, 1, 1, 1, 9], float)  # uçlardaki tepeler onaylanamaz
    ph, _ = tool.find_pivots(high, np.zeros(10), 2)
    assert ph == []


def test_cluster_anchors_on_lowest_price_and_respects_tolerance():
    items = [(100.0, 0), (100.9, 1), (101.5, 2), (110.0, 3)]
    cl = tool.cluster_prices(items, 1.0)
    assert [[p for p, _ in c] for c in cl] == [[100.0, 100.9], [101.5], [110.0]]  # 101.5 > 100*1.01


# =====================================================================================================
# (B) sentetik snapshot
# =====================================================================================================
def _frame(closes, highs, lows, vols, dates=DATES, ticker="THYAO") -> pd.DataFrame:
    c = np.asarray(closes, float)
    return pd.DataFrame({"ticker": ticker, "date": dates, "open": c, "high": highs, "low": lows, "close": c, "adj_close": c,
                         "volume": vols, "dividends": 0.0, "stock_splits": 0.0})[CANONICAL_COLUMNS]


def scenario(extra_high: dict | None = None, extra_low: dict | None = None, close=None, n=N):
    """Taban 100 (high 101, low 99). Zirveler: i=10: 110, i=30: 110,5, i=50: 109,8; dipler i=20: 90, i=40: 90,4."""
    closes = np.full(n, 100.0) if close is None else np.asarray(close, float)
    highs, lows = closes + 1.0, closes - 1.0
    for i, v in {10: 110.0, 30: 110.5, 50: 109.8, **(extra_high or {})}.items():
        highs[i] = v
    for i, v in {20: 90.0, 40: 90.4, **(extra_low or {})}.items():
        lows[i] = v
    return closes, highs, lows


def make_root(root, closes, highs, lows, shock_after: int | None = None, vols=None):
    n = len(closes)
    dates = pd.bdate_range("2024-01-01", periods=n)
    h, l, c = np.asarray(highs, float).copy(), np.asarray(lows, float).copy(), np.asarray(closes, float).copy()
    if shock_after is not None:  # as_of SONRASI satırlara aşırı değerler
        h[shock_after + 1:] *= 1e6
        l[shock_after + 1:] *= 1e6
        c[shock_after + 1:] *= 1e6
    v = np.full(n, 1000.0) if vols is None else vols
    stocks = _frame(c, h, l, v, dates)
    index = _frame(np.full(n, 10000.0), np.full(n, 10001.0), np.full(n, 9999.0), v, dates).drop(columns=["ticker"])
    make_snapshot(root, stocks, index, version=VERSION)
    return root


def call(root, as_of=DATES[-1], **over):
    params = {"ticker": "THYAO", "end": DATES[-1].date().isoformat(), "pivot_window": 3, "as_of": pd.Timestamp(as_of).date().isoformat()}
    params.update(over)
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> FindSupportResistanceResult:
    assert env["status"] == "OK", env.get("error")
    return FindSupportResistanceResult.model_validate(env["results"])


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    return make_root(tmp_path_factory.mktemp("sr_base"), *scenario())


def test_hand_computed_levels(root):
    env = call(root)
    validate_envelope(env)
    r = res(env)
    assert (r.last_close, r.last_date) == (100.0, DATES[-1].date())
    assert (r.nearest_support, r.nearest_resistance) == (90.2, 110.1)
    assert r.nearest_support_distance_pct == 9.8  # (100 - 90,2) / 100 x 100
    assert r.nearest_resistance_distance_pct == 10.1  # (110,1 - 100) / 100 x 100
    res_lv, sup_lv = r.levels[0], r.levels[1]
    assert (res_lv.type.value, res_lv.price, res_lv.zone_low, res_lv.zone_high, res_lv.touch_count) == ("RESISTANCE", 110.1, 109.8, 110.5, 3)
    assert res_lv.last_touch_date == DATES[50].date()
    assert (sup_lv.type.value, sup_lv.price, sup_lv.zone_low, sup_lv.zone_high, sup_lv.touch_count) == ("SUPPORT", 90.2, 90.0, 90.4, 2)
    assert sup_lv.last_touch_date == DATES[40].date()
    assert len(r.levels) == 2


def test_strength_formula_recency_and_volume(root):
    """strength = Σ 0,5^(yaş/126) x min(2, hacim/medyan hacim); hacim sabit -> ağırlık 1; yaş = son bardan bar sayısı."""
    r = res(call(root))
    last = N - 1
    expected = sum(0.5 ** ((last - i) / tool.RECENCY_HALF_LIFE_BARS) for i in (10, 30, 50))
    assert r.levels[0].strength == pytest.approx(expected, abs=1e-3)
    assert r.levels[0].strength > r.levels[1].strength  # 3 dokunuş > 2 dokunuş (yenilik farkı küçük)


def test_volume_weight_is_capped_at_two(tmp_path):
    vols = np.full(N, 1000.0)
    vols[[10, 30, 50]] = 1e6  # çok yüksek hacim -> ağırlık 2'de kırpılır
    r = res(call(make_root(tmp_path, *scenario(), vols=vols)))
    last = N - 1
    expected = sum(2.0 * 0.5 ** ((last - i) / tool.RECENCY_HALF_LIFE_BARS) for i in (10, 30, 50))
    assert r.levels[0].strength == pytest.approx(expected, abs=1e-3)


def test_min_touches_and_tolerance(root):
    r3 = res(call(root, min_touches=3))
    assert [lv.touch_count for lv in r3.levels] == [3] and r3.nearest_support is None and r3.nearest_resistance == 110.1
    # çok dar tolerans: 110 / 110,5 / 109,8 ayrı kümeler -> hiçbiri 2 dokunuşa ulaşmaz
    assert res(call(root, tolerance_pct=0.1)).levels == []


# =====================================================================================================
# (C) nedensellik
# =====================================================================================================
def test_pivot_in_the_last_w_bars_is_not_confirmed_until_later(tmp_path_factory):
    """Zirveler i=15 (120,3) ve i=57 (120). w=3: i=57 için i+w=60 gerekir.
    60 bar (son indeks 59): 57 ONAYSIZ -> küme tek dokunuş -> 120 seviyesi yok.
    63 bar: 57 onaylı -> 120,15 seviyesi 2 dokunuşla çıkar. Aynı 63 barlık veride as_of = bar 58 ise yine yok."""
    kw = dict(extra_high={57: 120.0, 15: 120.3})
    short = make_root(tmp_path_factory.mktemp("sr_short"), *scenario(**kw))
    assert all(lv.price < 115 for lv in res(call(short)).levels)
    n2 = N + 3
    dates2 = pd.bdate_range("2024-01-01", periods=n2)
    longer = make_root(tmp_path_factory.mktemp("sr_long"), *scenario(n=n2, **kw))
    r = res(call(longer, as_of=dates2[-1], end=dates2[-1].date().isoformat()))
    top = [lv for lv in r.levels if lv.price > 115]
    assert len(top) == 1 and (top[0].price, top[0].touch_count, top[0].last_touch_date) == (120.15, 2, dates2[57].date())
    early = res(call(longer, as_of=dates2[58], end=dates2[58].date().isoformat()))
    assert all(lv.price < 115 for lv in early.levels)


def test_post_as_of_shock_is_invisible(tmp_path_factory):
    c, h, l = scenario()
    clean = make_root(tmp_path_factory.mktemp("sr_clean"), c, h, l)
    shocked = make_root(tmp_path_factory.mktemp("sr_shock"), c, h, l, shock_after=45)
    as_of = DATES[45]
    a, b = call(clean, as_of=as_of), call(shocked, as_of=as_of)
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]
    assert res(a).last_date == DATES[45].date()
    # i=50 zirvesi as_of=45'ten sonra: görünmez -> direnç yalnızca 2 dokunuş (110, 110,5)
    assert res(a).levels[0].touch_count == 2


def test_prefix_invariance(tmp_path_factory):
    """as_of = t ile tam veride çalıştırmak, verinin t'de kesilmiş halinde çalıştırmakla birebir aynı."""
    c, h, l = scenario()
    full = make_root(tmp_path_factory.mktemp("sr_full"), c, h, l)
    cut = make_root(tmp_path_factory.mktemp("sr_cut"), c[:46], h[:46], l[:46])
    t = DATES[45]
    assert call(full, as_of=t)["results"] == call(cut, as_of=t)["results"]


def test_end_beyond_as_of_is_clamped_with_warning(root):
    env = call(root, as_of=DATES[45], end=DATES[-1].date().isoformat())
    assert "AS_OF_CLAMPED" in " | ".join(env["warnings"])
    assert res(env).last_date == DATES[45].date()


# =====================================================================================================
# (D) determinizm, rol değişimi, hatalar
# =====================================================================================================
def test_determinism_and_warnings(root):
    a, b = call(root), call(root)
    assert a == b
    assert "HISTORICAL_ONLY" in " | ".join(a["warnings"])
    assert call(root, tolerance_pct=2.0)["input_hash"] != a["input_hash"]


def test_broken_resistance_becomes_support(tmp_path):
    """Kapanış 120'ye çıkınca (110,1 direnci kırıldı) aynı seviye DESTEK olur: tip, son kapanışa göre."""
    close = np.full(N, 100.0)
    close[-3:] = 120.0
    r = res(call(make_root(tmp_path, *scenario(close=close))))
    assert r.last_close == 120.0
    assert r.nearest_support == 110.1 and r.nearest_resistance is None
    assert {lv.type.value for lv in r.levels} == {"SUPPORT"}


def test_levels_are_capped_per_side_nearest_first(tmp_path):
    closes = np.full(N, 100.0)
    highs, lows = closes + 1.0, closes - 1.0
    # 7 farklı dip kümesi (her biri 2 dokunuş): 80, 81, ... gibi birbirinden uzak
    levels = [60, 65, 70, 75, 80, 85, 90]
    idx = list(range(3, 3 + 4 * 2 * len(levels), 4))  # aralık 4: komşu dipler birbirinin pencereine girmez; son indeks 55 (onaylı)
    for k, p in enumerate(levels):
        for j in (0, 1):
            lows[idx[2 * k + j]] = p + 0.1 * j
    r = res(call(make_root(tmp_path, closes, highs, lows)))
    sup = [lv for lv in r.levels if lv.type.value == "SUPPORT"]
    assert len(sup) == tool.MAX_LEVELS_PER_SIDE == 5
    assert [round(lv.price) for lv in sup] == [90, 85, 80, 75, 70]  # en yakın (yüksek) 5 destek, yakından uzağa
    assert r.nearest_support == sup[0].price


def test_no_pivots_gives_empty_levels_and_none(tmp_path):
    c = np.full(N, 100.0)
    r = res(call(make_root(tmp_path, c, c + 1, c - 1)))
    assert (r.levels, r.nearest_support, r.nearest_resistance) == ([], None, None)
    assert (r.nearest_support_distance_pct, r.nearest_resistance_distance_pct) == (None, None)
    assert r.last_close == 100.0


def test_errors(root):
    assert call(root, ticker="ZZZZ")["error"]["code"] == "NO_DATA"
    assert call(root, tolerance_pct=0)["error"]["code"] == "INVALID_PARAMS"
    far = call(root, as_of="2023-06-01", end="2023-06-01", start="2023-01-02")
    assert far["status"] == "ERROR" and far["error"]["code"] == "NO_DATA"


# =====================================================================================================
# (E) gerçek v2 (as_of = 2026-09-10)
# =====================================================================================================
def real(ticker="THYAO", **over):
    p = {"ticker": ticker, "end": "2026-09-10", "as_of": "2026-09-10"}
    p.update(over)
    return tool.run_on(p, data_version=VERSION)


@needs_snapshot
def test_real_thyao_levels_are_consistent():
    env = real()
    validate_envelope(env)
    r = res(env)
    assert r.last_date == date(2026, 9, 10)
    assert r.nearest_support is None or r.nearest_support <= r.last_close
    assert r.nearest_resistance is None or r.nearest_resistance > r.last_close
    assert all(lv.touch_count >= 2 and lv.zone_low <= lv.price <= lv.zone_high for lv in r.levels)
    assert all(lv.last_touch_date <= date(2026, 9, 10) for lv in r.levels)
    assert real() == real()
    # gerçek değer çapaları (v2, as_of 2026-09-10; adjusted ölçek)
    assert (r.last_close, r.nearest_support, r.nearest_resistance) == (299.25, 297.1765, 302.012)
    assert (r.nearest_support_distance_pct, r.nearest_resistance_distance_pct) == (0.6929, 0.923)
    assert (r.levels[0].touch_count, r.levels[0].last_touch_date) == (5, date(2026, 6, 3))
