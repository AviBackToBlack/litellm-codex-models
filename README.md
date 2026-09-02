# litellm-codex-models

Generate a small, version-aware Codex `models.json` from LiteLLM's rich `/v1/model/info` response.

The key design rule is **Codex template inheritance + LiteLLM capability evidence**:

- The config contains an ordered, exact `model_name` allowlist.
- Only LiteLLM `mode = chat` or `mode = responses` entries are eligible.
- If a LiteLLM deployment resolves to a model already present in the matching Codex catalog, the entire Codex entry is deep-cloned and the LiteLLM alias becomes its slug.
- Codex-specific fields (instructions, shell/tool modes, truncation, multi-agent metadata, etc.) stay owned by Codex.
- Explicit LiteLLM transport restrictions can downgrade an exact template; `null` means unknown and does not become `false`.
- Unknown/foreign models use a conservative fallback cloned from a version-matched Codex donor and enriched with LiteLLM metadata.
- `explain` reports field provenance and important compatibility notes.

## Install

```bash
python -m pip install -e .
```

Requires Python 3.11+ and no third-party runtime dependencies.

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

For offline/reproducible work, use saved inputs:

```bash
litellm-codex-models \
  --config litellm-codex-models.toml \
  build \
  --input litellm.json \
  --catalog-file codex-models.json \
  --output generated-models.json
```

Then point Codex at the result:

```toml
model_catalog_json = "/absolute/path/to/generated-models.json"
```

## Context-window policy

For an **exact Codex template match**, `context_window` and `max_context_window` remain the Codex values. LiteLLM `max_input_tokens` is treated as validation evidence because the two fields do not have identical semantics.

For a **foreign model** with no Codex template, v0.1 uses LiteLLM `max_input_tokens` as the best available approximation for both context fields and marks that provenance explicitly. This is intentionally visible in `explain` rather than hidden as an assumption.

## v0.1 limitations

- Duplicate LiteLLM `model_name` values are rejected. Multi-deployment aggregation is planned rather than guessed.
- Foreign-model web search remains disabled even when LiteLLM advertises web search; Codex search-tool wire semantics need an explicit compatibility rule.
- Foreign-model context-window mapping is an approximation, as described above.
- The exact allowlist supports strings only in v0.1; per-model overrides/globs are deliberately deferred.
