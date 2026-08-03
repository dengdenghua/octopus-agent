"""Security primitives for LocalPartner detection + registration.

Extracted from ``agents_local_partner.py`` (god-file reduction). These
constants and helpers fence off the shape of user-controllable values that
flow into LLM context (SOUL.md, IDENTITY.md) or trigger command resolution
(``shutil.which``).

``_LOCAL_PARTNER_ALIAS_RE`` is intentionally tight:
  * 1..64 chars
  * letters / digits / CJK / space / a few punctuation marks
  * no control chars, no slashes, no markdown break-out chars

Tightening past prompt-injection still leaves SOUL.md as a markdown file the
LLM may eventually read — so we additionally require alias to not look like an
instruction stub. We don't claim immunity, just defense in depth.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

# Allowed alias characters: letters, digits, CJK, regular space,
# hyphen, underscore, dot. Notably NOT \s (which would allow \n / \r
# / \t and enable line-break-based prompt injection into SOUL.md).
# Length capped at 64. Rejecting markdown structural chars
# (`*` `_` `[` `]` `(` `)` `>` `#`) prevents trivial markdown
# break-out from the SOUL template.
_LOCAL_PARTNER_ALIAS_RE = re.compile(
    r"^[A-Za-z0-9一-龥　-〿 .\-_]{1,64}$",
)
_SAFE_LOCAL_PARTNER_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _require_safe_agent_id(value: str) -> str:
    agent_id = str(value or "").strip()
    if not _SAFE_LOCAL_PARTNER_AGENT_ID_RE.fullmatch(agent_id):
        raise ValueError(
            "local partner agent_id may only contain alphanumeric characters, "
            "hyphens, and underscores"
        )
    return agent_id


def _cleanup_created_agent_dir(agent_dir: Path, *, created: bool) -> None:
    if created and agent_dir.is_dir() and not agent_dir.is_symlink():
        shutil.rmtree(agent_dir, ignore_errors=True)


def validate_alias(value: str | None) -> str:
    """Reject aliases that could pollute SOUL.md / IDENTITY.md or DoS disk.

    Raises ``ValueError`` on bad input — caller must convert to HTTP 400.
    """
    if value is None:
        return ""
    candidate = value.strip()
    if not candidate:
        return ""
    if len(candidate) > 64:
        raise ValueError("alias must be 64 chars or fewer")
    if not _LOCAL_PARTNER_ALIAS_RE.fullmatch(candidate):
        raise ValueError("alias may only contain letters, digits, CJK, spaces, '.', '-', '_'")
    return candidate


def identity_has_admin_role(identity: Any) -> bool:
    """Conservative admin check.

    True iff the resolved identity carries the ``admin`` role. This is
    the gate for endpoints that mutate global agent registry / write
    files under ``default_agents_root()``.
    """
    if identity is None:
        return False
    roles = getattr(identity, "roles", ()) or ()
    return "admin" in {str(role).lower() for role in roles}


def safe_executable(executable_path: str) -> bool:
    """Reject executables that resolve into the current working
    directory subtree. Defense against the most common PATH-poisoning
    scenario: an attacker drops a fake ``claude.cmd`` in cwd and
    Windows' default ``.``-in-PATH resolves to it before the real one.

    Note we INTENTIONALLY do not reject paths under the user's home —
    legitimate per-user installs of Claude Code, Codex, etc. live
    there (``~/AppData/Local/Programs/...`` on Windows, ``~/.local/bin``
    on Linux). Rejecting home-paths would block every real install.

    Returns True iff the resolved path lives outside cwd. When path
    resolution fails we REJECT (fail-closed) — a resolve error means
    we cannot verify the path is safe, and accepting it would open a
    PATH-poisoning vector.
    """
    try:
        resolved = Path(executable_path).resolve()
    except (OSError, RuntimeError):
        return False  # fail-closed on resolve error

    try:
        cwd = Path.cwd().resolve()
    except (OSError, RuntimeError):
        return False  # fail-closed on resolve error

    try:
        resolved.relative_to(cwd)
    except ValueError:
        return True
    return False


__all__ = [
    "identity_has_admin_role",
    "safe_executable",
    "validate_alias",
]
