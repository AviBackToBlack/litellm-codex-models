# v0.3 model-group aggregation contract

Status: design gate for issue #7. This document defines the safety contract to implement before duplicate LiteLLM `model_name` values are accepted in production selection.

## Goal

A generated Codex catalog describes what is safe to send to a LiteLLM model group, not the union of features exposed by any one deployment.

Aggregation is therefore field-specific, conservative, deterministic, and order-independent.

## Non-goals

This design does not:

- enable foreign-model web search;
- change exact Codex template ownership of Codex-native metadata;
- infer capabilities from provider names or neighboring models;
- rely on LiteLLM `/model_group/info` as a safety contract;
- add per-model overrides or globs.

## Grouping and eligibility

Rows are grouped by exact user-facing `model_name` before mapping.

For a selected group:

- every deployment must have `mode` equal to `chat` or `responses`;
- a mixed eligible/ineligible group fails closed;
- a single-row group must preserve current v0.2 behavior;
- reordering deployments must never change the generated catalog or explanation.

The implementation should use a first-class group/evidence object before `mapping.py`. It may later expose a synthetic row for compatibility, but disagreement and unknown-state evidence must not be discarded.

## Exact-template identity

Resolve the Codex template identity independently for every deployment.

An exact Codex template may be used only when every deployment resolves unambiguously to the same exact template slug.

Examples:

- `azure/gpt-5.6-sol` + `openai/gpt-5.6-sol` -> exact `gpt-5.6-sol`, if both independently resolve there;
- two aliases with the same base model -> exact, if both resolve to the same template;
- `gpt-5.6-sol` + `claude-*` under one `model_name` -> foreign fallback;
- one exact deployment + one unresolved deployment -> foreign fallback.

Never choose first/last deployment as a donor.

If deployments disagree on canonical/base identity and no exact template survives, the foreign group canonical identity is the user-facing group `model_name`; the conflicting candidates are retained only as provenance/disagreement evidence.

## Tri-state capability evidence

Keep `true`, `false`, and unknown distinct internally. Conservative output is not the same thing as rewriting unknown to `false`.

For a foreign group capability that Codex would advertise:

| Deployment evidence | Group evidence | Advertise |
| --- | --- | --- |
| all explicit `true` | guaranteed true | yes |
| any explicit `false` | denied | no |
| `true` + unknown | unknown | no |
| `false` + unknown | denied | no |
| all unknown | unknown | no |

This rule applies to boolean-like capabilities unless a separately documented, mandatory LiteLLM request-time routing guarantee proves union semantics safe.

For an exact Codex template, Codex-owned positive metadata remains authoritative. Explicit LiteLLM `false` on any deployment may downgrade the corresponding capability. Unknown metadata does not downgrade an exact template by itself.

## Context and output limits

LiteLLM group discovery uses maximum values, but the generator needs a safe arbitrary-route guarantee.

### Foreign groups

`max_input_tokens`:

- every deployment must provide a positive integer;
- group safe input context is the minimum deployment value;
- if any deployment is missing/invalid, the group context guarantee is unknown and foreign multi-deployment synthesis fails closed until an explicit override exists.

`max_output_tokens` follows the same guarantee rule: minimum positive value when every deployment is known, otherwise unknown/fail closed for any future field that depends on it.

The current Codex catalog mapping does not emit a separate output-token limit, so v0.3 should retain the aggregated output limit as evidence/provenance without inventing a Codex field.

### Exact groups

Version-matched Codex template context values remain authoritative, as in v0.2. LiteLLM deployment limits are validation evidence only; they do not replace Codex-owned context fields.

## Reasoning effort

Foreign reasoning levels require explicit evidence.

For each deployment, build its explicitly supported effort set from:

- `reasoning_effort_levels` values recognized by Codex;
- explicit per-effort `supports_*_reasoning_effort == true` flags;
- with explicit per-effort `false` removing that effort.

The group advertised effort set is the intersection of deployment-supported sets for deployments that have reasoning metadata, with these additional safety rules:

- a deployment-wide explicit denial of reasoning denies group reasoning;
- unknown metadata never invents an effort;
- an effort contradicted by explicit `false` on any deployment is removed;
- result ordering follows Codex's stable effort order, not input order.

For exact templates, explicit denials from any deployment may restrict the template's reasoning levels; unknown does not narrow the exact template.

## `supported_openai_params`

Do not consume LiteLLM's order-dependent group value.

For foreign groups, a parameter is guaranteed only when every deployment has an explicit parameter list and the parameter appears in every list. The guaranteed set is therefore the intersection of complete deployment evidence.

If any deployment has unknown `supported_openai_params`, the group parameter evidence is unknown rather than an empty authoritative list. Foreign mapping must not advertise a parameter from that unknown state.

For exact templates, a known deployment list may explicitly prove absence of a transport parameter and therefore downgrade behavior as v0.2 already does. A missing list remains unknown and must not downgrade by itself.

## Web search

Foreign web search stays disabled in v0.3 aggregation.

LiteLLM can filter web-search deployments at request time, but missing `supports_web_search` currently behaves permissively upstream and registry metadata is incomplete. That is not sufficient evidence for Codex search-tool wire compatibility or a mandatory safe routing guarantee.

Exact Codex templates may retain their Codex-native search support unless any deployment explicitly reports `supports_web_search == false`, in which case the group is downgraded.

## Provenance and explanations

`explain` for an aggregated model must make grouping visible. At minimum record:

- group size;
- contributing deployments in deterministic order using non-secret identifiers/provider/base-model evidence available in the payload;
- resolved exact-template candidates;
- disagreements;
- per-field aggregation rule;
- group evidence state/value;
- conservative downgrades and foreign-fallback reasons.

Do not claim that one deployment supplied an aggregate value.

## Determinism

Aggregation output must be independent of LiteLLM row order.

Tests must permute the same deployment set and compare the complete aggregate result, including provenance/disagreement ordering. Any lists in emitted evidence use stable Codex ordering where defined, otherwise lexical/stable normalized ordering.

## First implementation slice

The first v0.3 code PR should stay below the production mapping path:

1. introduce a grouped-selection / aggregation module with an explicit evidence model;
2. add synthetic tests for group eligibility, identity, tri-state booleans, reasoning intersection, context limits, parameter intersection, and order independence;
3. keep duplicate rejection in the production `select_models()` path until the aggregation layer is proven;
4. in a later PR, connect grouped selection to mapping and extend `explain`/provenance;
5. enable duplicate model groups only after those integration tests pass.

This sequencing makes the safety contract testable without silently changing current v0.2 behavior.