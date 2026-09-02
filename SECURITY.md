# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security vulnerabilities or accidental secret exposure.

Use GitHub's private vulnerability reporting / security advisory flow for this repository:

https://github.com/AviBackToBlack/litellm-codex-models/security/advisories/new

When reporting a problem involving LiteLLM metadata, provide the smallest reproducer possible and redact API keys, tokens, internal URLs/hostnames, account identifiers, deployment identifiers, and unrelated model configuration.

## Sensitive-data policy

Real `/v1/model/info` responses can contain environment-specific metadata. They must not be committed as fixtures. Tests should use synthetic, minimal fixtures containing only fields required to exercise the behavior under test.
