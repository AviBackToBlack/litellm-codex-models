import subprocess

import pytest

from litellm_codex_models.codex import detect_codex_version, resolve_ref
from litellm_codex_models.config import CodexConfig


def test_detect_codex_version(monkeypatch):
    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, "codex-cli 0.148.0-alpha.9\n", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert detect_codex_version("codex") == "0.148.0-alpha.9"


def test_auto_version_maps_to_rust_tag(monkeypatch):
    monkeypatch.setattr("litellm_codex_models.codex.detect_codex_version", lambda _binary: "0.153.0")
    ref, version = resolve_ref(CodexConfig())
    assert ref == "rust-v0.153.0"
    assert version == "0.153.0"


def test_explicit_ref_wins():
    ref, version = resolve_ref(CodexConfig(ref="main"))
    assert ref == "main"
    assert version is None
