"""Unified collaboration-session storage.

This is the bottom-store step after the read-model bridge: a collaboration
thread owns its persistent room surface and heavyweight tasks directly. Legacy
``team_rooms`` / ``team_tasks`` stores can still be maintained as compatibility
projections, but the canonical session path no longer has to discover its room
and task state from separate JSON files.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runtime.memory.cowork.ids import (
    normalize_display_name,
    normalize_search_query,
    optional_cowork_id,
    require_cowork_id,
    require_message_text,
)

_MAX_JSON_BYTES = 512 * 1024
_MAX_LIST_ITEMS = 512
_TASK_KINDS = frozenset({"async", "team", "project"})
_TASK_STATUSES = frozenset(
    {
        "pending",
        "ready",
        "running",
        "blocked",
        "done",
        "failed",
        "cancelled",
        "rejected",
    }
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_rooms (
    session_id TEXT PRIMARY KEY,
    room_id    TEXT NOT NULL UNIQUE,
    room_json  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_rooms_room ON collaboration_rooms(room_id);

CREATE TABLE IF NOT EXISTS collaboration_tasks (
    task_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    room_id    TEXT NOT NULL,
    status     TEXT NOT NULL,
    task_json  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_tasks_session ON collaboration_tasks(session_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_collab_tasks_room ON collaboration_tasks(room_id, updated_at);

CREATE TABLE IF NOT EXISTS collaboration_messages (
    session_id     TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    room_id        TEXT NOT NULL,
    participant_id TEXT,
    display_name   TEXT,
    text           TEXT NOT NULL,
    ts             TEXT NOT NULL,
    metadata_json  TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_collab_messages_session ON collaboration_messages(session_id, seq);
CREATE INDEX IF NOT EXISTS idx_collab_messages_room ON collaboration_messages(room_id, seq);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "cowork"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_json_dict(data: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    try:
        blob = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: not JSON serializable") from exc
    if len(blob.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError(f"invalid {label}: JSON payload exceeds {_MAX_JSON_BYTES} bytes")
    normalized = json.loads(blob)
    return normalized if isinstance(normalized, dict) else {}


def _dump(data: dict[str, Any], *, label: str = "payload") -> str:
    return json.dumps(_normalize_json_dict(data, label=label), ensure_ascii=False)


def _load(text: str) -> dict[str, Any] | None:
    if len(str(text).encode("utf-8")) > _MAX_JSON_BYTES:
        return None
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _compact_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for item in value[:_MAX_LIST_ITEMS]:
        if isinstance(item, dict):
            out.append(_normalize_json_dict(item, label="list item"))
    return out


def _normalize_entity_refs(value: Any) -> list[dict[str, Any]]:
    """Normalize structured links carried by a room message.

    Entity references intentionally stay small and generic: the frontend can
    open a project, milestone, task, artifact, or decision without the
    collaboration store becoming another source of truth for those entities.
    """

    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value[:_MAX_LIST_ITEMS]:
        if not isinstance(item, dict):
            continue
        ref = _normalize_json_dict(item, label="message entity reference")
        kind = optional_cowork_id(ref.get("kind"), label="entity kind").lower()
        entity_id = optional_cowork_id(ref.get("id"), label="entity id")
        if not kind or not entity_id or (kind, entity_id) in seen:
            continue
        ref["kind"] = kind
        ref["id"] = entity_id
        for key in ("project_id", "milestone_id", "task_id"):
            if key in ref:
                ref[key] = optional_cowork_id(ref.get(key), label=key)
        if "label" in ref:
            ref["label"] = normalize_display_name(ref.get("label"), label="entity label")
        seen.add((kind, entity_id))
        out.append(ref)
    return out


def _normalize_message_metadata(value: Any) -> dict[str, Any]:
    """Validate optional, backwards-compatible room-message metadata.

    The stable envelope is ``octopus.room_message.metadata.v1``.  Plain legacy
    messages continue to store/return ``{}``; structured messages may include a
    client/source id, entity references, and a renderable system-card payload.
    Unknown JSON-safe keys are preserved so channel adapters can attach their
    own non-authoritative context.
    """

    metadata = _normalize_json_dict(value, label="message metadata")
    if not metadata:
        return {}
    if "source_message_id" in metadata:
        metadata["source_message_id"] = optional_cowork_id(
            metadata.get("source_message_id"),
            label="source_message_id",
        )
    if "entity_refs" in metadata:
        metadata["entity_refs"] = _normalize_entity_refs(metadata.get("entity_refs"))
    if "system_card" in metadata:
        metadata["system_card"] = _normalize_json_dict(
            metadata.get("system_card"),
            label="system card",
        )
    message_type = str(metadata.get("message_type") or "").strip().lower()
    if metadata.get("system_card"):
        message_type = "system_card"
    if message_type:
        metadata["message_type"] = (
            message_type if message_type in {"message", "system_card"} else "message"
        )
    if "project_actions" in metadata:
        metadata["project_actions"] = _compact_dict_list(metadata.get("project_actions"))
    metadata["schema"] = "octopus.room_message.metadata.v1"
    return metadata


def _merge_message_metadata(current: Any, patch: Any) -> dict[str, Any]:
    """Merge a metadata patch while de-duplicating references/actions."""

    before = _normalize_message_metadata(current)
    incoming = _normalize_message_metadata(patch)
    merged = {**before, **incoming}
    if "entity_refs" in before or "entity_refs" in incoming:
        merged["entity_refs"] = _normalize_entity_refs(
            [*(before.get("entity_refs") or []), *(incoming.get("entity_refs") or [])]
        )
    if "project_actions" in before or "project_actions" in incoming:
        actions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in [
            *(before.get("project_actions") or []),
            *(incoming.get("project_actions") or []),
        ]:
            if not isinstance(item, dict):
                continue
            action_id = str(item.get("id") or "").strip()
            if action_id and action_id in seen:
                continue
            if action_id:
                seen.add(action_id)
            actions.append(item)
        merged["project_actions"] = _compact_dict_list(actions)
    return _normalize_message_metadata(merged)


def _message_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    metadata = _load(str(row[7] or "{}")) or {}
    try:
        metadata = _normalize_message_metadata(metadata)
    except ValueError:
        # A corrupt optional envelope must not hide otherwise valid transcript
        # text during reconnect/catch-up.
        metadata = {}
    return {
        "session_id": row[0] or "",
        "seq": int(row[1]),
        "room_id": row[2] or "",
        "participant_id": row[3] or "",
        "display_name": row[4] or "",
        "text": row[5],
        "ts": row[6],
        "metadata": metadata,
    }


def _normalize_room_payload(payload: dict[str, Any], *, room_id: str) -> dict[str, Any]:
    payload = _normalize_json_dict(payload, label="room")
    payload["id"] = room_id
    if "name" in payload:
        payload["name"] = normalize_display_name(payload.get("name"), label="room name")
    if "members" in payload:
        payload["members"] = _compact_dict_list(payload.get("members"))
    if "participants" in payload:
        payload["participants"] = _compact_dict_list(payload.get("participants"))
    return payload


def _merge_room_payload(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
    *,
    room_id: str,
) -> dict[str, Any]:
    """Merge independent room projections without erasing richer state.

    Team Room owns participants/members while Project OS contributes project
    metadata.  Both project into this read model, so a sparse Project OS
    update must not make already-joined humans disappear.  Explicit incoming
    fields still win (including an intentionally empty participant list).
    """

    if not existing:
        return _normalize_room_payload(incoming, room_id=room_id)
    merged = {**existing, **incoming}
    existing_metadata = existing.get("metadata")
    incoming_metadata = incoming.get("metadata")
    if isinstance(existing_metadata, dict) or isinstance(incoming_metadata, dict):
        merged["metadata"] = {
            **(existing_metadata if isinstance(existing_metadata, dict) else {}),
            **(incoming_metadata if isinstance(incoming_metadata, dict) else {}),
        }
    return _normalize_room_payload(merged, room_id=room_id)


def _normalize_task_payload(
    payload: dict[str, Any],
    *,
    task_id: str,
    room_id: str,
    session_id: str,
) -> dict[str, Any]:
    payload = _normalize_json_dict(payload, label="task")
    payload["id"] = task_id
    payload["room_id"] = room_id
    kind = str(payload.get("kind") or "").strip().lower()
    if not kind:
        source = str(
            (payload.get("metadata") or {}).get("source")
            if isinstance(payload.get("metadata"), dict)
            else ""
        )
        kind = "project" if source.startswith("projectos") else "team"
    payload["kind"] = kind if kind in _TASK_KINDS else "team"
    status = str(payload.get("status") or "pending").strip().lower()
    payload["status"] = status if status in _TASK_STATUSES else "pending"
    if "title" in payload:
        payload["title"] = require_message_text(payload.get("title"), label="task title")
    if "description" in payload and str(payload.get("description") or "").strip():
        payload["description"] = require_message_text(
            payload.get("description"),
            label="task description",
        )
    elif "description" in payload:
        payload["description"] = ""
    if "assignees" in payload:
        payload["assignees"] = _compact_dict_list(payload.get("assignees"))
    if "produced_artifacts" in payload:
        payload["produced_artifacts"] = _compact_dict_list(payload.get("produced_artifacts"))
    if "artifacts" in payload:
        payload["artifacts"] = _compact_dict_list(payload.get("artifacts"))
    elif payload.get("produced_artifacts"):
        payload["artifacts"] = _compact_dict_list(payload.get("produced_artifacts"))
    if "lease" in payload:
        payload["lease"] = _normalize_json_dict(payload.get("lease"), label="task lease")
    for key in ("project_id", "milestone_id", "parent_task_id"):
        if key in payload:
            payload[key] = optional_cowork_id(payload.get(key), label=key) or ""
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    metadata = _normalize_json_dict(metadata, label="task metadata")
    metadata.setdefault("collab_session_id", session_id)
    metadata.setdefault("source", "collab_session")
    payload["metadata"] = metadata
    return payload


class CollaborationStore:
    """Canonical room/task storage keyed by collaboration session id."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "collaboration.db"
        self._lock = threading.Lock()
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def base_dir(self) -> Path:
        return self._dir

    def _connect(self) -> sqlite3.Connection:
        self._dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        # ``CREATE TABLE IF NOT EXISTS`` does not add columns to installations
        # created before structured messages existed.  Keep the migration
        # inline/idempotent because this store intentionally has no external
        # migration runner.
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(collaboration_messages)")}
        if "metadata_json" not in columns:
            conn.execute(
                "ALTER TABLE collaboration_messages "
                "ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'"
            )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_collab_messages_source "
            "ON collaboration_messages("
            "session_id, CASE WHEN json_valid(metadata_json) "
            "THEN json_extract(metadata_json, '$.source_message_id') END"
            ") WHERE CASE WHEN json_valid(metadata_json) "
            "THEN COALESCE(json_extract(metadata_json, '$.source_message_id'), '') != '' "
            "ELSE 0 END"
        )
        return conn

    def room_for_session(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT room_json FROM collaboration_rooms WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return _load(row[0]) if row else None

    def room_by_id(self, room_id: str) -> dict[str, Any] | None:
        if not room_id:
            return None
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT room_json FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return _load(row[0]) if row else None

    def session_id_for_room(self, room_id: str) -> str | None:
        if not room_id:
            return None
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        return str(row[0]) if row else None

    def upsert_room(self, session_id: str, room: dict[str, Any]) -> dict[str, Any]:
        session_id = require_cowork_id(session_id, label="session_id")
        incoming = dict(room or {})
        room_id = require_cowork_id(
            incoming.get("id") or incoming.get("room_id") or f"collab-{session_id}",
            label="room_id",
        )
        incoming = _normalize_room_payload(incoming, room_id=room_id)
        now = _now()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT room_id, room_json, created_at FROM collaboration_rooms "
                "WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            existing_payload = _load(row[1]) if row is not None and str(row[0]) == room_id else None
            existing_room = conn.execute(
                "SELECT session_id, room_json FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
            if existing_payload is None and existing_room is not None:
                existing_payload = _load(existing_room[1])
            payload = _merge_room_payload(existing_payload, incoming, room_id=room_id)
            created_at = str(row[2]) if row else str(payload.get("created_at") or now)
            payload.setdefault("created_at", created_at)
            payload["updated_at"] = str(payload.get("updated_at") or now)
            if existing_room and str(existing_room[0]) != session_id:
                conn.execute(
                    "UPDATE collaboration_tasks SET session_id = ? WHERE room_id = ?",
                    (session_id, room_id),
                )
                conn.execute(
                    "UPDATE collaboration_messages SET session_id = ? WHERE room_id = ?",
                    (session_id, room_id),
                )
                conn.execute(
                    "DELETE FROM collaboration_rooms WHERE room_id = ?",
                    (room_id,),
                )
            conn.execute(
                "INSERT INTO collaboration_rooms(session_id, room_id, room_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "room_id = excluded.room_id, room_json = excluded.room_json, updated_at = excluded.updated_at",
                (
                    session_id,
                    room_id,
                    _dump(payload, label="room"),
                    created_at,
                    payload["updated_at"],
                ),
            )
        return payload

    def upsert_room_by_id(self, room: dict[str, Any]) -> dict[str, Any] | None:
        payload = dict(room or {})
        room_id = require_cowork_id(
            payload.get("id") or payload.get("room_id") or "",
            label="room_id",
        )
        payload = _normalize_room_payload(payload, room_id=room_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            ).fetchone()
        if not row:
            return self.upsert_room(f"team:{room_id}", payload)
        return self.upsert_room(str(row[0]), payload)

    def tasks_for_session(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_json FROM collaboration_tasks WHERE session_id = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (session_id,),
            ).fetchall()
        return [item for row in rows if (item := _load(row[0])) is not None]

    def tasks_for_room(self, room_id: str) -> list[dict[str, Any]]:
        if not room_id:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_json FROM collaboration_tasks WHERE room_id = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (room_id,),
            ).fetchall()
        return [item for row in rows if (item := _load(row[0])) is not None]

    def upsert_task(self, session_id: str, task: dict[str, Any]) -> dict[str, Any]:
        session_id = require_cowork_id(session_id, label="session_id")
        payload = dict(task or {})
        task_id = require_cowork_id(
            payload.get("id") or payload.get("task_id") or "", label="task_id"
        )
        room_id = require_cowork_id(payload.get("room_id") or "", label="room_id")
        payload = _normalize_task_payload(
            payload,
            task_id=task_id,
            room_id=room_id,
            session_id=session_id,
        )
        now = _now()
        created_at = str(payload.get("created_at") or now)
        updated_at = str(payload.get("updated_at") or now)
        status = str(payload.get("status") or "pending")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO collaboration_tasks("
                "task_id, session_id, room_id, status, task_json, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(task_id) DO UPDATE SET "
                "session_id = excluded.session_id, room_id = excluded.room_id, "
                "status = excluded.status, task_json = excluded.task_json, "
                "updated_at = excluded.updated_at",
                (
                    task_id,
                    session_id,
                    room_id,
                    status,
                    _dump(payload, label="task"),
                    created_at,
                    updated_at,
                ),
            )
        return payload

    def upsert_task_for_room(self, room_id: str, task: dict[str, Any]) -> dict[str, Any] | None:
        room_id = require_cowork_id(room_id, label="room_id")
        session_id = self.session_id_for_room(room_id)
        if not session_id:
            return None
        payload = dict(task or {})
        payload.setdefault("room_id", room_id)
        return self.upsert_task(session_id, payload)

    def upsert_project_task(
        self,
        *,
        session_id: str,
        room_id: str,
        project_id: str,
        milestone_id: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(task or {})
        payload["kind"] = "project"
        payload["room_id"] = room_id
        payload["project_id"] = project_id
        payload["milestone_id"] = milestone_id
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        payload["metadata"] = {
            **metadata,
            "source": "projectos",
            "project_id": project_id,
            "milestone_id": milestone_id,
        }
        return self.upsert_task(session_id, payload)

    def project_tasks_for_project(self, project_id: str) -> list[dict[str, Any]]:
        if not project_id:
            return []
        project_id = require_cowork_id(project_id, label="project_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT task_json FROM collaboration_tasks "
                "WHERE json_extract(task_json, '$.kind') = 'project' "
                "AND json_extract(task_json, '$.project_id') = ? "
                "ORDER BY updated_at DESC, created_at DESC",
                (project_id,),
            ).fetchall()
        return [item for row in rows if (item := _load(row[0])) is not None]

    def delete_task(self, task_id: str) -> bool:
        if not task_id:
            return False
        task_id = require_cowork_id(task_id, label="task_id")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM collaboration_tasks WHERE task_id = ?",
                (task_id,),
            )
            return cur.rowcount > 0

    def delete_room_by_id(self, room_id: str) -> bool:
        if not room_id:
            return False
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            conn.execute(
                "DELETE FROM collaboration_tasks WHERE room_id = ?",
                (room_id,),
            )
            conn.execute(
                "DELETE FROM collaboration_messages WHERE room_id = ?",
                (room_id,),
            )
            cur = conn.execute(
                "DELETE FROM collaboration_rooms WHERE room_id = ?",
                (room_id,),
            )
            return cur.rowcount > 0

    def append_message(
        self,
        session_id: str,
        *,
        room_id: str,
        text: str,
        participant_id: str = "",
        display_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        session_id = require_cowork_id(session_id, label="session_id")
        room_id = require_cowork_id(room_id, label="room_id")
        participant_id = optional_cowork_id(participant_id, label="participant_id")
        display_name = normalize_display_name(display_name)
        text = require_message_text(text)
        message_metadata = _normalize_message_metadata(metadata)
        ts = _now()
        with self._lock, self._connect() as conn:
            source_message_id = str(message_metadata.get("source_message_id") or "")
            if source_message_id:
                existing = conn.execute(
                    "SELECT seq, room_id, participant_id, display_name, text "
                    "FROM collaboration_messages "
                    "WHERE session_id = ? "
                    "AND CASE WHEN json_valid(metadata_json) "
                    "THEN json_extract(metadata_json, '$.source_message_id') END = ?",
                    (session_id, source_message_id),
                ).fetchone()
                if existing:
                    if (
                        str(existing[1] or "") != room_id
                        or str(existing[2] or "") != participant_id
                        or str(existing[3] or "") != display_name
                        or str(existing[4] or "") != text
                    ):
                        raise ValueError(
                            "source_message_id already belongs to a different room message"
                        )
                    return int(existing[0])
            cur = conn.execute(
                "INSERT INTO collaboration_messages("
                "session_id, seq, room_id, participant_id, display_name, text, ts, metadata_json"
                ") VALUES (?, (SELECT COALESCE(MAX(seq), 0) + 1 FROM collaboration_messages "
                "WHERE session_id = ?), ?, ?, ?, ?, ?, ?) RETURNING seq",
                (
                    session_id,
                    session_id,
                    room_id,
                    participant_id,
                    display_name,
                    text,
                    ts,
                    _dump(message_metadata, label="message metadata"),
                ),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def append_message_for_room(
        self,
        room_id: str,
        *,
        text: str,
        participant_id: str = "",
        display_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        room_id = require_cowork_id(room_id, label="room_id")
        session_id = self.session_id_for_room(room_id)
        if not session_id:
            return None
        return self.append_message(
            session_id,
            room_id=room_id,
            text=text,
            participant_id=participant_id,
            display_name=display_name,
            metadata=metadata,
        )

    def message_for_session(self, session_id: str, seq: int) -> dict[str, Any] | None:
        if not session_id or int(seq) < 1:
            return None
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json FROM collaboration_messages WHERE session_id = ? AND seq = ?",
                (session_id, int(seq)),
            ).fetchone()
        return _message_from_row(row) if row else None

    def message_by_source_id(
        self,
        session_id: str,
        source_message_id: str,
    ) -> dict[str, Any] | None:
        if not session_id or not source_message_id:
            return None
        session_id = require_cowork_id(session_id, label="session_id")
        source_message_id = require_cowork_id(source_message_id, label="source_message_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json FROM collaboration_messages WHERE session_id = ? "
                "AND CASE WHEN json_valid(metadata_json) "
                "THEN json_extract(metadata_json, '$.source_message_id') END = ?",
                (session_id, source_message_id),
            ).fetchone()
        return _message_from_row(row) if row else None

    def update_message_metadata(
        self,
        session_id: str,
        seq: int,
        metadata: dict[str, Any],
        *,
        merge: bool = True,
    ) -> dict[str, Any] | None:
        """Attach references/action receipts to an existing message.

        Message text and attribution stay append-only; only the optional
        structured envelope can be enriched as a chat line becomes a project
        object.  ``merge=True`` preserves unrelated channel metadata.
        """

        if not session_id or int(seq) < 1:
            return None
        session_id = require_cowork_id(session_id, label="session_id")
        patch = _normalize_message_metadata(metadata)
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT metadata_json FROM collaboration_messages WHERE session_id = ? AND seq = ?",
                (session_id, int(seq)),
            ).fetchone()
            if not row:
                return None
            current = _load(str(row[0] or "{}")) or {}
            updated = _merge_message_metadata(current, patch) if merge else patch
            conn.execute(
                "UPDATE collaboration_messages SET metadata_json = ? "
                "WHERE session_id = ? AND seq = ?",
                (_dump(updated, label="message metadata"), session_id, int(seq)),
            )
            result = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json FROM collaboration_messages WHERE session_id = ? AND seq = ?",
                (session_id, int(seq)),
            ).fetchone()
        return _message_from_row(result) if result else None

    def messages_for_session(
        self,
        session_id: str,
        *,
        limit: int = 200,
        after_seq: int = 0,
    ) -> list[dict[str, Any]]:
        if not session_id:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        limit = max(1, min(2000, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json "
                "FROM collaboration_messages "
                "WHERE session_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (session_id, int(after_seq), limit),
            ).fetchall()
        return [_message_from_row(row) for row in reversed(rows)]

    def messages_for_room(
        self,
        room_id: str,
        *,
        limit: int = 200,
        after_seq: int = 0,
    ) -> list[dict[str, Any]]:
        if not room_id:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        limit = max(1, min(2000, limit))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json "
                "FROM collaboration_messages "
                "WHERE room_id = ? AND seq > ? ORDER BY seq DESC LIMIT ?",
                (room_id, int(after_seq), limit),
            ).fetchall()
        return [_message_from_row(row) for row in reversed(rows)]

    def search_messages(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = normalize_search_query(query)
        if not session_id or not q:
            return []
        session_id = require_cowork_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json "
                "FROM collaboration_messages "
                "WHERE session_id = ? AND (lower(text) LIKE ? OR lower(metadata_json) LIKE ?) "
                "ORDER BY seq DESC LIMIT ?",
                (session_id, f"%{q}%", f"%{q}%", max(1, min(200, limit))),
            ).fetchall()
        return [_message_from_row(row) for row in rows]

    def search_messages_for_room(
        self,
        room_id: str,
        query: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        q = normalize_search_query(query)
        if not room_id or not q:
            return []
        room_id = require_cowork_id(room_id, label="room_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, seq, room_id, participant_id, display_name, text, ts, "
                "metadata_json "
                "FROM collaboration_messages "
                "WHERE room_id = ? AND (lower(text) LIKE ? OR lower(metadata_json) LIKE ?) "
                "ORDER BY seq DESC LIMIT ?",
                (room_id, f"%{q}%", f"%{q}%", max(1, min(200, limit))),
            ).fetchall()
        return [_message_from_row(row) for row in rows]
