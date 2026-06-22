"""Execution bridge for LocalPartner agents — drive an official coding-agent
CLI (Claude Code, Codex) directly, with the user's own login/subscription.

LocalPartner registration (``agents_local_partner.write_partner_agent``) detects
an installed CLI and writes an agent whose ``profile.jsonc`` carries::

    "runtime": "local_partner",
    "capabilities": {
        "local_partner": true,
        "local_partner_id": "claude-code",            # which CLI
        "local_partner_command": "claude",            # the bare command
        "local_partner_executable": "/abs/path/claude" # resolved (safe) path
    }

Until now nothing *executed* on those flags: a LocalPartner agent ran as a
normal LLM agent whose SOUL.md merely *told the model* to shell out to the CLI —
indirect, unreliable, and a wasted LLM round-trip wrapping another agent. This
module is the direct dispatch: turn the user's prompt into the CLI's own
non-interactive invocation, run it, and hand the output back.

Design:
  * ``build_partner_argv`` holds the per-CLI knowledge (the only place that
    knows ``claude -p`` vs ``codex exec``). Unknown / not-yet-supported
    partners return ``None`` so the caller can fall back to the normal loop.
  * The prompt is always passed as a **separate argv element** and the process
    is spawned with ``shell=False`` — the user's text never reaches a shell, so
    there is no shell-injection surface.
  * ``run_local_partner`` takes an injectable ``runner`` so the whole path is
    unit-testable without a real CLI installed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# A runner executes ``argv`` in ``cwd`` with a wall-clock ``timeout`` and
# returns ``(exit_code, stdout, stderr)``. Injectable so tests don't spawn.
Runner = Callable[[list[str], "str | None", float], "tuple[int, str, str]"]

# Wall-clock ceiling for a single CLI run. Coding agents can take a while, but
# a turn shouldn't hang forever; override with OCTOPUS_LOCAL_PARTNER_TIMEOUT.
_DEFAULT_TIMEOUT_S = 240.0

# Trim runaway CLI output so one run can't flood a chat turn / the journal.
_MAX_OUTPUT_CHARS = 20_000


@dataclass(frozen=True)
class LocalPartnerResult:
    """Outcome of one CLI run. ``ok`` means it ran AND exited 0 with output."""

    ok: bool
    output: str = ""
    error: str = ""
    exit_code: int | None = None
    argv: list[str] = field(default_factory=list)
    timed_out: bool = False
    # True only when the partner type has no known non-interactive invocation
    # yet — the caller should fall back to the normal loop rather than show an
    # error (the agent isn't broken, we just can't drive it directly).
    unsupported: bool = False


def partner_identity(capabilities: Any) -> tuple[str, str] | None:
    """Read ``(partner_id, command)`` from an agent's capabilities, or ``None``
    when this isn't a drivable local partner. Prefers the resolved executable
    path (captured under PATH-poisoning defense at registration) over the bare
    command name."""
    if not isinstance(capabilities, dict):
        return None
    if not capabilities.get("local_partner"):
        return None
    partner_id = str(capabilities.get("local_partner_id") or "").strip()
    command = str(
        capabilities.get("local_partner_executable")
        or capabilities.get("local_partner_command")
        or ""
    ).strip()
    if not partner_id or not command:
        return None
    return partner_id, command


def build_partner_argv(partner_id: str, command: str, prompt: str) -> list[str] | None:
    """Map ``(partner_id, command, prompt)`` to the CLI's own non-interactive
    invocation, or ``None`` for partners we can't drive headless yet.

    The flags are best-effort for the known CLIs and intentionally isolated
    here so a single edit fixes a tool whose interface drifts:
      * ``claude-code`` → ``claude -p "<prompt>"``  (print / headless mode)
      * ``codex-cli``   → ``codex exec "<prompt>"`` (non-interactive exec)

    ``openclaw`` (desktop automation, not a prompt→answer coding agent) has no
    headless prompt form here → ``None`` (caller falls back to the LLM loop).
    """
    prompt = (prompt or "").strip()
    if not command or not prompt:
        return None
    if partner_id == "claude-code":
        return [command, "-p", prompt]
    if partner_id == "codex-cli":
        return [command, "exec", prompt]
    return None


def _default_runner(argv: list[str], cwd: str | None, timeout: float) -> tuple[int, str, str]:
    """Spawn ``argv`` with no shell, capturing stdout/stderr. Raises
    ``subprocess.TimeoutExpired`` on timeout (handled by ``run_local_partner``)."""
    proc = subprocess.run(  # noqa: S603 — argv is a list, shell=False, no user shell string
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def run_local_partner(
    *,
    partner_id: str,
    command: str,
    prompt: str,
    cwd: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT_S,
    runner: Runner | None = None,
) -> LocalPartnerResult:
    """Drive the partner CLI once. Best-effort and total — never raises; every
    failure mode (unsupported tool, missing binary, non-zero exit, timeout) is
    reflected in the returned :class:`LocalPartnerResult`."""
    argv = build_partner_argv(partner_id, command, prompt)
    if argv is None:
        return LocalPartnerResult(ok=False, unsupported=True)

    run = runner or _default_runner
    try:
        exit_code, stdout, stderr = run(argv, cwd, timeout)
    except subprocess.TimeoutExpired:
        return LocalPartnerResult(
            ok=False,
            error=f"{command} did not finish within {int(timeout)}s",
            argv=argv,
            timed_out=True,
        )
    except FileNotFoundError:
        return LocalPartnerResult(
            ok=False,
            error=f"{command} is not installed or not on PATH",
            argv=argv,
        )
    except OSError as exc:
        return LocalPartnerResult(ok=False, error=str(exc), argv=argv)

    output = (stdout or "").strip()
    if len(output) > _MAX_OUTPUT_CHARS:
        output = output[:_MAX_OUTPUT_CHARS].rstrip() + "\n…(truncated)"
    if exit_code == 0 and output:
        return LocalPartnerResult(ok=True, output=output, exit_code=exit_code, argv=argv)

    # Ran but failed: surface the most useful tail we have (stderr, else a hint).
    err_tail = (stderr or "").strip() or (output or "exited without output")
    if len(err_tail) > 2_000:
        err_tail = err_tail[-2_000:]
    return LocalPartnerResult(
        ok=False,
        output=output,
        error=err_tail,
        exit_code=exit_code,
        argv=argv,
    )
