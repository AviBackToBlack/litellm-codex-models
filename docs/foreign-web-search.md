# Foreign web-search compatibility contract

Status: **research complete; hosted-search enablement is blocked/deferred**.

This document closes the research/design gate for v0.3 foreign-model web search. It deliberately does **not** enable web search for foreign models.

## Why this needs a separate contract

LiteLLM and Codex expose similarly named search capability fields, but they are not the same contract.

The generator must not infer Codex hosted web-search compatibility from LiteLLM `supports_web_search` alone. A generated catalog entry describes model metadata, while Codex decides whether to emit a hosted `web_search` tool from a combination of model metadata, provider capabilities, and runtime configuration.

## Codex findings

Research against current upstream Codex on 2026-09-14 found two independent search concepts.

### `supports_search_tool` is tool discovery, not hosted web search

Codex `search_tool_enabled()` gates deferred/namespace tool discovery with:

- `model_info.supports_search_tool`; and
- provider `namespace_tools` capability.

It is used for `tool_search` and deferred tool exposure. It is **not** the hosted web-search enable bit.

Relevant upstream source:

- `codex-rs/core/src/tools/spec_plan.rs`
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs

This distinction is externally observable. OpenAI Codex issue #36382 documents custom models where `supports_search_tool=true` hides ordinary MCP tools behind deferred discovery while hosted web search remains independent:

- https://github.com/openai/codex/issues/36382

Therefore LiteLLM `supports_web_search` must never downgrade, enable, or otherwise rewrite Codex `supports_search_tool`.

### Hosted web search is provider/config controlled

Codex builds a hosted `web_search` tool when all relevant runtime conditions allow it. In current source:

1. the active provider must advertise `ProviderCapabilities.web_search=true`;
2. runtime `web_search_mode` must not be disabled; and
3. the model's `web_search_tool_type` controls the **shape** of the emitted hosted tool.

`WebSearchToolType` currently has only:

- `text`; and
- `text_and_image`.

There is no model-catalog `disabled` variant.

Relevant upstream source:

- `codex-rs/core/src/tools/hosted_spec.rs`
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/protocol/src/openai_models.rs`
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/hosted_spec.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs
- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs

Current configured/custom providers inherit `ProviderCapabilities::default()`, where `web_search=true`. The provider implementation does not currently expose a per-user custom-provider capability override through the model catalog.

Relevant upstream source:

- `codex-rs/model-provider/src/provider.rs`
- https://github.com/openai/codex/blob/main/codex-rs/model-provider/src/provider.rs

Current Codex tests also exercise cached hosted web search as a default path and show that configured model catalog metadata supplies `web_search_tool_type` rather than an on/off bit:

- `codex-rs/core/tests/suite/web_search.rs`
- https://github.com/openai/codex/blob/main/codex-rs/core/tests/suite/web_search.rs

## LiteLLM findings

LiteLLM `supports_web_search` is useful capability evidence, but it does not by itself prove that an arbitrary LiteLLM deployment accepts the exact OpenAI Responses `tools: [{"type":"web_search", ...}]` wire shape emitted by Codex.

Providers can expose native search through different request shapes and transformations. Recent upstream evidence includes:

- Anthropic-native `web_search_*` tool types versus OpenAI `web_search` / `web_search_preview` routing detection;
- provider-specific completion-to-Responses bridges for search;
- model/provider metadata gaps where `supports_web_search` is missing or wrong.

In particular, LiteLLM issue #38982 documents a mixed-provider group where explicit per-deployment `supports_web_search=false` is not sufficient for Anthropic-native search routing because the router's request detector recognizes only OpenAI-style tool types in that path:

- https://github.com/BerriAI/litellm/issues/38982

This reinforces the generator's existing group principle: metadata must describe what is safe for an arbitrary routed request, and similarly named provider-native capabilities are not interchangeable with a proven Codex/OpenAI wire contract.

## Contract

### 1. Never map LiteLLM web-search evidence to Codex `supports_search_tool`

`supports_search_tool` belongs to Codex tool discovery/deferred exposure semantics. LiteLLM `supports_web_search` belongs to search capability evidence. They are independent.

For exact Codex templates:

- preserve the version-matched Codex template's `supports_search_tool` value;
- do not downgrade it because LiteLLM says `supports_web_search=false`;
- do not upgrade it because LiteLLM says `supports_web_search=true` or because a configured override says so.

For foreign models:

- keep the existing conservative `supports_search_tool=false` choice as a **tool-discovery** decision only;
- never describe that field as disabling hosted web search.

### 2. `web_search_tool_type` is not an enable bit

A foreign entry needs a schema-valid `web_search_tool_type` when required by the matched Codex version, but `text` versus `text_and_image` only chooses the hosted tool payload shape.

The generator must not claim that `web_search_tool_type="text"` disables search.

### 3. `supports_web_search=true` remains evidence-only for foreign models

Until a stronger compatibility proof exists, effective foreign `supports_web_search=true` may be recorded in aggregation/override evidence and `explain`, but it must not cause the generator to mutate Codex hosted-search fields.

Likewise, `supports_web_search=false` is evidence that the LiteLLM route should not receive provider-native search, but the model catalog alone cannot currently enforce Codex provider-level hosted-search suppression.

### 4. Model catalog alone cannot currently guarantee hosted-search disablement

With current Codex semantics, `model_catalog_json` has no model-level hosted-search `disabled` switch:

- `WebSearchToolType` has no disabled variant;
- configured providers default to `ProviderCapabilities.web_search=true`;
- hosted-search emission also depends on runtime `web_search_mode`.

Therefore this project must not promise that foreign hosted web search is disabled solely because the generated model has `supports_search_tool=false`.

Users who need guaranteed suppression must currently disable web search in Codex runtime/provider configuration where that surface is available. A future Codex provider capability override or model-level hosted-search disable field would give the generator a stronger enforceable boundary.

Related upstream requests/bugs:

- https://github.com/openai/codex/issues/21952
- https://github.com/openai/codex/issues/24465
- https://github.com/openai/codex/issues/30760
- https://github.com/openai/codex/issues/37122

### 5. Future enablement requires an explicit wire proof

Foreign hosted web search may be enabled by this generator only when all of the following are proven for the matched Codex/LiteLLM path:

1. **Codex wire shape** — exact request tool type and fields emitted by the matched Codex version are known.
2. **Provider boundary** — the active Codex provider is allowed to emit hosted web search.
3. **LiteLLM route guarantee** — every deployment that can receive the public `model_name` accepts that exact wire shape, or LiteLLM deterministically filters to compatible deployments for that request shape.
4. **Response compatibility** — LiteLLM/provider responses preserve the response item/event shapes Codex expects, including `web_search_call` history when applicable.
5. **No semantic collision** — enabling hosted search does not repurpose `supports_search_tool`, tool-search discovery, MCP exposure, or another unrelated Codex capability.

A plain LiteLLM `supports_web_search=true` satisfies none of items 1, 2, 4, or 5 by itself and is therefore insufficient.

## Immediate implementation follow-up

The next production PR should be intentionally small:

1. remove the existing exact-template mapping from LiteLLM `supports_web_search=false` to Codex `supports_search_tool=false`;
2. remove override provenance that treats `supports_web_search` as ownership/validation of `supports_search_tool`;
3. keep foreign `supports_search_tool=false`, but describe it explicitly as conservative tool-search/deferred-discovery behavior;
4. update README/current-limitations wording so the project does not claim that model catalog metadata guarantees hosted web-search disablement;
5. add regressions proving exact `supports_search_tool` is Codex-owned regardless of LiteLLM web-search evidence.

No PR in this v0.3 item should set foreign hosted-search behavior from `supports_web_search` until the five-part proof above is available.

## v0.3 disposition

The research acceptance criteria are satisfied:

- Codex hosted-search wire construction and the separate `supports_search_tool` meaning are identified;
- provider-native/LiteLLM search evidence is distinguished from Codex/OpenAI hosted-search wire compatibility;
- the current model-catalog boundary is documented as insufficient for safe foreign enablement or guaranteed provider-level disablement;
- the implementation remains fail-closed with respect to **automatic capability mapping**: no foreign hosted-search field is enabled from LiteLLM evidence.

Actual hosted-search enablement is **deferred** pending a stronger Codex provider/model capability boundary plus route-level wire compatibility evidence.
