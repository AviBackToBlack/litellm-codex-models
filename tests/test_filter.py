import pytest

from litellm_codex_models.errors import AppError
from litellm_codex_models.litellm import select_model_groups


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
