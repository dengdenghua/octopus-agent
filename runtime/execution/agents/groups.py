from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from runtime.platform.models import now_utc

logger = logging.getLogger(__name__)

_GROUP_STORE_VERSION = 1
_MAX_GROUPS = 512
_MAX_MEMBERS_PER_GROUP = 512
_MAX_GROUP_STORE_BYTES = 2 * 1024 * 1024


@dataclass
class AgentGroup:
    group_id: str
    display_name: str = ""
    description: str = ""
    members: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=now_utc)
    updated_at: datetime = field(default_factory=now_utc)


class AgentGroupNotFound(KeyError):
    pass


class AgentGroupRegistry:
    def __init__(self, *, state_path: str | Path | None = None) -> None:
        self._groups: dict[str, AgentGroup] = {}
        self._lock = threading.RLock()
        self._state_path = Path(state_path) if state_path is not None else None
        self._load()

    def _load(self) -> None:
        path = self._state_path
        if path is None or not path.is_file():
            return
        try:
            if path.stat().st_size > _MAX_GROUP_STORE_BYTES:
                raise ValueError("group state file is too large")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != _GROUP_STORE_VERSION:
                raise ValueError("unsupported group state schema")
            rows = payload.get("groups")
            if not isinstance(rows, list):
                raise ValueError("groups must be a list")
            loaded: dict[str, AgentGroup] = {}
            for raw in rows[:_MAX_GROUPS]:
                if not isinstance(raw, dict):
                    continue
                group_id = str(raw.get("group_id") or "").strip()
                if not group_id or len(group_id) > 160:
                    continue
                raw_members = raw.get("members")
                members = (
                    [
                        str(member).strip()
                        for member in raw_members[:_MAX_MEMBERS_PER_GROUP]
                        if isinstance(member, str) and member.strip()
                    ]
                    if isinstance(raw_members, list)
                    else []
                )
                try:
                    created_at = datetime.fromisoformat(str(raw.get("created_at") or ""))
                except ValueError:
                    created_at = now_utc()
                try:
                    updated_at = datetime.fromisoformat(str(raw.get("updated_at") or ""))
                except ValueError:
                    updated_at = created_at
                loaded[group_id] = AgentGroup(
                    group_id=group_id,
                    display_name=str(raw.get("display_name") or "")[:240],
                    description=str(raw.get("description") or "")[:2000],
                    members=list(dict.fromkeys(members)),
                    created_at=created_at,
                    updated_at=updated_at,
                )
            self._groups = loaded
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("agent group state load failed: %s", exc)

    def _persist_locked(self) -> None:
        path = self._state_path
        if path is None:
            return
        payload = {
            "version": _GROUP_STORE_VERSION,
            "groups": [
                {
                    "group_id": group.group_id,
                    "display_name": group.display_name,
                    "description": group.description,
                    "members": list(group.members),
                    "created_at": group.created_at.isoformat(),
                    "updated_at": group.updated_at.isoformat(),
                }
                for group in sorted(self._groups.values(), key=lambda item: item.group_id)
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError as exc:
            logger.warning("agent group state save failed: %s", exc)

    # ─── CRUD ────────────────────────────────────────

    def create(self, group: AgentGroup) -> None:
        if not group.group_id:
            raise ValueError("group_id must be non-empty")
        with self._lock:
            if group.group_id in self._groups:
                raise ValueError(f"duplicate group_id: {group.group_id!r}")
            members = list(dict.fromkeys(group.members))
            self._groups[group.group_id] = AgentGroup(
                group_id=group.group_id,
                display_name=group.display_name,
                description=group.description,
                members=members,
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
            self._persist_locked()

    def update(
        self,
        group_id: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
    ) -> AgentGroup:
        with self._lock:
            if group_id not in self._groups:
                raise AgentGroupNotFound(group_id)
            g = self._groups[group_id]
            new = AgentGroup(
                group_id=g.group_id,
                display_name=display_name if display_name is not None else g.display_name,
                description=description if description is not None else g.description,
                members=list(g.members),
                created_at=g.created_at,
                updated_at=now_utc(),
            )
            self._groups[group_id] = new
            self._persist_locked()
            return new

    def remove(self, group_id: str) -> bool:
        with self._lock:
            removed = self._groups.pop(group_id, None) is not None
            if removed:
                self._persist_locked()
            return removed

    def get(self, group_id: str) -> AgentGroup:
        with self._lock:
            if group_id not in self._groups:
                raise AgentGroupNotFound(group_id)
            return self._groups[group_id]

    def has(self, group_id: str) -> bool:
        with self._lock:
            return group_id in self._groups

    def list_all(self) -> list[AgentGroup]:
        with self._lock:
            return sorted(self._groups.values(), key=lambda g: g.group_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._groups)

    def __iter__(self):
        with self._lock:
            return iter(list(self._groups.values()))

    def add_member(self, group_id: str, agent_id: str) -> bool:
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        with self._lock:
            if group_id not in self._groups:
                raise AgentGroupNotFound(group_id)
            g = self._groups[group_id]
            if agent_id in g.members:
                return False
            new_members = [*g.members, agent_id]
            self._groups[group_id] = AgentGroup(
                group_id=g.group_id,
                display_name=g.display_name,
                description=g.description,
                members=new_members,
                created_at=g.created_at,
                updated_at=now_utc(),
            )
            self._persist_locked()
            return True

    def remove_member(self, group_id: str, agent_id: str) -> bool:
        with self._lock:
            if group_id not in self._groups:
                raise AgentGroupNotFound(group_id)
            g = self._groups[group_id]
            if agent_id not in g.members:
                return False
            new_members = [m for m in g.members if m != agent_id]
            self._groups[group_id] = AgentGroup(
                group_id=g.group_id,
                display_name=g.display_name,
                description=g.description,
                members=new_members,
                created_at=g.created_at,
                updated_at=now_utc(),
            )
            self._persist_locked()
            return True

    def groups_for_agent(self, agent_id: str) -> list[str]:
        with self._lock:
            return sorted([gid for gid, g in self._groups.items() if agent_id in g.members])


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def effective_groups_for_agent(
    *,
    agent_id: str,
    static_groups: Iterable[str] = (),
    registry: AgentGroupRegistry | None = None,
) -> list[str]:
    merged: set[str] = set(static_groups)
    if registry is not None:
        merged.update(registry.groups_for_agent(agent_id))
    return sorted(merged)
