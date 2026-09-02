import json
from pathlib import Path

import pytest

from litellm_codex_models.errors import AppError
from litellm_codex_models.mapping import generate_model
from litellm_codex_models.schema import ModelInfoSchema


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text())
INDEX = {m["slug"]: m for m in CATALOG["models"]}
FALLBACK_PROMPT = "You are a generic Codex coding agent."
SCHEMA = ModelInfoSchema(
    fields=frozenset(),
    required_fields=frozenset(),
)


def row(name, model, **info):
    return {
        "model_name": name,
        "litellm_params": {"model": model, "base_model": model},
        "model_info": {"mode": "chat", **info},
    }


def test_exact_template_preserves_codex_context_and_unknown_fields():
    generated = generate_model(
        row(
            "gpt-5.6-sol",
            "azure/gpt-5.6-sol",
            max_input_tokens=922000,
            supports_vision=True,
            supports_reasoning=True,
            supported_openai_params=["parallel_tool_calls", "reasoning_effort", "verbosity"],
        ),
        INDEX,
    )
    assert generated.kind == "exact"
    assert generated.entry["context_window"] == 272000
    assert generated.entry["max_context_window"] == 872000
    assert generated.entry["future_field_unknown_to_converter"] == {"keep": True}


def test_alias_resolves_from_base_model_and_rewrites_slug():
    generated = generate_model(
        row(
            "claude_code.gpt-5.6-sol",
            "azure/gpt-5.6-sol",
            supports_vision=True,
            supported_openai_params=["parallel_tool_calls", "verbosity"],
        ),
        INDEX,
    )
    assert generated.template_slug == "gpt-5.6-sol"
    assert generated.entry["slug"] == "claude_code.gpt-5.6-sol"
    assert generated.entry["display_name"] == "claude_code.gpt-5.6-sol"


def test_explicit_false_downgrades_exact_capability_but_null_does_not():
    disabled = generate_model(
        row(
            "gpt-5.6-sol",
            "azure/gpt-5.6-sol",
            supports_vision=False,
            supported_openai_params=["reasoning_effort"],
        ),
        INDEX,
    )
    assert disabled.entry["input_modalities"] == ["text"]
    assert disabled.entry["support_verbosity"] is False
    assert disabled.entry["supports_parallel_tool_calls"] is False

    unknown = generate_model(
        row(
            "gpt-5.6-sol",
            "azure/gpt-5.6-sol",
            supports_vision=None,
            supported_openai_params=None,
        ),
        INDEX,
    )
    assert unknown.entry["input_modalities"] == ["text", "image"]
    assert unknown.entry["support_verbosity"] is True
    assert unknown.entry["supports_parallel_tool_calls"] is True


def test_foreign_model_uses_litellm_context_and_conservative_harness():
    generated = generate_model(
        {
            "model_name": "claude-sonnet-5",
            "litellm_params": {"model": "azure_ai/claude-sonnet-5"},
            "model_info": {
                "mode": "chat",
                "max_input_tokens": 1_000_000,
                "supports_vision": True,
                "supports_reasoning": True,
                "supports_xhigh_reasoning_effort": True,
                "supports_max_reasoning_effort": True,
                "supports_function_calling": True,
                "supports_web_search": True,
                "supported_openai_params": ["parallel_tool_calls", "reasoning_effort"],
            },
        },
        INDEX,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
        codex_catalog=CATALOG,
    )
    assert generated.kind == "foreign"
    assert generated.entry["context_window"] == 1_000_000
    assert generated.entry["max_context_window"] == 1_000_000
    assert generated.entry["input_modalities"] == ["text", "image"]
    assert generated.entry["supports_search_tool"] is False
    assert generated.entry["tool_mode"] is None
    assert generated.entry["multi_agent_version"] is None
    efforts = {x["effort"] for x in generated.entry["supported_reasoning_levels"]}
    assert efforts == {"xhigh", "max"}
    assert generated.entry["default_reasoning_level"] is None
    assert generated.entry["supports_reasoning_summary_parameter"] is False
    assert generated.entry["model_messages"]["instructions_template"] == FALLBACK_PROMPT
    assert "future_field_unknown_to_converter" not in generated.entry
    assert "available_in_plans" not in generated.entry


def test_foreign_reasoning_does_not_invent_null_efforts():
    generated = generate_model(
        {
            "model_name": "foreign-reasoner",
            "litellm_params": {"model": "vendor/foreign-reasoner"},
            "model_info": {
                "mode": "chat",
                "supports_reasoning": True,
                "supports_function_calling": True,
                "supported_openai_params": ["reasoning_effort", "parallel_tool_calls"],
            },
        },
        INDEX,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
        codex_catalog=CATALOG,
    )
    assert generated.entry["supported_reasoning_levels"] == []
    assert generated.entry["default_reasoning_level"] is None
    assert generated.entry["supports_reasoning_summary_parameter"] is False


def test_foreign_reasoning_uses_explicit_reasoning_effort_levels_in_codex_order():
    generated = generate_model(
        {
            "model_name": "foreign-explicit-levels",
            "litellm_params": {"model": "vendor/foreign-explicit-levels"},
            "model_info": {
                "mode": "chat",
                "supports_reasoning": True,
                "supports_low_reasoning_effort": False,
                "supported_openai_params": ["reasoning_effort"],
                "reasoning_effort_levels": ["high", "bogus", "medium", "low", "high", 123],
            },
        },
        INDEX,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
        codex_catalog=CATALOG,
    )
    assert [item["effort"] for item in generated.entry["supported_reasoning_levels"]] == [
        "medium",
        "high",
    ]
    assert generated.entry["default_reasoning_level"] is None


def test_foreign_parallel_tools_require_explicit_function_calling_true():
    generated = generate_model(
        {
            "model_name": "foreign-tools",
            "litellm_params": {"model": "vendor/foreign-tools"},
            "model_info": {
                "mode": "chat",
                "supports_function_calling": None,
                "supported_openai_params": ["parallel_tool_calls"],
            },
        },
        INDEX,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
        codex_catalog=CATALOG,
    )
    assert generated.entry["supports_parallel_tool_calls"] is False


def test_foreign_schema_guard_copies_only_catalog_invariant_required_fields():
    second = {**CATALOG["models"][0], "slug": "second-template"}
    catalog = {
        "models": [
            {**CATALOG["models"][0], "new_required": "same"},
            {**second, "new_required": "same"},
        ]
    }
    generated = generate_model(
        {
            "model_name": "foreign-new-schema",
            "litellm_params": {"model": "vendor/foreign-new-schema"},
            "model_info": {"mode": "chat"},
        },
        {m["slug"]: m for m in catalog["models"]},
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=ModelInfoSchema(
            fields=frozenset({"new_required"}),
            required_fields=frozenset({"new_required"}),
        ),
        codex_catalog=catalog,
    )
    assert generated.entry["new_required"] == "same"
    assert generated.provenance["new_required"] == "codex:catalog-invariant-required-field"


def test_foreign_schema_guard_fails_closed_for_model_specific_required_field():
    second = {**CATALOG["models"][0], "slug": "second-template"}
    catalog = {
        "models": [
            {**CATALOG["models"][0], "new_required": "a"},
            {**second, "new_required": "b"},
        ]
    }

    with pytest.raises(AppError, match="cannot safely synthesize"):
        generate_model(
            {
                "model_name": "foreign-new-schema",
                "litellm_params": {"model": "vendor/foreign-new-schema"},
                "model_info": {"mode": "chat"},
            },
            {m["slug"]: m for m in catalog["models"]},
            fallback_prompt=FALLBACK_PROMPT,
            model_info_schema=ModelInfoSchema(
                fields=frozenset({"new_required"}),
                required_fields=frozenset({"new_required"}),
            ),
            codex_catalog=catalog,
        )
