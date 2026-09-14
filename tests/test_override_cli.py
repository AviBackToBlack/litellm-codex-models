from __future__ import annotations

import json
from pathlib import Path

from litellm_codex_models.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"


def test_strict_false_allows_selector_covered_override_target_absent_from_payload(
    tmp_path,
    capsys,
):
    config = tmp_path / "config.toml"
    output = tmp_path / "models.json"
    config.write_text(
        f'''
models = ["temporarily-missing"]

[filter]
strict = false

[model_overrides."temporarily-missing"]
supports_vision = true

[output]
path = "{output.as_posix()}"
''',
        encoding="utf-8",
    )
    payload = tmp_path / "litellm.json"
    payload.write_text(json.dumps({"data": []}), encoding="utf-8")

    result = main(
        [
            "--config",
            str(config),
            "build",
            "--input",
            str(payload),
            "--catalog-file",
            str(FIXTURE),
        ]
    )

    assert result == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"models": []}
    assert "Wrote 0 models" in capsys.readouterr().out


def test_explain_prints_original_and_effective_override_evidence(tmp_path, capsys):
    config = tmp_path / "config.toml"
    config.write_text(
        '''
models = ["gpt-5.6-sol"]

[model_overrides."gpt-5.6-sol"]
supports_vision = true
''',
        encoding="utf-8",
    )
    payload = tmp_path / "litellm.json"
    payload.write_text(
        json.dumps(
            {
                "data": [
                    {
                        "model_name": "gpt-5.6-sol",
                        "litellm_params": {
                            "model": "openai/gpt-5.6-sol",
                            "base_model": "gpt-5.6-sol",
                        },
                        "model_info": {
                            "mode": "chat",
                            "max_input_tokens": 200000,
                            "supports_vision": False,
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "--config",
            str(config),
            "explain",
            "--input",
            str(payload),
            "--catalog-file",
            str(FIXTURE),
            "gpt-5.6-sol",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert '"configured_overrides"' in output
    assert '"original"' in output
    assert '"effective"' in output
    assert "config:model_overrides.gpt-5.6-sol.supports_vision" in output
