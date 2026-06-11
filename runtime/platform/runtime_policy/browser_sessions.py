"""Shared browser session state for UI preview and automation surfaces."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_SETTING_KEYS = {
    "browser_regression_enabled",
    "browser_regression_mode",
    "browser_regression_preview_url",
    "browser_regression_requires_visible_cursor",
}


class BrowserSessionCenter:
    """Small in-process registry for browser automation sessions.

    The router owns heavyweight runtime objects such as Playwright pages. This
    class owns the durable state shape and the API-facing snapshots, so browser
    preview, regression, and live automation do not each invent their own view
    of whether a session exists.
    """

    def __init__(
        self,
        config_state: dict[str, Any],
        *,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._config_state = config_state
        self._now = now or (lambda: int(time.time()))
        self.sessions: dict[str, dict[str, Any]] = {}

    def now(self) -> int:
        return self._now()

    def ensure(
        self,
        session_id: str,
        *,
        headless: bool | None = None,
        project_id: str | None = None,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_session_id(session_id)
        normalized_project = self._normalize_project_id(project_id or normalized)
        normalized_profile = self._normalize_profile_id(profile_id or normalized_project)
        now = self.now()
        session = self.sessions.get(normalized)
        if session is None:
            session = {
                "session_id": normalized,
                "project_id": normalized_project,
                "profile_id": normalized_profile,
                "automation_mode": "browser_context",
                "uses_system_mouse": False,
                "desktop_lease_required": False,
                "is_launched": True,
                "created_at": now,
                "last_activity": now,
                "action_count": 0,
                "headless": self._config_state["headless"] if headless is None else bool(headless),
                "current_url": "",
                "current_title": "",
                "history": [],
                "history_index": -1,
                "actions": [],
                "mode": "mock",
                "browser_regression_enabled": False,
                "browser_regression_mode": "off",
                "browser_regression_preview_url": "",
                "browser_regression_requires_visible_cursor": False,
                "playwright": None,
                "browser": None,
                "context": None,
                "page": None,
                "profile_dir": "",
            }
            self.sessions[normalized] = session
        else:
            session["is_launched"] = True
            session["last_activity"] = now
            if headless is not None:
                session["headless"] = bool(headless)
            session.setdefault("project_id", normalized_project)
            session.setdefault("profile_id", normalized_profile)
            session.setdefault("automation_mode", "browser_context")
            session.setdefault("uses_system_mouse", False)
            session.setdefault("desktop_lease_required", False)
            session.setdefault("profile_dir", "")
        return session

    def get(self, session_id: str) -> dict[str, Any] | None:
        return self.sessions.get(self._normalize_session_id(session_id))

    def pop(self, session_id: str) -> dict[str, Any] | None:
        return self.sessions.pop(self._normalize_session_id(session_id), None)

    def update_settings(self, session: dict[str, Any], settings: dict[str, Any]) -> None:
        for key in _SETTING_KEYS:
            if key not in settings:
                continue
            value = settings[key]
            if key in {"browser_regression_enabled", "browser_regression_requires_visible_cursor"}:
                session[key] = bool(value)
            elif key == "browser_regression_mode":
                session[key] = str(value or "off")
            elif key == "browser_regression_preview_url":
                session[key] = str(value or "")

    def record_action(self, session: dict[str, Any], action: str, detail: str) -> None:
        session["last_activity"] = self.now()
        session["action_count"] = int(session.get("action_count", 0)) + 1
        session.setdefault("actions", []).append({
            "action": action,
            "detail": detail,
            "timestamp": session["last_activity"],
        })

    def snapshot(self, session: dict[str, Any]) -> dict[str, Any]:
        page = session.get("page")
        mode = str(session.get("mode") or "mock")
        return {
            "session_id": str(session.get("session_id") or ""),
            "project_id": str(session.get("project_id") or session.get("session_id") or ""),
            "profile_id": str(session.get("profile_id") or session.get("session_id") or ""),
            "profile_dir": str(session.get("profile_dir") or ""),
            "automation_mode": str(session.get("automation_mode") or "browser_context"),
            "uses_system_mouse": bool(session.get("uses_system_mouse", False)),
            "desktop_lease_required": bool(session.get("desktop_lease_required", False)),
            "is_launched": bool(session.get("is_launched")),
            "created_at": int(session.get("created_at") or 0),
            "last_activity": int(session.get("last_activity") or 0),
            "action_count": int(session.get("action_count") or 0),
            "headless": bool(session.get("headless")),
            "mode": mode,
            "runtime": mode,
            "has_page": page is not None,
            "healthy": bool(session.get("is_launched")) and (mode == "mock" or page is not None),
            "current_url": str(session.get("current_url") or ""),
            "current_title": str(session.get("current_title") or ""),
            "browser_regression_enabled": bool(session.get("browser_regression_enabled")),
            "browser_regression_mode": str(session.get("browser_regression_mode") or "off"),
            "browser_regression_preview_url": str(session.get("browser_regression_preview_url") or ""),
            "browser_regression_requires_visible_cursor": bool(
                session.get("browser_regression_requires_visible_cursor")
            ),
        }

    def missing_snapshot(self, session_id: str) -> dict[str, Any]:
        return {
            "session_id": self._normalize_session_id(session_id),
            "project_id": self._normalize_project_id(session_id),
            "profile_id": self._normalize_profile_id(session_id),
            "profile_dir": "",
            "automation_mode": "browser_context",
            "uses_system_mouse": False,
            "desktop_lease_required": False,
            "is_launched": False,
            "created_at": 0,
            "last_activity": 0,
            "action_count": 0,
            "headless": bool(self._config_state["headless"]),
            "mode": "closed",
            "runtime": "closed",
            "has_page": False,
            "healthy": False,
            "current_url": "",
            "current_title": "",
            "browser_regression_enabled": False,
            "browser_regression_mode": "off",
            "browser_regression_preview_url": "",
            "browser_regression_requires_visible_cursor": False,
        }

    def list_snapshots(self) -> list[dict[str, Any]]:
        sessions = [self.snapshot(session) for session in self.sessions.values()]
        sessions.sort(key=lambda item: item["last_activity"], reverse=True)
        return sessions

    @staticmethod
    def _normalize_session_id(session_id: str) -> str:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is required")
        return normalized

    @staticmethod
    def _normalize_project_id(project_id: str) -> str:
        normalized = str(project_id or "").strip()
        return normalized or "default"

    @staticmethod
    def _normalize_profile_id(profile_id: str) -> str:
        raw = str(profile_id or "").strip().lower()
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)
        safe = "-".join(part for part in safe.split("-") if part)
        return safe[:80] or "default"
