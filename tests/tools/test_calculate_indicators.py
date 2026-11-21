"""calculate_indicators aracı testleri.

(A) Sentetik snapshot (hızlı, kontrollü): sızıntı, ısınma, determinizm, adjusted/unadjusted, kompaktlık, hata zarfları.
(B) Gerçek snapshot (v2): 2024-01-01 geçerliliği, CCOLA 2024-08-01 sürekliliği, gerçek veri sızıntı testi, THYAO regresyon çıpaları.
"""
from __future__ import annotations

import copy
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from config.settings import SNAPSHOT_DIR
from config.universe import load_universe
from schemas import validate_envelope
from schemas.enums import IndicatorName
from schemas.params import IndicatorConfig
from schemas.results import CalculateIndicatorsResult
from scripts.download_prices import CANONICAL_COLUMNS
from tests.conftest import make_snapshot
from tools import calculate_indicators as tool
from tools.common import InvalidToolCall, load_snapshot

ALL = [i.value for i in IndicatorName]
needs_snapshot = pytest.mark.skipif(not (SNAPSHOT_DIR / "LATEST").exists(), reason="gerçek snapshot yok")
VERSION = "snap_2026-11-20_v2"


# =====================================================================================================
# (A) sentetik snapshot
# =====================================================================================================
N_BARS = 700
DATES = pd.bdate_range("2023-01-02", periods=N_BARS)
AS_OF_IDX = 500
AS_OF = DATES[AS_OF_IDX].date()


def _thyao(shock: bool, adj_factor: float = 0.5) -> pd.DataFrame:
    rng = np.random.default_rng(481)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, N_BARS)))
    open_ = np.r_[close[0], close[:-1]] * np.exp(rng.normal(0, 0.005, N_BARS))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, N_BARS)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, N_BARS)))
    vol = rng.lognormal(15, 0.4, N_BARS)
    df = pd.DataFrame({"ticker": "THYAO", "date": DATES, "open": open_, "high": high, "low": low, "close": close,
                       "adj_close": close * adj_factor, "volume": vol, "dividends": 0.0, "stock_splits": 0.0})
    if shock:  # as_of SONRASI satırlara aşırı değerler
        after = df.index > AS_OF_IDX
        for c in ("open", "high", "low", "close", "adj_close", "volume"):
            df.loc[after, c] = df.loc[after, c] * 1e6
    return df[CANONICAL_COLUMNS]


def _index(df: pd.DataFrame) -> pd.DataFrame:
    x = df.drop(columns=["ticker"]).copy()
    x[["open", "high", "low", "close", "adj_close"]] = 10000.0
    return x


def _snap(root, shock=False, adj_factor=0.5):
    th = _thyao(shock, adj_factor)
    return make_snapshot(root, th, _index(th), version=VERSION)


@pytest.fixture(scope="module")
def roots(tmp_path_factory):
    base = tmp_path_factory.mktemp("ind")
    return {"normal": _snap(base / "normal"), "shock": _snap(base / "shock", shock=True),
            "adj1": _snap(base / "adj1", adj_factor=1.0)}


FULL = {"include_columns_meta": True, "last_n_rows": 5}  # 1.1.0 davranışı (1.2.0 varsayılanı hafiftir: False / 0)


def call(root, **over):
    """Eski testler için: kolon meta'lı, 5 satırlı (açık). Varsayılan davranış için `call_default` kullanılır."""
    params = {"ticker": "THYAO", "indicators": ALL, "as_of": AS_OF.isoformat(), "end": AS_OF.isoformat(),
              "start": "2023-01-02", **FULL, **over}
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def call_default(root, **over):
    """include_columns_meta / last_n_rows / value_columns VERİLMEDEN (1.2.0 varsayılanları)."""
    params = {"ticker": "THYAO", "indicators": ALL, "as_of": AS_OF.isoformat(), "end": AS_OF.isoformat(),
              "start": "2023-01-02", **over}
    return tool.run_on(params, snapshot_root=root, data_version=VERSION)


def res(env) -> CalculateIndicatorsResult:
    assert env["status"] == "OK", env
    return CalculateIndicatorsResult.model_validate(env["results"])


def test_envelope_validates_with_all_indicators(roots):
    env = call(roots["normal"])
    validate_envelope(env)
    assert env["tool"] == "calculate_indicators" and env["n_events"] is None


def test_future_shock_after_as_of_does_not_change_anything(roots):
    """as_of sonrasına 1e6 kat aşırı satırlar eklenince results BİREBİR aynı (sızıntı yok); hesap as_of'a kesilmiş veride."""
    a, b = call(roots["normal"]), call(roots["shock"])
    assert a["results"] == b["results"] and a["warnings"] == b["warnings"] and a["input_hash"] == b["input_hash"]
    r = res(a)
    assert r.state_date == AS_OF and r.n_bars_used == AS_OF_IDX + 1


def test_as_of_on_non_trading_day_uses_previous_trading_day(roots):
    sat = DATES[AS_OF_IDX] - pd.Timedelta(days=2)  # AS_OF Pazartesi -> önceki Cumartesi; son işlem günü = Cuma
    assert sat.weekday() == 5
    env = call(roots["normal"], as_of=sat.date().isoformat(), end=sat.date().isoformat())
    assert res(env).state_date == DATES[AS_OF_IDX - 1].date()


def test_end_after_as_of_is_clamped_with_warning(roots):
    env = call(roots["normal"], end=(DATES[AS_OF_IDX + 30]).date().isoformat())
    assert any(w.startswith("AS_OF_CLAMPED") for w in env["warnings"])
    assert res(env).state_date == AS_OF


# --- ısınma --------------------------------------------------------------------------------------
EXPECTED_WARMUP = {  # varsayılan config için analitik ısınma (bar sayısı)
    "SMA_20": 20, "SMA_50": 50, "SMA_200": 200, "EMA_12": 12, "EMA_26": 26, "KAMA_10_2_30": 11, "RSI_14": 15,
    "MACD_12_26_9": 26, "MACD_SIGNAL_12_26_9": 34, "MACD_HIST_12_26_9": 34,
    "BB_UPPER_20_2.0": 20, "BB_MID_20_2.0": 20, "BB_LOWER_20_2.0": 20, "BB_B_20_2.0": 20,
    "BB_BANDWIDTH_PCT_20_2.0": 20, "ATR_14": 15, "SUPERTREND_10_3.0": 11, "ICHIMOKU_TENKAN_9": 9,
    "ICHIMOKU_KIJUN_26": 26, "ICHIMOKU_SENKOU_A_9_26": 52, "ICHIMOKU_SENKOU_B_52": 78,
    "ICHIMOKU_CHIKOU_VS_CLOSE_26": 27, "VOLUME_ZSCORE_20": 20,
}


def test_default_columns_and_analytic_warmup(roots):
    r = res(call(roots["normal"]))
    assert {c.name: c.warmup_bars for c in r.columns} == EXPECTED_WARMUP


def test_empirical_first_valid_date_equals_analytic_warmup(roots):
    """İlk geçerli tarih = (warmup_bars)'ıncı bar; yani analitik ısınma ile ampirik NaN sonu aynı."""
    r = res(call(roots["normal"]))
    for c in r.columns:
        assert c.first_valid_date == DATES[c.warmup_bars - 1].date(), c.name
    assert r.first_valid_date == DATES[200 - 1].date()  # en uzun ısınma: SMA_200
    assert r.history_first_date == DATES[0].date()


def test_warmup_values_are_none_and_flagged_not_nan(roots):
    """Yalnızca 30 bar veri varken uzun pencereli kolonlar None ve valid_at_as_of=False; NaN asla zarfa girmez."""
    d = DATES[29].date().isoformat()
    env = call(roots["normal"], as_of=d, end=d)
    text = json.dumps(env, allow_nan=False)  # NaN olsaydı patlardı
    assert "NaN" not in text
    r = res(env)
    valid = {c.name: c.valid_at_as_of for c in r.columns}
    assert valid["SMA_20"] and valid["EMA_12"] and valid["RSI_14"] and valid["ATR_14"] and valid["BB_B_20_2.0"]
    assert not valid["SMA_50"] and not valid["SMA_200"] and not valid["ICHIMOKU_SENKOU_B_52"]
    assert not valid["MACD_SIGNAL_12_26_9"]
    assert r.latest.values["SMA_200"] is None and r.latest.values["SMA_20"] is not None
    assert r.first_valid_date is None
    assert any(w.startswith("INSUFFICIENT_HISTORY") and "SMA_200" in w for w in env["warnings"])


def test_states_none_during_warmup_and_present_after(roots):
    d = DATES[29].date().isoformat()
    early = res(call(roots["normal"], as_of=d, end=d)).latest.states
    assert early.ichimoku_position is None and early.supertrend is not None and early.volume_regime is not None
    late = res(call(roots["normal"])).latest.states
    assert all(v is not None for v in late.model_dump().values())


# --- determinizm ---------------------------------------------------------------------------------
def test_determinism_same_input_same_output(roots):
    a, b = call(roots["normal"]), call(roots["normal"])
    assert a == b and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_input_params_not_mutated(roots):
    p = {"ticker": "THYAO", "indicators": ["RSI", "SMA"], "as_of": AS_OF.isoformat(), "end": AS_OF.isoformat()}
    before = copy.deepcopy(p)
    tool.run_on(p, snapshot_root=roots["normal"], data_version=VERSION)
    assert p == before


# --- adjusted / unadjusted -----------------------------------------------------------------------
def test_adjusted_mode_uses_adj_close_and_scales_ohlc(roots):
    """Sabit faktör 0.5: adjusted modda SMA/ATR/Bollinger yarıya iner, RSI/%B/ER ölçekten bağımsızdır."""
    adj = res(call(roots["normal"], price_adjustment="adjusted"))
    raw = res(call(roots["normal"], price_adjustment="unadjusted"))
    assert adj.price_adjustment.value == "adjusted" and raw.price_adjustment.value == "unadjusted"
    assert adj.latest.close == pytest.approx(raw.latest.close * 0.5, abs=1e-3)
    for k in ("SMA_20", "SMA_200", "ATR_14", "BB_UPPER_20_2.0", "ICHIMOKU_KIJUN_26", "KAMA_10_2_30"):
        assert adj.latest.values[k] == pytest.approx(raw.latest.values[k] * 0.5, rel=1e-4, abs=2e-4), k
    for k in ("RSI_14", "BB_B_20_2.0", "VOLUME_ZSCORE_20", "BB_BANDWIDTH_PCT_20_2.0"):
        assert adj.latest.values[k] == pytest.approx(raw.latest.values[k], rel=1e-4, abs=2e-4), k
    assert adj.latest.states == raw.latest.states


def test_default_price_adjustment_is_adjusted(roots):
    env = call(roots["normal"])
    assert env["params"]["price_adjustment"] == "adjusted"
    assert res(env).latest.close == pytest.approx(res(call(roots["normal"], price_adjustment="adjusted")).latest.close)


def test_unit_adjustment_factor_modes_equal(roots):
    a = res(call(roots["adj1"], price_adjustment="adjusted"))
    b = res(call(roots["adj1"], price_adjustment="unadjusted"))
    assert a.latest.values == b.latest.values


# --- kompaktlık / satır kontrolü -----------------------------------------------------------------
def test_compact_output_fits_small_context(roots):
    env = call(roots["normal"])  # tüm göstergeler, varsayılan last_n_rows=5
    r = res(env)
    assert len(r.recent_rows) == 5 and r.recent_rows[-1].date < r.latest.date
    assert len(json.dumps(env)) < 12000  # ~ 23 kolon x 6 satır (~3-4 bin token); tüm zaman serisi DEĞİL
    assert r.n_bars_used == AS_OF_IDX + 1 and r.n_bars_used > 100  # hesap uzun, çıktı kısa


def test_last_n_rows_zero_gives_state_only_and_max_is_30(roots):
    assert res(call(roots["normal"], last_n_rows=0)).recent_rows == []
    assert len(res(call(roots["normal"], last_n_rows=30)).recent_rows) == 30
    env = call(roots["normal"], last_n_rows=31)
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"


def test_recent_rows_respect_start_and_are_ascending(roots):
    start = DATES[AS_OF_IDX - 2].date().isoformat()
    r = res(call(roots["normal"], start=start, last_n_rows=30))
    assert [x.date for x in r.recent_rows] == [DATES[AS_OF_IDX - 2].date(), DATES[AS_OF_IDX - 1].date()]
    # hesap start'tan bağımsız: değerler start=2023'teki satırlarla aynı
    full = res(call(roots["normal"], last_n_rows=30))
    assert r.latest == full.latest and r.recent_rows == full.recent_rows[-2:]


def test_subset_of_indicators_only_those_columns(roots):
    r = res(call(roots["normal"], indicators=["RSI", "BOLLINGER"]))
    names = [c.name for c in r.columns]
    assert names == ["BB_UPPER_20_2.0", "BB_MID_20_2.0", "BB_LOWER_20_2.0", "BB_B_20_2.0", "BB_BANDWIDTH_PCT_20_2.0",
                     "RSI_14"]
    assert r.latest.states.supertrend is None and r.latest.states.kama_slope is None


def test_custom_config_changes_columns_and_hash(roots):
    base = call(roots["normal"], indicators=["SMA"])
    cfg = IndicatorConfig(sma_windows=[10, 30]).model_dump(mode="json")
    other = call(roots["normal"], indicators=["SMA"], config=cfg)
    assert [c["name"] for c in other["results"]["columns"]] == ["SMA_10", "SMA_30"]
    assert base["input_hash"] != other["input_hash"]


# --- hatalar -------------------------------------------------------------------------------------
def test_unknown_ticker_error_envelope(roots):
    env = call(roots["normal"], ticker="ZZZZZ")
    assert env["status"] == "ERROR" and env["error"]["code"] == "UNKNOWN_TICKER"
    validate_envelope(env)


def test_ticker_in_universe_but_not_in_snapshot_is_no_data(roots):
    other = next(t for t in load_universe()["ticker"] if t != "THYAO" and t != "MGROS")
    env = call(roots["normal"], ticker=other)
    assert env["status"] == "ERROR" and env["error"]["code"] == "NO_DATA"


def test_invalid_indicator_config_is_invalid_params_not_exception(roots):
    cfg = IndicatorConfig(macd_fast=26, macd_slow=12).model_dump(mode="json")
    env = call(roots["normal"], indicators=["MACD"], config=cfg)
    assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS"
    validate_envelope(env)


def test_missing_as_of_raises(roots):
    with pytest.raises(InvalidToolCall):
        tool.run_on({"ticker": "THYAO", "indicators": ["RSI"], "end": "2024-01-10"}, snapshot_root=roots["normal"],
                    data_version=VERSION)


def test_as_of_before_first_bar_returns_empty_result_with_warning(roots):
    env = call(roots["normal"], as_of="2022-12-30", end="2022-12-30", start="2022-12-01")
    r = res(env)
    assert r.latest is None and r.state_date is None and r.recent_rows == [] and r.n_bars_used == 0
    assert any(w.startswith("INSUFFICIENT_HISTORY") for w in env["warnings"])


# =====================================================================================================
# (B) gerçek snapshot
# =====================================================================================================
def real(ticker, as_of, **over):
    params = {"ticker": ticker, "indicators": ALL, "as_of": as_of, "end": as_of, **FULL, **over}
    return tool.run_on(params, snapshot_root=SNAPSHOT_DIR, data_version=VERSION)


@needs_snapshot
def test_real_all_columns_valid_on_2024_01_01_for_all_30_tickers():
    """Veri 2023-01-02'den başlar: analiz başlangıcında (2024-01-01 tatil -> 2023-12-29 durumu) tüm kolonlar geçerli."""
    tickers = list(load_universe()["ticker"])
    assert len(tickers) == 30
    for t in tickers:
        env = real(t, "2024-01-01")
        r = res(env)
        assert r.state_date == date(2023, 12, 29), t
        assert all(c.valid_at_as_of for c in r.columns), (t, [c.name for c in r.columns if not c.valid_at_as_of])
        assert all(v is not None for v in r.latest.values.values()), t
        assert all(v is not None for v in r.latest.states.model_dump().values()), t
        assert not any("INSUFFICIENT_HISTORY" in w for w in env["warnings"]), t


@needs_snapshot
def test_real_first_valid_date_is_inside_2023():
    r = res(real("THYAO", "2026-09-10"))
    assert r.history_first_date == date(2023, 1, 2)
    sma200 = next(c for c in r.columns if c.name == "SMA_200")  # en uzun ısınma: 200 bar
    assert sma200.first_valid_date is not None and sma200.first_valid_date < date(2024, 1, 1)
    assert r.first_valid_date == sma200.first_valid_date  # tüm kolonlar ilk kez o gün birlikte geçerli


@needs_snapshot
def test_real_data_leakage_truncated_snapshot_gives_identical_results(tmp_path):
    """Gerçek snapshot'ı as_of'ta KES ve yeni kökte çalıştır: sonuç, tam snapshot'la birebir aynı olmalı."""
    as_of = "2026-09-10"
    full = load_snapshot(VERSION)
    assert full.stocks["date"].max() > pd.Timestamp(as_of)  # test anlamlı: snapshot as_of sonrasını içeriyor
    cut = pd.Timestamp(as_of)
    make_snapshot(tmp_path, full.stocks[full.stocks["date"] <= cut].reset_index(drop=True),
                  full.index[full.index["date"] <= cut].reset_index(drop=True), version=VERSION)
    for t in ("THYAO", "CCOLA", "ASELS"):
        base = {"ticker": t, "indicators": ALL, "as_of": as_of, "end": as_of}
        for extra in (FULL, {}):  # tam (kolon meta'lı, 5 satır) ve 1.2.0 hafif varsayılan
            a = real(t, as_of, **({} if extra else {"include_columns_meta": False, "last_n_rows": 0}))
            b = tool.run_on({**base, **extra}, snapshot_root=tmp_path, data_version=VERSION)
            assert a["results"] == b["results"], (t, bool(extra))
            assert a["input_hash"] == b["input_hash"]


@needs_snapshot
def test_real_as_of_in_the_past_ignores_later_rows():
    """as_of=2024-06-28 ile hesaplanan son gün değerleri, as_of=2026-09-10 sonuçlarının geçmiş satırıyla aynı (nedensellik)."""
    old = res(real("THYAO", "2024-06-28"))
    assert old.state_date == date(2024, 6, 28)
    # 2026'ya kadar veri varken aynı günü iste (end=2024-06-28): değerler as_of=2024-06-28 ile birebir aynı olmalı
    wide = res(real("THYAO", "2026-09-10", start="2024-06-28", end="2024-06-28", last_n_rows=0))
    assert wide.latest == old.latest


@needs_snapshot
def test_real_thyao_regression_anchors_2026_09_10():
    """Elle doğrulanmış çıpalar (docs/gerçek sayı örnekleri); snapshot değişmez, bu yüzden sabit."""
    r = res(real("THYAO", "2026-09-10"))
    v = r.latest.values
    assert r.state_date == date(2026, 9, 10) and r.n_bars_used == 921 and r.latest.close == 299.25
    assert v["SMA_20"] == pytest.approx(301.0625, abs=1e-4)
    assert v["EMA_12"] == pytest.approx(300.2647, abs=1e-4)
    assert v["RSI_14"] == pytest.approx(44.8273, abs=1e-4)
    assert v["ATR_14"] == pytest.approx(7.0839, abs=1e-4)
    assert v["MACD_HIST_12_26_9"] == pytest.approx(0.5949, abs=1e-4)
    assert v["ICHIMOKU_TENKAN_9"] == 298.0 and v["ICHIMOKU_KIJUN_26"] == 303.75
    assert v["ICHIMOKU_SENKOU_A_9_26"] == pytest.approx(323.6875) and v["ICHIMOKU_SENKOU_B_52"] == 313.5
    assert v["ICHIMOKU_CHIKOU_VS_CLOSE_26"] == pytest.approx(-14.75)
    assert v["VOLUME_ZSCORE_20"] == pytest.approx(-0.6633, abs=1e-4)
    s = r.latest.states
    assert (s.supertrend.value, s.ichimoku_position.value, s.volume_regime.value) == ("BEARISH", "BELOW_CLOUD", "NORMAL")
    assert s.kama_slope.value == "FLATTENING"  # eğim -%0.0978: |0.0978| < 0.10


@needs_snapshot
def test_real_ccola_indicators_do_not_jump_around_2024_08_01():
    """v2'de CCOLA'nın 2024-07-31 öncesi fiyatı /11 düzeltildi: göstergelerde 1 günlük sıçrama OLMAMALI."""
    r = res(real("CCOLA", "2024-08-20", start="2024-07-10", last_n_rows=30))
    rows = [*r.recent_rows, r.latest]
    assert min(x.date for x in rows) <= date(2024, 7, 29) and max(x.date for x in rows) >= date(2024, 8, 5)
    df = pd.DataFrame([{"date": x.date, "close": x.close, **x.values} for x in rows]).set_index("date")
    ch = df.pct_change().abs().dropna(how="all")
    assert ch["close"].max() < 0.105                                   # fiyatın kendisi ±%10 limit içinde
    for col in ("SMA_20", "SMA_50", "EMA_12", "EMA_26", "KAMA_10_2_30", "BB_MID_20_2.0", "ICHIMOKU_KIJUN_26"):
        assert ch[col].max() < 0.05, (col, ch[col].idxmax(), ch[col].max())
    for col in ("ATR_14", "BB_UPPER_20_2.0", "BB_LOWER_20_2.0"):
        assert ch[col].max() < 0.20, (col, ch[col].idxmax(), ch[col].max())


@needs_snapshot
def test_real_ccola_v1_does_jump_proving_the_test_is_sensitive():
    """Aynı testin v1 (düzeltilmemiş) snapshot'ta KIRILDIĞINI göster: test gerçekten sıçramayı yakalıyor."""
    params = {"ticker": "CCOLA", "indicators": ALL, "as_of": "2024-08-20", "end": "2024-08-20", "start": "2024-07-10",
              "last_n_rows": 30}
    env = tool.run_on(params, snapshot_root=SNAPSHOT_DIR, data_version="snap_2026-11-20_v1")
    r = res(env)
    df = pd.DataFrame([{"date": x.date, "close": x.close, **x.values} for x in [*r.recent_rows, r.latest]]).set_index("date")
    assert df["close"].pct_change().abs().max() > 0.5   # ~ -%90 sıçrama
    assert df["SMA_20"].pct_change().abs().max() > 0.05


@needs_snapshot
def test_real_adjusted_vs_unadjusted_modes_use_the_right_price_columns():
    """FROTO: adjusted modda kapanış = adj_close, unadjusted modda = close (Yahoo close'u bölünme-düzeltmelidir,
    temettü düzeltmesizdir; docs §11.3). Bölünme (2025-05-07) iki modda da sıçrama yaratmamalı; iki mod birbirinden farklı."""
    snap = load_snapshot(VERSION)
    fr = snap.stocks[(snap.stocks.ticker == "FROTO") & (snap.stocks.date == "2025-05-30")].iloc[0]
    kw = dict(start="2025-04-20", last_n_rows=30)
    adj = res(real("FROTO", "2025-05-30", price_adjustment="adjusted", **kw))
    raw = res(real("FROTO", "2025-05-30", price_adjustment="unadjusted", **kw))
    assert adj.latest.close == pytest.approx(fr["adj_close"], abs=1e-4)
    assert raw.latest.close == pytest.approx(fr["close"], abs=1e-4)
    assert adj.latest.close != raw.latest.close and adj.latest.values["SMA_20"] != raw.latest.values["SMA_20"]
    for r in (adj, raw):
        c = pd.Series([x.close for x in [*r.recent_rows, r.latest]])
        assert c.pct_change().abs().max() < 0.105
    # High/Low da aynı faktörle ölçeklendiği için Supertrend/Ichimoku durumu iki modda tutarlı çalışır (hata yok, durumlar dolu)
    assert adj.latest.states.supertrend is not None and raw.latest.states.supertrend is not None


@needs_snapshot
def test_real_determinism_and_schema_validity():
    a, b = real("THYAO", "2026-09-10"), real("THYAO", "2026-09-10")
    assert a == b
    validate_envelope(a)
    assert a["data_version"] == VERSION


# =====================================================================================================
# (C) şema 1.2.0: hafif varsayılanlar, kolon meta isteğe bağlı, value_columns (docs/schema_1_2_0_plan.md)
# =====================================================================================================
def test_default_call_is_light_no_columns_no_recent_rows(roots):
    env = call_default(roots["normal"])
    validate_envelope(env)
    r = res(env)
    assert env["schema_version"] == "1.2.0"
    assert env["params"]["last_n_rows"] == 0 and env["params"]["include_columns_meta"] is False
    assert env["params"]["value_columns"] is None
    assert (r.columns_meta_included, r.columns, r.recent_rows) == (False, [], [])
    assert r.invalid_columns_at_as_of == []  # as_of'ta (bar 501) tüm kolonlar geçerli
    assert set(r.latest.values) == set(EXPECTED_WARMUP)


def test_light_and_full_agree_on_numbers_and_flag_the_same_warmup_columns(roots):
    """Hafif zarf, tam zarfın bilgisini kaybetmez: latest, first_valid_date, n_bars_used aynı; ısınmadaki kolonlar adıyla listelenir."""
    d = DATES[29].date().isoformat()  # 30 bar: uzun pencereli kolonlar ısınmada
    light, full = res(call_default(roots["normal"], as_of=d, end=d)), res(call(roots["normal"], as_of=d, end=d))
    assert light.latest == full.latest and light.first_valid_date == full.first_valid_date
    assert light.n_bars_used == full.n_bars_used == 30
    assert light.invalid_columns_at_as_of == sorted(c.name for c in full.columns if not c.valid_at_as_of)
    assert "SMA_200" in light.invalid_columns_at_as_of and "SMA_20" not in light.invalid_columns_at_as_of
    assert full.invalid_columns_at_as_of == light.invalid_columns_at_as_of and full.columns_meta_included is True


def test_light_envelope_is_much_smaller_than_the_1_1_0_default(roots):
    light, old = json.dumps(call_default(roots["normal"])), json.dumps(call(roots["normal"]))
    assert len(light) < 0.5 * len(old)
    assert len(light) < 3500  # tüm göstergeler, sentetik veri; gerçek veri testi aşağıda (bağlam bütçesi)


def test_value_columns_restricts_values_and_first_valid_date(roots):
    env = call_default(roots["normal"], value_columns=["SMA_50", "RSI_14", "SMA_50"], include_columns_meta=True)
    validate_envelope(env)
    r = res(env)
    assert env["params"]["value_columns"] == ["RSI_14", "SMA_50"]  # sıralı-tekil
    assert set(r.latest.values) == {"RSI_14", "SMA_50"} and [c.name for c in r.columns] == ["RSI_14", "SMA_50"]
    assert r.first_valid_date == DATES[50 - 1].date()  # seçilen kolonların ilk ortak geçerli günü (SMA_50)
    assert r.latest.states.supertrend is not None  # durumlar istenen göstergelerden gelir, value_columns'tan bağımsız


def test_value_columns_only_affects_insufficient_history_for_selected_columns(roots):
    d = DATES[29].date().isoformat()
    ok = call_default(roots["normal"], as_of=d, end=d, value_columns=["SMA_20"])
    assert not any(w.startswith("INSUFFICIENT_HISTORY") for w in ok["warnings"]) and res(ok).invalid_columns_at_as_of == []
    bad = call_default(roots["normal"], as_of=d, end=d, value_columns=["SMA_200", "SMA_20"])
    assert any(w.startswith("INSUFFICIENT_HISTORY") and "SMA_200" in w for w in bad["warnings"])
    assert res(bad).invalid_columns_at_as_of == ["SMA_200"]


def test_unknown_value_column_is_invalid_params_listing_valid_names(roots):
    # (1) hiç olmayan kolon; (2) geçerli ad ama bu çağrıda hesaplanmayan gösterge (yalnız RSI istendi)
    for cols, indicators, bad, listed in ((["RSI_99"], ALL, "RSI_99", "SMA_20"), (["SMA_20"], ["RSI"], "SMA_20", "RSI_14")):
        env = call_default(roots["normal"], value_columns=cols, indicators=indicators)
        assert env["status"] == "ERROR" and env["error"]["code"] == "INVALID_PARAMS" and env["results"] is None
        assert bad in env["error"]["message"] and listed in env["error"]["message"]
        validate_envelope(env)


def test_value_columns_changes_hash_but_order_does_not(roots):
    a = call_default(roots["normal"], value_columns=["RSI_14", "SMA_50"])
    b = call_default(roots["normal"], value_columns=["SMA_50", "RSI_14"])
    c = call_default(roots["normal"])
    assert a["input_hash"] == b["input_hash"] != c["input_hash"]


def test_light_determinism_and_future_shock(roots):
    assert call_default(roots["normal"]) == call_default(roots["normal"])
    a, b = call_default(roots["normal"]), call_default(roots["shock"])
    assert a["results"] == b["results"] and a["input_hash"] == b["input_hash"]


def test_empty_result_before_first_bar_is_consistent_in_light_mode(roots):
    env = call_default(roots["normal"], as_of="2022-12-30", end="2022-12-30", start="2022-12-01")
    validate_envelope(env)
    r = res(env)
    assert r.latest is None and r.columns == [] and r.invalid_columns_at_as_of == []


@needs_snapshot
def test_real_light_default_fits_small_context_budget():
    params = {"ticker": "THYAO", "indicators": ALL, "as_of": "2026-09-10", "end": "2026-09-10"}
    light = tool.run_on(params, snapshot_root=SNAPSHOT_DIR, data_version=VERSION)
    validate_envelope(light)
    full = tool.run_on({**params, **FULL}, snapshot_root=SNAPSHOT_DIR, data_version=VERSION)
    assert len(json.dumps(light)) < 0.5 * len(json.dumps(full))
    assert len(json.dumps(light)) < 2600  # ölçüm (THYAO, 2026-09-10, 23 kolon): 2226 karakter; 1.1.0 varsayılanı 9124
    r = res(light)
    assert r.invalid_columns_at_as_of == [] and r.latest.values == res(full).latest.values
