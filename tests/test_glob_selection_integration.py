from __future__ import annotations

import json
from pathlib import Path

import pytest

from litellm_codex_models.cli import main
from litellm_codex_models.codex import catalog_index
from litellm_codex_models.errors import AppError
from litellm_codex_models.group_mapping import generate_prepared_catalog, prepare_model_groups
from litellm_codex_models.litellm import select_model_groups_with_provenance


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"
CATALOG = json.loads(FIXTURE.read_text(encoding="utf-8"))
INDEX = catalog_index(CATALOG)


def row(name: str, *, mode: str = "chat") -> dict:
    return {
        "model_name": name,
        "litellm_params": {"model": name},
        "model_info": {"mode": mode},
    }


def test_glob_selected_ineligible_group_still_fails_aggregation():
    selected = select_model_groups_with_provenance(
        [row("embed-model", mode="embedding")],
        (),
        ("embed-*",),
        strict=True,
    )

    with pytest.raises(AppError, match="mode"):
        prepare_model_groups(selected, INDEX)


def test_selection_provenance_survives_preparation_and_generation():
    selected = select_model_groups_with_provenance(
        [row("gpt-5.6-sol")],
        (),
        ("gpt-*",),
        strict=True,
    )
    prepared = prepare_model_groups(selected, INDEX)
    generated, explanations = generate_prepared_catalog(prepared, CATALOG)

    assert generated["models"][0]["slug"] == "gpt-5.6-sol"
    assert prepared[0].selection_source == "glob:gpt-*"
    assert explanations["gpt-5.6-sol"].selection_source == "glob:gpt-*"


def test_explain_accepts_glob_selected_model_and_prints_selection_source(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text('models = []\nmodel_globs = ["gpt-*"]\n', encoding="utf-8")

    payload = tmp_path / "litellm.json"
    payload.write_text(
        json.dumps({"data": [row("gpt-5.6-sol")]}),
        encoding="utf-8",
    )

    result = main([
        "--config",
        str(config),
        "explain",
        "--input",
        str(payload),
        "--catalog-file",
        str(FIXTURE),
        "gpt-5.6-sol",
    ])

    assert result == 0
    assert "selection_source: glob:gpt-*" in capsys.readouterr().out
