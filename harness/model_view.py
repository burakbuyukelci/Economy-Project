"""MODELE giden zarf görünümü (bağlam bütçesi: docs/harness_design.md 13.2).

Oturum deposu, kanıt paketi, etiket politikası ve sayı doğrulayıcı TAM zarfla çalışır; yalnızca modele giden `tool` mesajı bu görünümdür.
Kurallar:
  * boş (`null`) alanlar atılır (alan yoksa değer yoktur; sistem istemi bunu söyler). Kayıpsızdır, kırpma işareti gerektirmez.
  * modelin kendi çağrısının yankısı/kimlik alanları atılır: `params` (gizli varsayılanlarla birlikte yüzlerce karakter), `input_hash`, `schema_version`, `as_of`, `tool`
    (mesajın `name` alanı zaten araç adı; as_of sorudan bilinir). `data_version`, `status`, `warnings`, `n_events`, `n_excluded_incomplete_horizon`, `results` kalır.
  * rank_sector_relative_strength (şema 1.2.0 per_ticker, ~yarı boyut): `per_ticker` içinde yalnızca ÖZNE satırı tam kalır; diğer hisseler özet sayılara iner
    (ticker, is_laggard, lag_score_pp, ham/bağımsız/dışlanan olay); `ranking` satırları sıkıştırılır (rank, ticker, return_pct, lag_score_pp, is_laggard).
    Havuzlu `historical_catch_up` ve politikanın okuduğu alanlar KIRPILMAZ. Kırpılan bölümler `view_trimmed` listesinde işaretlenir.
Özne: soruda tek hisse varsa o, aksi halde sıralamadaki en çok geride kalan (label_policy ile aynı kural).
"""
from __future__ import annotations

from typing import Any

_RANK_SUMMARY_KEYS = ("ticker", "is_laggard", "lag_score_pp", "n_raw_laggard_observations", "n_independent_events", "n_excluded_incomplete_horizon")
_RANKING_KEYS = ("rank", "ticker", "return_pct", "lag_score_pp", "is_laggard")


def _strip_none(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _strip_none(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_strip_none(v) for v in x]
    return x


def _rank_subject(res: dict[str, Any], subject: str | None) -> str | None:
    ranking = res.get("ranking") or []
    if subject is not None and any(r.get("ticker") == subject for r in ranking):
        return subject
    if ranking:
        return min(ranking, key=lambda r: (r["lag_score_pp"], r["ticker"]))["ticker"]
    return subject


def _trim_rank(results: dict[str, Any], subject: str | None) -> list[str]:
    trimmed: list[str] = []
    who = _rank_subject(results, subject)
    rows = results.get("per_ticker") or []
    if rows and len(rows) > 1:
        results["per_ticker"] = [r if r.get("ticker") == who else {k: r[k] for k in _RANK_SUMMARY_KEYS if k in r} for r in rows]
        trimmed.append("per_ticker")
    if results.get("ranking"):
        results["ranking"] = [{k: r[k] for k in _RANKING_KEYS if k in r} for r in results["ranking"]]
        trimmed.append("ranking")
    return trimmed


_ECHO_KEYS = ("params", "input_hash", "schema_version", "as_of", "tool")


def model_view(envelope: dict[str, Any], *, subject: str | None) -> dict[str, Any]:
    """Zarfın modele gösterilen kopyası (girdi değişmez)."""
    view = {k: v for k, v in _strip_none(envelope).items() if k not in _ECHO_KEYS}
    results = view.get("results")
    if envelope.get("status") == "OK" and isinstance(results, dict) and str(envelope.get("tool")) == "rank_sector_relative_strength":
        trimmed = _trim_rank(results, subject)
        if trimmed:
            view["view_trimmed"] = trimmed
    return view
