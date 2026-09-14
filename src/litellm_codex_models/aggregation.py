from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .errors import AppError
from .mapping import EFFORT_FLAG_MAP, REASONING_DESCRIPTIONS, canonical_candidates, resolve_template


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
    canonical_candidates: tuple[str, ...]
    supported_openai_params: tuple[str, ...] | None
    reasoning_efforts: tuple[str, ...] | None


@dataclass(frozen=True)
class ModelGroupEvidence:
    model_name: str
    kind: Literal["exact", "foreign"]
    canonical_model: str
    template_slug: str | None
    deployments: tuple[DeploymentEvidence, ...]
    capabilities: dict[str, BooleanEvidence]
    max_input_tokens: LimitEvidence
    max_output_tokens: LimitEvidence
    supported_openai_params: SetEvidence
    reasoning_efforts: SetEvidence
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


def _raw_boolean_token(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"


def _raw_limit_token(value: Any) -> str:
    normalized = _positive_int(value)
    return str(normalized) if normalized is not None else "unknown"


def _deployment_evidence(
    row: dict[str, Any], codex_index: dict[str, dict[str, Any]]
) -> DeploymentEvidence:
    template_slug, _ = resolve_template(row, codex_index)
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
        canonical_candidates=tuple(canonical_candidates(row)),
        supported_openai_params=_normalize_string_set(info.get("supported_openai_params")),
        reasoning_efforts=_deployment_reasoning_efforts(row),
    )


def _deployment_sort_key(deployment: DeploymentEvidence) -> tuple[str, ...]:
    return (
        deployment.provider or "",
        deployment.model or "",
        deployment.base_model or "",
        deployment.mode,
        deployment.template_slug or "",
        "\x1f".join(deployment.canonical_candidates),
        "\x1f".join(deployment.supported_openai_params or ()),
        "\x1f".join(deployment.reasoning_efforts or ()),
    )


def _collect_disagreements(
    rows: list[dict[str, Any]], deployments: tuple[DeploymentEvidence, ...]
) -> tuple[str, ...]:
    disagreements: list[str] = []

    template_tokens = {deployment.template_slug or "unresolved" for deployment in deployments}
    if len(template_tokens) > 1:
        disagreements.append(
            "exact-template identity: " + ", ".join(sorted(template_tokens))
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

    return tuple(sorted(disagreements))


def aggregate_model_group(
    rows: list[dict[str, Any]], codex_index: dict[str, dict[str, Any]]
) -> ModelGroupEvidence:
    if not rows:
        raise AppError("Cannot aggregate an empty LiteLLM model group")

    names = {_string(row.get("model_name")) for row in rows}
    if None in names or len(names) != 1:
        raise AppError("Model-group aggregation requires one non-empty shared model_name")
    model_name = next(iter(names))
    assert model_name is not None

    invalid_modes = sorted(
        {
            _string(_info(row).get("mode")) or "unknown"
            for row in rows
            if (_string(_info(row).get("mode")) or "unknown") not in ALLOWED_MODES
        }
    )
    if invalid_modes:
        raise AppError(
            f'Model group "{model_name}" contains non-Codex-eligible mode(s): '
            + ", ".join(invalid_modes)
        )

    deployments = tuple(
        sorted(
            (_deployment_evidence(row, codex_index) for row in rows),
            key=_deployment_sort_key,
        )
    )
    template_slugs = {deployment.template_slug for deployment in deployments}
    template_slug = (
        next(iter(template_slugs))
        if len(template_slugs) == 1 and None not in template_slugs
        else None
    )
    kind: Literal["exact", "foreign"] = "exact" if template_slug else "foreign"
    canonical_model = template_slug if template_slug is not None else model_name

    capabilities = {
        field: aggregate_boolean(rows, field) for field in CAPABILITY_FIELDS
    }
    max_input_tokens = aggregate_limit(rows, "max_input_tokens")
    max_output_tokens = aggregate_limit(rows, "max_output_tokens")
    supported_openai_params = aggregate_supported_openai_params(rows)
    reasoning_efforts = aggregate_reasoning_efforts(rows)

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
        disagreements=_collect_disagreements(rows, deployments),
        foreign_synthesis_blockers=tuple(blockers),
    )
