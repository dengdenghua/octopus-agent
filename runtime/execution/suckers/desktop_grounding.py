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


# Roles worth pointing the planner at — things you can click / type into.
_AX_ACTIONABLE = frozenset({
    "AXButton", "AXTextField", "AXTextArea", "AXCheckBox", "AXRadioButton",
    "AXMenuItem", "AXMenuButton", "AXPopUpButton", "AXLink", "AXComboBox",
    "AXSlider", "AXTab", "AXDisclosureTriangle", "AXSearchField",
})


def ax_control_grounding(max_elements: int = 25, max_depth: int = 14) -> str:
    """Return the frontmost app's actionable UI elements (role/label @ center),
    or ``""`` if unavailable. macOS Accessibility (AXUIElement) only; needs the
    process to be Accessibility-trusted. Never raises — best-effort grounding
    on top of the screenshot so the planner can click by coordinate."""
    if sys.platform != "darwin":
        return ""
    try:
        import ApplicationServices as AS  # noqa: N817 — vendor acronym alias
        from AppKit import NSWorkspace
    except Exception:  # noqa: BLE001 — pyobjc AX frameworks absent
        return ""
    try:
        if not AS.AXIsProcessTrusted():
            return ""
        front = NSWorkspace.sharedWorkspace().frontmostApplication()
        if front is None:
            return ""
        app_name = str(front.localizedName() or "frontmost app")
        app_el = AS.AXUIElementCreateApplication(front.processIdentifier())
        err, windows = AS.AXUIElementCopyAttributeValue(
            app_el, AS.kAXWindowsAttribute, None,
        )
        if err != 0 or not windows:
            return ""
    except Exception:  # noqa: BLE001 — AX bootstrap failed
        return ""

    def _attr(el: object, name: str) -> object:
        try:
            err2, val = AS.AXUIElementCopyAttributeValue(el, name, None)
            return val if err2 == 0 else None
        except Exception:  # noqa: BLE001
            return None

    def _center(el: object) -> tuple[int, int] | None:
        pos = _attr(el, AS.kAXPositionAttribute)
        size = _attr(el, AS.kAXSizeAttribute)
        if pos is None:
            return None
        try:
            ok_p, pt = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
            if not ok_p:
                return None
            cx, cy = int(pt.x), int(pt.y)
            if size is not None:
                ok_s, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
                if ok_s:
                    cx += int(sz.width) // 2
                    cy += int(sz.height) // 2
            return cx, cy
        except Exception:  # noqa: BLE001
            return None

    lines: list[str] = []

    def _walk(el: object, depth: int) -> None:
        if len(lines) >= max_elements or depth > max_depth:
            return
        role = _attr(el, AS.kAXRoleAttribute)
        if role in _AX_ACTIONABLE:
            label = (
                _attr(el, AS.kAXTitleAttribute)
                or _attr(el, AS.kAXDescriptionAttribute)
                or _attr(el, AS.kAXValueAttribute)
                or _attr(el, AS.kAXHelpAttribute)
                or ""
            )
            center = _center(el)
            if center is not None:
                text = str(label).strip().replace("\n", " ")[:40]
                lines.append(f"- {role[2:]} {text!r} @ ({center[0]},{center[1]})")
        for child in (_attr(el, AS.kAXChildrenAttribute) or []):
            if len(lines) >= max_elements:
                break
            _walk(child, depth + 1)

    try:
        for win in windows:
            _walk(win, 0)
            if len(lines) >= max_elements:
                break
    except Exception:  # noqa: BLE001 — AX tree walk failed
        return ""

    if not lines:
        return ""
    return (
        f"Actionable UI in '{app_name}' (role label @ center x,y):\n"
        + "\n".join(lines)
    )


def combined_grounding() -> str:
    """Window list + frontmost-app actionable controls, for the vision loop.
    Each part is best-effort and contributes nothing (``""``) when unavailable.
    """
    parts = [window_grounding(), ax_control_grounding()]
    return "\n\n".join(p for p in parts if p)
