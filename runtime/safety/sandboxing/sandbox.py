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
  4. A no-op ``DirectBackend`` that runs subprocess directly. This remains
     the local-development default — soft constraints still apply. Shared /
     commercial mode selects a hard backend and fails closed when none exists.

The contract: even with the no-op backend, **a sandbox-aware caller
gets observable behavior** (timeout, output cap, env scrubbing,
blocked-network hints). Switching to a real backend later is a
configuration change, not an API change.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

_logger = logging.getLogger(__name__)


_COMMERCIAL_DEPLOYMENT_MODES = frozenset(
    {
        "commercial",
        "production",
        "shared",
        "server",
    }
)


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
_EXTRA_ENV_ALLOWED_EXACT = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "NODE_PATH",
        "RUST_LOG",
        "TERM",
        "COLORTERM",
    }
)
_EXTRA_ENV_ALLOWED_PREFIXES = ("OCT_", "OCTOPUS_", "PYTEST_")
_SENSITIVE_ENV_MARKERS = (
    "API_KEY",
    "ACCESS_KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "PRIVATE_KEY",
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
        allowed = set(self.allowed_env)
        for key, value in self.extra_env.items():
            key_s = str(key)
            if _sandbox_extra_env_key_allowed(key_s, allowed):
                env[key_s] = str(value)
        workspace = self.workspace.expanduser().resolve(strict=False)
        home_dir = _ensure_workspace_env_dir(workspace, ".octopus-home")
        tmp_dir = _ensure_workspace_env_dir(workspace, ".octopus-tmp")
        cache_dir = _ensure_workspace_env_dir(workspace, ".octopus-cache")
        config_dir = _ensure_workspace_env_dir(workspace, ".octopus-config")
        data_dir = _ensure_workspace_env_dir(workspace, ".octopus-data")
        env.update(
            {
                "HOME": str(home_dir),
                "USERPROFILE": str(home_dir),
                "TMPDIR": str(tmp_dir),
                "TMP": str(tmp_dir),
                "TEMP": str(tmp_dir),
                "XDG_CACHE_HOME": str(cache_dir),
                "XDG_CONFIG_HOME": str(config_dir),
                "XDG_DATA_HOME": str(data_dir),
            }
        )
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


def _ensure_workspace_env_dir(workspace: Path, name: str) -> Path:
    if not workspace.is_dir():
        return workspace
    path = workspace / name
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        return workspace


def _sandbox_extra_env_key_allowed(key: str, base_allowed: set[str]) -> bool:
    clean = str(key or "").strip()
    if not clean:
        return False
    upper = clean.upper()
    if upper in base_allowed:
        return True
    if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
        return False
    if upper in _EXTRA_ENV_ALLOWED_EXACT:
        return True
    return any(upper.startswith(prefix) for prefix in _EXTRA_ENV_ALLOWED_PREFIXES)


def _append_capped_utf8_output(
    sink: list[str],
    chunk: str,
    *,
    cap_bytes: int,
    size: list[int],
) -> tuple[str, bool]:
    if size[0] >= cap_bytes:
        return "", True
    chunk_bytes = chunk.encode("utf-8", errors="replace")
    remaining = cap_bytes - size[0]
    if len(chunk_bytes) <= remaining:
        size[0] += len(chunk_bytes)
        sink.append(chunk)
        return chunk, False
    if remaining <= 0:
        size[0] = cap_bytes
        return "", True
    truncated = chunk_bytes[:remaining].decode("utf-8", errors="ignore")
    size[0] = cap_bytes
    if truncated:
        sink.append(truncated)
    return truncated, True


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
class BackendChoice:
    """Resolved process sandbox backend for one command."""

    backend: Backend
    name: str
    hard: bool
    strict: bool = False


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


@dataclass(frozen=True)
class BubblewrapBackend:
    """Linux hard sandbox backend using ``bwrap``.

    The workspace is bind-mounted read/write at its original absolute
    path so callers can keep using host paths. System directories are
    mounted read-only; home directories and unrelated project folders
    are not mounted unless they are the workspace.
    """

    executable: str = "bwrap"

    @staticmethod
    def available() -> bool:
        return shutil.which("bwrap") is not None

    def transform(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        policy: SandboxPolicy,
    ) -> tuple[list[str], dict[str, str], Path]:
        workspace = policy.workspace.expanduser().resolve()
        run_cwd = cwd.expanduser().resolve()
        try:
            run_cwd.relative_to(workspace)
        except ValueError as exc:
            raise SandboxViolation(f"cwd {run_cwd} escapes workspace {workspace}") from exc

        bwrap = shutil.which(self.executable)
        if not bwrap:
            raise SandboxViolation("bubblewrap sandbox requested but bwrap is not installed")

        wrapped: list[str] = [
            bwrap,
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup",
        ]
        if not policy.allow_network:
            wrapped.append("--unshare-net")

        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
            if Path(path).exists():
                wrapped.extend(["--ro-bind", path, path])
        if Path("/dev").exists():
            wrapped.extend(["--dev", "/dev"])
        if Path("/proc").exists():
            wrapped.extend(["--proc", "/proc"])
        wrapped.extend(["--tmpfs", "/tmp"])  # nosec B108 — bwrap tmpfs mount arg, not a temp file

        parents = list(workspace.parents)
        parents.reverse()
        for parent in parents:
            if str(parent) != "/":
                wrapped.extend(["--dir", str(parent)])
        wrapped.extend(["--bind", str(workspace), str(workspace)])
        wrapped.extend(["--chdir", str(run_cwd), "--"])
        wrapped.extend(argv)
        return wrapped, env, run_cwd


@dataclass(frozen=True)
class SeatbeltBackend:
    """macOS hard write/network sandbox using ``sandbox-exec``.

    Seatbelt profiles that fully confine reads tend to break language
    runtimes without a curated framework allow-list, so this backend is
    intentionally scoped as a hard write/network guard: it allows reads
    needed to launch tooling, denies network unless explicitly allowed,
    and restricts writes to the workspace plus temporary directories.
    """

    executable: str = "sandbox-exec"

    @staticmethod
    def available() -> bool:
        return shutil.which("sandbox-exec") is not None and sys.platform == "darwin"

    def transform(
        self,
        argv: list[str],
        env: dict[str, str],
        cwd: Path,
        policy: SandboxPolicy,
    ) -> tuple[list[str], dict[str, str], Path]:
        workspace = policy.workspace.expanduser().resolve()
        run_cwd = cwd.expanduser().resolve()
        try:
            run_cwd.relative_to(workspace)
        except ValueError as exc:
            raise SandboxViolation(f"cwd {run_cwd} escapes workspace {workspace}") from exc

        sandbox_exec = shutil.which(self.executable)
        if not sandbox_exec:
            raise SandboxViolation("seatbelt sandbox requested but sandbox-exec is not installed")

        write_subpaths = [
            workspace,
            Path("/dev/null"),
            Path("/tmp"),  # nosec B108 — sandbox write-allow rule target, not a temp file
            Path("/private/tmp"),  # nosec B108 — sandbox write-allow rule target, not a temp file
            Path("/var/tmp"),  # nosec B108 — sandbox write-allow rule target, not a temp file
            Path(os.environ.get("TMPDIR", "/tmp")).expanduser().resolve(strict=False),  # nosec B108 — sandbox write-allow rule target
        ]
        write_rules = "\n".join(
            f'  (subpath "{_sbpl_escape(str(path))}")' for path in _unique_paths(write_subpaths)
        )
        network_rule = "(allow network*)" if policy.allow_network else "(deny network*)"
        profile = (
            "(version 1)\n"
            "(deny default)\n"
            "(allow process*)\n"
            "(allow signal (target same-sandbox))\n"
            "(allow sysctl-read)\n"
            "(allow mach-lookup)\n"
            "(allow file-read*)\n"
            f"(allow file-write*\n{write_rules})\n"
            f"{network_rule}\n"
        )
        return [sandbox_exec, "-p", profile, *argv], env, run_cwd


class SandboxViolation(Exception):
    """Raised when a request would escape the policy.

    Distinct from a non-zero exit code — the command did not even run.
    Caller should surface this as ``status=rejected`` so the planner
    distinguishes "not allowed" from "ran and failed".
    """


def commercial_execution_mode() -> bool:
    """Return whether the process is running in a shared/commercial mode.

    This is deliberately an explicit deployment switch.  Local desktop and
    test callers keep the historical soft fallback unless they opt into a
    strict process sandbox themselves.  A commercial deployment must opt in
    with ``OCTOPUS_DEPLOYMENT_MODE=commercial`` (``production``/``shared``
    are accepted aliases) so an operator cannot accidentally expose a
    network-facing service with the local development execution contract.
    """

    raw = os.environ.get("OCTOPUS_DEPLOYMENT_MODE", "").strip().lower()
    return raw in _COMMERCIAL_DEPLOYMENT_MODES


def process_sandbox_required() -> bool:
    """Whether a high-risk process caller must provide a hard sandbox.

    Explicit hard backend requests are also treated as required.  This lets
    ``OCTOPUS_PROCESS_SANDBOX=strict`` fail closed even for a local operator,
    while leaving the default local ``auto`` behavior backwards compatible.
    """

    raw = os.environ.get("OCTOPUS_PROCESS_SANDBOX", "").strip().lower()
    return commercial_execution_mode() or raw in {
        "strict",
        "bwrap",
        "bubblewrap",
        "seatbelt",
        "sandbox-exec",
    }


def effective_process_sandbox_mode() -> str:
    """Resolve the backend mode with a commercial fail-closed override."""

    raw = os.environ.get("OCTOPUS_PROCESS_SANDBOX", "").strip().lower()
    if commercial_execution_mode():
        # A commercial deployment may select a specific hard backend, but
        # cannot downgrade itself to ``soft``/``direct``/``auto``.
        if raw in {"bwrap", "bubblewrap", "seatbelt", "sandbox-exec", "strict"}:
            return raw
        return "strict"
    return raw or "auto"


def select_process_backend(mode: str | None = None) -> BackendChoice:
    """Resolve the process sandbox backend from env/config.

    ``OCTOPUS_PROCESS_SANDBOX`` values:

    * ``auto`` (default): use the best available hard backend; fall back
      to soft if none is installed.
    * ``soft`` / ``direct`` / ``off``: direct subprocess with
      the soft policy already enforced by callers.
    * ``strict``: use a hard backend; reject execution if unavailable.
    * ``bwrap`` / ``bubblewrap`` / ``seatbelt``: require that backend.
    """

    raw = (mode or os.environ.get("OCTOPUS_PROCESS_SANDBOX") or "auto").strip().lower()
    if raw in {"", "soft", "direct", "off", "false", "0"}:
        return BackendChoice(DirectBackend(), "direct", hard=False)

    if raw in {"bwrap", "bubblewrap"}:
        if BubblewrapBackend.available():
            return BackendChoice(BubblewrapBackend(), "bwrap", hard=True, strict=True)
        raise SandboxViolation("bwrap sandbox requested but bwrap is not installed")

    if raw in {"seatbelt", "sandbox-exec"}:
        if SeatbeltBackend.available():
            return BackendChoice(SeatbeltBackend(), "seatbelt", hard=True, strict=True)
        raise SandboxViolation(
            "seatbelt sandbox requested but sandbox-exec is not available on this host"
        )

    if raw in {"auto", "strict"}:
        strict = raw == "strict"
        if sys.platform.startswith("linux") and BubblewrapBackend.available():
            return BackendChoice(BubblewrapBackend(), "bwrap", hard=True, strict=strict)
        if SeatbeltBackend.available():
            return BackendChoice(SeatbeltBackend(), "seatbelt", hard=True, strict=strict)
        if strict:
            raise SandboxViolation(
                "strict process sandbox requested but no hard backend is available "
                "(install bwrap on Linux or use sandbox-exec on macOS)"
            )
        _warn_soft_fallback_once()
        return BackendChoice(DirectBackend(), "direct", hard=False)

    raise SandboxViolation(f"unknown process sandbox mode: {raw}")


_soft_fallback_warned = False
_soft_fallback_warn_lock = threading.Lock()


def _warn_soft_fallback_once() -> None:
    """Loudly note the auto→direct soft fallback — exactly once per process.

    Before this existed the fallback was silent: on a Linux host without
    ``bwrap`` every agent command ran with soft constraints only, and
    the only way to notice was reading the execution-policy metadata.
    Windows has no hard backend yet, so the warning there points at the
    tracking gap rather than an install hint.
    """
    global _soft_fallback_warned
    with _soft_fallback_warn_lock:
        if _soft_fallback_warned:
            return
        _soft_fallback_warned = True
    if sys.platform.startswith("linux"):
        hint = "install bubblewrap (bwrap) for kernel-level isolation"
    elif sys.platform == "darwin":
        hint = "sandbox-exec is unavailable on this host"
    else:
        hint = "no hard sandbox backend exists for this platform yet"
    _logger.warning(
        "process sandbox: no hard backend available — falling back to soft "
        "constraints only (cwd lock + env allowlist + output cap). To get "
        "kernel-level isolation: %s. Set OCTOPUS_PROCESS_SANDBOX=strict to "
        "refuse execution instead.",
        hint,
    )


def _sbpl_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


class SandboxRunner:
    def __init__(self, policy: SandboxPolicy, *, backend: Backend | None = None) -> None:
        self.policy = policy
        self.backend = backend or DirectBackend()
        if isinstance(self.backend, DirectBackend):
            _logger.warning(
                "SandboxRunner is using DirectBackend — no kernel-level isolation "
                "is applied. A misbehaving process can still damage the host "
                "(e.g. rm -rf, exfiltration). Install bwrap (Linux), sandbox-exec "
                "(macOS), or configure ContainerSandbox for real isolation."
            )

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
        from runtime.platform.process.tree import (
            process_group_kwargs,
            terminate_process_tree,
        )

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
                **process_group_kwargs(),
            )
        except FileNotFoundError as exc:
            raise SandboxViolation(f"executable not found: {exc.filename}") from exc
        except OSError as exc:
            raise SandboxViolation(f"failed to start process: {exc}") from exc

        out_chunks: list[str] = []
        err_chunks: list[str] = []
        truncated = False
        size_lock = threading.Lock()
        cap_bytes = max(0, int(self.policy.max_output_bytes))
        size = [0]

        def reader(stream: object, sink: list[str], tag: str) -> None:
            nonlocal truncated
            for raw_line in iter(stream.readline, ""):
                if not raw_line:
                    break
                with size_lock:
                    raw_line, was_truncated = _append_capped_utf8_output(
                        sink,
                        raw_line,
                        cap_bytes=cap_bytes,
                        size=size,
                    )
                    truncated = truncated or was_truncated
                if raw_line and on_output is not None:
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
            terminate_process_tree(proc)
            exit_code = proc.returncode if proc.returncode is not None else -1

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
        ws = self.policy.workspace.expanduser().resolve(strict=False)
        if not ws.is_dir():
            raise SandboxViolation(f"workspace is not a directory: {ws}")
        if cwd is None:
            return ws
        candidate = Path(cwd).expanduser().resolve(strict=False)
        try:
            candidate.relative_to(ws)
        except ValueError as exc:
            raise SandboxViolation(f"cwd {candidate} escapes workspace {ws}") from exc
        if not candidate.is_dir():
            raise SandboxViolation(f"cwd is not a directory: {candidate}")
        return candidate


def _normalise_argv(argv: Iterable[str] | str) -> list[str]:
    if isinstance(argv, str):
        return shlex.split(argv, posix=(sys.platform != "win32"))
    return [str(a) for a in argv]


__all__ = [
    "Backend",
    "BackendChoice",
    "BubblewrapBackend",
    "DirectBackend",
    "SandboxPolicy",
    "SandboxResult",
    "SandboxRunner",
    "SandboxViolation",
    "SeatbeltBackend",
    "select_process_backend",
]
