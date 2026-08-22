"""Pure validation and serialization helpers for team invitations."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_invitations (
    invite_id      TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL,
    room_id        TEXT NOT NULL,
    token_hash     TEXT NOT NULL UNIQUE,
    role           TEXT NOT NULL CHECK (role IN ('member', 'viewer')),
    created_by     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL,
    max_uses       INTEGER NOT NULL CHECK (max_uses > 0),
    use_count      INTEGER NOT NULL DEFAULT 0 CHECK (use_count >= 0),
    last_used_at   TEXT,
    revoked_at     TEXT,
    revoked_by     TEXT
);
CREATE INDEX IF NOT EXISTS idx_team_invites_room
    ON team_invitations(tenant_id, room_id, created_at DESC);

CREATE TABLE IF NOT EXISTS team_invitation_uses (
    invite_id      TEXT NOT NULL,
    use_number     INTEGER NOT NULL,
    tenant_id      TEXT NOT NULL,
    room_id        TEXT NOT NULL,
    actor_id       TEXT NOT NULL,
    used_at        TEXT NOT NULL,
    request_id     TEXT NOT NULL,
    PRIMARY KEY (invite_id, use_number),
    FOREIGN KEY (invite_id) REFERENCES team_invitations(invite_id)
);
CREATE INDEX IF NOT EXISTS idx_team_invite_uses_actor
    ON team_invitation_uses(tenant_id, room_id, actor_id, used_at DESC);

CREATE TABLE IF NOT EXISTS team_join_requests (
    request_id       TEXT PRIMARY KEY,
    invite_id        TEXT NOT NULL,
    tenant_id        TEXT NOT NULL,
    room_id          TEXT NOT NULL,
    actor_id         TEXT NOT NULL,
    display_name     TEXT NOT NULL,
    role             TEXT NOT NULL CHECK (role IN ('member', 'viewer')),
    status           TEXT NOT NULL CHECK (
        status IN ('pending', 'approved', 'rejected', 'withdrawn', 'expired', 'cancelled')
    ),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    decided_at       TEXT,
    decided_by       TEXT,
    decision_reason  TEXT,
    participant_id   TEXT,
    UNIQUE (invite_id, actor_id),
    FOREIGN KEY (invite_id) REFERENCES team_invitations(invite_id)
);
CREATE INDEX IF NOT EXISTS idx_team_join_requests_room
    ON team_join_requests(tenant_id, room_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_team_join_requests_actor
    ON team_join_requests(tenant_id, actor_id, created_at DESC);
"""

_INVITE_COLUMNS = (
    "invite_id, tenant_id, room_id, token_hash, role, created_by, created_at, "
    "expires_at, max_uses, use_count, last_used_at, revoked_at, revoked_by"
)
_JOIN_REQUEST_COLUMNS = (
    "request_id, invite_id, tenant_id, room_id, actor_id, display_name, role, "
    "status, created_at, updated_at, expires_at, decided_at, decided_by, "
    "decision_reason, participant_id"
)


def _default_db_path() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "teamroom" / "team_invitations.db"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _as_utc(parsed)


def _required_text(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"invalid {label}")
    return text


def _optional_note(value: object, *, label: str, max_length: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) > max_length or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"invalid {label}")
    return text


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _status(invitation: dict[str, Any], now: datetime) -> str:
    if invitation.get("revoked_at"):
        return "revoked"
    if _parse_time(str(invitation["expires_at"])) <= now:
        return "expired"
    if int(invitation["use_count"]) >= int(invitation["max_uses"]):
        return "exhausted"
    return "active"


def _from_row(row: sqlite3.Row, *, now: datetime) -> dict[str, Any]:
    invitation = {
        "id": str(row["invite_id"]),
        "tenant_id": str(row["tenant_id"]),
        "team_id": str(row["room_id"]),
        "room_id": str(row["room_id"]),
        "token_hash": str(row["token_hash"]),
        "role": str(row["role"]),
        "created_by": str(row["created_by"]),
        "created_at": str(row["created_at"]),
        "expires_at": str(row["expires_at"]),
        "max_uses": int(row["max_uses"]),
        "use_count": int(row["use_count"]),
        "last_used_at": row["last_used_at"],
        "revoked_at": row["revoked_at"],
        "revoked_by": row["revoked_by"],
    }
    invitation["status"] = _status(invitation, now)
    invitation["remaining_uses"] = max(
        0,
        int(invitation["max_uses"]) - int(invitation["use_count"]),
    )
    return invitation


def _without_secret(invitation: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in invitation.items() if key != "token_hash"}


def _join_request_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["request_id"]),
        "invite_id": str(row["invite_id"]),
        "tenant_id": str(row["tenant_id"]),
        "team_id": str(row["room_id"]),
        "room_id": str(row["room_id"]),
        "actor_id": str(row["actor_id"]),
        "display_name": str(row["display_name"]),
        "role": str(row["role"]),
        "status": str(row["status"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "expires_at": str(row["expires_at"]),
        "decided_at": row["decided_at"],
        "decided_by": row["decided_by"],
        "decision_reason": str(row["decision_reason"] or ""),
        "participant_id": row["participant_id"],
    }
