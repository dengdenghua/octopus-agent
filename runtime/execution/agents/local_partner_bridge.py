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

import os
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


def _default_runner(
    argv: list[str],
    cwd: str | None,
    timeout: float,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Spawn ``argv`` with no shell, capturing stdout/stderr. ``env`` (when given)
    is layered OVER the inherited environment, so extra vars like
    ``OCTOPUS_BLACKBOARD_DB`` / ``OCTOPUS_TURN_ID`` reach the CLI (letting a
    shell-capable agent read/write the shared blackboard via ``octopus bb``)
    without dropping PATH etc. Raises ``subprocess.TimeoutExpired`` on timeout."""
    proc = subprocess.run(  # noqa: S603 — argv is a list, shell=False, no user shell string
        argv,
        cwd=cwd,
        env=({**os.environ, **env} if env else None),
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
    env: dict[str, str] | None = None,
    runner: Runner | None = None,
) -> LocalPartnerResult:
    """Drive the partner CLI once. Best-effort and total — never raises; every
    failure mode (unsupported tool, missing binary, non-zero exit, timeout) is
    reflected in the returned :class:`LocalPartnerResult`. ``env`` is layered over
    the inherited environment for the default runner (custom runners ignore it)."""
    argv = build_partner_argv(partner_id, command, prompt)
    if argv is None:
        return LocalPartnerResult(ok=False, unsupported=True)

    if runner is None:

        def run(a: list[str], c: str | None, t: float) -> tuple[int, str, str]:
            return _default_runner(a, c, t, env=env)
    else:
        run = runner
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


# ── Shared-blackboard envelope (octopus-mediated stigmergy) ──────────
# External CLIs are black boxes: we can't touch their internal context. So
# teammates collaborate at the I/O boundary — brief the agent FROM the shared
# blackboard (read → into the prompt) and harvest its output BACK to the
# blackboard (so the next teammate's brief sees it). Shell-capable CLIs can also
# read/write the same board directly via ``octopus bb`` (we pass the env).

_BRIEF_VALUE_CAP = 300
_HARVEST_CAP = 4000


def blackboard_brief(turn_id: str | None, *, max_entries: int = 8) -> str:
    """A compact digest of the turn's shared blackboard, to brief a teammate —
    ``""`` when there's nothing to share (or no turn / no board). Best-effort."""
    if not turn_id:
        return ""
    try:
        from runtime.memory.runtime_state.blackboard import get_blackboard

        board = get_blackboard(str(turn_id))
        snap = board.snapshot() if board is not None else {}
    except Exception:  # noqa: BLE001 — briefing is strictly best-effort
        return ""
    if not isinstance(snap, dict) or not snap:
        return ""
    lines: list[str] = []
    for key, value in list(snap.items())[: max(1, max_entries)]:
        text = str(value)
        if len(text) > _BRIEF_VALUE_CAP:
            text = text[:_BRIEF_VALUE_CAP].rstrip() + "…"
        lines.append(f"- {key}: {text}")
    return "TEAM SHARED CONTEXT (from the shared blackboard):\n" + "\n".join(lines)


def harvest_to_blackboard(turn_id: str | None, writer: str | None, output: str) -> None:
    """Write a partner's output back to the turn blackboard so teammates see it.
    Best-effort; no-op without a turn / output / board."""
    if not turn_id or not (output or "").strip():
        return
    try:
        from runtime.memory.runtime_state.blackboard import get_blackboard

        board = get_blackboard(str(turn_id))
        if board is not None:
            board.write(
                f"partner.{writer or 'agent'}.output",
                output[:_HARVEST_CAP],
                writer=str(writer or "partner"),
            )
    except Exception:  # noqa: BLE001 — harvesting is strictly best-effort
        pass
