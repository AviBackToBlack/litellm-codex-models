import json
from pathlib import Path

import pytest

from litellm_codex_models.aggregation import aggregate_model_group
from litellm_codex_models.errors import AppError
from litellm_codex_models.mapping import generate_model


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text())
CATALOG_INDEX = {model["slug"]: model for model in CATALOG["models"]}
AMBIGUOUS_INDEX = {
    "gpt-5.6-sol": {},
    "gpt-5.6-luna": {},
}


def row(
    name="group",
    model="vendor/model-a",
    *,
    mode="chat",
    base_model=None,
    **info,
):
    params = {
        "model": model,
        "base_model": base_model if base_model is not None else model,
    }
    return {
        "model_name": name,
        "litellm_params": params,
        "model_info": {"mode": mode, "max_input_tokens": 200_000, **info},
    }


def test_ambiguous_catalog_matches_force_foreign_fallback():
    source = row(
        "alias",
        "openai/gpt-5.6-luna",
        base_model="gpt-5.6-sol",
    )

    group = aggregate_model_group([source], AMBIGUOUS_INDEX)

    assert group.kind == "foreign"
    assert group.template_slug is None
    assert group.deployments[0].template_matches == (
        "gpt-5.6-sol",
        "gpt-5.6-luna",
    )
    assert any("exact-template identity" in item for item in group.disagreements)


def test_foreign_canonical_identity_conflicts_are_reported():
    group = aggregate_model_group(
        [
            row("shared", "vendor/model-a"),
            row("shared", "vendor/model-b"),
        ],
        CATALOG_INDEX,
    )

    assert group.kind == "foreign"
    identity_disagreement = next(
        item
        for item in group.disagreements
        if item.startswith("canonical identity candidates:")
    )
    assert "vendor/model-a" in identity_disagreement
    assert "vendor/model-b" in identity_disagreement


def test_exact_grouping_does_not_trim_user_facing_model_name():
    with pytest.raises(AppError, match="shared model_name"):
        aggregate_model_group(
            [
                row("group", "vendor/model-a"),
                row(" group ", "vendor/model-b"),
            ],
            CATALOG_INDEX,
        )


def test_capability_mapping_is_immutable():
    group = aggregate_model_group(
        [row(supports_vision=True)],
        CATALOG_INDEX,
    )

    with pytest.raises(TypeError):
        group.capabilities["supports_vision"] = group.capabilities["supports_vision"]


def test_single_row_exact_identity_matches_existing_v02_mapping():
    source = row(
        "gpt-5.6-sol",
        "azure/gpt-5.6-sol",
        supports_vision=True,
        supported_openai_params=["parallel_tool_calls", "verbosity"],
    )

    group = aggregate_model_group([source], CATALOG_INDEX)
    generated = generate_model(source, CATALOG_INDEX)

    assert group.kind == generated.kind
    assert group.template_slug == generated.template_slug
    assert group.canonical_model == generated.canonical_model
    assert group.model_name == generated.entry["slug"]
    assert group.max_input_tokens.value == source["model_info"]["max_input_tokens"]
    assert group.capabilities["supports_vision"].value is True


def test_shared_group_alias_cannot_prove_multi_deployment_exact_identity():
    group = aggregate_model_group(
        [
            row("gpt-5.6-sol", "vendor/model-a"),
            row("gpt-5.6-sol", "vendor/model-b"),
        ],
        AMBIGUOUS_INDEX,
    )

    assert group.kind == "foreign"
    assert group.template_slug is None
    assert all(
        "gpt-5.6-sol" not in deployment.canonical_candidates
        for deployment in group.deployments
    )


def test_single_row_alias_preserves_v02_identity_compatibility():
    source = row("gpt-5.6-sol", "vendor/not-in-codex")

    group = aggregate_model_group([source], AMBIGUOUS_INDEX)
    generated = generate_model(source, AMBIGUOUS_INDEX)

    assert group.kind == "exact"
    assert group.template_slug == "gpt-5.6-sol"
    assert group.kind == generated.kind
    assert group.template_slug == generated.template_slug


def test_standalone_reasoning_effort_denial_is_preserved_for_exact_mapping():
    group = aggregate_model_group(
        [
            row(
                "alias",
                "openai/gpt-5.6-sol",
                supports_low_reasoning_effort=False,
            )
        ],
        AMBIGUOUS_INDEX,
    )

    assert group.kind == "exact"
    assert group.reasoning_efforts.state == "unknown"
    assert group.denied_reasoning_efforts == ("low",)
    assert ("low", "false") in group.deployments[0].reasoning_effort_evidence


def test_whitespace_padded_mode_fails_same_exact_eligibility_check_as_v02():
    with pytest.raises(AppError, match="non-Codex-eligible"):
        aggregate_model_group(
            [row(mode=" chat ")],
            AMBIGUOUS_INDEX,
        )


@pytest.mark.parametrize(
    ("field", "malformed_value"),
    [
        ("litellm_params", []),
        ("litellm_params", None),
        ("model_info", "chat"),
        ("model_info", None),
    ],
)
def test_malformed_nested_deployment_metadata_fails_closed(field, malformed_value):
    source = row()
    source[field] = malformed_value

    with pytest.raises(AppError, match="object-valued model_info and litellm_params"):
        aggregate_model_group([source], AMBIGUOUS_INDEX)


@pytest.mark.parametrize("field", ["litellm_params", "model_info"])
def test_missing_nested_deployment_metadata_fails_closed(field):
    source = row()
    source.pop(field)

    with pytest.raises(AppError, match="object-valued model_info and litellm_params"):
        aggregate_model_group([source], AMBIGUOUS_INDEX)
