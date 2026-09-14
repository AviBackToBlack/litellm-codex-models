from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .aggregation import ModelGroupEvidence, aggregate_model_group
from .errors import AppError
from .mapping import (
    EFFORT_FLAG_MAP,
    GeneratedModel,
    _build_foreign,
    _overlay_exact,
    generate_model,
    resolve_template,
)
from .schema import ModelInfoSchema


@dataclass(frozen=True)
class PreparedModelGroup:
    rows: tuple[dict[str, Any], ...]
    evidence: ModelGroupEvidence


@dataclass
class GroupGeneratedModel(GeneratedModel):
    group_evidence: dict[str, Any] | None = None


def prepare_model_groups(
    groups: list[list[dict[str, Any]]],
    codex_index: dict[str, dict[str, Any]],
) -> list[PreparedModelGroup]:
    return [
        PreparedModelGroup(
            rows=tuple(group),
            evidence=aggregate_model_group(group, codex_index),
        )
        for group in groups
    ]


def _group_evidence_payload(group: ModelGroupEvidence) -> dict[str, Any]:
    return {
        "deployment_count": group.deployment_count,
        "kind": group.kind,
        "template_slug": group.template_slug,
        "canonical_model": group.canonical_model,
        "deployments": [
            {
                "provider": deployment.provider,
                "model": deployment.model,
                "base_model": deployment.base_model,
                "mode": deployment.mode,
                "template_slug": deployment.template_slug,
                "template_matches": list(deployment.template_matches),
                "canonical_candidates": list(deployment.canonical_candidates),
            }
            for deployment in group.deployments
        ],
        "capabilities": {
            field: {
                "state": evidence.state,
                "value": evidence.value,
                "rule": evidence.rule,
            }
            for field, evidence in group.capabilities.items()
        },
        "max_input_tokens": {
            "state": group.max_input_tokens.state,
            "value": group.max_input_tokens.value,
            "rule": group.max_input_tokens.rule,
        },
        "max_output_tokens": {
            "state": group.max_output_tokens.state,
            "value": group.max_output_tokens.value,
            "rule": group.max_output_tokens.rule,
        },
        "supported_openai_params": {
            "state": group.supported_openai_params.state,
            "values": list(group.supported_openai_params.values),
            "rule": group.supported_openai_params.rule,
        },
        "reasoning_efforts": {
            "state": group.reasoning_efforts.state,
            "values": list(group.reasoning_efforts.values),
            "rule": group.reasoning_efforts.rule,
        },
        "denied_reasoning_efforts": list(group.denied_reasoning_efforts),
        "disagreements": list(group.disagreements),
        "foreign_synthesis_blockers": list(group.foreign_synthesis_blockers),
    }


def _synthetic_row(group: ModelGroupEvidence) -> dict[str, Any]:
    info: dict[str, Any] = {"mode": "chat"}

    for field, evidence in group.capabilities.items():
        if evidence.value is not None:
            info[field] = evidence.value

    if group.max_input_tokens.state == "known":
        info["max_input_tokens"] = group.max_input_tokens.value
    if group.max_output_tokens.state == "known":
        info["max_output_tokens"] = group.max_output_tokens.value
    if group.supported_openai_params.state == "known":
        info["supported_openai_params"] = list(group.supported_openai_params.values)
    if group.reasoning_efforts.state == "known":
        info["reasoning_effort_levels"] = list(group.reasoning_efforts.values)

    for effort in group.denied_reasoning_efforts:
        flag = EFFORT_FLAG_MAP.get(effort)
        if flag is not None:
            info[flag] = False

    return {
        "model_name": group.model_name,
        "litellm_params": {
            "model": group.canonical_model,
            "base_model": group.canonical_model,
        },
        "model_info": info,
    }


def _wrap(model: GeneratedModel, group: ModelGroupEvidence) -> GroupGeneratedModel:
    return GroupGeneratedModel(
        entry=model.entry,
        provenance=model.provenance,
        canonical_model=model.canonical_model,
        template_slug=model.template_slug,
        kind=model.kind,
        notes=model.notes,
        group_evidence=_group_evidence_payload(group),
    )


def _legacy_single_row_is_safe(
    prepared: PreparedModelGroup,
    codex_index: dict[str, dict[str, Any]],
) -> bool:
    if len(prepared.rows) != 1:
        return False
    legacy_slug, _canonical = resolve_template(prepared.rows[0], codex_index)
    group = prepared.evidence
    if group.kind == "exact":
        return legacy_slug == group.template_slug
    return legacy_slug is None


def _apply_exact_group_capability_denials(
    entry: dict[str, Any],
    group: ModelGroupEvidence,
    provenance: dict[str, str],
) -> None:
    reasoning = group.capabilities["supports_reasoning"]
    if reasoning.state == "denied":
        if isinstance(entry.get("supported_reasoning_levels"), list):
            entry["supported_reasoning_levels"] = []
            provenance["supported_reasoning_levels"] = (
                "codex:exact-template downgraded by LiteLLM model-group supports_reasoning=false"
            )
        if "default_reasoning_level" in entry:
            entry["default_reasoning_level"] = None
            provenance["default_reasoning_level"] = (
                "derived: disabled by LiteLLM model-group reasoning denial"
            )
        if entry.get("supports_reasoning_summary_parameter") is True:
            entry["supports_reasoning_summary_parameter"] = False
            provenance["supports_reasoning_summary_parameter"] = (
                "codex:exact-template downgraded by LiteLLM model-group reasoning denial"
            )

    parallel = group.capabilities["supports_parallel_function_calling"]
    functions = group.capabilities["supports_function_calling"]
    if (
        parallel.state == "denied" or functions.state == "denied"
    ) and entry.get("supports_parallel_tool_calls") is True:
        entry["supports_parallel_tool_calls"] = False
        provenance["supports_parallel_tool_calls"] = (
            "codex:exact-template downgraded by LiteLLM model-group "
            "function-calling capability denial"
        )


def generate_prepared_model(
    prepared: PreparedModelGroup,
    codex_index: dict[str, dict[str, Any]],
    *,
    fallback_prompt: str | None = None,
    model_info_schema: ModelInfoSchema | None = None,
    codex_catalog: dict[str, Any] | None = None,
) -> GroupGeneratedModel:
    group = prepared.evidence

    if _legacy_single_row_is_safe(prepared, codex_index):
        model = generate_model(
            prepared.rows[0],
            codex_index,
            fallback_prompt=fallback_prompt,
            model_info_schema=model_info_schema,
            codex_catalog=codex_catalog,
        )
        return _wrap(model, group)

    synthetic = _synthetic_row(group)

    if group.kind == "exact":
        assert group.template_slug is not None
        entry = deepcopy(codex_index[group.template_slug])
        provenance = {
            key: f"codex:exact-template:{group.template_slug}" for key in entry
        }
        notes = [f"Aggregated {group.deployment_count} LiteLLM deployments"]
        entry["slug"] = group.model_name
        provenance["slug"] = "LiteLLM model-group model_name"
        if group.model_name != group.template_slug:
            entry["display_name"] = group.model_name
            provenance["display_name"] = "derived: LiteLLM model-group alias"
            notes.append(f"Group resolves to exact Codex template {group.template_slug}")
        _overlay_exact(entry, synthetic, provenance, notes)
        _apply_exact_group_capability_denials(entry, group, provenance)
        notes.extend(f"Group disagreement: {item}" for item in group.disagreements)
        return GroupGeneratedModel(
            entry=entry,
            provenance=provenance,
            canonical_model=group.template_slug,
            template_slug=group.template_slug,
            kind="exact",
            notes=notes,
            group_evidence=_group_evidence_payload(group),
        )

    if group.foreign_synthesis_blockers:
        raise AppError(
            f'Model group "{group.model_name}" cannot be safely synthesized: '
            + "; ".join(group.foreign_synthesis_blockers)
        )
    if fallback_prompt is None:
        raise AppError("Foreign model-group generation requires the version-matched Codex fallback prompt")
    if model_info_schema is None or codex_catalog is None:
        raise AppError("Foreign model-group generation requires the version-matched Codex ModelInfo schema")

    model = _build_foreign(
        synthetic,
        group.canonical_model,
        fallback_prompt,
        model_info_schema,
        codex_catalog,
    )
    model.notes.insert(0, f"Aggregated {group.deployment_count} LiteLLM deployments")
    model.notes.extend(f"Group disagreement: {item}" for item in group.disagreements)

    if group.max_input_tokens.state == "known":
        model.provenance["context_window"] = "LiteLLM model-group minimum max_input_tokens"
        model.provenance["max_context_window"] = "LiteLLM model-group minimum max_input_tokens"
    model.provenance["input_modalities"] = "LiteLLM model-group guaranteed capability evidence"
    model.provenance["supported_reasoning_levels"] = "LiteLLM model-group explicit reasoning-effort intersection"
    model.provenance["support_verbosity"] = "LiteLLM model-group supported_openai_params intersection"

    if "supports_parallel_tool_calls" in model.entry:
        parallel = group.capabilities["supports_parallel_function_calling"]
        functions = group.capabilities["supports_function_calling"]
        if parallel.state != "guaranteed" or functions.state != "guaranteed":
            model.entry["supports_parallel_tool_calls"] = False
            model.provenance["supports_parallel_tool_calls"] = (
                "conservative: LiteLLM model-group function/parallel capability not guaranteed"
            )
        else:
            model.provenance["supports_parallel_tool_calls"] = (
                "LiteLLM model-group parameter/function/parallel-capability guarantee"
            )

    return _wrap(model, group)


def generate_prepared_catalog(
    prepared_groups: list[PreparedModelGroup],
    codex_catalog: dict[str, Any],
    *,
    fallback_prompt: str | None = None,
    model_info_schema: ModelInfoSchema | None = None,
) -> tuple[dict[str, Any], dict[str, GroupGeneratedModel]]:
    codex_index = {model["slug"]: model for model in codex_catalog["models"]}
    generated: list[dict[str, Any]] = []
    explanations: dict[str, GroupGeneratedModel] = {}

    for prepared in prepared_groups:
        model = generate_prepared_model(
            prepared,
            codex_index,
            fallback_prompt=fallback_prompt,
            model_info_schema=model_info_schema,
            codex_catalog=codex_catalog,
        )
        generated.append(model.entry)
        explanations[model.entry["slug"]] = model

    return {"models": generated}, explanations
