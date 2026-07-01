"""Computer automation API.

The surface is intentionally split into observe -> preview -> execute.
Mouse and keyboard actions are high-risk, so the UI must first create a
short-lived preview token and then send that token back for execution.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from runtime.execution.suckers import computer_skills, computer_uia_skills
from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.process.paths import app_paths
from runtime.safety.replay.browser_desktop_replay import computer_activity_replay_identity

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]


_VALID_ACTIONS = {"click", "move", "type", "key", "wait"}
_PENDING_TTL_SECONDS = 90
_LEASE_TTL_SECONDS = 30
_DEFAULT_LEASE_OWNER_ID = "default-computer-operator"
_DEFAULT_LEASE_OWNER_LABEL = "Default operator"


def create_computer_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    def _auth_dep(request: Request) -> None:
        # Desktop automation can click/type on the host machine. Keep
        # the current friction-free local-dev behavior, but in auth-on
        # deploys reject anonymous access at the router boundary.
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(
        prefix="/api/computer",
        tags=["computer"],
        dependencies=[Depends(_auth_dep)],
    )
    pending: dict[str, dict[str, Any]] = {}
    lease: dict[str, Any] = {}
    activity: list[dict[str, Any]] = []
    screenshot_root = Path("data/computer_automation/screenshots").resolve()

    def _cleanup_pending() -> None:
        now = time.time()
        expired = [
            token
            for token, item in pending.items()
            if now - float(item.get("created_at") or 0) > _PENDING_TTL_SECONDS
        ]
        for token in expired:
            pending.pop(token, None)

    def _record_activity(
        event: str,
        *,
        ok: bool = True,
        action: dict[str, Any] | None = None,
        token: str = "",
        risk: dict[str, str] | None = None,
        lease_state: dict[str, Any] | None = None,
        error: str = "",
        detail: dict[str, Any] | None = None,
        proof: dict[str, Any] | None = None,
    ) -> None:
        activity.append({
            "id": uuid.uuid4().hex,
            "event": event,
            "ok": ok,
            "action": action or {},
            "token": token,
            "risk": risk or {},
            "lease": lease_state or _public_lease(),
            "error": error,
            "detail": detail or {},
            "proof": proof or {},
            "created_at": time.time(),
        })
        if len(activity) > 500:
            del activity[:-500]

    def _queue_activity_replay_case(
        replay_case: dict[str, Any],
        *,
        reason: str = "",
        priority: str = "",
    ) -> dict[str, Any]:
        items = replay_case.get("items") if isinstance(replay_case.get("items"), list) else []
        last_activity = replay_case.get("last_activity")
        last_activity = last_activity if isinstance(last_activity, dict) else {}
        has_failure = any(
            isinstance(item, dict) and item.get("ok") is False
            for item in items
        )
        chosen_priority = priority or ("P0" if has_failure else "P1")
        last_event = str(last_activity.get("event") or "no activity")
        last_action = last_activity.get("action")
        last_action = last_action if isinstance(last_action, dict) else {}
        case_id = str(replay_case.get("case_id") or "")
        fingerprint = str(replay_case.get("fingerprint") or "")
        text = (
            f"Computer automation replay case `{case_id}` captured for operator review.\n"
            f"Last event: {last_event}; action: {last_action.get('action', 'none')}.\n"
            f"Activity count: {replay_case.get('activity_count', 0)}; "
            f"pending previews: {replay_case.get('pending_count', 0)}."
        )
        if reason:
            text += f"\nReason: {reason[:500]}"
        queue = ReviewQueue(app_paths().review_queue_path)
        return queue.upsert_item(
            source="computer_activity_replay",
            source_kind="browser_desktop_replay",
            candidate_kind="computer_activity_replay_case",
            priority=chosen_priority,
            target_bucket="browser_desktop_replay",
            title="Review computer automation replay case",
            text=text,
            metadata={
                "schema": replay_case.get("schema"),
                "case_id": case_id,
                "fingerprint": fingerprint,
                "replay_ready": bool(replay_case.get("replay_ready")),
                "activity_count": replay_case.get("activity_count"),
                "pending_count": replay_case.get("pending_count"),
                "lease": replay_case.get("lease"),
                "last_activity": last_activity,
                "proof": last_activity.get("proof") if isinstance(last_activity.get("proof"), dict) else {},
            },
            tags=[
                "computer",
                "desktop",
                "replay_case",
                "review_queue",
                "operator_review",
            ],
        )

    def _queue_uia_replay_assertion(
        action: dict[str, Any],
        assertion: dict[str, Any],
    ) -> dict[str, Any]:
        matched = (
            assertion.get("matched_control")
            if isinstance(assertion.get("matched_control"), dict)
            else action.get("matched_control")
            if isinstance(action.get("matched_control"), dict)
            else {}
        )
        label = str(matched.get("name") or matched.get("automation_id") or "desktop control")
        reason = str(assertion.get("reason") or assertion.get("error") or "UIA replay assertion failed")
        queue = ReviewQueue(app_paths().review_queue_path)
        return queue.upsert_item(
            source="computer_uia_replay_assertion",
            source_kind="browser_desktop_replay",
            candidate_kind="computer_uia_replay_assertion",
            priority="P0",
            target_bucket="browser_desktop_replay",
            title=f"Review desktop UIA replay assertion: {label}",
            text=(
                f"Desktop UIA replay assertion failed for `{label}`.\n"
                f"Reason: {reason[:500]}."
            ),
            metadata={
                "schema": "octopus.computer_uia_replay_assertion_queue.v1",
                "trace_id": assertion.get("trace_id"),
                "action": action,
                "replay_assertion": assertion,
                "source_trace": assertion.get("source_trace") if isinstance(assertion.get("source_trace"), dict) else {},
                "matched_control": matched,
            },
            tags=[
                "computer",
                "desktop",
                "uia",
                "replay_assertion",
                "review_queue",
            ],
        )

    def _computer_replay_evidence(*, limit: int = 100) -> dict[str, Any]:
        items = [item for item in activity[-limit:] if isinstance(item, dict)]
        identity = computer_activity_replay_identity(
            items=items,
            pending_count=len(pending),
        )
        return {
            "schema": "octopus.computer_replay_evidence_hint.v1",
            "case_id": identity["case_id"],
            "fingerprint": identity["fingerprint"],
            "replay_ready": bool(items),
            "replay_case_url": "/api/computer/activity/replay-case",
            "queue_url": "/api/computer/activity/replay-case/queue",
            "queue_body": {"limit": limit},
        }

    def _computer_diagnostic(
        code: str,
        *,
        severity: str,
        message: str,
        recommended_action: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": "octopus.computer_automation_diagnostic.v1",
            "code": code,
            "severity": severity,
            "message": message,
            "recommended_action": recommended_action,
            "metadata": metadata or {},
        }

    def _execution_failure_diagnostic(
        action: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        error = str(result.get("error") or "")
        category = _classify_computer_error(error)
        action_by_category = {
            "display_unavailable": "check_display_or_permissions",
            "permission": "review_desktop_permissions",
            "coordinate": "replan_with_fresh_screenshot",
            "timeout": "retry_with_shorter_sequence",
        }
        return _computer_diagnostic(
            "action_execution_failed",
            severity="error",
            message="Desktop automation action failed.",
            recommended_action=action_by_category.get(category, "queue_replay_case"),
            metadata={
                "action": str(action.get("action") or ""),
                "error": error,
                "error_category": category,
            },
        )

    def _computer_capability(
        capability_id: str,
        *,
        title: str,
        available: bool,
        mode: str,
        reason: str = "",
        recommended_action: str = "",
        critical: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": capability_id,
            "title": title,
            "available": bool(available),
            "critical": bool(critical),
            "mode": mode,
            "reason": reason,
            "recommended_action": recommended_action,
            "metadata": metadata or {},
        }

    def _runtime_readiness(
        *,
        screen_info: dict[str, Any],
        uia_status: dict[str, Any],
        lease_state: dict[str, Any],
    ) -> dict[str, Any]:
        screen_ok = "error" not in screen_info
        uia_ok = bool(uia_status.get("available"))
        lease_held = bool(lease_state.get("held"))
        replay_evidence = _computer_replay_evidence()
        capabilities = [
            _computer_capability(
                "screen_observation",
                title="Screen observation",
                available=screen_ok,
                critical=True,
                mode="pyautogui_screen_info",
                reason=str(screen_info.get("error") or ""),
                recommended_action=(
                    "check_display_or_desktop_permissions" if not screen_ok else ""
                ),
                metadata={
                    key: screen_info.get(key)
                    for key in ("width", "height", "cursor_x", "cursor_y")
                    if key in screen_info
                },
            ),
            _computer_capability(
                "preview_execute_contract",
                title="Preview-confirm-execute contract",
                available=True,
                critical=True,
                mode="token_preview_with_lease",
                metadata={
                    "pending_count": len(pending),
                    "lease_ttl_seconds": _LEASE_TTL_SECONDS,
                },
            ),
            _computer_capability(
                "lease_coordination",
                title="Desktop lease coordination",
                available=not lease_held,
                critical=False,
                mode="exclusive_operator_lease",
                reason=(
                    f"lease held by {lease_state.get('owner_label') or lease_state.get('owner_id')}"
                    if lease_held
                    else ""
                ),
                recommended_action="wait_or_release_lease" if lease_held else "",
                metadata=lease_state,
            ),
            _computer_capability(
                "uia_semantic_grounding",
                title="UIA semantic grounding",
                available=uia_ok,
                critical=False,
                mode="accessibility_tree",
                reason=str(uia_status.get("error") or ""),
                recommended_action=(
                    "install_or_enable_uia_backend" if not uia_ok else ""
                ),
                metadata={
                    "platform": uia_status.get("platform"),
                    "available": uia_status.get("available"),
                },
            ),
            _computer_capability(
                "replay_evidence",
                title="Replay evidence and review queue",
                available=True,
                critical=True,
                mode="activity_replay_case",
                metadata={
                    "replay_ready": replay_evidence.get("replay_ready"),
                    "case_id": replay_evidence.get("case_id"),
                    "fingerprint": replay_evidence.get("fingerprint"),
                    "activity_count": len(activity),
                },
            ),
        ]
        critical_blockers = [
            item for item in capabilities
            if item["critical"] and not item["available"]
        ]
        degraded = [
            item for item in capabilities
            if not item["available"] and not item["critical"]
        ]
        if critical_blockers:
            health = "blocked"
        elif degraded:
            health = "degraded"
        else:
            health = "ready"
        recommended_actions = [
            str(item.get("recommended_action") or "")
            for item in [*critical_blockers, *degraded]
            if str(item.get("recommended_action") or "").strip()
        ]
        return {
            "schema": "octopus.computer_runtime_readiness.v1",
            "ready": not critical_blockers,
            "health": health,
            "capabilities": capabilities,
            "degraded_capabilities": degraded,
            "critical_blockers": critical_blockers,
            "recommended_actions": recommended_actions,
            "replay_evidence": replay_evidence,
        }

    def _classify_computer_error(error: str) -> str:
        lower = error.lower()
        if any(token in lower for token in ("display", "screen", "x server", "quartz")):
            return "display_unavailable"
        if any(token in lower for token in ("permission", "accessibility", "denied", "not allowed")):
            return "permission"
        if any(token in lower for token in ("coordinate", "bounds", "out of range", "outside")):
            return "coordinate"
        if any(token in lower for token in ("timeout", "timed out", "deadline")):
            return "timeout"
        return "unknown"

    def _cleanup_lease(now: float | None = None) -> None:
        if not lease:
            return
        current = time.time() if now is None else now
        if float(lease.get("expires_at") or 0) <= current:
            lease.clear()

    def _lease_from_body(body: dict[str, Any] | None) -> dict[str, str]:
        body = body or {}
        owner_id = str(
            body.get("lease_owner_id")
            or body.get("owner_id")
            or body.get("project_id")
            or _DEFAULT_LEASE_OWNER_ID
        ).strip()
        owner_label = str(
            body.get("lease_owner_label")
            or body.get("owner_label")
            or body.get("project_label")
            or _DEFAULT_LEASE_OWNER_LABEL
        ).strip()
        return {
            "owner_id": owner_id[:120] or _DEFAULT_LEASE_OWNER_ID,
            "owner_label": owner_label[:120] or _DEFAULT_LEASE_OWNER_LABEL,
        }

    def _public_lease(now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else now
        _cleanup_lease(current)
        if not lease:
            return {
                "held": False,
                "ttl_seconds": 0,
                "lease_ttl_seconds": _LEASE_TTL_SECONDS,
            }
        return {
            "held": True,
            "owner_id": lease.get("owner_id"),
            "owner_label": lease.get("owner_label"),
            "acquired_at": lease.get("acquired_at"),
            "updated_at": lease.get("updated_at"),
            "expires_at": lease.get("expires_at"),
            "ttl_seconds": max(0, int(round(float(lease["expires_at"]) - current))),
            "lease_ttl_seconds": _LEASE_TTL_SECONDS,
        }

    def _claim_lease(owner: dict[str, str]) -> dict[str, Any]:
        now = time.time()
        _cleanup_lease(now)
        owner_id = owner["owner_id"]
        if lease and lease.get("owner_id") != owner_id:
            lease_state = _public_lease(now)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "computer lease is held by another operator",
                    "lease": lease_state,
                    "diagnostic": _computer_diagnostic(
                        "lease_conflict",
                        severity="warning",
                        message="Computer automation lease is held by another operator.",
                        recommended_action="wait_or_release_lease",
                        metadata={
                            "requested_owner_id": owner_id,
                            "current_owner_id": lease_state.get("owner_id"),
                            "ttl_seconds": lease_state.get("ttl_seconds"),
                        },
                    ),
                    "recommended_actions": ["wait_or_release_lease"],
                    "replay_evidence": _computer_replay_evidence(),
                },
            )
        acquired_at = float(lease.get("acquired_at") or now) if lease else now
        lease.update({
            "owner_id": owner_id,
            "owner_label": owner["owner_label"],
            "acquired_at": acquired_at,
            "updated_at": now,
            "expires_at": now + _LEASE_TTL_SECONDS,
        })
        return _public_lease(now)

    def _release_lease(owner: dict[str, str], *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        _cleanup_lease(now)
        if lease and not force and lease.get("owner_id") != owner["owner_id"]:
            lease_state = _public_lease(now)
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "computer lease is held by another operator",
                    "lease": lease_state,
                    "diagnostic": _computer_diagnostic(
                        "lease_release_conflict",
                        severity="warning",
                        message="Computer automation lease can only be released by its owner.",
                        recommended_action="release_with_owner_or_force",
                        metadata={
                            "requested_owner_id": owner["owner_id"],
                            "current_owner_id": lease_state.get("owner_id"),
                            "ttl_seconds": lease_state.get("ttl_seconds"),
                        },
                    ),
                    "recommended_actions": ["release_with_owner_or_force"],
                    "replay_evidence": _computer_replay_evidence(),
                },
            )
        lease.clear()
        return _public_lease(now)

    def _normalize_action(body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action") or "").strip().lower()
        if action not in _VALID_ACTIONS:
            raise HTTPException(400, f"unsupported action: {action or '<empty>'}")

        if action in {"click", "move"}:
            normalized = {
                "action": action,
                "x": int(body.get("x", -1)),
                "y": int(body.get("y", -1)),
                "button": str(body.get("button") or "left"),
                "clicks": int(body.get("clicks") or 1),
                "duration": float(body.get("duration") or 0.0),
            }
            for key in ("source", "matched_control", "replay_assertion"):
                value = body.get(key)
                if isinstance(value, (str, dict)):
                    normalized[key] = value
            return normalized
        if action == "type":
            return {
                "action": "type",
                "text": str(body.get("text") or ""),
                "interval": float(body.get("interval") or 0.01),
            }
        if action == "key":
            keys = body.get("keys")
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split("+") if k.strip()]
            if not isinstance(keys, list):
                raise HTTPException(400, "keys must be a list or + separated string")
            return {"action": "key", "keys": keys}
        return {"action": "wait", "ms": int(body.get("ms") or 500)}

    def _risk_for(action: dict[str, Any]) -> dict[str, str]:
        kind = action["action"]
        if kind == "type":
            return {
                "level": "high",
                "reason": "will type text into the currently focused application",
            }
        if kind in {"click", "key"}:
            return {
                "level": "medium",
                "reason": "can trigger UI actions in the active application",
            }
        return {"level": "low", "reason": "does not submit data by itself"}

    def _execute(action: dict[str, Any]) -> dict[str, Any]:
        kind = action["action"]
        if kind == "click":
            return computer_skills._mouse_click(
                x=int(action["x"]),
                y=int(action["y"]),
                button=str(action.get("button") or "left"),
                clicks=int(action.get("clicks") or 1),
                duration=float(action.get("duration") or 0.0),
            )
        if kind == "move":
            return computer_skills._mouse_move(
                x=int(action["x"]),
                y=int(action["y"]),
                duration=float(action.get("duration") or 0.2),
            )
        if kind == "type":
            return computer_skills._keyboard_type(
                text=str(action.get("text") or ""),
                interval=float(action.get("interval") or 0.01),
            )
        if kind == "key":
            return computer_skills._keyboard_press(keys=action.get("keys"))
        if kind == "wait":
            ms = int(action.get("ms") or 0)
            if ms < 0 or ms > 60_000:
                return {"error": f"wait ms out of range: {ms}"}
            time.sleep(ms / 1000)
            return {"waited_ms": ms}
        return {"error": f"unsupported action: {kind}"}

    def _ensure_uia_replay_trace(action: dict[str, Any]) -> dict[str, Any]:
        assertion = (
            action.get("replay_assertion")
            if isinstance(action.get("replay_assertion"), dict)
            else {}
        )
        if not assertion or assertion.get("trace_id") and assertion.get("source_trace"):
            return action
        enriched = computer_uia_skills.uia_replay_assertion_for_action(action)
        merged = {
            **assertion,
            "trace_id": assertion.get("trace_id") or enriched.get("trace_id"),
            "source_trace": assertion.get("source_trace") or enriched.get("source_trace"),
        }
        action = dict(action)
        action["replay_assertion"] = merged
        return action

    def _queue_preview(action: dict[str, Any], owner: dict[str, str]) -> dict[str, Any]:
        action = _ensure_uia_replay_trace(action)
        token = uuid.uuid4().hex
        risk = _risk_for(action)
        contract = _preview_contract(action, owner, risk)
        pending[token] = {
            "token": token,
            "action": action,
            "risk": risk,
            "preview_contract": contract,
            "created_at": time.time(),
            "lease_owner": owner,
        }
        return {
            "token": token,
            "action": action,
            "risk": risk,
            "preview_contract": contract,
            "expires_in_seconds": _PENDING_TTL_SECONDS,
            "lease_owner": owner,
        }

    def _preview_contract(
        action: dict[str, Any],
        owner: dict[str, str],
        risk: dict[str, str],
    ) -> dict[str, Any]:
        payload = {
            "schema": "octopus.computer_preview_contract.v1",
            "action": _stable_action_payload(action),
            "lease_owner": owner,
            "risk": risk,
            "ttl_seconds": _PENDING_TTL_SECONDS,
            "requires_execute_token": True,
        }
        payload["contract_id"] = _stable_digest(payload)
        return payload

    def _execution_proof(
        *,
        contract: dict[str, Any],
        action: dict[str, Any],
        risk: dict[str, str],
        lease_state: dict[str, Any],
        result: dict[str, Any],
        ok: bool,
    ) -> dict[str, Any]:
        payload = {
            "schema": "octopus.computer_execution_proof.v1",
            "preview_contract_id": contract.get("contract_id"),
            "action": _stable_action_payload(action),
            "risk": risk,
            "lease": {
                "held": bool(lease_state.get("held")),
                "owner_id": lease_state.get("owner_id"),
                "owner_label": lease_state.get("owner_label"),
            },
            "result": _stable_result_payload(result),
            "ok": ok,
        }
        payload["proof_id"] = _stable_digest(payload)
        return payload

    def _stable_action_payload(action: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "action",
            "x",
            "y",
            "button",
            "clicks",
            "duration",
            "text",
            "interval",
            "keys",
            "ms",
            "source",
            "matched_control",
            "replay_assertion",
        }
        return {
            key: _stable_value(action.get(key))
            for key in sorted(allowed)
            if key in action
        }

    def _stable_result_payload(result: dict[str, Any]) -> dict[str, Any]:
        return {
            str(key): _stable_value(value)
            for key, value in sorted(result.items())
            if str(key) not in {"created_at", "timestamp", "token"}
        }

    def _stable_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): _stable_value(item)
                for key, item in sorted(value.items())
                if str(key) not in {"created_at", "timestamp", "token"}
            }
        if isinstance(value, list):
            return [_stable_value(item) for item in value]
        if isinstance(value, bool | int | float) or value is None:
            return value
        return str(value)

    def _stable_digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _goal_uia_queries(goal: str) -> list[str]:
        text = goal.strip()
        if not text:
            return []
        candidates: list[str] = []
        for match in re.finditer(r"[\"'“”‘’]([^\"'“”‘’]{1,60})[\"'“”‘’]", text):
            candidates.append(match.group(1))
        patterns = (
            r"(?:click|press|select|open)\s+(?:the\s+)?(.{1,60})",
            r"(?:点击|单击|按下|选择|打开)\s*([^,，。；;:：\n\r]{1,40})",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                candidates.append(match.group(1))
        if (
            not candidates
            and len(text) <= 40
            and "http://" not in text
            and "https://" not in text
        ):
            candidates.append(text)

        cleaned: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            item = candidate.strip(" \t\r\n'\"“”‘’()[]{}<>:：,，.。;；")
            item = re.sub(
                r"\b(button|control|field|link|menu)\b",
                "",
                item,
                flags=re.IGNORECASE,
            )
            item = item.replace("按钮", "").replace("控件", "").replace("菜单", "")
            item = " ".join(item.split()).strip()
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                cleaned.append(item)
        return cleaned[:5]

    def _uia_actions_for_goal(goal: str) -> list[dict[str, Any]]:
        candidates: list[tuple[int, str, dict[str, Any]]] = []
        for query in _goal_uia_queries(goal):
            found = computer_uia_skills._computer_uia_find(
                query=query,
                max_results=5,
                max_depth=5,
                max_nodes=300,
            )
            if not found.get("ok"):
                continue
            for match in found.get("matches") or []:
                if not isinstance(match, dict):
                    continue
                if match.get("offscreen") or match.get("enabled") is False:
                    continue
                center = match.get("center")
                if not isinstance(center, dict):
                    continue
                try:
                    x = int(center["x"])
                    y = int(center["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                score = _uia_match_score(match, query)
                action = {
                    "action": "click",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "clicks": 1,
                    "duration": 0.0,
                    "source": "uia",
                    "matched_control": {
                        "id": match.get("id"),
                        "name": match.get("name"),
                        "control_type": match.get("control_type"),
                        "class_name": match.get("class_name"),
                        "automation_id": match.get("automation_id"),
                        "center": center,
                        "rect": match.get("rect"),
                        "query": query,
                        "score": score,
                    },
                }
                action["replay_assertion"] = computer_uia_skills.uia_replay_assertion_for_action(
                    action,
                )
                candidates.append((score, query, action))
        if not candidates:
            return []
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [candidates[0][2]]

    def _uia_match_score(match: dict[str, Any], query: str) -> int:
        needle = query.strip().lower()
        name = str(match.get("name") or "").strip().lower()
        automation_id = str(match.get("automation_id") or "").strip().lower()
        class_name = str(match.get("class_name") or "").strip().lower()
        control_type = str(match.get("control_type") or "").strip().lower()

        score = 0
        if bool(match.get("interactive")):
            score += 100
        if name == needle:
            score += 80
        elif name.startswith(needle):
            score += 60
        elif needle and needle in name:
            score += 40
        if automation_id == needle:
            score += 70
        elif needle and needle in automation_id:
            score += 35
        if needle and needle in class_name:
            score += 10
        if "button" in control_type or "menuitem" in control_type or "hyperlink" in control_type:
            score += 15
        if match.get("enabled") is not False:
            score += 5
        return score

    def _plan_actions(goal: str) -> list[dict[str, Any]]:
        text = goal.strip().lower()
        if not text:
            return []

        actions: list[dict[str, Any]] = []
        if "http://" in text or "https://" in text:
            url = goal.strip()
            for marker in ("http://", "https://"):
                idx = url.lower().find(marker)
                if idx >= 0:
                    url = url[idx:].split()[0]
                    break
            actions.extend([
                {"action": "key", "keys": ["ctrl", "l"]},
                {"action": "type", "text": url, "interval": 0.01},
                {"action": "key", "keys": ["enter"]},
            ])
        elif uia_actions := _uia_actions_for_goal(goal):
            actions.extend(uia_actions)
        elif any(word in text for word in ("browser", "chrome", "edge", "浏览器", "网页")):
            actions.extend([
                {"action": "key", "keys": ["win"]},
                {"action": "type", "text": "edge", "interval": 0.01},
                {"action": "key", "keys": ["enter"]},
            ])
        elif any(word in text for word in ("刷新", "reload", "refresh")):
            actions.append({"action": "key", "keys": ["ctrl", "r"]})
        elif any(word in text for word in ("关闭", "close")):
            actions.append({"action": "key", "keys": ["alt", "f4"]})
        else:
            actions.append({"action": "wait", "ms": 500})
        return actions[:5]

    def _extract_json_payload(text: str) -> Any:
        cleaned = text.strip()
        if not cleaned:
            raise HTTPException(400, "missing vision output")
        fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL | re.IGNORECASE)
        if fenced:
            cleaned = fenced.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start_candidates = [idx for idx in (cleaned.find("{"), cleaned.find("[")) if idx >= 0]
            if not start_candidates:
                raise HTTPException(400, "vision output does not contain JSON") from None
            start = min(start_candidates)
            end = max(cleaned.rfind("}"), cleaned.rfind("]"))
            if end <= start:
                raise HTTPException(400, "vision output JSON is incomplete") from None
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise HTTPException(400, f"invalid vision output JSON: {exc}") from None

    def _actions_from_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            raw_actions = payload["actions"]
        elif isinstance(payload, dict) and isinstance(payload.get("suggestions"), list):
            raw_actions = [
                item.get("action") if isinstance(item, dict) else item
                for item in payload["suggestions"]
            ]
        elif isinstance(payload, list):
            raw_actions = payload
        else:
            raw_actions = [payload]

        actions = []
        for raw in raw_actions[:5]:
            if not isinstance(raw, dict):
                continue
            normalized_input = dict(raw)
            if "action" not in normalized_input and "type" in normalized_input:
                normalized_input["action"] = normalized_input["type"]
            actions.append(_normalize_action(normalized_input))
        return actions

    def _load_custom_model(model_id: str) -> dict[str, Any] | None:
        if not model_id:
            return None
        path = Path("data/custom_models.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        entry = data.get(model_id)
        return entry if isinstance(entry, dict) else None

    def _vision_model_config(model_id: str) -> dict[str, Any] | None:
        import os

        selected = model_id or os.getenv("OCTOPUS_COMPUTER_VISION_MODEL", "")
        entry = _load_custom_model(selected)
        if entry:
            # Pick the first upstream model id from the new
            # ``models`` list, falling back to the legacy ``model``
            # field so pre-refactor entries keep working.
            upstream = ""
            raw_models = entry.get("models")
            if isinstance(raw_models, list):
                for m in raw_models:
                    if isinstance(m, str) and m.strip():
                        upstream = m.strip()
                        break
            if not upstream:
                legacy = entry.get("model")
                if isinstance(legacy, str) and legacy.strip():
                    upstream = legacy.strip()
            if not upstream:
                upstream = selected
            return {
                "id": selected,
                "provider": str(entry.get("provider") or "openai").lower(),
                "base_url": str(entry.get("base_url") or ""),
                "api_key": str(entry.get("api_key") or ""),
                "model": upstream,
                "default_headers": entry.get("default_headers") or {},
            }

        env_base = os.getenv("OCTOPUS_COMPUTER_VISION_BASE_URL", "")
        env_key = os.getenv("OCTOPUS_COMPUTER_VISION_API_KEY", "")
        env_model = selected or os.getenv("OCTOPUS_COMPUTER_VISION_UPSTREAM_MODEL", "")
        if env_base and env_model:
            return {
                "id": selected or env_model,
                "provider": "openai",
                "base_url": env_base,
                "api_key": env_key,
                "model": env_model,
                "default_headers": {},
            }
        return None

    def _call_openai_vision(
        *,
        config: dict[str, Any],
        goal: str,
        data_url: str,
    ) -> str:
        if not HTTPX_AVAILABLE or httpx is None:
            raise HTTPException(503, "httpx not installed")
        provider = str(config.get("provider") or "openai").lower()
        if provider not in {"openai", "openai-compatible", "custom"}:
            raise HTTPException(
                400,
                f"vision call currently supports openai-compatible models only, got {provider}",
            )
        base_url = str(config.get("base_url") or "").rstrip("/")
        model = str(config.get("model") or "")
        if not base_url or not model:
            raise HTTPException(400, "vision model base_url and model are required")
        headers = {
            "Content-Type": "application/json",
        }
        api_key = str(config.get("api_key") or "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        default_headers = config.get("default_headers") or {}
        if isinstance(default_headers, dict):
            headers.update({str(k): str(v) for k, v in default_headers.items()})

        prompt = (
            "You are a desktop UI grounding model. "
            "Inspect the screenshot and return only JSON. "
            "Schema: {\"actions\":[{\"action\":\"click\",\"x\":number,\"y\":number,"
            "\"button\":\"left\"}]} or type/key/wait actions. "
            "Coordinates must use the screenshot's native pixel coordinate system. "
            f"Task: {goal}"
        )
        payload = {
            "model": model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
        }
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"vision upstream request failed: {exc}") from exc
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "vision upstream returned an error")
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(502, "vision upstream returned non-JSON") from exc
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise HTTPException(502, "vision upstream returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            parts = [
                str(part.get("text"))
                for part in content
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            ]
            content = "\n".join(parts)
        if not isinstance(content, str) or not content.strip():
            raise HTTPException(502, "vision upstream returned empty content")
        return content

    @router.get("/status")
    def status() -> dict[str, Any]:
        _cleanup_pending()
        lease_state = _public_lease()
        info = computer_skills._screen_info()
        uia_status = computer_uia_skills._computer_uia_status()
        readiness = _runtime_readiness(
            screen_info=info,
            uia_status=uia_status,
            lease_state=lease_state,
        )
        return {
            "schema": "octopus.computer_runtime_status.v1",
            "ok": "error" not in info,
            "ready": readiness["ready"],
            "health": readiness["health"],
            "pyautogui_available": bool(computer_skills.PYAUTOGUI_AVAILABLE),
            "uia_available": bool(uia_status.get("available")),
            "uia": uia_status,
            "lease": lease_state,
            "screen": info,
            "readiness": readiness,
            "capabilities": readiness["capabilities"],
            "degraded_capabilities": readiness["degraded_capabilities"],
            "critical_blockers": readiness["critical_blockers"],
            "recommended_actions": readiness["recommended_actions"],
            "replay_evidence": readiness["replay_evidence"],
            "activity_count": len(activity),
            "recent_activity": activity[-10:],
            "skills": [
                "screen_capture",
                "screen_info",
                "mouse_click",
                "mouse_move",
                "keyboard_type",
                "keyboard_press",
                "computer_observe",
                "computer_plan_next",
                "computer_preview_action",
                "computer_execute_token",
                "computer_use_loop",
                "computer_uia_status",
                "computer_uia_tree",
                "computer_uia_find",
            ],
            "mode": "preview-confirm-execute-with-lease",
        }

    @router.get("/activity")
    def computer_activity(
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        _cleanup_pending()
        return {
            "schema": "octopus.computer_activity.v1",
            "count": len(activity),
            "pending_count": len(pending),
            "lease": _public_lease(),
            "items": activity[-limit:],
        }

    @router.get("/activity/replay-case")
    def computer_activity_replay_case(
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        _cleanup_pending()
        items = activity[-limit:]
        identity = computer_activity_replay_identity(
            items=[item for item in items if isinstance(item, dict)],
            pending_count=len(pending),
        )
        return {
            "schema": "octopus.computer_activity_replay_case.v1",
            "case_id": identity["case_id"],
            "fingerprint": identity["fingerprint"],
            "replay_ready": bool(items),
            "activity_count": len(items),
            "pending_count": len(pending),
            "lease": _public_lease(),
            "items": items,
            "last_activity": items[-1] if items else None,
        }

    @router.post("/activity/replay-case/queue")
    def computer_activity_replay_case_queue(body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        limit = int(body.get("limit") or 100)
        limit = max(1, min(500, limit))
        replay_case = computer_activity_replay_case(limit=limit)
        if not replay_case.get("replay_ready"):
            raise HTTPException(409, "computer activity replay case has no actions to review")
        queued = _queue_activity_replay_case(
            replay_case,
            reason=str(body.get("reason") or ""),
            priority=str(body.get("priority") or ""),
        )
        return {
            "ok": True,
            "schema": "octopus.computer_activity_replay_case_queue.v1",
            "replay_case": replay_case,
            "queue": queued,
        }

    @router.post("/screenshot")
    def screenshot(body: dict[str, Any] | None = None) -> dict[str, Any]:
        body = body or {}
        screenshot_root.mkdir(parents=True, exist_ok=True)
        shot_path = screenshot_root / f"{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
        region = body.get("region")
        result = computer_skills._screen_capture(
            path=str(shot_path),
            sandbox_dir=str(screenshot_root),
            region=region if isinstance(region, list) else None,
        )
        if "error" in result:
            return {"ok": False, "error": result["error"]}
        data = shot_path.read_bytes()
        return {
            "ok": True,
            "path": str(shot_path),
            "size_bytes": len(data),
            "data_url": "data:image/png;base64,"
            + base64.standard_b64encode(data).decode("ascii"),
            "created_at": time.time(),
        }

    @router.get("/uia/status")
    def uia_status() -> dict[str, Any]:
        return computer_uia_skills._computer_uia_status()

    @router.get("/uia/tree")
    def uia_tree(
        root: str = Query(default="foreground"),
        max_depth: int = Query(default=2, ge=0, le=8),
        max_nodes: int = Query(default=80, ge=1, le=1000),
        max_children: int = Query(default=30, ge=1, le=200),
        include_offscreen: bool = Query(default=False),
    ) -> dict[str, Any]:
        return computer_uia_skills._computer_uia_tree(
            root=root,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_children=max_children,
            include_offscreen=include_offscreen,
        )

    @router.get("/uia/find")
    def uia_find(
        query: str = Query(default=""),
        exact: bool = Query(default=False),
        root: str = Query(default="foreground"),
        max_results: int = Query(default=20, ge=1, le=100),
        max_depth: int = Query(default=5, ge=0, le=8),
        max_nodes: int = Query(default=300, ge=1, le=1000),
        include_offscreen: bool = Query(default=False),
    ) -> dict[str, Any]:
        return computer_uia_skills._computer_uia_find(
            query=query,
            exact=exact,
            root=root,
            max_results=max_results,
            max_depth=max_depth,
            max_nodes=max_nodes,
            include_offscreen=include_offscreen,
        )

    @router.post("/actions/preview")
    def preview_action(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        action = _normalize_action(body)
        preview = _queue_preview(action, owner)
        _record_activity(
            "preview_queued",
            action=action,
            token=str(preview["token"]),
            risk=preview["risk"],
            detail={
                "lease_owner": owner,
                "preview_contract_id": preview["preview_contract"]["contract_id"],
            },
            proof={"preview_contract": preview["preview_contract"]},
        )
        return {
            "ok": True,
            "lease": _public_lease(),
            **preview,
        }

    @router.post("/actions/plan")
    def plan_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        capture = bool(body.get("capture", True))
        screenshot_data: dict[str, Any] | None = None
        if capture:
            screenshot_data = screenshot({})

        suggestions = []
        for idx, action in enumerate(_plan_actions(goal), start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"step-{idx}",
                "title": f"Step {idx}: {action['action']}",
                "rationale": "Heuristic next action based on the task text and current screen observation.",
                **preview,
            })
        _record_activity(
            "plan_created",
            detail={
                "goal": goal,
                "suggestion_count": len(suggestions),
                "capture": capture,
            },
        )

        return {
            "ok": True,
            "goal": goal,
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "observe-plan-confirm",
            "lease": _public_lease(),
            "limitations": [
                "This first pass uses local heuristics and UIA semantic grounding when available.",
                "Visual screenshot grounding is only used by /actions/vision, not this local planner.",
                "Every suggested action still requires explicit user confirmation before execution.",
            ],
        }

    @router.post("/actions/ground")
    def ground_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        output = body.get("output")
        capture = bool(body.get("capture", True))
        screenshot_data: dict[str, Any] | None = None
        if capture:
            screenshot_data = screenshot({})

        if output is None:
            return {
                "ok": True,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-output-adapter",
                "lease": _public_lease(),
                "schema": {
                    "actions": [
                        {"action": "click", "x": 100, "y": 200, "button": "left"},
                        {"action": "type", "text": "hello"},
                        {"action": "key", "keys": ["enter"]},
                    ]
                },
                "limitations": [
                    "No vision model output was provided.",
                    "Paste a JSON action from any vision model to validate and queue it.",
                ],
            }

        payload = _extract_json_payload(output if isinstance(output, str) else json.dumps(output))
        actions = _actions_from_payload(payload)
        suggestions = []
        for idx, action in enumerate(actions, start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"vision-{idx}",
                "title": f"Vision {idx}: {action['action']}",
                "rationale": "Validated action parsed from vision model output.",
                **preview,
            })
        _record_activity(
            "grounded_actions_created",
            detail={"goal": goal, "suggestion_count": len(suggestions)},
        )

        return {
            "ok": True,
            "goal": goal,
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "vision-output-adapter",
            "lease": _public_lease(),
            "limitations": [
                "This endpoint validates vision output but does not execute automatically.",
                "Every parsed action still requires explicit user confirmation.",
            ],
        }

    @router.post("/actions/vision")
    def vision_actions(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        owner = _lease_from_body(body)
        goal = str(body.get("goal") or "")
        model_id = str(body.get("model_id") or "")
        config = _vision_model_config(model_id)
        screenshot_data = screenshot({})
        if not screenshot_data.get("ok"):
            return {
                "ok": False,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-model",
                "lease": _public_lease(),
                "error": screenshot_data.get("error") or "screenshot failed",
            }
        if not config:
            return {
                "ok": False,
                "goal": goal,
                "screenshot": screenshot_data,
                "suggestions": [],
                "mode": "vision-model",
                "lease": _public_lease(),
                "error": (
                    "vision model not configured · pass model_id for a custom openai-compatible "
                    "model or set OCTOPUS_COMPUTER_VISION_* env vars"
                ),
            }
        data_url = str(screenshot_data.get("data_url") or "")
        output = _call_openai_vision(config=config, goal=goal, data_url=data_url)
        payload = _extract_json_payload(output)
        actions = _actions_from_payload(payload)
        suggestions = []
        for idx, action in enumerate(actions, start=1):
            preview = _queue_preview(action, owner)
            suggestions.append({
                "id": f"vision-model-{idx}",
                "title": f"Vision model {idx}: {action['action']}",
                "rationale": "Grounded action returned by the configured vision model.",
                **preview,
            })
        _record_activity(
            "vision_actions_created",
            detail={
                "goal": goal,
                "model_id": str(config.get("id") or model_id),
                "suggestion_count": len(suggestions),
            },
        )
        return {
            "ok": True,
            "goal": goal,
            "model_id": str(config.get("id") or model_id),
            "screenshot": screenshot_data,
            "suggestions": suggestions,
            "mode": "vision-model",
            "lease": _public_lease(),
            "raw_output": output,
            "limitations": [
                "The screenshot is sent to the configured vision model provider.",
                "Returned actions are validated and require explicit user confirmation.",
            ],
        }

    @router.post("/actions/execute")
    def execute_action(body: dict[str, Any]) -> dict[str, Any]:
        _cleanup_pending()
        token = str(body.get("token") or "")
        item = pending.pop(token, None)
        if not item:
            diagnostic = _computer_diagnostic(
                "preview_token_missing",
                severity="error",
                message="Preview token was not found or has expired.",
                recommended_action="create_new_preview",
                metadata={"token_present": bool(token)},
            )
            _record_activity(
                "execute_rejected",
                ok=False,
                token=token,
                error="preview token not found or expired",
                detail={"diagnostic": diagnostic},
            )
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "preview token not found or expired",
                    "diagnostic": diagnostic,
                    "recommended_actions": ["create_new_preview"],
                    "replay_evidence": _computer_replay_evidence(),
                },
            )
        body_owner = _lease_from_body(body)
        item_owner = item.get("lease_owner")
        if isinstance(item_owner, dict):
            owner = {
                "owner_id": str(item_owner.get("owner_id") or body_owner["owner_id"]),
                "owner_label": str(item_owner.get("owner_label") or body_owner["owner_label"]),
            }
            if body.get("lease_owner_id") and body_owner["owner_id"] != owner["owner_id"]:
                diagnostic = _computer_diagnostic(
                    "preview_owner_mismatch",
                    severity="error",
                    message="Preview token belongs to another operator.",
                    recommended_action="create_new_preview",
                    metadata={
                        "preview_owner_id": owner.get("owner_id"),
                        "requested_owner_id": body_owner.get("owner_id"),
                    },
                )
                _record_activity(
                    "execute_rejected",
                    ok=False,
                    action=item.get("action") if isinstance(item.get("action"), dict) else {},
                    token=token,
                    risk=item.get("risk") if isinstance(item.get("risk"), dict) else {},
                    error="preview token belongs to another operator",
                    detail={
                        "lease_owner": owner,
                        "requested_owner": body_owner,
                        "diagnostic": diagnostic,
                    },
                )
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "preview token belongs to another operator",
                        "lease_owner": owner,
                        "diagnostic": diagnostic,
                        "recommended_actions": ["create_new_preview"],
                        "replay_evidence": _computer_replay_evidence(),
                    },
                )
        else:
            owner = body_owner
        lease_state = _claim_lease(owner)
        action = item["action"]
        result = _execute(action)
        ok = "error" not in result
        diagnostic = _execution_failure_diagnostic(action, result) if not ok else None
        preview_contract = (
            item.get("preview_contract")
            if isinstance(item.get("preview_contract"), dict)
            else _preview_contract(
                action,
                owner,
                item.get("risk") if isinstance(item.get("risk"), dict) else {},
            )
        )
        execution_proof = _execution_proof(
            contract=preview_contract,
            action=action,
            risk=item["risk"],
            lease_state=lease_state,
            result=result,
            ok=ok,
        )
        _record_activity(
            "action_executed",
            ok=ok,
            action=action,
            token=token,
            risk=item["risk"],
            lease_state=lease_state,
            error=str(result.get("error") or ""),
            detail={
                "result": result,
                "preview_contract_id": preview_contract.get("contract_id"),
                "execution_proof_id": execution_proof.get("proof_id"),
                **({"diagnostic": diagnostic} if diagnostic else {}),
            },
            proof={
                "preview_contract": preview_contract,
                "execution_proof": execution_proof,
            },
        )
        replay_assertion = (
            action.get("replay_assertion")
            if isinstance(action.get("replay_assertion"), dict)
            else {}
        )
        assertion_queue = None
        if replay_assertion.get("ok") is False:
            assertion_queue = _queue_uia_replay_assertion(action, replay_assertion)
        return {
            "ok": ok,
            "action": action,
            "risk": item["risk"],
            "result": result,
            "preview_contract": preview_contract,
            "execution_proof": execution_proof,
            "lease": lease_state,
            "executed_at": time.time(),
            **({"replay_assertion_queue": assertion_queue} if assertion_queue else {}),
            **({"diagnostic": diagnostic} if diagnostic else {}),
            **({"recommended_actions": [diagnostic["recommended_action"]]} if diagnostic else {}),
            **({"replay_evidence": _computer_replay_evidence()} if not ok else {}),
        }

    @router.post("/lease/release")
    def release_lease(body: dict[str, Any] | None = None) -> dict[str, Any]:
        owner = _lease_from_body(body)
        force = bool((body or {}).get("force", False))
        lease_state = _release_lease(owner, force=force)
        _record_activity(
            "lease_released",
            lease_state=lease_state,
            detail={"owner": owner, "force": force},
        )
        return {
            "ok": True,
            "lease": lease_state,
        }

    return router
