# Foreign web-search compatibility contract

Status: **research complete; hosted-search enablement is blocked/deferred**.

This document closes the research/design gate for v0.3 foreign-model web search. It deliberately does **not** enable web search for foreign models.

## Evidence scope

The concrete Codex behavior below was verified against **`rust-v0.154.0`**, the latest stable Codex release on 2026-09-14, and cross-checked against upstream `main` for drift. It is not a claim that every historical or future Codex version has identical semantics.

The generator remains version-aware: for a particular generated catalog, the matching `rust-v<version>` source is authoritative. The safe repository-wide rule is therefore narrower: **never map similarly named LiteLLM and Codex search fields unless semantic equivalence is proven for the version-matched Codex ref and the routed LiteLLM wire path.**

## Why this needs a separate contract

LiteLLM and Codex expose similarly named search capability fields, but they are not the same contract.

The generator must not infer Codex hosted web-search compatibility from LiteLLM `supports_web_search` alone. A generated catalog entry describes model metadata, while Codex decides whether to emit a hosted `web_search` tool from a combination of model metadata, provider capabilities, and runtime configuration.

## Codex findings

The current stable Codex ref (`rust-v0.154.0`) has two independent search concepts.

### `supports_search_tool` is tool discovery, not hosted web search

Codex `search_tool_enabled()` gates deferred/namespace tool discovery with:

- `model_info.supports_search_tool`; and
- provider `namespace_tools` capability.

It is used for `tool_search` and deferred tool exposure. It is **not** the hosted web-search enable bit.

Version-matched source:

- `codex-rs/core/src/tools/spec_plan.rs`
- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/spec_plan.rs

This distinction is externally observable. OpenAI Codex issue #36382 documents custom models where `supports_search_tool=true` hides ordinary MCP tools behind deferred discovery while hosted web search remains independent:

- https://github.com/openai/codex/issues/36382

Therefore v0.3 must not map LiteLLM `supports_web_search` to Codex `supports_search_tool`. A future Codex ref may be re-evaluated only from its version-matched semantics.

### Hosted web search is provider/config controlled

At `rust-v0.154.0`, Codex builds a hosted `web_search` tool when all relevant runtime conditions allow it:

1. the active provider advertises `ProviderCapabilities.web_search=true`;
2. runtime `web_search_mode` is not disabled; and
3. the model's `web_search_tool_type` controls the **shape** of the emitted hosted tool.

`WebSearchToolType` at that ref has only:

- `text`; and
- `text_and_image`.

There is no model-catalog `disabled` variant.

Version-matched source:

- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/hosted_spec.rs
- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/spec_plan.rs
- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/protocol/src/openai_models.rs

Configured/custom providers at that ref inherit `ProviderCapabilities::default()`, where `web_search=true`. The model catalog itself does not provide a per-model hosted-search off switch.

Version-matched source:

- https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/model-provider/src/provider.rs

The same architecture was still present on upstream `main` on 2026-09-14. The companion source index records both the stable-ref evidence and the `main` drift cross-check.

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

### 1. Never map LiteLLM web-search evidence to Codex `supports_search_tool` without version-matched proof

For the researched stable ref, `supports_search_tool` belongs to Codex tool discovery/deferred exposure semantics while LiteLLM `supports_web_search` belongs to search capability evidence. They are independent.

For exact Codex templates under this contract:

- preserve the version-matched Codex template's `supports_search_tool` value;
- do not downgrade it because LiteLLM says `supports_web_search=false`;
- do not upgrade it because LiteLLM says `supports_web_search=true` or because a configured override says so.

For foreign models:

- keep the existing conservative `supports_search_tool=false` choice as a **tool-discovery** decision only;
- never describe that field as disabling hosted web search.

If a future matched Codex ref changes `supports_search_tool` semantics, that ref must be researched before changing this rule.

### 2. `web_search_tool_type` is not an enable bit in the researched stable ref

At `rust-v0.154.0`, `text` versus `text_and_image` only chooses the hosted tool payload shape. A foreign entry may need a schema-valid `web_search_tool_type`, but the generator must not claim that `web_search_tool_type="text"` disables search.

A future matched ref must be re-checked for new enum values or changed semantics.

### 3. `supports_web_search` remains evidence-only for foreign hosted search

Until a stronger compatibility proof exists, effective foreign `supports_web_search=true` may be recorded in aggregation/override evidence and `explain`, but it must not cause the generator to mutate Codex `supports_search_tool` or claim hosted-search compatibility.

Likewise, `supports_web_search=false` is evidence about the LiteLLM route, but at the researched Codex ref the model catalog alone cannot enforce provider-level hosted-search suppression.

### 4. Model catalog alone cannot guarantee hosted-search disablement for the researched stable ref

At `rust-v0.154.0`:

- `WebSearchToolType` has no disabled variant;
- configured providers default to `ProviderCapabilities.web_search=true`;
- hosted-search emission also depends on runtime `web_search_mode`.

Therefore this project must not promise that foreign hosted web search is disabled solely because the generated model has `supports_search_tool=false`.

Users who need guaranteed suppression must currently disable web search in the applicable Codex runtime/provider configuration. A future Codex provider capability override or model-level hosted-search disable field could provide a stronger enforceable boundary and should be evaluated from the matched ref.

Related upstream requests/bugs:

- https://github.com/openai/codex/issues/21952
- https://github.com/openai/codex/issues/24465
- https://github.com/openai/codex/issues/30760
- https://github.com/openai/codex/issues/37122

### 5. Future enablement requires an explicit wire proof

Foreign hosted web search may be enabled by this generator only when all of the following are proven for the **matched Codex version and selected LiteLLM route**:

1. **Codex wire shape** — exact request tool type and fields emitted by the matched Codex version are known.
2. **Provider boundary** — the active Codex provider is allowed to emit hosted web search.
3. **LiteLLM route guarantee** — every deployment that can receive the public `model_name` accepts that exact wire shape, or LiteLLM deterministically filters to compatible deployments for that request shape.
4. **Response compatibility** — LiteLLM/provider responses preserve the response item/event shapes Codex expects, including `web_search_call` history when applicable.
5. **No semantic collision** — enabling hosted search does not repurpose `supports_search_tool`, tool-search discovery, MCP exposure, or another unrelated Codex capability.

A plain LiteLLM `supports_web_search=true` is insufficient because it does not prove the full five-part contract.

## Immediate implementation follow-up

The next production PR should be intentionally small:

1. remove the existing exact-template mapping from LiteLLM `supports_web_search=false` to Codex `supports_search_tool=false`;
2. remove override provenance that treats `supports_web_search` as ownership/validation of `supports_search_tool`;
3. keep foreign `supports_search_tool=false`, but describe it explicitly as conservative tool-search/deferred-discovery behavior;
4. keep README/current-limitations wording aligned with this contract so the project does not claim that model catalog metadata guarantees hosted web-search disablement;
5. add regressions proving exact `supports_search_tool` is Codex-owned regardless of LiteLLM web-search evidence.

No v0.3 implementation should set foreign hosted-search behavior from `supports_web_search` until the five-part proof above is available for the matched Codex/LiteLLM path.

## v0.3 disposition

The research acceptance criteria are satisfied for the current v0.3 decision:

- the current stable Codex hosted-search wire construction and separate `supports_search_tool` meaning are identified and source-backed at `rust-v0.154.0`;
- provider-native/LiteLLM search evidence is distinguished from Codex/OpenAI hosted-search wire compatibility;
- the current model-catalog boundary is documented as insufficient for safe foreign enablement or guaranteed provider-level disablement;
- future mappings require version-matched revalidation rather than extrapolation from `main`;
- the implementation remains fail-closed with respect to **automatic capability mapping**: no foreign hosted-search behavior is enabled from LiteLLM evidence.

Actual hosted-search enablement is **deferred** pending a stronger Codex provider/model capability boundary plus route-level wire compatibility evidence.
