from copy import deepcopy
import json
from pathlib import Path

import pytest

from litellm_codex_models.errors import AppError
from litellm_codex_models.group_mapping import (
    generate_prepared_catalog,
    generate_prepared_model,
    prepare_model_groups,
)
from litellm_codex_models.mapping import generate_model
from litellm_codex_models.schema import ModelInfoSchema


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text())
INDEX = {model["slug"]: model for model in CATALOG["models"]}
FALLBACK_PROMPT = "You are a generic Codex coding agent."
SCHEMA = ModelInfoSchema(fields=frozenset(), required_fields=frozenset())


def row(
    name: str,
    model: str,
    *,
    base_model: str | None = None,
    mode: str = "chat",
    max_input_tokens: int | None = 200_000,
    **info,
):
    model_info = {"mode": mode, **info}
    if max_input_tokens is not None:
        model_info["max_input_tokens"] = max_input_tokens
    return {
        "model_name": name,
        "litellm_params": {
            "model": model,
            "base_model": base_model if base_model is not None else model,
        },
        "model_info": model_info,
    }


def test_multi_deployment_exact_group_uses_aggregate_denials_without_donor_row():
    groups = [[
        row(
            "shared-gpt",
            "azure/gpt-5.6-sol",
            max_input_tokens=220_000,
            supports_vision=True,
            supports_parallel_function_calling=True,
            supported_openai_params=["parallel_tool_calls", "verbosity"],
        ),
        row(
            "shared-gpt",
            "openai/gpt-5.6-sol",
            max_input_tokens=180_000,
            supports_vision=False,
            supports_parallel_function_calling=False,
            supported_openai_params=["parallel_tool_calls"],
        ),
    ]]

    prepared = prepare_model_groups(groups, INDEX)
    generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["shared-gpt"]

    assert generated["models"][0]["slug"] == "shared-gpt"
    assert model.kind == "exact"
    assert model.template_slug == "gpt-5.6-sol"
    assert model.entry["input_modalities"] == ["text"]
    assert model.entry["support_verbosity"] is False
    assert model.entry["supports_parallel_tool_calls"] is False
    assert model.entry["supported_reasoning_levels"] == INDEX["gpt-5.6-sol"]["supported_reasoning_levels"]
    assert model.entry["context_window"] == INDEX["gpt-5.6-sol"]["context_window"]
    assert model.group_evidence["deployment_count"] == 2
    assert model.group_evidence["max_input_tokens"]["value"] == 180_000
    assert model.group_evidence["capabilities"]["supports_parallel_function_calling"]["state"] == "denied"
    assert any("supports_vision" in item for item in model.group_evidence["disagreements"])


def test_exact_group_reasoning_denial_clears_template_reasoning_levels():
    groups = [[
        row(
            "shared-gpt",
            "azure/gpt-5.6-sol",
            supports_reasoning=True,
            reasoning_effort_levels=["low", "high"],
            supported_openai_params=["reasoning_effort"],
        ),
        row(
            "shared-gpt",
            "openai/gpt-5.6-sol",
            supports_reasoning=False,
            supported_openai_params=["reasoning_effort"],
        ),
    ]]

    prepared = prepare_model_groups(groups, INDEX)
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["shared-gpt"]

    assert model.kind == "exact"
    assert model.entry["supported_reasoning_levels"] == []
    assert model.entry["default_reasoning_level"] is None
    assert model.group_evidence["capabilities"]["supports_reasoning"]["state"] == "denied"
    assert "supports_reasoning=false" in model.provenance["supported_reasoning_levels"]


def test_multi_deployment_foreign_group_uses_safe_intersections_and_min_context():
    groups = [[
        row(
            "foreign-group",
            "vendor/model-a",
            max_input_tokens=200_000,
            supports_vision=True,
            supports_reasoning=True,
            supports_function_calling=True,
            supports_parallel_function_calling=True,
            reasoning_effort_levels=["low", "high"],
            supported_openai_params=["reasoning_effort", "verbosity", "parallel_tool_calls"],
        ),
        row(
            "foreign-group",
            "vendor/model-b",
            max_input_tokens=150_000,
            supports_vision=True,
            supports_reasoning=True,
            supports_function_calling=True,
            supports_parallel_function_calling=False,
            reasoning_effort_levels=["high"],
            supported_openai_params=["reasoning_effort", "verbosity", "parallel_tool_calls"],
        ),
    ]]

    prepared = prepare_model_groups(groups, INDEX)
    generated, explanations = generate_prepared_catalog(
        prepared,
        CATALOG,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
    )
    model = explanations["foreign-group"]

    assert generated["models"][0]["context_window"] == 150_000
    assert model.kind == "foreign"
    assert model.canonical_model == "foreign-group"
    assert model.entry["input_modalities"] == ["text", "image"]
    assert model.entry["support_verbosity"] is True
    assert model.entry["supports_parallel_tool_calls"] is False
    assert [item["effort"] for item in model.entry["supported_reasoning_levels"]] == ["high"]
    assert model.entry["supports_search_tool"] is False
    assert model.provenance["context_window"] == "LiteLLM model-group minimum max_input_tokens"
    assert model.group_evidence["deployment_count"] == 2
    assert model.group_evidence["capabilities"]["supports_parallel_function_calling"]["state"] == "denied"


def test_multi_deployment_foreign_group_with_unknown_context_fails_closed():
    groups = [[
        row("foreign-group", "vendor/model-a", max_input_tokens=200_000),
        row("foreign-group", "vendor/model-b", max_input_tokens=None),
    ]]
    prepared = prepare_model_groups(groups, INDEX)

    with pytest.raises(AppError, match="max_input_tokens for every deployment"):
        generate_prepared_catalog(
            prepared,
            CATALOG,
            fallback_prompt=FALLBACK_PROMPT,
            model_info_schema=SCHEMA,
        )


def test_single_row_exact_output_preserves_v02_mapping():
    source = row(
        "gpt-5.6-sol",
        "azure/gpt-5.6-sol",
        supports_vision=True,
        supported_openai_params=["parallel_tool_calls", "verbosity"],
    )
    prepared = prepare_model_groups([[source]], INDEX)[0]

    integrated = generate_prepared_model(prepared, INDEX)
    legacy = generate_model(source, INDEX)

    assert integrated.entry == legacy.entry
    assert integrated.provenance == legacy.provenance
    assert integrated.notes == legacy.notes
    assert integrated.group_evidence["deployment_count"] == 1


def test_ambiguous_single_row_does_not_fall_back_to_legacy_first_match():
    sol = deepcopy(INDEX["gpt-5.6-sol"])
    luna = deepcopy(sol)
    luna["slug"] = "gpt-5.6-luna"
    catalog = {"models": [sol, luna]}
    index = {model["slug"]: model for model in catalog["models"]}
    source = row(
        "alias",
        "openai/gpt-5.6-luna",
        base_model="gpt-5.6-sol",
    )

    prepared = prepare_model_groups([[source]], index)[0]
    integrated = generate_prepared_model(
        prepared,
        index,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
        codex_catalog=catalog,
    )

    assert prepared.evidence.kind == "foreign"
    assert integrated.kind == "foreign"
    assert integrated.template_slug is None
    assert set(integrated.group_evidence["deployments"][0]["template_matches"]) == {
        "gpt-5.6-sol",
        "gpt-5.6-luna",
    }
