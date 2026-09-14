# Offline Codex bundle v1

## Goal

Offline Codex resources must carry one explicit source identity and must not rely on the caller remembering which `models.json`, fallback prompt, and Rust `ModelInfo` schema belong together.

Bundle v1 is the verification core for the v0.3 offline-resource path. Production CLI wiring is intentionally a later slice.

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

The integration slice must use the manifest identity as the offline Codex source. It must not combine a bundle with independently supplied catalog/prompt/schema files or silently substitute resources from another ref.

## Integrity contract

Every declared resource has a SHA-256 digest over its raw bytes. The loader verifies every declared digest before returning a bundle.

Resource paths are manifest-relative POSIX paths. Absolute paths, parent traversal, empty or dot path components, backslashes, duplicate resource paths, and paths that resolve outside the bundle directory fail closed.

The loader retains the verified bytes in memory. Later consumers should use those verified bytes rather than re-reading the path and reopening a time-of-check/time-of-use gap.

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

## Planned CLI integration

The next slice should add a single offline bundle option and make it the verified replacement for the current independent local-file trust boundary.

Expected behavior:

- exact-only generation requires only the verified `catalog` resource
- foreign generation additionally requires verified `prompt` and `schema` resources from the same manifest
- bundle identity is surfaced in build/explain output
- combining bundle mode with independent local Codex resource overrides fails closed
- normal online auto/ref behavior remains unchanged
