from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from .aggregation import ModelGroupEvidence, aggregate_model_group
from .config import ModelOverride
from .errors import AppError
from .litellm import SelectedModelGroup
from .mapping import (
    EFFORT_FLAG_MAP,
    GeneratedModel,
    _build_foreign,
    _overlay_exact,
    generate_model,
    resolve_template,
)
from .overrides import OverrideAudit, apply_model_override
from .schema import ModelInfoSchema


@dataclass(frozen=True)
class PreparedModelGroup:
    rows: tuple[dict[str, Any], ...]
    evidence: ModelGroupEvidence
    selection_source: str | None = None
    model_override: ModelOverride | None = None
    override_audit: tuple[OverrideAudit, ...] = ()


@dataclass
class GroupGeneratedModel(GeneratedModel):
    group_evidence: dict[str, Any] | None = None
    selection_source: str | None = None


def prepare_model_groups(
    groups: list[list[dict[str, Any]] | SelectedModelGroup],
    codex_index: dict[str, dict[str, Any]],
    model_overrides: Mapping[str, ModelOverride] | None = None,
) -> list[PreparedModelGroup]:
    overrides = model_overrides or {}
    prepared: list[PreparedModelGroup] = []

    for selected in groups:
        if isinstance(selected, SelectedModelGroup):
            rows = selected.rows
            selection_source = selected.selection_source
        else:
            rows = tuple(selected)
            selection_source = None

        aggregate = aggregate_model_group(list(rows), codex_index)
        override = overrides.get(aggregate.model_name)
        evidence = aggregate
        override_audit: tuple[OverrideAudit, ...] = ()
        if override is not None:
            evidence, override_audit = apply_model_override(aggregate, override)

        prepared.append(
            PreparedModelGroup(
                rows=rows,
                evidence=evidence,
                selection_source=selection_source,
                model_override=override,
                override_audit=override_audit,
            )
        )
    return prepared


def _json_value(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _group_evidence_payload(
    group: ModelGroupEvidence,
    override_audit: tuple[OverrideAudit, ...] = (),
) -> dict[str, Any]:
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
        "configured_overrides": {
            audit.field: {
                "source": audit.source,
                "configured_value": _json_value(audit.configured_value),
                "original": {
                    "state": audit.original_state,
                    "value": _json_value(audit.original_value),
                },
                "effective": {
                    "state": audit.effective_state,
                    "value": _json_value(audit.effective_value),
                },
            }
            for audit in override_audit
        },
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


def _wrap(
    model: GeneratedModel,
    prepared: PreparedModelGroup,
) -> GroupGeneratedModel:
    return GroupGeneratedModel(
        entry=model.entry,
        provenance=model.provenance,
        canonical_model=model.canonical_model,
        template_slug=model.template_slug,
        kind=model.kind,
        notes=model.notes,
        group_evidence=_group_evidence_payload(
            prepared.evidence,
            prepared.override_audit,
        ),
        selection_source=prepared.selection_source,
    )


def _legacy_single_row_is_safe(
    prepared: PreparedModelGroup,
    codex_index: dict[str, dict[str, Any]],
) -> bool:
    if len(prepared.rows) != 1 or prepared.override_audit:
        return False
    legacy_slug, _canonical = resolve_template(prepared.rows[0], codex_index)
    group = prepared.evidence
    if group.kind == "exact":
        return legacy_slug == group.template_slug
    return legacy_slug is None


def _override_sources(
    prepared: PreparedModelGroup,
    *fields: str,
) -> tuple[str, ...]:
    wanted = set(fields)
    return tuple(
        audit.source for audit in prepared.override_audit if audit.field in wanted
    )


def _source_or_default(
    prepared: PreparedModelGroup,
    fields: tuple[str, ...],
    default: str,
) -> str:
    sources = _override_sources(prepared, *fields)
    if not sources:
        return default
    return "config override/dependency closure: " + ", ".join(sources)


def _exact_retained_source(prepared: PreparedModelGroup, source: str) -> str:
    template = prepared.evidence.template_slug
    assert template is not None
    return f"codex:exact-template:{template}; compatibility retained by {source}"


def _apply_exact_group_capability_denials(
    entry: dict[str, Any],
    prepared: PreparedModelGroup,
    provenance: dict[str, str],
) -> None:
    group = prepared.evidence
    reasoning = group.capabilities["supports_reasoning"]
    if reasoning.state == "denied":
        reasoning_sources = _override_sources(prepared, "supports_reasoning")
        if reasoning_sources:
            level_source = default_source = summary_source = (
                "config override/dependency closure: " + ", ".join(reasoning_sources)
            )
        else:
            level_source = (
                "codex:exact-template downgraded by LiteLLM model-group supports_reasoning=false"
            )
            default_source = "derived: disabled by LiteLLM model-group reasoning denial"
            summary_source = (
                "codex:exact-template downgraded by LiteLLM model-group reasoning denial"
            )
        if isinstance(entry.get("supported_reasoning_levels"), list):
            entry["supported_reasoning_levels"] = []
            provenance["supported_reasoning_levels"] = level_source
        if "default_reasoning_level" in entry:
            entry["default_reasoning_level"] = None
            provenance["default_reasoning_level"] = default_source
        if entry.get("supports_reasoning_summary_parameter") is True:
            entry["supports_reasoning_summary_parameter"] = False
            provenance["supports_reasoning_summary_parameter"] = summary_source

    audio = group.capabilities["supports_audio_input"]
    if audio.state == "denied" and "audio" in entry.get("input_modalities", []):
        entry["input_modalities"] = [
            modality for modality in entry["input_modalities"] if modality != "audio"
        ]
        provenance["input_modalities"] = _source_or_default(
            prepared,
            ("supports_audio_input",),
            "codex:exact-template downgraded by LiteLLM model-group supports_audio_input=false",
        )

    parallel = group.capabilities["supports_parallel_function_calling"]
    functions = group.capabilities["supports_function_calling"]
    if (
        parallel.state == "denied" or functions.state == "denied"
    ) and entry.get("supports_parallel_tool_calls") is True:
        entry["supports_parallel_tool_calls"] = False
        provenance["supports_parallel_tool_calls"] = _source_or_default(
            prepared,
            ("supports_function_calling", "supports_parallel_function_calling"),
            "codex:exact-template downgraded by LiteLLM model-group function-calling capability denial",
        )


def _apply_exact_reasoning_override(
    entry: dict[str, Any],
    prepared: PreparedModelGroup,
    provenance: dict[str, str],
) -> None:
    override = prepared.model_override
    if override is None or override.reasoning_effort_levels is None:
        return
    levels = entry.get("supported_reasoning_levels")
    if not isinstance(levels, list):
        return

    evidence = prepared.evidence.reasoning_efforts
    source = f"config:model_overrides.{prepared.evidence.model_name}.reasoning_effort_levels"
    if evidence.state == "denied":
        entry["supported_reasoning_levels"] = []
        if "default_reasoning_level" in entry:
            entry["default_reasoning_level"] = None
            provenance["default_reasoning_level"] = (
                "effective model-group reasoning denial after " + source
            )
        provenance["supported_reasoning_levels"] = (
            "effective model-group reasoning denial after " + source
        )
        return
    if evidence.state != "known":
        return

    allowed = set(evidence.values)
    filtered = [
        item
        for item in levels
        if isinstance(item, dict) and item.get("effort") in allowed
    ]
    if filtered != levels:
        entry["supported_reasoning_levels"] = filtered
    provenance["supported_reasoning_levels"] = (
        "codex:exact-template intersected with " + source
    )
    default = entry.get("default_reasoning_level")
    allowed_defaults = {
        item.get("effort") for item in filtered if isinstance(item, dict)
    }
    if default not in allowed_defaults:
        entry["default_reasoning_level"] = (
            filtered[0].get("effort") if filtered else None
        )
        provenance["default_reasoning_level"] = "derived after " + source


def _repair_exact_override_provenance(
    entry: dict[str, Any],
    prepared: PreparedModelGroup,
    provenance: dict[str, str],
    notes: list[str],
) -> None:
    override = prepared.model_override
    if override is None:
        return
    model_name = prepared.evidence.model_name

    if override.supports_vision is not None:
        source = f"config:model_overrides.{model_name}.supports_vision"
        notes[:] = [note for note in notes if note != "LiteLLM confirms vision support"]
        if override.supports_vision:
            if "image" in entry.get("input_modalities", []):
                provenance["input_modalities"] = _exact_retained_source(prepared, source)
            notes.append("Configured override confirms vision support")

    if override.supports_audio_input is True and "audio" in entry.get("input_modalities", []):
        source = f"config:model_overrides.{model_name}.supports_audio_input"
        provenance["input_modalities"] = _exact_retained_source(prepared, source)

    if override.supported_openai_params is not None:
        source = f"config:model_overrides.{model_name}.supported_openai_params"
        params = set(override.supported_openai_params)

        if "verbosity" in params:
            if entry.get("support_verbosity") is True:
                provenance["support_verbosity"] = _exact_retained_source(prepared, source)
                if "default_verbosity" in entry:
                    provenance["default_verbosity"] = _exact_retained_source(prepared, source)
        else:
            if provenance.get("support_verbosity") == (
                "LiteLLM supported_openai_params (verbosity absent)"
            ):
                provenance["support_verbosity"] = source
            if provenance.get("default_verbosity") == "derived: verbosity disabled":
                provenance["default_verbosity"] = "derived after " + source

        if "parallel_tool_calls" in params:
            if entry.get("supports_parallel_tool_calls") is True:
                provenance["supports_parallel_tool_calls"] = _exact_retained_source(
                    prepared,
                    source,
                )
        elif provenance.get("supports_parallel_tool_calls") == (
            "LiteLLM supported_openai_params (parallel_tool_calls absent)"
        ):
            provenance["supports_parallel_tool_calls"] = source

        notes[:] = [
            note
            for note in notes
            if note
            not in {
                "LiteLLM confirms verbosity transport parameter",
                "LiteLLM confirms parallel_tool_calls transport parameter",
            }
        ]
        if "verbosity" in params:
            notes.append("Configured override confirms verbosity transport parameter")
        if "parallel_tool_calls" in params:
            notes.append("Configured override confirms parallel_tool_calls transport parameter")


def _repair_foreign_override_provenance(
    model: GeneratedModel,
    prepared: PreparedModelGroup,
) -> None:
    override = prepared.model_override
    if override is None:
        return
    model_name = prepared.evidence.model_name

    if override.max_input_tokens is not None:
        source = f"config:model_overrides.{model_name}.max_input_tokens"
        for field in ("context_window", "max_context_window"):
            if field in model.entry:
                model.provenance[field] = source

    if override.supports_vision is not None or override.supports_audio_input is not None:
        sources = _override_sources(
            prepared,
            "supports_vision",
            "supports_audio_input",
        )
        if "input_modalities" in model.entry and sources:
            model.provenance["input_modalities"] = ", ".join(sources)

    reasoning_sources = _override_sources(
        prepared,
        "supports_reasoning",
        "reasoning_effort_levels",
        "supported_openai_params",
    )
    if "supported_reasoning_levels" in model.entry and reasoning_sources:
        model.provenance["supported_reasoning_levels"] = ", ".join(reasoning_sources)

    if override.supported_openai_params is not None:
        source = f"config:model_overrides.{model_name}.supported_openai_params"
        for field in ("support_verbosity", "default_verbosity"):
            if field in model.entry:
                model.provenance[field] = source

    parallel_sources = _override_sources(
        prepared,
        "supports_function_calling",
        "supports_parallel_function_calling",
        "supported_openai_params",
    )
    if "supports_parallel_tool_calls" in model.entry and parallel_sources:
        model.provenance["supports_parallel_tool_calls"] = (
            "effective model-group dependency closure after "
            + ", ".join(parallel_sources)
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
        return _wrap(model, prepared)

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
        _repair_exact_override_provenance(entry, prepared, provenance, notes)
        _apply_exact_group_capability_denials(entry, prepared, provenance)
        _apply_exact_reasoning_override(entry, prepared, provenance)
        notes.extend(f"Group disagreement: {item}" for item in group.disagreements)
        return GroupGeneratedModel(
            entry=entry,
            provenance=provenance,
            canonical_model=group.template_slug,
            template_slug=group.template_slug,
            kind="exact",
            notes=notes,
            group_evidence=_group_evidence_payload(group, prepared.override_audit),
            selection_source=prepared.selection_source,
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

    _repair_foreign_override_provenance(model, prepared)
    return _wrap(model, prepared)


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
