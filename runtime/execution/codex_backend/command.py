"""Shared executable resolution for Codex control and execution planes."""

from __future__ import annotations

import os
from pathlib import Path

from runtime.execution.agents.local_partner_discovery import resolve_local_command

from .types import ConfigurationError


def resolve_codex_app_server_command(executable: str | None = None) -> tuple[str, ...]:
    """Resolve one absolute Codex binary and pin the App Server argv.

    Packaged macOS builds often have no ``codex`` on the service PATH while
    ChatGPT ships it in ``/Applications/ChatGPT.app/Contents/Resources``.
    ``resolve_local_command`` already probes service PATH, login-shell PATH,
    common install bins, and that packaged resource directory. Both account
    login and real Coder turns call this function so they cannot drift to
    different Codex versions.
    """

    candidate = str(os.environ.get("OCTOPUS_CODEX_EXECUTABLE") or executable or "codex").strip()
    if not candidate or "\x00" in candidate:
        raise ConfigurationError("Codex executable is invalid")
    expanded = Path(candidate).expanduser()
    resolved: str | None
    if (
        expanded.is_absolute()
        or os.path.sep in candidate
        or (os.path.altsep is not None and os.path.altsep in candidate)
    ):
        try:
            if not expanded.is_file() or not os.access(expanded, os.X_OK):
                resolved = None
            else:
                resolved = str(expanded.resolve(strict=True))
        except OSError:
            resolved = None
    else:
        resolved = resolve_local_command(candidate)
    if resolved is None:
        raise ConfigurationError("Codex executable is unavailable")
    return (resolved, "app-server", "--strict-config", "--listen", "stdio://")


__all__ = ["resolve_codex_app_server_command"]
