"""Shell execution skills for write_skills · extracted from write_skills.py.

Contains ``exec_shell`` / ``background_exec`` / ``read_background_output`` /
``kill_background_exec`` (and their shell aliases) and ``ipython``.
"""
from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.safety.env_scrub import scrub_credential_env as _scrub_unconfined_env

from ._write_skills_background import (
    _BACKGROUND_PROCESSES,
    _background_execution_policy,
    _background_paths,
    _BackgroundProcess,
    _read_background_metadata,
    _snapshot_background_metadata,
    _write_background_metadata,
)
from ._write_skills_common import (
    _DEFAULT_EXEC_TIMEOUT_S,
    _EXEC_OUTPUT_CAP,
    _ensure_sandbox,
    _error_with_execution_policy,
    _execution_policy_from_result,
    _parse_command,
)


def _exec_shell(
    command: str | list[str] = "",
    *,
    cwd: str | None = None,
    timeout_s: float = _DEFAULT_EXEC_TIMEOUT_S,
    env: dict[str, str] | None = None,
    sandbox_dir: str | None = None,
    run_in_background: bool = False,
    background: bool = False,
    **_kw: Any,
) -> dict[str, Any]:
    if run_in_background or background:
        return _background_exec(
            command=command,
            cwd=cwd,
            env=env,
            sandbox_dir=sandbox_dir,
        )

    argv, parse_error = _parse_command(command)
    if parse_error:
        return {"error": parse_error}
    assert argv is not None

    if cwd is not None:
        resolved_cwd, err = _ensure_sandbox(cwd, sandbox_dir)
        if err:
            return {"error": err}
        if not resolved_cwd.is_dir():
            return {"error": f"cwd not a directory: {resolved_cwd}"}
        cwd_str = str(resolved_cwd)
    elif sandbox_dir is not None:
        sandbox_root = Path(sandbox_dir).expanduser().resolve()
        if not sandbox_root.is_dir():
            return {"error": f"sandbox_violation: workspace not a directory: {sandbox_root}"}
        cwd_str = str(sandbox_root)
    else:
        cwd_str = None

    run_env = None
    if sandbox_dir is not None:
        # Confined exec: the sandbox backend (in ``stream_run``) owns the
        # environment. When the caller supplies an explicit env we pass
        # only that; otherwise leave ``run_env`` None so the backend
        # builds its allowlisted env.
        if env is not None:
            run_env = {str(k): str(v) for k, v in env.items()}
    else:
        # UNCONFINED exec (no sandbox_dir): never hand the child our full
        # os.environ — a model-driven shell on the compat-gateway path
        # (no bound Session) could echo $ANTHROPIC_API_KEY & friends.
        # Start from a credential-scrubbed copy and lay any explicit
        # caller env on top.
        run_env = _scrub_unconfined_env(env)

    from runtime.platform.process.streaming import stream_run

    r = stream_run(
        argv,
        cwd=cwd_str,
        env=run_env,
        timeout=timeout_s,
        output_cap_bytes=_EXEC_OUTPUT_CAP,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r and "exit_code" not in r:
        msg = r["error"]
        if "FileNotFoundError" in msg or "not found" in msg.lower():
            return _error_with_execution_policy(f"command not found: {msg}", r, argv=argv)
        return _error_with_execution_policy(f"exec_failed: {msg}", r, argv=argv)
    if r.get("timed_out"):
        return {
            "error": f"timeout after {timeout_s}s",
            "timed_out": True,
            "argv": argv,
            "stdout": r["stdout"],
            "stderr": r["stderr"],
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "argv": argv,
        "exit_code": r["exit_code"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "stdout_truncated": r["stdout_truncated"],
        "stderr_truncated": r["stderr_truncated"],
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }


def _background_exec(
    command: str | list[str] = "",
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    argv, parse_error = _parse_command(command)
    if parse_error:
        return {"error": parse_error}
    assert argv is not None

    if cwd is not None:
        resolved_cwd, err = _ensure_sandbox(cwd, sandbox_dir)
        if err:
            return {"error": err}
        if not resolved_cwd.is_dir():
            return {"error": f"cwd not a directory: {resolved_cwd}"}
        cwd_str = str(resolved_cwd)
    elif sandbox_dir is not None:
        sandbox_root = Path(sandbox_dir).expanduser().resolve()
        if not sandbox_root.is_dir():
            return {"error": f"sandbox_violation: workspace not a directory: {sandbox_root}"}
        cwd_str = str(sandbox_root)
    else:
        cwd_str = None

    run_env = None
    sandbox_backend = "direct"
    sandbox_hard = False
    sandbox_workspace: str | None = None
    env_mode = "custom" if env is not None else "inherit"
    if sandbox_dir is not None:
        from runtime.platform.process.streaming import _sandbox_extra_env
        from runtime.safety.sandboxing.sandbox import (
            SandboxPolicy,
            SandboxViolation,
            select_process_backend,
        )

        sandbox_root = Path(sandbox_dir).expanduser().resolve()
        sandbox_workspace = str(sandbox_root)
        policy = SandboxPolicy(
            workspace=sandbox_root,
            extra_env=_sandbox_extra_env(env),
        )
        run_env = policy.env_for()
        env_mode = "allowlist"
        try:
            choice = select_process_backend()
            argv, run_env, transformed_cwd = choice.backend.transform(
                list(argv),
                run_env,
                Path(cwd_str),
                policy,
            )
        except SandboxViolation as exc:
            return {"error": f"sandbox_violation: {exc}", "argv": argv}
        cwd_str = str(transformed_cwd)
        sandbox_backend = choice.name
        sandbox_hard = choice.hard
    else:
        # UNCONFINED background exec: scrub credential vars from the
        # inherited environment (see ``_exec_shell``), applied whether or
        # not the caller passed an explicit env.
        run_env = _scrub_unconfined_env(env)
        env_mode = "scrubbed"

    execution_policy = _background_execution_policy(
        sandbox_requested=sandbox_dir is not None,
        sandbox_workspace=sandbox_workspace,
        cwd=cwd_str,
        sandbox_backend=sandbox_backend,
        sandbox_hard=sandbox_hard,
        env_mode=env_mode,
    )

    task_id = f"bg_{uuid4().hex[:16]}"
    paths = _background_paths(task_id)
    try:
        from runtime.platform.process.tree import process_group_kwargs

        stdout_fh = paths["stdout"].open("w", encoding="utf-8", errors="replace")
        stderr_fh = paths["stderr"].open("w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=stdout_fh,
            stderr=stderr_fh,
            text=True,
            cwd=cwd_str,
            env=run_env,
            bufsize=1,
            shell=False,
            **process_group_kwargs(),
        )
    except FileNotFoundError as e:
        return {"error": f"command not found: {e}", "argv": argv}
    except OSError as e:
        return {"error": f"exec_failed: {e}", "argv": argv}
    finally:
        with contextlib.suppress(UnboundLocalError, OSError):
            stdout_fh.close()
        with contextlib.suppress(UnboundLocalError, OSError):
            stderr_fh.close()

    task = _BackgroundProcess(
        task_id=task_id,
        argv=argv,
        proc=proc,
        cwd=cwd_str,
        sandbox_backend=sandbox_backend,
        sandbox_hard=sandbox_hard,
        execution_policy=execution_policy,
        stdout_path=paths["stdout"],
        stderr_path=paths["stderr"],
        metadata_path=paths["metadata"],
    )
    _BACKGROUND_PROCESSES[task_id] = task
    snap = task.snapshot()
    snap["message"] = (
        "background process started; call read_background_output with task_id to poll output/status"
    )
    return snap


def _read_background_output(
    task_id: str = "",
    **_kw: Any,
) -> dict[str, Any]:
    if not task_id:
        return {"error": "missing task_id"}
    task = _BACKGROUND_PROCESSES.get(task_id)
    if task is None:
        metadata = _read_background_metadata(task_id)
        if metadata is None:
            return {"error": f"unknown task_id: {task_id}", "task_id": task_id}
        return _snapshot_background_metadata(metadata)
    return task.snapshot()


def _read_shell_output(
    task_id: str = "",
    **kw: Any,
) -> dict[str, Any]:
    return _read_background_output(task_id=task_id, **kw)


def _kill_background_exec(
    task_id: str = "",
    **_kw: Any,
) -> dict[str, Any]:
    if not task_id:
        return {"error": "missing task_id"}
    task = _BACKGROUND_PROCESSES.get(task_id)
    if task is None:
        metadata = _read_background_metadata(task_id)
        if metadata is None:
            return {"error": f"unknown task_id: {task_id}", "task_id": task_id}
        try:
            pid = int(metadata.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid > 0:
            from runtime.platform.process.tree import terminate_pid_tree

            with contextlib.suppress(Exception):
                terminate_pid_tree(pid)
        metadata["cancelled"] = True
        with contextlib.suppress(Exception):
            _write_background_metadata(_background_paths(task_id)["metadata"], metadata)
        return _snapshot_background_metadata(metadata)
    return task.kill()


def _kill_shell(
    task_id: str = "",
    **kw: Any,
) -> dict[str, Any]:
    return _kill_background_exec(task_id=task_id, **kw)


def _ipython(
    code: str = "",
    *,
    cwd: str | None = None,
    timeout_s: float = _DEFAULT_EXEC_TIMEOUT_S,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Execute a Python snippet with the current interpreter."""
    if not code.strip():
        return {"error": "missing code"}

    cwd_str = None
    if cwd is not None:
        resolved_cwd, err = _ensure_sandbox(cwd, sandbox_dir)
        if err:
            return {"error": err}
        if not resolved_cwd.is_dir():
            return {"error": f"cwd not a directory: {resolved_cwd}"}
        cwd_str = str(resolved_cwd)

    from runtime.platform.process.streaming import stream_run

    r = stream_run(
        [sys.executable, "-c", code],
        cwd=cwd_str,
        timeout=timeout_s,
        output_cap_bytes=_EXEC_OUTPUT_CAP,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r and "exit_code" not in r:
        return _error_with_execution_policy(f"exec_failed: {r['error']}", r)
    if r.get("timed_out"):
        return {
            "error": f"timeout after {timeout_s}s",
            "timed_out": True,
            "stdout": r["stdout"],
            "stderr": r["stderr"],
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "exit_code": r["exit_code"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "success": r["exit_code"] == 0,
        "stdout_truncated": r["stdout_truncated"],
        "stderr_truncated": r["stderr_truncated"],
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }
