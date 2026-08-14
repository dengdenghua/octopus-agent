"""Durable subagent sessions — dsh ``continuable`` child conversations.

dsh's continuable subagent keeps a durable child transcript keyed by a
``subagentId``; the parent can send the child more work and the child owns
its own turns. This module provides the storage half of that contract:

- one durable session per subagent conversation (JSONL file per session,
  atomic write via tmp+rename),
- ``create`` / ``get`` / ``append_turn`` vocabulary,
- ``transcript_prompt`` renders the prior turns as a bounded markdown
  prefix so the next call can continue without re-reading the transcript
  from scratch (mirrors dsh ``send_message`` semantics at the prompt level).

The store is best-effort by design: when no base directory can be resolved
the singleton falls back to in-memory so callers never crash because
persistence is unavailable.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)

MAX_TRANSCRIPT_TURNS = 6
MAX_TRANSCRIPT_CHARS = 6000
MAX_REPORTS_PROMPT_CHARS = 4000
# dsh session-reference projection: when enabled, the continuation transcript
# is a byte-bounded current-surface snapshot (exact ``[… omitted N bytes …]``
# notice + retention stats) instead of the per-turn head-truncated markdown.
# Off by default (dsh hosts opt into the session-reference service).
TRANSCRIPT_PROJECTION_ENABLED = os.environ.get("OCTOPUS_SESSION_REFERENCE_BOUNDED", "0") != "0"
MAX_TRANSCRIPT_PROJECTION_BYTES = 16000

# dsh ``tool-jobs`` bounded consecutive-wake budget: how many wakeup reports
# may open a parent turn in a row before the lane goes quiet. Mirrors dsh
# ``maxConsecutiveWakes`` (default 3): a completion on an idle owner wakes it
# only while the budget is unspent; once exhausted, further reports are
# queued as ``quiet`` until the parent claims a human turn and refills the
# budget. Without it a chatty child could spin an unbounded chain of parent
# turns between human inputs.
DEFAULT_MAX_CONSECUTIVE_WAKES = 3


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z"


@dataclass
class SubagentSessionTurn:
    prompt: str
    output: str
    success: bool
    rounds: int = 0
    error: str = ""
    timestamp: str = field(default_factory=_utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubagentSessionTurn:
        return cls(
            prompt=str(data.get("prompt") or ""),
            output=str(data.get("output") or ""),
            success=bool(data.get("success", False)),
            rounds=int(data.get("rounds") or 0),
            error=str(data.get("error") or ""),
            timestamp=str(data.get("timestamp") or _utc_now_iso()),
        )


@dataclass
class SubagentReport:
    """One child→parent delivery (dsh ``tool-subagent-report``).

    ``delivery`` mirrors dsh ``reportDelivery``: ``wakeup`` (default)
    schedules a parent turn so the report is not missed, ``quiet`` only
    adds context that the parent sees on its next wake, ``queued`` means
    the parent was busy when the report landed so it was injected into the
    running turn's queue instead of waking a second turn.
    """

    content: str
    delivery: Literal["wakeup", "quiet", "queued"] = "wakeup"
    timestamp: str = field(default_factory=_utc_now_iso)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubagentReport:
        return cls(
            content=str(data.get("content") or ""),
            delivery=_normalize_report_delivery(data.get("delivery")),
            timestamp=str(data.get("timestamp") or _utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "delivery": self.delivery,
            "timestamp": self.timestamp,
        }


@dataclass
class SubagentSession:
    session_id: str
    agent_id: str
    thread_id: str
    created_at: str
    updated_at: str
    turns: list[SubagentSessionTurn] = field(default_factory=list)
    reports: list[SubagentReport] = field(default_factory=list)
    reports_delivered_up_to: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubagentSession:
        turns = [
            SubagentSessionTurn.from_dict(item)
            for item in data.get("turns") or []
            if isinstance(item, dict)
        ]
        return cls(
            session_id=str(data.get("session_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            thread_id=str(data.get("thread_id") or ""),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            turns=turns,
            reports=[
                SubagentReport.from_dict(item)
                for item in data.get("reports") or []
                if isinstance(item, dict)
            ],
            reports_delivered_up_to=int(data.get("reports_delivered_up_to") or 0),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "thread_id": self.thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [asdict(turn) for turn in self.turns],
            "reports": [asdict(report) for report in self.reports],
            "reports_delivered_up_to": self.reports_delivered_up_to,
        }


def _default_base_dir() -> Path | None:
    try:
        from runtime.platform.process.paths import app_paths

        return app_paths().data_dir / "subagent_sessions"
    except Exception:  # noqa: BLE001 - persistence is best-effort
        return None


class SubagentSessionStore:
    """File-backed store of durable subagent sessions.

    ``base_dir=None`` resolves the runtime data dir; when even that fails
    the store degrades to in-memory so callers stay functional.
    """

    def __init__(
        self,
        base_dir: str | Path | None = None,
        *,
        on_report: Callable[[str, SubagentReport], None] | None = None,
        max_consecutive_wakes: int | None = None,
    ) -> None:
        self._base_dir: Path | None = None
        if base_dir is not None:
            self._base_dir = Path(base_dir)
        else:
            self._base_dir = _default_base_dir()
        self._memory: dict[str, SubagentSession] = {}
        self._lock = threading.RLock()
        # Optional wakeup hook (dsh ``reportDelivery: 'wakeup'``): called with
        # (session_id, report) after a report lands so a parent scheduler can
        # plan a turn. Best-effort — a failing hook never breaks the report.
        self._on_report = on_report
        # Bounded consecutive-wake budget (dsh ``tool-jobs.maxConsecutiveWakes``).
        # A wakeup report only opens a parent turn while this budget is unspent;
        # exhausted wakes drop the report to ``quiet`` until a human turn refills
        # it. A fraction never names a turn; ``Infinity`` would be unbounded.
        budget = (
            DEFAULT_MAX_CONSECUTIVE_WAKES
            if max_consecutive_wakes is None
            else max_consecutive_wakes
        )
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
            raise ValueError(
                f"SubagentSessionStore: max_consecutive_wakes ({budget!r}) "
                "must be a non-negative integer"
            )
        self._max_consecutive_wakes = budget
        # Per-session spent wakes since the parent last claimed a human turn.
        self._spent_wakes: dict[str, int] = {}
        # Parent owners currently mid-turn (dsh ``agent.status === 'running'``).
        # Live state only — a store restart always starts owners idle, matching
        # dsh's restart-into-idle lifecycle.
        self._owner_busy: set[str] = set()
        # Threads whose parent turn is running (dsh ``agent.status`` keyed by
        # the parent thread instead of one exact session). Also live-only; the
        # react-loop driver marks its thread busy for the turn's duration so a
        # report landing mid-turn queues for every session that thread owns,
        # including ones created during the turn.
        self._busy_threads: set[str] = set()

    def _path_for(self, session_id: str) -> Path | None:
        if self._base_dir is None:
            return None
        if not _VALID_SESSION_ID_RE.fullmatch(session_id):
            return None
        return self._base_dir / f"{session_id}.json"

    def create(self, *, agent_id: str, thread_id: str = "") -> SubagentSession:
        now = _utc_now_iso()
        session = SubagentSession(
            session_id=uuid4().hex,
            agent_id=agent_id,
            thread_id=thread_id,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._memory[session.session_id] = session
            self._spent_wakes.pop(session.session_id, None)
            self._owner_busy.discard(session.session_id)
            self._write_locked(session)
        return session

    def get(self, session_id: str) -> SubagentSession | None:
        with self._lock:
            cached = self._memory.get(session_id)
            if cached is not None:
                return _copy_session(cached)
            path = self._path_for(session_id)
            if path is None or not path.exists():
                return None
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session = SubagentSession.from_dict(data) if isinstance(data, dict) else None
            except (OSError, ValueError, TypeError):
                logger.warning("subagent session %s unreadable", session_id, exc_info=True)
                return None
            if session is None or not session.session_id:
                return None
            self._memory[session.session_id] = session
            return _copy_session(session)

    def surface_events(self, session_id: str) -> list[dict[str, Any]]:
        """The dsh surface-event shape for one session (session-reference input).

        Mirrors dsh ``sessionQuery.readSurface`` for a subagent session: the
        user/assistant turns are surfaced as ``user/message`` +
        ``assistant/message`` events so ``session_reference.prepare`` can
        project them. An unknown session returns an empty surface.
        """
        session = self.get(session_id)
        if session is None:
            return []
        return _surface_events_from_turns(session)

    def list_reference_candidates(
        self,
        *,
        target_id: str,
        query: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List subagent sessions as reference candidates (dsh listCandidates).

        Returns candidate dicts (``session_id`` / ``label`` / ``created_at``)
        for sessions other than ``target_id``, ranked by the resolver's
        working-directory affinity and filtered by an optional
        case-insensitive id / label substring.
        """
        from runtime.execution.tool_engine.session_reference import (
            SessionReferenceRecord,
            SessionReferenceResolver,
        )

        records: list[SessionReferenceRecord] = []
        with self._lock:
            for session in self._memory.values():
                records.append(
                    SessionReferenceRecord(
                        session_id=session.session_id,
                        label=session.agent_id or session.session_id,
                        created_at=int(session.created_at[:10].replace("-", ""))
                        if len(session.created_at) >= 10
                        else None,
                    )
                )
        resolver = SessionReferenceResolver()
        return [
            {
                "sessionId": candidate.session_id,
                "label": candidate.label,
                "createdAt": candidate.created_at,
            }
            for candidate in resolver.list_candidates(
                target_id=target_id,
                sessions=records,
                query=query,
                limit=limit,
            )
        ]

    def append_turn(
        self,
        session_id: str,
        *,
        prompt: str,
        output: str,
        success: bool,
        rounds: int = 0,
        error: str = "",
    ) -> SubagentSession | None:
        with self._lock:
            session = self.get(session_id)
            if session is None:
                return None
            session.turns.append(
                SubagentSessionTurn(
                    prompt=prompt,
                    output=output,
                    success=success,
                    rounds=rounds,
                    error=error,
                )
            )
            session.updated_at = _utc_now_iso()
            self._memory[session.session_id] = session
            self._write_locked(session)
            return _copy_session(session)

    def _write_locked(self, session: SubagentSession) -> None:
        path = self._path_for(session.session_id)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{session.session_id}.",
                suffix=".tmp",
                dir=str(path.parent),
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp_name, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                raise
        except OSError:
            logger.warning("subagent session %s write failed", session.session_id, exc_info=True)

    def append_report(
        self,
        session_id: str,
        *,
        content: str,
        delivery: Literal["wakeup", "quiet"] = "wakeup",
    ) -> SubagentSession | None:
        """Persist one child→parent report (dsh ``tool-subagent-report``).

        ``delivery`` mirrors dsh ``reportDelivery``: ``wakeup`` (default)
        schedules a parent turn via the optional ``on_report`` hook, ``quiet``
        only adds context the parent sees on its next wake. A ``wakeup`` report
        opens a parent turn only when the owner is idle AND the consecutive-wake
        budget is unspent (dsh ``maxConsecutiveWakes``): a busy owner is
        injected as ``queued`` without spending budget (dsh ``inject`` — the
        running turn claims it at its next boundary), and an exhausted budget
        degrades to ``quiet`` so a chatty child cannot spin an unbounded chain
        of parent turns. An empty content is rejected (dsh requires a
        self-contained result).
        """
        if not isinstance(content, str) or not content.strip():
            raise ValueError("subagent report content must be non-empty")
        with self._lock:
            session = self.get(session_id)
            if session is None:
                return None
            effective_delivery = "wakeup" if delivery != "quiet" else "quiet"
            if effective_delivery == "wakeup":
                owner_busy = session_id in self._owner_busy or bool(
                    session.thread_id and session.thread_id in self._busy_threads
                )
                if owner_busy:
                    # dsh ``inject``: a busy owner must not be woken mid-turn;
                    # the report waits in the running turn's queue and neither
                    # fires the hook nor spends the wake budget.
                    effective_delivery = "queued"
                elif self._spent_wakes.get(session_id, 0) >= self._max_consecutive_wakes:
                    effective_delivery = "quiet"
                else:
                    # The budget is spent the moment we decide to wake — a
                    # concurrent or repeated report must not re-wake the parent.
                    # Mirrors dsh ``spentWakes.set(owner, spent + 1)``.
                    self._spent_wakes[session_id] = (
                        self._spent_wakes.get(session_id, 0) + 1
                    )
            report = SubagentReport(
                content=content.strip(),
                delivery=effective_delivery,
            )
            session.reports.append(report)
            session.updated_at = _utc_now_iso()
            self._memory[session.session_id] = session
            self._write_locked(session)
            delivered = _copy_session(session)
        # A wake fires only when the report actually woke the parent (budget
        # allowed) — a budget-exhausted downgrade stays quiet.
        if effective_delivery == "wakeup" and self._on_report is not None:
            try:
                self._on_report(session_id, report)
            except Exception:  # noqa: BLE001 — notification is best-effort
                logger.warning("subagent report wakeup hook failed", exc_info=True)
        return delivered

    def mark_owner_busy(self, session_id: str) -> None:
        """Mark the parent owner mid-turn (dsh ``agent.status === 'running'``).

        While busy, a ``wakeup`` report is injected as ``queued`` instead of
        waking a second turn over an in-flight one. Live state only: a store
        restart starts every owner idle. Unknown sessions are a no-op.
        """
        with self._lock:
            if session_id in self._memory or self._path_for(session_id) is not None:
                self._owner_busy.add(session_id)

    def mark_owner_idle(self, session_id: str) -> None:
        """Mark the parent owner idle again (dsh ``agent.status === 'idle'``).

        The next ``wakeup`` report may open a parent turn again. Queued reports
        are not retroactively woken (dsh ``inject`` parks them until the next
        wake or in-turn read), they are consumed via ``pending_reports`` /
        ``reports_prompt``. No-op for unknown sessions.
        """
        with self._lock:
            self._owner_busy.discard(session_id)

    def mark_thread_busy(self, thread_id: str) -> None:
        """Mark every session of a parent thread mid-turn (thread-scoped busy).

        The react-loop driver calls this when a parent turn starts so reports
        landing during the turn queue (``delivery='queued'``) for all sessions
        the thread owns — including ones created later in the same turn.
        Live state only; an empty thread id is a no-op.
        """
        if not thread_id:
            return
        with self._lock:
            self._busy_threads.add(thread_id)

    def mark_thread_idle(self, thread_id: str) -> None:
        """Clear a parent thread's busy state (thread-scoped idle).

        Called when the parent turn ends (normal, error, or early close) so
        the next ``wakeup`` report may open a parent turn again. Queued
        reports are not retroactively woken — they are consumed via
        ``pending_reports`` / ``reports_prompt``. Empty id is a no-op.
        """
        if not thread_id:
            return
        with self._lock:
            self._busy_threads.discard(thread_id)

    def refill_thread_wake_budget(self, thread_id: str) -> None:
        """Refill wake budgets for every session a parent thread owns.

        dsh refills ``spentWakes`` when the owner claims a human turn; the
        realtime gateway calls this at turn start so a parent that just took
        real input may be woken a fresh budget's worth of times. Only sessions
        with a live budget are touched; empty id is a no-op.
        """
        if not thread_id:
            return
        with self._lock:
            for session in list(self._memory.values()):
                if session.thread_id == thread_id:
                    self._spent_wakes.pop(session.session_id, None)

    def refill_wake_budget(self, session_id: str) -> None:
        """Refill the consecutive-wake budget when the parent claims a human turn.

        dsh refills ``spentWakes`` on ``agent/inbox/claimed`` for a human
        ``user`` message: a parent that just took real input may be woken again
        a fresh budget's worth of times. No-op for unknown sessions.
        """
        with self._lock:
            if session_id in self._memory or self._path_for(session_id) is not None:
                self._spent_wakes.pop(session_id, None)

    def pending_reports(
        self,
        session_id: str,
    ) -> list[tuple[int, SubagentReport]]:
        """Undelivered reports as ``(index, report)`` pairs (oldest first)."""
        session = self.get(session_id)
        if session is None:
            return []
        start = max(0, session.reports_delivered_up_to)
        return [(index, report) for index, report in enumerate(session.reports) if index >= start]

    def mark_reports_delivered(
        self,
        session_id: str,
        *,
        up_to_index: int | None = None,
    ) -> SubagentSession | None:
        """Ack reports through ``up_to_index`` (default: the latest one)."""
        with self._lock:
            session = self.get(session_id)
            if session is None:
                return None
            if up_to_index is None:
                up_to_index = max(0, len(session.reports) - 1)
            session.reports_delivered_up_to = max(
                session.reports_delivered_up_to,
                up_to_index + 1,
            )
            session.updated_at = _utc_now_iso()
            self._memory[session.session_id] = session
            self._write_locked(session)
            return _copy_session(session)

    def reports_prompt(self, session: SubagentSession) -> str:
        """Bounded markdown of undelivered reports for the parent's context.

        This is the child→parent lane: a continuable child shares the
        workspace but the parent does not automatically see its transcript,
        so an explicit report is what the parent can actually act on (dsh
        ``report`` tool guidance).
        """
        start = max(0, session.reports_delivered_up_to)
        pending = list(enumerate(session.reports))[start:]
        if not pending:
            return ""
        lines: list[str] = ["## Subagent reports (child → parent)"]
        total = 0
        for index, report in pending:
            block = (
                f"\n### Report #{index + 1} ({report.delivery})\n{_truncate(report.content, 1500)}"
            )
            if total + len(block) > MAX_REPORTS_PROMPT_CHARS:
                break
            lines.append(block)
            total += len(block)
        return "\n".join(lines)

    def resolve_session_mentions(
        self,
        prompt: str,
        *,
        target_id: str,
        max_references: int | None = None,
        strip_mentions: bool = True,
    ) -> Any:
        """Resolve ``@session:<id>`` / ``@subagent:<id>`` mentions in a prompt.

        Thin store adapter over the resolver's host mention wiring: builds
        the candidate record list from the in-memory store and reads each
        referenced session's surface via ``self.surface_events``. Returns
        the resolver's ``PreparedReferencedMessage``; stale / self mentions
        are skipped, read/budget failures raise ``SessionReferenceError``.
        """
        from runtime.execution.tool_engine.session_reference import (
            SessionReferenceRecord,
            SessionReferenceResolver,
        )

        records: list[SessionReferenceRecord] = []
        with self._lock:
            for session in self._memory.values():
                records.append(
                    SessionReferenceRecord(
                        session_id=session.session_id,
                        label=session.agent_id or session.session_id,
                        created_at=int(session.created_at[:10].replace("-", ""))
                        if len(session.created_at) >= 10
                        else None,
                    )
                )
        kwargs: dict[str, Any] = {}
        if max_references is not None:
            kwargs["max_references"] = max_references
        resolver = SessionReferenceResolver(**kwargs)
        return resolver.resolve_mentions(
            prompt,
            target_id=target_id,
            read_surface=self.surface_events,
            sessions=records,
            strip_mentions=strip_mentions,
        )

    def transcript_prompt(
        self,
        session: SubagentSession,
        *,
        bounded: bool | None = None,
        max_projection_bytes: int | None = None,
    ) -> str:
        """Bounded markdown summary of the prior turns for a continuation call.

        ``bounded`` (default: the ``OCTOPUS_SESSION_REFERENCE_BOUNDED`` switch)
        selects the dsh session-reference projection — an exact byte-bounded
        current-surface snapshot with retention stats — over the legacy
        per-turn head truncation.
        """
        if not session.turns:
            return ""
        if bounded is None:
            bounded = TRANSCRIPT_PROJECTION_ENABLED
        if bounded:
            return self._bounded_transcript_prompt(session, max_projection_bytes)
        lines: list[str] = ["## Previous turns in this subagent session"]
        total = 0
        for turn in session.turns[-MAX_TRANSCRIPT_TURNS:]:
            block = (
                f"\n### Turn ({'ok' if turn.success else 'failed'})\n"
                f"**User asked**: {_truncate(turn.prompt, 400)}\n"
                f"**Subagent answered**: {_truncate(turn.output or turn.error or '(no output)', 1200)}"
            )
            if total + len(block) > MAX_TRANSCRIPT_CHARS:
                break
            lines.append(block)
            total += len(block)
        return "\n".join(lines)

    def _bounded_transcript_prompt(
        self,
        session: SubagentSession,
        max_projection_bytes: int | None,
    ) -> str:
        """Byte-bounded session-reference projection of the prior turns."""
        from runtime.execution.tool_engine.session_projection import (
            retain_session_reference,
        )

        result = retain_session_reference(
            _surface_events_from_turns(session),
            session_id=session.session_id,
            label=f"{session.agent_id or 'subagent'} session",
            max_bytes=max_projection_bytes or MAX_TRANSCRIPT_PROJECTION_BYTES,
        )
        if result is None:
            # Fixed fields cannot fit even at minimum · never emit a partial
            # context (dsh budget contract).
            return (
                "## Referenced session (projected)\n"
                "(conversation exceeds the projection budget; use the report "
                "lane for a bounded summary.)"
            )
        data, stats = result
        lines = [
            "## Referenced session (projected)",
            f"- label: {data.label}",
            f"- session: {data.session_id}",
        ]
        for item in data.conversation:
            role = item.get("role", "")
            text = item.get("text", "")
            lines.append(f"\n**{role}**: {text}")
        if stats.truncated:
            lines.append(
                f"\n_(projected: kept {stats.retained_messages}/"
                f"{stats.original_messages} messages, "
                f"omitted {stats.omitted_bytes} UTF-8 bytes)_"
            )
        return "\n".join(lines)


def _surface_events_from_turns(session: SubagentSession) -> list[dict[str, Any]]:
    """Project a subagent session's turns into the dsh surface event shape."""
    events: list[dict[str, Any]] = []
    for turn in session.turns:
        prompt = (turn.prompt or "").strip()
        output = (turn.output or turn.error or "(no output)").strip()
        events.append(
            {
                "type": "user/message",
                "data": {
                    "source": {"kind": "user"},
                    "content": [{"type": "text", "text": prompt}],
                },
            }
        )
        events.append(
            {
                "type": "assistant/message",
                "data": {
                    "message": {"content": [{"type": "text", "text": output}]},
                },
            }
        )
    return events


_VALID_SESSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _copy_session(session: SubagentSession) -> SubagentSession:
    return SubagentSession(
        session_id=session.session_id,
        agent_id=session.agent_id,
        thread_id=session.thread_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        turns=[SubagentSessionTurn(**asdict(turn)) for turn in session.turns],
        reports=[SubagentReport(**asdict(report)) for report in session.reports],
        reports_delivered_up_to=session.reports_delivered_up_to,
    )


def _normalize_report_delivery(value: Any) -> Literal["wakeup", "quiet", "queued"]:
    if value in ("wakeup", "quiet", "queued"):
        return value  # type: ignore[return-value]
    return "wakeup"


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "…"


_STORE: SubagentSessionStore | None = None
_STORE_LOCK = threading.Lock()


def set_subagent_session_store(store: SubagentSessionStore | None) -> None:
    global _STORE
    with _STORE_LOCK:
        _STORE = store


def get_subagent_session_store() -> SubagentSessionStore | None:
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            return _STORE
        _STORE = SubagentSessionStore()
        return _STORE


__all__ = [
    "DEFAULT_MAX_CONSECUTIVE_WAKES",
    "SubagentReport",
    "SubagentSession",
    "SubagentSessionStore",
    "SubagentSessionTurn",
    "get_subagent_session_store",
    "set_subagent_session_store",
]
