# Pull Request

## What does this change?

<!-- Summary of the change and motivation. Link related issues. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / enhancement
- [ ] Documentation
- [ ] CI / tooling
- [ ] Refactoring (no behavior change)

## Safety checklist

- [ ] No real LiteLLM payloads, internal URLs/hostnames, API keys, tokens, or other environment-specific secrets are included
- [ ] Exact Codex model matches still inherit from the version-matched Codex catalog
- [ ] LiteLLM `null` / unknown capability metadata is not treated as explicit support
- [ ] Foreign models do not inherit model-specific Codex donor metadata

## Validation

- [ ] `python -m pytest -q` passes
- [ ] `python -m compileall -q src tests` passes
- [ ] A wheel can be built and the installed CLI starts successfully

## Notes for the reviewer

<!-- Risky spots, compatibility assumptions, or anything needing extra scrutiny. -->
