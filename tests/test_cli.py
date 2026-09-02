import pytest

from litellm_codex_models.cli import _format_value, build_parser


def test_explain_collapses_large_values_by_default():
    value = {"instructions_template": "x" * 1000}
    rendered = _format_value(value)
    assert rendered.startswith("<object, ")
    assert rendered.endswith(" bytes>")


def test_explain_full_keeps_large_values():
    value = {"instructions_template": "x" * 1000}
    assert '"instructions_template"' in _format_value(value, full=True)


def test_explain_parser_accepts_full():
    args = build_parser().parse_args(["explain", "--full", "some-model"])
    assert args.full is True
    assert args.model == "some-model"


def test_cli_version_does_not_require_config(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == "litellm-codex-models 0.2.1\n"
