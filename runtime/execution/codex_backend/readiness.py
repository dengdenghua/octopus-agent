"""Read-only configuration checks shared by execution routing and its UI.

This does not start App Server, refresh credentials or make a model request.
The real execution boundary still validates principal, workspace and sandbox
authority, and may reject expired credentials or provider failures.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from runtime.platform.runtime_policy.feature_flags import resolution

from .command import resolve_codex_app_server_command
from .model_profile import ResolvedCodexExecutionProfile
from .types import ConfigurationError


@dataclass(frozen=True, slots=True)
class CodexReadiness:
    available: bool
    reason: str | None = None


def inspect_codex_readiness(
    profile: ResolvedCodexExecutionProfile,
    *,
    auth_source: Callable[[], Path | None],
    tools_available: bool = True,
) -> CodexReadiness:
    # Import lazily: role execution uses this helper for its own preflight.
    from .role_runner import require_codex_backend_enabled
    from .security import CodexSecurityError

    value, source = resolution("execution.codex_app_server")
    if source not in (None, "default") and value is not True:
        return CodexReadiness(False, "disabled")
    try:
        require_codex_backend_enabled()
    except CodexSecurityError:
        return CodexReadiness(False, "disabled")
    try:
        resolve_codex_app_server_command()
    except ConfigurationError:
        return CodexReadiness(False, "executable_unavailable")
    if not profile.compatible:
        return CodexReadiness(False, "model_incompatible")
    if not tools_available:
        return CodexReadiness(False, "tools_unavailable")
    if not profile.proxy_required:
        try:
            if auth_source() is None:
                return CodexReadiness(False, "account_required")
        except (CodexSecurityError, ConfigurationError, OSError, ValueError):
            return CodexReadiness(False, "account_unavailable")
    return CodexReadiness(True)
