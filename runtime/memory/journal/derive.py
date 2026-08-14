"""Project model-visible history from the journal (dsh session-log idea).

dsh's core invariant: **model-visible means logged** — anything that
reaches a model request must be reconstructable from the session log,
and raw assistant/tool events preserve replay and audit fidelity.

This module is the projection layer for Octopus: it rebuilds the
assistant ``tool_use`` / user ``tool_result`` message sequence from
``StepEvent`` rows. A caller can therefore resume or audit a turn from
the journal alone, without holding the original in-memory message list,
and a test can prove "the model saw exactly what the journal recorded".

The projection is deliberately lossy where the model contract allows:
tool outputs flatten to strings (matching the anthropic router's
``str(content)`` fallback) and timestamps/costs are dropped. User intent
is not yet a journal event type, so ``user_intent`` is supplied by the
caller until a user-message event type lands.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from runtime.memory.journal._journal_base import Journal
from runtime.memory.journal._journal_models import StepEvent
from runtime.platform.models import TaskId
from runtime.platform.models.llm import Message


def _flatten_output(output: Any) -> str:
    """Render a tool result as the model-facing string.

    Mirrors the anthropic router's flattening: strings pass through,
    structured values serialize deterministically.
    """

    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)


def derive_model_messages(
    journal: Journal,
    *,
    task_id: TaskId | None = None,
    user_intent: str | None = None,
    max_steps: int | None = None,
) -> list[Message]:
    """Rebuild model-visible messages from the journal's ``StepEvent`` rows.

    Each recorded step projects to two messages:

    1. assistant — one ``tool_use`` content block (id = the recorded
       ``ToolCall.call_id``, so providers that correlate tool results
       by id see a consistent pair).
    2. user — one ``tool_result`` content block referencing that id.

    ``user_intent`` becomes the leading user message when supplied.
    ``max_steps`` keeps only the tail of the step stream (context
    window pressure). Order follows journal order — the journal is
    append-only, so that is execution order.
    """

    events = journal.read_all()
    steps: list[StepEvent] = [e for e in events if e.event_type == "step"]
    if task_id is not None:
        wanted = str(task_id)
        steps = [e for e in steps if str(e.task_id) == wanted]
    if max_steps is not None:
        steps = steps[-max_steps:]

    messages: list[Message] = []
    if user_intent:
        messages.append(Message(role="user", content=user_intent))

    for event in steps:
        call = event.step.action
        result = event.step.result
        messages.append(
            Message(
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": str(call.call_id),
                        "name": str(call.sucker_id),
                        "input": call.args,
                    }
                ],
            )
        )
        messages.append(
            Message(
                role="user",
                content=[
                    {
                        "type": "tool_result",
                        "tool_use_id": str(call.call_id),
                        "content": _flatten_output(result.output),
                    }
                ],
            )
        )
    return messages


@dataclass(frozen=True)
class SubagentRoundStream:
    """One role's streamed prose for one round, rebuilt from the journal.

    ``text`` is the exact concatenation of that round's
    ``sub_text_delta`` deltas in journal order; ``chunk_count`` is how
    many chunks the log recorded (proves per-chunk fidelity, not just
    an opaque final string).
    """

    role_id: str
    round: int
    text: str
    chunk_count: int


def derive_subagent_streams(
    journal: Journal,
    *,
    role_id: str | None = None,
) -> list[SubagentRoundStream]:
    """Reconstruct each role's streamed prose from ``SubTextDeltaEvent`` rows.

    The dsh session-log invariant applied to sub-agent turns: the
    prose a role streamed is recoverable from the append-only journal
    alone, in journal order, grouped by ``(role_id, round)``. Rounds
    that streamed no text contribute nothing; roles are returned in
    first-seen order.
    """

    streams: dict[tuple[str, int], list[str]] = {}
    order: list[tuple[str, int]] = []
    for event in journal.read_all():
        if event.event_type != "sub_text_delta":
            continue
        # ``getattr`` guards against an untyped fallback row (unknown
        # event_type decodes to the base JournalEvent).
        event_role = getattr(event, "role_id", "") or ""
        event_round = int(getattr(event, "round", 0) or 0)
        if role_id is not None and event_role != role_id:
            continue
        key = (event_role, event_round)
        if key not in streams:
            streams[key] = []
            order.append(key)
        streams[key].append(getattr(event, "delta", "") or "")
    return [
        SubagentRoundStream(
            role_id=key[0],
            round=key[1],
            text="".join(streams[key]),
            chunk_count=len(streams[key]),
        )
        for key in order
    ]


def assert_logged_stream_reconstructs(
    journal: Journal,
    expected: list[SubagentRoundStream],
    *,
    role_id: str | None = None,
) -> None:
    """Assert the journal reconstructs the given streamed prose — round-trip.

    Mirrors ``assert_logged_history_reconstructs`` for the sub-agent
    prose lane: call from tests and audit paths that must prove the
    stream a role produced is fully recoverable from the log.
    """

    actual = derive_subagent_streams(journal, role_id=role_id)
    assert actual == expected, (
        f"derived {len(actual)} round-streams, expected {len(expected)}"
    )


def assert_logged_history_reconstructs(
    journal: Journal,
    expected_steps: list[StepEvent],
    *,
    task_id: TaskId | None = None,
) -> None:
    """Assert the journal reconstructs the given steps — the round-trip.

    The dsh invariant "model-visible means logged" reduces to: a step
    written to the journal derives back to the same tool_use id, tool
    name, and input. Call this from tests and from audit paths that
    must prove a transcript is complete.
    """

    messages = derive_model_messages(journal, task_id=task_id)
    tool_uses = [
        block
        for message in messages
        if isinstance(message.content, list)
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]
    assert len(tool_uses) == len(expected_steps), (
        f"derived {len(tool_uses)} tool_use blocks, expected {len(expected_steps)}"
    )
    for block, expected in zip(tool_uses, expected_steps, strict=True):
        call = expected.step.action
        assert block["id"] == str(call.call_id)
        assert block["name"] == str(call.sucker_id)
        assert block["input"] == call.args
