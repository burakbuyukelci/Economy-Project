"""MODELE giden zarf görünümü (bağlam bütçesi: docs/harness_design.md 13.2).

Oturum deposu, kanıt paketi, etiket politikası ve sayı doğrulayıcı TAM zarfla çalışır; yalnızca modele giden `tool` mesajı bu görünümdür.
Kurallar:
  * boş (`null`) alanlar atılır (alan yoksa değer yoktur; sistem istemi bunu söyler). Kayıpsızdır, kırpma işareti gerektirmez.
  * modelin kendi çağrısının yankısı/kimlik alanları atılır: `params` (gizli varsayılanlarla birlikte yüzlerce karakter), `input_hash`, `schema_version`, `as_of`, `tool`
    (mesajın `name` alanı zaten araç adı; as_of sorudan bilinir). `data_version`, `status`, `warnings`, `n_events`, `n_excluded_incomplete_horizon`, `results` kalır.
  * rank_sector_relative_strength (şema 1.2.0 per_ticker, ~yarı boyut): `per_ticker` içinde yalnızca ÖZNE satırı tam kalır; diğer hisseler özet sayılara iner
    (ticker, is_laggard, lag_score_pp, ham/bağımsız/dışlanan olay); `ranking` satırları sıkıştırılır (rank, ticker, return_pct, lag_score_pp, is_laggard).
    Havuzlu `historical_catch_up` ve politikanın okuduğu alanlar KIRPILMAZ. Kırpılan bölümler `view_trimmed` listesinde işaretlenir.
  * KANITA GİRMEYEN uzun listeler son kayıtlara kısaltılır (`evidence_headlines.json` `excluded` bölümleri: model bunlardan sayı alıntılayamaz zaten): reversal
    `groups[].events` ve backtest `trade_log` yalnızca SON `LIST_KEEP` kayıt; `view_trimmed`'e eklenir. Politika tam zarfı okur (son olay tarihi vb.).
  * KANITIN ALINTILAMADIĞI istatistik alanları atılır: ufuk bloklarında (`full`/`in_sample`/`out_of_sample`) yalnızca sayaçlar, isabet ve ortalama getiriler kalır
    (medyanlar, yanlış pozitif oranı, ters dönüş gücü, taban dağılımı ayrıntısı, `mean_diff/median_diff` atılır); `regime_breakdown` (bağlam bölümü) atılır. `view_trimmed` işaretler.
  * run_backtest: kanıtın alıntıladığı alanlar kalır (strateji özeti, net metrikler: getiri/Sharpe/düşüş/isabet/işlem, benchmark farkları, bölüm özetleri, bayraklar);
    brüt metrikler, maliyet/Sharpe tanımı ve benchmark ayrıntı metrikleri atılır. Tekrarlayan sabit uyarılar (`COST_ASSUMPTIONS`; sayısız `HISTORICAL_ONLY`) atılır: kural sistem isteminde.
  * get_stock_history / get_index_history: `rows` yalnızca İLK 2 ve SON 3 satır (kanıt dönem özetini zaten taşır).
Özne: soruda tek hisse varsa o, aksi halde sıralamadaki en çok geride kalan (label_policy ile aynı kural).
"""
from __future__ import annotations

import json
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
LIST_KEEP = 1                  # reversal olayları ve backtest işlem günlüğü: yalnızca SON kayıt (kanıtta zaten `last_event_date` / `last_exit_date` var)
ROWS_HEAD, ROWS_TAIL = 2, 3
_METRIC_KEEP = ("cumulative_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate_pct", "n_trades")
_STRATEGY_KEEP = ("variant", "signal_type", "holding_days", "train_end", "signal_params")
_BOILERPLATE_WARNINGS = ("COST_ASSUMPTIONS",)


def _slim_backtest(results: dict[str, Any]) -> list[str]:
    before = json.dumps(results, sort_keys=True)
    results.pop("strategy_gross", None)
    results.pop("cost_model", None)
    results.pop("sharpe_definition", None)
    if isinstance(results.get("strategy"), dict):
        results["strategy"] = {k: v for k, v in results["strategy"].items() if k in _STRATEGY_KEEP}
    if isinstance(results.get("strategy_net"), dict):
        results["strategy_net"] = {k: v for k, v in results["strategy_net"].items() if k in _METRIC_KEEP}
    if isinstance(results.get("benchmarks"), list):
        results["benchmarks"] = [{k: b[k] for k in ("name", "cumulative_return_diff_pct", "sharpe_diff") if k in b} for b in results["benchmarks"]]
    if isinstance(results.get("splits"), list):
        results["splits"] = [{**{k: v for k, v in sp.items() if k != "net_metrics"},
                              "net_metrics": {k: v for k, v in (sp.get("net_metrics") or {}).items() if k in _METRIC_KEEP}} for sp in results["splits"]]
    return ["backtest_slim"] if json.dumps(results, sort_keys=True) != before else []


def _trim_rows(results: dict[str, Any]) -> list[str]:
    rows = results.get("rows")
    if isinstance(rows, list) and len(rows) > ROWS_HEAD + ROWS_TAIL:
        results["rows"] = rows[:ROWS_HEAD] + rows[-ROWS_TAIL:]
        return ["rows"]
    return []


def _is_boilerplate(w: str, tool: str) -> bool:
    """Her zarfta bulunan sabit notlar (sistem isteminde anlatılır): COST_ASSUMPTIONS; sayı içermeyen HISTORICAL_ONLY. rank'te HISTORICAL_ONLY'nin ham sayıları tipli alanlarda (n_raw..., per_ticker)."""
    if w.startswith(_BOILERPLATE_WARNINGS):
        return True
    if w.startswith("HISTORICAL_ONLY"):
        return tool == "rank_sector_relative_strength" or not any(ch.isdigit() for ch in w)
    return False
_STAT_KEEP = ("n_events_complete", "n_excluded_incomplete_horizon", "n_success", "n_false_positive", "hit_rate_pct", "mean_return_pct",
              "cost_adjusted_mean_return_pct")
_SPLIT_KEEP = ("n_events_complete", "hit_rate_pct", "cost_adjusted_mean_return_pct")   # kanıt IS/OOS için yalnızca bunları alıntılar
_BLOCK_DROP = ("mean_diff_vs_baseline_pct", "median_diff_vs_baseline_pct")
_RANK_DROP = ("benchmark_definition", "cost_model", "strength_thresholds")   # çağrı/kural yankısı; sonuç ölçütü `outcome_benchmark_definition`te kalır


def _slim_stats(node: Any, hit: list[bool]) -> Any:
    """Ufuk istatistik sözlüklerini (n_events_complete + hit_rate_pct taşıyanlar) ve `baseline`'ı kanıtın alıntıladığı alanlara indirir."""
    if isinstance(node, dict):
        if "n_events_complete" in node and "hit_rate_pct" in node:
            kept = {k: node[k] for k in _STAT_KEEP if k in node}
            if len(kept) != len(node):
                hit.append(True)
            return kept
        out = {}
        for k, v in node.items():
            if k in _BLOCK_DROP and "horizon" in node:
                hit.append(True)
                continue
            if k in ("in_sample", "out_of_sample") and isinstance(v, dict) and "horizon" in node:
                out[k] = {x: v[x] for x in _SPLIT_KEEP if x in v}
                if len(out[k]) != len(v):
                    hit.append(True)
                continue
            if k == "baseline" and isinstance(v, dict) and "horizon" in node:
                out[k] = {"hit_rate_pct": v["hit_rate_pct"]} if "hit_rate_pct" in v else v
                if len(out[k]) != len(v):
                    hit.append(True)
                continue
            out[k] = _slim_stats(v, hit)
        return out
    if isinstance(node, list):
        return [_slim_stats(v, hit) for v in node]
    return node


def _slim_blocks(tool: str, results: dict[str, Any]) -> list[str]:
    hit: list[bool] = []
    trimmed: list[str] = []
    if tool == "detect_reversal_events":
        for g in results.get("groups") or []:
            if "regime_breakdown" in g:
                del g["regime_breakdown"]
                if "groups[].regime_breakdown" not in trimmed:
                    trimmed.append("groups[].regime_breakdown")
            if "per_horizon" in g:
                g["per_horizon"] = _slim_stats(g["per_horizon"], hit)
    elif tool == "rank_sector_relative_strength":
        for k in _RANK_DROP:
            if k in results:
                del results[k]
                hit.append(True)
        for key in ("historical_catch_up", "per_ticker"):
            if key in results:
                results[key] = _slim_stats(results[key], hit)
    if hit:
        trimmed.append("block_stats")
    return trimmed


def _trim_long_lists(tool: str, results: dict[str, Any]) -> list[str]:
    trimmed: list[str] = []
    if tool == "detect_reversal_events":
        for g in results.get("groups") or []:
            if isinstance(g.get("events"), list) and len(g["events"]) > LIST_KEEP:
                g["events"] = g["events"][-LIST_KEEP:]
                if "groups[].events" not in trimmed:
                    trimmed.append("groups[].events")
    elif tool == "run_backtest":
        trimmed += _slim_backtest(results)
        if isinstance(results.get("trade_log"), list) and len(results["trade_log"]) > LIST_KEEP:
            results["trade_log"] = results["trade_log"][-LIST_KEEP:]
            trimmed.append("trade_log")
    return trimmed


def model_view(envelope: dict[str, Any], *, subject: str | None) -> dict[str, Any]:
    """Zarfın modele gösterilen kopyası (girdi değişmez)."""
    view = {k: v for k, v in _strip_none(envelope).items() if k not in _ECHO_KEYS}
    if isinstance(view.get("warnings"), list):
        kept = [w for w in view["warnings"] if not _is_boilerplate(str(w), str(envelope.get("tool")))]
        if len(kept) != len(view["warnings"]):
            view["warnings"] = kept
    results = view.get("results")
    if envelope.get("status") == "OK" and isinstance(results, dict):
        tool = str(envelope.get("tool"))
        trimmed = _trim_rank(results, subject) if tool == "rank_sector_relative_strength" else []
        trimmed += _trim_long_lists(tool, results)
        trimmed += _slim_blocks(tool, results)
        if tool in ("get_stock_history", "get_index_history"):
            trimmed += _trim_rows(results)
        if trimmed:
            view["view_trimmed"] = trimmed
    return view
