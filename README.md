# litellm-codex-models

Generate a small, version-aware Codex `models.json` from LiteLLM's rich `/v1/model/info` response.

The key design rule is **Codex template inheritance + LiteLLM capability evidence**:

- The config selects exact `model_name` values and/or deterministic case-sensitive globs.
- Only LiteLLM `mode = chat` or `mode = responses` entries are eligible.
- If all deployments in a LiteLLM model group independently resolve to the same model in the matching Codex catalog, the entire Codex entry is deep-cloned and the LiteLLM alias becomes its slug.
- Codex-specific fields (instructions, shell/tool modes, truncation, multi-agent metadata, etc.) stay owned by Codex.
- Explicit LiteLLM transport restrictions can downgrade an exact template; `null` means unknown and does not become `false`.
- Unknown/foreign model groups are built from conservative Codex fallback semantics, use the version-matched Codex fallback prompt, and are enriched only with capability evidence guaranteed across every possible deployment.
- Optional exact-keyed `model_overrides` can replace aggregate compatibility evidence when gateway metadata is incomplete or known-wrong; the original and effective evidence remain visible in `explain`.
- `explain` reports selection provenance, field provenance, group evidence, configured overrides, and important compatibility notes.

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

Copy `config.example.toml` to `litellm-codex-models.toml` and configure exact selectors and/or globs:

```toml
# Exact selectors keep declaration order.
models = [
  "gpt-5.6-sol",
  "claude-sonnet-5",
]

# Optional case-sensitive shell-style selectors. Globs are evaluated after
# exact selectors, in declaration order; matches inside each glob are lexical.
model_globs = [
  "gpt-oss-*",
]

# Optional trusted compatibility assertion for one exact user-facing model_name.
[model_overrides."claude-sonnet-5"]
supports_vision = true
max_input_tokens = 200000
supported_openai_params = ["reasoning_effort", "tools"]
reasoning_effort_levels = ["low", "medium", "high"]

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

Existing `models = ["..."]` entries are always exact strings; wildcard characters in that list are never reinterpreted as patterns. `model_globs` uses case-sensitive `fnmatch`-style matching over the raw LiteLLM `model_name`. Exact selectors are considered first, then globs in declaration order, with lexical ordering inside each glob and stable first-selection de-duplication. With `strict = true`, a missing exact selector or an empty glob is an error.

`model_overrides` is keyed by an exact user-facing `model_name`; override keys are never globs. The target must be covered by either `models` or `model_globs`. Overrides operate on aggregated compatibility evidence, not on individual deployments and not on arbitrary Codex catalog fields. Supported fields are the six capability booleans (`supports_vision`, `supports_audio_input`, `supports_function_calling`, `supports_parallel_function_calling`, `supports_web_search`, `supports_reasoning`), `max_input_tokens`, `max_output_tokens`, `supported_openai_params`, and `reasoning_effort_levels`. `max_output_tokens` is currently evidence/audit-only because the generated Codex model schema has no independent output-token-limit field that consumes it; it is retained for explainability and future fields that may depend on that evidence.

An override is an explicit trusted assertion and can replace aggregate `guaranteed`, `denied`, or `unknown` evidence. `explain` keeps the original aggregate state/value beside the configured value and effective state/value. Dependency closure still applies: disabling reasoning disables reasoning transport/efforts, and disabling function calling prevents parallel tool calls. `supports_web_search` overrides remain evidence-only for hosted-search compatibility: they do not control Codex `supports_search_tool`, and the generated model catalog alone does not guarantee hosted web-search enablement or suppression. See [docs/foreign-web-search.md](docs/foreign-web-search.md).

`version = "auto"` runs `codex --version` and fetches the catalog from the corresponding `rust-v<version>` tag in `openai/codex`. This avoids using a `main` catalog whose schema may not match the installed Codex binary.

## Commands

List every model in LiteLLM:

```bash
litellm-codex-models --config litellm-codex-models.toml list
```

Only models selected by the configured exact/glob selectors:

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

For verified offline/reproducible work, use a Codex bundle manifest that pins one `repository@ref` identity and SHA-256 digest for every bundled resource:

```bash
litellm-codex-models \
  --config litellm-codex-models.toml \
  build \
  --input litellm.json \
  --codex-bundle codex-bundle.json \
  --output generated-models.json
```

Exact-only generation needs only the bundle's verified catalog. If any configured model is foreign, the same bundle must also contain the verified fallback prompt and `ModelInfo` schema. `--codex-bundle` cannot be combined with `--catalog-file`, `--codex-prompt-file`, `--codex-schema-file`, or `--codex-ref`. See [docs/offline-bundle.md](docs/offline-bundle.md) for the manifest contract and threat model.

The older independent local-file path remains available for compatibility:

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

Those independent local-file flags remain a caller trust boundary; use `--codex-bundle` when version identity and digest verification matter.

Then point Codex at the result:

```toml
model_catalog_json = "/absolute/path/to/generated-models.json"
```

## Model-group policy

Rows with the same exact raw `model_name` are treated as one LiteLLM routing group rather than as duplicates to reject.

For an **exact Codex template group**, every deployment must independently resolve unambiguously to the same version-matched Codex template. The Codex entry remains authoritative, while explicit deployment denials can conservatively downgrade capabilities. Unknown evidence alone does not narrow exact-template behavior. A configured override may replace the aggregate compatibility evidence used for those downgrade decisions, but cannot change the proven exact identity or invent Codex-owned fields.

For a **foreign group**, the generated catalog entry describes what is safe for an arbitrary routed request: boolean capabilities require a group guarantee, supported parameter and reasoning sets are intersected, and context/output limits use the safe minimum only when every deployment provides a valid value. Explicit overrides may replace those aggregate evidence values. Web-search evidence is retained for audit/explain but is not mapped to Codex `supports_search_tool` or treated as sufficient proof for hosted-search compatibility; hosted web search also depends on Codex provider/runtime behavior.

## Context-window policy

For an **exact Codex template match**, `context_window` and `max_context_window` remain the Codex values. LiteLLM `max_input_tokens` is treated as validation evidence because the two fields do not have identical semantics. A `max_input_tokens` override likewise changes the LiteLLM validation evidence only; it does not replace the exact template's Codex context fields.

For a **foreign model group**, the generator uses the minimum known LiteLLM `max_input_tokens` across every deployment as the best safe approximation for both context fields. A multi-deployment foreign group with missing or invalid context evidence fails closed rather than advertising a guessed window. An explicit `max_input_tokens` override can supply the trusted effective evidence needed to synthesize that group. A single foreign deployment preserves the v0.2 fallback behavior.

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

- Foreign hosted web-search compatibility is not inferred from LiteLLM `supports_web_search`. Current Codex hosted search is provider/runtime controlled, while `supports_search_tool` has separate tool-discovery semantics; see [docs/foreign-web-search.md](docs/foreign-web-search.md). The generated model catalog alone does not guarantee hosted-search enablement or suppression.
- Foreign-model context-window mapping is an approximation, as described above.
- `model_overrides` are trusted user assertions; they can deliberately replace conservative aggregate evidence, so incorrect overrides can over-advertise gateway compatibility even though Codex-owned template identity/fields remain protected.
- Hand-authored offline bundle manifests provide digest integrity and one declared Codex identity, but are not signed provenance attestations that the files came from the named Git ref.
- The legacy independent `--catalog-file` / `--codex-prompt-file` / `--codex-schema-file` path remains a caller trust boundary; prefer `--codex-bundle` for verified offline resources.

## Security

Please report security issues according to [SECURITY.md](SECURITY.md).
