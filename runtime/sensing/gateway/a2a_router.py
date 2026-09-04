"""A2A (Agent-to-Agent) remote agent registry + relay router.

Connects the frontend ``a2a-agents-panel`` (registered remote agents) to the
A2A protocol via the official ``a2a-sdk``. The UI was authored earlier but its
backend endpoints never existed; this router completes that surface:

  GET    /api/a2a/agents                 list registered remote agents
  POST   /api/a2a/agents/register        register by URL (resolve agent card)
  DELETE /api/a2a/agents/{id}            unregister
  POST   /api/a2a/agents/{id}/health     probe the remote agent card
  POST   /api/a2a/agents/{id}/send       send a task message
  GET    /api/a2a/tasks                  list durable remote tasks
  GET    /api/a2a/tasks/{id}             inspect a task after reconnect
  GET    /api/a2a/tasks/{id}/events      inspect its ordered event history
  POST   /api/a2a/tasks/{id}/refresh     reconcile remote state
  POST   /api/a2a/tasks/{id}/cancel      cancel a running remote task
  GET    /api/a2a/tasks/{id}/subscribe   relay remote lifecycle updates as SSE

Registry entries persist to ``~/.octopus/a2a/registry.json`` (atomic writes).
Task snapshots and events persist to ``~/.octopus/a2a/tasks.db``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from runtime.memory.a2a_task_store import A2ATaskStore, canonical_a2a_state

_log = logging.getLogger(__name__)

_REGISTRY_DIR = Path.home() / ".octopus" / "a2a"
_REGISTRY_FILE = _REGISTRY_DIR / "registry.json"
_lock = threading.RLock()
_LOCAL_TASK_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


# ── Registry persistence ─────────────────────────────────────────


def _load_registry() -> dict[str, Any]:
    if not _REGISTRY_FILE.exists():
        return {"agents": []}
    try:
        data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        return (
            data
            if isinstance(data, dict) and isinstance(data.get("agents"), list)
            else {"agents": []}
        )
    except (OSError, json.JSONDecodeError):
        return {"agents": []}


def _save_registry(agents: list[dict[str, Any]]) -> None:
    from runtime.platform.io import atomic_write_json

    _REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_json(_REGISTRY_FILE, {"agents": agents})


def _find_agent(agents: list[dict[str, Any]], agent_id: str) -> dict[str, Any] | None:
    for entry in agents:
        if entry.get("agent_id") == agent_id:
            return entry
    return None


# ── A2A SDK helpers (lazy import — SDK is optional at runtime) ───


async def _resolve_agent_card(url: str) -> dict[str, Any]:
    """Fetch a remote agent's A2A card and normalize it for our wire shape."""
    try:
        from a2a.client import ClientFactory
    except ImportError as exc:  # pragma: no cover
        raise HTTPException(500, "a2a-sdk not installed") from exc

    factory = ClientFactory()
    try:
        client = await factory.create_from_url(url)
    except Exception as exc:  # noqa: BLE001 — surface as a clean 502
        _log.warning("A2A card resolution failed for %s: %s", url, exc)
        raise HTTPException(502, f"failed to resolve agent card: {exc}") from exc

    card = getattr(client, "agent_card", None) or getattr(client, "card", None)
    if card is None:
        raise HTTPException(502, f"no agent card resolved from {url}")

    def _field(obj: Any, name: str, default: Any = None) -> Any:
        if obj is None:
            return default
        # protobuf message: getattr works with default None; pydantic: model_dump path.
        try:
            value = getattr(obj, name, None)
        except (AttributeError, ValueError):
            value = None
        if value is None and hasattr(obj, "model_dump"):
            value = obj.model_dump().get(name)
        return value if value is not None else default

    skills: list[dict[str, Any]] = []
    for skill in _field(card, "skills", []) or []:
        skills.append(
            {
                "id": _field(skill, "id", "") or _field(skill, "name", ""),
                "name": _field(skill, "name", "") or _field(skill, "id", ""),
                "description": _field(skill, "description", ""),
                "tags": list(_field(skill, "tags", []) or []),
            }
        )
    capabilities = _field(card, "capabilities", None)
    return {
        "name": _field(card, "name", ""),
        "description": _field(card, "description", ""),
        "version": _field(card, "version", "1.0.0"),
        "skills": skills,
        "capabilities": {
            "streaming": bool(_field(capabilities, "streaming", False)) if capabilities else False,
            # A2A protobuf uses snake_case (push_notifications); the frontend
            # wire shape uses camelCase (pushNotifications).
            "pushNotifications": (
                bool(
                    _field(capabilities, "push_notifications", False)
                    or _field(capabilities, "pushNotifications", False)
                )
                if capabilities
                else False
            ),
            # multiTurn was dropped from the modern AgentCard; keep the field
            # for the frontend contract, defaulting False.
            "multiTurn": (
                bool(_field(capabilities, "multiTurn", False)) if capabilities else False
            ),
        },
    }


async def _probe_agent(url: str) -> dict[str, Any]:
    """Health probe: try resolving the card; success ⇒ healthy."""
    try:
        await _resolve_agent_card(url)
        return {"healthy": True, "status": "active", "error": None}
    except HTTPException as exc:
        return {"healthy": False, "status": "unreachable", "error": str(exc.detail)}


def _protobuf_dict(value: Any) -> dict[str, Any]:
    """Convert an SDK protobuf or plain mapping without relying on unsafe field access."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    if hasattr(value, "DESCRIPTOR"):
        from google.protobuf.json_format import MessageToDict

        converted = MessageToDict(value, preserving_proto_field_name=True)
        return converted if isinstance(converted, dict) else {}
    if hasattr(value, "model_dump"):
        converted = value.model_dump(mode="json")
        return converted if isinstance(converted, dict) else {}
    return {}


def _plain_task_dict(value: Any) -> dict[str, Any]:
    """Find the Task payload in a Task, StreamResponse, or lightweight SDK double."""
    converted = _protobuf_dict(value)
    if converted:
        nested = converted.get("task") or converted.get("result")
        if isinstance(nested, dict):
            return nested
        if "id" in converted and ("status" in converted or "history" in converted):
            return converted

    task_obj = getattr(value, "task", None) or getattr(value, "result", None)
    converted_task = _protobuf_dict(task_obj)
    if converted_task:
        return converted_task
    if task_obj is None:
        task_obj = value

    status_obj = getattr(task_obj, "status", None)
    history = []
    for message in getattr(task_obj, "history", None) or []:
        history.append(
            {
                "role": str(getattr(message, "role", "")),
                "parts": [
                    {"text": str(getattr(part, "text", ""))}
                    for part in (getattr(message, "parts", None) or [])
                    if getattr(part, "text", None) is not None
                ],
            }
        )
    artifacts = []
    for artifact in getattr(task_obj, "artifacts", None) or []:
        artifacts.append(
            {
                "name": str(getattr(artifact, "name", "") or ""),
                "parts": [
                    {"text": str(getattr(part, "text", ""))}
                    for part in (getattr(artifact, "parts", None) or [])
                    if getattr(part, "text", None) is not None
                ],
            }
        )
    return {
        "id": getattr(task_obj, "id", None),
        "context_id": getattr(task_obj, "context_id", None),
        "status": {
            "state": getattr(status_obj, "state", None),
            "message": getattr(status_obj, "message", None),
        },
        "history": history,
        "artifacts": artifacts,
    }


def _task_result(value: Any) -> dict[str, Any]:
    """Normalize a remote A2A task into the stable frontend wire shape."""
    task = _plain_task_dict(value)
    status_value = task.get("status")
    status: dict[str, Any] = status_value if isinstance(status_value, dict) else {}
    raw_state = str(status.get("state", "") or "")
    state_numbers = {
        "unknown": "0",
        "submitted": "1",
        "working": "2",
        "completed": "3",
        "failed": "4",
        "canceled": "5",
        "input_required": "6",
        "rejected": "7",
        "auth_required": "8",
    }
    wire_state = (
        raw_state
        if not raw_state or raw_state.isdigit()
        else state_numbers.get(canonical_a2a_state(raw_state), raw_state)
    )
    messages: list[dict[str, Any]] = []
    for message in task.get("history", []) or []:
        if not isinstance(message, dict):
            continue
        parts = [
            {"type": "text", "text": str(part.get("text", ""))}
            for part in message.get("parts", []) or []
            if isinstance(part, dict) and part.get("text") is not None
        ]
        messages.append({"role": str(message.get("role", "")), "parts": parts})
    artifacts: list[dict[str, Any]] = []
    for artifact in task.get("artifacts", []) or []:
        if not isinstance(artifact, dict):
            continue
        parts = [
            {"type": "text", "text": str(part.get("text", ""))}
            for part in artifact.get("parts", []) or []
            if isinstance(part, dict) and part.get("text") is not None
        ]
        artifacts.append({"name": str(artifact.get("name", "") or ""), "parts": parts})
    return {
        "id": str(task.get("id") or ""),
        "context_id": str(task.get("context_id") or ""),
        "status": {
            "state": wire_state,
            "message": str(status.get("message", "") or ""),
        },
        "messages": messages,
        "artifacts": artifacts,
    }


def _stream_snapshot(value: Any) -> tuple[dict[str, Any], str, str]:
    """Return normalized task result, canonical state, and event kind."""
    payload = _protobuf_dict(value)
    if payload.get("task") is not None or getattr(value, "task", None) is not None:
        result = _task_result(value)
        return result, canonical_a2a_state(result["status"]["state"]), "remote_task"

    update = payload.get("status_update")
    if isinstance(update, dict):
        status_value = update.get("status")
        status: dict[str, Any] = status_value if isinstance(status_value, dict) else {}
        result = {
            "id": str(update.get("task_id") or ""),
            "context_id": str(update.get("context_id") or ""),
            "status": {
                "state": str(status.get("state", "") or ""),
                "message": str(status.get("message", "") or ""),
            },
            "messages": [],
            "artifacts": [],
        }
        return result, canonical_a2a_state(result["status"]["state"]), "remote_status"

    event_kind = "remote_message" if payload.get("message") is not None else "remote_artifact"
    return {}, "working", event_kind


# ── Router ───────────────────────────────────────────────────────


def create_a2a_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    def _auth_dep(request: Request) -> None:
        if require_auth and identity_store is None:
            raise HTTPException(401, "identity store required for a2a auth")
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
        prefix="/api/a2a",
        tags=["a2a"],
        dependencies=[Depends(_auth_dep)],
    )
    task_store = A2ATaskStore(_REGISTRY_DIR)

    def _registered_agent(agent_id: str) -> dict[str, Any]:
        with _lock:
            registry = _load_registry()
            entry = _find_agent(registry["agents"], agent_id)
        if entry is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        return entry

    async def _client_for(entry: dict[str, Any]) -> Any:
        try:
            from a2a.client import ClientFactory
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(500, "a2a-sdk not installed") from exc
        try:
            return await ClientFactory().create_from_url(str(entry["base_url"]))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"failed to connect to remote agent: {exc}") from exc

    def _stored_task(local_task_id: str) -> dict[str, Any]:
        task = task_store.get(local_task_id)
        if task is None:
            raise HTTPException(404, f"A2A task not found: {local_task_id}")
        return task

    def _update_from_remote(
        local_task_id: str,
        result: dict[str, Any],
        *,
        event_type: str,
    ) -> dict[str, Any]:
        current = _stored_task(local_task_id)
        state = canonical_a2a_state(result.get("status", {}).get("state"))
        if current["terminal_at"]:
            state = str(current["status"])
        try:
            return task_store.update(
                local_task_id,
                status=state,
                remote_task_id=str(result.get("id") or ""),
                context_id=str(result.get("context_id") or ""),
                result=result,
                event_type=event_type,
                event_payload={"remote": result},
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/agents")
    def list_agents() -> dict[str, Any]:
        with _lock:
            registry = _load_registry()
        return {"agents": registry["agents"], "count": len(registry["agents"])}

    @router.post("/agents/register")
    async def register_agent(body: dict[str, Any]) -> dict[str, Any]:
        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(400, "url is required")
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "url must be http(s)")

        card = await _resolve_agent_card(url)
        now = datetime.now(UTC).isoformat()
        with _lock:
            registry = _load_registry()
            # Re-registering the same URL refreshes in place.
            existing = next(
                (e for e in registry["agents"] if e.get("base_url") == url),
                None,
            )
            if existing:
                existing.update(
                    {
                        **card,
                        "status": "active",
                        "updated_at": now,
                        "last_health_check": now,
                    }
                )
                entry = existing
            else:
                entry = {
                    "agent_id": f"a2a_{uuid.uuid4().hex[:12]}",
                    "base_url": url,
                    "status": "active",
                    "registered_at": now,
                    "updated_at": now,
                    "last_health_check": now,
                    **card,
                }
                registry["agents"].append(entry)
            _save_registry(registry["agents"])
        return entry

    @router.delete("/agents/{agent_id}")
    def unregister_agent(agent_id: str) -> dict[str, Any]:
        with _lock:
            registry = _load_registry()
            before = len(registry["agents"])
            registry["agents"] = [e for e in registry["agents"] if e.get("agent_id") != agent_id]
            if len(registry["agents"]) == before:
                raise HTTPException(404, f"agent not found: {agent_id}")
            _save_registry(registry["agents"])
        return {"ok": True, "agent_id": agent_id}

    @router.post("/agents/{agent_id}/health")
    async def health_check(agent_id: str) -> dict[str, Any]:
        with _lock:
            registry = _load_registry()
            entry = _find_agent(registry["agents"], agent_id)
        if entry is None:
            raise HTTPException(404, f"agent not found: {agent_id}")
        result = await _probe_agent(str(entry["base_url"]))
        now = datetime.now(UTC).isoformat()
        with _lock:
            registry = _load_registry()
            current = _find_agent(registry["agents"], agent_id)
            if current is not None:
                current["status"] = "active" if result["healthy"] else "unreachable"
                current["last_health_check"] = now
                current["updated_at"] = now
                _save_registry(registry["agents"])
        return {"healthy": result["healthy"], "status": result["status"], "error": result["error"]}

    @router.post("/agents/{agent_id}/send")
    async def send_task(agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(400, "text is required")
        entry = _registered_agent(agent_id)
        local_task_id = str(body.get("local_task_id") or f"a2at_{uuid.uuid4().hex}").strip()
        if not _LOCAL_TASK_ID_RE.fullmatch(local_task_id):
            raise HTTPException(400, "local_task_id contains unsupported characters")
        context_id = str(body.get("context_id") or "").strip()
        request_payload = {"text": text, "context_id": context_id}
        try:
            existing, created = task_store.create_once(
                local_task_id=local_task_id,
                agent_id=agent_id,
                request=request_payload,
                context_id=context_id,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not created:
            if existing["agent_id"] != agent_id or existing["request"] != request_payload:
                raise HTTPException(409, "local_task_id already belongs to a different A2A task")
            if isinstance(existing["result"], dict) and existing["terminal_at"]:
                return {
                    **existing["result"],
                    "local_task_id": local_task_id,
                    "lifecycle_status": existing["status"],
                    "replayed": True,
                }
            raise HTTPException(409, "A2A task is already in progress")

        try:
            from a2a.types import Message, Part, Role, SendMessageRequest
        except ImportError as exc:  # pragma: no cover
            task_store.update(
                local_task_id,
                status="failed",
                error="a2a-sdk not installed",
                event_type="local_error",
                event_payload={"error": "a2a-sdk not installed"},
            )
            raise HTTPException(500, "a2a-sdk not installed") from exc

        last_result: dict[str, Any] = {}
        response_count = 0
        try:
            client = await _client_for(entry)
            message = Message(
                message_id=str(uuid.uuid4()),
                role=Role.ROLE_USER,
                parts=[Part(text=text)],
            )
            if context_id:
                message.context_id = context_id
            request = SendMessageRequest(message=message)
            async for response in client.send_message(request):
                response_count += 1
                result, state, event_type = _stream_snapshot(response)
                if result:
                    if last_result:
                        result["id"] = result.get("id") or last_result.get("id", "")
                        result["context_id"] = result.get("context_id") or last_result.get(
                            "context_id", ""
                        )
                        result["messages"] = result.get("messages") or last_result.get(
                            "messages", []
                        )
                        result["artifacts"] = result.get("artifacts") or last_result.get(
                            "artifacts", []
                        )
                    last_result = result
                else:
                    result = last_result or {
                        "id": "",
                        "context_id": context_id,
                        "status": {"state": state, "message": ""},
                        "messages": [],
                        "artifacts": [],
                    }
                current = _stored_task(local_task_id)
                effective_state = current["status"] if current["terminal_at"] else state
                task_store.update(
                    local_task_id,
                    status=effective_state,
                    remote_task_id=str(result.get("id") or ""),
                    context_id=str(result.get("context_id") or ""),
                    result=result,
                    event_type=event_type,
                    event_payload={"remote": _protobuf_dict(response) or result},
                )
        except HTTPException as exc:
            current = _stored_task(local_task_id)
            failure_state = current["status"] if current["terminal_at"] else "failed"
            task_store.update(
                local_task_id,
                status=failure_state,
                result=last_result or None,
                error=str(exc.detail),
                event_type="remote_error",
                event_payload={"error": str(exc.detail)[:4000]},
            )
            raise
        except Exception as exc:  # noqa: BLE001 — surface remote failure cleanly
            current = _stored_task(local_task_id)
            failure_state = current["status"] if current["terminal_at"] else "failed"
            task_store.update(
                local_task_id,
                status=failure_state,
                result=last_result or None,
                error=str(exc),
                event_type="remote_error",
                event_payload={"error": str(exc)[:4000]},
            )
            _log.warning("A2A send_task to %s failed: %s", entry["base_url"], exc)
            raise HTTPException(502, f"remote agent call failed: {exc}") from exc

        if response_count == 0:
            task_store.update(
                local_task_id,
                status="failed",
                error="remote agent returned no response",
                event_type="remote_error",
                event_payload={"error": "remote agent returned no response"},
            )
            raise HTTPException(502, "remote agent returned no response")

        stored = _stored_task(local_task_id)
        return {
            **last_result,
            "id": str(last_result.get("id") or local_task_id),
            "local_task_id": local_task_id,
            "lifecycle_status": stored["status"],
        }

    @router.get("/tasks")
    def list_tasks(agent_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
        try:
            tasks = task_store.list(agent_id=agent_id, status=status, limit=limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"tasks": tasks, "count": len(tasks)}

    @router.get("/tasks/{local_task_id}")
    def get_task(local_task_id: str) -> dict[str, Any]:
        return _stored_task(local_task_id)

    @router.get("/tasks/{local_task_id}/events")
    def get_task_events(local_task_id: str, after_seq: int = 0) -> dict[str, Any]:
        _stored_task(local_task_id)
        events = task_store.events(local_task_id, after_seq=after_seq)
        return {"events": events, "count": len(events)}

    @router.post("/tasks/{local_task_id}/refresh")
    async def refresh_task(local_task_id: str) -> dict[str, Any]:
        task = _stored_task(local_task_id)
        if not task["remote_task_id"]:
            raise HTTPException(409, "remote task id is not available")
        entry = _registered_agent(str(task["agent_id"]))
        try:
            from a2a.types import GetTaskRequest

            client = await _client_for(entry)
            remote_task = await client.get_task(GetTaskRequest(id=task["remote_task_id"]))
        except HTTPException as exc:
            task_store.update(
                local_task_id,
                status=task["status"],
                error=str(exc.detail),
                event_type="refresh_failed",
                event_payload={"error": str(exc.detail)[:4000]},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            task_store.update(
                local_task_id,
                status=task["status"],
                error=str(exc),
                event_type="refresh_failed",
                event_payload={"error": str(exc)[:4000]},
            )
            raise HTTPException(502, f"remote task refresh failed: {exc}") from exc
        return _update_from_remote(local_task_id, _task_result(remote_task), event_type="refreshed")

    @router.post("/tasks/{local_task_id}/cancel")
    async def cancel_task(local_task_id: str) -> dict[str, Any]:
        task = _stored_task(local_task_id)
        if task["terminal_at"]:
            return task
        if not task["remote_task_id"]:
            raise HTTPException(409, "remote task id is not available")
        entry = _registered_agent(str(task["agent_id"]))
        try:
            from a2a.types import CancelTaskRequest

            client = await _client_for(entry)
            remote_task = await client.cancel_task(CancelTaskRequest(id=task["remote_task_id"]))
        except HTTPException as exc:
            task_store.update(
                local_task_id,
                status=task["status"],
                error=str(exc.detail),
                event_type="cancel_failed",
                event_payload={"error": str(exc.detail)[:4000]},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            task_store.update(
                local_task_id,
                status=task["status"],
                error=str(exc),
                event_type="cancel_failed",
                event_payload={"error": str(exc)[:4000]},
            )
            raise HTTPException(502, f"remote task cancellation failed: {exc}") from exc
        return _update_from_remote(local_task_id, _task_result(remote_task), event_type="canceled")

    @router.get("/tasks/{local_task_id}/subscribe")
    async def subscribe_task(local_task_id: str) -> StreamingResponse:
        task = _stored_task(local_task_id)
        if not task["remote_task_id"]:
            raise HTTPException(409, "remote task id is not available")
        entry = _registered_agent(str(task["agent_id"]))
        try:
            from a2a.types import SubscribeToTaskRequest

            client = await _client_for(entry)
            request = SubscribeToTaskRequest(id=task["remote_task_id"])
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"remote task subscription failed: {exc}") from exc

        async def _events():
            yield f"event: snapshot\ndata: {json.dumps(task, ensure_ascii=False)}\n\n"
            try:
                async for response in client.subscribe(request):
                    result, state, event_type = _stream_snapshot(response)
                    if result:
                        stored = _update_from_remote(
                            local_task_id,
                            result,
                            event_type=f"subscription_{event_type}",
                        )
                    else:
                        current = _stored_task(local_task_id)
                        effective_state = current["status"] if current["terminal_at"] else state
                        stored = task_store.update(
                            local_task_id,
                            status=effective_state,
                            result=current["result"],
                            event_type=f"subscription_{event_type}",
                            event_payload={"remote": _protobuf_dict(response)},
                        )
                    yield f"event: update\ndata: {json.dumps(stored, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                current = _stored_task(local_task_id)
                stored = task_store.update(
                    local_task_id,
                    status=current["status"],
                    result=current["result"],
                    error=str(exc),
                    event_type="subscription_failed",
                    event_payload={"error": str(exc)[:4000]},
                )
                yield (
                    "event: error\ndata: "
                    f"{json.dumps({'task': stored, 'error': str(exc)}, ensure_ascii=False)}\n\n"
                )

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


__all__ = ["create_a2a_router"]
