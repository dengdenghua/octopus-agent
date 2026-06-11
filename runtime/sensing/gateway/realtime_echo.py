"""Echo runtime — reference :class:`RealtimeRuntime` implementation.

Demonstrates the full item-oriented turn loop without depending on an
LLM, planner, or skill registry. Every ``turn/start`` emits:

  1. ``thread/started`` (first time)
  2. ``turn/started``
  3. one ``reasoning`` item with streaming text
  4. one ``commandExecution`` item that goes through approval if the
     incoming approvalPolicy != "never"
  5. one ``agentMessage`` item streaming the user's input back
  6. ``turn/completed`` (auto-emitted by the gateway)

State is persisted to per-thread JSONL via ``EventLog``. Disconnect and
reconnect, call ``thread/resume``, and every item plus its accumulated
content reappears.

Use this as the integration test reference and as the template for
plugging real planners (e.g. ``cerebrum.react_loop.stream_react_loop``)
into the gateway later.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from runtime.memory.threads.event_log import (
    EventLog,
    actor_id_from_turn_params,
    owner_actor_id_from_turns,
    thread_log_path,
    validate_thread_id,
)
from runtime.protocol import (
    AgentMessageItem,
    CommandExecutionItem,
    ItemStatus,
    JsonRpcErrorCode,
    ReasoningItem,
    ServerMethod,
    Turn,
    TurnParams,
    TurnStatus,
)
from runtime.sensing.gateway.realtime_gateway import EventEmitter, RealtimeRuntime


class EchoRuntime:
    """Single-process runtime with file-backed event logs.

    ``logs_root`` defaults to ``./data/threads`` and is created on
    demand. Each thread gets ``<logs_root>/<thread_id>.jsonl``.
    """

    def __init__(self, logs_root: Path | str = "data/threads") -> None:
        self._logs_root = Path(logs_root)
        self._logs_root.mkdir(parents=True, exist_ok=True)
        # Tracks which threads have already had their thread_started
        # event written, so resume + new turn don't double-log.
        self._known_threads: set[str] = set()
        self._lock = asyncio.Lock()

    def _log_for(self, thread_id: str) -> EventLog:
        return EventLog(thread_log_path(self._logs_root, thread_id))

    def _require_thread_id(self, value: Any) -> str:
        from runtime.sensing.gateway.realtime_gateway import _RpcError

        if not isinstance(value, str):
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, "threadId required")
        try:
            return validate_thread_id(value)
        except ValueError as exc:
            raise _RpcError(JsonRpcErrorCode.INVALID_PARAMS, str(exc)) from exc

    def _require_owner(self, log: EventLog, actor_id: str | None) -> None:
        from runtime.sensing.gateway.realtime_gateway import _RpcError

        owner = owner_actor_id_from_turns(log.replay())
        if owner is not None and actor_id != owner:
            raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {log.path.stem}")

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
        validated = TurnParams.model_validate(params)
        thread_id = validated.thread_id
        self._require_thread_id(thread_id)
        log = await self._ensure_thread(thread_id, emitter)
        self._require_owner(log, actor_id_from_turn_params(validated) or getattr(emitter, "actor_id", None))

        turn = Turn(threadId=thread_id, params=validated)
        # Register *before* emitting turn/started so a racing
        # turn/interrupt delivered between turn/started and the first
        # yield still lands on this turn's flag.
        emitter.register_turn(turn.id)
        try:
            log.turn_started(thread_id, turn)
            await emitter.notify(
                ServerMethod.TURN_STARTED,
                {
                    "threadId": thread_id,
                    "turn": turn.model_dump(by_alias=True, mode="json"),
                },
            )

            user_text = _join_text(validated.input) or "<empty input>"

            if not await self._check_interrupt(turn, log, emitter):
                await self._emit_streaming_reasoning(turn, log, emitter, user_text)

            if (
                not await self._check_interrupt(turn, log, emitter)
                and validated.approval_policy != "never"
            ):
                await self._emit_command_with_approval(turn, log, emitter)

            if not await self._check_interrupt(turn, log, emitter):
                await self._emit_streaming_agent_message(turn, log, emitter, user_text)

            if turn.status == TurnStatus.IN_PROGRESS:
                turn.status = TurnStatus.COMPLETED
            log.turn_completed(thread_id, turn.id, turn.status, error=None)
            return turn
        finally:
            emitter.unregister_turn(turn.id)

    async def _check_interrupt(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
    ) -> bool:
        """Return True if the turn has been interrupted, marking it
        as such and persisting the terminal state.

        Callers skip any remaining work when this returns True, because
        both the turn status and the JSONL log are already finalized.
        """
        if turn.status != TurnStatus.IN_PROGRESS:
            return True
        if not emitter.is_turn_interrupted(turn.id):
            return False
        turn.status = TurnStatus.INTERRUPTED
        log.turn_completed(turn.thread_id, turn.id, turn.status, error=None)
        await emitter.notify(
            ServerMethod.TURN_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turn": turn.model_dump(by_alias=True, mode="json"),
            },
        )
        return True

    async def _interrupt_item(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        item: ReasoningItem | AgentMessageItem,
    ) -> bool:
        """Mid-delta interrupt check. If the turn has been interrupted,
        mark the in-flight item as INTERRUPTED, emit its completion,
        and let the outer stage boundary via ``_check_interrupt`` flip
        the turn to the terminal state and emit ``turn/completed``.

        Short inputs can race past every stage boundary because the
        TestClient / event-loop scheduling can push the ``turn/interrupt``
        handler task after the streaming task has already started
        emitting deltas. Polling the flag between deltas gives the
        interrupt a reliable observation window.
        """
        if turn.status != TurnStatus.IN_PROGRESS:
            return True
        if not emitter.is_turn_interrupted(turn.id):
            return False
        item.status = ItemStatus.INTERRUPTED
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )
        turn.status = TurnStatus.INTERRUPTED
        log.turn_completed(turn.thread_id, turn.id, turn.status, error=None)
        await emitter.notify(
            ServerMethod.TURN_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turn": turn.model_dump(by_alias=True, mode="json"),
            },
        )
        return True

    async def handle_request(
        self,
        method: str,
        params: dict[str, Any],
        emitter: EventEmitter,
    ) -> Any:
        if method == "thread/resume":
            return await self._handle_resume(params, emitter)
        if method == "thread/read":
            return await self._handle_resume(params, emitter)
        if method == "thread/list":
            return await self._handle_list(params, emitter)
        if method == "thread/archive":
            return await self._handle_archive(params, emitter)
        # Mirror the gateway behavior so callers see a clean
        # method-not-found rather than NotImplementedError noise.
        from runtime.sensing.gateway.realtime_gateway import (
            _RpcError,  # local import to dodge cycle
        )

        raise _RpcError(JsonRpcErrorCode.METHOD_NOT_FOUND, method)

    async def _handle_resume(self, params: dict[str, Any], emitter: EventEmitter) -> dict[str, Any]:
        thread_id = self._require_thread_id(params.get("threadId"))
        log = self._log_for(thread_id)
        self._require_owner(log, getattr(emitter, "actor_id", None))
        summary = log.summary()
        if summary is not None and summary.archived:
            from runtime.sensing.gateway.realtime_gateway import _RpcError

            raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
        turns = log.replay()
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

    async def _handle_list(self, params: dict[str, Any], emitter: EventEmitter) -> dict[str, Any]:
        from runtime.memory.threads.event_log import list_threads

        include_archived = bool(params.get("includeArchived"))
        actor_id = getattr(emitter, "actor_id", None)
        summaries = list_threads(self._logs_root)
        items = []
        for summary in summaries:
            if not include_archived and summary.archived:
                continue
            log = self._log_for(summary.thread_id)
            owner = owner_actor_id_from_turns(log.replay())
            if owner is not None and actor_id != owner:
                continue
            items.append(summary.model_dump(by_alias=True, mode="json"))
        return {"threads": items}

    async def _handle_archive(self, params: dict[str, Any], emitter: EventEmitter) -> dict[str, Any]:
        from runtime.memory.threads.event_log import archive_thread
        from runtime.sensing.gateway.realtime_gateway import _RpcError

        thread_id = self._require_thread_id(params.get("threadId"))
        self._require_owner(self._log_for(thread_id), getattr(emitter, "actor_id", None))
        if not archive_thread(self._logs_root, thread_id):
            raise _RpcError(JsonRpcErrorCode.THREAD_NOT_FOUND, f"unknown thread {thread_id}")
        return {"threadId": thread_id, "archived": True}

    # ── Item emitters ────────────────────────────────────────

    async def _emit_streaming_reasoning(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        user_text: str,
    ) -> None:
        item = ReasoningItem(content="")
        turn.items.append(item)
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

        for chunk in _chunked(f"Echoing back: {user_text!r}", size=8):
            if await self._interrupt_item(turn, log, emitter, item):
                return
            item.content += chunk
            log.item_delta(turn.thread_id, turn.id, item.id, "reasoning", chunk)
            await emitter.notify(
                ServerMethod.ITEM_REASONING_TEXT_DELTA,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "itemId": item.id,
                    "delta": chunk,
                    "contentIndex": 0,
                },
            )
            await asyncio.sleep(0)  # yield to other tasks

        if await self._interrupt_item(turn, log, emitter, item):
            return
        item.status = ItemStatus.COMPLETED
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_command_with_approval(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
    ) -> None:
        item = CommandExecutionItem(command="echo hello", actions=[])
        turn.items.append(item)
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

        try:
            decision = await emitter.request_approval(
                ServerMethod.REQ_COMMAND_APPROVAL,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "itemId": item.id,
                    "command": item.command,
                },
            )
        except (OSError, ConnectionError, TimeoutError):  # noqa: BLE001
            item.status = ItemStatus.DECLINED
            log.item_completed(turn.thread_id, turn.id, item)
            await emitter.notify(
                ServerMethod.ITEM_COMPLETED,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "item": item.model_dump(by_alias=True, mode="json"),
                },
            )
            return

        action = (decision or {}).get("action")
        if action == "accept":
            item.aggregated_output = "hello\n"
            item.exit_code = 0
            item.status = ItemStatus.COMPLETED
        else:
            item.status = ItemStatus.DECLINED

        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

    async def _emit_streaming_agent_message(
        self,
        turn: Turn,
        log: EventLog,
        emitter: EventEmitter,
        user_text: str,
    ) -> None:
        item = AgentMessageItem(text="")
        turn.items.append(item)
        log.item_started(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_STARTED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )

        for chunk in _chunked(user_text, size=4):
            if await self._interrupt_item(turn, log, emitter, item):
                return
            item.text += chunk
            log.item_delta(turn.thread_id, turn.id, item.id, "agentMessage", chunk)
            await emitter.notify(
                ServerMethod.ITEM_AGENT_MESSAGE_DELTA,
                {
                    "threadId": turn.thread_id,
                    "turnId": turn.id,
                    "itemId": item.id,
                    "delta": chunk,
                },
            )
            await asyncio.sleep(0)

        if await self._interrupt_item(turn, log, emitter, item):
            return
        item.status = ItemStatus.COMPLETED
        log.item_completed(turn.thread_id, turn.id, item)
        await emitter.notify(
            ServerMethod.ITEM_COMPLETED,
            {
                "threadId": turn.thread_id,
                "turnId": turn.id,
                "item": item.model_dump(by_alias=True, mode="json"),
            },
        )


def _join_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _chunked(s: str, *, size: int) -> list[str]:
    return [s[i : i + size] for i in range(0, len(s), size)] or [""]


# Statically declare the protocol bond so type checkers catch
# signature drift between EchoRuntime and the RealtimeRuntime contract.
_: RealtimeRuntime = EchoRuntime()
del _


__all__ = ["EchoRuntime"]
