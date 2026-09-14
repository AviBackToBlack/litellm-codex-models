from __future__ import annotations

import json
from pathlib import Path

import pytest

from litellm_codex_models.config import ModelOverride
from litellm_codex_models.group_mapping import generate_prepared_catalog, prepare_model_groups
from litellm_codex_models.mapping import generate_model


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text(encoding="utf-8"))
INDEX = {model["slug"]: model for model in CATALOG["models"]}


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
