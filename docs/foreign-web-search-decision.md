# v0.3 foreign web-search decision

**Decision:** do not map LiteLLM `supports_web_search` to Codex hosted-search behavior in v0.3.

Reasons:

- Codex `supports_search_tool` controls tool discovery/deferred exposure, not hosted web search.
- Hosted `web_search` emission is controlled by Codex provider capability plus runtime web-search mode; `web_search_tool_type` only selects payload shape.
- Current custom/configured Codex providers default to `web_search=true` and the model catalog has no hosted-search `disabled` variant.
- LiteLLM `supports_web_search` is not sufficient proof that every routed deployment accepts the exact OpenAI Responses hosted-search wire shape Codex emits.

Immediate correction required after this design gate:

- stop rewriting exact-template `supports_search_tool` from LiteLLM `supports_web_search` evidence;
- stop claiming foreign `supports_search_tool=false` guarantees hosted web search is disabled;
- retain LiteLLM web-search values as evidence/audit only until a stronger provider/route wire contract exists.

See `foreign-web-search.md` for the full contract and `foreign-web-search-sources.md` for source evidence.
