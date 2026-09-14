import pytest

from litellm_codex_models.aggregation import aggregate_model_group
from litellm_codex_models.errors import AppError


INDEX = {
    "gpt-5.6-sol": {},
    "gpt-5.6-luna": {},
}


def row(
    name="group",
    model="vendor/model-a",
    *,
    mode="chat",
    provider=None,
    base_model=None,
    **info,
):
    params = {
        "model": model,
        "base_model": base_model if base_model is not None else model,
    }
    if provider is not None:
        params["custom_llm_provider"] = provider
    model_info = {"mode": mode, "max_input_tokens": 200_000, **info}
    return {
        "model_name": name,
        "litellm_params": params,
        "model_info": model_info,
    }


def test_identical_exact_deployments_preserve_exact_identity():
    group = aggregate_model_group(
        [
            row("alias", "azure/gpt-5.6-sol"),
            row("alias", "azure/gpt-5.6-sol"),
        ],
        INDEX,
    )
    assert group.kind == "exact"
    assert group.template_slug == "gpt-5.6-sol"
    assert group.canonical_model == "gpt-5.6-sol"
    assert group.deployment_count == 2


def test_different_providers_can_resolve_to_same_exact_identity():
    group = aggregate_model_group(
        [
            row("alias", "azure/gpt-5.6-sol", provider="azure"),
            row("alias", "openai/gpt-5.6-sol", provider="openai"),
        ],
        INDEX,
    )
    assert group.kind == "exact"
    assert group.template_slug == "gpt-5.6-sol"
    assert [deployment.provider for deployment in group.deployments] == ["azure", "openai"]


def test_conflicting_exact_identities_fall_back_to_foreign_group():
    group = aggregate_model_group(
        [
            row("mixed", "openai/gpt-5.6-sol"),
            row("mixed", "openai/gpt-5.6-luna"),
        ],
        INDEX,
    )
    assert group.kind == "foreign"
    assert group.template_slug is None
    assert group.canonical_model == "mixed"
    assert any("exact-template identity" in item for item in group.disagreements)


def test_one_exact_and_one_unresolved_deployment_falls_back_to_foreign():
    group = aggregate_model_group(
        [
            row("mixed", "openai/gpt-5.6-sol"),
            row("mixed", "vendor/not-in-codex"),
        ],
        INDEX,
    )
    assert group.kind == "foreign"
    assert group.template_slug is None


def test_chat_and_responses_are_both_group_eligible():
    group = aggregate_model_group(
        [row(mode="chat"), row(model="vendor/model-b", mode="responses")],
        INDEX,
    )
    assert group.deployment_count == 2


def test_mixed_eligible_and_incompatible_mode_fails_closed():
    with pytest.raises(AppError, match="non-Codex-eligible"):
        aggregate_model_group(
            [row(mode="chat"), row(model="vendor/embed", mode="embedding")],
            INDEX,
        )


@pytest.mark.parametrize(
    ("values", "expected_state", "expected_value"),
    [
        ((True, True), "guaranteed", True),
        ((True, False), "denied", False),
        ((True, None), "unknown", None),
        ((False, None), "denied", False),
    ],
)
def test_boolean_capabilities_use_safe_tri_state(values, expected_state, expected_value):
    rows = [
        row(model=f"vendor/model-{index}", supports_vision=value)
        for index, value in enumerate(values)
    ]
    evidence = aggregate_model_group(rows, INDEX).capabilities["supports_vision"]
    assert evidence.state == expected_state
    assert evidence.value is expected_value


def test_context_and_output_limits_use_safe_minimum():
    group = aggregate_model_group(
        [
            row(
                model="vendor/small",
                max_input_tokens=100_000,
                max_output_tokens=8_000,
            ),
            row(
                model="vendor/large",
                max_input_tokens=1_000_000,
                max_output_tokens=32_000,
            ),
        ],
        INDEX,
    )
    assert group.max_input_tokens.state == "known"
    assert group.max_input_tokens.value == 100_000
    assert group.max_output_tokens.state == "known"
    assert group.max_output_tokens.value == 8_000


def test_unknown_foreign_context_is_retained_and_blocks_future_synthesis():
    group = aggregate_model_group(
        [
            row(model="vendor/known", max_input_tokens=100_000),
            row(model="vendor/unknown", max_input_tokens=None),
        ],
        INDEX,
    )
    assert group.kind == "foreign"
    assert group.max_input_tokens.state == "unknown"
    assert group.max_input_tokens.value is None
    assert group.foreign_synthesis_blockers == (
        "foreign multi-deployment synthesis requires max_input_tokens for every deployment",
    )


def test_supported_openai_params_are_intersected_deterministically():
    group = aggregate_model_group(
        [
            row(
                model="vendor/a",
                supported_openai_params=["verbosity", "reasoning_effort", "parallel_tool_calls"],
            ),
            row(
                model="vendor/b",
                supported_openai_params=["reasoning_effort", "parallel_tool_calls"],
            ),
        ],
        INDEX,
    )
    assert group.supported_openai_params.state == "known"
    assert group.supported_openai_params.values == (
        "parallel_tool_calls",
        "reasoning_effort",
    )


def test_unknown_supported_openai_params_do_not_inherit_other_deployment_values():
    group = aggregate_model_group(
        [
            row(model="vendor/a", supported_openai_params=["verbosity"]),
            row(model="vendor/b", supported_openai_params=None),
        ],
        INDEX,
    )
    assert group.supported_openai_params.state == "unknown"
    assert group.supported_openai_params.values == ()


def test_reasoning_efforts_are_intersected_in_codex_order():
    group = aggregate_model_group(
        [
            row(
                model="vendor/a",
                supports_reasoning=True,
                reasoning_effort_levels=["high", "low", "medium"],
            ),
            row(
                model="vendor/b",
                supports_reasoning=True,
                supports_medium_reasoning_effort=True,
                reasoning_effort_levels=["medium", "high"],
            ),
        ],
        INDEX,
    )
    assert group.reasoning_efforts.state == "known"
    assert group.reasoning_efforts.values == ("medium", "high")


def test_explicit_effort_denial_wins_over_positive_list_entry():
    group = aggregate_model_group(
        [
            row(
                model="vendor/a",
                reasoning_effort_levels=["medium", "high"],
            ),
            row(
                model="vendor/b",
                reasoning_effort_levels=["medium", "high"],
                supports_high_reasoning_effort=False,
            ),
        ],
        INDEX,
    )
    assert group.reasoning_efforts.state == "known"
    assert group.reasoning_efforts.values == ("medium",)


def test_unknown_reasoning_deployment_blocks_foreign_effort_advertisement():
    group = aggregate_model_group(
        [
            row(
                model="vendor/a",
                supports_reasoning=True,
                reasoning_effort_levels=["high"],
            ),
            row(model="vendor/b", supports_reasoning=True),
        ],
        INDEX,
    )
    assert group.reasoning_efforts.state == "unknown"
    assert group.reasoning_efforts.values == ()


def test_deployment_wide_reasoning_denial_has_precedence():
    group = aggregate_model_group(
        [
            row(model="vendor/a", reasoning_effort_levels=["high"]),
            row(
                model="vendor/b",
                supports_reasoning=False,
                reasoning_effort_levels=["high"],
            ),
        ],
        INDEX,
    )
    assert group.reasoning_efforts.state == "denied"
    assert group.reasoning_efforts.values == ()


def test_group_aggregation_is_fully_order_independent():
    rows = [
        row(
            model="vendor/a",
            provider="provider-a",
            max_input_tokens=120_000,
            max_output_tokens=16_000,
            supports_vision=True,
            supports_function_calling=True,
            supported_openai_params=["reasoning_effort", "parallel_tool_calls"],
            reasoning_effort_levels=["medium", "high"],
        ),
        row(
            model="vendor/b",
            provider="provider-b",
            max_input_tokens=200_000,
            max_output_tokens=8_000,
            supports_vision=None,
            supports_function_calling=False,
            supported_openai_params=["reasoning_effort"],
            reasoning_effort_levels=["high"],
        ),
    ]
    forward = aggregate_model_group(rows, INDEX)
    reverse = aggregate_model_group(list(reversed(rows)), INDEX)
    assert forward == reverse
    assert forward.disagreements == tuple(sorted(forward.disagreements))
