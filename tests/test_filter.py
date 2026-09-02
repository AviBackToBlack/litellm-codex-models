import pytest

from litellm_codex_models.errors import AppError
from litellm_codex_models.litellm import select_models


def make(name, mode="chat"):
    return {"model_name": name, "model_info": {"mode": mode}}


def test_allowlist_is_exact_and_ordered():
    rows = [make("a"), make("b"), make("a-extra")]
    selected = select_models(rows, ("b", "a"), strict=True)
    assert [row["model_name"] for row in selected] == ["b", "a"]


def test_missing_model_is_error_in_strict_mode():
    with pytest.raises(AppError, match="not found"):
        select_models([make("a")], ("a", "missing"), strict=True)


def test_non_codex_mode_is_error_if_explicitly_selected():
    with pytest.raises(AppError, match="not Codex-eligible"):
        select_models([make("embed", "embedding")], ("embed",), strict=True)


def test_duplicate_model_name_is_rejected_in_v01():
    with pytest.raises(AppError, match="duplicate"):
        select_models([make("a"), make("a")], ("a",), strict=True)
