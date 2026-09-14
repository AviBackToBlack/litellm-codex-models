from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from .errors import AppError


BUNDLE_SCHEMA_VERSION = 1
RESOURCE_ROLES = ("catalog", "prompt", "schema")
_SHA256_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
_DRIVE_PREFIX_RE = re.compile(r"^[A-Za-z]:.*$")


@dataclass(frozen=True)
class VerifiedBundleResource:
    role: str
    relative_path: str
    path: Path
    sha256: str
    content: bytes

    def text(self) -> str:
        try:
            return self.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AppError(
                f'Codex bundle resource "{self.role}" is not valid UTF-8: {self.relative_path}'
            ) from exc


@dataclass(frozen=True)
class CodexBundle:
    schema_version: int
    repository: str
    ref: str
    manifest_path: Path
    resources: Mapping[str, VerifiedBundleResource]

    @property
    def identity(self) -> str:
        return f"{self.repository}@{self.ref}"

    def resource(self, role: str, *, required: bool = True) -> VerifiedBundleResource | None:
        resource = self.resources.get(role)
        if resource is None and required:
            raise AppError(
                f'Codex bundle {self.manifest_path} does not contain required resource "{role}"'
            )
        return resource


def _require_exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if not missing and not extra:
        return

    detail: list[str] = []
    if missing:
        detail.append("missing " + ", ".join(missing))
    if extra:
        detail.append("unexpected " + ", ".join(extra))
    raise AppError(f"Invalid {context}: " + "; ".join(detail))


def _identity_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AppError(f"Codex bundle {field} must be a non-empty string without surrounding whitespace")
    return value


def _resource_relative_parts(raw_path: Any, role: str) -> tuple[str, ...]:
    if not isinstance(raw_path, str) or not raw_path or raw_path != raw_path.strip():
        raise AppError(f'Codex bundle resource "{role}" path must be a non-empty relative POSIX path')
    if "\\" in raw_path:
        raise AppError(f'Codex bundle resource "{role}" path must use forward slashes')

    parts = tuple(raw_path.split("/"))
    drive_qualified = bool(parts and _DRIVE_PREFIX_RE.fullmatch(parts[0]))
    if raw_path.startswith("/") or drive_qualified or any(part in {"", ".", ".."} for part in parts):
        raise AppError(f'Codex bundle resource "{role}" path must stay inside the bundle directory')
    return parts


def _load_resource(
    root: Path,
    role: str,
    spec: Any,
    seen_paths: set[str],
) -> VerifiedBundleResource:
    if not isinstance(spec, dict):
        raise AppError(f'Codex bundle resource "{role}" must be an object')
    _require_exact_keys(spec, {"path", "sha256"}, f'Codex bundle resource "{role}"')

    raw_path = spec["path"]
    parts = _resource_relative_parts(raw_path, role)
    normalized_path = "/".join(parts)
    if normalized_path in seen_paths:
        raise AppError(f"Codex bundle resources must use distinct paths; duplicate: {normalized_path}")
    seen_paths.add(normalized_path)

    expected_digest = spec["sha256"]
    if not isinstance(expected_digest, str) or _SHA256_RE.fullmatch(expected_digest) is None:
        raise AppError(f'Codex bundle resource "{role}" sha256 must be exactly 64 hexadecimal characters')
    expected_digest = expected_digest.lower()

    path = root.joinpath(*parts).resolve()
    if not path.is_relative_to(root):
        raise AppError(f'Codex bundle resource "{role}" resolves outside the bundle directory')

    try:
        content = path.read_bytes()
    except FileNotFoundError as exc:
        raise AppError(f'Codex bundle resource "{role}" not found: {normalized_path}') from exc
    except OSError as exc:
        raise AppError(f'Failed to read Codex bundle resource "{role}": {normalized_path}: {exc}') from exc

    actual_digest = sha256(content).hexdigest()
    if actual_digest != expected_digest:
        raise AppError(
            f'Codex bundle resource "{role}" failed SHA-256 verification: {normalized_path}; '
            f"expected {expected_digest}, got {actual_digest}"
        )

    return VerifiedBundleResource(
        role=role,
        relative_path=normalized_path,
        path=path,
        sha256=actual_digest,
        content=content,
    )


def load_codex_bundle(path: str | Path) -> CodexBundle:
    manifest_path = Path(path).expanduser().resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Codex bundle manifest not found: {manifest_path}") from exc
    except UnicodeDecodeError as exc:
        raise AppError(f"Codex bundle manifest is not valid UTF-8: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid Codex bundle manifest JSON in {manifest_path}: {exc}") from exc
    except OSError as exc:
        raise AppError(f"Failed to read Codex bundle manifest {manifest_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise AppError("Codex bundle manifest must be a JSON object")
    _require_exact_keys(payload, {"schema_version", "codex", "files"}, "Codex bundle manifest")

    schema_version = payload["schema_version"]
    if type(schema_version) is not int or schema_version != BUNDLE_SCHEMA_VERSION:
        raise AppError(
            f"Unsupported Codex bundle schema_version {schema_version!r}; expected {BUNDLE_SCHEMA_VERSION}"
        )

    codex = payload["codex"]
    if not isinstance(codex, dict):
        raise AppError("Codex bundle codex identity must be an object")
    _require_exact_keys(codex, {"repository", "ref"}, "Codex bundle codex identity")
    repository = _identity_string(codex["repository"], "codex.repository")
    ref = _identity_string(codex["ref"], "codex.ref")

    files = payload["files"]
    if not isinstance(files, dict):
        raise AppError("Codex bundle files must be an object")
    unknown_roles = sorted(set(files) - set(RESOURCE_ROLES))
    if unknown_roles:
        raise AppError("Codex bundle contains unsupported resource role(s): " + ", ".join(unknown_roles))
    if "catalog" not in files:
        raise AppError('Codex bundle must contain the required "catalog" resource')

    root = manifest_path.parent.resolve()
    seen_paths: set[str] = set()
    resources = {
        role: _load_resource(root, role, files[role], seen_paths)
        for role in RESOURCE_ROLES
        if role in files
    }

    return CodexBundle(
        schema_version=schema_version,
        repository=repository,
        ref=ref,
        manifest_path=manifest_path,
        resources=MappingProxyType(resources),
    )
