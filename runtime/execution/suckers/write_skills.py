from __future__ import annotations

# ╔════════════════════════════════════════════════════════════════════════╗
# ║ write_skills.py · navigation map (1934 lines, ~50 skills).             ║
# ║                                                                        ║
# ║   §1 _BackgroundProcess (subprocess wrapper)         ~L26              ║
# ║   §2 background metadata helpers                      ~L127             ║
# ║   §3 sandbox + path resolution                        ~L289             ║
# ║   §4 file write/append/edit primitives                ~L307             ║
# ║   §5 multi_edit_file                                  ~L502             ║
# ║   §6 exec_shell + background_exec + kill              ~L594             ║
# ║   §7 ipython / repl skill                             ~L789             ║
# ║   §8 git core (status/diff/log/add/commit/branch)     ~L846             ║
# ║   §9 register_write_skills (the sucker entrypoint)    ~L1112            ║
# ║   §10 register_git_skills                             ~L1233            ║
# ║   §11 register_exec_skill                             ~L1345            ║
# ║   §12 git network (push/pull/checkout/stash/PR)       ~L1505            ║
# ║   §13 register_git_network_skills                     ~L1660            ║
# ║   §14 run_tests / lint / format                       ~L1733            ║
# ║   §15 register_code_quality_skills                    ~L1878            ║
# ║                                                                        ║
# ║ Each skill is a thin Skill(...) registration; the work happens in the  ║
# ║ free function above it. Splitting risks scattering the skill ↔ helper ║
# ║ pairs across files for no real call-site win.                          ║
# ╚════════════════════════════════════════════════════════════════════════╝
import contextlib
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.safety.env_scrub import scrub_credential_env as _scrub_unconfined_env

from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase

_DEFAULT_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
_DEFAULT_EXEC_TIMEOUT_S = 30.0
_EXEC_OUTPUT_CAP = 200_000  # Implementation note.

_BACKGROUND_OUTPUT_CAP = 200_000


def _execution_policy_from_result(result: dict[str, Any]) -> dict[str, Any]:
    policy = result.get("execution_policy")
    return dict(policy) if isinstance(policy, dict) else {}


def _error_with_execution_policy(
    error: str,
    result: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": error, **extra}
    policy = _execution_policy_from_result(result)
    if policy:
        payload["execution_policy"] = policy
    return payload


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


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _parse_command(command: str | list[str]) -> tuple[list[str] | None, str | None]:
    if not command:
        return None, "missing command"
    if isinstance(command, str):
        try:
            argv = shlex.split(command, posix=(sys.platform != "win32"))
        except ValueError as e:
            return None, f"shlex_split_failed: {e}"
    elif isinstance(command, list):
        argv = [str(x) for x in command]
    else:
        return None, f"command must be str or list (got {type(command).__name__})"
    if not argv:
        return None, "empty argv after parsing"
    return argv, None


# ═══════════════════════════════════════════════════════════
# write / append / edit
# ═══════════════════════════════════════════════════════════


def _ensure_sandbox(
    path: str | Path,
    sandbox_dir: str | Path | None,
) -> tuple[Path, str | None]:
    from runtime.safety.auth.path_guard import check_path

    verdict = check_path(path, sandbox_dir=sandbox_dir)
    if not verdict.allow:
        reason = verdict.reason
        if "escapes_sandbox" in reason:
            reason = (
                f"path_escapes_sandbox: {verdict.resolved} not under {sandbox_dir}. "
                f"This usually means the session lost its workspace_path / code-mode context. "
                f"The write target is outside the allowed scope roots."
            )
        return Path(path), reason
    return Path(verdict.resolved) if verdict.resolved else Path(path), None


def _write_text_file(
    path: str = "",
    content: str = "",
    *,
    sandbox_dir: str | None = None,
    overwrite: bool = False,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    data = content.encode("utf-8")
    if len(data) > max_bytes:
        return {"error": f"content too large: {len(data)} > {max_bytes}"}

    resolved, err = _ensure_sandbox(path, sandbox_dir)
    if err:
        return {"error": err}
    if resolved.exists() and not overwrite:
        return {
            "error": "exists · pass overwrite=True to replace",
            "path": str(resolved),
        }
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(data)
    except OSError as e:
        return {"error": f"write_failed: {e}", "path": str(resolved)}
    return {
        "path": str(resolved),
        "bytes_written": len(data),
        "overwrote": resolved.exists(),
    }


def _append_text_file(
    path: str = "",
    content: str = "",
    *,
    sandbox_dir: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    data = content.encode("utf-8")
    if len(data) > max_bytes:
        return {"error": f"content too large: {len(data)} > {max_bytes}"}

    resolved, err = _ensure_sandbox(path, sandbox_dir)
    if err:
        return {"error": err}
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("ab") as f:
            f.write(data)
    except OSError as e:
        return {"error": f"append_failed: {e}", "path": str(resolved)}
    return {
        "path": str(resolved),
        "bytes_appended": len(data),
        "total_size": resolved.stat().st_size,
    }


def _edit_text_file(
    path: str = "",
    find: str = "",
    replace: str = "",
    *,
    sandbox_dir: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    count: int = -1,  # Implementation note.
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    if not find:
        return {"error": "find must be non-empty"}

    resolved, err = _ensure_sandbox(path, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.exists():
        return {"error": f"not found: {resolved}"}
    try:
        original = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"read_failed: {e}"}
    occurrences = original.count(find)
    if occurrences == 0:
        return {
            "error": "find pattern not present in file",
            "occurrences": 0,
        }
    if count < 0:
        new_text = original.replace(find, replace)
        replaced = occurrences
    else:
        new_text = original.replace(find, replace, count)
        replaced = min(occurrences, count)
    new_bytes = new_text.encode("utf-8")
    if len(new_bytes) > max_bytes:
        return {"error": f"result too large: {len(new_bytes)} > {max_bytes}"}
    try:
        resolved.write_bytes(new_bytes)
    except OSError as e:
        return {"error": f"write_failed: {e}"}
    return {
        "path": str(resolved),
        "occurrences": occurrences,
        "replaced": replaced,
        "new_size": len(new_bytes),
    }


def _edit_file(
    path: str = "",
    old_string: str = "",
    new_string: str = "",
    *,
    replace_all: bool = False,
    sandbox_dir: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    if not old_string:
        return {"error": "old_string must be non-empty"}
    if old_string == new_string:
        return {"error": "no-op edit: old_string and new_string are identical"}

    resolved, err = _ensure_sandbox(path, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.exists():
        return {"error": f"not found: {resolved}"}
    try:
        original = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"read_failed: {e}"}

    occurrences = original.count(old_string)
    if occurrences == 0:
        # Help the model recover by hinting at the most common cause —
        # whitespace / line-ending / quoting drift between what they
        # remembered and what's actually on disk.
        preview = old_string[:80].replace("\n", "\\n")
        return {
            "error": "old_string_not_found",
            "occurrences": 0,
            "hint": (
                f"Searched for: {preview!r}. The exact bytes weren't "
                "found. Common causes: (1) whitespace/indentation "
                "differs from what you remember, (2) the file was "
                "modified by a previous tool call this turn, (3) "
                "different line endings (\\r\\n vs \\n). "
                "Re-read the file with read_file(path) and copy the "
                "block literally."
            ),
        }
    if not replace_all and occurrences != 1:
        # Show approximate locations so the model can disambiguate
        # by adding surrounding context.
        first_line = original[: original.index(old_string)].count("\n") + 1
        return {
            "error": "old_string_not_unique",
            "occurrences": occurrences,
            "first_match_line": first_line,
            "hint": (
                f"Found {occurrences} occurrences (first one at line "
                f"{first_line}). To disambiguate either: (a) extend "
                "old_string with surrounding lines so it matches "
                "exactly once, or (b) pass replace_all=True if you "
                "really want every occurrence changed."
            ),
        }

    new_text = (
        original.replace(old_string, new_string)
        if replace_all
        else original.replace(old_string, new_string, 1)
    )
    new_bytes = new_text.encode("utf-8")
    if len(new_bytes) > max_bytes:
        return {"error": f"result too large: {len(new_bytes)} > {max_bytes}"}
    try:
        resolved.write_bytes(new_bytes)
    except OSError as e:
        return {"error": f"write_failed: {e}"}
    return {
        "path": str(resolved),
        "occurrences": occurrences,
        "replaced": occurrences if replace_all else 1,
        "new_size": len(new_bytes),
    }


def _multi_edit_file(
    path: str = "",
    edits: list[dict[str, Any]] | None = None,
    *,
    sandbox_dir: str | None = None,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    **_kw: Any,
) -> dict[str, Any]:
    if not path:
        return {"error": "missing path"}
    if not edits:
        return {"error": "edits must be a non-empty list"}

    resolved, err = _ensure_sandbox(path, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.exists():
        return {"error": f"not found: {resolved}"}
    try:
        original = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return {"error": f"read_failed: {e}"}

    candidate = original
    normalized: list[tuple[str, str, bool]] = []
    for idx, edit in enumerate(edits):
        if not isinstance(edit, dict):
            return {"error": f"edits[{idx}] must be an object"}
        old_string = str(edit.get("old_string", ""))
        new_string = str(edit.get("new_string", ""))
        replace_all = bool(edit.get("replace_all", False))
        if not old_string:
            return {"error": f"edits[{idx}].old_string must be non-empty"}
        if old_string == new_string:
            return {"error": f"edits[{idx}] is a no-op: old_string and new_string are identical"}
        occurrences = candidate.count(old_string)
        if occurrences == 0:
            preview = old_string[:80].replace("\n", "\\n")
            return {
                "error": f"edits[{idx}].old_string_not_found",
                "edit_index": idx,
                "occurrences": 0,
                "hint": (
                    f"Searched for: {preview!r}. Note: each edit "
                    "applies to the file AFTER previous edits in this "
                    "call. If a prior edit changed the surrounding "
                    "context, the later old_string may no longer match. "
                    "Re-read the file or split into separate edit_file "
                    "calls."
                ),
            }
        if not replace_all and occurrences != 1:
            first_line = candidate[: candidate.index(old_string)].count("\n") + 1
            return {
                "error": f"edits[{idx}].old_string_not_unique",
                "edit_index": idx,
                "occurrences": occurrences,
                "first_match_line": first_line,
                "hint": (
                    f"Found {occurrences} occurrences in edits[{idx}] "
                    f"(first at line {first_line}). Extend old_string "
                    "with surrounding lines or set replace_all=True "
                    "for this specific edit."
                ),
            }
        normalized.append((old_string, new_string, replace_all))
        candidate = (
            candidate.replace(old_string, new_string)
            if replace_all
            else candidate.replace(old_string, new_string, 1)
        )

    new_bytes = candidate.encode("utf-8")
    if len(new_bytes) > max_bytes:
        return {"error": f"result too large: {len(new_bytes)} > {max_bytes}"}
    try:
        resolved.write_bytes(new_bytes)
    except OSError as e:
        return {"error": f"write_failed: {e}"}
    return {
        "path": str(resolved),
        "edits": len(normalized),
        "new_size": len(new_bytes),
    }


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


# ── Unconfined-exec environment scrubbing ────────────────────
# When a shell/exec skill runs WITHOUT a sandbox (``sandbox_dir`` is
# None — e.g. the OpenAI-compat gateway path that never binds a Session,
# or a direct CLI run), the child would otherwise inherit the runtime's
# full ``os.environ`` and a model-driven command could read secrets
# straight out of it. Full confinement is ``sandbox_dir`` + the sandbox
# backend; this closes the secret-leak half on the unconfined path by
# handing the child a credential-scrubbed copy of the environment.
# The scrubbing itself lives in ``runtime.safety.env_scrub`` (imported at
# module top as ``_scrub_unconfined_env``) so the interactive terminal
# WebSocket shares the same credential heuristics.


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


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


_GIT_READ_TIMEOUT_S = 15.0
_GIT_WRITE_TIMEOUT_S = 30.0
_GIT_OUTPUT_CAP = 200_000


def _run_git(
    repo_dir: str | Path,
    argv: list[str],
    *,
    timeout_s: float,
    sandbox_dir: str | None = None,
    allow_network: bool = False,
) -> dict[str, Any]:
    if not repo_dir:
        return {"error": "missing repo_dir"}
    resolved, err = _ensure_sandbox(repo_dir, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.is_dir():
        return {"error": f"repo_dir not a directory: {resolved}"}

    from runtime.platform.process.streaming import stream_run

    full_argv = ["git", "-C", str(resolved), *argv]
    r = stream_run(
        full_argv,
        timeout=timeout_s,
        output_cap_bytes=_GIT_OUTPUT_CAP,
        sandbox_dir=sandbox_dir,
        allow_network=allow_network,
    )
    if "error" in r and "exit_code" not in r:
        msg = r["error"]
        if "FileNotFoundError" in msg or "No such file" in msg or "not found" in msg.lower():
            return _error_with_execution_policy("git_not_found_on_path", r)
        return _error_with_execution_policy(f"git_exec_failed: {msg}", r)
    if r.get("timed_out"):
        return {
            "error": f"git timeout after {timeout_s}s",
            "timed_out": True,
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "exit_code": r["exit_code"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "stdout_truncated": r["stdout_truncated"],
        "resolved_repo": str(resolved),
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }


def _git_status(
    repo_dir: str = "",
    *,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    r = _run_git(
        repo_dir,
        ["status", "--porcelain=v1", "--branch"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_status_failed", **r}

    branch = ""
    files: list[dict[str, str]] = []
    for line in r["stdout"].splitlines():
        if line.startswith("## "):
            branch = line[3:].split("...")[0]
            continue
        if len(line) < 3:
            continue
        code = line[:2]
        path = line[3:]
        files.append({"status": code.strip() or code, "path": path})
    return {
        "branch": branch,
        "files": files,
        "clean": not files,
    }


def _git_diff(
    repo_dir: str = "",
    *,
    path: str | None = None,
    staged: bool = False,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    argv = ["diff"]
    if staged:
        argv.append("--staged")
    if path:
        if path.startswith("-"):
            return {"error": "invalid path (leading '-')"}
        argv.extend(["--", path])
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_diff_failed", **r}
    return {
        "diff": r["stdout"],
        "truncated": r["stdout_truncated"],
        "staged": staged,
    }


def _git_log(
    repo_dir: str = "",
    *,
    limit: int = 10,
    path: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if limit <= 0 or limit > 500:
        return {"error": f"limit out of range: {limit}"}
    fmt = "%H%x1f%an%x1f%aI%x1f%s"
    argv = ["log", f"-n{limit}", f"--pretty=format:{fmt}"]
    if path:
        if path.startswith("-"):
            return {"error": "invalid path (leading '-')"}
        argv.extend(["--", path])
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_log_failed", **r}

    commits: list[dict[str, str]] = []
    for line in r["stdout"].splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, author, date, subject = parts
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "subject": subject,
            }
        )
    return {"commits": commits}


def _git_add(
    repo_dir: str = "",
    paths: list[str] | None = None,
    *,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not paths:
        return {"error": "paths must be a non-empty list"}
    if not isinstance(paths, list):
        return {"error": f"paths must be list (got {type(paths).__name__})"}
    safe_paths: list[str] = []
    for p in paths:
        if not isinstance(p, str) or not p:
            return {"error": "each path must be a non-empty string"}
        if p.startswith("-"):
            return {"error": f"flag-like path rejected: {p}"}
        if p in (".", "*") or ".." in Path(p).parts:
            return {"error": f"overly broad or traversal path: {p}"}
        safe_paths.append(p)

    r = _run_git(
        repo_dir,
        ["add", "--", *safe_paths],
        timeout_s=_GIT_WRITE_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_add_failed", **r}
    return {"added": safe_paths, "exit_code": 0}


def _git_commit(
    repo_dir: str = "",
    message: str = "",
    *,
    author: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not message.strip():
        return {"error": "commit message must be non-empty"}
    if len(message.encode("utf-8")) > 10_000:
        return {"error": "commit message too large"}

    argv = ["commit", "-m", message]
    if author:
        if "<" not in author or ">" not in author:
            return {"error": "author must be 'Name <email>' format"}
        argv.extend(["--author", author])

    r = _run_git(
        repo_dir,
        argv,
        timeout_s=_GIT_WRITE_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_commit_failed", **r}

    head = _run_git(
        repo_dir,
        ["rev-parse", "HEAD"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    sha = head.get("stdout", "").strip() if "error" not in head else ""
    return {"sha": sha, "stdout": r["stdout"], "stderr": r["stderr"]}


def _git_branch(
    repo_dir: str = "",
    *,
    create: str | None = None,
    from_ref: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if create:
        if create.startswith("-") or " " in create:
            return {"error": f"invalid branch name: {create!r}"}
        argv = ["branch", create]
        if from_ref:
            if from_ref.startswith("-"):
                return {"error": f"invalid ref: {from_ref!r}"}
            argv.append(from_ref)
        r = _run_git(
            repo_dir,
            argv,
            timeout_s=_GIT_WRITE_TIMEOUT_S,
            sandbox_dir=sandbox_dir,
        )
        if "error" in r:
            return r
        if r["exit_code"] != 0:
            return {"error": "git_branch_create_failed", **r}
        return {"created": create, "from_ref": from_ref}

    r = _run_git(
        repo_dir,
        ["branch", "--list"],
        timeout_s=_GIT_READ_TIMEOUT_S,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_branch_list_failed", **r}
    branches: list[dict[str, Any]] = []
    for line in r["stdout"].splitlines():
        line = line.rstrip()
        if not line:
            continue
        current = line.startswith("*")
        name = line[2:] if len(line) > 2 else line
        branches.append({"name": name.strip(), "current": current})
    return {"branches": branches}


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


WRITE_SKILL_NAMES = [
    "write_text_file",
    "append_text_file",
    "edit_text_file",
    "edit_file",
    "multi_edit_file",
]
EXEC_SKILL_NAME = "exec_shell"
GIT_SKILL_NAMES = [
    "git_status",
    "git_diff",
    "git_log",
    "git_add",
    "git_commit",
    "git_branch",
]


def register_write_skills(registry: SkillRegistry) -> int:
    registry.register(
        Skill(
            name="write_text_file",
            description=(
                "用途: 把 UTF-8 文本完整写入一个新文件；首选用于「创建新文件」场景。会受 sandbox_dir 路径校验保护。\n"
                "何时不用: 要修改已有文件请用 edit_file (按唯一片段) 或 multi_edit_file (批量精确替换)；要追加内容用 append_text_file；要写二进制不要用本工具。\n"
                "关键参数: path (必填); content (必填); overwrite (默认 False — 文件已存在时返回错误); max_bytes (默认 1MB)。\n"
                '示例: write_text_file({"path": "notes.md", "content": "# hello\\n", "overwrite": false})'
            ),
            affinity=["file", "write"],
            cost_profile="low",
            trusted_source="skill://public/write_text_file",
            handler=_write_text_file,
            tests=[
                SkillTestCase(
                    name="missing_path_error",
                    tier="golden",
                    args={"path": "", "content": "x"},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="append_text_file",
            description=(
                "用途: 在文件末尾追加 UTF-8 文本（不存在则创建）；常用于日志、增量记录、向 markdown 续写。\n"
                "何时不用: 要替换/修改文件中间某段用 edit_file；要整体覆写一个新文件用 write_text_file (overwrite=True)；要在指定位置插入用 edit_file 把上下文一并替换。\n"
                "关键参数: path (必填); content (必填, 自带换行需自己加 \\n); max_bytes (默认 1MB)。\n"
                '示例: append_text_file({"path": "log.txt", "content": "2026-05-29 ok\\n"})'
            ),
            affinity=["file", "write"],
            cost_profile="low",
            trusted_source="skill://public/append_text_file",
            handler=_append_text_file,
            tests=[
                SkillTestCase(
                    name="missing_path_error",
                    tier="golden",
                    args={"path": "", "content": "x"},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="edit_text_file",
            description=(
                "用途: 老式宽松版 find-and-replace — 不强制唯一性，按计数替换出现的字面串。适合简单批量改名、注释清理。\n"
                "何时不用: 想要「唯一片段才替换」的安全编辑用 edit_file；要一次改多处不同片段用 multi_edit_file；要写新文件用 write_text_file。\n"
                "关键参数: path / find / replace (均必填); count (默认 -1 = 全部替换, 正数 = 只替换前 N 个)。\n"
                '示例: edit_text_file({"path": "a.py", "find": "foo", "replace": "bar", "count": 1})'
            ),
            affinity=["file", "edit"],
            cost_profile="low",
            trusted_source="skill://public/edit_text_file",
            handler=_edit_text_file,
            tests=[
                SkillTestCase(
                    name="missing_find_error",
                    tier="golden",
                    args={"path": "/tmp/x", "find": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="edit_file",
            description=(
                "用途: 安全的精确编辑 — 把 old_string 替换为 new_string，默认要求文件中只出现一次 (避免误改)。改源码首选。\n"
                "何时不用: 要一次性应用多处不同替换用 multi_edit_file (原子化、按序合并)；要写全新文件用 write_text_file；只是末尾追加用 append_text_file；宽松全替换用 edit_text_file。\n"
                "关键参数: path / old_string / new_string (均必填, old≠new); replace_all (默认 False, True 时允许多处匹配并全替换)。\n"
                '示例: edit_file({"path": "a.py", "old_string": "def foo():\\n    pass", "new_string": "def foo():\\n    return 1"})'
            ),
            summary="Replace one exact unique string in a file.",
            affinity=["file", "edit"],
            cost_profile="low",
            trusted_source="skill://public/edit_file",
            handler=_edit_file,
            tests=[
                SkillTestCase(
                    name="missing_old_string_error",
                    tier="golden",
                    args={"path": "/tmp/x", "old_string": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="multi_edit_file",
            description=(
                "用途: 一次调用对同一文件原子化应用多个精确替换 (按 edits 顺序累积)；适合重构 / 同时改多处。任一编辑失败整批回滚。\n"
                "何时不用: 只改一处用 edit_file；不同文件分别处理；要一行 find/replace 全文扫荡用 edit_text_file；要新建文件用 write_text_file。\n"
                "关键参数: path (必填); edits (必填, list[{old_string, new_string, replace_all?}], 顺序敏感, 默认每条要求唯一)。\n"
                '示例: multi_edit_file({"path": "a.py", "edits": [{"old_string": "v1", "new_string": "v2"}, {"old_string": "x", "new_string": "y", "replace_all": true}]})'
            ),
            summary="Apply multiple exact string edits to one file.",
            affinity=["file", "edit"],
            cost_profile="low",
            trusted_source="skill://public/multi_edit_file",
            handler=_multi_edit_file,
            tests=[
                SkillTestCase(
                    name="missing_edits_error",
                    tier="golden",
                    args={"path": "/tmp/x", "edits": []},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    return 5


def register_git_skills(registry: SkillRegistry) -> int:
    registry.register(
        Skill(
            name="git_status",
            description="Structured `git status` (branch + porcelain file list).",
            affinity=["git", "read"],
            cost_profile="low",
            trusted_source="skill://public/git_status",
            handler=_git_status,
            tests=[
                SkillTestCase(
                    name="missing_repo_error",
                    tier="golden",
                    args={"repo_dir": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="git_diff",
            description="Run `git diff` (optionally --staged or for a single path).",
            affinity=["git", "read"],
            cost_profile="low",
            trusted_source="skill://public/git_diff",
            handler=_git_diff,
            tests=[
                SkillTestCase(
                    name="missing_repo_error",
                    tier="golden",
                    args={"repo_dir": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="git_log",
            description="Recent commits (sha/author/date/subject · structured).",
            affinity=["git", "read"],
            cost_profile="low",
            trusted_source="skill://public/git_log",
            handler=_git_log,
            tests=[
                SkillTestCase(
                    name="missing_repo_error",
                    tier="golden",
                    args={"repo_dir": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="git_add",
            description="Stage explicit paths · rejects -A / '.' / flag injection.",
            affinity=["git", "write"],
            cost_profile="low",
            trusted_source="skill://public/git_add",
            handler=_git_add,
            tests=[
                SkillTestCase(
                    name="missing_paths_error",
                    tier="golden",
                    args={"repo_dir": "/tmp", "paths": []},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="git_commit",
            description="Commit staged changes (no auto-add, no amend, no hook skip).",
            affinity=["git", "write"],
            cost_profile="low",
            trusted_source="skill://public/git_commit",
            handler=_git_commit,
            tests=[
                SkillTestCase(
                    name="empty_message_error",
                    tier="golden",
                    args={"repo_dir": "/tmp", "message": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="git_branch",
            description="List branches · or create a new one (no switch, no force).",
            affinity=["git", "write"],
            cost_profile="low",
            trusted_source="skill://public/git_branch",
            handler=_git_branch,
            tests=[
                SkillTestCase(
                    name="missing_repo_error",
                    tier="golden",
                    args={"repo_dir": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    return 6


def register_exec_skill(registry: SkillRegistry) -> int:
    registry.register(
        Skill(
            name=EXEC_SKILL_NAME,
            description=(
                "用途: 执行本地 shell 命令 (无 shell=True、有超时)；最适合编译、打包、文件管线、调用各种 CLI；当没有专门 skill 匹配时的兜底。\n"
                "何时不用: 谷歌/搜资料用 web_search；抓取已知 URL 用 fetch_url (curl/wget 抓回的 HTML 不好解析)；跑 Python 片段用 ipython；改文件用 edit_file/write_text_file；查 git 状态用 git_status。\n"
                "关键参数: command (str 或 list[str], 必填); cwd (可选); timeout_s (默认 30); run_in_background (默认 False, True 时返回 task_id, 配合 read_shell_output / kill_shell)。\n"
                '示例: exec_shell({"command": "npm test", "cwd": "web", "timeout_s": 120})'
            ),
            affinity=["shell", "exec", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/exec_shell",
            handler=_exec_shell,
            tests=[
                SkillTestCase(
                    name="missing_command_error",
                    tier="golden",
                    args={"command": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="ipython",
            description=(
                "用途: 在带超时的子进程里跑一段 Python (当前解释器, 无 REPL 状态保留)；适合数据分析、临时计算、调用 numpy/pandas/json。\n"
                "何时不用: 跑非 Python 命令用 exec_shell；只是数文本用 count_words；改文件用 edit_file 而不是写脚本绕路；要长跑用 background_exec / exec_shell(run_in_background=True)。\n"
                "关键参数: code (必填, 完整 Python 片段, 用 print 才能拿到 stdout); cwd (可选); timeout_s (默认 30)。\n"
                '示例: ipython({"code": "import json; print(json.dumps({\\"x\\": 1}))"})'
            ),
            affinity=["python", "analysis", "exec", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/ipython",
            handler=_ipython,
            tests=[
                SkillTestCase(
                    name="missing_code_error",
                    tier="golden",
                    args={"code": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="background_exec",
            description=(
                "Start a LOCAL long-running command in the background and "
                "return immediately with a task_id. Use for dev servers, "
                "watchers, docker compose, and long tests. Poll with "
                "`read_background_output`; stop with `kill_background_exec`."
            ),
            affinity=["shell", "exec", "background", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/background_exec",
            handler=_background_exec,
            tests=[
                SkillTestCase(
                    name="missing_command_error",
                    tier="golden",
                    args={"command": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="read_background_output",
            description=(
                "Poll stdout/stderr and status for a command started by `background_exec`."
            ),
            affinity=["shell", "exec", "background", "read"],
            cost_profile="low",
            trusted_source="skill://public/read_background_output",
            handler=_read_background_output,
            tests=[
                SkillTestCase(
                    name="missing_task_id_error",
                    tier="golden",
                    args={"task_id": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="read_shell_output",
            description=(
                "Alias for read_background_output. Poll stdout/stderr and "
                "status for a command started by exec_shell(run_in_background=True) "
                "or background_exec."
            ),
            affinity=["shell", "exec", "background", "read"],
            cost_profile="low",
            trusted_source="skill://public/read_shell_output",
            handler=_read_shell_output,
            tests=[
                SkillTestCase(
                    name="missing_task_id_error",
                    tier="golden",
                    args={"task_id": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="kill_background_exec",
            description="Stop a command started by `background_exec`.",
            affinity=["shell", "exec", "background", "dangerous"],
            cost_profile="low",
            trusted_source="skill://public/kill_background_exec",
            handler=_kill_background_exec,
            tests=[
                SkillTestCase(
                    name="missing_task_id_error",
                    tier="golden",
                    args={"task_id": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="kill_shell",
            description=(
                "Alias for kill_background_exec. Stop a command started by "
                "exec_shell(run_in_background=True) or background_exec."
            ),
            affinity=["shell", "exec", "background", "dangerous"],
            cost_profile="low",
            trusted_source="skill://public/kill_shell",
            handler=_kill_shell,
            tests=[
                SkillTestCase(
                    name="missing_task_id_error",
                    tier="golden",
                    args={"task_id": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    return 7


# ═══════════════════════════════════════════════════════════
# Git network + branch switch skills (opt-in · dangerous)
# ═══════════════════════════════════════════════════════════


def _git_push(
    repo_dir: str = "",
    *,
    remote: str = "origin",
    branch: str | None = None,
    set_upstream: bool = False,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Push commits to remote. Never force-pushes."""
    if remote.startswith("-"):
        return {"error": f"invalid remote: {remote!r}"}
    argv = ["push", remote]
    if branch:
        if branch.startswith("-"):
            return {"error": f"invalid branch: {branch!r}"}
        argv.append(branch)
    if set_upstream:
        argv.insert(1, "-u")
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=60.0,
        sandbox_dir=sandbox_dir,
        allow_network=True,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_push_failed", **r}
    return {"pushed": True, "remote": remote, "branch": branch}


def _git_pull(
    repo_dir: str = "",
    *,
    remote: str = "origin",
    branch: str | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Pull from remote (rebase mode)."""
    if remote.startswith("-"):
        return {"error": f"invalid remote: {remote!r}"}
    argv = ["pull", "--rebase", remote]
    if branch:
        if branch.startswith("-"):
            return {"error": f"invalid branch: {branch!r}"}
        argv.append(branch)
    r = _run_git(
        repo_dir,
        argv,
        timeout_s=60.0,
        sandbox_dir=sandbox_dir,
        allow_network=True,
    )
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": "git_pull_failed", **r}
    return {"pulled": True, "remote": remote, "branch": branch, "stdout": r["stdout"][:2000]}


def _git_checkout(
    repo_dir: str = "",
    *,
    branch: str = "",
    create: bool = False,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Switch branch. Auto-stashes dirty state."""
    if not branch or branch.startswith("-"):
        return {"error": f"invalid branch: {branch!r}"}
    stash_r = _run_git(
        repo_dir, ["stash", "--include-untracked"], timeout_s=15.0, sandbox_dir=sandbox_dir
    )
    stashed = stash_r.get("exit_code") == 0 and "No local changes" not in stash_r.get("stdout", "")
    argv = ["checkout"]
    if create:
        argv.append("-b")
    argv.append(branch)
    r = _run_git(repo_dir, argv, timeout_s=_GIT_WRITE_TIMEOUT_S, sandbox_dir=sandbox_dir)
    if "error" in r:
        if stashed:
            _run_git(repo_dir, ["stash", "pop"], timeout_s=15.0, sandbox_dir=sandbox_dir)
        return r
    if r["exit_code"] != 0:
        if stashed:
            _run_git(repo_dir, ["stash", "pop"], timeout_s=15.0, sandbox_dir=sandbox_dir)
        return {"error": "git_checkout_failed", **r}
    result: dict[str, Any] = {"switched": branch, "created": create}
    if stashed:
        pop_r = _run_git(repo_dir, ["stash", "pop"], timeout_s=15.0, sandbox_dir=sandbox_dir)
        result["stash_restored"] = pop_r.get("exit_code") == 0
    return result


def _git_stash(
    repo_dir: str = "",
    *,
    action: str = "push",
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Stash push/pop/list."""
    allowed = {"push", "pop", "list", "show", "drop"}
    if action not in allowed:
        return {"error": f"invalid action: {action!r}, allowed: {allowed}"}
    argv = ["stash", action]
    if action == "push":
        argv.append("--include-untracked")
    r = _run_git(repo_dir, argv, timeout_s=15.0, sandbox_dir=sandbox_dir)
    if "error" in r:
        return r
    if r["exit_code"] != 0:
        return {"error": f"git_stash_{action}_failed", **r}
    return {"action": action, "stdout": r["stdout"][:4000]}


def _git_create_pr(
    repo_dir: str = "",
    *,
    title: str = "",
    body: str = "",
    base: str | None = None,
    draft: bool = False,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Create a GitHub PR using the `gh` CLI."""
    if not title:
        return {"error": "title is required"}
    from runtime.execution.suckers.write_skills import _ensure_sandbox

    resolved, err = _ensure_sandbox(repo_dir, sandbox_dir)
    if err:
        return {"error": err}
    argv = ["gh", "pr", "create", "--title", title]
    if body:
        argv.extend(["--body", body])
    if base:
        argv.extend(["--base", base])
    if draft:
        argv.append("--draft")

    from runtime.platform.process.streaming import stream_run

    r = stream_run(
        argv,
        cwd=str(resolved),
        timeout=30.0,
        output_cap_bytes=8000,
        sandbox_dir=sandbox_dir,
        allow_network=True,
    )
    if "error" in r and "exit_code" not in r:
        msg = r["error"]
        if "FileNotFoundError" in msg or "not found" in msg.lower():
            return _error_with_execution_policy(
                "gh CLI not found — install from https://cli.github.com",
                r,
            )
        return _error_with_execution_policy(f"gh_exec_failed: {msg}", r)
    if r.get("timed_out"):
        return {
            "error": "timeout creating PR",
            "execution_policy": _execution_policy_from_result(r),
        }
    if r["exit_code"] != 0:
        return {
            "error": "gh_pr_create_failed",
            "stderr": r["stderr"][:2000],
            "exit_code": r["exit_code"],
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "created": True,
        "url": r["stdout"].strip(),
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }


GIT_NETWORK_SKILL_NAMES = [
    "git_push",
    "git_pull",
    "git_checkout",
    "git_stash",
    "git_create_pr",
]


def register_git_network_skills(registry: SkillRegistry) -> int:
    """Register git network/branch skills · opt-in · dangerous."""
    registry.register(
        Skill(
            name="git_push",
            description="Push commits to remote (never force-pushes).",
            affinity=["git", "network", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/git_push",
            handler=_git_push,
            tests=[],
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="git_pull",
            description="Pull from remote with rebase.",
            affinity=["git", "network", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/git_pull",
            handler=_git_pull,
            tests=[],
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="git_checkout",
            description="Switch branch (auto-stashes dirty state).",
            affinity=["git", "write", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/git_checkout",
            handler=_git_checkout,
            tests=[],
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="git_stash",
            description="Stash push/pop/list/show/drop.",
            affinity=["git", "write"],
            cost_profile="low",
            trusted_source="skill://public/git_stash",
            handler=_git_stash,
            tests=[],
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="git_create_pr",
            description="Create a GitHub PR using `gh` CLI.",
            affinity=["git", "network", "dangerous"],
            cost_profile="mid",
            trusted_source="skill://public/git_create_pr",
            handler=_git_create_pr,
            tests=[],
        ),
        verify_tests=False,
    )
    return 5


# ═══════════════════════════════════════════════════════════
# Code quality skills · lint / test / format
# ═══════════════════════════════════════════════════════════

_QUALITY_TIMEOUT_S = 60.0
_QUALITY_OUTPUT_CAP = 200_000


def _run_quality_cmd(
    command: list[str],
    cwd: str | Path,
    *,
    timeout_s: float = _QUALITY_TIMEOUT_S,
    sandbox_dir: str | None = None,
) -> dict[str, Any]:
    """Shared runner for code quality tools."""
    if not cwd:
        return {"error": "missing cwd"}
    resolved, err = _ensure_sandbox(cwd, sandbox_dir)
    if err:
        return {"error": err}
    if not resolved.is_dir():
        return {"error": f"cwd not a directory: {resolved}"}

    from runtime.platform.process.streaming import stream_run

    r = stream_run(
        command,
        cwd=str(resolved),
        timeout=timeout_s,
        output_cap_bytes=_QUALITY_OUTPUT_CAP,
        sandbox_dir=sandbox_dir,
    )
    if "error" in r and "exit_code" not in r:
        msg = r["error"]
        if "FileNotFoundError" in msg or "not found" in msg.lower():
            return _error_with_execution_policy(f"command not found: {command[0]}", r)
        return _error_with_execution_policy(f"exec failed: {msg}", r)
    if r.get("timed_out"):
        return {
            "error": f"timeout after {timeout_s}s",
            "timed_out": True,
            "execution_policy": _execution_policy_from_result(r),
        }
    return {
        "exit_code": r["exit_code"],
        "stdout": r["stdout"],
        "stderr": r["stderr"],
        "success": r["exit_code"] == 0,
        "sandbox_backend": r.get("sandbox_backend", "direct"),
        "sandbox_hard": bool(r.get("sandbox_hard")),
        "execution_policy": _execution_policy_from_result(r),
    }


def _run_tests(
    cwd: str = "",
    *,
    command: str = "",
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Run project tests. Auto-detects runner if command not specified."""
    if not cwd:
        return {"error": "missing cwd"}
    resolved, err = _ensure_sandbox(cwd, sandbox_dir)
    if err:
        return {"error": err}

    if command:
        argv = shlex.split(command)
    else:
        p = Path(str(resolved))
        if (p / "pytest.ini").exists() or (p / "pyproject.toml").exists():
            argv = [sys.executable, "-m", "pytest", "--tb=short", "-q"]
        elif (p / "package.json").exists():
            argv = (
                ["npx", "vitest", "--run"]
                if (p / "vitest.config.ts").exists() or (p / "vitest.config.js").exists()
                else ["npm", "test"]
            )
        else:
            return {"error": "cannot auto-detect test runner; pass command explicitly"}

    return _run_quality_cmd(argv, resolved, sandbox_dir=sandbox_dir)


def _lint_check(
    cwd: str = "",
    *,
    command: str = "",
    paths: list[str] | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Run linter. Auto-detects ruff/eslint if command not specified."""
    if not cwd:
        return {"error": "missing cwd"}
    resolved, err = _ensure_sandbox(cwd, sandbox_dir)
    if err:
        return {"error": err}

    if command:
        argv = shlex.split(command)
    else:
        p = Path(str(resolved))
        if (p / "ruff.toml").exists() or (p / "pyproject.toml").exists():
            argv = [sys.executable, "-m", "ruff", "check", "--output-format=concise"]
        elif (
            (p / ".eslintrc.js").exists()
            or (p / ".eslintrc.json").exists()
            or (p / "eslint.config.js").exists()
        ):
            argv = ["npx", "eslint", "--format=compact"]
        else:
            return {"error": "cannot auto-detect linter; pass command explicitly"}

    if paths:
        for pt in paths:
            if pt.startswith("-") or ".." in Path(pt).parts:
                return {"error": f"invalid path: {pt}"}
        argv.extend(paths)

    return _run_quality_cmd(argv, resolved, sandbox_dir=sandbox_dir)


def _format_code(
    cwd: str = "",
    *,
    command: str = "",
    check_only: bool = True,
    paths: list[str] | None = None,
    sandbox_dir: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Run formatter. Auto-detects ruff format/prettier if command not specified."""
    if not cwd:
        return {"error": "missing cwd"}
    resolved, err = _ensure_sandbox(cwd, sandbox_dir)
    if err:
        return {"error": err}

    if command:
        argv = shlex.split(command)
    else:
        p = Path(str(resolved))
        if (p / "ruff.toml").exists() or (p / "pyproject.toml").exists():
            argv = [sys.executable, "-m", "ruff", "format"]
            if check_only:
                argv.append("--check")
        elif (
            (p / ".prettierrc").exists()
            or (p / ".prettierrc.json").exists()
            or (p / "prettier.config.js").exists()
        ):
            argv = ["npx", "prettier"]
            argv.append("--check" if check_only else "--write")
            argv.append(".")
        else:
            return {"error": "cannot auto-detect formatter; pass command explicitly"}

    if paths:
        for pt in paths:
            if pt.startswith("-") or ".." in Path(pt).parts:
                return {"error": f"invalid path: {pt}"}
        argv.extend(paths)

    return _run_quality_cmd(argv, resolved, sandbox_dir=sandbox_dir)


CODE_QUALITY_SKILL_NAMES = ["run_tests", "lint_check", "format_code"]


def register_code_quality_skills(registry: SkillRegistry) -> int:
    """Register code quality skills · lint / test / format."""
    registry.register(
        Skill(
            name="run_tests",
            description="Run project tests (auto-detects pytest/vitest/npm test).",
            affinity=["test", "code", "quality"],
            cost_profile="mid",
            trusted_source="skill://public/run_tests",
            handler=_run_tests,
            tests=[
                SkillTestCase(
                    name="missing_cwd_error",
                    tier="golden",
                    args={"cwd": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="lint_check",
            description="Run linter (auto-detects ruff/eslint). Returns diagnostics.",
            affinity=["lint", "code", "quality"],
            cost_profile="low",
            trusted_source="skill://public/lint_check",
            handler=_lint_check,
            tests=[
                SkillTestCase(
                    name="missing_cwd_error",
                    tier="golden",
                    args={"cwd": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="format_code",
            description="Run formatter (auto-detects ruff format/prettier). Default check-only.",
            affinity=["format", "code", "quality"],
            cost_profile="low",
            trusted_source="skill://public/format_code",
            handler=_format_code,
            tests=[
                SkillTestCase(
                    name="missing_cwd_error",
                    tier="golden",
                    args={"cwd": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    return 3
