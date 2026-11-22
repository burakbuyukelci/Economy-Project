"""Sahte (mock) araçlar: gerçek araçlar bitene kadar harness'i uçtan uca denemek için.

Çıktı = `schemas/examples.py` örnek zarfı; yalnızca params / as_of / data_version / input_hash
çağrıya göre yeniden kurulur. Her çıktı `validate_envelope`'tan geçer.

UYARI: Mock çıktılar uydurmadır. EĞİTİM VERİSİNE GİRMEMELİDİR. Koruma: mock zarfın
`data_version` değeri `settings.MOCK_DATA_VERSION` sentinelidir. Eğitim verisi üreten kod `assert_training_eligible()`
çağırır: mock ve v1 reddedilir, yalnızca snap_*_v2 ve sonraki üretilmiş sürümler geçer (CLAUDE.md kural 12).
Bilinen sınırlama: sonuç sabittir; `results` içindeki ticker vb. alanlar çağrıdakiyle uyuşmayabilir.
"""
from __future__ import annotations

import re
from typing import Any

from harness import settings
from schemas.enums import ToolName, ToolStatus
from schemas.examples import example_envelope
from schemas.hashing import compute_input_hash
from schemas.registry import validate_envelope, validate_params


_DATA_VERSION_RE = re.compile(r"^snap_\d{4}-\d{2}-\d{2}_v(\d+)$")
_FUND_VERSION_RE = re.compile(r"fundamentals_\d{4}-\d{2}-\d{2}_v\d+")
_MACRO_VERSION_RE = re.compile(r"macro_\d{4}-\d{2}-\d{2}_v\d+")
# Bilanço/makro araçlarının sürümü: araçlar sürümü `HISTORICAL_ONLY` uyarı metninde taşır (zarfta ikincil sürüm alanı yok).
_AUX_TOOLS = {"get_fundamental_metrics": ("fundamentals", _FUND_VERSION_RE), "calculate_fundamental_change": ("fundamentals", _FUND_VERSION_RE),
              "get_macro_context": ("macro", _MACRO_VERSION_RE)}


class TrainingEligibilityError(ValueError):
    """Zarf eğitim verisine alınamaz (mock, v1 ya da bozuk/eksik data_version)."""


class MockDataError(TrainingEligibilityError):
    """Mock (uydurma) veri, gerçek veri gereken bir yere girmeye çalıştı."""


def is_mock_envelope(env: dict[str, Any]) -> bool:
    return env.get("data_version") == settings.MOCK_DATA_VERSION


def assert_not_mock(env: dict[str, Any]) -> None:
    """Mock zarfı reddeder. Eğitim verisi için bunun yerine `assert_training_eligible` kullanılır (daha sıkı)."""
    if is_mock_envelope(env):
        raise MockDataError(
            f"{env.get('tool')}: mock zarf eğitim/değerlendirme verisine alınamaz "
            f"(data_version={settings.MOCK_DATA_VERSION})"
        )


def aux_dataset_versions(env: dict[str, Any]) -> list[str]:
    """Bilanço/makro araç zarfının veri seti sürümleri (HISTORICAL_ONLY uyarılarından regex ile). Başka araçlar için boş liste."""
    kind = _AUX_TOOLS.get(str(env.get("tool")))
    if kind is None:
        return []
    found: list[str] = []
    for w in env.get("warnings") or []:
        if str(w).startswith("HISTORICAL_ONLY"):
            found += kind[1].findall(str(w))
    return sorted(set(found))


def _aux_eligible(env: dict[str, Any]) -> bool:
    """Bilanço/makro zarfı: status OK ise tam BİR sürüm bulunmalı ve kabul listesinde olmalı (hata zarfı sürüm taşımaz; zaten ayrıca elenir)."""
    kind = _AUX_TOOLS.get(str(env.get("tool")))
    if kind is None or env.get("status") != "OK":
        return True
    accepted = settings.ACCEPTED_FUNDAMENTALS_VERSIONS if kind[0] == "fundamentals" else settings.ACCEPTED_MACRO_VERSIONS
    versions = aux_dataset_versions(env)
    return len(versions) == 1 and versions[0] in accepted


def is_training_eligible(env: dict[str, Any]) -> bool:
    """CLAUDE.md kural 12: yalnızca snap_<tarih>_v<N>, N >= MIN_TRAINING_SNAPSHOT_VERSION (v2 ve sonrası).

    Mock (v0), v1 ve biçimi bozuk/eksik data_version False döner. Sürüm numarası SAYISAL karşılaştırılır (v10 > v2).
    """
    match = _DATA_VERSION_RE.match(str(env.get("data_version") or ""))
    return (bool(match) and not is_mock_envelope(env) and int(match.group(1)) >= settings.MIN_TRAINING_SNAPSHOT_VERSION
            and _aux_eligible(env))


def assert_training_eligible(env: dict[str, Any]) -> None:
    """Eğitim verisi üreten kod her zarf için bunu çağırır; uygun değilse hata fırlatır."""
    assert_not_mock(env)
    if not is_training_eligible(env):
        raise TrainingEligibilityError(
            f"{env.get('tool')}: eğitim verisi yalnızca snap_*_v{settings.MIN_TRAINING_SNAPSHOT_VERSION} ve sonraki "
            f"üretilmiş sürümlerden olabilir (data_version={env.get('data_version')!r}); bilanço/makro zarflarında ayrıca veri seti sürümü "
            f"kabul listesinde olmalı (bulunan: {aux_dataset_versions(env)})"
        )


def run_mock_tool(tool: ToolName | str, params: dict[str, Any]) -> dict[str, Any]:
    """Şemaya uygun sahte zarf döndürür. Geçersiz params -> pydantic ValidationError."""
    tool = ToolName(tool)
    parsed = validate_params(tool, params)
    norm_params = parsed.model_dump(mode="json")
    as_of = norm_params["as_of"]

    env = example_envelope(tool)  # derin kopya; çağıranın etkileyeceği paylaşılan durum yok
    env["params"] = norm_params
    env["as_of"] = as_of
    env["data_version"] = settings.MOCK_DATA_VERSION
    env["input_hash"] = compute_input_hash(tool.value, norm_params, settings.MOCK_DATA_VERSION)

    # Fixture tarihleri 2026-09-10'a kadar: daha eski bir as_of için sızıntı üretmek yerine hata döndür.
    if parsed.as_of < settings.MOCK_FIXTURE_LAST_DATE:  # type: ignore[attr-defined]
        env.update({
            "results": None, "n_events": None, "n_excluded_incomplete_horizon": 0, "warnings": [],
            "status": ToolStatus.ERROR.value,
            "error": {
                "code": settings.MOCK_AS_OF_ERROR_CODE,
                "message": (f"Mock fixture verisi {settings.MOCK_FIXTURE_LAST_DATE.isoformat()} tarihine kadar; "
                            f"as_of={as_of} bundan önce"),
            },
        })
    validate_envelope(env)  # mock bile sözleşmeyi bozamaz
    return env
