# Contributing

Thanks for contributing to `litellm-codex-models`.

## Development setup

Requires Python 3.11+.

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q src tests
```

Before opening a pull request, run the test suite and make sure the CLI still starts:

```bash
litellm-codex-models --version
litellm-codex-models --help
```

## Pull requests

- Keep changes focused and explain the compatibility or behavior change in the PR body.
- Add or update tests for behavior changes and regressions.
- Do not weaken conservative fallback behavior without explicit evidence from LiteLLM or the version-matched Codex catalog/schema.
- Do not commit API keys, generated local configuration, or other secrets.
- Repository CI and security checks must pass before merge.

## Security issues

Do not open a public issue for a suspected vulnerability. Follow the repository's `SECURITY.md` guidance or use GitHub private vulnerability reporting when available.
