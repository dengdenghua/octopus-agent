from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID

from pydantic import BaseModel

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
from runtime.safety.auth.scope import TenantScope
from runtime.safety.invariants import AppendOnlyList
from runtime.safety.invariants.enforce import enforces

from ._chunk_rows import (
    MIN_RUN,
    chunk_packing_enabled,
    classify_chunk,
    continues_chunk_run,
    expand_chunk_row,
    is_chunk_row,
    pack_chunk_row,
)
from ._journal_base import Journal
from ._journal_models import (
    CURRENT_SCHEMA_VERSION,
    AssistantChunkEvent,
    BrowserArtifactEvent,
    BudgetBreakerResetEvent,
    BudgetEvent,
    CurriculumGoalDecisionEvent,
    FileOpEvent,
    FileRollbackEvent,
    HookInvokedEvent,
    HookResultEvent,
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
    SubSessionSummaryEvent,
    SubTextDeltaEvent,
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
from ._journal_parse import _parse_event, _parse_event_data


def _lock_windows_fd(fd: int, mode_name: str) -> None:
    """Call the Windows-only ``msvcrt.locking`` API without making POSIX
    type-checking depend on attributes absent from its platform stubs."""

    import msvcrt

    namespace = vars(msvcrt)
    namespace["locking"](fd, namespace[mode_name], 1)


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
    "AssistantChunkEvent",
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
    "HookInvokedEvent",
    "HookResultEvent",
    "PreviewRefreshEvent",
    "ReflexHitEvent",
    "SkillProposalDecisionEvent",
    "CurriculumGoalDecisionEvent",
    "McpProposalDecisionEvent",
    "ProtocolDriftDecisionEvent",
    "SubSessionSummaryEvent",
    "SubTextDeltaEvent",
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


def _refresh_session_index(
    index: dict[str, list[JournalEvent]],
    events: list[JournalEvent],
    upto: int,
) -> None:
    """Extend a per-session index with events past ``upto`` (audit P-04)."""
    for event in events[upto:]:
        sid = str(getattr(event, "session_id", "") or "")
        if sid:
            index.setdefault(sid, []).append(event)


class _StructuredJournalRedaction:
    """Structured, identity-preserving redaction shared by file journals."""

    @staticmethod
    def _scope_digest(value: str, *, field: str) -> str:
        """Return a deterministic storage identifier outside PII patterns."""

        digest = hashlib.sha256(f"octopus-journal-scope-v1\0{field}\0{value}".encode()).hexdigest()
        letters_only = digest.translate(str.maketrans("0123456789", "ghijklmnop"))
        return f"octopus-scope-{field}-vone-{letters_only}"

    def _storage_scope_value(self, value: str | None, *, field: str) -> str | None:
        if value is None or self._redactor is None:
            return value
        text = str(value)
        if text.startswith(f"octopus-scope-{field}-vone-"):
            return text
        try:
            redacted = self._redactor.redact(text)
        except Exception:  # noqa: BLE001 - a broken optional redactor is best-effort
            return text
        if redacted == text:
            return text
        return self._scope_digest(text, field=field)

    def _storage_scoped_event(self, event: JournalEvent) -> JournalEvent:
        tenant_id = self._storage_scope_value(event.tenant_id, field="tenant")
        owner_actor_id = self._storage_scope_value(event.owner_actor_id, field="owner")
        if tenant_id == event.tenant_id and owner_actor_id == event.owner_actor_id:
            return event
        return event.model_copy(update={"tenant_id": tenant_id, "owner_actor_id": owner_actor_id})

    @staticmethod
    def _is_redaction_protected_model_field(field_name: str, field_value: Any) -> bool:
        if field_name in {"tenant_id", "owner_actor_id"}:
            return False
        return bool(
            field_name in {"schema_version", "event_type", "effect_key", "args_fingerprint"}
            or field_name.endswith(("_fingerprint", "_hash"))
            or isinstance(field_value, (UUID, date, datetime, Enum))
        )

    @classmethod
    def _restore_redaction_protected_model_fields(
        cls,
        model: Any,
        original: Any,
        redacted: Any,
    ) -> Any:
        if isinstance(model, BaseModel):
            if not isinstance(original, dict) or not isinstance(redacted, dict):
                return redacted
            restored = dict(redacted)
            for field_name in type(model).model_fields:
                if field_name not in original:
                    continue
                field_value = getattr(model, field_name, None)
                if cls._is_redaction_protected_model_field(field_name, field_value):
                    restored[field_name] = original[field_name]
                elif field_name in redacted:
                    restored[field_name] = cls._restore_redaction_protected_model_fields(
                        field_value,
                        original[field_name],
                        redacted[field_name],
                    )
            return restored
        if isinstance(model, (list, tuple)):
            if not isinstance(original, list) or not isinstance(redacted, list):
                return redacted
            return [
                cls._restore_redaction_protected_model_fields(item, original_item, redacted_item)
                for item, original_item, redacted_item in zip(
                    model, original, redacted, strict=False
                )
            ]
        if isinstance(model, dict):
            if not isinstance(original, dict) or not isinstance(redacted, dict):
                return redacted
            restored = dict(redacted)
            for key, item in model.items():
                if key in original and key in redacted:
                    restored[key] = cls._restore_redaction_protected_model_fields(
                        item, original[key], redacted[key]
                    )
            return restored
        return redacted

    def _redact_json_string_values(self, value: Any) -> Any:
        if self._redactor is None:
            return value
        if isinstance(value, str):
            try:
                redacted = self._redactor.redact(value)
            except Exception:  # noqa: BLE001 - optional redaction remains best-effort
                return value
            return redacted if isinstance(redacted, str) else value
        if isinstance(value, list):
            return [self._redact_json_string_values(item) for item in value]
        if isinstance(value, dict):
            return {key: self._redact_json_string_values(item) for key, item in value.items()}
        return value

    @classmethod
    def _string_redaction_changes(
        cls,
        original: Any,
        redacted: Any,
        path: tuple[str | int, ...] = (),
    ) -> list[tuple[tuple[str | int, ...], str]]:
        if isinstance(original, str) and isinstance(redacted, str):
            return [] if original == redacted else [(path, redacted)]
        if isinstance(original, list) and isinstance(redacted, list):
            changes: list[tuple[tuple[str | int, ...], str]] = []
            for index, (original_item, redacted_item) in enumerate(
                zip(original, redacted, strict=False)
            ):
                changes.extend(
                    cls._string_redaction_changes(original_item, redacted_item, (*path, index))
                )
            return changes
        if isinstance(original, dict) and isinstance(redacted, dict):
            changes = []
            for key, original_item in original.items():
                if key in redacted:
                    changes.extend(
                        cls._string_redaction_changes(original_item, redacted[key], (*path, key))
                    )
            return changes
        return []

    @classmethod
    def _replace_json_path(
        cls,
        value: Any,
        path: tuple[str | int, ...],
        replacement: str,
    ) -> Any:
        if not path:
            return replacement
        head, *tail = path
        if isinstance(head, int) and isinstance(value, list):
            updated = list(value)
            updated[head] = cls._replace_json_path(updated[head], tuple(tail), replacement)
            return updated
        if isinstance(head, str) and isinstance(value, dict):
            updated = dict(value)
            updated[head] = cls._replace_json_path(updated[head], tuple(tail), replacement)
            return updated
        return value

    @staticmethod
    def _dump_json_payload(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _serialized_event_keeps_structure(event: JournalEvent, line: str) -> bool:
        try:
            durable_event = _parse_event(line)
        except (TypeError, ValueError):
            return False
        return bool(
            durable_event.event_id == event.event_id
            and durable_event.event_type == event.event_type
            and durable_event.task_id == event.task_id
            and durable_event.arm_id == event.arm_id
            and durable_event.tenant_id == event.tenant_id
            and durable_event.owner_actor_id == event.owner_actor_id
            and durable_event.ts == event.ts
            and durable_event.source == event.source
        )

    def _visible(self, event: JournalEvent, scope: TenantScope | None) -> bool:
        if scope is None or scope.allow_cross_tenant:
            return True
        tenant_ids = {
            scope.tenant_id,
            self._storage_scope_value(scope.tenant_id, field="tenant"),
        }
        owner_actor_ids = {
            scope.actor_id,
            self._storage_scope_value(scope.actor_id, field="owner"),
        }
        return bool(
            event.tenant_id
            and event.owner_actor_id
            and event.tenant_id in tenant_ids
            and event.owner_actor_id in owner_actor_ids
        )


class InMemoryJournal(Journal):
    def __init__(self, max_events: int = 0) -> None:
        """In-memory journal with an optional oldest-event eviction cap."""

        self._events = AppendOnlyList[JournalEvent](rule_id="CC-5")
        self._max_events = max(0, int(max_events))
        self._lock = Lock()
        self._session_index: dict[str, list[JournalEvent]] = {}
        self._session_index_upto = 0

    @enforces("CC-5")
    def _append(self, event: JournalEvent) -> None:
        self._events.append(event)

    def write(self, event: JournalEvent) -> None:
        event = self._apply_context(event)
        with self._lock:
            self._append(event)
            if self._max_events > 0:
                overflow = len(self._events) - self._max_events
                if overflow > 0:
                    self._events.drop_oldest(overflow)

    def read_all(self, *, scope: TenantScope | None = None) -> list[JournalEvent]:
        with self._lock:
            events = self._events.snapshot()
        return [event for event in events if self._visible(event, scope)]

    def read_by_session(self, session_id: str) -> list[JournalEvent]:
        with self._lock:
            events = self._events.snapshot()
            _refresh_session_index(self._session_index, events, self._session_index_upto)
            self._session_index_upto = len(events)
            return list(self._session_index.get(session_id, ()))

    def __len__(self) -> int:
        return len(self._events)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class JSONLJournal(_StructuredJournalRedaction, Journal):
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
        # Buffered chunk run awaiting packing (list of (entry, event) pairs).
        self._pending_chunk_run: list[tuple[dict, JournalEvent]] | None = None
        # Audit P-04: incremental per-session index (built from the parsed
        # cache; reset automatically when the file rotates/truncates).
        self._session_index: dict[str, list[JournalEvent]] = {}
        self._session_index_upto = 0

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
                    _lock_windows_fd(fd, "LK_LOCK")
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
                        with contextlib.suppress(OSError):
                            lock_file.seek(0)
                        _lock_windows_fd(fd, "LK_UNLCK")
                    else:
                        import fcntl as _fcntl

                        _fcntl.flock(fd, _fcntl.LOCK_UN)
                except OSError:  # best-effort · lock_file.close() below releases it anyway
                    pass
            with contextlib.suppress(OSError):
                lock_file.close()

    @enforces("CC-5")
    def write(self, event: JournalEvent) -> None:
        event = self._storage_scoped_event(self._apply_context(event))
        with self._lock:
            entry = classify_chunk(event)
            if entry is not None and chunk_packing_enabled():
                # Defer the file write: hold the chunk run in memory so a
                # run of token-sized deltas lands as ONE packed storage row
                # (dsh ``chunk-rows``). Any non-chunk event, an explicit
                # read, or a run break flushes it first — so at most the
                # trailing chunk run is buffered at any moment.
                run = self._pending_chunk_run
                if run is not None and continues_chunk_run(run[-1][0], entry):
                    run.append((entry, event))
                else:
                    self._flush_pending_chunks_locked()
                    self._pending_chunk_run = [(entry, event)]
                return
            self._flush_pending_chunks_locked()
            self._append_event_locked(event)

    def canonicalize_event(self, event: JournalEvent) -> JournalEvent:
        """Return the exact scoped and redacted event accepted by storage."""

        with self._lock:
            durable_event, _line = self._canonicalize_event_locked(event)
            return durable_event

    def _append_event_locked(self, event: JournalEvent) -> None:
        """Serialize + redact + append + mirror one event.

        Caller must hold ``self._lock`` (the interprocess lock is taken
        inside ``_append_raw_locked``).
        """
        durable_event, line = self._canonicalize_event_locked(event)
        self._append_raw_locked(line + "\n")
        self._mirror_event_effects(durable_event)

    def _canonicalize_event_locked(self, event: JournalEvent) -> tuple[JournalEvent, str]:
        scoped_event = self._storage_scoped_event(self._apply_context(event))
        line = self._serialize_event_locked(scoped_event)
        durable_event = _parse_event(line)
        if not self._serialized_event_keeps_structure(scoped_event, line):
            raise ValueError("serialized journal event changed structural identity")
        return durable_event, line

    def _serialize_event_locked(self, event: JournalEvent) -> str:
        original_payload = event.model_dump(mode="json")
        original_line = self._dump_json_payload(original_payload)
        if self._redactor is None:
            return original_line

        redacted_payload = self._redact_json_string_values(original_payload)
        redacted_payload = self._restore_redaction_protected_model_fields(
            event,
            original_payload,
            redacted_payload,
        )
        if redacted_payload == original_payload:
            return original_line

        candidate_line = self._dump_json_payload(redacted_payload)
        if self._serialized_event_keeps_structure(event, candidate_line):
            return candidate_line

        # Preserve each independently valid payload redaction while rejecting
        # only replacements that would mutate the journal schema or identity.
        accepted_payload = original_payload
        for path, replacement in self._string_redaction_changes(
            original_payload,
            redacted_payload,
        ):
            trial_payload = self._replace_json_path(accepted_payload, path, replacement)
            trial_line = self._dump_json_payload(trial_payload)
            if self._serialized_event_keeps_structure(event, trial_line):
                accepted_payload = trial_payload
        return self._dump_json_payload(accepted_payload)

    def _append_raw_locked(self, line: str) -> None:
        """Append one storage line under the interprocess lock, then rotate.

        Caller must hold ``self._lock``. ``self._interprocess_lock()``
        serialises writers across processes — with ``uvicorn --workers N``
        two processes can interleave ``write`` + ``flush`` cycles.
        POSIX ``O_APPEND`` is atomic only for writes ≤ PIPE_BUF (~4 KB);
        trajectory dumps routinely blow past that. On Windows ``"a"``
        mode is never atomic across processes. Wrap the actual
        ``write/flush`` in an OS-level file lock keyed on the journal
        path so one writer at a time touches the JSONL. Falls back
        silently when ``fcntl``/``msvcrt`` aren't importable (e.g. WASM).
        """
        with self._interprocess_lock():
            import os as _os

            with self._path.open("a", encoding="utf-8") as f:
                fd = f.fileno()
                _locked = False
                try:
                    if _os.name == "nt":
                        try:
                            # LK_LOCK: block up to ~10s per attempt, retry
                            # a few times. LK_LOCK retries internally, so
                            # a single call is enough in practice.
                            _lock_windows_fd(fd, "LK_LOCK")
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
                                # Seek back to the lock byte before unlocking.
                                try:  # noqa: SIM105
                                    f.seek(0, 0)
                                except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                                    pass
                                _lock_windows_fd(fd, "LK_UNLCK")
                            else:
                                import fcntl as _fcntl

                                _fcntl.flock(fd, _fcntl.LOCK_UN)
                        except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                            pass
            # Rotate if we've blown past the cap — still under the
            # interprocess lock so a rename can't race another process's
            # append to the old inode (data-loss window on rotation).
            if self._max_size_bytes is not None:
                try:
                    size = self._path.stat().st_size
                except OSError:
                    return
                if size > self._max_size_bytes:
                    self._rotate_locked()

    def _mirror_event_effects(self, event: JournalEvent) -> None:
        """Best-effort side mirrors (audit chain + trace store) for one event.

        Runs at flush time so the chain's order matches the file's line
        order. A mirror failure must NOT take down the journal write
        path (which is on every step).
        """
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
        self._mirror_trace_event(event)

    def _flush_pending_chunks_locked(self) -> None:
        """Flush the buffered chunk run: one packed row, or verbatim lines.

        Caller must hold ``self._lock``. A run of ``>= MIN_RUN``
        consecutive chunks writes a single packed row (lossless on
        read); shorter runs fall back to per-event lines. Every member
        still gets its audit/trace mirror at flush time.
        """
        run = self._pending_chunk_run
        if not run:
            return
        self._pending_chunk_run = None
        if len(run) >= MIN_RUN:
            durable_events: list[JournalEvent] = []
            durable_entries: list[dict[str, Any]] = []
            for _entry, event in run:
                durable_event, _line = self._canonicalize_event_locked(event)
                durable_entry = classify_chunk(durable_event)
                if durable_entry is None or (
                    durable_entries and not continues_chunk_run(durable_entries[-1], durable_entry)
                ):
                    for _fallback_entry, fallback_event in run:
                        self._append_event_locked(fallback_event)
                    return
                durable_events.append(durable_event)
                durable_entries.append(durable_entry)

            row = pack_chunk_row(durable_entries)
            line = json.dumps(row, ensure_ascii=False)
            self._append_raw_locked(line + "\n")
            for event in durable_events:
                self._mirror_event_effects(event)
        else:
            for _entry, event in run:
                self._append_event_locked(event)

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
                tenant_id=str(event.tenant_id or "") or None,
                owner_actor_id=str(event.owner_actor_id or event.actor or "") or None,
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
                    tenant_id=str(event.tenant_id or "") or None,
                    owner_actor_id=str(event.owner_actor_id or event.actor or "") or None,
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
                    tenant_id=str(event.tenant_id or "") or None,
                    owner_actor_id=str(event.owner_actor_id or event.actor or "") or None,
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
                    tenant_id=str(event.tenant_id or "") or None,
                    owner_actor_id=str(event.owner_actor_id or event.actor or "") or None,
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

    def read_all(self, *, scope: TenantScope | None = None) -> list[JournalEvent]:
        with self._lock:
            # Make buffered chunk runs visible to readers: flush them to
            # disk first so the cache is always a complete prefix.
            self._flush_pending_chunks_locked()
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
                events = list(self._cache)
                return [event for event in events if self._visible(event, scope)]
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
                    data = json.loads(line)
                    if is_chunk_row(data):
                        # Packed storage row (dsh chunk-rows): expand to the
                        # exact original events, same ids and timestamps.
                        for event_data in expand_chunk_row(data):
                            self._cache.append(_parse_event_data(event_data))
                    else:
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
            events = list(self._cache)
            return [event for event in events if self._visible(event, scope)]

    def read_by_session(self, session_id: str) -> list[JournalEvent]:
        # Ensure the parsed cache includes the latest file tail (read_all
        # flushes pending chunk runs and reads only the new delta).
        self.read_all()
        with self._lock:
            events = list(self._cache)
            if self._session_index_upto > len(events):
                # File rotated/truncated — the old offsets are stale; rebuild.
                self._session_index = {}
                self._session_index_upto = 0
            _refresh_session_index(self._session_index, events, self._session_index_upto)
            self._session_index_upto = len(events)
            return list(self._session_index.get(session_id, ()))

    def __len__(self) -> int:
        # Event count, not line count: a packed chunk row is one line but
        # N events. ``read_all`` flushes the pending run, so this is exact.
        return len(self.read_all())
