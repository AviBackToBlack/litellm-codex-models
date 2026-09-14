from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping

from .errors import AppError
from .mapping import EFFORT_FLAG_MAP, REASONING_DESCRIPTIONS, canonical_candidates


ALLOWED_MODES = frozenset({"chat", "responses"})
CAPABILITY_FIELDS = (
    "supports_vision",
    "supports_audio_input",
    "supports_function_calling",
    "supports_parallel_function_calling",
    "supports_web_search",
    "supports_reasoning",
)


@dataclass(frozen=True)
class BooleanEvidence:
    state: Literal["guaranteed", "denied", "unknown"]
    value: bool | None
    rule: str = "all true / any false / otherwise unknown"


@dataclass(frozen=True)
class SetEvidence:
    state: Literal["known", "denied", "unknown"]
    values: tuple[str, ...]
    rule: str


@dataclass(frozen=True)
class LimitEvidence:
    state: Literal["known", "unknown"]
    value: int | None
    rule: str = "minimum positive value when every deployment is known"


@dataclass(frozen=True)
class DeploymentEvidence:
    provider: str | None
    model: str | None
    base_model: str | None
    mode: str
    template_slug: str | None
    template_matches: tuple[str, ...]
    canonical_candidates: tuple[str, ...]
    supported_openai_params: tuple[str, ...] | None
    reasoning_efforts: tuple[str, ...] | None
    reasoning_effort_evidence: tuple[tuple[str, str], ...]
    capability_evidence: tuple[tuple[str, str], ...]
    max_input_tokens: int | None
    max_output_tokens: int | None


@dataclass(frozen=True)
class ModelGroupEvidence:
    model_name: str
    kind: Literal["exact", "foreign"]
    canonical_model: str
    template_slug: str | None
    deployments: tuple[DeploymentEvidence, ...]
    capabilities: Mapping[str, BooleanEvidence]
    max_input_tokens: LimitEvidence
    max_output_tokens: LimitEvidence
    supported_openai_params: SetEvidence
    reasoning_efforts: SetEvidence
    denied_reasoning_efforts: tuple[str, ...]
    disagreements: tuple[str, ...]
    foreign_synthesis_blockers: tuple[str, ...]

    @property
    def deployment_count(self) -> int:
        return len(self.deployments)


def _info(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("model_info")
    return value if isinstance(value, dict) else {}


def _params(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("litellm_params")
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    return None


def _provider(row: dict[str, Any]) -> str | None:
    params = _params(row)
    explicit = _string(params.get("custom_llm_provider"))
    if explicit:
        return explicit
    model = _string(params.get("model"))
    if model and "/" in model:
        prefix, _ = model.split("/", 1)
        return prefix or None
    return None


def _normalize_string_set(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    return tuple(sorted({item for item in value if isinstance(item, str)}))


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def aggregate_boolean(rows: list[dict[str, Any]], field: str) -> BooleanEvidence:
    values = [_info(row).get(field) for row in rows]
    if any(value is False for value in values):
        return BooleanEvidence("denied", False)
    if values and all(value is True for value in values):
        return BooleanEvidence("guaranteed", True)
    return BooleanEvidence("unknown", None)


def aggregate_limit(rows: list[dict[str, Any]], field: str) -> LimitEvidence:
    values = [_positive_int(_info(row).get(field)) for row in rows]
    if not values or any(value is None for value in values):
        return LimitEvidence("unknown", None)
    return LimitEvidence("known", min(value for value in values if value is not None))


def aggregate_supported_openai_params(rows: list[dict[str, Any]]) -> SetEvidence:
    per_deployment = [
        _normalize_string_set(_info(row).get("supported_openai_params")) for row in rows
    ]
    if not per_deployment or any(value is None for value in per_deployment):
        return SetEvidence(
            "unknown",
            (),
            "intersection only when every deployment has an explicit parameter list",
        )

    intersection = set(per_deployment[0] or ())
    for value in per_deployment[1:]:
        intersection.intersection_update(value or ())
    return SetEvidence(
        "known",
        tuple(sorted(intersection)),
        "intersection of explicit deployment parameter lists",
    )


def _deployment_reasoning_efforts(row: dict[str, Any]) -> tuple[str, ...] | None:
    info = _info(row)
    explicit_levels = info.get("reasoning_effort_levels")
    has_positive_metadata = isinstance(explicit_levels, (list, tuple))
    confirmed: set[str] = set()

    if has_positive_metadata:
        confirmed.update(
            effort
            for effort in explicit_levels
            if isinstance(effort, str) and effort in REASONING_DESCRIPTIONS
        )

    for effort, flag in EFFORT_FLAG_MAP.items():
        if info.get(flag) is True:
            confirmed.add(effort)
            has_positive_metadata = True
        elif info.get(flag) is False:
            confirmed.discard(effort)

    if not has_positive_metadata:
        return None
    return tuple(effort for effort in REASONING_DESCRIPTIONS if effort in confirmed)


def _deployment_reasoning_effort_evidence(
    row: dict[str, Any],
) -> tuple[tuple[str, str], ...]:
    info = _info(row)
    explicit_levels = info.get("reasoning_effort_levels")
    listed = {
        effort
        for effort in explicit_levels
        if isinstance(effort, str) and effort in REASONING_DESCRIPTIONS
    } if isinstance(explicit_levels, (list, tuple)) else set()

    evidence: list[tuple[str, str]] = []
    for effort, flag in EFFORT_FLAG_MAP.items():
        raw_flag = info.get(flag)
        if raw_flag is False:
            token = "false"
        elif raw_flag is True or effort in listed:
            token = "true"
        else:
            token = "unknown"
        evidence.append((effort, token))
    return tuple(evidence)


def aggregate_reasoning_efforts(rows: list[dict[str, Any]]) -> SetEvidence:
    if any(_info(row).get("supports_reasoning") is False for row in rows):
        return SetEvidence(
            "denied",
            (),
            "deployment-wide explicit supports_reasoning=false denies group reasoning",
        )

    per_deployment = [_deployment_reasoning_efforts(row) for row in rows]
    if not per_deployment or any(value is None for value in per_deployment):
        return SetEvidence(
            "unknown",
            (),
            "every deployment must provide explicit positive reasoning-effort metadata",
        )

    intersection = set(per_deployment[0] or ())
    for value in per_deployment[1:]:
        intersection.intersection_update(value or ())

    explicitly_denied = {
        effort
        for row in rows
        for effort, flag in EFFORT_FLAG_MAP.items()
        if _info(row).get(flag) is False
    }
    intersection.difference_update(explicitly_denied)
    return SetEvidence(
        "known",
        tuple(effort for effort in REASONING_DESCRIPTIONS if effort in intersection),
        "intersection of explicit deployment effort sets; explicit false removes an effort",
    )


def _denied_reasoning_efforts(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        effort
        for effort in REASONING_DESCRIPTIONS
        if any(_info(row).get(EFFORT_FLAG_MAP[effort]) is False for row in rows)
    )


def _raw_boolean_token(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def _raw_limit_token(value: Any) -> str:
    normalized = _positive_int(value)
    return str(normalized) if normalized is not None else "unknown"


def _identity_candidates(
    row: dict[str, Any], *, include_group_alias: bool
) -> tuple[str, ...]:
    if include_group_alias:
        return tuple(canonical_candidates(row))
    deployment_only = dict(row)
    deployment_only["model_name"] = None
    return tuple(canonical_candidates(deployment_only))


def _template_matches(
    candidates: tuple[str, ...], codex_index: dict[str, dict[str, Any]]
) -> tuple[str, ...]:
    return tuple(candidate for candidate in candidates if candidate in codex_index)


def _deployment_evidence(
    row: dict[str, Any],
    codex_index: dict[str, dict[str, Any]],
    *,
    include_group_alias: bool,
) -> DeploymentEvidence:
    candidates = _identity_candidates(row, include_group_alias=include_group_alias)
    matches = _template_matches(candidates, codex_index)
    template_slug = matches[0] if len(matches) == 1 else None
    params = _params(row)
    info = _info(row)
    mode = _string(info.get("mode")) or "unknown"
    base_model = _string(info.get("base_model")) or _string(params.get("base_model"))
    return DeploymentEvidence(
        provider=_provider(row),
        model=_string(params.get("model")),
        base_model=base_model,
        mode=mode,
        template_slug=template_slug,
        template_matches=matches,
        canonical_candidates=candidates,
        supported_openai_params=_normalize_string_set(info.get("supported_openai_params")),
        reasoning_efforts=_deployment_reasoning_efforts(row),
        reasoning_effort_evidence=_deployment_reasoning_effort_evidence(row),
        capability_evidence=tuple(
            (field, _raw_boolean_token(info.get(field))) for field in CAPABILITY_FIELDS
        ),
        max_input_tokens=_positive_int(info.get("max_input_tokens")),
        max_output_tokens=_positive_int(info.get("max_output_tokens")),
    )


def _deployment_sort_key(deployment: DeploymentEvidence) -> tuple[str, ...]:
    params_token = (
        "<unknown>"
        if deployment.supported_openai_params is None
        else "<known>:" + "\x1f".join(deployment.supported_openai_params)
    )
    reasoning_token = (
        "<unknown>"
        if deployment.reasoning_efforts is None
        else "<known>:" + "\x1f".join(deployment.reasoning_efforts)
    )
    reasoning_evidence_token = "\x1f".join(
        f"{effort}={value}" for effort, value in deployment.reasoning_effort_evidence
    )
    return (
        deployment.provider or "",
        deployment.model or "",
        deployment.base_model or "",
        deployment.mode,
        deployment.template_slug or "",
        "\x1f".join(deployment.template_matches),
        "\x1f".join(deployment.canonical_candidates),
        params_token,
        reasoning_token,
        reasoning_evidence_token,
        "\x1f".join(f"{field}={value}" for field, value in deployment.capability_evidence),
        str(deployment.max_input_tokens or 0),
        str(deployment.max_output_tokens or 0),
    )


def _identity_token(deployment: DeploymentEvidence) -> str:
    if deployment.template_matches:
        return "[" + ",".join(deployment.template_matches) + "]"
    return "unresolved"


def _candidate_set_token(deployment: DeploymentEvidence) -> str:
    normalized = tuple(sorted(set(deployment.canonical_candidates)))
    return "[" + ",".join(normalized) + "]"


def _exact_identity_survives(deployments: tuple[DeploymentEvidence, ...]) -> bool:
    return bool(deployments) and all(
        deployment.template_slug is not None for deployment in deployments
    ) and len({deployment.template_slug for deployment in deployments}) == 1


def _collect_disagreements(
    rows: list[dict[str, Any]], deployments: tuple[DeploymentEvidence, ...]
) -> tuple[str, ...]:
    disagreements: list[str] = []

    unique_template_slugs = {deployment.template_slug for deployment in deployments}
    has_ambiguous_deployment = any(
        len(deployment.template_matches) > 1 for deployment in deployments
    )
    if has_ambiguous_deployment or len(unique_template_slugs) > 1:
        template_tokens = sorted({_identity_token(deployment) for deployment in deployments})
        disagreements.append("exact-template identity: " + ", ".join(template_tokens))

    if not _exact_identity_survives(deployments):
        candidate_tokens = sorted(
            {_candidate_set_token(deployment) for deployment in deployments}
        )
        if len(candidate_tokens) > 1:
            disagreements.append(
                "canonical identity candidates: " + " | ".join(candidate_tokens)
            )

    for field in CAPABILITY_FIELDS:
        tokens = {_raw_boolean_token(_info(row).get(field)) for row in rows}
        if len(tokens) > 1:
            disagreements.append(f"{field}: " + ", ".join(sorted(tokens)))

    for field in ("max_input_tokens", "max_output_tokens"):
        tokens = {_raw_limit_token(_info(row).get(field)) for row in rows}
        if len(tokens) > 1:
            disagreements.append(f"{field}: " + ", ".join(sorted(tokens)))

    param_tokens = {
        "unknown"
        if deployment.supported_openai_params is None
        else "[" + ",".join(deployment.supported_openai_params) + "]"
        for deployment in deployments
    }
    if len(param_tokens) > 1:
        disagreements.append("supported_openai_params: " + ", ".join(sorted(param_tokens)))

    reasoning_tokens = {
        "unknown"
        if deployment.reasoning_efforts is None
        else "[" + ",".join(deployment.reasoning_efforts) + "]"
        for deployment in deployments
    }
    if len(reasoning_tokens) > 1:
        disagreements.append("reasoning_efforts: " + ", ".join(sorted(reasoning_tokens)))

    for effort in REASONING_DESCRIPTIONS:
        tokens = {
            dict(deployment.reasoning_effort_evidence)[effort]
            for deployment in deployments
        }
        if len(tokens) > 1:
            disagreements.append(
                f"reasoning effort {effort}: " + ", ".join(sorted(tokens))
            )

    return tuple(sorted(disagreements))


def aggregate_model_group(
    rows: list[dict[str, Any]], codex_index: dict[str, dict[str, Any]]
) -> ModelGroupEvidence:
    if not rows:
        raise AppError("Cannot aggregate an empty LiteLLM model group")

    raw_names = [row.get("model_name") for row in rows]
    if (
        any(not isinstance(name, str) or not name.strip() for name in raw_names)
        or len(set(raw_names)) != 1
    ):
        raise AppError("Model-group aggregation requires one non-empty shared model_name")
    model_name = raw_names[0]
    assert isinstance(model_name, str)

    invalid_modes = sorted(
        {
            mode if isinstance(mode, str) and mode else "unknown"
            for row in rows
            if (mode := _info(row).get("mode")) not in ALLOWED_MODES
        }
    )
    if invalid_modes:
        raise AppError(
            f'Model group "{model_name}" contains non-Codex-eligible mode(s): '
            + ", ".join(repr(mode) for mode in invalid_modes)
        )

    include_group_alias = len(rows) == 1
    deployments = tuple(
        sorted(
            (
                _deployment_evidence(
                    row,
                    codex_index,
                    include_group_alias=include_group_alias,
                )
                for row in rows
            ),
            key=_deployment_sort_key,
        )
    )
    template_slug = (
        deployments[0].template_slug if _exact_identity_survives(deployments) else None
    )
    kind: Literal["exact", "foreign"] = "exact" if template_slug else "foreign"
    canonical_model = template_slug if template_slug is not None else model_name

    capabilities = MappingProxyType(
        {field: aggregate_boolean(rows, field) for field in CAPABILITY_FIELDS}
    )
    max_input_tokens = aggregate_limit(rows, "max_input_tokens")
    max_output_tokens = aggregate_limit(rows, "max_output_tokens")
    supported_openai_params = aggregate_supported_openai_params(rows)
    reasoning_efforts = aggregate_reasoning_efforts(rows)
    denied_reasoning_efforts = _denied_reasoning_efforts(rows)

    blockers: list[str] = []
    if kind == "foreign" and len(rows) > 1 and max_input_tokens.state != "known":
        blockers.append(
            "foreign multi-deployment synthesis requires max_input_tokens for every deployment"
        )

    return ModelGroupEvidence(
        model_name=model_name,
        kind=kind,
        canonical_model=canonical_model,
        template_slug=template_slug,
        deployments=deployments,
        capabilities=capabilities,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        supported_openai_params=supported_openai_params,
        reasoning_efforts=reasoning_efforts,
        denied_reasoning_efforts=denied_reasoning_efforts,
        disagreements=_collect_disagreements(rows, deployments),
        foreign_synthesis_blockers=tuple(blockers),
    )
