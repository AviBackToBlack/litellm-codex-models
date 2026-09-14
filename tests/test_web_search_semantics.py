from __future__ import annotations

import json
from pathlib import Path

import pytest

from litellm_codex_models.config import ModelOverride
from litellm_codex_models.group_mapping import generate_prepared_catalog, prepare_model_groups
from litellm_codex_models.mapping import generate_model
from litellm_codex_models.schema import ModelInfoSchema


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text(encoding="utf-8"))
INDEX = {model["slug"]: model for model in CATALOG["models"]}
FALLBACK_PROMPT = "You are a generic Codex coding agent."
SCHEMA = ModelInfoSchema(fields=frozenset(), required_fields=frozenset())


def row(name: str, model: str, **info):
    return {
        "model_name": name,
        "litellm_params": {"model": model, "base_model": model},
        "model_info": {"mode": "chat", **info},
    }


@pytest.mark.parametrize("supports_web_search", [True, False, None])
def test_exact_search_tool_is_codex_owned_regardless_of_litellm_web_search(
    supports_web_search: bool | None,
):
    generated = generate_model(
        row(
            "gpt-5.6-sol",
            "openai/gpt-5.6-sol",
            supports_web_search=supports_web_search,
        ),
        INDEX,
    )

    assert generated.entry["supports_search_tool"] is True
    assert generated.provenance["supports_search_tool"] == (
        "codex:exact-template:gpt-5.6-sol"
    )


@pytest.mark.parametrize(
    ("reported_value", "override_value", "expected_state"),
    [
        (False, True, "guaranteed"),
        (True, False, "denied"),
    ],
)
def test_exact_web_search_override_is_evidence_only_for_codex_search_tool(
    reported_value: bool,
    override_value: bool,
    expected_state: str,
):
    source = row(
        "gpt-5.6-sol",
        "openai/gpt-5.6-sol",
        supports_web_search=reported_value,
    )
    prepared = prepare_model_groups(
        [[source]],
        INDEX,
        {"gpt-5.6-sol": ModelOverride(supports_web_search=override_value)},
    )

    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["supports_search_tool"] is True
    assert model.provenance["supports_search_tool"] == (
        "codex:exact-template:gpt-5.6-sol"
    )
    assert model.group_evidence["capabilities"]["supports_web_search"]["state"] == (
        expected_state
    )
    assert "supports_web_search" in model.group_evidence["configured_overrides"]


def test_foreign_search_tool_is_conservative_tool_discovery_not_web_search_policy():
    source = row(
        "foreign-model",
        "vendor/model",
        max_input_tokens=200_000,
        supports_web_search=False,
    )
    prepared = prepare_model_groups(
        [[source]],
        INDEX,
        {"foreign-model": ModelOverride(supports_web_search=True)},
    )

    _generated, explanations = generate_prepared_catalog(
        prepared,
        CATALOG,
        fallback_prompt=FALLBACK_PROMPT,
        model_info_schema=SCHEMA,
    )
    model = explanations["foreign-model"]

    assert model.entry["supports_search_tool"] is False
    assert model.provenance["supports_search_tool"] == (
        "conservative: foreign tool-search/deferred discovery disabled"
    )
    assert model.group_evidence["capabilities"]["supports_web_search"]["state"] == (
        "guaranteed"
    )
    assert "supports_web_search" in model.group_evidence["configured_overrides"]
