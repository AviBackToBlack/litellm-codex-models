from __future__ import annotations

from hashlib import sha256
import json

import pytest

from litellm_codex_models.bundle import BUNDLE_SCHEMA_VERSION, load_codex_bundle
from litellm_codex_models.errors import AppError


def _digest(content: bytes) -> str:
    return sha256(content).hexdigest()


def _resource(tmp_path, name: str, content: bytes) -> dict[str, str]:
    (tmp_path / name).write_bytes(content)
    return {"path": name, "sha256": _digest(content)}


def _write_manifest(tmp_path, files: dict, **overrides):
    payload = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "codex": {
            "repository": "openai/codex",
            "ref": "rust-v0.153.0",
        },
        "files": files,
    }
    payload.update(overrides)
    path = tmp_path / "codex-bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_catalog_only_bundle_is_valid_for_lightweight_exact_offline_use(tmp_path):
    catalog = b'{"models": []}\n'
    manifest = _write_manifest(
        tmp_path,
        {"catalog": _resource(tmp_path, "models.json", catalog)},
    )

    bundle = load_codex_bundle(manifest)

    assert bundle.identity == "openai/codex@rust-v0.153.0"
    assert bundle.repository == "openai/codex"
    assert bundle.ref == "rust-v0.153.0"
    assert bundle.resource("catalog").content == catalog
    assert bundle.resource("prompt", required=False) is None
    assert bundle.resource("schema", required=False) is None


def test_full_bundle_verifies_all_declared_resources(tmp_path):
    catalog = b'{"models": []}\n'
    prompt = "Generic Codex prompt.\n".encode()
    schema = b"pub struct ModelInfo {}\n"
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": _resource(tmp_path, "models.json", catalog),
            "prompt": _resource(tmp_path, "prompt.md", prompt),
            "schema": _resource(tmp_path, "openai_models.rs", schema),
        },
    )

    bundle = load_codex_bundle(manifest)

    assert bundle.resource("prompt").text() == "Generic Codex prompt.\n"
    assert bundle.resource("schema").text() == "pub struct ModelInfo {}\n"
    assert tuple(bundle.resources) == ("catalog", "prompt", "schema")


def test_digest_mismatch_fails_closed(tmp_path):
    catalog = b'{"models": []}\n'
    spec = _resource(tmp_path, "models.json", catalog)
    manifest = _write_manifest(tmp_path, {"catalog": spec})
    (tmp_path / "models.json").write_bytes(b'{"models": [{"slug": "tampered"}]}\n')

    with pytest.raises(AppError, match="failed SHA-256 verification"):
        load_codex_bundle(manifest)


def test_manifest_requires_catalog_but_not_foreign_only_resources(tmp_path):
    prompt = _resource(tmp_path, "prompt.md", b"prompt\n")
    manifest = _write_manifest(tmp_path, {"prompt": prompt})

    with pytest.raises(AppError, match='required "catalog" resource'):
        load_codex_bundle(manifest)


def test_unsupported_manifest_schema_version_fails_closed(tmp_path):
    catalog = _resource(tmp_path, "models.json", b'{"models": []}\n')
    manifest = _write_manifest(tmp_path, {"catalog": catalog}, schema_version=2)

    with pytest.raises(AppError, match="Unsupported Codex bundle schema_version"):
        load_codex_bundle(manifest)


def test_boolean_schema_version_is_not_accepted_as_integer_one(tmp_path):
    catalog = _resource(tmp_path, "models.json", b'{"models": []}\n')
    manifest = _write_manifest(tmp_path, {"catalog": catalog}, schema_version=True)

    with pytest.raises(AppError, match="Unsupported Codex bundle schema_version"):
        load_codex_bundle(manifest)


def test_resource_parent_traversal_is_rejected(tmp_path):
    outside = tmp_path.parent / "outside-models.json"
    outside.write_bytes(b'{"models": []}\n')
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": {
                "path": "../outside-models.json",
                "sha256": _digest(outside.read_bytes()),
            }
        },
    )

    with pytest.raises(AppError, match="must stay inside the bundle directory"):
        load_codex_bundle(manifest)


def test_absolute_resource_path_is_rejected(tmp_path):
    content = b'{"models": []}\n'
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": {
                "path": "/models.json",
                "sha256": _digest(content),
            }
        },
    )

    with pytest.raises(AppError, match="must stay inside the bundle directory"):
        load_codex_bundle(manifest)


def test_drive_qualified_resource_path_is_rejected_portably(tmp_path):
    content = b'{"models": []}\n'
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": {
                "path": "C:/models.json",
                "sha256": _digest(content),
            }
        },
    )

    with pytest.raises(AppError, match="must stay inside the bundle directory"):
        load_codex_bundle(manifest)


def test_resource_roles_must_use_distinct_paths(tmp_path):
    content = b"same bytes\n"
    spec = _resource(tmp_path, "shared.txt", content)
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": spec,
            "prompt": dict(spec),
        },
    )

    with pytest.raises(AppError, match="resources must use distinct paths"):
        load_codex_bundle(manifest)


def test_per_resource_ref_is_rejected_so_identity_is_manifest_wide(tmp_path):
    catalog = _resource(tmp_path, "models.json", b'{"models": []}\n')
    catalog["ref"] = "rust-v0.999.0"
    manifest = _write_manifest(tmp_path, {"catalog": catalog})

    with pytest.raises(AppError, match="unexpected ref"):
        load_codex_bundle(manifest)


def test_unknown_resource_role_is_rejected(tmp_path):
    catalog = _resource(tmp_path, "models.json", b'{"models": []}\n')
    extra = _resource(tmp_path, "other.txt", b"other\n")
    manifest = _write_manifest(
        tmp_path,
        {
            "catalog": catalog,
            "future_resource": extra,
        },
    )

    with pytest.raises(AppError, match="unsupported resource role"):
        load_codex_bundle(manifest)


def test_non_utf8_resource_can_be_digest_verified_but_not_read_as_text(tmp_path):
    content = b"\xff\xfe"
    manifest = _write_manifest(
        tmp_path,
        {"catalog": _resource(tmp_path, "models.json", content)},
    )
    bundle = load_codex_bundle(manifest)

    with pytest.raises(AppError, match="not valid UTF-8"):
        bundle.resource("catalog").text()
