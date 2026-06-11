
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

_SENSITIVE_HOME_SUFFIXES = (
    ".ssh",
    ".aws",
    ".gcp",
    ".kube",
    ".docker",
    ".gnupg",
    ".config/gh",      # GitHub CLI
    ".netrc",
    ".pgpass",
)

_SENSITIVE_ABS_PREFIXES_UNIX = (
    "/etc/passwd",
    "/etc/shadow",
    "/etc/sudoers",
    "/root",
    "/proc/self/environ",
    "/sys/class/",
    "/var/log/auth",
)

_DOS_DEVICE_NAMES = frozenset({
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
})


@dataclass(frozen=True)
class PathVerdict:

    allow: bool
    path: str
    resolved: str | None = None
    reason: str = ""


def check_path(
    path: str | Path,
    *,
    sandbox_dir: str | Path | None = None,
    allow_sensitive: bool = False,
    must_exist: bool = False,
) -> PathVerdict:
    p_in = str(path)
    if not p_in:
        return PathVerdict(False, p_in, reason="empty_path")

    if sys.platform == "win32" and _has_dos_device(p_in):
        return PathVerdict(False, p_in, reason="dos_device_name")

    try:
        if sandbox_dir is not None and not Path(p_in).is_absolute():
            base = Path(sandbox_dir).resolve()
            resolved = (base / p_in).resolve()
        else:
            resolved = Path(p_in).resolve()
    except (OSError, RuntimeError) as e:
        return PathVerdict(False, p_in, reason=f"resolve_error: {e}")

    resolved_str = str(resolved)

    if sandbox_dir is not None:
        try:
            base = Path(sandbox_dir).resolve()
            resolved.relative_to(base)
        except ValueError:
            return PathVerdict(
                False, p_in, resolved=resolved_str,
                reason=f"escapes_sandbox: not under {base}",
            )

    if not allow_sensitive:
        reason = _check_sensitive(resolved)
        if reason:
            return PathVerdict(
                False, p_in, resolved=resolved_str, reason=reason,
            )

        # User-defined denylist (Marvis-style "不可读取文件夹"). Applies
        # even inside the sandbox — a sandbox says "this is the work
        # area" but the denylist says "but not these spots inside it
        # either". Includes shipped defaults, user-saved list, and any
        # per-turn additions pushed via ``push_turn_denylist`` (used by
        # the sub-agent bridge for ad-hoc restrictions like "researcher,
        # don't touch .env this turn").
        #
        # Only enforced when ``allow_sensitive`` is False; the explicit
        # opt-in flag is the single override point so admin/audit
        # callers can still reach denied paths intentionally.
        try:
            from runtime.safety.auth.path_denylist import is_blocked
            blocked, prefix = is_blocked(resolved)
            if blocked:
                return PathVerdict(
                    False, p_in, resolved=resolved_str,
                    reason=f"denylist_blocked: {prefix}",
                )
        except ImportError:  # noqa: BLE001 — denylist is optional, skip if missing
            pass

    # 5. must_exist
    if must_exist and not resolved.exists():
        return PathVerdict(
            False, p_in, resolved=resolved_str, reason="not_found",
        )

    return PathVerdict(True, p_in, resolved=resolved_str)


def is_safe_path(
    path: str | Path,
    *,
    sandbox_dir: str | Path | None = None,
    allow_sensitive: bool = False,
) -> bool:
    return check_path(
        path, sandbox_dir=sandbox_dir, allow_sensitive=allow_sensitive,
    ).allow


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _has_dos_device(path_str: str) -> bool:
    normalized = path_str.replace("\\", "/").lower()
    for part in normalized.split("/"):
        if not part:
            continue
        stem = part.split(".")[0]   # con.txt → con
        if stem in _DOS_DEVICE_NAMES:
            return True
    return False


def _check_sensitive(resolved: Path) -> str:
    rs = str(resolved)
    rs_norm = rs.replace("\\", "/").lower()

    for pref in _SENSITIVE_ABS_PREFIXES_UNIX:
        if rs_norm.startswith(pref.lower()):
            return f"sensitive_abs_path: {pref}"

    try:
        home = Path(os.path.expanduser("~")).resolve()
    except (OSError, RuntimeError):
        home = None

    if home is not None:
        try:
            rel = resolved.relative_to(home)
        except ValueError:
            rel = None
        if rel is not None:
            rel_str = str(rel).replace("\\", "/").lower()
            for suf in _SENSITIVE_HOME_SUFFIXES:
                if rel_str == suf.lower() or rel_str.startswith(suf.lower() + "/"):
                    return f"sensitive_home_path: ~/{suf}"


    return ""
