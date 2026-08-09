from __future__ import annotations

from runtime.memory.threads.event_log import EventLog
from runtime.protocol import (
    AgentMessageItem,
    CommandExecutionItem,
    ErrorItem,
    ItemStatus,
    ReasoningItem,
    TodoEntry,
    TodoListItem,
    Turn,
    TurnParams,
    TurnStatus,
    UserMessageItem,
)
from runtime.sensing.gateway.realtime_cerebrum import (
    _build_intent,
    _conversation_messages_for_react,
)
from runtime.sensing.gateway.realtime_thread_history import _flatten_turns_to_messages


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


def _build_failed_turn(
    thread_id: str,
    user_text: str,
    *,
    draft_commentary: list[str],
    with_error_item: bool = False,
    answer_text: str | None = None,
) -> Turn:
    """Build a FAILED turn that carries stale intermediate drafts — the
    shape that previously leaked narrative into the next turn."""
    turn = Turn(
        threadId=thread_id,
        params=TurnParams(threadId=thread_id, input=[{"type": "text", "text": user_text}]),
        status=TurnStatus.FAILED,
    )
    user = UserMessageItem(text=user_text)
    user.status = ItemStatus.COMPLETED
    turn.items.append(user)

    for text in draft_commentary:
        draft = AgentMessageItem(text=text, message_kind="commentary")
        draft.status = ItemStatus.COMPLETED
        turn.items.append(draft)

    if answer_text:
        answer = AgentMessageItem(text=answer_text, message_kind="answer")
        answer.status = ItemStatus.COMPLETED
        turn.items.append(answer)

    reasoning = ReasoningItem(content="正在针对上一轮主题继续深入……")
    reasoning.status = ItemStatus.COMPLETED
    turn.items.append(reasoning)

    cmd = CommandExecutionItem(command="grep_text", input_preview={"query": "PolicyNet"})
    cmd.status = ItemStatus.COMPLETED
    turn.items.append(cmd)

    todo = TodoListItem(plan=[TodoEntry(title="神经网络性能验证", status="completed")])
    todo.status = ItemStatus.COMPLETED
    turn.items.append(todo)

    if with_error_item:
        err = ErrorItem(message="false-verification guard 拦截")
        err.status = ItemStatus.COMPLETED
        turn.items.append(err)
    return turn


def test_failed_turn_drafts_do_not_leak_into_next_react_context(tmp_path) -> None:
    """A FAILED turn's intermediate commentary / reasoning / tool chain must
    NOT be injected into the next turn's model context. Only the user prompt
    (and error summary, when present) survive; otherwise the model answers
    the previous unfinished question instead of the user's new one."""
    thread_id = "thread-failed-leak"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)

    failed = _build_failed_turn(
        thread_id,
        "神经网络真的有用么",
        draft_commentary=[
            "我在查找 PolicyNet 与传统算法的对比测试数据",
            "已找到关键性能数据：42µs / 881fps",
        ],
        with_error_item=True,
    )
    log.turn_started(thread_id, failed)
    for item in failed.items:
        log.item_started(thread_id, failed.id, item)
        log.item_completed(thread_id, failed.id, item)
    log.turn_completed(thread_id, failed.id, TurnStatus.FAILED)

    # A brand-new follow-up question unrelated to the failed turn.
    _append_message_turn(log, thread_id, "解读该项目", "")

    conversation_messages = _conversation_messages_for_react(log.replay())

    texts = [m["content"] for m in conversation_messages]
    # The stale draft narrative must NOT appear.
    assert not any("PolicyNet" in (t or "") for t in texts)
    assert not any("42µs" in (t or "") for t in texts)
    assert not any("神经网络性能验证" in (t or "") for t in texts)
    # The failed prompt is kept, the new question is kept.
    assert "神经网络真的有用么" in texts
    assert "解读该项目" in texts
    # The failure itself is surfaced (not silently dropped).
    assert any("上一轮任务失败" in (t or "") for t in texts)


def test_failed_turn_drafts_kept_for_sidebar_snapshot(tmp_path) -> None:
    """The sidebar snapshot must KEEP failed drafts so the user can review
    what went wrong — only the model-context path strips them."""
    thread_id = "thread-failed-sidebar"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)

    failed = _build_failed_turn(
        thread_id,
        "神经网络真的有用么",
        draft_commentary=["我在查找 PolicyNet 对比数据"],
    )
    log.turn_started(thread_id, failed)
    for item in failed.items:
        log.item_started(thread_id, failed.id, item)
        log.item_completed(thread_id, failed.id, item)
    log.turn_completed(thread_id, failed.id, TurnStatus.FAILED)

    messages, _, _ = _flatten_turns_to_messages(log.replay())
    texts = [str(m.get("content") or "") for m in messages]
    assert any("PolicyNet" in t for t in texts)


def test_failed_turn_answer_anchor_kept_in_next_react_context(tmp_path) -> None:
    """A FAILED turn keeps its last ``answer`` as a progress anchor for the
    next turn — the model needs to know what the run was doing and how far it
    got, not just that it failed. Commentary checkpoints still stay out."""
    thread_id = "thread-failed-anchor"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)

    failed = _build_failed_turn(
        thread_id,
        "神经网络真的有用么",
        draft_commentary=["我在查找 PolicyNet 与传统算法的对比测试数据"],
        answer_text="**任务被环境阻塞，需要你本地跑 pnpm typecheck 验证后我才能收尾。**",
        with_error_item=True,
    )
    log.turn_started(thread_id, failed)
    for item in failed.items:
        log.item_started(thread_id, failed.id, item)
        log.item_completed(thread_id, failed.id, item)
    log.turn_completed(thread_id, failed.id, TurnStatus.FAILED)

    _append_message_turn(log, thread_id, "解读该项目", "")

    conversation_messages = _conversation_messages_for_react(log.replay())
    texts = [m["content"] for m in conversation_messages]

    # The stale commentary draft still does NOT leak.
    assert not any("PolicyNet" in (t or "") for t in texts)
    # The user prompt, the failure marker and the progress anchor survive.
    assert "神经网络真的有用么" in texts
    assert any("上一轮任务失败" in (t or "") for t in texts)
    anchor = next(
        (t for t in texts if "上一轮任务进行到" in (t or "")), None
    )
    assert anchor is not None
    assert "任务被环境阻塞" in anchor
    assert "pnpm typecheck" in anchor


def test_failed_turn_without_answer_injects_no_progress_anchor(tmp_path) -> None:
    """A FAILED turn that never produced an ``answer`` (only commentary) must
    not inject a progress anchor — there is no conclusion to anchor on."""
    thread_id = "thread-failed-no-anchor"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)

    failed = _build_failed_turn(
        thread_id,
        "神经网络真的有用么",
        draft_commentary=["我在查找 PolicyNet 对比数据"],
    )
    log.turn_started(thread_id, failed)
    for item in failed.items:
        log.item_started(thread_id, failed.id, item)
        log.item_completed(thread_id, failed.id, item)
    log.turn_completed(thread_id, failed.id, TurnStatus.FAILED)

    _append_message_turn(log, thread_id, "解读该项目", "")

    conversation_messages = _conversation_messages_for_react(log.replay())
    texts = [m["content"] for m in conversation_messages]
    assert not any("上一轮任务进行到" in (t or "") for t in texts)
