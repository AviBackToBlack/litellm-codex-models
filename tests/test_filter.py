import pytest

from litellm_codex_models.errors import AppError
from litellm_codex_models.litellm import (
    select_model_groups,
    select_model_groups_with_provenance,
)


def make(name, mode="chat"):
    return {
        "model_name": name,
        "litellm_params": {"model": f"vendor/{name}"},
        "model_info": {"mode": mode},
    }


def test_allowlist_is_exact_and_ordered():
    rows = [make("a"), make("b"), make("a-extra")]
    selected = select_model_groups(rows, ("b", "a"), strict=True)
    assert [[row["model_name"] for row in group] for group in selected] == [["b"], ["a"]]


def test_missing_model_is_error_in_strict_mode():
    with pytest.raises(AppError, match="not found"):
        select_model_groups([make("a")], ("a", "missing"), strict=True)


def test_duplicate_model_name_is_selected_as_one_group():
    first = make("a")
    second = make("a")
    second["litellm_params"]["model"] = "vendor/a-second"

    selected = select_model_groups([first, second], ("a",), strict=True)

    assert len(selected) == 1
    assert selected[0] == [first, second]


def test_globs_expand_after_exact_entries_in_lexical_order():
    rows = [make("claude-z"), make("exact"), make("claude-a"), make("other")]
    selected = select_model_groups_with_provenance(
        rows,
        ("exact",),
        ("claude-*",),
        strict=True,
    )

    assert [group.model_name for group in selected] == ["exact", "claude-a", "claude-z"]
    assert [group.selection_source for group in selected] == [
        "exact:exact",
        "glob:claude-*",
        "glob:claude-*",
    ]


def test_first_selector_wins_deduplication_and_provenance():
    rows = [make("claude-a"), make("claude-b")]
    selected = select_model_groups_with_provenance(
        rows,
        ("claude-b",),
        ("claude-*", "*-b"),
        strict=True,
    )

    assert [group.model_name for group in selected] == ["claude-b", "claude-a"]
    assert [group.selection_source for group in selected] == [
        "exact:claude-b",
        "glob:claude-*",
    ]


def test_glob_matching_is_case_sensitive():
    rows = [make("Claude-A"), make("claude-a")]
    selected = select_model_groups_with_provenance(
        rows,
        (),
        ("claude-*",),
        strict=True,
    )

    assert [group.model_name for group in selected] == ["claude-a"]


def test_unmatched_glob_is_error_only_in_strict_mode():
    rows = [make("a")]
    with pytest.raises(AppError, match="matched no LiteLLM"):
        select_model_groups_with_provenance(rows, (), ("missing-*",), strict=True)

    assert select_model_groups_with_provenance(rows, (), ("missing-*",), strict=False) == []


def test_glob_expansion_is_independent_of_litellm_row_order():
    rows = [make("m-c"), make("m-a"), make("m-b")]
    forward = select_model_groups_with_provenance(rows, (), ("m-*",), strict=True)
    reverse = select_model_groups_with_provenance(list(reversed(rows)), (), ("m-*",), strict=True)

    assert [(g.model_name, g.selection_source) for g in forward] == [
        ("m-a", "glob:m-*"),
        ("m-b", "glob:m-*"),
        ("m-c", "glob:m-*"),
    ]
    assert [(g.model_name, g.selection_source) for g in reverse] == [
        (g.model_name, g.selection_source) for g in forward
    ]
