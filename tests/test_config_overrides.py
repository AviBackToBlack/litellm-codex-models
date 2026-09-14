from __future__ import annotations

import pytest

from litellm_codex_models.config import load_config
from litellm_codex_models.errors import AppError


def write_config(tmp_path, text: str):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_whitelisted_override_fields_and_normalizes_sets(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            '''
models = ["model-a"]

[model_overrides."model-a"]
supports_vision = true
supports_audio_input = false
supports_function_calling = true
supports_parallel_function_calling = true
supports_web_search = true
supports_reasoning = true
max_input_tokens = 200000
max_output_tokens = 32000
supported_openai_params = ["verbosity", "tools", "reasoning_effort"]
reasoning_effort_levels = ["high", "low", "medium"]
''',
        )
    )

    override = config.model_overrides["model-a"]
    assert override.supports_vision is True
    assert override.supports_audio_input is False
    assert override.max_input_tokens == 200000
    assert override.max_output_tokens == 32000
    assert override.supported_openai_params == (
        "reasoning_effort",
        "tools",
        "verbosity",
    )
    assert override.reasoning_effort_levels == ("low", "medium", "high")


def test_override_target_may_be_selected_by_glob(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            '''
model_globs = ["claude-*"]

[model_overrides."claude-sonnet-5"]
supports_vision = true
''',
        )
    )
    assert "claude-sonnet-5" in config.model_overrides


def test_override_target_outside_all_selectors_is_rejected(tmp_path):
    with pytest.raises(AppError, match="not selected"):
        load_config(
            write_config(
                tmp_path,
                '''
models = ["model-a"]
model_globs = ["claude-*"]

[model_overrides."other-model"]
supports_vision = true
''',
            )
        )


@pytest.mark.parametrize(
    "body, match",
    [
        ("made_up = true", "unsupported field"),
        ("supports_vision = 1", "must be a boolean"),
        ("max_input_tokens = true", "positive integer"),
        ("max_output_tokens = 0", "positive integer"),
        (
            'supported_openai_params = ["tools", "tools"]',
            "contains duplicates",
        ),
        (
            'reasoning_effort_levels = ["low", "turbo"]',
            "unsupported effort",
        ),
    ],
)
def test_invalid_override_values_fail_closed(tmp_path, body, match):
    with pytest.raises(AppError, match=match):
        load_config(
            write_config(
                tmp_path,
                f'''models = ["model-a"]

[model_overrides."model-a"]
{body}
''',
            )
        )


def test_function_and_parallel_contradiction_is_rejected(tmp_path):
    with pytest.raises(AppError, match="contradictory"):
        load_config(
            write_config(
                tmp_path,
                '''
models = ["model-a"]

[model_overrides."model-a"]
supports_function_calling = false
supports_parallel_function_calling = true
''',
            )
        )


def test_reasoning_false_with_nonempty_efforts_is_rejected(tmp_path):
    with pytest.raises(AppError, match="contradictory"):
        load_config(
            write_config(
                tmp_path,
                '''
models = ["model-a"]

[model_overrides."model-a"]
supports_reasoning = false
reasoning_effort_levels = ["low"]
''',
            )
        )


def test_reasoning_false_with_explicit_empty_effort_set_is_valid(tmp_path):
    config = load_config(
        write_config(
            tmp_path,
            '''
models = ["model-a"]

[model_overrides."model-a"]
supports_reasoning = false
reasoning_effort_levels = []
''',
        )
    )
    override = config.model_overrides["model-a"]
    assert override.supports_reasoning is False
    assert override.reasoning_effort_levels == ()
