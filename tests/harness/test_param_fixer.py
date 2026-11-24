"""Parametre düzeltici: modelin BİÇİM hatalarını (dönem yazımı, büyük/küçük harf, fazla alan) araç çağrılmadan önce düzeltir.
Değişmezler: as_of'a asla dokunulmaz; anlam değiştiren düzeltme yapılmaz; belirsizse düzeltme YOK; her düzeltme not olarak döner (sessiz değil)."""
from __future__ import annotations

from datetime import date

import pytest

from harness.param_fixer import fix_params
from harness.session import HarnessSession
from schemas.enums import ToolName as T
from schemas.registry import validate_params

AS_OF = date(2026, 11, 13)


def _fund(**kw):
    return {"as_of": "2026-11-13", "ticker": "TTKOM", **kw}


@pytest.mark.parametrize("raw,want", [
    ("Q3", "2026Q3"),            # yılsız: as_of yılı (dönem sonu as_of'u aşmıyor)
    ("q3", "2026Q3"),
    ("2026-Q3", "2026Q3"),
    ("2026 Q3", "2026Q3"),
    ("Q3 2026", "2026Q3"),
    ("Q3-2026", "2026Q3"),
    ("2026/Q3", "2026Q3"),
    ("2025q4", "2025Q4"),
])
def test_period_formats_are_repaired(raw, want):
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, _fund(period=raw), AS_OF)
    assert fixed["period"] == want and notes
    validate_params(T.GET_FUNDAMENTAL_METRICS, fixed)


def test_bare_quarter_after_as_of_falls_back_to_previous_year():
    """Q4'ün dönem sonu (31 Aralık) as_of'tan sonraysa bir önceki yıl alınır (as_of sonrası dönem seçilmez)."""
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, _fund(period="Q4"), AS_OF)
    assert fixed["period"] == "2025Q4" and notes


@pytest.mark.parametrize("raw", ["son çeyrek", "latest", "2026", "Q5", "2026Q5", "", "bu yıl"])
def test_unparseable_period_is_not_guessed(raw):
    """Belirsiz/yanlış değer tahmin edilmez; orijinal hata modele döner."""
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, _fund(period=raw), AS_OF)
    assert fixed is None and notes == []


def test_valid_params_untouched():
    p = _fund(period="2026Q3")
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, p, AS_OF)
    assert fixed is None and notes == []


def test_enum_case_is_repaired_only_when_unique():
    p = {"as_of": "2026-11-13", "ticker": "ASELS", "start": "2025-01-01", "end": "2026-11-13", "indicators": ["RSI", "Ichimoku"]}
    fixed, notes = fix_params(T.CALCULATE_INDICATORS, p, AS_OF)
    assert fixed is not None and fixed["indicators"] == ["RSI", "ICHIMOKU"] and notes
    validate_params(T.CALCULATE_INDICATORS, fixed)


def test_enum_unknown_value_is_not_guessed():
    p = {"as_of": "2026-11-13", "ticker": "ASELS", "start": "2025-01-01", "end": "2026-11-13", "indicators": ["RSI14"]}
    fixed, notes = fix_params(T.CALCULATE_INDICATORS, p, AS_OF)
    assert fixed is None and notes == []


def test_as_of_is_never_touched():
    """as_of yanlışsa düzeltici dokunmaz (as_of kuralı: oturum tarafından kilitli)."""
    p = _fund(period="Q3")
    p["as_of"] = "13.11.2026"
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, p, AS_OF)
    assert fixed is None or fixed["as_of"] == "13.11.2026"


def test_unknown_extra_field_is_dropped_with_note():
    p = {"as_of": "2026-11-13", "ticker": "TTKOM", "period": "2026Q3", "event_family": "RSI_LOCAL_TROUGH"}
    fixed, notes = fix_params(T.GET_FUNDAMENTAL_METRICS, p, AS_OF)
    assert fixed is not None and "event_family" not in fixed
    assert any("event_family" in n for n in notes)


def test_deterministic():
    a = fix_params(T.GET_FUNDAMENTAL_METRICS, _fund(period="Q3"), AS_OF)
    b = fix_params(T.GET_FUNDAMENTAL_METRICS, _fund(period="Q3"), AS_OF)
    assert a == b


def test_input_not_mutated():
    p = _fund(period="Q3")
    before = dict(p)
    fix_params(T.GET_FUNDAMENTAL_METRICS, p, AS_OF)
    assert p == before


# ---- oturum entegrasyonu ------------------------------------------------------------------------------------------------
def _session(**kw):
    return HarnessSession.from_question("Analiz tarihi: 13.11.2026\nTTKOM cari oranı son çeyrekte nasıl?", profile="D", **kw)


def test_session_runs_repaired_call_and_records_note(monkeypatch):
    monkeypatch.setenv("HARNESS_NORMALIZE_PARAMS", "1")
    s = _session()
    r = s.call_tool("get_fundamental_metrics", _fund(period="Q3"))
    assert r.ok, r.error
    assert r.envelope["params"]["period"] == "2026Q3"          # çalışan çağrı = düzeltilmiş çağrı (input_hash buna göre)
    assert any(w.startswith("PARAMS_NORMALIZED") for w in s.warnings)
    assert any(e["kind"] == "PARAMS_NORMALIZED" for e in s.log.events)


def test_session_flag_off_keeps_original_error(monkeypatch):
    monkeypatch.setenv("HARNESS_NORMALIZE_PARAMS", "0")
    s = _session()
    r = s.call_tool("get_fundamental_metrics", _fund(period="Q3"))
    assert not r.ok and r.error["code"] == "INVALID_PARAMS"


def test_session_unfixable_still_returns_error_with_hint(monkeypatch):
    monkeypatch.setenv("HARNESS_NORMALIZE_PARAMS", "1")
    s = _session()
    r = s.call_tool("get_fundamental_metrics", _fund(period="son çeyrek"))
    assert not r.ok and r.error["code"] == "INVALID_PARAMS"
    assert "2026Q3" in r.error["message"] or "YYYYQn" in r.error["message"]   # biçim ipucu
