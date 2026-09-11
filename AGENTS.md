# AGENTS.md

This file contains repository-wide instructions for coding agents and automation.

## Project intent

`litellm-codex-models` generates a small Codex `models.json` from LiteLLM `/v1/model/info` while preserving Codex-owned semantics. Prefer conservative, evidence-based compatibility decisions over guessed capabilities.

## Development commands

```bash
python -m pip install -e ".[test]"
python -m pytest -q
python -m compileall -q src tests
```

Smoke-test the CLI after behavior or packaging changes:

```bash
litellm-codex-models --version
litellm-codex-models --help
```

## Engineering constraints

- Python 3.11+ is supported; CI also exercises the latest supported Python.
- Keep runtime dependencies at zero unless there is a strong, documented reason to add one.
- Exact Codex template matches inherit Codex semantics; do not replace Codex-owned fields with guesses from LiteLLM metadata.
- For foreign models, only explicit LiteLLM capability evidence may enable features. Unknown values must not become implicit `true`.
- Version-matched Codex catalog, prompt, and Rust schema resources must stay aligned.
- Preserve fail-closed behavior for schema drift and compatibility uncertainty.
- Add regression tests for bug fixes and compatibility-rule changes.

## Repository safety

- Do not commit secrets, local API keys, generated private configuration, or credentials.
- Do not bypass required CI/security checks to land a change.
- Do not modify repository governance, release, or security policy unless the task explicitly requires it.
- Keep GitHub Actions dependencies pinned to full commit SHAs with a human-readable version comment.

## Documentation

Update README/help text when user-visible behavior, configuration, installation, or compatibility policy changes.
