"""Pinned local executable discovery does not consult task workspace files."""

import json
import os

import pytest

from runtime.execution import opencode_backend as backend


@pytest.mark.parametrize("kind", ["valid", "outside", "missing", "malformed"])
def test_pinned_discovery_is_confined_to_managed_installation(tmp_path, monkeypatch, kind):
    monkeypatch.delenv("OCTOPUS_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(
        backend, "__file__", str(tmp_path / "runtime" / "execution" / "opencode_backend.py")
    )
    monkeypatch.setattr(backend.shutil, "which", lambda name: "path-fallback")
    state = tmp_path / ".codex-run"
    candidate = state / "tools" / "opencode" / "1.0" / "opencode.exe"
    if kind == "outside":
        candidate = tmp_path / "outside.exe"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if kind != "missing":
        candidate.write_text("fixture")
        if os.name != "nt":
            candidate.chmod(0o700)
    state.mkdir(exist_ok=True)
    (state / "runtime-paths.json").write_text(
        "invalid" if kind == "malformed" else json.dumps({"opencode": str(candidate)}),
        encoding="utf-8",
    )
    assert backend.executable() == (
        str(candidate.resolve()) if kind == "valid" else "path-fallback"
    )
    monkeypatch.setenv("OCTOPUS_OPENCODE_BIN", str(tmp_path / "explicit-missing.exe"))
    assert backend.executable() is None


def test_task_directory_cannot_override_executable(tmp_path, monkeypatch):
    monkeypatch.delenv("OCTOPUS_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(
        backend,
        "__file__",
        str(tmp_path / "trusted" / "runtime" / "execution" / "opencode_backend.py"),
    )
    monkeypatch.setattr(backend.shutil, "which", lambda name: "path-fallback")
    task = tmp_path / "task"
    (task / ".codex-run").mkdir(parents=True)
    (task / ".codex-run" / "runtime-paths.json").write_text(
        json.dumps({"opencode": "untrusted.exe"})
    )
    monkeypatch.chdir(task)
    assert backend.executable() == "path-fallback"
