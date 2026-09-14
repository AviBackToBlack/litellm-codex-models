from __future__ import annotations

import json
from pathlib import Path

from litellm_codex_models.config import ModelOverride
from litellm_codex_models.group_mapping import generate_prepared_catalog, prepare_model_groups


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text(encoding="utf-8"))
INDEX = {model["slug"]: model for model in CATALOG["models"]}


def test_exact_max_input_override_changes_evidence_not_codex_context_fields():
    source = {
        "model_name": "gpt-5.6-sol",
        "litellm_params": {
            "model": "openai/gpt-5.6-sol",
            "base_model": "gpt-5.6-sol",
        },
        "model_info": {
            "mode": "chat",
            "max_input_tokens": 100000,
        },
    }
    prepared = prepare_model_groups(
        [[source]],
        INDEX,
        {"gpt-5.6-sol": ModelOverride(max_input_tokens=123456)},
    )
    _generated, explanations = generate_prepared_catalog(prepared, CATALOG)
    model = explanations["gpt-5.6-sol"]

    assert model.entry["context_window"] == INDEX["gpt-5.6-sol"]["context_window"]
    assert model.entry["max_context_window"] == INDEX["gpt-5.6-sol"]["max_context_window"]
    audit = model.group_evidence["configured_overrides"]["max_input_tokens"]
    assert audit["original"] == {"state": "known", "value": 100000}
    assert audit["effective"] == {"state": "known", "value": 123456}
