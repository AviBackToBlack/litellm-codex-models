from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
import tomllib

from .errors import AppError
from .mapping import REASONING_DESCRIPTIONS


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
class ModelOverride:
    supports_vision: bool | None = None
    supports_audio_input: bool | None = None
    supports_function_calling: bool | None = None
    supports_parallel_function_calling: bool | None = None
    supports_web_search: bool | None = None
    supports_reasoning: bool | None = None
    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    supported_openai_params: tuple[str, ...] | None = None
    reasoning_effort_levels: tuple[str, ...] | None = None


@dataclass(frozen=True)
class AppConfig:
    models: tuple[str, ...]
    strict: bool
    litellm: LiteLLMConfig
    codex: CodexConfig
    output: OutputConfig
    model_globs: tuple[str, ...] = ()
    model_overrides: Mapping[str, ModelOverride] = field(
        default_factory=lambda: MappingProxyType({})
    )


_BOOLEAN_OVERRIDE_FIELDS = (
    "supports_vision",
    "supports_audio_input",
    "supports_function_calling",
    "supports_parallel_function_calling",
    "supports_web_search",
    "supports_reasoning",
)
_LIMIT_OVERRIDE_FIELDS = ("max_input_tokens", "max_output_tokens")
_SET_OVERRIDE_FIELDS = ("supported_openai_params", "reasoning_effort_levels")
_OVERRIDE_FIELDS = frozenset(
    _BOOLEAN_OVERRIDE_FIELDS + _LIMIT_OVERRIDE_FIELDS + _SET_OVERRIDE_FIELDS
)


def _string_list(raw: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(x, str) and x for x in raw):
        raise AppError(f'{field} must be an array of non-empty strings')
    if len(raw) != len(set(raw)):
        raise AppError(f'{field} contains duplicates')
    return tuple(raw)


def _override_string_set(raw: object, *, field: str) -> tuple[str, ...]:
    values = _string_list(raw, field=field)
    return tuple(sorted(values))


def _parse_model_override(model_name: str, raw: object) -> ModelOverride:
    if not isinstance(raw, dict):
        raise AppError(f'Config model_overrides."{model_name}" must be a table')

    unknown = sorted(set(raw) - _OVERRIDE_FIELDS)
    if unknown:
        raise AppError(
            f'Config model_overrides."{model_name}" contains unsupported field(s): '
            + ", ".join(unknown)
        )

    parsed: dict[str, object] = {}
    for name in _BOOLEAN_OVERRIDE_FIELDS:
        if name not in raw:
            continue
        value = raw[name]
        if not isinstance(value, bool):
            raise AppError(
                f'Config model_overrides."{model_name}".{name} must be a boolean'
            )
        parsed[name] = value

    for name in _LIMIT_OVERRIDE_FIELDS:
        if name not in raw:
            continue
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise AppError(
                f'Config model_overrides."{model_name}".{name} must be a positive integer'
            )
        parsed[name] = value

    if "supported_openai_params" in raw:
        parsed["supported_openai_params"] = _override_string_set(
            raw["supported_openai_params"],
            field=f'Config model_overrides."{model_name}".supported_openai_params',
        )

    if "reasoning_effort_levels" in raw:
        efforts = _override_string_set(
            raw["reasoning_effort_levels"],
            field=f'Config model_overrides."{model_name}".reasoning_effort_levels',
        )
        unknown_efforts = sorted(set(efforts) - set(REASONING_DESCRIPTIONS))
        if unknown_efforts:
            raise AppError(
                f'Config model_overrides."{model_name}".reasoning_effort_levels contains unsupported effort(s): '
                + ", ".join(unknown_efforts)
            )
        parsed["reasoning_effort_levels"] = tuple(
            effort for effort in REASONING_DESCRIPTIONS if effort in efforts
        )

    if (
        parsed.get("supports_function_calling") is False
        and parsed.get("supports_parallel_function_calling") is True
    ):
        raise AppError(
            f'Config model_overrides."{model_name}" is contradictory: '
            "supports_function_calling=false cannot be combined with "
            "supports_parallel_function_calling=true"
        )
    reasoning_efforts = parsed.get("reasoning_effort_levels")
    if (
        parsed.get("supports_reasoning") is False
        and isinstance(reasoning_efforts, tuple)
        and reasoning_efforts
    ):
        raise AppError(
            f'Config model_overrides."{model_name}" is contradictory: '
            "supports_reasoning=false cannot be combined with non-empty "
            "reasoning_effort_levels"
        )

    return ModelOverride(**parsed)


def _parse_model_overrides(raw: object) -> Mapping[str, ModelOverride]:
    if raw is None:
        return MappingProxyType({})
    if not isinstance(raw, dict):
        raise AppError("Config model_overrides must be a table")

    parsed: dict[str, ModelOverride] = {}
    for model_name, value in raw.items():
        if not isinstance(model_name, str) or not model_name:
            raise AppError("Config model_overrides keys must be non-empty exact model names")
        parsed[model_name] = _parse_model_override(model_name, value)
    return MappingProxyType(parsed)


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise AppError(f"Invalid TOML in {path}: {exc}") from exc

    models = _string_list(raw.get("models", []), field="Config models allowlist")
    model_globs = _string_list(raw.get("model_globs", []), field="Config model_globs")
    if not models and not model_globs:
        raise AppError("Config must select at least one model through models or model_globs")
    model_overrides = _parse_model_overrides(raw.get("model_overrides"))

    filter_raw = raw.get("filter") or {}
    litellm_raw = raw.get("litellm") or {}
    codex_raw = raw.get("codex") or {}
    output_raw = raw.get("output") or {}

    return AppConfig(
        models=models,
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
        model_globs=model_globs,
        model_overrides=model_overrides,
    )
