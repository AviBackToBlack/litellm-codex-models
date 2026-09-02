import json
from pathlib import Path

from litellm_codex_models.mapping import generate_model


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text())
INDEX = {m["slug"]: m for m in CATALOG["models"]}


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
    )
    assert generated.kind == "foreign"
    assert generated.entry["context_window"] == 1_000_000
    assert generated.entry["max_context_window"] == 1_000_000
    assert generated.entry["input_modalities"] == ["text", "image"]
    assert generated.entry["supports_search_tool"] is False
    assert generated.entry["tool_mode"] is None
    assert generated.entry["multi_agent_version"] is None
    assert generated.entry["future_field_unknown_to_converter"] == {"keep": True}
    efforts = {x["effort"] for x in generated.entry["supported_reasoning_levels"]}
    assert {"low", "medium", "high", "xhigh", "max"}.issubset(efforts)
