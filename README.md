# litellm-codex-models

Generate a small, version-aware Codex `models.json` from LiteLLM's rich `/v1/model/info` response.

The key design rule is **Codex template inheritance + LiteLLM capability evidence**:

- The config contains an ordered, exact `model_name` allowlist.
- Only LiteLLM `mode = chat` or `mode = responses` entries are eligible.
- If a LiteLLM deployment resolves to a model already present in the matching Codex catalog, the entire Codex entry is deep-cloned and the LiteLLM alias becomes its slug.
- Codex-specific fields (instructions, shell/tool modes, truncation, multi-agent metadata, etc.) stay owned by Codex.
- Explicit LiteLLM transport restrictions can downgrade an exact template; `null` means unknown and does not become `false`.
- Unknown/foreign models are built from conservative Codex fallback semantics, use the version-matched Codex fallback prompt, and are enriched only with explicit LiteLLM capability evidence.
- `explain` reports field provenance and important compatibility notes.

## Install

Requires Python 3.11+ and no third-party runtime dependencies.

### Stable release from GitHub

After the `v0.2.0` tag exists, install that exact release directly from GitHub:

```bash
python -m pip install "git+https://github.com/AviBackToBlack/litellm-codex-models.git@v0.2.0"
```

This is the recommended VCS install because it is reproducible.

### Latest `main`

To install the current development head:

```bash
python -m pip install "git+https://github.com/AviBackToBlack/litellm-codex-models.git"
```

To force-refresh an existing `main` install when the package version has not changed:

```bash
python -m pip install --upgrade --force-reinstall "git+https://github.com/AviBackToBlack/litellm-codex-models.git"
```

### Local checkout

For development from a clone:

```bash
python -m pip install -e ".[test]"
```

Verify the installed CLI:

```bash
litellm-codex-models --version
litellm-codex-models --help
```

The repository CI smoke-tests installation of the exact PR/push revision through a `pip` VCS URL, so `git+https://...` installation is continuously covered by the required `build` check.

## Configure

Copy `config.example.toml` to `litellm-codex-models.toml` and edit the exact allowlist:

```toml
models = [
  "gpt-5.6-sol",
  "claude-sonnet-5",
]

[filter]
strict = true

[litellm]
url = "https://litellm.example.com"
api_key_env = "LITELLM_API_KEY"

[codex]
binary = "codex"
version = "auto"

[output]
path = "models.json"
pretty = true
```

`version = "auto"` runs `codex --version` and fetches the catalog from the corresponding `rust-v<version>` tag in `openai/codex`. This avoids using a `main` catalog whose schema may not match the installed Codex binary.

## Commands

List every model in LiteLLM:

```bash
litellm-codex-models --config litellm-codex-models.toml list
```

Only the configured allowlist:

```bash
litellm-codex-models --config litellm-codex-models.toml list --configured
```

Generate:

```bash
litellm-codex-models --config litellm-codex-models.toml build
```

Explain one model:

```bash
litellm-codex-models --config litellm-codex-models.toml explain gpt-5.6-sol
```

Large values such as full instruction templates are summarized by default. Use
`explain --full MODEL` when the complete value is needed.

For offline/reproducible work, use saved inputs:

```bash
litellm-codex-models \
  --config litellm-codex-models.toml \
  build \
  --input litellm.json \
  --catalog-file codex-models.json \
  --codex-prompt-file codex-prompt.md \
  --codex-schema-file openai_models.rs \
  --output generated-models.json
```

Then point Codex at the result:

```toml
model_catalog_json = "/absolute/path/to/generated-models.json"
```

## Context-window policy

For an **exact Codex template match**, `context_window` and `max_context_window` remain the Codex values. LiteLLM `max_input_tokens` is treated as validation evidence because the two fields do not have identical semantics.

For a **foreign model** with no Codex template, the generator uses LiteLLM `max_input_tokens` as the best available approximation for both context fields and marks that provenance explicitly. This is intentionally visible in `explain` rather than hidden as an assumption.

## v0.2 highlights

- Model-specific Codex donor fields are never inherited by foreign models.
- The generic Codex fallback prompt comes from the same version-matched `rust-v<version>` tag.
- Reasoning effort levels are advertised only from explicit LiteLLM evidence: `reasoning_effort_levels` and/or explicit per-effort capability flags. Unknown values are ignored, and explicit `false` denials win.
- Generic reasoning support does not imply support for the Responses `reasoning.summary` parameter.
- Parallel tool calls require both the transport parameter and explicit function-calling support.
- `explain` collapses large instruction/message payloads by default; `--full` restores the complete dump.
- Foreign generation validates itself against the version-matched Rust `ModelInfo` schema. Newly required fields are copied only when their value is invariant across the whole Codex catalog; model-specific required fields fail closed instead of leaking a donor value.
- The schema parser handles rustfmt-wrapped multiline declarations and restricted/private visibility so required-field drift cannot silently bypass the guard.

## Current limitations

- Duplicate LiteLLM `model_name` values are rejected. Multi-deployment aggregation is planned rather than guessed.
- Foreign-model web search remains disabled even when LiteLLM advertises web search; Codex search-tool wire semantics need an explicit compatibility rule.
- Foreign-model context-window mapping is an approximation, as described above.
- The exact allowlist supports strings only; per-model overrides/globs are deliberately deferred.
- Explicit local `--catalog-file` / `--codex-prompt-file` / `--codex-schema-file` overrides are a caller trust boundary. The normal auto/ref path fetches all resources from one version-matched Codex ref.
