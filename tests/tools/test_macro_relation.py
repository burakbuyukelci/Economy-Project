"""get_macro_context.relate_to (şema 1.5.0): kur/faiz değişimi ile hisse getirisi ilişkisi.

Bilinen cevaplı sentetik veri: blok getirileri y_j ve makro dönüşümleri x_j ELLE kurulur, fiyat/makro serileri bloklar içinde geometrik
yürür; böylece beklenen korelasyon/beta/grup sayıları bağımsız (naif) hesapla bulunur.
Bloklar j = -B0 .. K-1; blok 0 `start` günündeki fiyattan başlar (B0 blok geçmiş: öncü/lag testleri için).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from schemas import validate_envelope
from scripts.download_macro import write_macro_snapshot
from tests.conftest import make_frame, make_snapshot
from tools import get_macro_context as MC

DV = "snap_2026-11-20_v2"
MV = "macro_2026-11-09_v2"
H = 5
B0 = 4          # geçmiş blok sayısı
K = 16          # asıl bloklar


def _days(n):
    return list(pd.bdate_range("2023-10-02", periods=n))


def _walk(start_value, block_changes, h, kind):
    """block_changes: blok başına % (PCT) ya da fark (LEVEL); blok içinde geometrik/doğrusal ara değerler."""
    out = [start_value]
    for c in block_changes:
        a = out[-1]
        for i in range(1, h + 1):
            out.append(a * (1 + c / 100) ** (i / h) if kind == "pct" else a + c * i / h)
    return np.array(out)


def build(tmp_path, x, y, *, k=K, extra=0, macro_kind="pct", series="USDTRY", skip_macro_days=(), calendar_skip=()):
    """x, y: j = -B0..K-1 için sözlük {j: değer}. Dönüş: (kök, günler, start_str)."""
    js = list(range(-B0, k))
    n = (B0 + k) * H + 1 + extra
    days = [d for d in _days(n + len(calendar_skip)) if d not in {pd.Timestamp(c) for c in calendar_skip}][:n]
    P = _walk(100.0, [y[j] for j in js] + [0.0] * (extra // H + 1), H, "pct")[:n]
    M = _walk(40.0, [x[j] for j in js] + [0.0] * (extra // H + 1), H, macro_kind)[:n]
    stock = make_frame("THYAO", 100, days, 1.0)
    stock["close"] = stock["adj_close"] = P
    stock["open"], stock["high"], stock["low"] = P, P * 1.001, P * 0.999
    idx = make_frame("XU100", 10000, days, 1.0).drop(columns=["ticker"])
    make_snapshot(tmp_path, stock, idx, version=DV)
    keep = [(d, v) for d, v in zip(days, M) if d not in {pd.Timestamp(s) for s in skip_macro_days}]
    tab = pd.DataFrame({"series": series, "observation_date": [d for d, _ in keep], "publication_date": [d for d, _ in keep], "value": [v for _, v in keep]})
    write_macro_snapshot(tab, tmp_path, MV, {})
    return tmp_path, days, days[B0 * H]


def _xy(fn_y, k=K):
    rng = np.random.default_rng(7)
    x = {j: float(rng.normal(0, 2)) for j in range(-B0, k)}
    return x, {j: fn_y(x, j) for j in range(-B0, k)}


def _run(root, days, start, spec=None, **p):
    rel = {"ticker": "THYAO", "macro_series": "USDTRY", "horizon": H, **(spec or {})}
    prm = {"start": str(start.date()), "end": str(days[-1].date()), "as_of": str(days[-1].date()), "series": ["USDTRY"], "relate_to": [rel], **p}
    return MC.run_on(prm, snapshot_root=root, data_version=DV, macro_version=MV)


def _rel(e, i=0):
    return e["results"]["relations"][i]


def test_perfect_contemporaneous_relation_known_answer(tmp_path):
    x, y = _xy(lambda x, j: 2.0 * x[j])
    root, days, start = build(tmp_path, x, y)
    e = _run(root, days, start)
    validate_envelope(e)
    f = _rel(e)["full"]
    assert e["status"] == "OK" and f["n_obs"] == K and f["n_excluded_incomplete_horizon"] == 0
    assert f["correlation"] == pytest.approx(1.0, abs=1e-4) and f["beta"] == pytest.approx(2.0, abs=2e-3)
    xs = np.array([x[j] for j in range(K)]); ys = np.array([y[j] for j in range(K)])
    assert f["macro_up"]["n"] == int((xs > 0).sum()) and f["macro_down"]["n"] == int((xs < 0).sum())
    assert f["macro_up"]["mean_return_pct"] == pytest.approx(ys[xs > 0].mean(), abs=2e-3)
    assert f["macro_down"]["median_return_pct"] == pytest.approx(np.median(ys[xs < 0]), abs=2e-3)
    assert f["unconditional"]["mean_return_pct"] == pytest.approx(ys.mean(), abs=2e-3)
    cm = e["results"]["cost_model"]
    assert cm["round_trip_cost_pct"] == 0.5
    assert f["unconditional"]["cost_adjusted_mean_return_pct"] == pytest.approx(f["unconditional"]["mean_return_pct"] - 0.5, abs=1e-3)
    assert f["p_value_raw"] is not None and f["p_value_raw"] < 0.001
    assert f["p_value_adjusted"] == pytest.approx(min(1.0, f["p_value_raw"] * 1), abs=1e-6) and f["significant_after_correction"] is True
    assert e["n_events"] == K and e["results"]["multiple_testing"]["n_tests_declared"] == 1


def test_leading_relation_uses_previous_block_and_has_no_lookahead(tmp_path):
    x, y = _xy(lambda x, j: 3.0 * x[j - 1] if j - 1 in x else 0.0)    # y_j = 3 * x_(j-1): makro hisseden ÖNCE
    root, days, start = build(tmp_path, x, y)
    lead = _rel(_run(root, days, start, {"lag_days": H}))["full"]
    same = _rel(_run(root, days, start, {"lag_days": 0}))["full"]
    assert lead["correlation"] == pytest.approx(1.0, abs=1e-4) and lead["beta"] == pytest.approx(3.0, abs=3e-3)
    assert abs(same["correlation"]) < 0.9                           # eş zamanlıda aynı ilişki yok


def test_level_diff_transform_for_rates(tmp_path):
    x, y = _xy(lambda x, j: -1.5 * x[j])
    root, days, start = build(tmp_path, x, y, macro_kind="level", series="TCMB_FUNDING_COST")
    prm = {"start": str(start.date()), "end": str(days[-1].date()), "as_of": str(days[-1].date()), "series": ["TCMB_FUNDING_COST"],
           "relate_to": [{"ticker": "THYAO", "macro_series": "TCMB_FUNDING_COST", "horizon": H, "transform": "LEVEL_DIFF"}]}
    f = _rel(MC.run_on(prm, snapshot_root=root, data_version=DV, macro_version=MV))["full"]
    assert f["correlation"] == pytest.approx(-1.0, abs=1e-4) and f["beta"] == pytest.approx(-1.5, abs=2e-3)


def test_incomplete_trailing_block_is_excluded_and_counted(tmp_path):
    x, y = _xy(lambda x, j: x[j])
    root, days, start = build(tmp_path, x, y, extra=3)            # 3 işlem günü artık: kısmi blok
    e = _run(root, days, start)
    f = _rel(e)["full"]
    assert f["n_obs"] == K and f["n_excluded_incomplete_horizon"] == 1 and e["n_excluded_incomplete_horizon"] == 1
    assert any(w.startswith("INCOMPLETE_HORIZON_EXCLUDED") for w in e["warnings"])
    assert _rel(e)["sample_last_date"] == str(days[(B0 + K) * H].date())   # son TAMAMLANMIŞ bloğun bitişi


def test_split_date_makes_is_oos_and_degradation_flag(tmp_path):
    # IS'te y = 2x, OOS'ta y = -2x (işaret tersine döner): bozulma
    split_block = 10
    x, y = _xy(lambda x, j: 0.0)
    y = {j: (2.0 if j < split_block else -2.0) * x[j] for j in range(-B0, K)}
    root, days, start = build(tmp_path, x, y)
    split = days[B0 * H + split_block * H]                        # blok 10'un başladığı gün: blok 10 = ilk OOS bloğu
    r = _rel(_run(root, days, start, {"split_date": str(split.date())}))
    # split günü = blok 9'un SON getiri günü (OOS günü): blok 9 sınırı keser, yalnızca "full"e girer; IS = blok 0..8, OOS = blok 10..K-1
    assert r["in_sample"]["n_obs"] == split_block - 1 and r["out_of_sample"]["n_obs"] == K - split_block
    assert r["in_sample"]["correlation"] == pytest.approx(1.0, abs=1e-4) and r["out_of_sample"]["correlation"] == pytest.approx(-1.0, abs=1e-4)
    assert r["oos_degradation_flag"] is True and r["full"]["n_obs"] == K
    assert max(r["in_sample"]["window"]["end"], "") <= str(split.date())


def test_small_oos_flag_false_with_warning(tmp_path):
    x, y = _xy(lambda x, j: 2.0 * x[j])
    root, days, start = build(tmp_path, x, y)
    split = days[B0 * H + (K - 3) * H]                            # OOS yalnızca 3 blok (< MIN_OOS_EVENTS=5)
    e = _run(root, days, start, {"split_date": str(split.date())})
    assert _rel(e)["oos_degradation_flag"] is False and any(w.startswith("OOS_TOO_SMALL") for w in e["warnings"])
    assert any(w.startswith("FEW_EVENTS") for w in e["warnings"])   # n_obs=16 < MIN_EVENTS=20


def test_nothing_after_as_of_changes_the_result(tmp_path_factory):
    fn = lambda x, j: 2.0 * x[j]  # noqa: E731
    x, y = _xy(fn)
    root_flat, days, start = build(tmp_path_factory.mktemp("flat"), x, y, extra=40)      # as_of sonrası: sakin (sabit) kuyruk
    cut = days[(B0 + K) * H]                                                              # as_of = son tamamlanan blok bitişi
    xw, yw = _xy(fn, K + 8)
    xw.update({j: 50.0 for j in range(K, K + 8)}); yw.update({j: -50.0 for j in range(K, K + 8)})   # as_of SONRASI uç değerler
    root_wild, days_w, _ = build(tmp_path_factory.mktemp("wild"), xw, yw, k=K + 8)
    a = _run(root_flat, days, start, as_of=str(cut.date()))
    b = _run(root_wild, days_w, start, as_of=str(cut.date()))
    assert a["status"] == b["status"] == "OK"
    assert a["results"]["relations"] == b["results"]["relations"]   # as_of sonrası veri hiçbir sayıyı değiştirmez (sızıntı olsaydı farklı çıkardı)
    assert _rel(a)["sample_last_date"] <= str(cut.date())
    assert max(p["observation_date"] for s_ in a["results"]["series"] for p in s_["points"]) <= str(cut.date())


def test_deterministic_and_input_hash_depends_on_relation_spec(tmp_path):
    x, y = _xy(lambda x, j: 2.0 * x[j] + 0.3 * x[j - 1] if j - 1 in x else 2.0 * x[j])
    root, days, start = build(tmp_path, x, y)
    a, b = _run(root, days, start), _run(root, days, start)
    assert a == b and a["results"]["relations"][0]["full"]["p_value_raw"] == b["results"]["relations"][0]["full"]["p_value_raw"]
    assert _run(root, days, start, {"horizon": 10})["input_hash"] != a["input_hash"]


def test_monthly_or_missing_series_and_unknown_ticker(tmp_path):
    x, y = _xy(lambda x, j: x[j])
    root, days, start = build(tmp_path, x, y)
    e = _run(root, days, start, {"macro_series": "CPI_ANNUAL"})
    assert e["status"] == "ERROR" and e["error"]["code"] == "UNSUPPORTED_RELATION"
    e2 = _run(root, days, start, {"macro_series": "EURTRY"})          # veri setinde yok: ilişki atlanır, uyarı verilir
    assert e2["status"] == "OK" and e2["results"]["relations"] == [] and any(w.startswith("MACRO_DATA_MISSING") for w in e2["warnings"])
    e3 = _run(root, days, start, {"ticker": "NOPE"})
    assert e3["status"] == "ERROR" and e3["error"]["code"] in ("UNKNOWN_TICKER", "INVALID_PARAMS")


def test_warnings_state_association_and_multiple_testing(tmp_path):
    x, y = _xy(lambda x, j: 2.0 * x[j])
    root, days, start = build(tmp_path, x, y)
    e = _run(root, days, start, n_tests_declared=2)
    ws = " ".join(e["warnings"])
    assert "ASSOCIATION_NOT_CAUSATION" in ws and "MULTIPLE_TESTING_RISK" in ws and "COST_ASSUMPTIONS" in ws and "HISTORICAL_ONLY" in ws
    f = _rel(e)["full"]
    assert f["p_value_adjusted"] == pytest.approx(min(1.0, f["p_value_raw"] * 2), abs=1e-6)
    assert e["results"]["multiple_testing"]["adjusted_alpha"] == pytest.approx(0.025)


def test_relate_to_is_sorted_unique_and_limited(tmp_path):
    from pydantic import ValidationError
    from schemas.params import GetMacroContextParams
    a = {"ticker": "THYAO", "macro_series": "USDTRY", "horizon": 5}
    b = {"ticker": "THYAO", "macro_series": "USDTRY", "horizon": 5, "lag_days": 5}
    p1 = GetMacroContextParams(start="2024-01-01", end="2024-02-01", as_of="2024-02-01", relate_to=[b, a, a])
    p2 = GetMacroContextParams(start="2024-01-01", end="2024-02-01", as_of="2024-02-01", relate_to=[a, b])
    assert p1.relate_to == p2.relate_to and len(p1.relate_to) == 2
    with pytest.raises(ValidationError):
        GetMacroContextParams(start="2024-01-01", end="2024-02-01", as_of="2024-02-01", relate_to=[{**a, "horizon": h} for h in range(1, 8)])
