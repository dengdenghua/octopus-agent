"""Semantic grounding for the desktop vision loop.

The computer-use vision loop reasons over a raw screenshot only — pure pixels.
This module adds a cheap, best-effort *semantic* layer the planner can read
alongside the image: the list of on-screen windows (owning app, title, bounds).
That gives the model app/window structure it would otherwise have to infer
pixel-by-pixel, closing part of the gap with accessibility-tree-aware agents.

macOS is implemented via Quartz (pyobjc). Other platforms — and any failure or
missing dependency — return ``""``: grounding is strictly additive and must
NEVER raise into the loop. Windows already has the UIA skills; a UIA-backed
provider can slot in here later behind the same ``window_grounding`` contract.
"""

from __future__ import annotations

import sys

# Windows smaller than this (px) are chrome/indicators, not real targets.
_MIN_WINDOW_PX = 40


def window_grounding(max_windows: int = 12) -> str:
    """Return a compact on-screen window list, or ``""`` if unavailable.

    Never raises — callers (the vision planner) treat ``""`` as "no grounding".
    """
    if sys.platform == "darwin":
        return _macos_window_grounding(max_windows)
    return ""


def _macos_window_grounding(max_windows: int) -> str:
    try:
        import Quartz
    except Exception:  # noqa: BLE001 — pyobjc absent → no grounding
        return ""
    try:
        opts = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        windows = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []
    except Exception:  # noqa: BLE001 — Quartz call failed → no grounding
        return ""

    lines: list[str] = []
    for win in windows:
        owner = str(win.get("kCGWindowOwnerName") or "").strip()
        if not owner or owner == "Window Server":
            continue
        bounds = win.get("kCGWindowBounds") or {}
        try:
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            width = int(bounds.get("Width", 0))
            height = int(bounds.get("Height", 0))
        except (TypeError, ValueError):
            continue
        if width < _MIN_WINDOW_PX or height < _MIN_WINDOW_PX:
            continue
        title = str(win.get("kCGWindowName") or "").strip()
        label = f"{owner}: {title}" if title else owner
        lines.append(f"- {label} @ ({x},{y}) {width}x{height}")
        if len(lines) >= max_windows:
            break

    if not lines:
        return ""
    return "On-screen windows (app: title @ x,y WxH):\n" + "\n".join(lines)
