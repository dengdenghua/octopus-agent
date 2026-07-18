"""React-event → ``item/*`` bridge state for the realtime runtime.

Split out of ``realtime_cerebrum.py``: ``_ReactBridgeState`` tracks the
currently-open agentMessage / reasoning / tool items for a turn,
coalesces streaming deltas, watches background commands, and promotes
tool results to first-class ``FileChangeItem`` / ``VerificationItem``
records (the ``*_from_tool_evt`` builders at the bottom).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from runtime.memory.threads.event_log import EventLog
from runtime.protocol import (
    AgentMessageItem,
    AgentPhaseSnapshot,
    CommandExecutionItem,
    FileChange,
    FileChangeItem,
    FileHunk,
    ItemStatus,
    ReasoningItem,
    ServerMethod,
    Turn,
    TurnStatus,
    VerificationItem,
    WorkspaceFocus,
)
from runtime.protocol.diff_parser import parse_unified_diff
from runtime.protocol.items import diff_is_truncated
from runtime.protocol.text_limits import (
    MAX_AGGREGATED_OUTPUT as _MAX_AGGREGATED_OUTPUT,
)
from runtime.protocol.text_limits import (
    MAX_STREAM_ITEM_CONTENT as _MAX_STREAM_ITEM_CONTENT,
)
from runtime.protocol.text_limits import (
    OUTPUT_TRUNCATION_MARK as _OUTPUT_TRUNCATION_MARK,
)
from runtime.protocol.text_limits import (
    STREAM_CONTENT_TRUNCATION_MARK as _STREAM_CONTENT_TRUNCATION_MARK,
)
from runtime.protocol.text_limits import (
    append_capped_text as _append_capped_text,
)
from runtime.sensing.gateway.realtime_gateway import EventEmitter
from runtime.sensing.gateway.realtime_workbench import (
    _phases_from_todo_preview,
    _phases_with_active_item,
    _terminal_workbench_phases,
    _workbench_snapshot,
    _workspace_focus_for_file_change,
    _workspace_focus_for_tool,
)

_logger = logging.getLogger(__name__)


def _safe_list_remove(bucket: list[Any], item: Any) -> None:
    """Remove ``item`` from ``bucket`` if present. Tolerant of races
    (the bucket may have been swept out from under us by a concurrent
    reap)."""
    with contextlib.suppress(ValueError):
        bucket.remove(item)


# Hard cap on a single command item's retained output. The per-delta
# stream (ITEM_COMMAND_OUTPUT_DELTA) still carries every chunk live, so the
# user's view is unaffected — this only bounds the *accumulated* buffer that
# gets re-serialized whole into workbench snapshots and the turn/completed
# frame. Without it a runaway command (a stress test, a verbose build) grows
# aggregated_output without limit until that frame exceeds the realtime WS
# 16 MiB message ceiling and the socket is dropped with code 1009 — which
# also took down mid-run backends. 256 KiB is far more than any rendered log
# needs and keeps a whole turn's items well under the frame limit.
def _append_capped_output(existing: str, delta: str) -> str:
    """Append ``delta`` to ``existing`` but never grow past the cap.

    Once the cap is reached the buffer is frozen (the live delta stream
    still delivers subsequent chunks), so this is also O(cap) per delta
    instead of the O(n) string rebuild the unbounded ``+=`` incurred.
    """
    return _append_capped_text(
        existing,
        delta,
        cap=_MAX_AGGREGATED_OUTPUT,
        marker=_OUTPUT_TRUNCATION_MARK,
    )


def _append_capped_stream_content(existing: str, delta: str) -> str:
    """Bound reasoning/message snapshots without dropping live deltas."""

    return _append_capped_text(
        existing,
        delta,
        cap=_MAX_STREAM_ITEM_CONTENT,
        marker=_STREAM_CONTENT_TRUNCATION_MARK,
    )


# ── Bridge state — open agentMessage / reasoning / tool items ─


class _ReactBridgeState:
    """Tracks which items are currently open per (turn, kind).

    The react loop streams ``text_delta`` / ``thinking_delta`` chunks
    that should land on a single ongoing item. ``tool_start``/``tool_end``
    bind by ``tool_call_id``. ``flush`` finalizes any open prose items
    so subsequent steps start fresh.
    """

    # Streaming text/reasoning chunks arrive per-token from the LLM.
    # One WS frame + one journal write per token is pure overhead —
    # the frontend coalesces per animation frame anyway. Buffer and
    # flush on whichever comes first: ~64 chars or 50ms. The FIRST
    # chunk of each item is never buffered (time-to-first-token), and
    # any kind switch / item finalization drains the buffer, so
    # ordering and final content are byte-identical to unbuffered.
    _DELTA_FLUSH_INTERVAL_S = 0.05
    _DELTA_FLUSH_MAX_CHARS = 64

    def __init__(
        self,
        on_background_task_start: Callable[[asyncio.Task[None]], None] | None = None,
    ) -> None:
        self.agent_message: AgentMessageItem | None = None
        self.commentary_message: AgentMessageItem | None = None
        self.last_public_commentary_key: str | None = None
        self.progress_sequence = 0
        self.timeline_sequence = 0
        self.last_timeline_item_id: str | None = None
        self.current_phase_id: str | None = None
        self.reasoning: ReasoningItem | None = None
        self.tools: dict[str, CommandExecutionItem] = {}
        self.phases: list[AgentPhaseSnapshot] = []
        self.workbench_snapshot_version = 0
        self.background_tasks: list[asyncio.Task[None]] = []
        self._delta_buf: list[str] = []
        self._delta_kind: str | None = None
        self._delta_ctx: tuple[Turn, EventLog, EventEmitter] | None = None
        self._delta_flush_task: asyncio.Task[None] | None = None
        # Serializes buffer drain between the consumer coroutine and
        # the delayed-flush task so emitted chunks never interleave
        # out of order on the socket.
        self._delta_lock = asyncio.Lock()
        # Optional sink for cross-turn ownership of background watchers.
        # When set, each task created by ``track_background_tool`` is
        # also pushed through this callback so the runtime can sweep
        # leftovers when the user starts a brand-new turn on the same
        # thread (the watcher lives on by design — see
        # ``test_background_tool_item_completes_after_turn_response`` —
        # but we don't want it bleeding into the NEXT conversation).
        self._on_background_task_start = on_background_task_start

    # ── Lifecycle helpers ──────────────────────────────────────────────
    # Every method in this class emits item lifecycle events as a pair:
    # journal write + WS notify. Inlining the 5-line ``notify`` payload
    # at every site obscured the actual logic and made the ServerMethod
    # name a search-and-replace hazard. These helpers centralize the
    # boilerplate; behaviour is byte-identical to the previous inline form.
    @staticmethod
    def _item_payload(turn: Turn, item: Any) -> dict[str, Any]:
        return {
            "threadId": turn.thread_id,
            "turnId": turn.id,
            "item": item.model_dump(by_alias=True, mode="json"),
        }

    def _bind_timeline(self, item: Any, *, phase_id: str | None = None) -> None:
        """Assign stable causal coordinates before an item is published.

        Transport arrival order is not durable: reconnect replay, browser
        batching and background completions can all deliver snapshots on a
        different schedule. A monotonic per-turn coordinate plus an explicit
        parent lets every client reconstruct the same conversational rhythm.
        """
        if getattr(item, "timeline_sequence", None) is None:
            self.timeline_sequence += 1
            item.timeline_sequence = self.timeline_sequence
        if getattr(item, "parent_item_id", None) is None:
            item.parent_item_id = self.last_timeline_item_id
        if getattr(item, "phase_id", None) is None:
            item.phase_id = phase_id or self.current_phase_id
        self.last_timeline_item_id = item.id

    async def _emit_started(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            self._item_payload(turn, item),
        )

    async def _emit_completed(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            self._item_payload(turn, item),
        )

    async def append_agent_message(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        delta: str,
    ) -> None:
        if not delta:
            return
        first = self.agent_message is None
        if first:
            self.agent_message = AgentMessageItem(text="")
            self._bind_timeline(self.agent_message)
            turn.items.append(self.agent_message)
            await self._emit_started(turn, log, emitter, self.agent_message)
        self.agent_message.text = _append_capped_stream_content(
            self.agent_message.text,
            delta,
        )
        await self._buffer_delta(
            turn,
            log,
            emitter,
            "agentMessage",
            delta,
            flush_now=first,
        )

    async def append_reasoning(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        delta: str,
    ) -> None:
        if not delta:
            return
        first = self.reasoning is None
        if first:
            self.reasoning = ReasoningItem(content="")
            self._bind_timeline(self.reasoning)
            turn.items.append(self.reasoning)
            await self._emit_started(turn, log, emitter, self.reasoning)
        self.reasoning.content = _append_capped_stream_content(
            self.reasoning.content,
            delta,
        )
        await self._buffer_delta(
            turn,
            log,
            emitter,
            "reasoning",
            delta,
            flush_now=first,
        )

    async def append_commentary(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        delta: str,
        *,
        start_new_segment: bool = False,
    ) -> None:
        if not delta:
            return
        if start_new_segment:
            commentary_key = " ".join(delta.split()).casefold()
            if commentary_key == self.last_public_commentary_key:
                return
            self.last_public_commentary_key = commentary_key
        # Public-checkpoint boundaries are structural. Never inspect prose or
        # a hard-coded "investigate / implement / verify" label to decide
        # whether two messages belong together.
        if self.commentary_message is not None and start_new_segment:
            await self._flush_pending_delta()
            self.commentary_message.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.commentary_message)
            self.commentary_message = None
        first = self.commentary_message is None
        if first:
            self.progress_sequence += 1
            phase_id = f"{turn.id}:progress:{self.progress_sequence}"
            self.current_phase_id = phase_id
            self.commentary_message = AgentMessageItem(
                text="",
                message_kind="commentary",
                phase_id=phase_id,
                progress_sequence=self.progress_sequence,
            )
            self._bind_timeline(self.commentary_message, phase_id=phase_id)
            turn.items.append(self.commentary_message)
            await self._emit_started(turn, log, emitter, self.commentary_message)
        self.commentary_message.text = _append_capped_stream_content(
            self.commentary_message.text,
            delta,
        )
        await self._buffer_delta(
            turn,
            log,
            emitter,
            "commentary",
            delta,
            flush_now=first,
        )

    # ── Delta coalescing ────────────────────────────────────────────

    async def _buffer_delta(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        kind: str,
        delta: str,
        *,
        flush_now: bool,
    ) -> None:
        if self._delta_buf and self._delta_kind != kind:
            # Prose kind switched (reasoning ↔ message): drain the old
            # kind first so chunks never reorder across items.
            await self._flush_pending_delta()
        self._delta_kind = kind
        self._delta_ctx = (turn, log, emitter)
        self._delta_buf.append(delta)
        if flush_now or sum(len(s) for s in self._delta_buf) >= self._DELTA_FLUSH_MAX_CHARS:
            await self._flush_pending_delta()
            return
        if self._delta_flush_task is None or self._delta_flush_task.done():
            # Deadline flush: without it, an LLM stall mid-stream
            # would leave the buffered tail invisible until the next
            # chunk arrives (which may be seconds away).
            self._delta_flush_task = asyncio.create_task(self._delayed_delta_flush())

    async def _delayed_delta_flush(self) -> None:
        await asyncio.sleep(self._DELTA_FLUSH_INTERVAL_S)
        await self._flush_pending_delta()

    async def _flush_pending_delta(self) -> None:
        async with self._delta_lock:
            task = self._delta_flush_task
            if task is not None and task is not asyncio.current_task():
                task.cancel()
            self._delta_flush_task = None
            if not self._delta_buf or self._delta_ctx is None:
                return
            combined = "".join(self._delta_buf)
            self._delta_buf.clear()
            kind = self._delta_kind
            turn, log, emitter = self._delta_ctx
            if kind == "agentMessage" and self.agent_message is not None:
                item_id = self.agent_message.id
                log.item_delta(turn.thread_id, turn.id, item_id, "agentMessage", combined)
                await emitter.notify(
                    ServerMethod.ITEM_AGENT_MESSAGE_DELTA,
                    {
                        "threadId": turn.thread_id,
                        "turnId": turn.id,
                        "itemId": item_id,
                        "delta": combined,
                    },
                )
            elif kind == "commentary" and self.commentary_message is not None:
                item_id = self.commentary_message.id
                log.item_delta(turn.thread_id, turn.id, item_id, "agentMessage", combined)
                await emitter.notify(
                    ServerMethod.ITEM_AGENT_MESSAGE_DELTA,
                    {
                        "threadId": turn.thread_id,
                        "turnId": turn.id,
                        "itemId": item_id,
                        "delta": combined,
                    },
                )
            elif kind == "reasoning" and self.reasoning is not None:
                item_id = self.reasoning.id
                log.item_delta(turn.thread_id, turn.id, item_id, "reasoning", combined)
                await emitter.notify(
                    ServerMethod.ITEM_REASONING_TEXT_DELTA,
                    {
                        "threadId": turn.thread_id,
                        "turnId": turn.id,
                        "itemId": item_id,
                        "delta": combined,
                        "contentIndex": 0,
                    },
                )
            # else: the item was already finalized — drop the tail; the
            # item/completed snapshot carries the full text regardless.

    async def start_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        # Flush any open prose so the tool item appears after the
        # reasoning that produced it.
        await self.flush(turn, log, emitter)
        call_id = str(evt.get("tool_call_id") or "")
        # Disambiguate when the same tool_call_id appears twice (e.g.
        # swarm sub_tool ids built from ``agent-round-skill`` collide
        # if the same role calls the same skill twice in a round).
        # Without this the second start silently orphans the first
        # CommandExecutionItem — it never gets a tool_end since the
        # dict slot is overwritten.
        if call_id and call_id in self.tools:
            suffix = 2
            while f"{call_id}#{suffix}" in self.tools:
                suffix += 1
            call_id = f"{call_id}#{suffix}"
        # Let the model's default_factory mint the id when there's no
        # call_id — the old ``CommandExecutionItem().id`` built a throwaway
        # with no ``command`` and raised ValidationError (command is required).
        item = CommandExecutionItem(
            command=str(evt.get("tool_name", "tool")),
            input_preview=evt.get("input_preview"),
            **({"id": call_id} if call_id else {}),
        )
        self._bind_timeline(item)
        self.tools[call_id] = item
        turn.items.append(item)
        await self._emit_started(turn, log, emitter, item)
        phases = _phases_from_todo_preview(item.input_preview, active_item_id=item.id)
        if phases is not None:
            self.phases = phases
        await self._emit_turn_update(
            turn,
            log,
            emitter,
            workspace_focus=_workspace_focus_for_tool(item),
        )

    async def append_tool_output(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        item = self.tools.get(call_id)
        delta = evt.get("delta")
        if item is None or not isinstance(delta, str) or not delta:
            return
        item.aggregated_output = _append_capped_output(item.aggregated_output or "", delta)
        log.item_delta(turn.thread_id, turn.id, item.id, "commandOutput", delta)
        await emitter.notify(
            ServerMethod.ITEM_COMMAND_OUTPUT_DELTA,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "itemId": item.id,
                "delta": delta,
            },
        )

    async def track_background_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        task_id = str(evt.get("task_id") or "")
        item = self.tools.get(call_id)
        if item is None or not task_id:
            return

        preview = item.input_preview if isinstance(item.input_preview, dict) else {}
        snapshot = evt.get("snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        item.input_preview = {
            **preview,
            "background": True,
            "task_id": task_id,
            "status": "running",
            "argv": snapshot.get("argv"),
            "cwd": snapshot.get("cwd") or item.cwd,
        }
        item.process_id = task_id
        # Re-emit ITEM_STARTED so the UI picks up the background metadata
        # we just added; the journal already has the original start record
        # from ``start_tool`` so we skip the journal write here.
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            self._item_payload(turn, item),
        )
        with contextlib.suppress(ConnectionError, OSError, RuntimeError, TypeError):
            await self.append_tool_output(
                turn,
                log,
                emitter,
                {
                    "tool_call_id": call_id,
                    "delta": f"background process started: {task_id}\n",
                },
            )

        async def _watch_background() -> None:
            last_stdout = ""
            last_stderr = ""
            try:
                from runtime.execution.suckers.write_skills import (
                    _kill_background_exec,
                    _read_background_output,
                )

                while True:
                    if emitter.is_turn_interrupted(turn.id):
                        snap = _kill_background_exec(task_id=task_id)
                    else:
                        snap = _read_background_output(task_id=task_id)
                    if not isinstance(snap, dict):
                        snap = {"status": "failed", "error": "invalid background snapshot"}

                    stdout = str(snap.get("stdout") or "")
                    stderr = str(snap.get("stderr") or "")
                    delta = ""
                    if len(stdout) > len(last_stdout):
                        delta += stdout[len(last_stdout) :]
                    if len(stderr) > len(last_stderr):
                        stderr_delta = stderr[len(last_stderr) :]
                        delta += stderr_delta if not delta else "\n[stderr]\n" + stderr_delta
                    last_stdout = stdout
                    last_stderr = stderr
                    if delta:
                        with contextlib.suppress(
                            ConnectionError,
                            OSError,
                            RuntimeError,
                            TypeError,
                        ):
                            await self.append_tool_output(
                                turn,
                                log,
                                emitter,
                                {"tool_call_id": call_id, "delta": delta},
                            )

                    status = str(snap.get("status") or "")
                    if status != "running":
                        if status == "cancelled":
                            end_status = "cancelled"
                        elif status == "completed":
                            end_status = "success"
                        else:
                            end_status = "error"
                        with contextlib.suppress(
                            ConnectionError,
                            OSError,
                            RuntimeError,
                            TypeError,
                        ):
                            await self.complete_tool(
                                turn,
                                log,
                                emitter,
                                {
                                    "tool_call_id": call_id,
                                    "tool_name": evt.get("tool_name") or item.command,
                                    "status": end_status,
                                    "output_preview": "",
                                    "duration_ms": evt.get("duration_ms"),
                                },
                            )
                        return
                    await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                _logger.debug("background command watcher failed", exc_info=True)

        self.background_tasks.append(asyncio.create_task(_watch_background()))
        if self._on_background_task_start is not None:
            with contextlib.suppress(Exception):
                self._on_background_task_start(self.background_tasks[-1])

    async def complete_tool(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        evt: dict[str, Any],
    ) -> None:
        call_id = str(evt.get("tool_call_id") or "")
        item = self.tools.pop(call_id, None)
        if item is None:
            # Unknown tool_call_id — skip rather than synthesize.
            return
        status = evt.get("status", "success")
        if status == "rejected":
            item.status = ItemStatus.DECLINED
        elif status == "cancelled":
            item.status = ItemStatus.INTERRUPTED
        elif status == "error":
            item.status = ItemStatus.FAILED
        else:
            item.status = ItemStatus.COMPLETED
        if isinstance(evt.get("output_preview"), str) and not item.aggregated_output:
            # If the tool already streamed output incrementally, keep the
            # streamed text — ``output_preview`` is a *summary* that loses
            # detail, so overwriting would regress the live view.
            item.aggregated_output = _append_capped_output("", evt["output_preview"])
        await self._emit_completed(turn, log, emitter, item)
        # Apply-patch first-class item: when a file-editing tool ran
        # successfully and surfaced a unified diff, promote it to a
        # dedicated FileChangeItem so the UI can render hunks with
        # per-hunk accept/reject. We only do this on success — a
        # failed tool call has nothing to show.
        if item.status == ItemStatus.COMPLETED:
            related_change_item_ids: list[str] = []
            related_files: list[str] = []
            file_item = _file_change_item_from_tool_evt(evt)
            if file_item is not None:
                self._bind_timeline(file_item)
                related_change_item_ids.append(file_item.id)
                related_files = [change.path for change in file_item.changes]
                turn.items.append(file_item)
                started_file_item = FileChangeItem(
                    id=file_item.id,
                    changes=[],
                    grant_root=file_item.grant_root,
                    timeline_sequence=file_item.timeline_sequence,
                    parent_item_id=file_item.parent_item_id,
                    phase_id=file_item.phase_id,
                )
                await self._emit_started(turn, log, emitter, started_file_item)
                file_focus = _workspace_focus_for_file_change(file_item)
                await self._emit_turn_update(
                    turn,
                    log,
                    emitter,
                    workspace_focus=file_focus,
                )
                await self._emit_file_change_hunks(
                    turn,
                    log,
                    emitter,
                    file_item,
                    workspace_focus=file_focus,
                )
                # ``_emit_item_completed`` lives on ``CerebrumRuntime`` and
                # isn't reachable from here — use the local ``_emit_completed``
                # so we don't reach across class boundaries.
                await self._emit_completed(turn, log, emitter, file_item)

            verification_item = _verification_item_from_tool_evt(
                item,
                evt,
                related_change_item_ids=related_change_item_ids,
                related_files=related_files,
            )
            if verification_item is not None:
                self._bind_timeline(verification_item)
                turn.items.append(verification_item)
                await self._emit_started(turn, log, emitter, verification_item)
                await self._emit_completed(turn, log, emitter, verification_item)
        else:
            verification_item = _verification_item_from_tool_evt(
                item,
                evt,
                related_change_item_ids=[],
                related_files=[],
            )
            if verification_item is not None:
                self._bind_timeline(verification_item)
                turn.items.append(verification_item)
                await self._emit_started(turn, log, emitter, verification_item)
                await self._emit_completed(turn, log, emitter, verification_item)

    async def flush(self, turn: Turn, log: EventLog, emitter: EventEmitter) -> None:
        # Drain coalesced deltas BEFORE finalizing: completing an item
        # nulls the slot the pending tail would attach to.
        await self._flush_pending_delta()
        if self.agent_message is not None:
            self.agent_message.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.agent_message)
            self.agent_message = None
        if self.commentary_message is not None:
            self.commentary_message.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.commentary_message)
            self.commentary_message = None
        if self.reasoning is not None:
            self.reasoning.status = ItemStatus.COMPLETED
            await self._emit_completed(turn, log, emitter, self.reasoning)
            self.reasoning = None

    async def finalize_workbench(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        *,
        terminal_status: TurnStatus,
    ) -> None:
        """Emit the terminal workbench snapshot for ``turn``.

        Called when the orchestrating turn reaches a terminal state
        (COMPLETED / FAILED / INTERRUPTED). ``_terminal_workbench_phases``
        rewrites pending/running phases into the appropriate terminal
        shape and clears every ``active_item_id`` so the UI stops
        highlighting items owned by long-lived background watchers
        (e.g. a long-running shell command whose output keeps
        streaming after the turn finishes).

        We do NOT bail when ``self.tools`` is non-empty — those are
        background watchers by design (see
        ``track_background_tool``); the user's *turn* is over even if
        the watcher process isn't. Bailing here used to leave the UI
        stuck at "running" forever.
        """
        if not self.phases:
            return
        terminal_phases = _terminal_workbench_phases(
            self.phases,
            terminal_status,
        )
        if terminal_phases == self.phases and turn.workbench_snapshot is not None:
            return
        self.phases = terminal_phases
        await self._emit_turn_update(
            turn,
            log,
            emitter,
            workspace_focus=turn.workspace_focus,
        )

    async def _emit_turn_update(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        *,
        workspace_focus: WorkspaceFocus | None = None,
    ) -> None:
        phases = _phases_with_active_item(self.phases, workspace_focus)
        turn.phases = phases
        if workspace_focus is not None:
            turn.workspace_focus = workspace_focus
        self.workbench_snapshot_version += 1
        snapshot = _workbench_snapshot(
            version=self.workbench_snapshot_version,
            phases=phases,
            workspace_focus=turn.workspace_focus,
        )
        turn.workbench_snapshot = snapshot
        phases_payload = [phase.model_dump(by_alias=True, mode="json") for phase in phases]
        focus_payload = (
            workspace_focus.model_dump(by_alias=True, mode="json")
            if workspace_focus is not None
            else None
        )
        snapshot_payload = snapshot.model_dump(by_alias=True, mode="json")
        log.turn_updated(
            turn.thread_id,
            turn.id,
            phases=phases_payload,
            workspace_focus=focus_payload,
            workbench_snapshot=snapshot_payload,
        )
        # MIGRATION (sunset target: v0.3): we currently emit the snapshot on
        # BOTH ``turn/plan/updated`` (legacy clients) and ``workbench/snapshot``
        # (new clients). Once every shipped frontend is on the new method,
        # drop ``workbenchSnapshot`` from the ``turn/plan/updated`` payload
        # so the wire is half the size for plan-only updates. Track removal
        # in CHANGELOG when the tap is closed.
        await emitter.notify(
            ServerMethod.TURN_PLAN_UPDATED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "phases": phases_payload,
                **({"workspaceFocus": focus_payload} if focus_payload is not None else {}),
                "workbenchSnapshot": snapshot_payload,
            },
        )
        await emitter.notify(
            ServerMethod.WORKBENCH_SNAPSHOT,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "snapshot": snapshot_payload,
            },
        )

    async def _emit_file_change_hunks(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: FileChangeItem,
        *,
        workspace_focus: WorkspaceFocus | None = None,
    ) -> None:
        focus_payload = (
            workspace_focus.model_dump(by_alias=True, mode="json")
            if workspace_focus is not None
            else None
        )
        for change in item.changes:
            for hunk in change.hunks:
                hunk_payload = hunk.model_dump(by_alias=True, mode="json")
                delta_payload = {
                    "path": change.path,
                    "op": change.op,
                    "hunk": hunk_payload,
                }
                log.item_delta(
                    turn.thread_id,
                    turn.id,
                    item.id,
                    "fileChangeHunk",
                    delta_payload,
                )
                await emitter.notify(
                    ServerMethod.ITEM_FILE_CHANGE_HUNK_DELTA,
                    {
                        "threadId": turn.thread_id,
                        "turnId": turn.id,
                        "itemId": item.id,
                        "path": change.path,
                        "op": change.op,
                        "hunk": hunk_payload,
                        **({"workspaceFocus": focus_payload} if focus_payload is not None else {}),
                    },
                )


def _file_change_item_from_tool_evt(evt: dict[str, Any]) -> FileChangeItem | None:
    """Build a structured FileChangeItem from a react_loop ``tool_end`` event.

    Two input shapes are accepted:

      * ``evt["diff"]``               — a raw unified-diff string (multi-file ok).
      * ``evt["file_changes"]``       — a pre-parsed list of
        ``{path, op, diff?, hunks?}`` dicts; skills that already know
        the shape can emit these directly to avoid a re-parse.

    Returns ``None`` when neither is present or both are empty — the
    caller must not emit an empty FileChangeItem.
    """
    raw_diff = evt.get("diff")
    if isinstance(raw_diff, str) and raw_diff.strip():
        changes = parse_unified_diff(raw_diff)
        if changes:
            if diff_is_truncated(raw_diff):
                # The marker sits at the tail of the combined diff, so
                # only the last file's diff is known-incomplete.
                changes[-1].diff_truncated = True
            return FileChangeItem(changes=changes)

    raw_list = evt.get("file_changes")
    if isinstance(raw_list, list) and raw_list:
        parsed: list[FileChange] = []
        for entry in raw_list:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            op = entry.get("op")
            if not isinstance(path, str) or op not in ("create", "update", "delete"):
                continue
            diff_str = entry.get("diff") if isinstance(entry.get("diff"), str) else None
            hunks_raw = entry.get("hunks")
            hunks: list[FileHunk] = []
            if isinstance(hunks_raw, list):
                for h in hunks_raw:
                    if not isinstance(h, dict):
                        continue
                    hunks.append(
                        FileHunk(
                            old_start=int(h.get("old_start", h.get("oldStart", 0)) or 0),
                            old_lines=int(h.get("old_lines", h.get("oldLines", 0)) or 0),
                            new_start=int(h.get("new_start", h.get("newStart", 0)) or 0),
                            new_lines=int(h.get("new_lines", h.get("newLines", 0)) or 0),
                            body=str(h.get("body", "")),
                        )
                    )
            if not hunks and diff_str:
                sub = parse_unified_diff(diff_str)
                if sub:
                    hunks = sub[0].hunks
            parsed.append(
                FileChange(
                    path=path,
                    op=op,
                    diff=diff_str,
                    diff_truncated=diff_is_truncated(diff_str),
                    hunks=hunks,
                )
            )
        if parsed:
            return FileChangeItem(changes=parsed)
    return None


def _verification_item_from_tool_evt(
    command_item: CommandExecutionItem,
    evt: dict[str, Any],
    *,
    related_change_item_ids: list[str] | None = None,
    related_files: list[str] | None = None,
) -> VerificationItem | None:
    """Promote embedded post-write diagnostics to a first-class item."""

    explicit = evt.get("verification")
    if isinstance(explicit, dict):
        kind = explicit.get("kind")
        if kind not in {"test", "lint", "typecheck", "build", "diagnostic", "manual"}:
            kind = "manual"
        success = explicit.get("success")
        exit_code = explicit.get("exit_code")
        if not isinstance(exit_code, int):
            exit_code = 0 if success is True else None
        if success is True:
            status = ItemStatus.COMPLETED
        elif success is False:
            status = ItemStatus.FAILED
        elif isinstance(exit_code, int):
            status = ItemStatus.COMPLETED if exit_code == 0 else ItemStatus.FAILED
        else:
            status = ItemStatus.COMPLETED if evt.get("status") == "success" else ItemStatus.FAILED
        stdout_tail = explicit.get("stdout_tail")
        stderr_tail = explicit.get("stderr_tail")
        stdout_tail = stdout_tail[-4000:] if isinstance(stdout_tail, str) else None
        stderr_tail = stderr_tail[-4000:] if isinstance(stderr_tail, str) else None
        summary_src = stderr_tail or stdout_tail or command_item.aggregated_output
        summary = None
        if isinstance(summary_src, str) and summary_src.strip():
            summary = summary_src.strip().splitlines()[0][:240]
        command = explicit.get("command")
        if not isinstance(command, str) or not command.strip():
            command = command_item.command
        explicit_related_files = explicit.get("related_files")
        if not isinstance(explicit_related_files, list):
            explicit_related_files = explicit.get("relatedFiles")
        verification_related_files: list[str] = []
        if isinstance(explicit_related_files, list):
            verification_related_files = [
                path for path in explicit_related_files if isinstance(path, str) and path.strip()
            ]
        if not verification_related_files:
            verification_related_files = list(related_files or [])
        return VerificationItem(
            command=command,
            kind=kind,
            status=status,
            exit_code=exit_code,
            summary=summary,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            related_files=verification_related_files,
            related_change_item_ids=list(related_change_item_ids or []),
        )

    output = ""
    if isinstance(evt.get("output_preview"), str):
        output = evt["output_preview"]
    if command_item.aggregated_output:
        output = command_item.aggregated_output
    if not output:
        return None

    markers = (
        "[post-write diagnostics]",
        "[自动诊断结果]",
        "ruff diagnostics",
        "eslint diagnostics",
    )
    if not any(marker in output for marker in markers):
        return None

    diagnostic_related_files: list[str] = list(related_files or [])
    file_item = _file_change_item_from_tool_evt(evt)
    if file_item is not None:
        for change in file_item.changes:
            if change.path not in diagnostic_related_files:
                diagnostic_related_files.append(change.path)
    preview = command_item.input_preview
    if isinstance(preview, dict):
        path = preview.get("path") or preview.get("file_path")
        if isinstance(path, str) and path and path not in diagnostic_related_files:
            diagnostic_related_files.append(path)

    tail = output[-4000:]
    stripped = tail.strip()
    summary = stripped.splitlines()[0][:240] if stripped else None
    return VerificationItem(
        command="post-write diagnostics",
        kind="diagnostic",
        status=ItemStatus.FAILED,
        exit_code=1,
        summary=summary,
        stdout_tail=tail,
        stderr_tail=None,
        related_files=diagnostic_related_files,
        related_change_item_ids=list(related_change_item_ids or []),
    )
