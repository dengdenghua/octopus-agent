"""Isolated fixture lifecycle and deterministic outcome graders."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.eval_harness import Trajectory, Verdict

TrajectoryValidator = Callable[[Trajectory], str | None]


@dataclass
class IsolatedFixture:
    template: str | Path
    runs_root: str | Path
    preserve_runs: bool = False
    _current: Path | None = field(default=None, init=False, repr=False)

    def setup(self) -> None:
        if self._current is not None:
            raise RuntimeError("fixture trial is already active")
        template = Path(self.template).resolve()
        runs_root = Path(self.runs_root).resolve()
        if not template.is_dir():
            raise ValueError(f"fixture template does not exist: {template}")
        try:
            runs_root.relative_to(template)
        except ValueError:
            pass
        else:
            raise ValueError("runs_root must not be inside the fixture template")
        runs_root.mkdir(parents=True, exist_ok=True)
        destination = runs_root / f"trial-{uuid.uuid4().hex}"
        try:
            shutil.copytree(template, destination, symlinks=True)
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
        self._current = destination

    def workspace(self) -> Path:
        if self._current is None:
            raise RuntimeError("fixture trial is not active")
        return self._current

    def teardown(self) -> None:
        current = self._current
        self._current = None
        if current is not None and not self.preserve_runs:
            shutil.rmtree(current, ignore_errors=False)


@dataclass
class LiveIsolatedFixture(IsolatedFixture):
    server_command: Sequence[str] = field(default_factory=tuple)
    startup_timeout_seconds: float = 10.0
    _server: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)

    def setup(self) -> None:
        super().setup()
        workspace = self.workspace()
        command = [part.replace("{workspace}", str(workspace)) for part in self.server_command]
        if not command:
            super().teardown()
            raise ValueError("live fixture server_command is empty")
        self._server = subprocess.Popen(
            command,
            cwd=workspace,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        url_path = workspace / "EVAL_URL.txt"
        deadline = time.monotonic() + self.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self._server.poll() is not None:
                break
            if url_path.exists() and url_path.read_text(encoding="utf-8").strip():
                return
            time.sleep(0.02)
        self._stop_server()
        super().teardown()
        raise RuntimeError("live fixture server failed to become ready")

    def url(self) -> str:
        return (self.workspace() / "EVAL_URL.txt").read_text(encoding="utf-8").strip()

    def teardown(self) -> None:
        self._stop_server()
        super().teardown()

    def _stop_server(self) -> None:
        process = self._server
        self._server = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@dataclass(frozen=True)
class SubprocessOutcomeGrader:
    fixture: IsolatedFixture
    command: Sequence[str]
    rubric: dict[str, Any]
    timeout_seconds: float = 120.0
    extra_env: dict[str, str] = field(default_factory=dict)
    trajectory_validator: TrajectoryValidator | None = None

    def __call__(self, _trajectory: Trajectory) -> Verdict:
        workspace = self.fixture.workspace()
        command = [part.replace("{workspace}", str(workspace)) for part in self.command]
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
            env={**os.environ, "OCTOPUS_BEHAVIORAL_EVAL": "1", **self.extra_env},
        )
        if completed.returncode != 0:
            reason = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or (f"verifier exited {completed.returncode}")
            )
            return Verdict(
                passed=False,
                score=0.0,
                reason=reason[-4000:],
                rubric=self.rubric,
            )
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return Verdict(
                passed=False,
                score=0.0,
                reason="verifier produced no JSON result",
                rubric=self.rubric,
            )
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            return Verdict(
                passed=False,
                score=0.0,
                reason=f"verifier result is not JSON: {exc}",
                rubric=self.rubric,
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("passed"), bool):
            return Verdict(
                passed=False,
                score=0.0,
                reason="verifier JSON must contain boolean passed",
                rubric=self.rubric,
            )
        raw_score = payload.get("score", 1.0 if payload["passed"] else 0.0)
        score = float(raw_score) if isinstance(raw_score, int | float) else 0.0
        if not 0.0 <= score <= 1.0:
            return Verdict(
                passed=False,
                score=0.0,
                reason="verifier score must be between 0 and 1",
                rubric=self.rubric,
            )
        if payload["passed"] and self.trajectory_validator is not None:
            trajectory_error = self.trajectory_validator(_trajectory)
            if trajectory_error:
                return Verdict(
                    passed=False,
                    score=0.0,
                    reason=trajectory_error,
                    rubric={**self.rubric, "observed_checks": payload.get("checks") or []},
                )
        return Verdict(
            passed=payload["passed"],
            score=score,
            reason=str(payload.get("reason") or ""),
            rubric={**self.rubric, "observed_checks": payload.get("checks") or []},
        )


__all__ = [
    "IsolatedFixture",
    "LiveIsolatedFixture",
    "SubprocessOutcomeGrader",
    "TrajectoryValidator",
]
