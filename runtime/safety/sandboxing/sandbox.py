"""Sandboxed shell command execution.

The "let the agent run shell" axis is the place where the gap between
a toy agent and a production agent is widest. ``exec_shell`` is **not**
raw ``subprocess.Popen``. It's wrapped in a platform-appropriate
sandbox: macOS Seatbelt, Linux ``bwrap`` / ``unshare``, Windows Job
Object + restricted token. The harness still gets the same
``stdout``/``stderr`` interface, but a misbehaving model cannot
``rm -rf /``, exfiltrate to a proxy, or escape the workspace.

This module does **not** ship a turnkey kernel sandbox — that's a deep
platform integration each user has to install. Instead it provides:

  1. A common ``SandboxPolicy`` data class.
  2. ``SandboxRunner`` — a process executor that always enforces the
     soft constraints (cwd lock, env allow-list, deny-network env hints,
     output size cap, wall-clock timeout, kill-tree on cancel).
  3. A pluggable ``Backend`` interface so a real bwrap/Seatbelt/Job
     Object backend can be wired in by the caller without touching
     the runner itself.
  4. A no-op ``DirectBackend`` that runs subprocess directly. This is
     the default — soft constraints still apply.

The contract: even with the no-op backend, **a sandbox-aware caller
gets observable behavior** (timeout, output cap, env scrubbing,
blocked-network hints). Switching to a real backend later is a
configuration change, not an API change.
"""
from __future__ import annotations

import contextlib
import logging
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

_logger = logging.getLogger(__name__)


# Default env keys allowed through to the child. Anything else is
# stripped — keeps the tested model from accidentally inheriting a
# user's API keys / OAuth tokens. If you need more, override via
# ``SandboxPolicy.allowed_env``.
_BASE_ALLOWED_ENV = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
    "TZ",
    "TEMP",
    "TMP",
    "TMPDIR",
    "SystemRoot",
    "ComSpec",
    "PATHEXT",
)


@dataclass(frozen=True)
class SandboxPolicy:
    """Knobs the runner enforces for every command."""

    workspace: Path
    """Allowed cwd. The runner refuses cwd= outside this tree."""

    allow_network: bool = False
    """If False, set ``no_proxy=*`` etc. so common HTTP libs short-circuit."""

    timeout_s: float = 60.0
    """Wall-clock cap. 0 disables (don't do that with untrusted models)."""

    max_output_bytes: int = 256 * 1024
    """Truncate stdout+stderr beyond this. Avoids OOM on chatty commands."""

    allowed_env: tuple[str, ...] = field(default_factory=lambda: _BASE_ALLOWED_ENV)

    extra_env: Mapping[str, str] = field(default_factory=dict)
    """Extra entries to inject (e.g. project-specific PYTHONPATH)."""

    def env_for(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in self.allowed_env if k in os.environ}
        env.update(self.extra_env)
        if not self.allow_network:
            # Hint to popular HTTP libs to give up immediately. This is
            # not a substitute for kernel-level network namespace, but
            # it covers casual ``urllib.request.urlopen`` and pip
            # without backend support.
            env["no_proxy"] = "*"
            env["NO_PROXY"] = "*"
            env["http_proxy"] = "http://127.0.0.1:1"
            env["https_proxy"] = "http://127.0.0.1:1"
        return env


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
    timed_out: bool
    killed: bool = False


class Backend(Protocol):
    """Plug point for platform-specific sandbox launchers.

    Implementations rewrite the ``argv``/``env``/``cwd`` to invoke the
    actual command under their isolation primitive (e.g. ``bwrap --
    <argv>`` on Linux). The default ``DirectBackend`` returns the input
    unchanged.
    """

    def transform(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        policy: SandboxPolicy,
    ) -> tuple[list[str], dict[str, str], Path]: ...


@dataclass(frozen=True)
class DirectBackend:
    """No isolation primitive applied — soft constraints only.

    Used by default. Replaceable by a caller who has bubblewrap /
    sandbox-exec / Job Object configured.
    """

    def transform(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        policy: SandboxPolicy,
    ) -> tuple[list[str], dict[str, str], Path]:
        return argv, env, cwd


class SandboxViolation(Exception):
    """Raised when a request would escape the policy.

    Distinct from a non-zero exit code — the command did not even run.
    Caller should surface this as ``status=rejected`` so the planner
    distinguishes "not allowed" from "ran and failed".
    """


class SandboxRunner:
    def __init__(self, policy: SandboxPolicy, *, backend: Backend | None = None) -> None:
        self.policy = policy
        self.backend = backend or DirectBackend()

    def run(
        self,
        argv: Iterable[str] | str,
        *,
        cwd: Path | str | None = None,
        stdin_text: str | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> SandboxResult:
        """Run a command under the policy. Returns a :class:`SandboxResult`.

        ``argv`` may be a list (preferred) or a string — strings are
        split with :func:`shlex.split` so users get the obvious behaviour.
        ``on_output`` is called with each chunk of decoded stdout/stderr
        as it arrives; the runner *also* keeps the aggregated text for
        the result. Use ``on_output`` for streaming UIs.
        """
        cmd_list = list(_normalise_argv(argv))
        if not cmd_list:
            raise SandboxViolation("empty command")

        run_cwd = self._resolve_cwd(cwd)
        env = self.policy.env_for()
        cmd_list, env, run_cwd = self.backend.transform(cmd_list, env, run_cwd, self.policy)

        started_at = time.monotonic()
        # ``preexec_fn`` is unsafe with threading on POSIX
        # (https://bugs.python.org/issue40364). We rely on signalling
        # the process group from the parent, which is portable enough.
        creationflags = 0
        start_new_session = False
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            start_new_session = True

        try:
            proc = subprocess.Popen(
                cmd_list,
                cwd=str(run_cwd),
                env=env,
                stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
        except FileNotFoundError as exc:
            raise SandboxViolation(f"executable not found: {exc.filename}") from exc
        except OSError as exc:
            raise SandboxViolation(f"failed to start process: {exc}") from exc

        out_chunks: list[str] = []
        err_chunks: list[str] = []
        truncated = False
        size_lock = threading.Lock()
        size = [0]

        def reader(stream: object, sink: list[str], tag: str) -> None:
            nonlocal truncated
            for raw_line in iter(stream.readline, ""):
                if not raw_line:
                    break
                with size_lock:
                    if size[0] >= self.policy.max_output_bytes:
                        truncated = True
                        continue
                    remaining = self.policy.max_output_bytes - size[0]
                    if len(raw_line) > remaining:
                        truncated = True
                        raw_line = raw_line[:remaining]
                    size[0] += len(raw_line)
                sink.append(raw_line)
                if on_output is not None:
                    try:
                        on_output(raw_line)
                    except Exception as cb_err:  # noqa: BLE001
                        _logger.debug("sandbox on_output raised: %s", cb_err)

        out_thread = threading.Thread(
            target=reader, args=(proc.stdout, out_chunks, "out"), daemon=True
        )
        err_thread = threading.Thread(
            target=reader, args=(proc.stderr, err_chunks, "err"), daemon=True
        )
        out_thread.start()
        err_thread.start()

        if stdin_text is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except OSError:  # noqa: BLE001 — stdin write best-effort
                pass

        timed_out = False
        killed = False
        timeout = self.policy.timeout_s if self.policy.timeout_s > 0 else None
        try:
            exit_code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            killed = True
            _kill_tree(proc)
            try:
                exit_code = proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                exit_code = -1

        out_thread.join(timeout=1.0)
        err_thread.join(timeout=1.0)

        return SandboxResult(
            exit_code=exit_code,
            stdout="".join(out_chunks),
            stderr="".join(err_chunks),
            duration_ms=int((time.monotonic() - started_at) * 1000),
            truncated=truncated,
            timed_out=timed_out,
            killed=killed,
        )

    def _resolve_cwd(self, cwd: Path | str | None) -> Path:
        ws = self.policy.workspace.expanduser().resolve()
        if cwd is None:
            return ws
        candidate = Path(cwd).expanduser().resolve()
        try:
            candidate.relative_to(ws)
        except ValueError as exc:
            raise SandboxViolation(
                f"cwd {candidate} escapes workspace {ws}"
            ) from exc
        if not candidate.is_dir():
            raise SandboxViolation(f"cwd is not a directory: {candidate}")
        return candidate


def _normalise_argv(argv: Iterable[str] | str) -> list[str]:
    if isinstance(argv, str):
        return shlex.split(argv, posix=(sys.platform != "win32"))
    return [str(a) for a in argv]


def _kill_tree(proc: subprocess.Popen) -> None:
    """Best-effort kill of the process and its children.

    On POSIX we signal the session group; on Windows we send
    CTRL_BREAK to the process group, then ``terminate`` as a fallback.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        with contextlib.suppress((OSError, ValueError)):
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
            proc.terminate()
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except OSError:
        with contextlib.suppress(OSError):
            proc.terminate()


__all__ = [
    "Backend",
    "DirectBackend",
    "SandboxPolicy",
    "SandboxResult",
    "SandboxRunner",
    "SandboxViolation",
]
