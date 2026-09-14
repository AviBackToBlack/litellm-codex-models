# Foreign web-search research source index

This companion page records the upstream evidence used by `foreign-web-search.md` so the contract can be revalidated against future Codex/LiteLLM versions without redoing discovery from scratch.

## Evidence scope

The Codex behavior used for the v0.3 decision was verified against **`rust-v0.154.0`**, the latest stable Codex release on 2026-09-14, and then cross-checked against upstream `main` for drift. The contract does not assume that every historical or future Codex ref has identical semantics.

For any generated catalog, the version-matched Codex ref remains authoritative. If a future matched ref changes these semantics, the generator must re-evaluate the mapping rather than inherit this snapshot blindly.

## Codex — version-matched stable evidence (`rust-v0.154.0`)

- Hosted web-search construction and `WebSearchToolType` consumption:
  - https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/hosted_spec.rs
- Hosted web-search provider/config gating and separate `search_tool_enabled()` path:
  - https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/core/src/tools/spec_plan.rs
- `WebSearchToolType` schema (`text`, `text_and_image`; no disabled variant):
  - https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/protocol/src/openai_models.rs
- Configured-provider capability defaults (`web_search=true` via `ProviderCapabilities::default()`):
  - https://github.com/openai/codex/blob/rust-v0.154.0/codex-rs/model-provider/src/provider.rs

The same semantics were still present on upstream `main` when researched on 2026-09-14:

- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/hosted_spec.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs
- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs
- https://github.com/openai/codex/blob/main/codex-rs/model-provider/src/provider.rs
- https://github.com/openai/codex/blob/main/codex-rs/core/tests/suite/web_search.rs

Additional behavioral evidence:

- Custom catalog/tool-search failure showing `supports_search_tool` is about deferred tool discovery, while hosted web search is independent:
  - https://github.com/openai/codex/issues/36382
- Provider capability/config limitations relevant to suppression/opt-in:
  - https://github.com/openai/codex/issues/21952
  - https://github.com/openai/codex/issues/24465
- LiteLLM/custom-provider model discovery context:
  - https://github.com/openai/codex/issues/30760
  - https://github.com/openai/codex/issues/37122

## LiteLLM

- Mixed-provider routing bug demonstrating that `supports_web_search` metadata does not by itself prove deterministic compatibility for every native search request shape:
  - https://github.com/BerriAI/litellm/issues/38982
- Responses/web-search integration gaps and response-shape translation context:
  - https://github.com/BerriAI/litellm/issues/26073
- Provider-specific Responses bridge interaction for search:
  - https://github.com/BerriAI/litellm/issues/37127

## Revalidation rule

Before changing or applying the contract to a new Codex version, re-check the **version-matched** source used by the generator, not only `main`. In particular verify:

1. whether `WebSearchToolType` gained a disabled/off variant;
2. whether provider capabilities became user-configurable;
3. whether `supports_search_tool` changed meaning;
4. whether hosted search is still gated by provider capability + runtime mode;
5. whether LiteLLM routing guarantees the exact OpenAI Responses hosted-search wire shape across every deployment in the selected model group.

The v0.3 rule is intentionally conservative: without a version-matched proof of semantic equivalence, LiteLLM `supports_web_search` must not be mapped to Codex `supports_search_tool` or treated as sufficient proof for hosted-search enablement.
