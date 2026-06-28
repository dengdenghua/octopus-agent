"""Desktop automation app policy.

The computer router can move the pointer and type into the active desktop.
Keep app allow/deny decisions in a small structured policy so product surfaces
can expose the same kind of durable permission state as browser/site controls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.platform.process.paths import app_paths

SCHEMA = "octopus.computer_automation_policy.v1"

_DEFAULT_POLICY: dict[str, Any] = {
    "schema": SCHEMA,
    "allowed_apps": [],
    "denied_apps": [],
    "preview_required": True,
    "lease_required": True,
    "confirmation_required": True,
    "screenshot_permission_required": True,
    "sensitive_actions": ["click", "key", "type"],
}


def load_computer_automation_policy(
    path: str | Path | None = None,
) -> dict[str, Any]:
    policy_path = _policy_path(path)
    raw: dict[str, Any] = {}
    try:
        loaded = json.loads(policy_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            raw = loaded
    except (OSError, json.JSONDecodeError):
        raw = {}
    policy = normalize_computer_automation_policy(raw)
    policy["path"] = str(policy_path)
    policy["persisted"] = policy_path.exists()
    return policy


def save_computer_automation_policy(
    policy: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    policy_path = _policy_path(path)
    normalized = normalize_computer_automation_policy(policy)
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    normalized["path"] = str(policy_path)
    normalized["persisted"] = True
    return normalized


def update_computer_automation_policy(
    patch: dict[str, Any],
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    current = load_computer_automation_policy(path)
    merged = {**current}
    for key in (
        "allowed_apps",
        "denied_apps",
        "preview_required",
        "lease_required",
        "confirmation_required",
        "screenshot_permission_required",
        "sensitive_actions",
    ):
        if key in patch:
            merged[key] = patch[key]
    return save_computer_automation_policy(merged, path=path)


def normalize_computer_automation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    raw = policy if isinstance(policy, dict) else {}
    normalized = dict(_DEFAULT_POLICY)
    normalized["allowed_apps"] = _string_list(raw.get("allowed_apps"))
    normalized["denied_apps"] = _string_list(raw.get("denied_apps"))
    normalized["sensitive_actions"] = (
        _string_list(raw.get("sensitive_actions"))
        or list(_DEFAULT_POLICY["sensitive_actions"])
    )
    for key in (
        "preview_required",
        "lease_required",
        "confirmation_required",
        "screenshot_permission_required",
    ):
        normalized[key] = bool(raw.get(key, _DEFAULT_POLICY[key]))
    return normalized


def app_permission_decision(
    policy: dict[str, Any],
    *,
    target_app: str,
) -> dict[str, Any]:
    app = _clean(target_app)
    allowed = {item.lower() for item in _string_list(policy.get("allowed_apps"))}
    denied = {item.lower() for item in _string_list(policy.get("denied_apps"))}
    app_key = app.lower()
    if app_key and app_key in denied:
        decision = "denied"
        reason = "target app is blocked by the desktop automation policy"
    elif app_key and app_key in allowed:
        decision = "allowed"
        reason = "target app is explicitly allowed by the desktop automation policy"
    else:
        decision = "prompt"
        reason = "target app has no durable allow decision"
    return {
        "schema": "octopus.computer_automation_policy_decision.v1",
        "target_app": app,
        "decision": decision,
        "reason": reason,
        "preview_required": bool(policy.get("preview_required", True)),
        "lease_required": bool(policy.get("lease_required", True)),
        "confirmation_required": bool(policy.get("confirmation_required", True)),
    }


def _policy_path(path: str | Path | None) -> Path:
    return Path(path).expanduser().resolve() if path is not None else app_paths().computer_automation_policy_path


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        item = _clean(str(raw))
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return items[:100]


def _clean(value: str) -> str:
    return " ".join(value.strip().split())[:120]


__all__ = [
    "SCHEMA",
    "app_permission_decision",
    "load_computer_automation_policy",
    "normalize_computer_automation_policy",
    "save_computer_automation_policy",
    "update_computer_automation_policy",
]
