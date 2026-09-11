"""Canonical three-mode approval contract shared by every execution engine.

The persisted ``acceptEdits`` value is retained for backwards compatibility,
but its current product meaning is Codex-style automatic review.  This module
is the server-owned authority for converting client-facing mode names into an
approval reviewer; engines must not reinterpret the legacy label themselves.
"""

from __future__ import annotations

from typing import Literal

ApprovalReviewer = Literal["user", "auto_review"]


def canonical_permission_mode(value: object) -> str:
    raw = str(value or "").strip().replace("_", "-").casefold()
    compact = raw.replace("-", "")
    if compact in {"acceptedits", "autoreview", "approveforme"}:
        return "acceptEdits"
    if compact in {"bypasspermissions", "bypass", "yolo", "full", "fullaccess"}:
        return "bypassPermissions"
    if compact == "plan":
        return "plan"
    return "default"


def approval_reviewer_for_mode(value: object) -> ApprovalReviewer:
    return "auto_review" if canonical_permission_mode(value) == "acceptEdits" else "user"


def is_auto_review_mode(value: object) -> bool:
    return approval_reviewer_for_mode(value) == "auto_review"


__all__ = [
    "ApprovalReviewer",
    "approval_reviewer_for_mode",
    "canonical_permission_mode",
    "is_auto_review_mode",
]
