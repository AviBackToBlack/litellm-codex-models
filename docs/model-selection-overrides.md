# v0.3 model selection and override contract

## Goal

Extend the current exact `model_name` allowlist with deterministic glob selection and explicit per-model compatibility overrides without weakening the conservative model-group aggregation contract.

The generator must continue to describe what is safe for an arbitrary routed request. A glob is only a selection convenience. An override is an explicit user assertion about one selected user-facing LiteLLM model group and must remain visible in provenance.

## Non-goals

This work does not:

- reinterpret existing `models = ["..."]` strings as patterns;
- allow arbitrary Codex catalog fields to be overwritten;
- allow overrides to force exact-template identity;
- allow `mode`, provider, deployment model, or base-model identity to be overridden;
- enable foreign-model web search;
- infer capabilities from model names or provider names;
- add exclusion patterns or regular-expression syntax in v0.3.

## Configuration shape

Existing exact strings keep their current meaning unchanged:

```toml
models = [
  "gpt-5.6-sol",
  "claude-sonnet-5",
]
```

Globs are a separate top-level list so a literal model name containing wildcard characters can never silently change meaning after an upgrade:

```toml
model_globs = [
  "claude-*",
  "gpt-oss-*",
]
```

Overrides are keyed by an exact user-facing `model_name`:

```toml
[model_overrides."claude-sonnet-5"]
supports_vision = true
supports_function_calling = true
max_input_tokens = 200000
supported_openai_params = ["tools", "reasoning_effort"]
reasoning_effort_levels = ["low", "medium", "high"]
```

An override key is never a glob. A configured override whose exact target is not selected by either `models` or `model_globs` is an error rather than a silently unused setting.

## Glob semantics

Globs use case-sensitive shell-style matching equivalent to Python `fnmatch.fnmatchcase` over the exact raw LiteLLM `model_name` string.

Patterns must be non-empty strings. Duplicate patterns are rejected in configuration.

Selection order is deterministic:

1. exact `models` entries are considered in their declared order;
2. `model_globs` are considered in their declared order;
3. matches within one glob are ordered lexically by exact raw `model_name`;
4. the first selection of a model name wins and later exact/glob matches are de-duplicated without reordering it.

This preserves current exact-list ordering while making glob expansion independent of LiteLLM response row order.

`strict = true` keeps the current missing-exact behavior and additionally rejects a glob that matches no model names. With `strict = false`, missing exact names and empty glob expansions are skipped.

A glob does not weaken eligibility. After expansion, every selected model group goes through the same aggregation validation as an exact selection. If a matched group contains a deployment whose mode is not exactly `chat` or `responses`, generation fails closed rather than silently including that model. Malformed deployment metadata also remains an error.

## Override surface

Overrides operate on the model-group evidence layer. They do not patch individual LiteLLM deployment rows and they do not patch arbitrary generated Codex fields.

The v0.3 override whitelist is:

### Boolean capability evidence

- `supports_vision`
- `supports_audio_input`
- `supports_function_calling`
- `supports_parallel_function_calling`
- `supports_web_search`
- `supports_reasoning`

Values must be booleans.

### Limits

- `max_input_tokens`
- `max_output_tokens`

Values must be positive integers; booleans are not integers for this contract.

For exact Codex templates, context-window values remain Codex-owned exactly as today. A `max_input_tokens` override changes the LiteLLM validation evidence only; it does not replace the exact template's Codex context fields.

### Explicit sets

- `supported_openai_params`
- `reasoning_effort_levels`

Values must be arrays of unique strings. `reasoning_effort_levels` accepts only reasoning efforts known to the generator. An explicit empty array is valid and means a known-empty set, not unknown evidence.

No other keys are accepted. Unknown override fields fail closed.

## Override precedence

Normal deployment evidence is aggregated first using the existing deterministic model-group contract. A configured override is then applied to the aggregate evidence for that user-facing group.

Therefore an override is intentionally capable of replacing an aggregated `guaranteed`, `denied`, or `unknown` value. This makes it useful for correcting incomplete or known-wrong LiteLLM metadata, but the replacement must never erase what was observed.

For every overridden field, `explain` must retain both:

- the original aggregate state/value;
- the effective configured override value.

The override source must be identified as `config:model_overrides.<model_name>.<field>` or an equivalently explicit provenance string.

Overrides never affect exact-template resolution. Exact identity must still be independently proven by the deployment identity evidence under the existing aggregation rules.

## Dependency and safety rules

Existing capability dependency rules still apply after overrides.

In particular:

- effective `supports_reasoning = false` disables reasoning efforts and reasoning-summary transport on generated output;
- effective `supports_function_calling = false` prevents parallel tool calls;
- parallel tool calls for foreign models still require all existing parameter/function/parallel guarantees;
- an override cannot turn on foreign Codex web search. `supports_web_search = true` may alter the recorded LiteLLM evidence or prevent an exact-template downgrade, but foreign `supports_search_tool` remains disabled until the separate web-search compatibility work is complete.

Directly contradictory settings inside one override table fail configuration validation. At minimum:

- `supports_function_calling = false` with `supports_parallel_function_calling = true` is invalid;
- `supports_reasoning = false` with a non-empty `reasoning_effort_levels` array is invalid.

Other cross-field safety dependencies continue to be enforced by the mapper even when only one side was overridden.

## Selection and override provenance

Prepared model groups should retain selection provenance in addition to compatibility evidence:

- `exact:<model_name>` for a group selected by the existing exact list;
- `glob:<pattern>` for a group first selected by a glob.

If a model is matched again by later selectors, the original first-selection provenance remains authoritative.

`explain` should expose the selection source and configured overrides. It must not rewrite overridden LiteLLM evidence as if the gateway itself reported the effective value.

## Determinism requirements

Tests must prove that reordering LiteLLM response rows cannot change:

- glob expansion;
- final selected model order;
- de-duplication behavior;
- effective override values;
- override provenance;
- generated catalog output for the same logical input.

Exact-list behavior with no `model_globs` or `model_overrides` must remain semantically compatible with the current v0.3 behavior.

## Implementation slices

The first implementation slice should add configuration parsing and deterministic selector expansion with selection provenance while keeping the existing aggregation/mapping behavior unchanged for configurations without the new fields.

The second slice should apply the whitelist overrides to aggregated group evidence, preserve original evidence for `explain`, and wire generated-field provenance through the existing exact/foreign dependency rules.

Only after those tests are green should README/config examples advertise the new syntax as production-supported.
