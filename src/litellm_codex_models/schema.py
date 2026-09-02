from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import AppError


_FIELD_RE = re.compile(r"^\s*pub\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.+),\s*$")


@dataclass(frozen=True)
class ModelInfoSchema:
    fields: frozenset[str]
    required_fields: frozenset[str]


def _model_info_body(source: str) -> str:
    marker = "pub struct ModelInfo {"
    start = source.find(marker)
    if start < 0:
        raise AppError("Could not find `pub struct ModelInfo` in the version-matched Codex schema source")

    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise AppError("Unterminated `pub struct ModelInfo` in the version-matched Codex schema source")


def parse_model_info_schema(source: str) -> ModelInfoSchema:
    body = _model_info_body(source)
    fields: set[str] = set()
    required: set[str] = set()
    pending_attrs: list[str] = []
    attr_buffer: list[str] | None = None
    attr_depth = 0

    for line in body.splitlines():
        stripped = line.strip()

        if attr_buffer is not None:
            attr_buffer.append(stripped)
            attr_depth += stripped.count("[") - stripped.count("]")
            if attr_depth <= 0:
                pending_attrs.append(" ".join(attr_buffer))
                attr_buffer = None
            continue

        if stripped.startswith("#["):
            attr_buffer = [stripped]
            attr_depth = stripped.count("[") - stripped.count("]")
            if attr_depth <= 0:
                pending_attrs.append(stripped)
                attr_buffer = None
            continue

        match = _FIELD_RE.match(line)
        if not match:
            # Keep serde attributes across doc comments/blank lines, but discard
            # unrelated attributes once some other Rust item is encountered.
            if stripped and not stripped.startswith("///") and not stripped.startswith("//"):
                pending_attrs.clear()
            continue

        name, rust_type = match.groups()
        attrs = " ".join(pending_attrs)
        pending_attrs.clear()
        fields.add(name)

        serde_default = "serde" in attrs and ("default" in attrs or "skip_deserializing" in attrs)
        option_type = rust_type.strip().startswith("Option<")
        if not serde_default and not option_type:
            required.add(name)

    if not fields:
        raise AppError("No fields found in the version-matched Codex `ModelInfo` schema")
    return ModelInfoSchema(fields=frozenset(fields), required_fields=frozenset(required))