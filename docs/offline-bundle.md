# Offline Codex bundle v1

## Goal

Offline Codex resources must carry one explicit source identity and must not rely on the caller remembering which `models.json`, fallback prompt, and Rust `ModelInfo` schema belong together.

Bundle v1 is the verified offline-resource path used by `build` and `explain` in v0.3 development.

## Manifest

A bundle is a JSON manifest stored next to the resources it describes:

```json
{
  "schema_version": 1,
  "codex": {
    "repository": "openai/codex",
    "ref": "rust-v0.153.0"
  },
  "files": {
    "catalog": {
      "path": "models.json",
      "sha256": "<64 hexadecimal characters>"
    },
    "prompt": {
      "path": "prompt.md",
      "sha256": "<64 hexadecimal characters>"
    },
    "schema": {
      "path": "openai_models.rs",
      "sha256": "<64 hexadecimal characters>"
    }
  }
}
```

`catalog` is required. `prompt` and `schema` are optional so an exact-only offline workflow does not need to carry resources that are only required for foreign-model synthesis.

## Identity contract

`codex.repository` and `codex.ref` are the single identity for every resource in the manifest.

Resources cannot declare their own ref/version identity. Unknown resource fields and unknown resource roles fail closed. This prevents the file-level API from representing a catalog as one Codex ref and a prompt/schema as another.

Bundle mode uses the manifest identity as the offline Codex source. It cannot be combined with `--catalog-file`, `--codex-prompt-file`, `--codex-schema-file`, or `--codex-ref`; mixing verified bundle resources with independent Codex overrides fails closed before LiteLLM input is loaded or fetched.

## Integrity contract

Every declared resource has a SHA-256 digest over its raw bytes. The loader verifies every declared digest before returning a bundle.

Resource paths are manifest-relative POSIX paths. Absolute paths, parent traversal, empty or dot path components, backslashes, duplicate resource paths, and paths that resolve outside the bundle directory fail closed.

The loader retains the verified bytes in memory. `build` and `explain` consume those verified bytes directly rather than re-reading the resource paths and reopening a time-of-check/time-of-use gap.

## Schema drift

The manifest shape is strict and versioned. Bundle v1 accepts only:

- top-level `schema_version`, `codex`, and `files`
- `codex.repository` and `codex.ref`
- resource roles `catalog`, `prompt`, and `schema`
- per-resource `path` and `sha256`

Unknown fields or a future `schema_version` fail closed until the implementation explicitly supports them.

## Threat model

The bundle contract is intended to prevent accidental resource mixing and to detect resource changes after a manifest was created.

A hand-authored manifest is not a signed attestation that its bytes actually came from the named Git repository/ref. A later bundle-creation workflow should fetch all selected resources from one resolved Codex ref and then emit this manifest. Authenticating arbitrary hand-authored offline provenance would require a stronger signed or Git-object proof and is outside bundle v1.

## CLI integration

Use the same verified bundle with either generation command:

```bash
litellm-codex-models \
  --config litellm-codex-models.toml \
  build \
  --input litellm.json \
  --codex-bundle ./codex-bundle.json \
  --output generated-models.json

litellm-codex-models \
  --config litellm-codex-models.toml \
  explain \
  --input litellm.json \
  --codex-bundle ./codex-bundle.json \
  gpt-5.6-sol
```

Behavior:

- exact-only generation requires only the verified `catalog` resource
- foreign generation additionally requires verified `prompt` and `schema` resources from the same manifest
- build/explain output surfaces the bundle identity as `repository@ref`
- bundle mode cannot be combined with independent local Codex resource overrides or `--codex-ref`
- normal online auto/ref behavior remains unchanged
- the older independent `--catalog-file` / `--codex-prompt-file` / `--codex-schema-file` path remains available for compatibility, but it is still a caller-trust boundary and is not equivalent to a verified bundle
