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
    anchor = next((t for t in texts if "上一轮任务进行到" in (t or "")), None)
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


# ── history rehydration · an uploaded image outlives its own turn ─
#
# Assembly drops the last history entry and rebuilds it from
# ``user_context["attachments"]``, so an image only ever reached the model on
# the turn it was sent. A follow-up question about that same picture ("what's
# in the top-left?") arrived with no picture attached.

_PNG_1PX = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _append_image_turn(
    log: EventLog,
    thread_id: str,
    user_text: str,
    assistant_text: str | None = None,
    *,
    data_url: str = _PNG_1PX,
    filename: str = "shot.png",
) -> None:
    turn = Turn(
        threadId=thread_id,
        params=TurnParams(threadId=thread_id, input=[{"type": "text", "text": user_text}]),
    )
    log.turn_started(thread_id, turn)
    user = UserMessageItem(
        text=user_text,
        attachments=[
            {
                "filename": filename,
                "mediaType": "image/png",
                "data_url": data_url,
                "path": f"/w/{filename}",
            }
        ],
    )
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


def test_past_image_upload_is_rehydrated_for_followup(tmp_path) -> None:
    thread_id = "thread-image-history"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_image_turn(log, thread_id, "这是什么", "一张图片。")
    _append_message_turn(log, thread_id, "左上角是什么颜色")

    history = _conversation_messages_for_react(log.replay())

    first = history[0]
    assert isinstance(first["content"], list), "past image turn must stay multimodal"
    assert [b["type"] for b in first["content"]] == ["text", "image_url"]
    assert first["content"][0]["text"] == "这是什么"
    assert first["content"][1]["image_url"]["url"] == _PNG_1PX
    assert "_attachment_id" not in first, "internal join key must not leak to the model"
    assert history[-1] == {"role": "user", "content": "左上角是什么颜色"}


def test_current_turn_image_is_not_duplicated_into_history(tmp_path) -> None:
    """The last entry is rebuilt by assembly — spending budget on it wastes tokens."""

    thread_id = "thread-image-current"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_image_turn(log, thread_id, "看这张图")

    history = _conversation_messages_for_react(log.replay())

    assert history[-1] == {"role": "user", "content": "看这张图"}


def test_history_image_budget_keeps_the_newest(tmp_path) -> None:
    thread_id = "thread-image-budget"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    for index in range(4):
        _append_image_turn(log, thread_id, f"图{index}", "收到。", filename=f"s{index}.png")
    _append_message_turn(log, thread_id, "再看看")

    history = _conversation_messages_for_react(log.replay(), max_history_images=2)

    multimodal = [m for m in history if isinstance(m["content"], list)]
    assert len(multimodal) == 2
    assert [m["content"][0]["text"] for m in multimodal] == ["图2", "图3"]
    assert all(isinstance(m["content"], str) for m in history if m not in multimodal)


def test_history_image_byte_budget_skips_oversized(tmp_path) -> None:
    """A phone screenshot is MiB-scale base64; the count cap alone is not a budget."""

    thread_id = "thread-image-bytes"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    fat = "data:image/png;base64," + ("A" * 200_000)
    _append_image_turn(log, thread_id, "大图", "收到。", data_url=fat)
    _append_image_turn(log, thread_id, "小图", "收到。")
    _append_message_turn(log, thread_id, "对比一下")

    history = _conversation_messages_for_react(
        log.replay(),
        max_history_image_bytes=50_000,
    )

    multimodal = [m for m in history if isinstance(m["content"], list)]
    assert [m["content"][0]["text"] for m in multimodal] == ["小图"]
    assert history[0] == {"role": "user", "content": "大图"}


def test_history_images_can_be_disabled(tmp_path) -> None:
    thread_id = "thread-image-off"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_image_turn(log, thread_id, "这是什么", "一张图片。")
    _append_message_turn(log, thread_id, "继续")

    history = _conversation_messages_for_react(log.replay(), max_history_images=0)

    assert all(isinstance(m["content"], str) for m in history)


def test_relative_artifact_url_is_not_rehydrated(tmp_path) -> None:
    """A hosted-only upload has no provider-fetchable URL; text must survive alone."""

    thread_id = "thread-image-relative"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    turn = Turn(
        threadId=thread_id,
        params=TurnParams(threadId=thread_id, input=[{"type": "text", "text": "看图"}]),
    )
    log.turn_started(thread_id, turn)
    user = UserMessageItem(
        text="看图",
        attachments=[
            {
                "filename": "hosted.png",
                "mediaType": "image/png",
                "artifact_url": f"/api/threads/{thread_id}/artifacts/hosted.png",
            }
        ],
    )
    turn.items.append(user)
    log.item_started(thread_id, turn.id, user)
    user.status = ItemStatus.COMPLETED
    log.item_completed(thread_id, turn.id, user)
    turn.status = TurnStatus.COMPLETED
    log.turn_completed(thread_id, turn.id, turn.status)
    _append_message_turn(log, thread_id, "然后呢")

    history = _conversation_messages_for_react(log.replay())

    assert history[0] == {"role": "user", "content": "看图"}


def _append_tool_turn(
    log: EventLog,
    thread_id: str,
    user_text: str,
    assistant_text: str,
    tools: list[str],
) -> None:
    """Append a turn whose AI message carries tool calls."""

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
    for tool in tools:
        cmd = CommandExecutionItem(command=tool)
        cmd.status = ItemStatus.COMPLETED
        turn.items.append(cmd)
        log.item_started(thread_id, turn.id, cmd)
        log.item_completed(thread_id, turn.id, cmd)
    assistant = AgentMessageItem(text=assistant_text)
    turn.items.append(assistant)
    log.item_started(thread_id, turn.id, assistant)
    assistant.status = ItemStatus.COMPLETED
    log.item_completed(thread_id, turn.id, assistant)
    turn.status = TurnStatus.COMPLETED
    log.turn_completed(thread_id, turn.id, turn.status)


def test_tool_summary_never_rides_inside_assistant_content(tmp_path) -> None:
    """Scaffolding in the assistant lane gets echoed back as the model's own prose.

    Regression: the summary used to be prepended to the AI message, so the
    model read ``[上轮操作: web_search]`` as something it had said and quoted
    it in later replies, leaking the marker into user-visible output.
    """

    thread_id = "thread-tool-note"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_tool_turn(log, thread_id, "今天宜休么", "今天是七夕。", ["web_search"])
    _append_message_turn(log, thread_id, "那明天呢")

    history = _conversation_messages_for_react(log.replay())

    assistant = [m for m in history if m["role"] == "assistant"]
    assert assistant, history
    for message in assistant:
        assert "上轮操作" not in str(message["content"])
        # Assert on the tool name, not on the note's wording: a phrasing-based
        # assertion goes vacuous the moment the note is reworded.
        assert "web_search" not in str(message["content"])
        assert message["content"] == "今天是七夕。"


def test_tool_summary_is_emitted_as_a_system_note_after_the_turn(tmp_path) -> None:
    thread_id = "thread-tool-note-order"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_tool_turn(log, thread_id, "查一下", "查完了。", ["web_search", "read_file"])
    _append_message_turn(log, thread_id, "继续")

    history = _conversation_messages_for_react(log.replay())

    roles = [m["role"] for m in history]
    notes = [i for i, m in enumerate(history) if m["role"] == "system"]
    assert len(notes) == 1, history
    index = notes[0]
    # The note explains the assistant turn it trails, so order is part of the contract.
    assert roles[index - 1] == "assistant"
    assert "web_search, read_file" in history[index]["content"]
    assert "never quote it" in history[index]["content"]
    # No private bookkeeping keys survive into the payload handed to the model.
    assert all("_tool_note" not in m for m in history)


def test_tool_note_orphaned_by_truncation_is_dropped(tmp_path) -> None:
    thread_id = "thread-tool-note-trunc"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_tool_turn(log, thread_id, "第一轮", "做完了。", ["web_search"])
    _append_message_turn(log, thread_id, "第二轮", "好的。")

    # max_messages=3 slices mid-note: user/assistant/note/user/assistant -> note first.
    history = _conversation_messages_for_react(log.replay(), max_messages=3)

    assert history[0]["role"] != "system", history


def test_tool_note_is_self_anchoring_across_provider_translation(tmp_path) -> None:
    """The note must still identify its turn after provider translation.

    anthropic/gemini hoist every ``system`` message into the top-level system
    prompt, so a note saying "the previous turn" would lose its referent. This
    runs the real translators, not stubs.
    """
    from runtime.platform.models.llm import Message
    from runtime.sensing.model_router.anthropic_router import _split_system
    from runtime.sensing.model_router.gemini_router import _split_system_and_contents
    from runtime.sensing.model_router.openai_router import _messages_to_openai

    thread_id = "thread-tool-note-providers"
    log = EventLog(tmp_path / f"{thread_id}.jsonl")
    log.thread_started(thread_id)
    _append_tool_turn(log, thread_id, "今天几号", "今天是七夕。", ["web_search"])

    history = _conversation_messages_for_react(log.replay())
    msgs = [Message(role=m["role"], content=m["content"]) for m in history]

    # anthropic: note lands in the hoisted system arg, still naming its turn.
    sys_arg, rest = _split_system(msgs)
    assert "web_search" in sys_arg
    assert "今天是七夕。" in sys_arg, sys_arg
    assert all("web_search" not in str(m.get("content", "")) for m in rest), rest

    # gemini: same hoisting, same anchoring.
    sys_parts, contents = _split_system_and_contents(msgs)
    joined = "\n".join(sys_parts)
    assert "web_search" in joined and "今天是七夕。" in joined, joined
    assert all("web_search" not in str(c) for c in contents), contents

    # openai keeps position: note trails its assistant message.
    out = _messages_to_openai(msgs)
    note_at = [i for i, m in enumerate(out) if "web_search" in str(m.get("content", ""))]
    assert len(note_at) == 1, out
    assert out[note_at[0]]["role"] == "system"
    assert out[note_at[0] - 1]["role"] == "assistant"
