"""Cerebrum-backed realtime runtime.

Bridges the existing :func:`runtime.core.cerebrum.react_loop.stream_react_loop`
to the JSON-RPC ``item/*`` protocol. Translation rules:

  ``text_delta``           → ``item/agentMessage/delta`` on the active
                             agentMessage item (created lazily).
  ``thinking_delta``       → ``item/reasoning/textDelta`` on the active
                             reasoning item (created lazily).
  ``tool_start``           → emits ``item/started`` for a new
                             commandExecution / mcpToolCall item; record
                             the tool call id so subsequent events bind.
  ``tool_approval_request``→ converted into a server-initiated
                             ``item/commandExecution/requestApproval``
                             via the gateway's approval channel; the
                             returned decision is forwarded to the
                             :class:`ApprovalProvider` blocking the
                             react loop's thread.
  ``tool_end``             → emits ``item/completed`` for the matching
                             tool item, propagating status/exit code.
  ``react_step_complete``  → flushes any open agentMessage/reasoning
                             items and finalizes them.
  ``react_completed``      → triggers turn close; ``turn/completed`` is
                             emitted by the gateway after start_turn
                             returns.
  ``react_error``          → final ``error`` item.

The ``GatewayApprovalProvider`` runs the react loop's blocking
``request`` call on the asyncio event loop's executor, then awaits the
gateway's :meth:`EventEmitter.request_approval` from the running loop.
This is the only place where async↔sync handoff happens; the rest of
the bridge stays in the runtime's coroutine.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.platform.models.primitives import now_utc
from runtime.protocol import (
    AgentMessageItem,
    ItemStatus,
    JsonRpcErrorCode,
    ServerMethod,
    Turn,
    TurnParams,
    TurnStatus,
)
from runtime.safety.approval.approval_gate import (
    ApprovalProvider,
)
from runtime.safety.approval.approval_policy_store import load_policy

# ── Split-module compat re-exports ────────────────────────────
# The helpers below moved out of this file into focused sibling
# modules. Re-import them under their original names (redundant-alias
# form marks an intentional re-export) so existing imports and tests
# that reach into ``realtime_cerebrum`` keep working unchanged.
from runtime.sensing.gateway.realtime_approval import (
    GatewayApprovalProvider as GatewayApprovalProvider,
)
from runtime.sensing.gateway.realtime_event_bridge import (
    _file_change_item_from_tool_evt as _file_change_item_from_tool_evt,
)
from runtime.sensing.gateway.realtime_event_bridge import (
    _ReactBridgeState as _ReactBridgeState,
)
from runtime.sensing.gateway.realtime_event_bridge import (
    _safe_list_remove as _safe_list_remove,
)
from runtime.sensing.gateway.realtime_event_bridge import (
    _verification_item_from_tool_evt as _verification_item_from_tool_evt,
)
from runtime.sensing.gateway.realtime_gateway import (
    EventEmitter,
    RealtimeRuntime,
    _RpcError,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _agentic_stream_event_to_react_event as _agentic_stream_event_to_react_event,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _apply_react_event as _apply_react_event,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _drive_react as _drive_react,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _drive_reflection_fast_path as _drive_reflection_fast_path,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _is_auth_context_error as _is_auth_context_error,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _model_error_reply as _model_error_reply,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _should_use_native_tool_loop as _should_use_native_tool_loop,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _should_use_reflection_fast_path as _should_use_reflection_fast_path,
)
from runtime.sensing.gateway.realtime_react_stream import (
    _try_reflex_reply as _try_reflex_reply,
)
from runtime.sensing.gateway.realtime_team_stream import (
    _drive_group_fanout as _drive_group_fanout,
)
from runtime.sensing.gateway.realtime_team_stream import (
    _drive_swarm_mesh as _drive_swarm_mesh,
)
from runtime.sensing.gateway.realtime_team_stream import (
    _drive_team_topology as _drive_team_topology,
)
from runtime.sensing.gateway.realtime_thread_history import (
    _build_ai_kwargs as _build_ai_kwargs,
)
from runtime.sensing.gateway.realtime_thread_history import (
    _conversation_messages_for_react as _conversation_messages_for_react,
)
from runtime.sensing.gateway.realtime_thread_history import (
    _flatten_turns_to_messages as _flatten_turns_to_messages,
)
from runtime.sensing.gateway.realtime_thread_history import (
    _title_from_messages as _title_from_messages,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    _compaction_lock_for as _compaction_lock_for,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    _handle_hunk_decide as _handle_hunk_decide,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    _maybe_compact as _maybe_compact,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    _maybe_compact_locked as _maybe_compact_locked,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    _resolve_hunk_path as _resolve_hunk_path,
)
from runtime.sensing.gateway.realtime_thread_ops import (
    compact_thread as compact_thread,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _agent_id_from_params as _agent_id_from_params,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _build_intent as _build_intent,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _conversation_messages_from_params as _conversation_messages_from_params,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _execution_resume_intent as _execution_resume_intent,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _input_attachments as _input_attachments,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _input_metadata as _input_metadata,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _join_text as _join_text,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _parse_resume_confirmation as _parse_resume_confirmation,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _parse_resume_intent as _parse_resume_intent,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _preview_text as _preview_text,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _reflex_response_to_text as _reflex_response_to_text,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _resume_confirmation_text as _resume_confirmation_text,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _resume_task_id_from_intent as _resume_task_id_from_intent,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _safe_int as _safe_int,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _safe_str as _safe_str,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _should_default_planning_mode as _should_default_planning_mode,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _should_default_topology as _should_default_topology,
)
from runtime.sensing.gateway.realtime_turn_input import (
    _turn_mode as _turn_mode,
)
from runtime.sensing.gateway.realtime_turn_lifecycle import (
    _consume_confirmed_resume_intent as _consume_confirmed_resume_intent,
)
from runtime.sensing.gateway.realtime_turn_lifecycle import (
    _record_pending_resume_intent as _record_pending_resume_intent,
)
from runtime.sensing.gateway.realtime_turn_lifecycle import (
    _start_turn as _start_turn,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _code_change_paths as _code_change_paths,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _failed_turn_description as _failed_turn_description,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _failed_turn_metadata as _failed_turn_metadata,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _file_change_item_ids as _file_change_item_ids,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _file_change_items as _file_change_items,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _is_code_change_path as _is_code_change_path,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _record_failed_turn_proposal as _record_failed_turn_proposal,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _record_react_trace_event as _record_react_trace_event,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _record_successful_turn_example as _record_successful_turn_example,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _record_task_run_finished as _record_task_run_finished,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _record_task_run_started as _record_task_run_started,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _successful_turn_description as _successful_turn_description,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _successful_turn_metadata as _successful_turn_metadata,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_failure_text as _turn_failure_text,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_goal_text as _turn_goal_text,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_has_failed_code_verification as _turn_has_failed_code_verification,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_has_passing_code_verification as _turn_has_passing_code_verification,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_has_unverified_code_changes as _turn_has_unverified_code_changes,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_item_counts as _turn_item_counts,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _turn_model as _turn_model,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _verification_items as _verification_items,
)
from runtime.sensing.gateway.realtime_turn_outcome import (
    _verification_matches_code_changes as _verification_matches_code_changes,
)
from runtime.sensing.gateway.realtime_workbench import (
    _coerce_preview_record as _coerce_preview_record,
)
from runtime.sensing.gateway.realtime_workbench import (
    _current_workbench_phase as _current_workbench_phase,
)
from runtime.sensing.gateway.realtime_workbench import (
    _first_string as _first_string,
)
from runtime.sensing.gateway.realtime_workbench import (
    _phase_title as _phase_title,
)
from runtime.sensing.gateway.realtime_workbench import (
    _phases_from_todo_preview as _phases_from_todo_preview,
)
from runtime.sensing.gateway.realtime_workbench import (
    _phases_with_active_item as _phases_with_active_item,
)
from runtime.sensing.gateway.realtime_workbench import (
    _terminal_workbench_phases as _terminal_workbench_phases,
)
from runtime.sensing.gateway.realtime_workbench import (
    _todo_phase_status as _todo_phase_status,
)
from runtime.sensing.gateway.realtime_workbench import (
    _workbench_snapshot as _workbench_snapshot,
)
from runtime.sensing.gateway.realtime_workbench import (
    _workbench_status as _workbench_status,
)
from runtime.sensing.gateway.realtime_workbench import (
    _workspace_focus_for_file_change as _workspace_focus_for_file_change,
)
from runtime.sensing.gateway.realtime_workbench import (
    _workspace_focus_for_tool as _workspace_focus_for_tool,
)

_logger = logging.getLogger(__name__)


# ── Cerebrum runtime ──────────────────────────────────────────


class CerebrumRuntime:
    """Realtime runtime backed by the project's ReAct planner.

    Construct with the same execution stack the rest of the runtime
    uses. ``logs_root`` is the per-thread JSONL directory (same shape
    as :class:`EchoRuntime`).
    """

    def __init__(
        self,
        stack: Any,
        *,
        agent: Any = None,
        agent_registry: Any = None,
        logs_root: str = "data/threads",
        max_iterations: int = 30,
        policy_path: Any = None,
        workspace_root: Any = None,
        compaction_policy: Any = None,
        summary_router: Any = None,
        thread_store: Any = None,
        allow_client_auto_approve: bool = False,
        reflex_router: Any = None,
        trace_store: Any = None,
        cowork_group_store: Any = None,
    ) -> None:
        """Wire a CerebrumRuntime onto an existing octopus stack.

        ``agent`` is the default agent — used when the turn params don't
        specify one. ``agent_registry`` lets the runtime resolve a
        per-turn agent from ``params['agent']`` (typically the assistant
        id picked by the UI). Either or both may be ``None``; the
        underlying react_loop also accepts a None agent and falls back
        to its catch-all skill catalogue.

        ``policy_path`` points at the ``permissions.json`` the UI writes
        to when the user clicks "always trust". None = no static layer,
        every approval round-trips through the gateway.

        ``workspace_root`` is the directory where per-thread isolated
        workspaces are allocated. When None, the runtime does not
        auto-allocate: turns use whatever ``cwd`` the client supplies
        (or None). When set, turns without an explicit cwd default to
        ``<workspace_root>/<thread_id>/``, giving parallel threads
        collision-free filesystem scope — each thread gets its own
        directory, so two concurrent threads can't write to the
        same file.

        ``compaction_policy`` enables automatic turn-compaction after
        each completed turn (bounded context window). None disables
        compaction entirely. When ``summary_router`` is also
        provided, an LLM-backed summariser is wired in — otherwise the
        mechanical default (deterministic prose) is used.
        """
        self._stack = stack
        self._default_agent = agent
        self._agent_registry = agent_registry
        self._logs_root = logs_root
        self._max_iterations = max_iterations
        self._policy_path = policy_path
        self._compaction_policy = compaction_policy
        self._summary_router = summary_router
        # Optional handle to the legacy ``ThreadStateStore`` so each
        # completed realtime turn can write a flattened AgentThreadState
        # snapshot. The workspace sidebar's "recent chats" list reads
        # from that store; without this bridge, realtime conversations
        # would never appear in the history grouping (today / 7d / 30d).
        self._thread_store = thread_store
        self._reflex_router = reflex_router
        self._trace_store = trace_store
        self._cowork_group_store = cowork_group_store
        # Server-side authority over auto-approval. When False (default),
        # a client setting ``approvalPolicy="never"`` is downgraded to
        # ``"on-request"`` server-side — the client never gets to silently
        # disable approval gates. Operators who genuinely want headless
        # batches must opt in at config time.
        self._allow_client_auto_approve = bool(allow_client_auto_approve)
        from pathlib import Path

        Path(logs_root).mkdir(parents=True, exist_ok=True)
        self._proposal_ledger_path = Path(logs_root).parent / "proposal_ledger.jsonl"
        self._workspaces: Any = None
        if workspace_root is not None:
            from runtime.platform.runtime_policy.workspaces import WorkspaceManager

            self._workspaces = WorkspaceManager(Path(workspace_root))
        self._known_threads: set[str] = set()
        self._lock = asyncio.Lock()
        self._active_turn_ids: set[str] = set()
        self._compaction_locks: dict[str, asyncio.Lock] = {}
        self._compaction_locks_guard = asyncio.Lock()
        self._pending_resume_intents: dict[str, dict[str, Any]] = {}
        self._resume_intents_lock = asyncio.Lock()
        # Per-thread registry of background command watchers. Each
        # ``track_background_tool`` call registers its asyncio task
        # here; the next turn on the same thread reaps any still-
        # running entries before it begins. Without this, watchers
        # outlive their turn (by design — long shells must keep
        # streaming after the LLM finalises) but they CAN bleed into
        # a brand-new conversation when the user reuses the thread.
        self._thread_background_tasks: dict[str, list[asyncio.Task[None]]] = {}

    def _make_bridge_state(self, thread_id: str) -> _ReactBridgeState:
        """Build a ``_ReactBridgeState`` wired to the per-thread
        background-task registry, so the next turn on this thread can
        sweep any watchers the previous turn left running."""

        def _register(task: asyncio.Task[None]) -> None:
            bucket = self._thread_background_tasks.setdefault(thread_id, [])
            bucket.append(task)
            # Auto-clean when the task finishes naturally — keeps the
            # bucket bounded for long-lived threads.
            task.add_done_callback(lambda t: _safe_list_remove(bucket, t))

        return _ReactBridgeState(on_background_task_start=_register)

    # ── Turn telemetry records (bodies in realtime_turn_outcome) ──

    def _record_task_run_started(
        self,
        turn: Turn,
        *,
        text: str,
        params: TurnParams,
    ) -> None:
        _record_task_run_started(self, turn, text=text, params=params)

    def _record_task_run_finished(self, turn: Turn) -> None:
        _record_task_run_finished(self, turn)

    def _record_react_trace_event(self, turn: Turn, evt: dict[str, Any]) -> None:
        _record_react_trace_event(self, turn, evt)

    def _record_failed_turn_proposal(
        self,
        turn: Turn,
        *,
        intent: ParsedIntent | None,
        failure_source: str,
    ) -> None:
        _record_failed_turn_proposal(self, turn, intent=intent, failure_source=failure_source)

    def _record_successful_turn_example(
        self,
        turn: Turn,
        *,
        intent: ParsedIntent | None,
    ) -> None:
        _record_successful_turn_example(self, turn, intent=intent)

    async def _reap_stale_background_tasks(self, thread_id: str) -> None:
        """Cancel and reap any background watchers from prior turns
        on this thread before a new turn begins.

        Called at the top of ``start_turn``. ``done`` tasks are
        already pruned by the registration done-callback, so this
        loop only fires for actually-still-running watchers — the
        common case (new turn after the prior one finished cleanly)
        is a no-op.
        """
        bucket = self._thread_background_tasks.get(thread_id)
        if not bucket:
            return
        stale = [t for t in bucket if not t.done()]
        if not stale:
            self._thread_background_tasks.pop(thread_id, None)
            return
        for task in stale:
            task.cancel()
        for task in stale:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        # Drop the whole bucket; done-callbacks may still fire and
        # try to remove from a stale list, but ``_safe_list_remove``
        # tolerates missing entries.
        self._thread_background_tasks.pop(thread_id, None)

    def _resolve_agent(self, params: TurnParams) -> Any:
        """Pick the agent for this turn.

        Lookup order:
          1. Realtime input metadata (``agent_id`` / ``agent`` /
             ``agent_name``), including the nested ``context`` bag the
             web UI sends on ``turn/start``.
          2. The registry's match for that id, if any.
          3. The default agent passed at construction time.
          4. ``None``.
        """
        agent_id: str | None = None
        for block in params.input:
            md = block.get("metadata") if isinstance(block, dict) else None
            if not isinstance(md, dict):
                continue
            candidates: list[Any] = [md.get("agent_id"), md.get("agent"), md.get("agent_name")]
            context = md.get("context")
            if isinstance(context, dict):
                candidates.extend(
                    [
                        context.get("agent_id"),
                        context.get("agent"),
                        context.get("agent_name"),
                    ]
                )
            agent_id = next(
                (value.strip() for value in candidates if isinstance(value, str) and value.strip()),
                None,
            )
            if agent_id:
                break
        if agent_id and self._agent_registry is not None:
            try:
                if self._agent_registry.has(agent_id):
                    return self._agent_registry.get(agent_id)
            except (AttributeError, TypeError, OSError):  # noqa: BLE001 — agent lookup failed; fall back to default
                pass
        return self._default_agent

    def _wrap_with_policy(self, fallback: ApprovalProvider) -> ApprovalProvider:
        """Two-layer permission: static rules first, fallback otherwise.

        Reads ``permissions.json`` on every turn so UI-initiated edits
        (the "always trust" button) take effect immediately without
        bouncing the runtime. The file is small (a handful of rules)
        so the IO cost is irrelevant compared to a turn's LLM calls.
        """
        from pathlib import Path

        if self._policy_path is None:
            return fallback
        path = Path(self._policy_path)
        policy = load_policy(path)
        if not policy.rules:
            return fallback
        from runtime.safety.audit.trust_gateway import TrustGatewayApprovalProvider

        return TrustGatewayApprovalProvider(
            static_policy=policy,
            fallback=fallback,
            trace_store=getattr(self, "_trace_store", None),
            turn_id=getattr(fallback, "_turn_id", None),
            agent_id=getattr(getattr(self, "_default_agent", None), "agent_id", None),
        )

    # ── Compaction (bodies in realtime_thread_ops) ────────────

    async def _maybe_compact(
        self,
        thread_id: str,
        log: EventLog,
        emitter: EventEmitter,
    ) -> None:
        await _maybe_compact(self, thread_id, log, emitter)

    async def _compaction_lock_for(self, thread_id: str) -> asyncio.Lock:
        return await _compaction_lock_for(self, thread_id)

    async def _maybe_compact_locked(
        self,
        thread_id: str,
        log: EventLog,
        emitter: EventEmitter,
    ) -> None:
        await _maybe_compact_locked(self, thread_id, log, emitter)

    def _log_for(self, thread_id: str) -> EventLog:
        from runtime.memory.threads.event_log import thread_log_path

        return EventLog(thread_log_path(self._logs_root, thread_id))

    def _require_thread_id(self, value: Any) -> str:
        from runtime.memory.threads.event_log import validate_thread_id

        if not isinstance(value, str):
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, "threadId required")
        try:
            return validate_thread_id(value)
        except ValueError as exc:
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from exc

    def _require_thread_owner(self, log: EventLog, actor_id: str | None) -> None:
        from runtime.memory.threads.event_log import owner_actor_id_from_turns

        owner = owner_actor_id_from_turns(log.replay())
        if owner is not None and actor_id != owner:
            raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {log.path.stem}")

    def _resume_turns(self, log: EventLog) -> list[Turn]:
        """Replay and close in-progress turns left by an older process."""
        turns = log.replay()
        if not turns:
            return turns
        stale = [
            turn
            for turn in turns
            if turn.status == TurnStatus.IN_PROGRESS and turn.id not in self._active_turn_ids
        ]
        for turn in stale:
            turn.status = TurnStatus.FAILED
            turn.error = {
                "message": "上次执行在后端重启或连接中断时未完成，已自动结束。请重新发送或点击重试。",
                "code": "stale_in_progress_turn",
            }
            turn.completed_at = now_utc()
            for item in turn.items:
                if item.status == ItemStatus.IN_PROGRESS:
                    item.status = ItemStatus.FAILED
            log.turn_completed(turn.thread_id, turn.id, turn.status, error=turn.error)
        return turns

    def _snapshot_to_thread_store(
        self,
        thread_id: str,
        log: EventLog,
        intent: ParsedIntent | None = None,
    ) -> None:
        """Flatten the realtime conversation into the legacy
        ``AgentThreadState`` shape and upsert it into ``ThreadStateStore``.

        Without this bridge, realtime turns live only in the per-thread
        JSONL event log under ``data/threads/`` and never surface in the
        sidebar's "recent chats" list, which reads ``ThreadStateStore``
        (``agents/<agent>/sessions/<thread>.jsonl`` + the legacy
        ``data/threads.jsonl`` index).

        Called after every turn — completed, failed, or interrupted —
        so a half-completed conversation still shows up in history.
        Failures here are swallowed: the realtime event log is the
        durable record; the legacy store is a derived cache for the
        sidebar.
        """
        store = self._thread_store
        if store is None:
            return
        try:
            turns = log.replay()
            messages, artifacts, todos = _flatten_turns_to_messages(turns)
            title = _title_from_messages(messages) or ""
            values: dict[str, Any] = {
                "title": title,
                "messages": messages,
                "artifacts": artifacts,
            }
            if todos is not None:
                values["todos"] = todos
            uc = (intent.user_context or {}) if intent is not None else {}
            metadata: dict[str, Any] = {}
            for key in (
                "mode",
                "agent",
                "agent_name",
                "workspace_path",
                "workspace_scope",
                "personal_workspace_path",
                "personal_workspace_enabled",
                "owner_actor_id",
                "actor_id",
            ):
                v = uc.get(key) if isinstance(uc, dict) else None
                if v is not None:
                    # ThreadStateStore.search() filters by ``metadata.agent``
                    # so we normalise the key name the sidebar expects.
                    metadata[
                        "agent"
                        if key == "agent_name"
                        else "owner_actor_id"
                        if key == "actor_id"
                        else key
                    ] = v
            store.ensure_thread(thread_id, metadata=metadata, values=values)
            store.update_state(
                thread_id,
                values=values,
                metadata=metadata if metadata else None,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.debug(
                "snapshot to thread_store skipped (%s: %s)",
                type(exc).__name__,
                exc,
                exc_info=True,
            )

    async def _ensure_thread(self, thread_id: str, emitter: EventEmitter) -> EventLog:
        log = self._log_for(thread_id)
        async with self._lock:
            if thread_id in self._known_threads:
                return log
            existed = log.path.exists() and log.path.stat().st_size > 0
            if not existed:
                log.thread_started(thread_id)
                await emitter.notify(
                    ServerMethod.THREAD_STARTED,
                    {"thread": {"id": thread_id}},
                )
            self._known_threads.add(thread_id)
        return log

    # ── RealtimeRuntime ──────────────────────────────────────

    async def start_turn(
        self,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> Turn:
        """Start a new turn in a realtime thread.

        The orchestration body lives in
        :func:`runtime.sensing.gateway.realtime_turn_lifecycle._start_turn`;
        this method keeps the public ``RealtimeRuntime`` surface (and
        subclass override point) stable.
        """
        return await _start_turn(self, params, emitter)

    async def _record_pending_resume_intent(
        self,
        thread_id: str,
        resume_intent: dict[str, Any],
    ) -> None:
        await _record_pending_resume_intent(self, thread_id, resume_intent)

    async def _consume_confirmed_resume_intent(
        self,
        thread_id: str,
        text: str,
    ) -> dict[str, Any] | None:
        return await _consume_confirmed_resume_intent(self, thread_id, text)

    async def handle_request(
        self,
        method: str,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> Any:
        if method in ("thread/resume", "thread/read"):
            thread_id = self._require_thread_id(params.get("threadId"))
            log = self._log_for(thread_id)
            self._require_thread_owner(log, getattr(emitter, "actor_id", None))
            summary = log.summary()
            if summary is not None and summary.archived:
                raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
            # Stale-turn closing must see the FULL replay; pagination
            # only slices the response.
            turns = self._resume_turns(log)
            raw_limit = params.get("limit")
            window, has_more = EventLog.paginate_turns(
                turns,
                limit=(
                    raw_limit
                    if isinstance(raw_limit, int) and not isinstance(raw_limit, bool)
                    else None
                ),
                before_turn_id=(
                    params.get("beforeTurnId")
                    if isinstance(params.get("beforeTurnId"), str)
                    else None
                ),
            )
            return {
                "thread": {"id": thread_id, "path": str(log.path)},
                "turns": [t.model_dump(by_alias=True, mode="json") for t in window],
                "totalTurns": len(turns),
                "hasMore": has_more,
            }
        if method == "thread/compact":
            thread_id = self._require_thread_id(params.get("threadId"))
            self._require_thread_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
            return await self.compact_thread(thread_id, emitter)
        if method == "thread/list":
            from runtime.memory.threads.event_log import list_threads

            include_archived = bool(params.get("includeArchived"))
            actor_id = getattr(emitter, "actor_id", None)
            summaries = list_threads(self._logs_root)
            items = []
            for summary in summaries:
                if not include_archived and summary.archived:
                    continue
                log = self._log_for(summary.thread_id)
                try:
                    self._require_thread_owner(log, actor_id)
                except _RpcError:
                    continue
                items.append(summary.model_dump(by_alias=True, mode="json"))
            return {"threads": items}
        if method == "thread/archive":
            from runtime.memory.threads.event_log import archive_thread

            thread_id = self._require_thread_id(params.get("threadId"))
            self._require_thread_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
            if not archive_thread(self._logs_root, thread_id):
                raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
            return {"threadId": thread_id, "archived": True}
        if method == "item/fileChange/hunkDecide":
            return await self._handle_hunk_decide(params, emitter)
        raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, method)

    async def compact_thread(
        self,
        thread_id: str,
        emitter: EventEmitter | None = None,
    ) -> dict[str, Any]:
        """Manually compact a thread (body in ``realtime_thread_ops``)."""
        return await compact_thread(self, thread_id, emitter)

    async def _handle_hunk_decide(
        self,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> dict[str, Any]:
        return await _handle_hunk_decide(self, params, emitter)

    def _resolve_hunk_path(self, thread_id: str, path_value: str) -> Path:
        return _resolve_hunk_path(self, thread_id, path_value)

    # ── Drivers ───────────────────────────────────────────────
    # Bodies live in ``realtime_react_stream`` / ``realtime_team_stream``;
    # these thin methods keep the original call surface (and subclass
    # override points) stable.

    def _should_use_reflection_fast_path(
        self,
        text: str,
        params: TurnParams,
        *,
        conversation_messages: list[dict[str, object]] | None = None,
    ) -> bool:
        return _should_use_reflection_fast_path(
            self,
            text,
            params,
            conversation_messages=conversation_messages,
        )

    async def _drive_reflection_fast_path(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        agent: Any,
        *,
        model: str | None = None,
    ) -> None:
        await _drive_reflection_fast_path(self, turn, log, emitter, intent, agent, model=model)

    def _try_reflex_reply(self, intent: ParsedIntent) -> str | None:
        return _try_reflex_reply(self, intent)

    async def _drive_team_topology(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        *,
        text: str,
        topology_id: str,
    ) -> None:
        await _drive_team_topology(
            self, turn, log, emitter, intent, text=text, topology_id=topology_id
        )

    async def _drive_swarm_mesh(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        *,
        text: str,
        topology_id: str = "",
    ) -> None:
        await _drive_swarm_mesh(
            self,
            turn,
            log,
            emitter,
            intent,
            text=text,
            topology_id=topology_id,
        )

    async def _drive_group_fanout(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        *,
        text: str,
    ) -> None:
        await _drive_group_fanout(
            self,
            turn,
            log,
            emitter,
            intent,
            text=text,
        )

    async def _drive_react(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        provider: ApprovalProvider,
        agent: Any,
        *,
        model: str | None = None,
    ) -> None:
        await _drive_react(
            self, turn, log, emitter, intent, provider, agent, model=model,
        )

    async def _apply_react_event(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        state: _ReactBridgeState,
        evt: dict[str, Any],
    ) -> None:
        await _apply_react_event(self, turn, log, emitter, state, evt)

    async def _emit_item_started(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_item_completed(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: Any,
    ) -> None:
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_agent_message(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        text: str,
    ) -> None:
        item = AgentMessageItem(text=text)
        turn.items.append(item)
        await self._emit_item_started(turn, log, emitter, item)
        item.status = ItemStatus.COMPLETED
        await self._emit_item_completed(turn, log, emitter, item)

    def _is_local_partner(self, agent: Any) -> bool:
        """True when this agent should be driven by spawning its registered
        coding-agent CLI directly (Claude Code / Codex) instead of the LLM
        loop — i.e. its profile carries drivable ``local_partner`` capabilities."""
        from runtime.sensing.gateway.realtime_local_partner import agent_is_local_partner

        return agent_is_local_partner(agent)

    async def _drive_local_partner(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        intent: ParsedIntent,
        agent: Any,
        provider: ApprovalProvider,
        *,
        text: str,
    ) -> None:
        """Drive the agent's registered external coding-agent CLI directly —
        the missing execution half of LocalPartner. Delegates to the free
        function so the dispatch/fallback logic stays unit-testable."""
        from runtime.sensing.gateway.realtime_local_partner import drive_local_partner

        await drive_local_partner(self, turn, log, emitter, intent, agent, provider, text=text)


# Static check: this class fulfills the realtime contract.
_: RealtimeRuntime = CerebrumRuntime.__new__(CerebrumRuntime)  # type: ignore[arg-type]
del _


__all__ = ["CerebrumRuntime", "GatewayApprovalProvider"]
