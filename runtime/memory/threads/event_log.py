"""Append-only item-oriented event log.

Each thread owns one ``.jsonl`` file. Every observable runtime fact —
turn started, item started, item delta, item completed, turn completed —
appends as one line. The file is the source of truth: process restart,
client reconnect, multi-window resume all rebuild from disk.

Wire format (one event per line)::

    {"event":"thread_started","threadId":"...","ts":"..."}
    {"event":"turn_started","threadId":"...","turnId":"...","ts":"...","params":{...}}
    {"event":"item_started","threadId":"...","turnId":"...","item":{...}}
    {"event":"item_delta","threadId":"...","turnId":"...","itemId":"...","kind":"agentMessage","delta":"..."}
    {"event":"item_completed","threadId":"...","turnId":"...","item":{...}}
    {"event":"turn_completed","threadId":"...","turnId":"...","status":"completed"}

Replay walks events in order, applying each to a ``Turn``. Idempotent —
duplicates are detected by ``itemId`` and silently merged.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.models.primitives import new_id, now_utc
from runtime.protocol.items import (
    AgentMessageItem,
    AgentPhaseSnapshot,
    ApprovalItem,
    ArtifactItem,
    CommandExecutionItem,
    ErrorItem,
    FileChange,
    FileChangeItem,
    FileHunk,
    Item,
    ItemStatus,
    ItemType,
    McpToolCallItem,
    McpToolProgress,
    PlanItem,
    ReasoningItem,
    SteeringUserMessageItem,
    SubagentItem,
    TodoListItem,
    Turn,
    TurnParams,
    TurnStatus,
    UserMessageItem,
    VerificationItem,
    WorkbenchSnapshotV2,
    WorkspaceFocus,
)
from runtime.protocol.text_limits import (
    MAX_AGGREGATED_OUTPUT,
    MAX_STREAM_ITEM_CONTENT,
    OUTPUT_TRUNCATION_MARK,
    STREAM_CONTENT_TRUNCATION_MARK,
    append_capped_text,
)

_logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _exclusive_file_lock(stream: Any, path: Path) -> Iterator[None]:
    """Best-effort cross-process exclusive lock for one open file."""
    fd = stream.fileno()
    locked = False
    try:
        try:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True
        except (ImportError, OSError) as exc:
            _logger.warning(
                "event-log: cross-process lock unavailable for %s (%s)",
                path.name,
                exc,
            )
        yield
    finally:
        if locked:
            with contextlib.suppress(ImportError, OSError):
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)


EventKind = Literal[
    "thread_started",
    "thread_archived",
    "turn_started",
    "turn_updated",
    "turn_completed",
    "turn_diff_updated",
    "item_started",
    "item_delta",
    "item_completed",
    "turn_compacted",
]

_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def validate_thread_id(thread_id: str) -> str:
    if not isinstance(thread_id, str) or not _THREAD_ID_RE.fullmatch(thread_id):
        raise ValueError("threadId must be 1-128 chars of letters, numbers, '_' or '-'")
    return thread_id


def thread_log_path(logs_root: Path | str, thread_id: str) -> Path:
    safe_thread_id = validate_thread_id(thread_id)
    return Path(logs_root) / f"{safe_thread_id}.jsonl"


def actor_id_from_turn_params(params: TurnParams | None) -> str | None:
    if params is None:
        return None
    for block in params.input:
        if not isinstance(block, dict):
            continue
        metadata = block.get("metadata")
        if not isinstance(metadata, dict):
            continue
        actor_id = metadata.get("actor_id") or metadata.get("actorId")
        if isinstance(actor_id, str) and actor_id.strip():
            return actor_id.strip()
    return None


def owner_actor_id_from_turns(turns: list[Turn]) -> str | None:
    for turn in turns:
        actor_id = actor_id_from_turn_params(turn.params)
        if actor_id is not None:
            return actor_id
    return None


class LoggedEvent(BaseModel):
    """Single line in the JSONL log.

    The schema is intentionally loose: ``payload`` is opaque JSON and
    new event kinds add fields without breaking older readers.
    """

    model_config = ConfigDict(populate_by_name=True)

    event: EventKind
    # Stable identity makes replay idempotent under at-least-once delivery,
    # log replication and crash recovery. Old JSONL lines omit it and receive
    # a deterministic content-derived ``legacy:<digest>`` identity.
    event_id: str | None = Field(default=None, alias="eventId")
    thread_id: str = Field(alias="threadId")
    ts: datetime = Field(default_factory=now_utc)
    turn_id: str | None = Field(default=None, alias="turnId")
    payload: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EventLogSnapshot:
    """Immutable, byte-bounded view of one event log.

    ``cursor`` and ``events`` always describe the same file prefix. Anything
    appended after the snapshot boundary is intentionally deferred to the
    next resume, eliminating the replay/cursor race that can otherwise skip a
    live delta forever.
    """

    events: tuple[tuple[int, LoggedEvent], ...]
    cursor: int
    stream_id: str | None = None

    def replay(self) -> list[Turn]:
        turns: list[Turn] = []
        by_id: dict[str, Turn] = {}
        for _sequence, event in self.events:
            _apply_event(event, turns, by_id)
        return turns

    def cursor_delta(self, after_sequence: int) -> tuple[list[str], bool]:
        """Return changed turn ids and whether a full reset is required."""
        after = max(0, int(after_sequence))
        if after > self.cursor:
            return [], True
        changed_turn_ids: list[str] = []
        seen_turn_ids: set[str] = set()
        requires_reset = False
        for sequence, event in self.events:
            if sequence <= after:
                continue
            if event.event == "turn_compacted":
                requires_reset = True
            if event.turn_id and event.turn_id not in seen_turn_ids:
                seen_turn_ids.add(event.turn_id)
                changed_turn_ids.append(event.turn_id)
        return changed_turn_ids, requires_reset


class EventLog:
    """Per-thread JSONL writer + reader.

    Concurrency: a process-local ``threading.Lock`` plus an OS file lock
    guards each append. Readers snapshot lock-free; a partial trailing line
    remains invisible until the next snapshot. This keeps one shared thread
    log valid under multiple Uvicorn workers and second-tab steering.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    # ── Writer side ──────────────────────────────────────────

    def append(self, event: LoggedEvent) -> None:
        if not event.event_id:
            event = event.model_copy(update={"event_id": f"evt_{new_id().hex}"})
        line = event.model_dump_json(by_alias=True) + "\n"
        with (
            self._lock,
            self._path.open("a", encoding="utf-8") as stream,
            _exclusive_file_lock(stream, self._path),
        ):
            stream.seek(0, 2)
            stream.write(line)
            stream.flush()

    def reserve_timeline_sequence(self, turn_id: str) -> int:
        """Atomically reserve the next 1-based item slot for one turn.

        The mutable sidecar is only an allocator; item coordinates remain in
        the append-only event log and are still the replay source of truth.
        A fresh sidecar seeds itself from replay so upgrades and restored logs
        preserve existing coordinates.
        """
        counter_path = self._path.with_suffix(self._path.suffix + ".timeline")
        counter_path.parent.mkdir(parents=True, exist_ok=True)
        with (
            counter_path.open("a+", encoding="utf-8") as stream,
            _exclusive_file_lock(stream, counter_path),
        ):
            stream.seek(0)
            try:
                counters = json.loads(stream.read() or "{}")
            except (json.JSONDecodeError, TypeError, ValueError):
                counters = {}
            if not isinstance(counters, dict):
                counters = {}
            raw_current = counters.get(turn_id)
            if isinstance(raw_current, int) and raw_current >= 0:
                current = raw_current
            else:
                replayed = next((turn for turn in self.replay() if turn.id == turn_id), None)
                current = (
                    max(
                        (
                            item.timeline_sequence or 0
                            for item in replayed.items
                            if item.timeline_sequence is not None
                        ),
                        default=0,
                    )
                    if replayed is not None
                    else 0
                )
            reserved = current + 1
            counters[turn_id] = reserved
            stream.seek(0)
            stream.truncate()
            stream.write(json.dumps(counters, separators=(",", ":")))
            stream.flush()
            return reserved

    def thread_started(self, thread_id: str) -> None:
        self.append(
            LoggedEvent(
                event="thread_started",
                threadId=thread_id,
                payload={"streamId": f"stream_{new_id().hex}"},
            )
        )

    def turn_started(self, thread_id: str, turn: Turn) -> None:
        self.append(
            LoggedEvent(
                event="turn_started",
                threadId=thread_id,
                turnId=turn.id,
                payload={
                    "params": (turn.params.model_dump(by_alias=True) if turn.params else None),
                    "startedAt": turn.started_at.isoformat(),
                },
            )
        )

    def turn_completed(
        self,
        thread_id: str,
        turn_id: str,
        status: TurnStatus,
        error: dict[str, Any] | None = None,
    ) -> None:
        self.append(
            LoggedEvent(
                event="turn_completed",
                threadId=thread_id,
                turnId=turn_id,
                payload={"status": status.value, "error": error},
            )
        )

    def turn_updated(
        self,
        thread_id: str,
        turn_id: str,
        *,
        phases: list[dict[str, Any]] | None = None,
        workspace_focus: dict[str, Any] | None = None,
        workbench_snapshot: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if phases is not None:
            payload["phases"] = phases
        if workspace_focus is not None:
            payload["workspaceFocus"] = workspace_focus
        if workbench_snapshot is not None:
            payload["workbenchSnapshot"] = workbench_snapshot
        if not payload:
            return
        self.append(
            LoggedEvent(
                event="turn_updated",
                threadId=thread_id,
                turnId=turn_id,
                payload=payload,
            )
        )

    def turn_compacted(
        self,
        thread_id: str,
        summary_turn: Turn,
        superseded_turn_ids: list[str],
    ) -> None:
        """Record that ``superseded_turn_ids`` have been summarised into
        ``summary_turn``. Subsequent ``replay()`` calls will surface the
        summary in place of the old turns, keeping context bounded.

        The old events stay on disk — the log remains append-only, and
        audits can reconstruct the original sequence by ignoring
        ``turn_compacted`` events. Replay is the only reader affected.
        """
        self.append(
            LoggedEvent(
                event="turn_compacted",
                threadId=thread_id,
                turnId=summary_turn.id,
                payload={
                    "summaryTurn": summary_turn.model_dump(by_alias=True, mode="json"),
                    "supersededTurnIds": list(superseded_turn_ids),
                },
            )
        )

    def item_started(self, thread_id: str, turn_id: str, item: Item) -> None:
        self.append(
            LoggedEvent(
                event="item_started",
                threadId=thread_id,
                turnId=turn_id,
                payload={"item": item.model_dump(by_alias=True, mode="json")},
            )
        )

    def item_delta(
        self,
        thread_id: str,
        turn_id: str,
        item_id: str,
        kind: str,
        delta: Any,
    ) -> None:
        self.append(
            LoggedEvent(
                event="item_delta",
                threadId=thread_id,
                turnId=turn_id,
                payload={"itemId": item_id, "kind": kind, "delta": delta},
            )
        )

    def item_completed(self, thread_id: str, turn_id: str, item: Item) -> None:
        self.append(
            LoggedEvent(
                event="item_completed",
                threadId=thread_id,
                turnId=turn_id,
                payload={"item": item.model_dump(by_alias=True, mode="json")},
            )
        )

    # ── Reader side ──────────────────────────────────────────

    def snapshot(self) -> EventLogSnapshot:
        """Capture one immutable prefix of the JSONL file.

        The byte length is fixed before reading. Concurrent appends beyond
        that boundary are never mixed into this snapshot, while a trailing
        partial line stays invisible until a later capture.
        """
        if not self._path.exists():
            return EventLogSnapshot(events=(), cursor=0, stream_id=None)
        with self._path.open("rb") as stream:
            stream.seek(0, 2)
            boundary = stream.tell()
            stream.seek(0)
            raw = stream.read(boundary)

        events: list[tuple[int, LoggedEvent]] = []
        seen_event_ids: set[str] = set()
        cursor = 0
        stream_id: str | None = None
        for sequence, raw_line in enumerate(raw.splitlines(keepends=True), start=1):
            if not raw_line.endswith(b"\n"):
                continue
            cursor = sequence
            try:
                line = raw_line.decode("utf-8").strip()
                if not line:
                    continue
                event = LoggedEvent.model_validate(json.loads(line))
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                continue
            event_id = event.event_id or (
                "legacy:" + hashlib.sha256(raw_line.removesuffix(b"\n")).hexdigest()[:24]
            )
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            if event.event_id is None:
                event = event.model_copy(update={"event_id": event_id})
            if stream_id is None and event.event == "thread_started":
                raw_stream_id = event.payload.get("streamId")
                stream_id = (
                    raw_stream_id if isinstance(raw_stream_id, str) and raw_stream_id else event_id
                )
            events.append((sequence, event))
        return EventLogSnapshot(
            events=tuple(events),
            cursor=cursor,
            stream_id=stream_id,
        )

    def iter_events_with_sequence(self) -> Iterator[tuple[int, LoggedEvent]]:
        """Yield ``(cursor, event)`` pairs in append order.

        The cursor is the one-based physical JSONL line number. That makes it
        stable for every existing log without a migration and monotonic across
        process restarts. Malformed lines consume a cursor but are not yielded;
        a later valid line still advances beyond them.
        """
        yield from self.snapshot().events

    def iter_events(self) -> Iterator[LoggedEvent]:
        """Yield events in append order. Skips malformed lines."""
        for _sequence, event in self.iter_events_with_sequence():
            yield event

    def cursor_delta(
        self,
        after_sequence: int,
        *,
        snapshot: EventLogSnapshot | None = None,
    ) -> tuple[list[str], int, bool]:
        """Return changed turn ids, latest cursor and whether a reset is needed.

        ``turn_compacted`` rewrites the visible turn set, so an incremental
        merge cannot represent it safely; callers receive ``requires_reset``
        and fall back to a normal window snapshot. A cursor beyond the current
        file also signals reset (log replacement/truncation).
        """
        captured = snapshot or self.snapshot()
        changed_turn_ids, requires_reset = captured.cursor_delta(after_sequence)
        return changed_turn_ids, captured.cursor, requires_reset

    def latest_sequence(self, *, snapshot: EventLogSnapshot | None = None) -> int:
        """Return the current append cursor without decoding event payloads."""
        return (snapshot or self.snapshot()).cursor

    def replay(self, snapshot: EventLogSnapshot | None = None) -> list[Turn]:
        """Reconstruct the full turn list from disk.

        After the call you have the same in-memory state the producing
        process held when it last wrote a ``turn_completed`` (or the
        last consistent ``item_*`` if the turn was still running).
        """
        return (snapshot or self.snapshot()).replay()

    @staticmethod
    def paginate_turns(
        turns: list[Turn],
        *,
        limit: int | None = None,
        before_turn_id: str | None = None,
    ) -> tuple[list[Turn], bool]:
        """Newest-window slice of an already-replayed turn list.

        ``before_turn_id`` (exclusive cursor) confines the window to
        turns strictly older than that id; ``limit`` keeps the newest
        N of the window. Returns ``(window, has_more)`` where
        ``has_more`` means turns older than the window exist —
        clients page backwards with ``before_turn_id = window[0].id``.

        No ``limit`` → the full window (back-compat: thread/resume
        without params behaves exactly as before). An unknown cursor
        falls back to the full list rather than guessing.

        Replay still walks the whole JSONL; what pagination saves is
        the model_dump + wire payload + client-side reduce, which is
        where large threads actually hurt.
        """
        window = turns
        if before_turn_id:
            idx = next((i for i, t in enumerate(turns) if t.id == before_turn_id), None)
            if idx is not None:
                window = turns[:idx]
        if limit is None or limit <= 0 or limit >= len(window):
            # Whole window returned — nothing older remains beyond it.
            return window, False
        return window[-limit:], True

    def summary(
        self,
        snapshot: EventLogSnapshot | None = None,
    ) -> ThreadSummary | None:
        """Lightweight metadata snapshot for thread/list responses.

        Walks the file once to compute counts; doesn't materialize
        every Turn. Returns ``None`` if the log file doesn't exist.
        """
        if not self._path.exists():
            return None
        first_ts: datetime | None = None
        last_ts: datetime | None = None
        turn_count = 0
        last_status: TurnStatus | None = None
        archived = False
        captured = snapshot or self.snapshot()
        for _sequence, evt in captured.events:
            if first_ts is None:
                first_ts = evt.ts
            last_ts = evt.ts
            if evt.event == "turn_started":
                turn_count += 1
                last_status = TurnStatus.IN_PROGRESS
            elif evt.event == "turn_completed":
                status_raw = evt.payload.get("status")
                if isinstance(status_raw, str):
                    try:
                        last_status = TurnStatus(status_raw)
                    except ValueError:
                        last_status = None
            elif evt.event == "thread_archived":
                archived = True
        if first_ts is None or last_ts is None:
            return None
        return ThreadSummary(
            thread_id=_thread_id_from_path(self._path),
            path=str(self._path),
            created_at=first_ts,
            updated_at=last_ts,
            turn_count=turn_count,
            last_turn_status=last_status,
            archived=archived,
        )


# ── Directory-level helpers ───────────────────────────────────


class ThreadSummary(BaseModel):
    """Lightweight thread metadata for list views.

    Server emits one ``ThreadSummary`` per thread on a ``thread/list``
    response; the full turn replay only happens when the client picks
    a thread and requests ``thread/resume``.
    """

    model_config = ConfigDict(populate_by_name=True)

    thread_id: str = Field(alias="threadId")
    path: str
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    turn_count: int = Field(alias="turnCount")
    last_turn_status: TurnStatus | None = Field(default=None, alias="lastTurnStatus")
    archived: bool = False


def list_threads(logs_root: Path | str) -> list[ThreadSummary]:
    """Enumerate every thread under ``logs_root`` ordered by recency.

    Skips files that don't parse as a valid thread log. Returns an
    empty list if the directory doesn't exist yet.
    """
    root = Path(logs_root)
    if not root.exists():
        return []
    summaries: list[ThreadSummary] = []
    for path in root.glob("*.jsonl"):
        log = EventLog(path)
        s = log.summary()
        if s is not None:
            summaries.append(s)
    summaries.sort(key=lambda s: s.updated_at, reverse=True)
    return summaries


def archive_thread(logs_root: Path | str, thread_id: str) -> bool:
    """Append a ``thread_archived`` event. Returns True if the thread
    log existed; False otherwise (caller decides whether that's a
    404 or silently OK)."""
    log = EventLog(thread_log_path(logs_root, thread_id))
    if not log.path.exists():
        return False
    log.append(LoggedEvent(event="thread_archived", threadId=thread_id))
    return True


def _thread_id_from_path(path: Path) -> str:
    return path.stem


# ── Replay engine ─────────────────────────────────────────────


_ITEM_BY_TYPE: dict[ItemType, type] = {
    ItemType.USER_MESSAGE: UserMessageItem,
    ItemType.STEERING_USER_MESSAGE: SteeringUserMessageItem,
    ItemType.AGENT_MESSAGE: AgentMessageItem,
    ItemType.REASONING: ReasoningItem,
    ItemType.PLAN: PlanItem,
    ItemType.COMMAND_EXECUTION: CommandExecutionItem,
    ItemType.FILE_CHANGE: FileChangeItem,
    ItemType.MCP_TOOL_CALL: McpToolCallItem,
    ItemType.TODO_LIST: TodoListItem,
    ItemType.SUBAGENT: SubagentItem,
    ItemType.APPROVAL: ApprovalItem,
    ItemType.VERIFICATION: VerificationItem,
    ItemType.ARTIFACT: ArtifactItem,
    ItemType.ERROR: ErrorItem,
}


def _apply_event(
    evt: LoggedEvent,
    turns: list[Turn],
    by_id: dict[str, Turn],
) -> None:
    if evt.event == "thread_started":
        return
    if evt.event == "turn_started":
        params_raw = evt.payload.get("params")
        params = TurnParams.model_validate(params_raw) if params_raw else None
        turn = Turn(
            id=evt.turn_id or "",
            threadId=evt.thread_id,
            status=TurnStatus.IN_PROGRESS,
            startedAt=evt.ts,
            params=params,
        )
        turns.append(turn)
        by_id[turn.id] = turn
        return
    if evt.event == "turn_completed":
        turn = by_id.get(evt.turn_id or "")
        if turn:
            # evt.payload["status"] is a string from JSON ("completed", "failed").
            # Convert to TurnStatus enum properly to avoid Pydantic serializer
            # warnings. Default to COMPLETED if missing/malformed.
            status_str = str(evt.payload.get("status", "completed")).upper()
            try:
                turn.status = TurnStatus[status_str]
            except KeyError:
                turn.status = TurnStatus.COMPLETED
            turn.completed_at = evt.ts
            turn.error = evt.payload.get("error")
        return
    if evt.event == "turn_updated":
        turn = by_id.get(evt.turn_id or "")
        if turn:
            _apply_turn_update(turn, evt.payload)
        return
    if evt.event == "item_started":
        turn = by_id.get(evt.turn_id or "")
        if not turn:
            return
        item = _decode_item(evt.payload.get("item", {}))
        if item is not None:
            _upsert_replayed_item(turn, item, completed=False)
        return
    if evt.event == "item_delta":
        turn = by_id.get(evt.turn_id or "")
        if not turn:
            return
        item_id = evt.payload.get("itemId")
        kind = evt.payload.get("kind")
        delta = evt.payload.get("delta")
        for itm in turn.items:
            if itm.id != item_id:
                continue
            _merge_delta(itm, kind, delta)
            break
        return
    if evt.event == "item_completed":
        turn = by_id.get(evt.turn_id or "")
        if not turn:
            return
        new_item = _decode_item(evt.payload.get("item", {}))
        if new_item is None:
            return
        _upsert_replayed_item(turn, new_item, completed=True)
        return
    if evt.event == "turn_compacted":
        # Compaction replaces a contiguous range of prior turns with a
        # single summary turn. Replay drops the superseded turns and
        # inserts the summary in their place, preserving the original
        # ordering (summary slots where the oldest superseded turn was).
        superseded_ids = evt.payload.get("supersededTurnIds") or []
        if not isinstance(superseded_ids, list):
            return
        summary_raw = evt.payload.get("summaryTurn")
        if not isinstance(summary_raw, dict):
            return
        try:
            summary_turn = Turn.model_validate(summary_raw)
        except (TypeError, ValueError):  # noqa: BLE001
            return
        first_idx: int | None = None
        for idx, t in enumerate(turns):
            if t.id in superseded_ids and first_idx is None:
                first_idx = idx
                break
        keep = [t for t in turns if t.id not in superseded_ids]
        insert_at = first_idx if first_idx is not None else len(keep)
        if insert_at > len(keep):
            insert_at = len(keep)
        keep.insert(insert_at, summary_turn)
        turns[:] = keep
        for sid in superseded_ids:
            by_id.pop(sid, None)
        by_id[summary_turn.id] = summary_turn


def _decode_item(raw: dict[str, Any]) -> Item | None:
    type_str = raw.get("type")
    if not type_str:
        return None
    try:
        item_type = ItemType(type_str)
    except ValueError:
        return None
    cls = _ITEM_BY_TYPE.get(item_type)
    if cls is None:
        return None
    try:
        return cls.model_validate(raw)
    except (TypeError, ValueError):
        return None


def _upsert_replayed_item(turn: Turn, incoming: Item, *, completed: bool) -> None:
    """Idempotently fold a lifecycle snapshot into replay state.

    A completed snapshot may be observed before its delayed started snapshot
    after journal repair or event import. Never regress terminal state, and
    use protocol-authored timeline coordinates rather than append order.
    """
    existing_idx = next(
        (idx for idx, item in enumerate(turn.items) if item.id == incoming.id),
        None,
    )
    if existing_idx is None:
        turn.items.append(incoming)
    else:
        existing = turn.items[existing_idx]
        if not completed and existing.status != ItemStatus.IN_PROGRESS:
            return
        if incoming.timeline_sequence is None:
            incoming.timeline_sequence = existing.timeline_sequence
        if incoming.parent_item_id is None:
            incoming.parent_item_id = existing.parent_item_id
        if incoming.phase_id is None:
            incoming.phase_id = existing.phase_id
        turn.items[existing_idx] = incoming
    _order_replayed_timeline(turn)


def _order_replayed_timeline(turn: Turn) -> None:
    """Sort coordinated item slots while leaving legacy slots untouched."""
    sequenced = sorted(
        (item for item in turn.items if item.timeline_sequence is not None),
        key=lambda item: item.timeline_sequence or 0,
    )
    if len(sequenced) < 2:
        return
    cursor = iter(sequenced)
    turn.items = [
        next(cursor) if item.timeline_sequence is not None else item for item in turn.items
    ]


def _apply_turn_update(turn: Turn, payload: dict[str, Any]) -> None:
    phases_raw = payload.get("phases")
    if isinstance(phases_raw, list):
        phases: list[AgentPhaseSnapshot] = []
        for raw in phases_raw:
            if not isinstance(raw, dict):
                continue
            try:
                phases.append(AgentPhaseSnapshot.model_validate(raw))
            except (TypeError, ValueError):  # noqa: BLE001
                continue
        turn.phases = phases
    if "workspaceFocus" in payload:
        focus_raw = payload.get("workspaceFocus")
        if focus_raw is None:
            turn.workspace_focus = None
        elif isinstance(focus_raw, dict):
            with contextlib.suppress(TypeError, ValueError):
                turn.workspace_focus = WorkspaceFocus.model_validate(focus_raw)
    if "workbenchSnapshot" in payload:
        snapshot_raw = payload.get("workbenchSnapshot")
        if snapshot_raw is None:
            turn.workbench_snapshot = None
        elif isinstance(snapshot_raw, dict):
            with contextlib.suppress(TypeError, ValueError):
                turn.workbench_snapshot = WorkbenchSnapshotV2.model_validate(snapshot_raw)


def _merge_delta(item: Item, kind: str | None, delta: Any) -> None:
    """Apply a delta event in-place. Unknown kinds are ignored.

    The set of (kind, target field) pairs lives here so the rest of the
    codebase doesn't have to know how a given subtype accumulates.
    """
    if kind == "agentMessage" and isinstance(item, AgentMessageItem) and isinstance(delta, str):
        item.text = append_capped_text(
            item.text,
            delta,
            cap=MAX_STREAM_ITEM_CONTENT,
            marker=STREAM_CONTENT_TRUNCATION_MARK,
        )
    elif kind == "reasoning" and isinstance(item, ReasoningItem) and isinstance(delta, str):
        item.content = append_capped_text(
            item.content,
            delta,
            cap=MAX_STREAM_ITEM_CONTENT,
            marker=STREAM_CONTENT_TRUNCATION_MARK,
        )
    elif kind == "plan" and isinstance(item, PlanItem) and isinstance(delta, str):
        item.text = append_capped_text(
            item.text,
            delta,
            cap=MAX_STREAM_ITEM_CONTENT,
            marker=STREAM_CONTENT_TRUNCATION_MARK,
        )
    elif (
        kind == "commandOutput"
        and isinstance(item, CommandExecutionItem)
        and isinstance(delta, str)
    ):
        item.aggregated_output = append_capped_text(
            item.aggregated_output,
            delta,
            cap=MAX_AGGREGATED_OUTPUT,
            marker=OUTPUT_TRUNCATION_MARK,
        )
    elif (
        kind == "mcpToolProgress" and isinstance(item, McpToolCallItem) and isinstance(delta, dict)
    ):
        with contextlib.suppress(TypeError, ValueError):
            item.progress = McpToolProgress.model_validate(delta)
    elif kind == "fileChangeHunk" and isinstance(item, FileChangeItem) and isinstance(delta, dict):
        _merge_file_change_hunk(item, delta)


def _merge_file_change_hunk(item: FileChangeItem, delta: dict[str, Any]) -> None:
    path = delta.get("path")
    op = delta.get("op")
    raw_hunk = delta.get("hunk")
    if (
        not isinstance(path, str)
        or op not in ("create", "update", "delete")
        or not isinstance(raw_hunk, dict)
    ):
        return
    try:
        hunk = FileHunk.model_validate(raw_hunk)
    except (TypeError, ValueError):  # noqa: BLE001
        return
    for change in item.changes:
        if change.path != path:
            continue
        hunks = list(change.hunks)
        for idx, existing in enumerate(hunks):
            if existing.id == hunk.id:
                hunks[idx] = hunk
                change.hunks = hunks
                return
        change.hunks = [*hunks, hunk]
        return
    item.changes.append(FileChange(path=path, op=op, hunks=[hunk]))
    item.status = ItemStatus.IN_PROGRESS


__all__ = [
    "EventKind",
    "EventLog",
    "EventLogSnapshot",
    "LoggedEvent",
    "ThreadSummary",
    "actor_id_from_turn_params",
    "archive_thread",
    "list_threads",
    "owner_actor_id_from_turns",
    "thread_log_path",
    "validate_thread_id",
]
