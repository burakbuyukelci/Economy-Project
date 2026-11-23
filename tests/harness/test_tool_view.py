"""Modele görünen araç tanımları (harness/tool_view.py): kısa description, sadeleştirilmiş input_schema, gelişmiş parametreler gizli.

Doğrulama şeması (schemas/) DEĞİŞMEZ: gizli parametreler varsayılanlarıyla çalışır, model yine de gönderirse tam şema doğrular.
Bağlam hedefi ≤ 8192 token (Ollama kurulana kadar karakter/3 tahmini; sonra prompt_eval_count).
"""
from __future__ import annotations

import json

import pytest

from harness.profiles import get_profile, visible_tools
from harness.tool_view import (HIDDEN_PARAMS, PARAM_NOTES, TOOL_DESCRIPTIONS, TOOL_SPEC_CHAR_BUDGET, compact_schema, estimate_tokens,
                               model_tool_specs)
from schemas.enums import ToolName as T
from schemas.examples import example_params
from schemas.registry import TOOL_REGISTRY, validate_params

D_TOOLS = visible_tools(get_profile("D"))
C_TOOLS = visible_tools(get_profile("C"))


def specs(tools=D_TOOLS):
    return {s["name"]: s for s in model_tool_specs(tools)}


def full_props(tool):
    return TOOL_REGISTRY[tool].params_model.model_json_schema()


def walk_paths(schema, defs=None, prefix=""):
    """Tam şemadaki tüm (iç içe dahil) nesne özelliklerinin noktalı yolları."""
    defs = defs if defs is not None else schema.get("$defs", {})
    out = set()
    node = schema
    if "$ref" in node:
        node = defs[node["$ref"].split("/")[-1]]
    for name, sub in (node.get("properties") or {}).items():
        path = f"{prefix}{name}"
        out.add(path)
        out |= walk_paths(sub, defs, path + ".")
    return out


# =============================== boyut ===============================
def test_tool_definitions_fit_the_character_budget():
    total = sum(len(json.dumps(s, ensure_ascii=False)) for s in specs().values())
    assert total <= TOOL_SPEC_CHAR_BUDGET, total
    assert estimate_tokens(chars=total) <= 3150                              # 13 araç: ~3,1 bin token (şema 1.5.0 relate_to ~+0,3 bin; önceden ~7,9 bin)
    assert len(specs(C_TOOLS)) == 14 and sum(len(json.dumps(s, ensure_ascii=False)) for s in specs(C_TOOLS).values()) <= TOOL_SPEC_CHAR_BUDGET * 1.1


def test_every_description_is_short_and_has_no_repeated_boilerplate():
    for name, s in specs(C_TOOLS).items():
        assert 10 < len(s["description"]) <= 100, (name, len(s["description"]))
        assert "must equal the analysis date" not in s["description"] and "January 1" not in s["description"]     # kural system prompt'ta TEK kez


def test_the_tool_description_table_covers_exactly_the_registered_tools():
    assert set(TOOL_DESCRIPTIONS) == set(T)


# =============================== gizleme ===============================
def test_hidden_paths_exist_in_the_full_schema_and_are_never_required():
    for tool, hidden in HIDDEN_PARAMS.items():
        schema = full_props(tool)
        paths = walk_paths(schema)
        for h in hidden:
            assert h in paths, f"{tool.value}: bayat gizli yol {h}"
        top_required = set(schema.get("required", []))
        assert not (set(hidden) & top_required), (tool.value, set(hidden) & top_required)
        defs = schema.get("$defs", {})
        for h in hidden:                                 # iç içe zorunlu alan da olmasın (gizlenirse çağrı imkânsız olurdu)
            if "." in h:
                parent, leaf = h.rsplit(".", 1)
                node = schema["properties"][parent.split(".")[0]]
                node = defs[node["$ref"].split("/")[-1]] if "$ref" in node else node
                assert leaf not in node.get("required", []), h


def test_visible_properties_are_real_and_hidden_ones_are_absent():
    for tool in C_TOOLS:
        view = compact_schema(tool)
        real = walk_paths(full_props(tool))

        def visible_paths(node, prefix=""):
            out = set()
            for name, sub in (node.get("properties") or {}).items():
                out.add(prefix + name)
                out |= visible_paths(sub, prefix + name + ".")
            return out
        vis = visible_paths(view)
        assert vis <= real, (tool.value, vis - real)
        assert not (vis & set(HIDDEN_PARAMS.get(tool, ()))), (tool.value, vis & set(HIDDEN_PARAMS.get(tool, ())))
        assert set(view.get("required", [])) <= set(view["properties"])


def test_essential_parameters_stay_visible():
    s = specs()
    assert {"as_of", "ticker", "indicators", "end", "last_n_rows", "value_columns"} <= set(s["calculate_indicators"]["parameters"]["properties"])
    assert {"sector", "horizon", "split_date"} <= set(s["rank_sector_relative_strength"]["parameters"]["properties"])
    assert {"event_family", "condition_sets", "split_date", "n_tests_declared"} <= set(s["detect_reversal_events"]["parameters"]["properties"])
    assert {"pattern", "in_sample_start", "in_sample_end", "out_of_sample_start", "out_of_sample_end", "n_tests_declared"} \
        <= set(s["test_weekday_pattern"]["parameters"]["properties"])
    strat = s["run_backtest"]["parameters"]["properties"]["strategy"]["properties"]
    assert {"variant", "signal_type", "holding_days", "train_end", "signal_params"} <= set(strat) and "transaction_cost_bps" not in strat
    assert "event_family" in strat["signal_params"]["description"]            # REVERSAL ailesi (RSI/BB) backtest'e buradan iletilir
    for hidden in ("config", "price_adjustment", "include_columns_meta"):
        assert hidden not in s["calculate_indicators"]["parameters"]["properties"]


def test_oos_start_parameters_carry_the_short_rule_note():
    s = specs()
    for tool, key in (("rank_sector_relative_strength", "split_date"), ("detect_reversal_events", "split_date"),
                      ("test_weekday_pattern", "out_of_sample_start")):
        note = s[tool]["parameters"]["properties"][key]["description"]
        assert "Jan 1" in note and "question" in note, tool
    assert "day before" in s["run_backtest"]["parameters"]["properties"]["strategy"]["properties"]["train_end"]["description"]
    assert "analysis date" in s["get_stock_history"]["parameters"]["properties"]["as_of"]["description"]


def test_notes_only_refer_to_existing_parameters():
    names = set().union(*({p.split(".")[-1] for p in walk_paths(full_props(t))} for t in T))
    assert set(PARAM_NOTES) <= names


# =============================== uyumluluk: görünen parametrelerle yapılan çağrı geçerli ===============================
@pytest.mark.parametrize("tool", [t for t in C_TOOLS], ids=lambda t: t.value)
def test_a_call_with_only_visible_parameters_validates_against_the_full_schema(tool):
    """Örnek çağrının yalnızca görünen alanlarını bırak: gizli alanlar varsayılanla dolar ve tam şema geçer."""
    view = compact_schema(tool)

    def keep(value, node):
        if isinstance(value, dict) and node.get("properties"):
            return {k: keep(v, node["properties"][k]) for k, v in value.items() if k in node["properties"]}
        if isinstance(value, list) and node.get("items", {}).get("properties"):
            return [keep(v, node["items"]) for v in value]
        return value

    params = keep(example_params(tool), view)
    parsed = validate_params(tool, params)
    assert parsed.as_of.isoformat() == "2026-09-10"


def test_hidden_defaults_match_the_defaults_the_examples_use():
    """Gizlenen alanın varsayılanı örnekteki (eğitim/test) değerle aynı: gizleme sonucu değiştirmez."""
    for tool, hidden in HIDDEN_PARAMS.items():
        example = example_params(tool)
        defaults = validate_params(tool, {k: v for k, v in example.items() if k not in {h.split(".")[0] for h in hidden if "." not in h}}).model_dump(mode="json")
        for h in hidden:
            if "." not in h and h in example:
                assert defaults[h] == example[h], (tool.value, h, defaults[h], example[h])


def test_views_are_deterministic_and_json_serialisable():
    a = json.dumps(model_tool_specs(C_TOOLS), ensure_ascii=False, sort_keys=True)
    assert a == json.dumps(model_tool_specs(C_TOOLS), ensure_ascii=False, sort_keys=True)


def test_estimate_tokens_is_chars_over_three_rounded_up():
    assert estimate_tokens(chars=3000) == 1000 and estimate_tokens(chars=3001) == 1001
    assert estimate_tokens(messages=[{"role": "user", "content": "a" * 30}], tools=None) >= 10
