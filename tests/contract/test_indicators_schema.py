"""calculate_indicators sonuç/params sözleşmesi (1.1.0 kuralları, 1.2.0'da korunur): kompakt, sayı/kategori ayrık, ısınma açık.

Kolon meta kuralları `columns_meta_included=True` (tam varyant) üzerinde sınanır; hafif varsayılanlar test_schema_1_2_0.py'de."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from schemas import SCHEMA_VERSION, ToolName, validate_envelope
from schemas.enums import IchimokuState, KamaSlope, PriceAdjustment, SupertrendState, VolumeRegime
from schemas import examples
from schemas.examples import example_params
from schemas.params import CalculateIndicatorsParams
from schemas.results import CalculateIndicatorsResult, IndicatorRow, IndicatorStates

TOOL = ToolName.CALCULATE_INDICATORS


def _full() -> dict:
    """Kolon meta'lı (1.1.0 biçimli) örnek zarf."""
    return copy.deepcopy(examples.example_envelope_indicators_full())


def _res() -> dict:
    return copy.deepcopy(_full()["results"])


def _validate(res: dict) -> CalculateIndicatorsResult:
    return CalculateIndicatorsResult.model_validate(res)


def test_schema_version_is_at_least_1_1_0():
    major, minor, _ = (int(x) for x in SCHEMA_VERSION.split("."))
    assert (major, minor) >= (1, 1)


# --- params -------------------------------------------------------------------------------------
def test_params_defaults_price_adjustment_and_last_n_rows():  # 1.2.0: last_n_rows varsayılanı 0
    p = CalculateIndicatorsParams.model_validate(example_params(TOOL))
    assert p.price_adjustment == PriceAdjustment.ADJUSTED
    assert p.last_n_rows == 0


@pytest.mark.parametrize("n", [-1, 31])
def test_params_last_n_rows_bounds(n):
    raw = example_params(TOOL)
    raw["last_n_rows"] = n
    with pytest.raises(ValidationError):
        CalculateIndicatorsParams.model_validate(raw)


@pytest.mark.parametrize("n", [0, 30])
def test_params_last_n_rows_accepts_edges(n):
    raw = example_params(TOOL)
    raw["last_n_rows"] = n
    assert CalculateIndicatorsParams.model_validate(raw).last_n_rows == n


# --- örnek zarf ----------------------------------------------------------------------------------
def test_example_envelope_is_strict_ok():
    env = validate_envelope(_full())
    res = _validate(env.results)  # type: ignore[arg-type]
    assert res.latest is not None and res.latest.date == res.state_date
    assert set(res.latest.values) == {c.name for c in res.columns}


# --- sayı / kategori ayrımı ----------------------------------------------------------------------
def test_values_must_be_numeric_only_no_strings():
    res = _res()
    res["latest"]["values"]["RSI_14"] = "BEARISH"
    with pytest.raises(ValidationError):
        _validate(res)


def test_values_reject_nan_and_inf():
    for bad in (float("nan"), float("inf")):
        res = _res()
        res["latest"]["values"]["RSI_14"] = bad
        with pytest.raises(ValidationError):
            _validate(res)


def test_states_use_existing_enums_and_reject_unknown_values():
    st = IndicatorStates(supertrend=SupertrendState.BULLISH, ichimoku_position=IchimokuState.IN_CLOUD,
                         kama_slope=KamaSlope.FLATTENING, volume_regime=VolumeRegime.NORMAL)
    assert st.supertrend == SupertrendState.BULLISH
    with pytest.raises(ValidationError):
        IndicatorStates.model_validate({"supertrend": "BUY"})
    with pytest.raises(ValidationError):
        IndicatorStates.model_validate({"unknown_state": "X"})


# --- ısınma (None) ve sütun tutarlılığı ----------------------------------------------------------
def test_warmup_value_is_none_and_column_flagged_invalid():
    res = _res()
    res["latest"]["values"]["RSI_14"] = None
    res["columns"][0]["valid_at_as_of"] = False
    res["invalid_columns_at_as_of"] = ["RSI_14"]  # 1.2.0: None değerli kolonlar burada da listelenir
    _validate(res)  # tutarlı: değer None <-> valid_at_as_of False


def test_valid_flag_must_match_latest_value():
    res = _res()
    res["latest"]["values"]["RSI_14"] = None  # valid_at_as_of True kaldı
    with pytest.raises(ValueError, match="valid_at_as_of"):
        _validate(res)


def test_row_values_keys_must_equal_columns():
    res = _res()
    res["latest"]["values"]["EKSTRA_1"] = 1.0
    with pytest.raises(ValueError, match="columns"):
        _validate(res)
    res = _res()
    res["latest"]["values"].pop("RSI_14")
    with pytest.raises(ValueError, match="columns"):
        _validate(res)


def test_column_names_unique_and_well_formed():
    res = _res()
    res["columns"].append(copy.deepcopy(res["columns"][0]))
    with pytest.raises(ValueError, match="tekil"):
        _validate(res)
    res = _res()
    res["columns"][0]["name"] = "rsi 14"
    with pytest.raises(ValidationError):
        _validate(res)


def test_column_without_first_valid_date_cannot_be_valid():
    res = _res()
    res["columns"][0]["first_valid_date"] = None
    with pytest.raises(ValueError, match="first_valid_date"):
        _validate(res)


# --- latest / recent_rows düzeni -----------------------------------------------------------------
def _row(d: str, rsi: float | None = 40.0) -> dict:
    return {"date": d, "close": 10.0, "values": {"RSI_14": rsi}, "states": {}}


def test_recent_rows_must_be_ascending_and_before_latest():
    res = _res()
    res["recent_rows"] = [_row("2026-09-08"), _row("2026-09-09")]
    _validate(res)  # latest = 2026-09-10
    res["recent_rows"] = [_row("2026-09-09"), _row("2026-09-08")]
    with pytest.raises(ValueError, match="artan"):
        _validate(res)
    res["recent_rows"] = [_row("2026-09-10")]  # latest ile aynı gün
    with pytest.raises(ValueError, match="latest"):
        _validate(res)


def test_latest_none_iff_state_date_none_and_no_rows():
    res = _res()
    res.update(latest=None, recent_rows=[], state_date=None, first_valid_date=None, history_first_date=None,
               n_bars_used=0)
    for c in res["columns"]:
        c.update(first_valid_date=None, valid_at_as_of=False)
    _validate(res)  # boş ama tutarlı
    res["state_date"] = "2026-09-10"
    with pytest.raises(ValueError, match="state_date"):
        _validate(res)


def test_latest_date_must_equal_state_date():
    res = _res()
    res["state_date"] = "2026-09-09"
    with pytest.raises(ValueError, match="state_date"):
        _validate(res)


def test_row_model_is_strict():
    with pytest.raises(ValidationError):
        IndicatorRow.model_validate({**_row("2026-09-10"), "extra": 1})


# --- look-ahead (zarf düzeyi) --------------------------------------------------------------------
def test_state_date_after_as_of_is_caught_as_lookahead():
    env = _full()
    env["results"]["state_date"] = "2026-09-11"
    env["results"]["latest"]["date"] = "2026-09-11"
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_column_first_valid_date_after_as_of_is_caught():
    env = _full()
    env["results"]["columns"][0]["first_valid_date"] = "2026-09-11"
    with pytest.raises(ValueError):
        validate_envelope(env)


def test_latest_row_date_after_as_of_is_caught():
    env = _full()
    env["results"]["recent_rows"] = []
    env["results"]["latest"]["date"] = "2026-09-12"
    env["results"]["state_date"] = "2026-09-12"
    with pytest.raises(ValueError):
        validate_envelope(env)
