from __future__ import annotations

import pytest

from litellm_codex_models.config import load_config
from litellm_codex_models.errors import AppError


def write_config(tmp_path, text: str):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_existing_exact_only_config_keeps_empty_globs(tmp_path):
    config = load_config(write_config(tmp_path, 'models = ["a"]\n'))
    assert config.models == ("a",)
    assert config.model_globs == ()


def test_glob_only_selection_does_not_require_empty_exact_list(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            'model_globs = ["claude-*", "gpt-oss-*"]\n',
        )
    )
    assert config.models == ()
    assert config.model_globs == ("claude-*", "gpt-oss-*")


def test_duplicate_model_glob_is_rejected(tmp_path):
    with pytest.raises(AppError, match="model_globs contains duplicates"):
        load_config(
            write_config(
                tmp_path,
                'models = ["a"]\nmodel_globs = ["claude-*", "claude-*"]\n',
            )
        )


def test_empty_model_glob_is_rejected(tmp_path):
    with pytest.raises(AppError, match="model_globs must be an array of non-empty strings"):
        load_config(write_config(tmp_path, 'models = ["a"]\nmodel_globs = [""]\n'))


def test_config_requires_at_least_one_exact_or_glob_selector(tmp_path):
    with pytest.raises(AppError, match="select at least one model"):
        load_config(write_config(tmp_path, "models = []\nmodel_globs = []\n"))


def test_model_overrides_fail_closed_until_override_slice_is_implemented(tmp_path):
    with pytest.raises(AppError, match="model_overrides are not supported"):
        load_config(
            write_config(
                tmp_path,
                'models = ["a"]\n[model_overrides.a]\nsupports_vision = true\n',
            )
        )
