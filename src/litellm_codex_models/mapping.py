from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .errors import AppError


REASONING_DESCRIPTIONS = {
    "none": "No reasoning effort",
    "minimal": "Minimal reasoning",
    "low": "Fast responses with lighter reasoning",
    "medium": "Balances speed and reasoning depth for everyday tasks",
    "high": "Greater reasoning depth for complex problems",
    "xhigh": "Extra high reasoning depth for complex problems",
    "max": "Maximum reasoning depth for the hardest problems",
}

EFFORT_FLAG_MAP = {
    "none": "supports_none_reasoning_effort",
    "minimal": "supports_minimal_reasoning_effort",
    "low": "supports_low_reasoning_effort",
    "xhigh": "supports_xhigh_reasoning_effort",
    "max": "supports_max_reasoning_effort",
}

PROVIDER_PREFIXES = {
    "openai",
    "azure",
    "azure_ai",
    "anthropic",
    "bedrock",
    "bedrock_converse",
    "vertex_ai",
    "vertex_ai_beta",
    "gemini",
    "xai",
}


@dataclass
class GeneratedModel:
    entry: dict[str, Any]
    provenance: dict[str, str]
    canonical_model: str
    template_slug: str | None
    kind: str
    notes: list[str]


def _normalize_candidate(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    value = value.strip()
    if "/" in value:
        prefix, tail = value.split("/", 1)
        if prefix in PROVIDER_PREFIXES and tail:
            value = tail
    for region in ("us.", "eu.", "apac.", "global."):
        if value.startswith(region):
            value = value[len(region):]
            break
    if value.startswith("openai."):
        value = value[len("openai."):]
    return value or None


def canonical_candidates(row: dict[str, Any]) -> list[str]:
    params = row.get("litellm_params") or {}
    info = row.get("model_info") or {}
    raw = [
        info.get("base_model"),
        params.get("base_model"),
        params.get("model"),
        row.get("model_name"),
    ]
    result: list[str] = []
    for value in raw:
        candidate = _normalize_candidate(value)
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def resolve_template(row: dict[str, Any], codex_index: dict[str, dict[str, Any]]) -> tuple[str | None, str]:
    candidates = canonical_candidates(row)
    for candidate in candidates:
        if candidate in codex_index:
            return candidate, candidate
    canonical = candidates[0] if candidates else str(row.get("model_name") or "unknown")
    return None, canonical


def _params(row: dict[str, Any]) -> set[str]:
    values = (row.get("model_info") or {}).get("supported_openai_params") or []
    return {x for x in values if isinstance(x, str)}


def _modalities(row: dict[str, Any]) -> list[str]:
    info = row.get("model_info") or {}
    result = ["text"]
    if info.get("supports_vision") is True:
        result.append("image")
    if info.get("supports_audio_input") is True:
        result.append("audio")
    return result


def _reasoning_presets_foreign(row: dict[str, Any]) -> list[dict[str, str]]:
    info = row.get("model_info") or {}
    if info.get("supports_reasoning") is not True:
        return []
    params = _params(row)
    if "reasoning_effort" not in params:
        return []
    efforts = [effort for effort, flag in EFFORT_FLAG_MAP.items() if info.get(flag) is True]
    return [
        {"effort": effort, "description": REASONING_DESCRIPTIONS[effort]}
        for effort in efforts
    ]


def _restrict_exact_reasoning(entry: dict[str, Any], row: dict[str, Any], provenance: dict[str, str]) -> None:
    info = row.get("model_info") or {}
    levels = entry.get("supported_reasoning_levels")
    if not isinstance(levels, list):
        return
    denied = {effort for effort, flag in EFFORT_FLAG_MAP.items() if info.get(flag) is False}
    if not denied:
        return
    filtered = [item for item in levels if not (isinstance(item, dict) and item.get("effort") in denied)]
    if filtered != levels:
        entry["supported_reasoning_levels"] = filtered
        provenance["supported_reasoning_levels"] = "codex:exact-template intersected with explicit LiteLLM denials"
        default = entry.get("default_reasoning_level")
        if default in denied:
            entry["default_reasoning_level"] = filtered[0]["effort"] if filtered else None
            provenance["default_reasoning_level"] = "derived: adjusted after LiteLLM reasoning-effort denial"


def _overlay_exact(entry: dict[str, Any], row: dict[str, Any], provenance: dict[str, str], notes: list[str]) -> None:
    info = row.get("model_info") or {}
    params = _params(row)
    if info.get("supports_vision") is False and "image" in entry.get("input_modalities", []):
        entry["input_modalities"] = [x for x in entry["input_modalities"] if x != "image"]
        provenance["input_modalities"] = "codex:exact-template downgraded by LiteLLM supports_vision=false"
    elif info.get("supports_vision") is True:
        notes.append("LiteLLM confirms vision support")
    if "support_verbosity" in entry and info.get("supported_openai_params") is not None:
        if "verbosity" not in params and entry.get("support_verbosity") is True:
            entry["support_verbosity"] = False
            entry["default_verbosity"] = None
            provenance["support_verbosity"] = "LiteLLM supported_openai_params (verbosity absent)"
            provenance["default_verbosity"] = "derived: verbosity disabled"
        elif "verbosity" in params:
            notes.append("LiteLLM confirms verbosity transport parameter")
    if "supports_parallel_tool_calls" in entry and info.get("supported_openai_params") is not None:
        if "parallel_tool_calls" not in params:
            entry["supports_parallel_tool_calls"] = False
            provenance["supports_parallel_tool_calls"] = "LiteLLM supported_openai_params (parallel_tool_calls absent)"
        else:
            notes.append("LiteLLM confirms parallel_tool_calls transport parameter")
    if info.get("supports_web_search") is False and entry.get("supports_search_tool") is True:
        entry["supports_search_tool"] = False
        provenance["supports_search_tool"] = "codex:exact-template downgraded by LiteLLM supports_web_search=false"
    _restrict_exact_reasoning(entry, row, provenance)
    max_input = info.get("max_input_tokens")
    if isinstance(max_input, int):
        notes.append(
            f"LiteLLM max_input_tokens={max_input} kept as validation evidence; Codex template context values preserved"
        )


def _build_foreign(row: dict[str, Any], canonical: str, fallback_prompt: str) -> GeneratedModel:
    entry: dict[str, Any] = {
        "slug": str(row["model_name"]),
        "display_name": str(row["model_name"]),
        "description": f"LiteLLM model backed by {canonical}.",
        "default_reasoning_level": None,
        "supported_reasoning_levels": [],
        "shell_type": "unified_exec",
        "visibility": "list",
        "supported_in_api": True,
        "priority": 99,
        "additional_speed_tiers": [],
        "service_tiers": [],
        "default_service_tier": None,
        "availability_nux": None,
        "upgrade": None,
        "model_messages": {"instructions_template": fallback_prompt, "instructions_variables": None},
        "include_skills_usage_instructions": False,
        "include_plugin_usage_instructions": False,
        "include_apps_usage_instructions": False,
        "supports_reasoning_summary_parameter": False,
        "default_reasoning_summary": "auto",
        "support_verbosity": False,
        "default_verbosity": None,
        "apply_patch_tool_type": None,
        "web_search_tool_type": "text",
        "truncation_policy": {"mode": "bytes", "limit": 10000},
        "supports_image_detail_original": False,
        "context_window": 272000,
        "max_context_window": 272000,
        "auto_compact_token_limit": None,
        "comp_hash": None,
        "effective_context_window_percent": 95,
        "experimental_supported_tools": [],
        "input_modalities": ["text"],
        "supports_search_tool": False,
        "use_responses_lite": False,
        "node_repl_auto_review_required": False,
        "node_repl_disabled": False,
        "auto_review_model_override": None,
        "model_specialty": None,
        "tool_mode": None,
        "multi_agent_version": None,
        "multi_agent_reasoning_effort": None,
    }
    provenance = {key: "codex:conservative-fallback" for key in entry}
    notes = [f"No exact Codex template for canonical model {canonical!r}"]
    info = row.get("model_info") or {}
    params = _params(row)
    provenance.update({
        "slug": "LiteLLM model_name",
        "display_name": "derived: LiteLLM model_name",
        "description": "derived: canonical model identity",
        "model_messages": "codex:version-matched-fallback-prompt",
    })
    max_input = info.get("max_input_tokens")
    if isinstance(max_input, int) and max_input > 0:
        entry["context_window"] = max_input
        entry["max_context_window"] = max_input
        provenance["context_window"] = "LiteLLM max_input_tokens (foreign-model approximation)"
        provenance["max_context_window"] = "LiteLLM max_input_tokens (foreign-model approximation)"
    else:
        notes.append("LiteLLM max_input_tokens is unavailable; using Codex fallback context_window=272000")
    entry["input_modalities"] = _modalities(row)
    provenance["input_modalities"] = "LiteLLM modality capability flags"
    supports_reasoning = info.get("supports_reasoning") is True
    levels = _reasoning_presets_foreign(row)
    entry["supported_reasoning_levels"] = levels
    entry["default_reasoning_level"] = None
    provenance["supported_reasoning_levels"] = "LiteLLM explicit reasoning-effort flags only"
    provenance["default_reasoning_level"] = "conservative: no foreign-model default"
    if supports_reasoning and not levels:
        notes.append("LiteLLM confirms reasoning but no explicit effort levels; none are advertised to Codex")
    entry["supports_reasoning_summary_parameter"] = False
    provenance["supports_reasoning_summary_parameter"] = "conservative: no direct LiteLLM evidence"
    entry["support_verbosity"] = "verbosity" in params
    entry["default_verbosity"] = None
    provenance["support_verbosity"] = "LiteLLM supported_openai_params"
    provenance["default_verbosity"] = "derived: no foreign-model default"
    if "parallel_tool_calls" in params:
        entry["supports_parallel_tool_calls"] = info.get("supports_function_calling") is True
        provenance["supports_parallel_tool_calls"] = "LiteLLM parallel_tool_calls + explicit supports_function_calling"
    if info.get("supports_web_search") is True:
        notes.append("LiteLLM advertises web search; Codex supports_search_tool remains disabled for foreign model")
    return GeneratedModel(entry, provenance, canonical, None, "foreign", notes)


def generate_model(
    row: dict[str, Any],
    codex_index: dict[str, dict[str, Any]],
    *,
    fallback_prompt: str | None = None,
) -> GeneratedModel:
    template_slug, canonical = resolve_template(row, codex_index)
    name = str(row.get("model_name") or "")
    if not name:
        raise AppError("Selected LiteLLM row has no model_name")
    if template_slug is not None:
        entry = deepcopy(codex_index[template_slug])
        provenance = {key: f"codex:exact-template:{template_slug}" for key in entry}
        notes: list[str] = []
        entry["slug"] = name
        provenance["slug"] = "LiteLLM model_name"
        if name != template_slug:
            entry["display_name"] = name
            provenance["display_name"] = "derived: LiteLLM alias"
            notes.append(f"Alias resolves to exact Codex template {template_slug}")
        _overlay_exact(entry, row, provenance, notes)
        return GeneratedModel(entry, provenance, canonical, template_slug, "exact", notes)
    if fallback_prompt is None:
        raise AppError("Foreign model generation requires the version-matched Codex fallback prompt")
    return _build_foreign(row, canonical, fallback_prompt)


def generate_catalog(
    rows: list[dict[str, Any]],
    codex_catalog: dict[str, Any],
    *,
    fallback_prompt: str | None = None,
) -> tuple[dict[str, Any], dict[str, GeneratedModel]]:
    index = {model["slug"]: model for model in codex_catalog["models"]}
    generated: list[dict[str, Any]] = []
    explanations: dict[str, GeneratedModel] = {}
    for row in rows:
        model = generate_model(row, index, fallback_prompt=fallback_prompt)
        generated.append(model.entry)
        explanations[model.entry["slug"]] = model
    return {"models": generated}, explanations
