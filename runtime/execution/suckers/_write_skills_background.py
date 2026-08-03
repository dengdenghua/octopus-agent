"""Background-process machinery for write_skills · extracted from write_skills.py.

Holds ``_BackgroundProcess``, the in-memory registry, the on-disk metadata
helpers, the process liveness probe, and the recovered-metadata snapshotter.

Note: ``_snapshot_background_metadata`` resolves ``_probe_process`` lazily via
``runtime.execution.suckers.write_skills`` so that tests monkeypatching
``write_skills._probe_process`` still observe the patched function at call time.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ._write_skills_common import _BACKGROUND_OUTPUT_CAP, _optional_float


def _background_policy_with_result(
    policy: dict[str, Any],
    *,
    status: str,
    exit_code: int | None,
    started_at: float | None,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> dict[str, Any]:
    from runtime.platform.process.streaming import execution_policy_result_snapshot

    enriched = dict(policy) if isinstance(policy, dict) else {}
    duration_ms: int | None = None
    if started_at is not None:
        duration_ms = int(max(0.0, time.time() - float(started_at)) * 1000)
    enriched["result"] = execution_policy_result_snapshot(
        status=status,
        exit_code=exit_code,
        timed_out=False,
        cancelled=status == "cancelled",
        killed=status == "cancelled",
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        duration_ms=duration_ms,
    )
    return enriched


def _background_execution_policy(
    *,
    sandbox_requested: bool,
    sandbox_workspace: str | None,
    cwd: str | None,
    sandbox_backend: str,
    sandbox_hard: bool,
    env_mode: str,
) -> dict[str, Any]:
    from runtime.platform.process.streaming import execution_policy_snapshot

    return execution_policy_snapshot(
        sandbox_requested=sandbox_requested,
        workspace=sandbox_workspace,
        cwd=cwd,
        backend=sandbox_backend,
        hard=sandbox_hard,
        allow_network=False,
        env_mode=env_mode,
        process_group=True,
        timeout_s=None,
    )


class _BackgroundProcess:
    def __init__(
        self,
        *,
        task_id: str,
        argv: list[str],
        proc: subprocess.Popen[str],
        cwd: str | None,
        sandbox_backend: str = "direct",
        sandbox_hard: bool = False,
        execution_policy: dict[str, Any] | None = None,
        stdout_path: Path,
        stderr_path: Path,
        metadata_path: Path,
    ) -> None:
        self.task_id = task_id
        self.argv = argv
        self.proc = proc
        self.cwd = cwd
        self.sandbox_backend = sandbox_backend
        self.sandbox_hard = sandbox_hard
        self.execution_policy = execution_policy or {}
        self.started_at = time.time()
        self.cancelled = False
        self._lock = threading.Lock()
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.metadata_path = metadata_path
        self._persist(exit_code=None)
        self._wait_thread = threading.Thread(
            target=self._wait_and_persist,
            name=f"background-exec-{task_id}-wait",
            daemon=True,
        )
        self._wait_thread.start()

    def _metadata(self, *, exit_code: int | None) -> dict[str, Any]:
        raw_stdout = _read_background_text(self.stdout_path)
        raw_stderr = _read_background_text(self.stderr_path)
        if self.cancelled:
            status = "cancelled"
        elif exit_code is None:
            status = "running"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"
        return {
            "task_id": self.task_id,
            "argv": self.argv,
            "cwd": self.cwd,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_hard": self.sandbox_hard,
            "execution_policy": _background_policy_with_result(
                self.execution_policy,
                status=status,
                exit_code=exit_code,
                started_at=self.started_at,
                stdout_truncated=len(raw_stdout) > _BACKGROUND_OUTPUT_CAP,
                stderr_truncated=len(raw_stderr) > _BACKGROUND_OUTPUT_CAP,
            ),
            "pid": self.proc.pid,
            "started_at": self.started_at,
            "cancelled": self.cancelled,
            "exit_code": exit_code,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
        }

    def _persist(self, *, exit_code: int | None) -> None:
        with self._lock:
            _write_background_metadata(
                self.metadata_path,
                self._metadata(exit_code=exit_code),
            )

    def _wait_and_persist(self) -> None:
        try:
            exit_code = self.proc.wait()
        except Exception:  # noqa: BLE001
            return
        self._persist(exit_code=exit_code)

    def snapshot(self) -> dict[str, Any]:
        exit_code = self.proc.poll()
        if self.cancelled:
            status = "cancelled"
        elif exit_code is None:
            status = "running"
        elif exit_code == 0:
            status = "completed"
        else:
            status = "failed"
        if exit_code is not None:
            self._persist(exit_code=exit_code)

        raw_stdout = _read_background_text(self.stdout_path)
        raw_stderr = _read_background_text(self.stderr_path)
        execution_policy = _background_policy_with_result(
            self.execution_policy,
            status=status,
            exit_code=exit_code,
            started_at=self.started_at,
            stdout_truncated=len(raw_stdout) > _BACKGROUND_OUTPUT_CAP,
            stderr_truncated=len(raw_stderr) > _BACKGROUND_OUTPUT_CAP,
        )
        return {
            "task_id": self.task_id,
            "status": status,
            "argv": self.argv,
            "cwd": self.cwd,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_hard": self.sandbox_hard,
            "execution_policy": execution_policy,
            "exit_code": exit_code,
            "running": status == "running",
            "stdout": raw_stdout[:_BACKGROUND_OUTPUT_CAP],
            "stderr": raw_stderr[:_BACKGROUND_OUTPUT_CAP],
            "stdout_truncated": len(raw_stdout) > _BACKGROUND_OUTPUT_CAP,
            "stderr_truncated": len(raw_stderr) > _BACKGROUND_OUTPUT_CAP,
            "started_at": self.started_at,
        }

    def kill(self) -> dict[str, Any]:
        if self.proc.poll() is None:
            from runtime.platform.process.tree import terminate_process_tree

            self.cancelled = True
            terminate_process_tree(self.proc)
        else:
            self.cancelled = self.cancelled or False
        self._wait_thread.join(timeout=1)
        return self.snapshot()


_BACKGROUND_PROCESSES: dict[str, _BackgroundProcess] = {}


def _background_root() -> Path:
    from runtime.platform.process.paths import app_paths

    root = app_paths().data_dir / "background_exec"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _background_paths(task_id: str) -> dict[str, Path]:
    task_dir = _background_root() / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return {
        "dir": task_dir,
        "metadata": task_dir / "metadata.json",
        "stdout": task_dir / "stdout.txt",
        "stderr": task_dir / "stderr.txt",
    }


def _write_background_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(path)


def _read_background_metadata(task_id: str) -> dict[str, Any] | None:
    try:
        path = _background_paths(task_id)["metadata"]
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_background_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:_BACKGROUND_OUTPUT_CAP]


def _probe_process(pid: int | None) -> tuple[bool, int | None]:
    if not pid or pid <= 0:
        return False, None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(
                process_query_limited_information,
                False,
                wintypes.DWORD(pid),
            )
            if not handle:
                return False, None
            try:
                code = wintypes.DWORD()
                ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                if not ok:
                    return False, None
                exit_code = int(code.value)
                if exit_code == still_active:
                    return True, None
                return False, exit_code
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return True, None
    try:
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False, os.waitstatus_to_exitcode(status)
    except (
        ChildProcessError
    ):  # expected · already reaped elsewhere, falls through to the liveness probe
        pass
    except OSError:  # expected · falls through to the liveness probe below
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False, None
    return True, None


def _snapshot_background_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    task_id = str(metadata.get("task_id") or "")
    try:
        exit_code = metadata.get("exit_code")
        exit_code = int(exit_code) if exit_code is not None else None
    except (TypeError, ValueError):
        exit_code = None
    try:
        pid = int(metadata.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if exit_code is None:
        # Resolve _probe_process via the write_skills module so tests that
        # monkeypatch ``write_skills._probe_process`` observe the patch here.
        from runtime.execution.suckers.write_skills import _probe_process

        running, probed_exit = _probe_process(pid)
        if probed_exit is not None:
            exit_code = probed_exit
            metadata["exit_code"] = exit_code
            with contextlib.suppress(Exception):
                _write_background_metadata(
                    _background_paths(task_id)["metadata"],
                    metadata,
                )
    else:
        running = False

    cancelled = bool(metadata.get("cancelled"))
    if cancelled:
        status = "cancelled"
    elif running:
        status = "running"
    elif exit_code == 0:
        status = "completed"
    elif exit_code is None:
        status = "unknown"
    else:
        status = "failed"

    default_paths = _background_paths(task_id)
    stdout_path = Path(str(metadata.get("stdout_path") or default_paths["stdout"]))
    stderr_path = Path(str(metadata.get("stderr_path") or default_paths["stderr"]))
    raw_stdout = _read_background_text(stdout_path)
    raw_stderr = _read_background_text(stderr_path)
    execution_policy = (
        dict(metadata["execution_policy"])
        if isinstance(metadata.get("execution_policy"), dict)
        else {}
    )
    execution_policy = _background_policy_with_result(
        execution_policy,
        status=status,
        exit_code=exit_code,
        started_at=_optional_float(metadata.get("started_at")),
        stdout_truncated=len(raw_stdout) > _BACKGROUND_OUTPUT_CAP,
        stderr_truncated=len(raw_stderr) > _BACKGROUND_OUTPUT_CAP,
    )
    return {
        "task_id": task_id,
        "status": status,
        "argv": list(metadata.get("argv") or []),
        "cwd": metadata.get("cwd"),
        "sandbox_backend": str(metadata.get("sandbox_backend") or "direct"),
        "sandbox_hard": bool(metadata.get("sandbox_hard")),
        "execution_policy": execution_policy,
        "pid": pid,
        "exit_code": exit_code,
        "running": status == "running",
        "stdout": raw_stdout[:_BACKGROUND_OUTPUT_CAP],
        "stderr": raw_stderr[:_BACKGROUND_OUTPUT_CAP],
        "stdout_truncated": len(raw_stdout) > _BACKGROUND_OUTPUT_CAP,
        "stderr_truncated": len(raw_stderr) > _BACKGROUND_OUTPUT_CAP,
        "started_at": metadata.get("started_at"),
        "recovered": True,
    }
