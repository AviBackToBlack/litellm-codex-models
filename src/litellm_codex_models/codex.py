from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import CodexConfig
from .errors import AppError


_VERSION_RE = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)")


def detect_codex_version(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise AppError(f"Codex binary not found: {binary}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise AppError(f"Failed to run {binary} --version: {detail or exc.returncode}") from exc

    text = f"{completed.stdout}\n{completed.stderr}"
    match = _VERSION_RE.search(text)
    if not match:
        raise AppError(f"Could not parse Codex version from: {text.strip()!r}")
    return match.group(1)


def resolve_ref(config: CodexConfig, override_ref: str | None = None) -> tuple[str, str | None]:
    if override_ref:
        return override_ref, None
    if config.ref:
        return config.ref, None
    if config.version != "auto":
        if config.version == "main":
            return "main", None
        return f"rust-v{config.version}", config.version
    version = detect_codex_version(config.binary)
    return f"rust-v{version}", version


def _validate_catalog(payload: Any, source: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise AppError(f"Codex catalog from {source} must contain models[]")
    if not all(isinstance(model, dict) and isinstance(model.get("slug"), str) for model in payload["models"]):
        raise AppError(f"Codex catalog from {source} contains an invalid model entry")
    return payload


def load_catalog_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"Codex catalog file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid Codex catalog JSON in {path}: {exc}") from exc
    return _validate_catalog(payload, str(path))


def fetch_catalog(config: CodexConfig, ref: str) -> dict[str, Any]:
    owner_repo = config.repository.strip("/")
    path = "codex-rs/models-manager/models.json"
    url = f"https://raw.githubusercontent.com/{owner_repo}/{quote(ref, safe='')}/{path}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "litellm-codex-models/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise AppError(
                f"No Codex models.json found at ref {ref!r}. "
                "Use --codex-ref, [codex].ref, or --catalog-file to select a compatible catalog."
            ) from exc
        raise AppError(f"Codex catalog request failed: HTTP {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise AppError(f"Codex catalog request failed: {exc.reason}") from exc
    return _validate_catalog(payload, url)


def catalog_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {model["slug"]: model for model in catalog["models"]}
