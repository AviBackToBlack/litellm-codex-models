from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .errors import AppError


@dataclass(frozen=True)
class LiteLLMConfig:
    url: str | None = None
    api_key_env: str = "LITELLM_API_KEY"
    endpoint: str = "/v1/model/info"
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class CodexConfig:
    binary: str = "codex"
    version: str = "auto"
    ref: str | None = None
    repository: str = "openai/codex"


@dataclass(frozen=True)
class OutputConfig:
    path: str = "models.json"
    pretty: bool = True


@dataclass(frozen=True)
class AppConfig:
    models: tuple[str, ...]
    strict: bool
    litellm: LiteLLMConfig
    codex: CodexConfig
    output: OutputConfig


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise AppError(f"Invalid TOML in {path}: {exc}") from exc

    models = raw.get("models")
    if not isinstance(models, list) or not models or not all(isinstance(x, str) and x for x in models):
        raise AppError("Config must contain a non-empty top-level models = [\"...\"] array")
    if len(models) != len(set(models)):
        raise AppError("Config models allowlist contains duplicates")

    filter_raw = raw.get("filter") or {}
    litellm_raw = raw.get("litellm") or {}
    codex_raw = raw.get("codex") or {}
    output_raw = raw.get("output") or {}

    return AppConfig(
        models=tuple(models),
        strict=bool(filter_raw.get("strict", True)),
        litellm=LiteLLMConfig(
            url=litellm_raw.get("url"),
            api_key_env=str(litellm_raw.get("api_key_env", "LITELLM_API_KEY")),
            endpoint=str(litellm_raw.get("endpoint", "/v1/model/info")),
            timeout_seconds=float(litellm_raw.get("timeout_seconds", 30.0)),
        ),
        codex=CodexConfig(
            binary=str(codex_raw.get("binary", "codex")),
            version=str(codex_raw.get("version", "auto")),
            ref=codex_raw.get("ref"),
            repository=str(codex_raw.get("repository", "openai/codex")),
        ),
        output=OutputConfig(
            path=str(output_raw.get("path", "models.json")),
            pretty=bool(output_raw.get("pretty", True)),
        ),
    )
