"""ThreadStateStore · lightweight thread/state persistence for frontend compat."""

from __future__ import annotations

import contextlib
import copy
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .session_index import SessionIndex, entry_from_thread

_PATH_SEGMENT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _deepcopy(value: Any) -> Any:
    return copy.deepcopy(value)


def _default_values(values: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {
        "title": "New chat",
        "messages": [],
        "artifacts": [],
    }
    if values:
        merged.update(_deepcopy(values))
    return merged


def _safe_path_segment(value: str, fallback: str) -> str:
    clean = _PATH_SEGMENT_RE.sub("_", value.strip())
    clean = re.sub(r"\s+", "-", clean).strip(" .")
    return clean or fallback


class ThreadStateStore:
    """Thread state store with append-only JSONL persistence.

    Two persistence modes:

    1. **Legacy single-file** — ``ThreadStateStore(path=...)`` · every
       thread's records append to one big jsonl. Matches the original
       ``data/threads.jsonl`` behavior.

    2. **Scoped routing** — ``ThreadStateStore(per_agent_base=<repo>)``
       · team threads write to
       ``<repo>/teams/<team_id>/sessions/<thread_id>.jsonl`` first.
       Solo agent threads write under
       ``<repo>/agents/<agent_id>/sessions/<thread_id>.jsonl``. Threads
       with neither team nor agent metadata fall back to
       ``<repo>/data/sessions/misc/<thread_id>.jsonl``.

    Modes are mutually exclusive (pass only one of ``path`` /
    ``per_agent_base``). ``None`` for both is pure in-memory.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        per_agent_base: str | Path | None = None,
        dated_layout: bool = False,
        index_enabled: bool = True,
        session_origin: str = "octopus",
    ) -> None:
        self._threads: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

        # Mode selection
        if path is not None and per_agent_base is not None:
            raise ValueError(
                "ThreadStateStore: pass only one of path= / per_agent_base=",
            )
        self._path: Path | None = Path(path) if path is not None else None
        self._per_agent_base: Path | None = (
            Path(per_agent_base) if per_agent_base is not None else None
        )

        # ── Ergonomics ─────────────────────────────────────
        # ``dated_layout`` shards new threads under
        # ``sessions/<YYYY>/<MM>/<thread_id>.jsonl``. Reads still
        # cover the flat ``sessions/<thread_id>.jsonl`` so older
        # threads are not orphaned. Only honored in per-agent mode.
        self._dated_layout = dated_layout and self._per_agent_base is not None

        # ``session_origin`` is stamped into the per-thread
        # ``session_meta`` header (see ``_write_session_header``).
        # Default is ``octopus`` so operators can tell at a glance
        # which runtime produced a given session file.
        self._session_origin = session_origin

        # Lightweight index for fast list/search. Lives next to the
        # session tree so it's portable. Disabled when neither path
        # nor per_agent_base is set (in-memory tests).
        self._index: SessionIndex | None = None
        if index_enabled:
            index_path = self._resolve_index_path()
            if index_path is not None:
                self._index = SessionIndex(index_path)

        # Load existing records
        if self._path is not None and self._path.exists():
            self._load_from(self._path)
        if self._per_agent_base is not None:
            self._load_from_per_agent_tree()

        # Backfill the index from in-memory state on first boot. The
        # index is authoritative AFTER first write; before then we
        # need to seed it from whatever the file walk discovered.
        if (
            self._index is not None
            and len(self._index) == 0
            and self._threads
        ):
            self._reindex_all_locked()

    # ─── index helpers ───────────────────────────────────────

    def _resolve_index_path(self) -> Path | None:
        if self._per_agent_base is not None:
            return self._per_agent_base / "data" / "sessions" / "session_index.jsonl"
        if self._path is not None:
            return self._path.with_name("session_index.jsonl")
        return None

    def _index_file_for(self, target: Path) -> str:
        """Return the per-thread file path **as recorded in the
        index**, repo-relative when in per-agent mode so the index
        stays portable across moves of the project root.
        """
        if self._per_agent_base is None:
            return str(target)
        try:
            return str(
                target.resolve().relative_to(
                    self._per_agent_base.resolve()
                )
            ).replace("\\", "/")
        except ValueError:
            return str(target)

    def _reindex_all_locked(self) -> None:
        assert self._index is not None
        for _thread_id, thread in self._threads.items():
            target = (
                self._per_thread_path(thread)
                if self._per_agent_base is not None
                else self._path
            )
            if target is None:
                continue
            entry = entry_from_thread(
                thread,
                file_path=self._index_file_for(target),
            )
            if entry is not None:
                self._index.upsert(entry)

    def create(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        values: dict[str, Any] | None = None,
        status: str = "idle",
    ) -> dict[str, Any]:
        now = _utc_now_iso()
        thread = {
            "thread_id": uuid4().hex,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "metadata": _deepcopy(metadata or {}),
            "values": _default_values(values),
        }
        state = self._make_state(thread)
        with self._lock:
            self._threads[thread["thread_id"]] = thread
            self._history[thread["thread_id"]] = [state]
            self._append_upsert(thread, state)
            return _deepcopy(thread)

    def ensure_thread(
        self,
        thread_id: str,
        *,
        metadata: dict[str, Any] | None = None,
        values: dict[str, Any] | None = None,
        status: str = "idle",
    ) -> dict[str, Any]:
        with self._lock:
            existing = self._threads.get(thread_id)
            if existing is not None:
                return _deepcopy(existing)

            now = _utc_now_iso()
            thread = {
                "thread_id": thread_id,
                "status": status,
                "created_at": now,
                "updated_at": now,
                "metadata": _deepcopy(metadata or {}),
                "values": _default_values(values),
            }
            state = self._make_state(thread)
            self._threads[thread_id] = thread
            self._history[thread_id] = [state]
            self._append_upsert(thread, state)
            return _deepcopy(thread)

    def get(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            thread = self._threads.get(thread_id)
            return _deepcopy(thread) if thread is not None else None

    def delete(self, thread_id: str) -> bool:
        with self._lock:
            if thread_id not in self._threads:
                return False
            thread = _deepcopy(self._threads[thread_id])
            del self._threads[thread_id]
            self._history.pop(thread_id, None)
            self._append_delete(thread_id, thread)
            return True

    def clear(self) -> None:
        """Drop all in-memory threads and rebuild persistent indices on disk."""
        with self._lock:
            self._threads.clear()
            self._history.clear()

    def search(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        metadata: dict[str, Any] | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> list[dict[str, Any]]:
        with self._lock:
            threads = list(self._threads.values())
        if metadata:
            threads = [
                thread for thread in threads
                if all(thread["metadata"].get(key) == value for key, value in metadata.items())
            ]
        reverse = sort_order.lower() != "asc"
        threads.sort(key=lambda item: item.get(sort_by) or "", reverse=reverse)
        return [_deepcopy(item) for item in threads[offset: offset + limit]]

    def get_state(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            history = self._history.get(thread_id)
            if not history:
                return None
            return _deepcopy(history[-1])

    def get_history(self, thread_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            history = self._history.get(thread_id, [])
            sliced = history[-limit:] if limit > 0 else history[:]
        return [_deepcopy(item) for item in reversed(sliced)]

    def update_state(
        self,
        thread_id: str,
        *,
        values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if thread_id not in self._threads:
                raise KeyError(thread_id)
            thread = _deepcopy(self._threads[thread_id])
            merged_values = _default_values(thread.get("values"))
            if values:
                for key, value in values.items():
                    merged_values[key] = _deepcopy(value)
            merged_metadata = _deepcopy(thread.get("metadata", {}))
            if metadata:
                merged_metadata.update(_deepcopy(metadata))
            thread["values"] = merged_values
            thread["metadata"] = merged_metadata
            thread["updated_at"] = _utc_now_iso()
            if status is not None:
                thread["status"] = status
            state = self._make_state(thread)
            self._threads[thread_id] = thread
            self._history.setdefault(thread_id, []).append(state)
            self._append_upsert(thread, state)
            return _deepcopy(state)

    def __len__(self) -> int:
        with self._lock:
            return len(self._threads)

    def _make_state(self, thread: dict[str, Any]) -> dict[str, Any]:
        checkpoint_id = uuid4().hex
        return {
            "values": _deepcopy(thread["values"]),
            "next": [],
            "metadata": _deepcopy(thread["metadata"]),
            "checkpoint": {
                "id": checkpoint_id,
                "checkpoint_id": checkpoint_id,
                "ts": thread["updated_at"],
            },
            "checkpoint_id": checkpoint_id,
            "tasks": [],
        }

    # ─── path routing ────────────────────────────────────────

    def _agent_id_for(self, thread: dict[str, Any]) -> str | None:
        """Extract a stable agent_id from a thread's metadata (if any).

        Metadata keys we try, in order: ``agent`` · ``agent_id`` ·
        ``assistant_id``. We filter out the ``lead_agent`` placeholder
        (used by the OpenAI-compat gateway when no persona is bound).
        """
        meta = thread.get("metadata") or {}
        for key in ("agent", "agent_id", "assistant_id"):
            value = meta.get(key)
            if isinstance(value, str) and value and value != "lead_agent":
                return value
        return None

    def _team_id_for(self, thread: dict[str, Any]) -> str | None:
        meta = thread.get("metadata") or {}
        value = meta.get("team_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _team_path_for(self, thread: dict[str, Any]) -> Path | None:
        if self._per_agent_base is None:
            return None
        thread_id = thread.get("thread_id")
        team_id = self._team_id_for(thread)
        if not isinstance(thread_id, str) or not thread_id or team_id is None:
            return None
        sess_root = (
            self._per_agent_base / "teams" / _safe_path_segment(team_id, "team")
            / "sessions"
        )
        return self._resolve_thread_file(sess_root, thread_id)

    def _agent_path_for(self, thread: dict[str, Any]) -> Path | None:
        if self._per_agent_base is None:
            return None
        thread_id = thread.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        agent_id = self._agent_id_for(thread)
        if agent_id is None:
            return None
        sess_root = (
            self._per_agent_base / "agents" / _safe_path_segment(agent_id, "agent")
            / "sessions"
        )
        return self._resolve_thread_file(sess_root, thread_id)

    def _misc_path_for(self, thread_id: str) -> Path | None:
        if self._per_agent_base is None:
            return None
        sess_root = self._per_agent_base / "data" / "sessions" / "misc"
        return self._resolve_thread_file(sess_root, thread_id)

    def _resolve_thread_file(self, sess_root: Path, thread_id: str) -> Path:
        """Pick the on-disk path for a thread's jsonl.

        Read order: any existing file (flat OR dated) wins so an
        upgrade from flat → dated layout doesn't orphan history.
        Write order: dated when ``dated_layout`` is on, flat
        otherwise.
        """
        flat = sess_root / f"{thread_id}.jsonl"
        if flat.exists():
            return flat
        if self._dated_layout:
            # Look for any existing dated file (created in a prior
            # month) before defaulting to "now".
            if sess_root.exists():
                hits = list(sess_root.rglob(f"{thread_id}.jsonl"))
                if hits:
                    # Take the deepest match — dated paths are
                    # /YYYY/MM/<id>.jsonl, flat is /<id>.jsonl;
                    # already-exists short-circuits flat above.
                    return hits[0]
            now = datetime.utcnow()
            return (
                sess_root
                / f"{now.year:04d}"
                / f"{now.month:02d}"
                / f"{thread_id}.jsonl"
            )
        return flat

    def _per_thread_path(self, thread: dict[str, Any]) -> Path | None:
        """Compute the on-disk jsonl for this thread in per-agent mode.

        Returns None when this store isn't running in per-agent mode
        (caller should fall back to self._path instead).
        """
        if self._per_agent_base is None:
            return None
        thread_id = thread.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        team_path = self._team_path_for(thread)
        if team_path is not None:
            return team_path
        agent_path = self._agent_path_for(thread)
        if agent_path is not None:
            return agent_path
        # No agent bound yet — stash in misc. Future writes keep landing
        # here unless we add rename-on-agent-bind (we don't, to keep
        # file-path stability).
        return self._misc_path_for(thread_id)

    def _append_upsert(self, thread: dict[str, Any], state: dict[str, Any]) -> None:
        record = {
            "op": "upsert",
            "thread_id": thread["thread_id"],
            "thread": thread,
            "state": state,
        }
        self._cleanup_stale_paths_if_promoted(thread)
        target = self._append_record(thread, record)
        if self._index is not None and target is not None:
            entry = entry_from_thread(
                thread,
                file_path=self._index_file_for(target),
            )
            if entry is not None:
                self._index.upsert(entry)

    def _cleanup_stale_paths_if_promoted(self, thread: dict[str, Any]) -> None:
        """If a thread just gained an agent tag and is about to be
        written under ``agents/<agent_id>/sessions/...``, remove any
        earlier stub file that was written to ``data/sessions/misc/``.

        Rationale: the very first ``ensure_thread()`` runs before any
        turn knows which agent will handle the thread, so it routes
        to misc. After the first turn's ``update_state()`` assigns an
        ``agent`` in metadata, later writes land under the per-agent
        path — leaving a lingering misc file for the same thread id
        that never receives more writes. Delete it so each thread has
        exactly one on-disk home.
        """
        if self._per_agent_base is None:
            return
        thread_id = thread.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            return
        target = self._per_thread_path(thread)
        candidates = [
            self._misc_path_for(thread_id),
            self._agent_path_for(thread),
        ]
        for candidate in candidates:
            if candidate is None or candidate == target or not candidate.exists():
                continue
            with contextlib.suppress(OSError):
                candidate.unlink()

    def _append_delete(self, thread_id: str, thread: dict[str, Any] | None = None) -> None:
        stub = thread or {"thread_id": thread_id, "metadata": {}}
        record = {"op": "delete", "thread_id": thread_id}
        self._append_record(stub, record)
        if self._index is not None:
            self._index.delete(thread_id)

    def _append_record(self, thread: dict[str, Any], record: dict[str, Any]) -> Path | None:
        target: Path | None
        target = self._per_thread_path(thread) if self._per_agent_base is not None else self._path
        if target is None:
            return None
        is_new = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            # Write session_meta header on brand-new files.
            if is_new:
                meta = self._session_meta(thread)
                handle.write(json.dumps(meta, ensure_ascii=False) + "\n")
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return target

    def _session_meta(self, thread: dict[str, Any]) -> dict[str, Any]:
        """Build a ``session_meta`` header. The first line of each
        session file carries the metadata the journal indexer
        needs (id, origin, timestamps) before any user content
        appears."""
        metadata = thread.get("metadata") or {}
        return {
            "type": "session_meta",
            "payload": {
                "id": thread.get("thread_id", ""),
                "timestamp": thread.get("created_at", _utc_now_iso()),
                "originator": self._session_origin,
                "agent": metadata.get("agent"),
                "team_id": metadata.get("team_id"),
            },
        }

    # ─── load ────────────────────────────────────────────────

    def _load_from(
        self,
        path: Path,
        implied_agent: str | None = None,
        implied_team_id: str | None = None,
    ) -> None:
        """Read a single jsonl (legacy single-file OR one per-thread
        file) and fold its records into memory.

        ``implied_agent`` · when set and a record's thread has no
        explicit ``metadata.agent`` tag, tag it to this value. The
        caller (per-agent tree walker) passes the folder-derived
        agent id so legacy threads that predate the metadata tagging
        get retroactively attributed. This is the "migration" path
        for old history that was invisible under the agent filter.
        """
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip session_meta headers — they have no thread dict.
            if record.get("type") == "session_meta":
                continue
            thread_id = record.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id:
                continue
            if record.get("op") == "delete":
                self._threads.pop(thread_id, None)
                self._history.pop(thread_id, None)
                continue
            thread = record.get("thread")
            state = record.get("state")
            if not isinstance(thread, dict) or not isinstance(state, dict):
                continue
            # Retro-tag legacy threads that lived under a per-agent
            # folder without explicit metadata.agent. The folder name
            # IS the agent id — trust it. Don't overwrite an existing
            # tag (the thread may have been moved; explicit wins).
            if implied_agent and isinstance(thread.get("metadata"), dict):
                meta = thread["metadata"]
                if not meta.get("agent"):
                    meta["agent"] = implied_agent
            if implied_team_id and isinstance(thread.get("metadata"), dict):
                meta = thread["metadata"]
                if not meta.get("team_id"):
                    meta["team_id"] = implied_team_id
                if not meta.get("mode"):
                    meta["mode"] = "team"
            self._threads[thread_id] = thread
            self._history.setdefault(thread_id, []).append(state)

    def _load_from_per_agent_tree(self) -> None:
        """Scan team, agent, and misc session trees and load every thread."""
        assert self._per_agent_base is not None
        misc_dir = self._per_agent_base / "data" / "sessions" / "misc"
        if misc_dir.exists():
            for jsonl in misc_dir.rglob("*.jsonl"):
                self._load_from(jsonl)
        agents_root = self._per_agent_base / "agents"
        if agents_root.exists():
            for agent_dir in agents_root.iterdir():
                if not agent_dir.is_dir():
                    continue
                sess = agent_dir / "sessions"
                if not sess.exists():
                    continue
                implied = agent_dir.name
                for jsonl in sess.rglob("*.jsonl"):
                    self._load_from(jsonl, implied_agent=implied)
        teams_root = self._per_agent_base / "teams"
        if teams_root.exists():
            for team_dir in teams_root.iterdir():
                if not team_dir.is_dir():
                    continue
                sess = team_dir / "sessions"
                if not sess.exists():
                    continue
                implied_team_id = team_dir.name
                for jsonl in sess.rglob("*.jsonl"):
                    self._load_from(jsonl, implied_team_id=implied_team_id)
