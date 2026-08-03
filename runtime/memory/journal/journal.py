from __future__ import annotations

import contextlib
import json
from pathlib import Path
from threading import Lock
from typing import Any

from runtime.platform.models import (
    AntigenSignature,
    ArmId,
    CostEntry,
    ImmuneVerdict,
    Source,
    Step,
    TaskId,
    Trajectory,
    new_id,
    now_utc,
)
from runtime.safety.invariants import AppendOnlyList
from runtime.safety.invariants.enforce import enforces

from ._journal_base import Journal
from ._journal_models import (
    CURRENT_SCHEMA_VERSION,
    BrowserArtifactEvent,
    BudgetBreakerResetEvent,
    BudgetEvent,
    CurriculumGoalDecisionEvent,
    FileOpEvent,
    FileRollbackEvent,
    ImmuneEvent,
    JournalEvent,
    JournalEventType,
    McpProposalDecisionEvent,
    NodeStartedEvent,
    PreviewRefreshEvent,
    ProtocolDriftDecisionEvent,
    ReactCheckpointEvent,
    ReflexHitEvent,
    SkillProposalDecisionEvent,
    StepEvent,
    SubToolEndEvent,
    SubToolStartEvent,
    TaskCheckpointEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskStartedEvent,
    TokenUsageEvent,
    ToolEffectIntentEvent,
    ToolEffectReconciliationEvent,
    TrajectoryEvent,
)
from ._journal_parse import _parse_event

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "AntigenSignature",
    "ArmId",
    "CostEntry",
    "ImmuneVerdict",
    "Source",
    "Step",
    "TaskId",
    "Trajectory",
    "new_id",
    "now_utc",
    "Journal",
    "JournalEvent",
    "JournalEventType",
    "StepEvent",
    "TrajectoryEvent",
    "ImmuneEvent",
    "BudgetEvent",
    "BudgetBreakerResetEvent",
    "TaskStartedEvent",
    "NodeStartedEvent",
    "TaskCheckpointEvent",
    "ReactCheckpointEvent",
    "ToolEffectIntentEvent",
    "ToolEffectReconciliationEvent",
    "TaskPausedEvent",
    "TaskResumedEvent",
    "TokenUsageEvent",
    "FileOpEvent",
    "FileRollbackEvent",
    "PreviewRefreshEvent",
    "ReflexHitEvent",
    "SkillProposalDecisionEvent",
    "CurriculumGoalDecisionEvent",
    "McpProposalDecisionEvent",
    "ProtocolDriftDecisionEvent",
    "SubToolStartEvent",
    "SubToolEndEvent",
    "BrowserArtifactEvent",
    "InMemoryJournal",
    "JSONLJournal",
]


# ═══════════════════════════════════════════════════════════
# journal.py · concrete journal implementations.
#
#   §1  InMemoryJournal                                  ~L85
#   §2  JSONLJournal (file-backed, the production impl)  ~L108
#
# Shared building blocks live in sibling submodules:
#   - _journal_models.py — JournalEventType, CURRENT_SCHEMA_VERSION,
#     and every per-event-type Pydantic model (StepEvent, ...).
#   - _journal_base.py   — the abstract ``Journal`` base + all
#     ``write_*`` convenience methods.
#   - _journal_parse.py  — ``_EVENT_CLASSES``, ``_migrate_event``,
#     ``_parse_event`` (schema migration + JSONL parsing).
#
# All public names are re-exported here so ``from
# runtime.memory.journal.journal import ...`` keeps working.
# ═══════════════════════════════════════════════════════════


class InMemoryJournal(Journal):
    def __init__(self) -> None:
        self._events = AppendOnlyList[JournalEvent](rule_id="CC-5")
        self._lock = Lock()

    @enforces("CC-5")
    def write(self, event: JournalEvent) -> None:
        with self._lock:
            self._events.append(event)

    def read_all(self) -> list[JournalEvent]:
        with self._lock:
            return self._events.snapshot()

    def __len__(self) -> int:
        return len(self._events)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class JSONLJournal(Journal):
    def __init__(
        self,
        path: Path | str,
        *,
        max_size_bytes: int | None = None,
        keep_ratio: float = 0.5,
        audit_chain: Any = None,
        redactor: Any = None,
        trace_store: Any = None,
    ) -> None:
        """
        Parameters
        ----------
        path :
            On-disk location for the JSONL file.
        max_size_bytes :
            Optional cap. When the file grows past this, the oldest
            lines are dropped so roughly ``keep_ratio`` of the cap
            worth of most-recent events survive. ``None`` (default)
            disables rotation — the journal grows forever, matching
            older behavior. Recommended ~10-50 MB for a demo setup.
        keep_ratio :
            Fraction of ``max_size_bytes`` retained after a rotation.
            Default 0.5 keeps the last half. Higher = less frequent
            rotation but less headroom before the next one.
        audit_chain :
            Optional ``runtime.safety.audit.audit_chain.AuditChain`` instance.
            When provided, every ``write(event)`` also appends a
            signed record to the chain so tampering with the JSONL
            file (or dropping/reordering lines) is detectable via
            ``audit_chain.verify()``. ``None`` disables audit signing —
            matches the prior default behaviour.
        redactor :
            Optional ``runtime.platform.observability.redactor.Redactor`` instance.
            When provided, the JSON payload is run through
            ``redactor.redact()`` before persistence so accidental
            secrets in tool outputs / args don't land on disk.
            ``None`` (default) disables redaction.
        trace_store :
            Optional ``runtime.memory.diagnostics.trace_store.AgentTraceStore`` sidecar.
            When provided, selected journal events are mirrored into
            SQLite tables for fast audit and recovery queries.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: list[JournalEvent] = []
        self._cache_byte_pos: int = 0
        self._skipped_total: int = 0
        self._max_size_bytes = max_size_bytes
        self._keep_ratio = max(0.1, min(0.9, keep_ratio))
        self._audit_chain = audit_chain
        self._redactor = redactor
        self._trace_store = trace_store

    def attach_trace_store(self, trace_store: Any) -> None:
        """Attach or replace the optional SQLite trace sidecar."""
        self._trace_store = trace_store

    @contextlib.contextmanager
    def _interprocess_lock(self) -> Any:
        """Exclusive cross-process lock on a STABLE sidecar (``<path>.lock``),
        held across BOTH the append and the rotation below.

        Rotation does a ``tmp.replace`` rename, which swaps the journal inode —
        so a per-fd ``flock`` on the journal file itself cannot serialise a
        concurrent worker's append against a rename (the appender ends up
        writing the orphaned inode and its events are lost under
        ``uvicorn --workers N``). Locking a sidecar that is never renamed gives
        every writer a single, stable mutex. Best-effort: degrades to the
        process-internal ``self._lock`` the caller already holds when
        ``fcntl``/``msvcrt`` aren't importable (e.g. a WASM build)."""
        import os as _os

        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            lock_file = lock_path.open("a")
        except OSError:
            yield
            return
        fd = lock_file.fileno()
        locked = False
        try:
            try:
                if _os.name == "nt":
                    import msvcrt as _msvcrt

                    _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                    locked = True
                else:
                    import fcntl as _fcntl

                    _fcntl.flock(fd, _fcntl.LOCK_EX)
                    locked = True
            except (OSError, ImportError):
                locked = False
            yield
        finally:
            if locked:
                try:
                    if _os.name == "nt":
                        import msvcrt as _msvcrt

                        with contextlib.suppress(OSError):
                            lock_file.seek(0)
                        _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl as _fcntl

                        _fcntl.flock(fd, _fcntl.LOCK_UN)
                except OSError:  # best-effort · lock_file.close() below releases it anyway
                    pass
            with contextlib.suppress(OSError):
                lock_file.close()

    @enforces("CC-5")
    def write(self, event: JournalEvent) -> None:
        line = event.model_dump_json()
        # Optional secret/PII scrubbing. Done on the serialised JSON
        # string so we cover every nested ``output`` / ``args`` field
        # without having to walk the Pydantic model. Best-effort: a
        # broken redactor must not block journaling.
        if self._redactor is not None:
            with contextlib.suppress(Exception):
                redacted = self._redactor.redact(line)
                # The redactor's loose patterns (e.g. "phone" matches any
                # run of ~9-15 digits) can hit a digit run inside a JSON
                # *numeric* literal — a float timestamp/latency field —
                # and splice replacement text in there, corrupting the
                # line's JSON syntax (every subsequent read then fails to
                # parse the whole file, silently dropping every event).
                # A real phone number is never a bare JSON number in our
                # schemas — it would be a quoted string — so any match
                # that breaks JSON validity is by definition a false
                # positive; keep the unredacted line rather than persist
                # invalid JSON.
                if redacted != line:
                    try:
                        json.loads(redacted)
                    except (json.JSONDecodeError, ValueError):
                        redacted = line
                line = redacted
        line = line + "\n"
        with self._lock, self._interprocess_lock():
            # Cross-process lock. ``self._lock`` only serialises writers
            # inside this Python process — with ``uvicorn --workers N``
            # two processes can interleave ``write`` + ``flush`` cycles.
            # POSIX ``O_APPEND`` is atomic only for writes ≤ PIPE_BUF
            # (~4 KB); trajectory dumps routinely blow past that. On
            # Windows ``"a"`` mode is never atomic across processes.
            # Wrap the actual ``write/flush`` in an OS-level file lock
            # keyed on the journal path so one writer at a time touches
            # the JSONL. Falls back silently when ``fcntl``/``msvcrt``
            # aren't importable (e.g. WASM build).
            import os as _os

            with self._path.open("a", encoding="utf-8") as f:
                fd = f.fileno()
                _locked = False
                try:
                    if _os.name == "nt":
                        try:
                            import msvcrt as _msvcrt

                            # LK_LOCK: block up to ~10s per attempt, retry
                            # a few times. LK_LOCK retries internally, so
                            # a single call is enough in practice.
                            _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                            _locked = True
                        except OSError:
                            _locked = False
                    else:
                        try:
                            import fcntl as _fcntl

                            _fcntl.flock(fd, _fcntl.LOCK_EX)
                            _locked = True
                        except (OSError, ImportError):
                            _locked = False
                    # Seek to end: another process may have extended the
                    # file since our ``open("a")`` computed the cursor.
                    try:  # noqa: SIM105
                        f.seek(0, 2)
                    except OSError:  # noqa: BLE001 — seek-to-end best-effort; writes still append
                        pass
                    f.write(line)
                    f.flush()
                    try:  # noqa: SIM105
                        _os.fsync(fd)
                    except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                        pass
                finally:
                    if _locked:
                        try:
                            if _os.name == "nt":
                                import msvcrt as _msvcrt

                                # Seek back to the lock byte before unlocking.
                                try:  # noqa: SIM105
                                    f.seek(0, 0)
                                except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                                    pass
                                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
                            else:
                                import fcntl as _fcntl

                                _fcntl.flock(fd, _fcntl.LOCK_UN)
                        except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                            pass
            # Mirror the event into the audit chain. Best-effort —
            # an audit-chain write failure must NOT take down the
            # journal write path (which is on every step).
            if self._audit_chain is not None:
                try:
                    self._audit_chain.append(
                        kind=type(event).__name__,
                        payload={
                            "event_type": getattr(event, "event_type", None),
                            "ts": (
                                event.ts.isoformat()
                                if hasattr(event, "ts") and event.ts is not None
                                else None
                            ),
                        },
                    )
                except Exception:  # noqa: BLE001 — audit mirror is best-effort; never break the hot write path
                    import logging

                    logging.getLogger(__name__).warning(
                        "journal %s: audit chain append failed",
                        self._path,
                    )
            # Rotate if we've blown past the cap. Cheap check (stat
            # call) · only triggers rewrite when actually needed.
            if self._max_size_bytes is not None:
                try:
                    size = self._path.stat().st_size
                except OSError:
                    return
                if size > self._max_size_bytes:
                    self._rotate_locked()
        self._mirror_trace_event(event)

    def _mirror_trace_event(self, event: JournalEvent) -> None:
        if self._trace_store is None:
            return
        try:
            payload = event.model_dump(mode="json")
            task_id = str(event.task_id) if event.task_id is not None else None
            thread_id = str(event.conversation_id or "") or None
            agent_id = str(event.agent_id or "") or None
            ts = event.ts.isoformat() if event.ts is not None else None
            self._trace_store.record_event(
                event_type=str(event.event_type),
                payload=payload,
                thread_id=thread_id,
                task_id=task_id,
                agent_id=agent_id,
                ts=ts,
            )
            if isinstance(event, TokenUsageEvent):
                self._trace_store.record_token_usage(
                    task_id=task_id,
                    thread_id=thread_id,
                    agent_id=agent_id,
                    iteration=event.iteration,
                    model=event.model,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cost_usd=event.cost_usd,
                    ts=ts,
                )
            elif isinstance(event, ReactCheckpointEvent):
                self._trace_store.record_checkpoint(
                    task_id=str(event.task_id or ""),
                    thread_id=thread_id,
                    agent_id=agent_id,
                    checkpoint_type="react",
                    iteration=event.iteration_completed,
                    summary=event.progress_summary,
                    state={
                        "iteration_completed": event.iteration_completed,
                        "max_iterations": event.max_iterations,
                        "messages_snapshot": event.messages_snapshot,
                        "steps_snapshot": event.steps_snapshot,
                        "has_final_answer": event.has_final_answer,
                        "final_answer": event.final_answer,
                        "working_set_snapshot": event.working_set_snapshot,
                        "progress_summary": event.progress_summary,
                        "current_phase": event.current_phase,
                    },
                    ts=ts,
                )
            elif isinstance(event, TaskCheckpointEvent):
                self._trace_store.record_checkpoint(
                    task_id=str(event.task_id or ""),
                    thread_id=thread_id,
                    agent_id=agent_id,
                    checkpoint_type="task",
                    iteration=event.nodes_completed,
                    summary=f"{event.nodes_completed}/{event.total_nodes} nodes",
                    state={
                        "nodes_completed": event.nodes_completed,
                        "total_nodes": event.total_nodes,
                        "tokens_spent": event.tokens_spent,
                        "usd_spent": event.usd_spent,
                    },
                    ts=ts,
                )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug(
                "journal %s: trace mirror failed",
                self._path,
                exc_info=True,
            )

    def _rotate_locked(self) -> None:
        """Trim the file to the last ``keep_ratio * max_size_bytes``
        from the tail (so the most-recent events survive). Caller must
        hold ``self._lock``. Invalidates the incremental read cache
        because byte offsets shift.
        """
        if self._max_size_bytes is None:
            return
        keep_bytes = int(self._max_size_bytes * self._keep_ratio)
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size <= keep_bytes:
            return
        # Read tail + find next newline so we start at a clean line boundary.
        seek_to = size - keep_bytes
        with self._path.open("rb") as f:
            f.seek(seek_to)
            # Skip partial first line
            chunk = f.read()
        nl_idx = chunk.find(b"\n")
        if nl_idx == -1:
            import logging

            logging.getLogger(__name__).warning(
                "journal %s: rotate skipped · no newline in tail",
                self._path,
            )
            return
        tail = chunk[nl_idx + 1 :]
        # Atomic replace: write to .tmp then rename.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(tail)
        tmp.replace(self._path)
        # Invalidate cache · next read_all() reparses from scratch.
        self._cache = []
        self._cache_byte_pos = 0
        self._skipped_total = 0
        import logging

        logging.getLogger(__name__).info(
            "journal %s rotated · kept tail %d bytes (was %d)",
            self._path,
            len(tail),
            size,
        )

    def read_all(self) -> list[JournalEvent]:
        with self._lock:
            if not self._path.exists():
                # File gone entirely → reset cache (a fresh file may
                # appear later and we want to parse it from scratch).
                self._cache = []
                self._cache_byte_pos = 0
                return []

            file_size = self._path.stat().st_size
            if file_size == self._cache_byte_pos:
                # Nothing new — hand back cached list (shallow copy so
                # caller mutations don't poison the cache).
                return list(self._cache)
            if file_size < self._cache_byte_pos:
                # File shrank (manual truncate / rotation) → invalidate.
                self._cache = []
                self._cache_byte_pos = 0
                self._skipped_total = 0

            # Read only the tail that's new since last parse. Using
            # binary mode + seek avoids decoder issues when a multi-byte
            # char straddles a read boundary — we read to the current
            # end-of-file which always aligns to a line boundary in
            # append-only usage.
            with self._path.open("rb") as f:
                f.seek(self._cache_byte_pos)
                new_bytes = f.read()
                new_pos = self._cache_byte_pos + len(new_bytes)

            new_text = new_bytes.decode("utf-8", errors="replace")
            for _lineno_offset, raw in enumerate(new_text.splitlines(), 1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    self._cache.append(_parse_event(line))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    self._skipped_total += 1
                    if self._skipped_total == 1:
                        import logging

                        logging.getLogger(__name__).warning(
                            "journal %s: unparseable event %s at "
                            "byte ~%d · skipping (and any subsequent)",
                            self._path,
                            type(exc).__name__,
                            self._cache_byte_pos,
                        )
            self._cache_byte_pos = new_pos
            return list(self._cache)

    def __len__(self) -> int:
        if not self._path.exists():
            return 0
        with self._path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)
