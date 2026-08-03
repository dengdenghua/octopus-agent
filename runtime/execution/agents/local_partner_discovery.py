"""Layer-neutral discovery for locally installed partner CLIs."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .login_shell_path import login_shell_path as _login_shell_path


def _path_entries(raw: str | None) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for part in (raw or "").split(os.pathsep):
        item = os.path.expanduser(part.strip())
        if not item or item in seen:
            continue
        seen.add(item)
        entries.append(item)
    return entries


def _common_local_bin_entries() -> list[str]:
    home = Path.home()
    return [
        str(home / ".local" / "bin"),
        str(home / ".local" / "node" / "bin"),
        str(home / ".codebuddy" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/Applications/ChatGPT.app/Contents/Resources",
    ]


def _candidate_path_entries() -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    for source in (
        _path_entries(os.environ.get("PATH")),
        _path_entries(_login_shell_path()),
        _common_local_bin_entries(),
    ):
        for entry in source:
            if entry in seen:
                continue
            seen.add(entry)
            entries.append(entry)
    return entries


def resolve_local_command(command: str) -> str | None:
    """Resolve a bare executable against service and login-shell paths."""

    path = shutil.which(command)
    if path:
        return path
    if os.path.sep in command or (os.path.altsep and os.path.altsep in command):
        return None
    for directory in _candidate_path_entries():
        candidate = Path(directory) / command
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())
        except OSError:
            continue
    return None


__all__ = ["resolve_local_command"]
