"""get_macro_context (minimum sürüm): yayın tarihi hizalaması, as_of sızıntısı, boşluk, eksik seri, determinizm."""
from __future__ import annotations

import pandas as pd
import pytest

from schemas import validate_envelope
from scripts.download_macro import write_macro_snapshot
from tests.conftest import make_frame, make_snapshot
from tools import get_macro_context as MC

AS_OF = "2026-09-10"
MV = "macro_2026-11-21_v1"
DV = "snap_2026-11-20_v2"
DAYS = pd.bdate_range("2026-08-24", "2026-09-18")  # 2026-09-11 ve sonrası as_of'tan sonra


def _rows(series, obs, pub, vals):
    return pd.DataFrame({"series": series, "observation_date": pd.to_datetime(obs), "publication_date": pd.to_datetime(pub), "value": vals})


def _macro_table():
    fx = _rows("USDTRY", DAYS, DAYS, [41.0 + i * 0.1 for i in range(len(DAYS))])
    cpi = _rows("CPI_ANNUAL", ["2026-06-30", "2026-07-31", "2026-08-31"], ["2026-07-03", "2026-08-03", "2026-09-03"], [33.0, 32.0, 31.0])
    fut = _rows("CPI_ANNUAL", ["2026-09-30"], ["2026-10-05"], [99.0])  # gelecek açıklama: as_of'ta GÖRÜNMEZ
    return pd.concat([fx, cpi, fut], ignore_index=True)


def _prices(root):
    make_snapshot(root, make_frame("THYAO", 100, DAYS, 1.0), make_frame("XU100", 10000, DAYS, 1.0).drop(columns=["ticker"]), version=DV)


@pytest.fixture()
def env(tmp_path):
    _prices(tmp_path)
    write_macro_snapshot(_macro_table(), tmp_path, MV, {})
    return tmp_path


def _run(env, **p):
    base = {"start": "2026-06-01", "end": "2026-12-31", "as_of": AS_OF}
    return MC.run_on({**base, **p}, snapshot_root=env, data_version=DV, macro_version=MV)


def _s(e, name):
    return next(s for s in e["results"]["series"] if s["series"] == name)


def test_valid_envelope_and_clamp_warning(env):
    e = _run(env, series=["USDTRY", "CPI_ANNUAL"])
    validate_envelope(e)
    assert e["results"]["end"] == AS_OF and any(w.startswith("AS_OF_CLAMPED") for w in e["warnings"])
    assert all(p["observation_date"] <= AS_OF for s in e["results"]["series"] for p in s["points"])


def test_alignment_by_publication_date_not_observation_date(env):
    # Ağustos TÜFE gözlemi 31 Ağu, yayın 3 Eyl: as_of 2 Eyl'de GÖRÜNMEZ, 3 Eyl'de görünür
    before = _run(env, series=["CPI_ANNUAL"], as_of="2026-09-02")
    assert [p["observation_date"] for p in _s(before, "CPI_ANNUAL")["points"]] == ["2026-06-30", "2026-07-31"]
    after = _run(env, series=["CPI_ANNUAL"], as_of="2026-09-03")
    pts = _s(after, "CPI_ANNUAL")["points"]
    assert pts[-1]["observation_date"] == "2026-08-31" and pts[-1]["publication_date"] == "2026-09-03" and pts[-1]["value"] == 31.0
    assert _s(after, "CPI_ANNUAL")["last_publication_date"] == "2026-09-03"


def test_future_rows_never_leak(env):
    e = _run(env, series=["USDTRY", "CPI_ANNUAL"], end="2026-12-31")
    assert 99.0 not in [p["value"] for s in e["results"]["series"] for p in s["points"]]
    assert max(p["publication_date"] for s in e["results"]["series"] for p in s["points"]) <= AS_OF


def test_missing_series_warns_and_all_missing_is_error(env):
    e = _run(env)  # varsayılan: tüm MacroSeries; FED/EURTRY/politika faizi veri setinde yok
    assert {s["series"] for s in e["results"]["series"]} == {"CPI_ANNUAL", "USDTRY"}
    w = [x for x in e["warnings"] if x.startswith("MACRO_DATA_MISSING")]
    assert len(w) == 1 and "FED_FUNDS_UPPER" in w[0] and "TCMB_POLICY_RATE" in w[0]
    bad = _run(env, series=["FED_FUNDS_UPPER"])        # hiçbir seri yok: hata DEĞİL, boş sonuç + MACRO_DATA_MISSING
    assert bad["status"] == "OK" and bad["results"]["series"] == [] and any(w.startswith("MACRO_DATA_MISSING") for w in bad["warnings"])
    validate_envelope(bad)


def test_gaps_leading_and_none_for_dense_monthly(env):
    e = _run(env, series=["USDTRY"], start="2026-08-01", end="2026-09-10")
    assert _s(e, "USDTRY")["gaps"] == [{"start": "2026-08-01", "end": "2026-08-23"}]  # veri 24 Ağu'da başlıyor
    e2 = _run(env, series=["CPI_ANNUAL"], start="2026-06-01", end="2026-09-10")
    assert _s(e2, "CPI_ANNUAL")["gaps"] == []  # aylık: boşluklar 40 gün eşiğinin altında


def test_range_after_as_of_and_missing_dataset_error(env, tmp_path_factory):
    e = _run(env, start="2026-09-11", end="2026-09-18")
    assert e["status"] == "ERROR" and e["error"]["code"] == "NO_DATA"
    empty = tmp_path_factory.mktemp("e")
    _prices(empty)  # makro veri seti yok
    out = MC.run_on({"start": "2026-06-01", "end": "2026-09-10", "as_of": AS_OF, "series": ["USDTRY", "TCMB_POLICY_RATE"]}, snapshot_root=empty, data_version=DV)
    assert out["status"] == "OK" and out["results"]["series"] == []
    w = [x for x in out["warnings"] if x.startswith("MACRO_DATA_MISSING")]
    assert len(w) == 1 and "USDTRY" in w[0] and "TCMB_POLICY_RATE" in w[0] and "makro veri seti yok" in w[0]
    validate_envelope(out)


def test_determinism_and_hash_changes_with_params(env):
    a, b = _run(env, series=["USDTRY"]), _run(env, series=["USDTRY"])
    assert a == b and len(a["input_hash"]) == 64
    assert _run(env, series=["USDTRY"], as_of="2026-09-09")["input_hash"] != a["input_hash"]


def test_dataset_version_in_warning(env):
    assert any(w.startswith("HISTORICAL_ONLY") and MV in w for w in _run(env, series=["USDTRY"])["warnings"])


# --- şema 1.4.0: TCMB_FUNDING_COST, tatil ileri doldurma, tatil dışı boşluk --------------------------------
HOL = pd.Timestamp("2026-09-02")  # sentetik "resmî tatil": işlem takviminde yok, makro seride yok


def _fx_funding_table(skip=(), end="2026-09-18"):
    days = [d for d in pd.bdate_range("2026-08-24", end) if d not in {pd.Timestamp(x) for x in skip}]
    rows = []
    for name, base in (("USDTRY", 41.0), ("TCMB_FUNDING_COST", 40.0)):
        rows.append(_rows(name, days, days, [base + i * 0.1 for i in range(len(days))]))
    return pd.concat(rows, ignore_index=True)


def _env_with(tmp_path, table, calendar_skip=()):
    from tests.conftest import make_frame, make_snapshot
    cal = [d for d in DAYS if d not in {pd.Timestamp(x) for x in calendar_skip}]
    make_snapshot(tmp_path, make_frame("THYAO", 100, cal, 1.0), make_frame("XU100", 10000, cal, 1.0).drop(columns=["ticker"]), version=DV)
    write_macro_snapshot(table, tmp_path, MV, {})
    return tmp_path


def _pts(e, name):
    return {p["observation_date"]: p for p in _s(e, name)["points"]}


def test_funding_cost_is_a_macro_series_and_policy_rate_is_not_substituted():
    from schemas import SCHEMA_VERSION
    from schemas.enums import MacroSeries
    assert MacroSeries.TCMB_FUNDING_COST.value == "TCMB_FUNDING_COST"
    assert tuple(int(x) for x in SCHEMA_VERSION.split(".")) >= (1, 4, 0)
    assert "TCMB_POLICY_RATE" in {m.value for m in MacroSeries}  # enum'da kalır (indirilmez)


def test_holiday_is_forward_filled_not_missing(tmp_path):
    env = _env_with(tmp_path, _fx_funding_table(skip=[HOL]), calendar_skip=[HOL])
    e = _run(env, series=["USDTRY", "TCMB_FUNDING_COST"], start="2026-08-24", end="2026-09-10")
    validate_envelope(e)
    for name in ("USDTRY", "TCMB_FUNDING_COST"):
        pts = _pts(e, name)
        prev, hol = pts["2026-09-01"], pts["2026-09-02"]
        assert hol["value"] == prev["value"]                       # son gözlem taşındı (ileri doldurma)
        assert hol["publication_date"] == "2026-09-02"             # taşınan nokta tatil gününde bilinir; geriye doldurma yok
        assert pts["2026-09-03"]["value"] != prev["value"]
    assert not [w for w in e["warnings"] if w.startswith("MACRO_DATA_MISSING")]
    assert any(w.startswith("HISTORICAL_ONLY") and "ileri dolduruldu" in w and "2026-09-02" in w for w in e["warnings"])


def test_non_holiday_gap_warns_macro_data_missing_and_is_not_filled(tmp_path):
    # makroda 2026-09-02 yok AMA işlem takviminde var (tatil değil) -> doldurulmaz, MACRO_DATA_MISSING
    env = _env_with(tmp_path, _fx_funding_table(skip=[HOL]))
    e = _run(env, series=["USDTRY"], start="2026-08-24", end="2026-09-10")
    assert "2026-09-02" not in _pts(e, "USDTRY")
    w = [x for x in e["warnings"] if x.startswith("MACRO_DATA_MISSING")]
    assert len(w) == 1 and "USDTRY" in w[0] and "2026-09-02" in w[0] and "tatil dışı" in w[0]
    assert not any("ileri dolduruldu" in x for x in e["warnings"])


def test_no_backward_fill_before_first_observation_and_weekends_not_filled(tmp_path):
    env = _env_with(tmp_path, _fx_funding_table(), calendar_skip=[pd.Timestamp("2026-08-24")])  # ilk gözlem günü takvimde yok
    e = _run(env, series=["USDTRY"], start="2026-08-17", end="2026-09-10")
    pts = _pts(e, "USDTRY")
    assert min(pts) == "2026-08-24"                                # öncesine (geriye) nokta eklenmez
    assert "2026-08-29" not in pts and "2026-08-30" not in pts      # hafta sonu doldurulmaz


def test_nothing_after_as_of_enters_output_including_filled_points(tmp_path):
    hol_after = pd.Timestamp("2026-09-14")                         # as_of (09-10) SONRASI tatil
    env = _env_with(tmp_path, _fx_funding_table(skip=[HOL, hol_after]), calendar_skip=[HOL])
    for as_of in ("2026-09-10", "2026-09-02", "2026-09-01"):
        e = _run(env, series=["USDTRY", "TCMB_FUNDING_COST"], start="2026-08-01", end="2026-12-31", as_of=as_of)
        for s in e["results"]["series"]:
            assert all(p["observation_date"] <= as_of and p["publication_date"] <= as_of for p in s["points"]), (as_of, s["series"])
        assert e["results"]["end"] == as_of
    e = _run(env, series=["USDTRY"], start="2026-08-01", end="2026-12-31")
    assert "2026-09-14" not in _pts(e, "USDTRY") and "2026-09-11" not in _pts(e, "USDTRY")


def test_filled_output_is_deterministic(tmp_path):
    env = _env_with(tmp_path, _fx_funding_table(skip=[HOL]), calendar_skip=[HOL])
    a, b = (_run(env, series=["TCMB_FUNDING_COST"], start="2026-08-24", end="2026-09-10") for _ in range(2))
    assert a == b


def test_monthly_series_never_forward_filled(env):
    e = _run(env, series=["CPI_ANNUAL"], start="2026-06-01", end="2026-09-10")
    assert [p["observation_date"] for p in _s(e, "CPI_ANNUAL")["points"]] == ["2026-06-30", "2026-07-31", "2026-08-31"]
