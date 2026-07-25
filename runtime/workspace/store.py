"""WorkspaceStore · SQLite-backed persistence for Workspace + members.

Two tables (schema matches the task spec):
  - ``workspaces``: PK id, name, mount_type, mount_target,
    ``mount_options_json`` (encrypted sensitive fields), owner_id, created_at
  - ``workspace_members``: composite PK (workspace_id, member_id), role,
    added_at

``mount_options_json`` is the output of ``crypto.encrypt_options`` —
sensitive fields (password, token, etc.) are individually encrypted inside
the JSON blob; non-sensitive fields stay plaintext so they remain queryable
and debuggable. Reads decrypt on the fly via ``crypto.decrypt_options`` so
callers always see the original dict.

Mirrors the SQLite style used in ``runtime/projectos/store.py`` and
``runtime/memory/cowork/group_store.py``: ``sqlite3`` stdlib +
``threading.Lock`` for write serialization, ``PRAGMA journal_mode=WAL``.
``delete_workspace`` cascades to ``workspace_members`` inside one
transaction so partial state never leaks.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.workspace.crypto import decrypt_options, encrypt_options
from runtime.workspace.model import (
    VALID_MEMBER_ROLES,
    VALID_MOUNT_TYPES,
    Workspace,
    WorkspaceMember,
)

_LOG = logging.getLogger("octopus.workspace.store")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    mount_type         TEXT NOT NULL,
    mount_target       TEXT NOT NULL,
    mount_options_json TEXT NOT NULL,
    owner_id           TEXT NOT NULL,
    created_at         REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL,
    member_id    TEXT NOT NULL,
    role         TEXT NOT NULL,
    added_at     REAL NOT NULL,
    PRIMARY KEY (workspace_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner ON workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_workspace_members_member ON workspace_members(member_id);
"""


def _default_db_path() -> Path:
    """``<data>/workspaces.db`` — same ``app_paths`` data dir other stores use."""
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "workspaces.db"


def _workspace_from_row(row: tuple[Any, ...]) -> Workspace:
    return Workspace(
        id=str(row[0]),
        name=str(row[1]),
        mount_type=str(row[2]) if str(row[2]) in VALID_MOUNT_TYPES else "local",
        mount_target=str(row[3]),
        mount_options=decrypt_options(str(row[4])),
        owner_id=str(row[5]),
        created_at=float(row[6]),
    )


def _member_from_row(row: tuple[Any, ...]) -> WorkspaceMember:
    role = str(row[2]) if str(row[2]) in VALID_MEMBER_ROLES else "viewer"
    return WorkspaceMember(
        workspace_id=str(row[0]),
        member_id=str(row[1]),
        role=role,
        added_at=float(row[3]),
    )


class WorkspaceStore:
    """SQLite-backed persistence for Workspace + WorkspaceMember rows.

    The constructor accepts a full DB file path (``db_path``) so tests can
    point at a tmpdir. When ``db_path`` is None the default
    ``<data>/workspaces.db`` is used (resolved via ``app_paths``).
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        path = Path(db_path) if db_path else _default_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = path
        self._lock = threading.Lock()
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ── workspaces ────────────────────────────────────────────────────────

    def create_workspace(
        self,
        *,
        name: str,
        mount_type: str,
        mount_target: str,
        mount_options: dict[str, Any] | None = None,
        owner_id: str,
        workspace_id: str | None = None,
        created_at: float | None = None,
    ) -> Workspace:
        """Insert a new workspace row. ``mount_options`` is encrypted at rest.

        The owner is auto-added to ``workspace_members`` with role=``"owner"``
        so membership queries for the owner work without an extra call.
        """
        if mount_type not in VALID_MOUNT_TYPES:
            raise ValueError(
                f"invalid mount_type {mount_type!r}; "
                f"expected one of {sorted(VALID_MOUNT_TYPES)}"
            )
        if not name.strip():
            raise ValueError("name is required")
        if not owner_id:
            raise ValueError("owner_id is required")
        ws = Workspace(
            id=workspace_id or str(uuid4()),
            name=name.strip(),
            mount_type=mount_type,
            mount_target=mount_target,
            mount_options=dict(mount_options or {}),
            owner_id=owner_id,
            created_at=float(created_at if created_at is not None else time.time()),
        )
        encrypted = encrypt_options(ws.mount_options)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO workspaces"
                "(id, name, mount_type, mount_target, mount_options_json, "
                "owner_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ws.id,
                    ws.name,
                    ws.mount_type,
                    ws.mount_target,
                    encrypted,
                    ws.owner_id,
                    ws.created_at,
                ),
            )
        # Auto-add the owner as a member so list_workspaces_for_user works
        # for the owner without an explicit add_member call.
        self.add_member(ws.id, ws.owner_id, role="owner", added_at=ws.created_at)
        return ws

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, mount_type, mount_target, mount_options_json, "
                "owner_id, created_at FROM workspaces WHERE id=?",
                (workspace_id,),
            ).fetchone()
        if not row:
            return None
        return _workspace_from_row(row)

    def list_workspaces(self) -> list[Workspace]:
        """All workspaces, ordered by creation time then id (stable)."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, mount_type, mount_target, mount_options_json, "
                "owner_id, created_at FROM workspaces "
                "ORDER BY created_at, id"
            ).fetchall()
        return [_workspace_from_row(r) for r in rows]

    def list_workspaces_for_user(self, member_id: str) -> list[Workspace]:
        """Workspaces ``member_id`` belongs to (any role)."""
        if not member_id:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT w.id, w.name, w.mount_type, w.mount_target, "
                "w.mount_options_json, w.owner_id, w.created_at "
                "FROM workspaces w "
                "INNER JOIN workspace_members m ON m.workspace_id = w.id "
                "WHERE m.member_id = ? "
                "ORDER BY w.created_at, w.id",
                (member_id,),
            ).fetchall()
        return [_workspace_from_row(r) for r in rows]

    def delete_workspace(self, workspace_id: str) -> bool:
        """Remove a workspace and all of its members in one transaction.

        Returns True if the workspace existed and was removed, False if it
        was already gone (idempotent).
        """
        if not workspace_id:
            return False
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
            if not exists:
                return False
            conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id=?",
                (workspace_id,),
            )
            conn.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))
        return True

    # ── members ───────────────────────────────────────────────────────────

    def add_member(
        self,
        workspace_id: str,
        member_id: str,
        *,
        role: str = "viewer",
        added_at: float | None = None,
    ) -> WorkspaceMember:
        """Add or upsert a membership row.

        If the (workspace_id, member_id) pair already exists, the role is
        updated to the new value — useful for promoting/demoting a user
        without a remove+re-add round-trip.
        """
        if role not in VALID_MEMBER_ROLES:
            raise ValueError(
                f"invalid role {role!r}; "
                f"expected one of {sorted(VALID_MEMBER_ROLES)}"
            )
        if not member_id:
            raise ValueError("member_id is required")
        if not workspace_id:
            raise ValueError("workspace_id is required")
        member = WorkspaceMember(
            workspace_id=workspace_id,
            member_id=member_id,
            role=role,
            added_at=float(added_at if added_at is not None else time.time()),
        )
        with self._lock, self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()
            if not exists:
                raise ValueError(f"workspace {workspace_id!r} does not exist")
            conn.execute(
                "INSERT INTO workspace_members(workspace_id, member_id, role, added_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(workspace_id, member_id) DO UPDATE SET role=excluded.role",
                (
                    member.workspace_id,
                    member.member_id,
                    member.role,
                    member.added_at,
                ),
            )
        return member

    def remove_member(self, workspace_id: str, member_id: str) -> bool:
        """Remove a membership row. Returns True if a row was deleted."""
        if not workspace_id or not member_id:
            return False
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id=? AND member_id=?",
                (workspace_id, member_id),
            )
            return cur.rowcount > 0

    def list_members(self, workspace_id: str) -> list[WorkspaceMember]:
        """All members of a workspace, ordered by added_at then member_id."""
        if not workspace_id:
            return []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT workspace_id, member_id, role, added_at "
                "FROM workspace_members WHERE workspace_id=? "
                "ORDER BY added_at, member_id",
                (workspace_id,),
            ).fetchall()
        return [_member_from_row(r) for r in rows]

    def get_member_role(self, workspace_id: str, member_id: str) -> str | None:
        """Return the role for (workspace_id, member_id), or None if not a member."""
        if not workspace_id or not member_id:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT role FROM workspace_members "
                "WHERE workspace_id=? AND member_id=?",
                (workspace_id, member_id),
            ).fetchone()
        return str(row[0]) if row else None


__all__ = ["WorkspaceStore"]
