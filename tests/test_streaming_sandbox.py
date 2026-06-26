from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from runtime.platform.process.streaming import stream_run
from runtime.safety.sandboxing import sandbox as sandbox_mod
from runtime.safety.sandboxing.sandbox import DirectBackend, SandboxViolation


def test_stream_run_reports_direct_sandbox_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "soft")

    result = stream_run(
        [sys.executable, "-c", "from pathlib import Path; print(Path.cwd())"],
        timeout=10,
        sandbox_dir=str(tmp_path),
    )

    assert result["exit_code"] == 0
    assert Path(result["stdout"].strip()).resolve() == tmp_path.resolve()
    assert result["sandbox_backend"] == "direct"
    assert result["sandbox_hard"] is False
    policy = result["execution_policy"]
    assert policy["schema"] == "octopus.execution_policy.v1"
    assert policy["sandbox_requested"] is True
    assert policy["workspace"] == str(tmp_path.resolve())
    assert policy["cwd"] == str(tmp_path.resolve())
    assert policy["backend"] == "direct"
    assert policy["hard"] is False
    assert policy["allow_network"] is False
    assert policy["env_mode"] == "allowlist"
    assert policy["process_tree_kill"] is True


def test_stream_run_strict_mode_rejects_without_hard_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_PROCESS_SANDBOX", "strict")
    monkeypatch.setattr(sandbox_mod.BubblewrapBackend, "available", staticmethod(lambda: False))
    monkeypatch.setattr(sandbox_mod.SeatbeltBackend, "available", staticmethod(lambda: False))

    result = stream_run(
        [sys.executable, "-c", "print('should not run')"],
        timeout=10,
        sandbox_dir=str(tmp_path),
    )

    assert "error" in result
    assert "strict process sandbox requested" in result["error"]
    assert result["execution_policy"]["schema"] == "octopus.execution_policy.v1"
    assert result["execution_policy"]["sandbox_requested"] is True


def test_stream_run_uses_selected_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TaggingBackend(DirectBackend):
        def transform(self, argv, env, cwd, policy):  # type: ignore[no-untyped-def]
            return (
                [
                    sys.executable,
                    "-c",
                    "print('wrapped')",
                ],
                env,
                cwd,
            )

    monkeypatch.setattr(
        sandbox_mod,
        "select_process_backend",
        lambda: sandbox_mod.BackendChoice(TaggingBackend(), "tagged", hard=True),
    )

    result = stream_run(
        [sys.executable, "-c", "print('original')"],
        timeout=10,
        sandbox_dir=str(tmp_path),
    )

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "wrapped"
    assert result["sandbox_backend"] == "tagged"
    assert result["sandbox_hard"] is True
    assert result["execution_policy"]["backend"] == "tagged"
    assert result["execution_policy"]["hard"] is True


def test_stream_run_surfaces_backend_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectingBackend(DirectBackend):
        def transform(self, argv, env, cwd, policy):  # type: ignore[no-untyped-def]
            raise SandboxViolation("backend rejected")

    monkeypatch.setattr(
        sandbox_mod,
        "select_process_backend",
        lambda: sandbox_mod.BackendChoice(RejectingBackend(), "reject", hard=True),
    )

    result = stream_run(
        [sys.executable, "-c", "print('should not run')"],
        timeout=10,
        sandbox_dir=str(tmp_path),
    )

    assert result["error"] == "sandbox_violation: backend rejected"
    assert result["execution_policy"]["schema"] == "octopus.execution_policy.v1"
    assert result["execution_policy"]["sandbox_requested"] is True


def test_stream_run_timeout_kills_child_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived.txt"
    code = (
        "import subprocess, sys, time\n"
        "subprocess.Popen([\n"
        "    sys.executable,\n"
        "    '-c',\n"
        f"    \"import pathlib, time; time.sleep(1.0); pathlib.Path({str(marker)!r}).write_text('alive')\",\n"
        "])\n"
        "time.sleep(10)\n"
    )

    result = stream_run(
        [sys.executable, "-c", code],
        timeout=0.2,
        cwd=str(tmp_path),
    )

    assert result["timed_out"] is True
    assert result["killed"] is True
    time.sleep(1.2)
    assert not marker.exists()
