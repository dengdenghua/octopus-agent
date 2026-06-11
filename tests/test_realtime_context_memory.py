from __future__ import annotations

from runtime.memory.threads.event_log import EventLog
from runtime.protocol import AgentMessageItem, ItemStatus, Turn, TurnParams, TurnStatus
from runtime.protocol.items import UserMessageItem
from runtime.sensing.gateway.realtime_cerebrum import (
    _build_intent,
    _conversation_messages_for_react,
)


def _append_message_turn(
    log: EventLog,
    thread_id: str,
    user_text: str,
    assistant_text: str | None = None,
) -> None:
    turn = Turn(
        threadId=thread_id,
        params=TurnParams(threadId=thread_id, input=[{"type": "text", "text": user_text}]),
    )
    log.turn_started(thread_id, turn)

    user = UserMessageItem(text=user_text)
    turn.items.append(user)
    log.item_started(thread_id, turn.id, user)
    user.status = ItemStatus.COMPLETED
    log.item_completed(thread_id, turn.id, user)

    if assistant_text is not None:
        assistant = AgentMessageItem(text=assistant_text)
        turn.items.append(assistant)
        log.item_started(thread_id, turn.id, assistant)
        assistant.status = ItemStatus.COMPLETED
        log.item_completed(thread_id, turn.id, assistant)

    turn.status = TurnStatus.COMPLETED
    log.turn_completed(thread_id, turn.id, turn.status)


def test_realtime_turn_history_is_available_to_react_loop(tmp_path) -> None:
    thread_id = "thread-context"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_message_turn(log, thread_id, "今天A股为什么大跌", "要我去查今天的实际情况吗？")
    _append_message_turn(log, thread_id, "去查呀")

    conversation_messages = _conversation_messages_for_react(log.replay())
    intent = _build_intent(
        "去查呀",
        TurnParams(threadId=thread_id, input=[{"type": "text", "text": "去查呀"}]),
        conversation_messages=conversation_messages,
    )

    assert intent.user_context["conversation_messages"] == [
        {"role": "user", "content": "今天A股为什么大跌"},
        {"role": "assistant", "content": "要我去查今天的实际情况吗？"},
        {"role": "user", "content": "去查呀"},
    ]
