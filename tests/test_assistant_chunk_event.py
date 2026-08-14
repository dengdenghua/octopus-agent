"""Parent-reply chunk journaling (dsh ``assistant/chunk``).

The react loop streams the user-visible final answer through
``text_delta`` events; each fragment is mirrored to the journal as an
``assistant/chunk`` event so the assistant's streamed text is
reconstructable from the log alone (dsh session-log invariant).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from runtime.core.cerebrum.react_loop_controls import _emit_assistant_chunk
from runtime.memory.journal import (
    AssistantChunkEvent,
    InMemoryJournal,
    JSONLJournal,
)
from runtime.memory.journal._journal_parse import _EVENT_CLASSES
from runtime.memory.journal.derive import (
    AssistantChunkStream,
    assert_logged_assistant_reconstructs,
    derive_assistant_stream,
)


def _stack_with(journal: InMemoryJournal) -> SimpleNamespace:
    return SimpleNamespace(journal=journal)


def test_event_class_is_registered_for_parse() -> None:
    assert _EVENT_CLASSES["assistant/chunk"] is AssistantChunkEvent


def test_event_roundtrips_through_jsonl(tmp_path: Path) -> None:
    task_id = uuid4()
    journal = JSONLJournal(tmp_path / "journal.jsonl")
    journal.write_assistant_chunk(iteration=2, delta="found it", task_id=str(task_id))

    events = journal.read_all()
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, AssistantChunkEvent)
    assert ev.iteration == 2
    assert ev.kind == "text-delta"
    assert ev.delta == "found it"
    assert str(ev.task_id) == str(task_id)


def test_write_assistant_chunk_writes_typed_event() -> None:
    journal = InMemoryJournal()
    journal.write_assistant_chunk(iteration=1, delta="你好")

    events = journal.read_all()
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, AssistantChunkEvent)
    assert ev.iteration == 1
    assert ev.delta == "你好"


def test_emit_noops_without_journal() -> None:
    """Best-effort: stack without a journal → no crash, no write."""

    _emit_assistant_chunk(SimpleNamespace(journal=None), iteration=1, delta="x")


def test_emit_writes_to_stack_journal() -> None:
    journal = InMemoryJournal()
    task_id = uuid4()
    _emit_assistant_chunk(
        _stack_with(journal),
        iteration=3,
        delta="answer chunk",
        task_id=str(task_id),
    )

    events = journal.read_all()
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, AssistantChunkEvent)
    assert ev.iteration == 3
    assert ev.delta == "answer chunk"
    assert str(ev.task_id) == str(task_id)


def test_emit_skips_empty_delta() -> None:
    journal = InMemoryJournal()
    _emit_assistant_chunk(_stack_with(journal), iteration=1, delta="")
    assert journal.read_all() == []


def test_derive_reconstructs_multi_iteration_text_in_order() -> None:
    journal = InMemoryJournal()
    journal.write_assistant_chunk(iteration=1, delta="第一段 ")
    journal.write_assistant_chunk(iteration=1, delta="续写")
    journal.write_assistant_chunk(iteration=2, delta="第二段")

    streams = derive_assistant_stream(journal)
    assert streams == [
        AssistantChunkStream(iteration=1, text="第一段 续写", chunk_count=2),
        AssistantChunkStream(iteration=2, text="第二段", chunk_count=1),
    ]


def test_derive_filters_by_iteration() -> None:
    journal = InMemoryJournal()
    journal.write_assistant_chunk(iteration=1, delta="A")
    journal.write_assistant_chunk(iteration=2, delta="B")

    streams = derive_assistant_stream(journal, iteration=2)
    assert streams == [
        AssistantChunkStream(iteration=2, text="B", chunk_count=1)
    ]


def test_derive_empty_journal_yields_nothing() -> None:
    assert derive_assistant_stream(InMemoryJournal()) == []


def test_derive_skips_non_chunk_events() -> None:
    journal = InMemoryJournal()
    journal.write_assistant_chunk(iteration=1, delta="live")
    journal.write_user_message("普通消息")
    journal.write_goal_change({"kind": "goal/change", "operation": "clear"})

    streams = derive_assistant_stream(journal)
    assert streams == [
        AssistantChunkStream(iteration=1, text="live", chunk_count=1)
    ]


def test_assert_logged_assistant_reconstructs_roundtrip() -> None:
    journal = InMemoryJournal()
    journal.write_assistant_chunk(iteration=1, delta="hi ")
    journal.write_assistant_chunk(iteration=1, delta="there")

    assert_logged_assistant_reconstructs(
        journal,
        [AssistantChunkStream(iteration=1, text="hi there", chunk_count=2)],
    )
