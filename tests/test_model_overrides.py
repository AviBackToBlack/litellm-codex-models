from __future__ import annotations

import json
from pathlib import Path

from litellm_codex_models.config import ModelOverride
from litellm_codex_models.group_mapping import generate_prepared_catalog, prepare_model_groups
from litellm_codex_models.schema import ModelInfoSchema


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text(encoding="utf-8"))
INDEX = {model["slug"]: model for model in CATALOG["models"]}
FALLBACK_PROMPT = "You are a generic Codex coding agent."
SCHEMA = ModelInfoSchema(fields=frozenset(), required_fields=frozenset())


def row(
    name: str,
    model: str,
    *,
    max_input_tokens: int | None = 200_000,
    **info,
):
    model_info = {"mode": "chat", **info}
    if max_input_tokens is not None:
        model_info["max_input_tokens"] = max_input_tokens
    return {
        "model_name": name,
        "litellm_params": {"model": model, "base_model": model},
        "model_info": model_info,
    }


def test_exact_override_can_replace_aggregate_vision_denial_with_audited_provenance():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_vision=False,
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(supports_vision=True),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["input_modalities"] == ["text", "image"]
    evidence = model.group_evidence
    assert evidence["capabilities"]["supports_vision"]["state"] == "guaranteed"
    audit = evidence["configured_overrides"]["supports_vision"]
    assert audit["configured_value"] is True
    assert audit["original"] == {"state": "denied", "value": False}
    assert audit["effective"] == {"state": "guaranteed", "value": True}
    assert model.provenance["input_modalities"].startswith("codex:exact-template:gpt-5.6-sol")
    assert "config:model_overrides.gpt-5.6-sol.supports_vision" in model.provenance[
        "input_modalities"
    ]
    assert "LiteLLM confirms vision support" not in model.notes
    assert "Configured override confirms vision support" in model.notes


def test_exact_reasoning_effort_override_replaces_old_denials_and_restricts_template():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_reasoning=True,
        supports_low_reasoning_effort=False,
        supported_openai_params=["reasoning_effort"],
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(
            reasoning_effort_levels=("low", "medium"),
        ),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert [item["effort"] for item in model.entry["supported_reasoning_levels"]] == [
        "low",
        "medium",
    ]
    assert model.entry["default_reasoning_level"] == "low"
    audit = model.group_evidence["configured_overrides"]["reasoning_effort_levels"]
    assert audit["configured_value"] == ["low", "medium"]
    assert "config:model_overrides.gpt-5.6-sol.reasoning_effort_levels" in model.provenance[
        "supported_reasoning_levels"
    ]


def test_effort_override_cannot_bypass_effective_reasoning_denial():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_reasoning=False,
        supported_openai_params=["reasoning_effort"],
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(reasoning_effort_levels=("low",)),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    assert prepared[0].evidence.reasoning_efforts.state == "denied"
    assert prepared[0].evidence.reasoning_efforts.values == ()

    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["supported_reasoning_levels"] == []
    assert model.entry["default_reasoning_level"] is None
    assert model.entry["supports_reasoning_summary_parameter"] is False
    assert model.group_evidence["configured_overrides"]["reasoning_effort_levels"][
        "effective"
    ] == {"state": "denied", "value": []}


def test_function_override_false_applies_dependency_closure_to_parallel_calls():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_function_calling=True,
        supports_parallel_function_calling=True,
        supported_openai_params=["parallel_tool_calls"],
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(supports_function_calling=False),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["supports_parallel_tool_calls"] is False
    assert model.group_evidence["capabilities"]["supports_function_calling"]["state"] == "denied"
    assert model.group_evidence["capabilities"]["supports_parallel_function_calling"]["state"] == "denied"
    assert "config:model_overrides.gpt-5.6-sol.supports_function_calling" in model.provenance[
        "supports_parallel_tool_calls"
    ]


def test_exact_supported_parameter_override_keeps_codex_owned_positive_provenance():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supported_openai_params=[],
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(
            supported_openai_params=("parallel_tool_calls", "verbosity"),
        ),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["support_verbosity"] is True
    assert model.entry["supports_parallel_tool_calls"] is True
    for field in ("support_verbosity", "supports_parallel_tool_calls"):
        assert model.provenance[field].startswith("codex:exact-template:gpt-5.6-sol")
        assert "config:model_overrides.gpt-5.6-sol.supported_openai_params" in model.provenance[
            field
        ]


def test_reasoning_override_false_clears_exact_reasoning_transport():
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_reasoning=True,
        reasoning_effort_levels=["low", "high"],
        supported_openai_params=["reasoning_effort"],
    )
    overrides = {
        "gpt-5.6-sol": ModelOverride(supports_reasoning=False),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["supported_reasoning_levels"] == []
    assert model.entry["default_reasoning_level"] is None
    assert model.entry["supports_reasoning_summary_parameter"] is False
    assert "config:model_overrides.gpt-5.6-sol.supports_reasoning" in model.provenance[
        "supports_reasoning_summary_parameter"
    ]


def test_foreign_context_override_removes_multi_deployment_synthesis_blocker():
    groups = [[
        row("foreign-group", "vendor/model-a", max_input_tokens=200_000),
        row("foreign-group", "vendor/model-b", max_input_tokens=None),
    ]]
    overrides = {
        "foreign-group": ModelOverride(max_input_tokens=123_456),
    }

    prepared = prepare_model_groups(groups, INDEX, overrides)
    assert prepared[0].evidence.foreign_synthesis_blockers == ()

    generated, explanations = generate_prepared_catalog(
        prepared,
        CATALOG,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
    )
    model = explanations["foreign-group"]

    assert generated["models"][0]["context_window"] == 123_456
    assert model.provenance["context_window"] == (
        "config:model_overrides.foreign-group.max_input_tokens"
    )
    audit = model.group_evidence["configured_overrides"]["max_input_tokens"]
    assert audit["original"] == {"state": "unknown", "value": None}
    assert audit["effective"] == {"state": "known", "value": 123_456}


def test_foreign_web_search_override_is_evidence_only_for_search_tool():
    source = row(
        "foreign-model",
        "vendor/model",
        supports_web_search=False,
    )
    overrides = {
        "foreign-model": ModelOverride(supports_web_search=True),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(
        prepared,
        CATALOG,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
    )
    model = explanations["foreign-model"]

    assert model.entry["supports_search_tool"] is False
    assert model.group_evidence["capabilities"]["supports_web_search"]["state"] == "guaranteed"
    assert model.provenance["supports_search_tool"] == (
        "conservative: foreign tool-search/deferred discovery disabled"
    )


def test_supported_parameter_override_can_enable_foreign_verbosity_without_donor_leakage():
    source = row(
        "foreign-model",
        "vendor/model",
        supported_openai_params=[],
    )
    overrides = {
        "foreign-model": ModelOverride(supported_openai_params=("verbosity",)),
    }

    prepared = prepare_model_groups([[source]], INDEX, overrides)
    _generated, explanations = generate_prepared_catalog(
        prepared,
        CATALOG,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
    )
    model = explanations["foreign-model"]

    assert model.entry["support_verbosity"] is True
    assert model.provenance["support_verbosity"] == (
        "config:model_overrides.foreign-model.supported_openai_params"
    )
