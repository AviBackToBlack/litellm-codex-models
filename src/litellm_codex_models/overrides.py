from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

from .aggregation import BooleanEvidence, LimitEvidence, ModelGroupEvidence, SetEvidence
from .config import ModelOverride


_CONTEXT_BLOCKER = (
    "foreign multi-deployment synthesis requires max_input_tokens for every deployment"
)
_BOOLEAN_FIELDS = (
    "supports_vision",
    "supports_audio_input",
    "supports_function_calling",
    "supports_parallel_function_calling",
    "supports_web_search",
    "supports_reasoning",
)
_OVERRIDE_FIELDS = (
    *_BOOLEAN_FIELDS,
    "max_input_tokens",
    "max_output_tokens",
    "supported_openai_params",
    "reasoning_effort_levels",
)


@dataclass(frozen=True)
class OverrideAudit:
    field: str
    source: str
    configured_value: Any
    original_state: str
    original_value: Any
    effective_state: str
    effective_value: Any


def configured_override_fields(override: ModelOverride) -> tuple[str, ...]:
    return tuple(
        field for field in _OVERRIDE_FIELDS if getattr(override, field) is not None
    )


def _snapshot(group: ModelGroupEvidence, field: str) -> tuple[str, Any]:
    if field in _BOOLEAN_FIELDS:
        evidence = group.capabilities[field]
        return evidence.state, evidence.value
    if field in ("max_input_tokens", "max_output_tokens"):
        evidence = getattr(group, field)
        return evidence.state, evidence.value
    if field == "supported_openai_params":
        evidence = group.supported_openai_params
        return evidence.state, evidence.values
    if field == "reasoning_effort_levels":
        evidence = group.reasoning_efforts
        return evidence.state, evidence.values
    raise AssertionError(f"unsupported override field: {field}")


def _configured_value(override: ModelOverride, field: str) -> Any:
    value = getattr(override, field)
    return tuple(value) if isinstance(value, tuple) else value


def apply_model_override(
    group: ModelGroupEvidence,
    override: ModelOverride,
) -> tuple[ModelGroupEvidence, tuple[OverrideAudit, ...]]:
    configured_fields = configured_override_fields(override)
    if not configured_fields:
        return group, ()

    capabilities = dict(group.capabilities)
    for field in _BOOLEAN_FIELDS:
        value = getattr(override, field)
        if value is None:
            continue
        capabilities[field] = BooleanEvidence(
            "guaranteed" if value else "denied",
            value,
            "configured model override",
        )

    max_input_tokens = group.max_input_tokens
    if override.max_input_tokens is not None:
        max_input_tokens = LimitEvidence(
            "known",
            override.max_input_tokens,
            "configured model override",
        )

    max_output_tokens = group.max_output_tokens
    if override.max_output_tokens is not None:
        max_output_tokens = LimitEvidence(
            "known",
            override.max_output_tokens,
            "configured model override",
        )

    supported_openai_params = group.supported_openai_params
    if override.supported_openai_params is not None:
        supported_openai_params = SetEvidence(
            "known",
            override.supported_openai_params,
            "configured model override",
        )

    reasoning_efforts = group.reasoning_efforts
    denied_reasoning_efforts = group.denied_reasoning_efforts
    if override.reasoning_effort_levels is not None:
        reasoning_efforts = SetEvidence(
            "known",
            override.reasoning_effort_levels,
            "configured model override",
        )
        # The explicit configured effort set replaces the aggregate effort
        # evidence, including deployment-level per-effort denials. The exact
        # mapper applies the effective set directly, including medium/high
        # levels that have no LiteLLM boolean flag.
        denied_reasoning_efforts = ()

    # Apply cross-field dependency closure after configured replacements.
    if capabilities["supports_reasoning"].state == "denied":
        reasoning_efforts = SetEvidence(
            "denied",
            (),
            "effective supports_reasoning=false disables reasoning efforts",
        )

    if capabilities["supports_function_calling"].state == "denied":
        capabilities["supports_parallel_function_calling"] = BooleanEvidence(
            "denied",
            False,
            "effective supports_function_calling=false prevents parallel function calling",
        )

    blockers = [
        blocker for blocker in group.foreign_synthesis_blockers if blocker != _CONTEXT_BLOCKER
    ]
    if (
        group.kind == "foreign"
        and group.deployment_count > 1
        and max_input_tokens.state != "known"
    ):
        blockers.append(_CONTEXT_BLOCKER)

    effective = replace(
        group,
        capabilities=MappingProxyType(capabilities),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        supported_openai_params=supported_openai_params,
        reasoning_efforts=reasoning_efforts,
        denied_reasoning_efforts=denied_reasoning_efforts,
        foreign_synthesis_blockers=tuple(blockers),
    )

    audits: list[OverrideAudit] = []
    for field in configured_fields:
        original_state, original_value = _snapshot(group, field)
        effective_state, effective_value = _snapshot(effective, field)
        audits.append(
            OverrideAudit(
                field=field,
                source=f"config:model_overrides.{group.model_name}.{field}",
                configured_value=_configured_value(override, field),
                original_state=original_state,
                original_value=original_value,
                effective_state=effective_state,
                effective_value=effective_value,
            )
        )
    return effective, tuple(audits)
