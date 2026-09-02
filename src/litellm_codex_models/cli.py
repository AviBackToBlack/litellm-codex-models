from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from .codex import (
    catalog_index,
    fetch_catalog,
    fetch_model_prompt,
    fetch_model_schema_source,
    load_catalog_file,
    load_prompt_file,
    load_schema_file,
    resolve_ref,
)
from .config import AppConfig, load_config
from .errors import AppError
from .litellm import fetch_payload, load_payload_file, select_models
from .mapping import GeneratedModel, canonical_candidates, generate_catalog, resolve_template
from .schema import parse_model_info_schema


def _load_litellm(config: AppConfig, input_path: str | None) -> list[dict[str, Any]]:
    return load_payload_file(input_path) if input_path else fetch_payload(config.litellm)


def _load_codex_catalog(
    config: AppConfig,
    catalog_file: str | None,
    codex_ref: str | None,
) -> tuple[dict[str, Any], str]:
    if catalog_file:
        return load_catalog_file(catalog_file), f"file:{catalog_file}"
    ref, detected_version = resolve_ref(config.codex, codex_ref)
    label = ref if detected_version is None else f"{ref} (Codex {detected_version})"
    return fetch_catalog(config.codex, ref), label


def _load_foreign_prompt(
    config: AppConfig,
    catalog_file: str | None,
    prompt_file: str | None,
    codex_ref: str | None,
) -> str:
    if prompt_file:
        return load_prompt_file(prompt_file)
    if catalog_file:
        raise AppError(
            "Foreign models with --catalog-file also require --codex-prompt-file so no model-specific donor prompt is guessed"
        )
    ref, _detected_version = resolve_ref(config.codex, codex_ref)
    return fetch_model_prompt(config.codex, ref)


def _load_foreign_schema(
    config: AppConfig,
    catalog_file: str | None,
    schema_file: str | None,
    codex_ref: str | None,
) -> str:
    if schema_file:
        return load_schema_file(schema_file)
    if catalog_file:
        raise AppError(
            "Foreign models with --catalog-file also require --codex-schema-file so required ModelInfo fields "
            "are validated against the same Codex version"
        )
    ref, _detected_version = resolve_ref(config.codex, codex_ref)
    return fetch_model_schema_source(config.codex, ref)


def _atomic_write_json(path: Path, payload: dict[str, Any], pretty: bool) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2 if pretty else None, ensure_ascii=False) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def cmd_list(args: argparse.Namespace, config: AppConfig) -> int:
    rows = _load_litellm(config, args.input)
    configured = set(config.models)
    source_rows = rows
    if args.configured:
        by_name = {row.get("model_name"): row for row in rows if isinstance(row.get("model_name"), str)}
        source_rows = [by_name[name] for name in config.models if name in by_name]

    table: list[list[str]] = []
    for row in source_rows:
        name = row.get("model_name")
        if not isinstance(name, str):
            continue
        if args.configured and name not in configured:
            continue
        info = row.get("model_info") or {}
        params = row.get("litellm_params") or {}
        canonical = canonical_candidates(row)
        table.append([
            name,
            str(info.get("mode")),
            str(info.get("litellm_provider")),
            canonical[0] if canonical else str(params.get("model") or ""),
            str(info.get("max_input_tokens") or ""),
        ])
    _print_table(table, ["MODEL_NAME", "MODE", "PROVIDER", "CANONICAL_CANDIDATE", "MAX_INPUT"])
    return 0


def _build(args: argparse.Namespace, config: AppConfig) -> tuple[dict[str, Any], dict[str, GeneratedModel], str]:
    rows = _load_litellm(config, args.input)
    selected = select_models(rows, config.models, strict=config.strict)
    catalog, source = _load_codex_catalog(config, args.catalog_file, args.codex_ref)
    index = catalog_index(catalog)
    has_foreign = any(resolve_template(row, index)[0] is None for row in selected)
    fallback_prompt = None
    model_info_schema = None
    if has_foreign:
        fallback_prompt = _load_foreign_prompt(
            config,
            args.catalog_file,
            args.codex_prompt_file,
            args.codex_ref,
        )
        schema_source = _load_foreign_schema(
            config,
            args.catalog_file,
            args.codex_schema_file,
            args.codex_ref,
        )
        model_info_schema = parse_model_info_schema(schema_source)
    generated, explanations = generate_catalog(
        selected,
        catalog,
        fallback_prompt=fallback_prompt,
        model_info_schema=model_info_schema,
    )
    return generated, explanations, source


def cmd_build(args: argparse.Namespace, config: AppConfig) -> int:
    generated, explanations, source = _build(args, config)
    output = Path(args.output or config.output.path)
    _atomic_write_json(output, generated, config.output.pretty)
    exact = sum(1 for model in explanations.values() if model.kind == "exact")
    foreign = len(explanations) - exact
    print(f"Wrote {len(explanations)} models to {output.expanduser().resolve()}")
    print(f"Codex catalog source: {source}")
    print(f"Template matches: exact={exact}, foreign-fallback={foreign}")
    return 0


def _format_value(value: Any, *, full: bool = False) -> str:
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if not full and len(rendered.encode("utf-8")) > 240:
            kind = "object" if isinstance(value, dict) else "array"
            return f"<{kind}, {len(rendered.encode('utf-8'))} bytes>"
        return rendered
    if isinstance(value, str) and not full and len(value.encode("utf-8")) > 240:
        return f"<string, {len(value.encode('utf-8'))} bytes>"
    return repr(value)


def cmd_explain(args: argparse.Namespace, config: AppConfig) -> int:
    if args.model not in config.models:
        raise AppError(f'Model "{args.model}" is not present in the configured allowlist')
    _generated, explanations, source = _build(args, config)
    model = explanations.get(args.model)
    if model is None:
        raise AppError(f'Model "{args.model}" was not generated')

    print(f"model: {args.model}")
    print(f"kind: {model.kind}")
    print(f"canonical_model: {model.canonical_model}")
    print(f"template_slug: {model.template_slug or '-'}")
    print(f"catalog_source: {source}")
    if model.notes:
        print("notes:")
        for note in model.notes:
            print(f"  - {note}")
    print("fields:")
    for key in sorted(model.entry):
        print(f"  {key}: {_format_value(model.entry[key], full=args.full)}")
        print(f"    source: {model.provenance.get(key, 'unknown')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="litellm-codex-models")
    parser.add_argument("--config", default="litellm-codex-models.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, needs_catalog: bool) -> None:
        p.add_argument("--input", help="Read a saved LiteLLM /v1/model/info JSON instead of calling LiteLLM")
        if needs_catalog:
            p.add_argument("--catalog-file", help="Use a local Codex models.json instead of fetching one")
            p.add_argument("--codex-prompt-file", help="Use a local version-matched Codex models-manager/prompt.md for foreign models")
            p.add_argument("--codex-schema-file", help="Use a local version-matched Codex protocol/src/openai_models.rs for foreign models")
            p.add_argument("--codex-ref", help="Override Codex git ref/tag, e.g. rust-v0.153.0 or main")

    p_list = sub.add_parser("list", help="List LiteLLM models")
    common(p_list, needs_catalog=False)
    p_list.add_argument("--configured", action="store_true", help="Show only configured allowlist models")

    p_build = sub.add_parser("build", help="Generate Codex models.json")
    common(p_build, needs_catalog=True)
    p_build.add_argument("--output", help="Override output path")

    p_explain = sub.add_parser("explain", help="Explain generated field provenance")
    common(p_explain, needs_catalog=True)
    p_explain.add_argument("--full", action="store_true", help="Print full large strings/objects such as model messages")
    p_explain.add_argument("model")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "list":
            return cmd_list(args, config)
        if args.command == "build":
            return cmd_build(args, config)
        if args.command == "explain":
            return cmd_explain(args, config)
        parser.error("unknown command")
    except AppError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0
