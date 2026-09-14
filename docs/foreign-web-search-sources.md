# Foreign web-search research source index

This companion page records the upstream evidence used by `foreign-web-search.md` so the contract can be revalidated against future Codex/LiteLLM versions without redoing discovery from scratch.

## Codex

- Hosted web-search construction and `WebSearchToolType` consumption:
  - https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/hosted_spec.rs
- Hosted web-search provider/config gating and separate `search_tool_enabled()` path:
  - https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/spec_plan.rs
- `WebSearchToolType` schema (`text`, `text_and_image`; no disabled variant):
  - https://github.com/openai/codex/blob/main/codex-rs/protocol/src/openai_models.rs
- Configured-provider capability defaults (`web_search=true` via `ProviderCapabilities::default()`):
  - https://github.com/openai/codex/blob/main/codex-rs/model-provider/src/provider.rs
- Current hosted-web-search integration tests, including configured catalogs:
  - https://github.com/openai/codex/blob/main/codex-rs/core/tests/suite/web_search.rs
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

Before changing the contract, re-check the **version-matched** Codex source used by the generator, not only `main`. In particular verify:

1. whether `WebSearchToolType` gained a disabled/off variant;
2. whether provider capabilities became user-configurable;
3. whether `supports_search_tool` changed meaning;
4. whether hosted search is still gated by provider capability + runtime mode;
5. whether LiteLLM routing guarantees the exact OpenAI Responses hosted-search wire shape across every deployment in the selected model group.
