from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .config import LiteLLMConfig
from .errors import AppError


def _validate_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise AppError("LiteLLM response must be a JSON object with a data[] array")
    rows = payload["data"]
    if not all(isinstance(row, dict) for row in rows):
        raise AppError("LiteLLM data[] contains a non-object entry")
    return rows


def load_payload_file(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AppError(f"LiteLLM input file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AppError(f"Invalid LiteLLM JSON in {path}: {exc}") from exc
    return _validate_payload(payload)


def fetch_payload(config: LiteLLMConfig) -> list[dict[str, Any]]:
    if not config.url:
        raise AppError("litellm.url is required when --input is not supplied")

    key = os.environ.get(config.api_key_env)
    if not key:
        raise AppError(f"Environment variable {config.api_key_env} is not set")

    url = f"{config.url.rstrip('/')}/{config.endpoint.lstrip('/')}"
    request = Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": f"litellm-codex-models/{__version__}",
        },
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise AppError(f"LiteLLM request failed: HTTP {exc.code} {exc.reason}") from exc
    except URLError as exc:
        raise AppError(f"LiteLLM request failed: {exc.reason}") from exc

    return _validate_payload(payload)


def index_model_groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        name = row.get("model_name")
        if not isinstance(name, str) or not name:
            continue
        result.setdefault(name, []).append(row)
    return result


def select_model_groups(
    rows: list[dict[str, Any]],
    allowlist: tuple[str, ...],
    *,
    strict: bool,
) -> list[list[dict[str, Any]]]:
    index = index_model_groups(rows)
    selected: list[list[dict[str, Any]]] = []
    missing: list[str] = []

    for name in allowlist:
        group = index.get(name)
        if group is None:
            missing.append(name)
            continue
        selected.append(group)

    if missing and strict:
        raise AppError("Requested models not found in LiteLLM: " + ", ".join(missing))
    return selected
