from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import pytest

import litellm_codex_models.cli as cli
from litellm_codex_models.config import AppConfig, CodexConfig, LiteLLMConfig, OutputConfig
from litellm_codex_models.errors import AppError


FIXTURE = Path(__file__).parent / "fixtures" / "codex-models.json"


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _resource(tmp_path: Path, name: str, content: bytes) -> dict[str, str]:
    (tmp_path / name).write_bytes(content)
    return {"path": name, "sha256": _digest(content)}


def _bundle(tmp_path: Path, files: dict[str, dict[str, str]]) -> Path:
    manifest = tmp_path / "codex-bundle.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "codex": {
                    "repository": "openai/codex",
                    "ref": "rust-v0.153.0",
                },
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def _args(bundle: str | Path, **overrides) -> argparse.Namespace:
    values = {
        "input": None,
        "codex_bundle": str(bundle),
        "catalog_file": None,
        "codex_prompt_file": None,
        "codex_schema_file": None,
        "codex_ref": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _config(model: str) -> AppConfig:
    return AppConfig(
        models=(model,),
        strict=True,
        litellm=LiteLLMConfig(),
        codex=CodexConfig(),
        output=OutputConfig(),
    )


def _exact_row() -> dict:
    return {
        "model_name": "gpt-5.6-sol",
        "model_info": {
            "mode": "chat",
            "base_model": "gpt-5.6-sol",
        },
        "litellm_params": {
            "model": "openai/gpt-5.6-sol",
        },
    }


def _foreign_row() -> dict:
    return {
        "model_name": "vendor-model",
        "model_info": {
            "mode": "chat",
            "max_input_tokens": 64000,
            "supports_function_calling": False,
        },
        "litellm_params": {
            "model": "vendor/example-model",
        },
    }


def test_parser_accepts_verified_bundle_for_build_and_explain():
    build = cli.build_parser().parse_args(["build", "--codex-bundle", "codex-bundle.json"])
    explain = cli.build_parser().parse_args(
        ["explain", "--codex-bundle", "codex-bundle.json", "gpt-5.6-sol"]
    )

    assert build.codex_bundle == "codex-bundle.json"
    assert explain.codex_bundle == "codex-bundle.json"


@pytest.mark.parametrize(
    ("attr", "value", "flag"),
    [
        ("catalog_file", "models.json", "--catalog-file"),
        ("codex_prompt_file", "prompt.md", "--codex-prompt-file"),
        ("codex_schema_file", "openai_models.rs", "--codex-schema-file"),
        ("codex_ref", "main", "--codex-ref"),
    ],
)
def test_bundle_conflicts_fail_before_litellm_work(monkeypatch, attr, value, flag):
    def unexpected_litellm(*_args, **_kwargs):
        raise AssertionError("LiteLLM must not be touched before bundle conflicts are rejected")

    monkeypatch.setattr(cli, "_load_litellm", unexpected_litellm)

    with pytest.raises(AppError, match=flag):
        cli._build(_args("missing-bundle.json", **{attr: value}), _config("gpt-5.6-sol"))


def test_exact_only_build_needs_only_verified_catalog(monkeypatch, tmp_path):
    catalog = FIXTURE.read_bytes()
    manifest = _bundle(
        tmp_path,
        {"catalog": _resource(tmp_path, "models.json", catalog)},
    )
    monkeypatch.setattr(cli, "_load_litellm", lambda *_args, **_kwargs: [_exact_row()])

    generated, explanations, source = cli._build(_args(manifest), _config("gpt-5.6-sol"))

    assert explanations["gpt-5.6-sol"].kind == "exact"
    assert generated["models"][0]["slug"] == "gpt-5.6-sol"
    assert source.startswith("bundle:openai/codex@rust-v0.153.0")


def test_foreign_build_requires_prompt_and_schema_in_same_bundle(monkeypatch, tmp_path):
    manifest = _bundle(
        tmp_path,
        {"catalog": _resource(tmp_path, "models.json", FIXTURE.read_bytes())},
    )
    monkeypatch.setattr(cli, "_load_litellm", lambda *_args, **_kwargs: [_foreign_row()])

    with pytest.raises(AppError, match=r"missing: prompt, schema"):
        cli._build(_args(manifest), _config("vendor-model"))


def test_foreign_build_consumes_verified_bundle_prompt_and_schema(monkeypatch, tmp_path):
    prompt = b"You are the verified generic Codex prompt.\n"
    schema = b"pub struct ModelInfo {\n    pub slug: String,\n}\n"
    manifest = _bundle(
        tmp_path,
        {
            "catalog": _resource(tmp_path, "models.json", FIXTURE.read_bytes()),
            "prompt": _resource(tmp_path, "prompt.md", prompt),
            "schema": _resource(tmp_path, "openai_models.rs", schema),
        },
    )
    monkeypatch.setattr(cli, "_load_litellm", lambda *_args, **_kwargs: [_foreign_row()])

    _generated, explanations, source = cli._build(_args(manifest), _config("vendor-model"))

    model = explanations["vendor-model"]
    assert model.kind == "foreign"
    assert model.entry["model_messages"]["instructions_template"] == prompt.decode("utf-8")
    assert model.entry["context_window"] == 64000
    assert source.startswith("bundle:openai/codex@rust-v0.153.0")
