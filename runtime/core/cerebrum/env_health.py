"""Startup execution-health canary.

The guard system's hard/repair/advisory tiers assume tools can run. The
trajectory detector (``_trajectory_execution_degraded``) already learns an
environment is degraded after ≥2 environmental tool failures mid-turn; the
canary adds a *startup* probe so a serve that boots into a blocked
execution environment knows it degraded immediately instead of burning two
failed tool calls to find out.

Probe semantics: run a harmless ``echo`` exactly the way an exec tool
would — through the configured process-sandbox backend
(``select_process_backend`` / ``SandboxPolicy``). A non-zero exit means the
sandbox application itself fails (the ``sandbox_apply`` EPERM root cause)
or the host blocks subprocesses outright. Best-effort: any probe failure
is treated as "not degraded" rather than blocking server startup.

The probe result lives in a module-level cell so the ReAct guard path can
read it without re-running the subprocess on every turn. It is only ever
set by an explicit serve/test startup path — never on import.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

_logger = logging.getLogger(__name__)

# Default: unknown. None ≠ degraded — trajectory evidence must fire first.
_CANARY_DEGRADED: bool | None = None
_CANARY_LOCK = threading.Lock()

# Harmless marker command; the probe only checks exit status.
_CANARY_COMMAND = "echo octopus-exec-canary"


def set_execution_canary(degraded: bool | None) -> None:
    """Record the startup probe result (True = execution degraded)."""
    global _CANARY_DEGRADED
    with _CANARY_LOCK:
        _CANARY_DEGRADED = degraded


def execution_canary() -> bool | None:
    """Return the recorded startup probe result, or None if never probed."""
    with _CANARY_LOCK:
        return _CANARY_DEGRADED


def execution_canary_degraded() -> bool:
    """Whether the startup probe found execution degraded (False if unknown)."""
    with _CANARY_LOCK:
        return _CANARY_DEGRADED is True


def probe_execution_health(*, cwd: str | None = None, timeout_s: float = 8.0) -> bool:
    """Run one harmless command through the configured sandbox backend.

    Returns True when the environment blocks it (degraded execution), False
    when it runs or the probe itself cannot be set up. Never raises.
    """
    try:
        workspace = Path(cwd or os.getcwd()).expanduser().resolve()
        from runtime.safety.sandboxing.sandbox import (
            SandboxPolicy,
            effective_process_sandbox_mode,
            select_process_backend,
        )

        choice = select_process_backend(effective_process_sandbox_mode())
        policy = SandboxPolicy(workspace=workspace)
        argv, env, run_cwd = choice.backend.transform(
            ["echo", "octopus-exec-canary"],
            policy.env_for(),
            workspace,
            policy,
        )
        result = subprocess.run(
            argv,
            cwd=str(run_cwd),
            env=env,
            capture_output=True,
            timeout=timeout_s,
            text=True,
        )
        return result.returncode != 0
    except Exception as exc:  # noqa: BLE001 — the probe must never break startup
        _logger.debug("execution canary probe failed: %s", exc)
        return False


def run_startup_canary(*, cwd: str | None = None) -> bool:
    """Probe and record execution health; return the degraded flag.

    Intended for the serve startup path (after ``_prepare_execution_security``
    has set the sandbox env). Tests can call it with a temp cwd. Logs at
    warning when degraded so operators see the environment block in the
    startup log before the first ReAct turn.
    """
    degraded = probe_execution_health(cwd=cwd)
    set_execution_canary(degraded)
    if degraded:
        _logger.warning(
            "execution canary: sandboxed command could not run — dynamic "
            "verification evidence (tests / typecheck) may be unavailable "
            "this session; ReAct run-evidence guards will auto-downgrade"
        )
    return degraded
