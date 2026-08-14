"""Turn-level transcript bridge: ``sub_text_delta`` journal events.

dsh's session-log invariant is "model-visible means logged": the prose
a sub-agent streams must be reconstructable from the append-only log,
not only from the in-memory emitter callback. These tests cover the
event model, the emitter helper's journal mirror, and the derivation
that rebuilds per-role round prose from the log alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from runtime.execution.suckers._ephemeral_events import (
    _emit_sub_text_delta,
)
from runtime.memory.journal import (
    InMemoryJournal,
    JSONLJournal,
    SubTextDeltaEvent,
)
from runtime.memory.journal._journal_parse import _EVENT_CLASSES
from runtime.memory.journal.derive import (
    SubagentRoundStream,
    assert_logged_stream_reconstructs,
    derive_subagent_streams,
)
from runtime.platform.process.session import Session, session_scope


def _scoped_session_with_journal(journal: InMemoryJournal) -> Session:
    return Session(metadata={"journal": journal})


def test_event_class_is_registered_for_parse() -> None:
    assert _EVENT_CLASSES["sub_text_delta"] is SubTextDeltaEvent


def test_event_roundtrips_through_jsonl(tmp_path: Path) -> None:
    journal = JSONLJournal(tmp_path / "journal.jsonl")
    journal.write(
        SubTextDeltaEvent(
            role_id="researcher",
            round=2,
            delta="found vendor X",
            parent_tool_use_id="tool-1",
        )
    )

    events = journal.read_all()
    assert len(events) == 1
    ev = events[0]
    assert isinstance(ev, SubTextDeltaEvent)
    assert ev.role_id == "researcher"
    assert ev.round == 2
    assert ev.delta == "found vendor X"
    assert ev.parent_tool_use_id == "tool-1"


def test_emit_forwards_to_emitter_and_writes_journal() -> None:
    journal = InMemoryJournal()
    seen: list[dict[str, Any]] = []

    def emitter(event: dict[str, Any]) -> None:
        seen.append(event)

    with session_scope(_scoped_session_with_journal(journal)):
        _emit_sub_text_delta("researcher", 1, "你好", emitter=emitter)
        _emit_sub_text_delta("researcher", 1, "，世界", emitter=emitter)

    assert len(seen) == 2
    assert seen[0] == {
        "type": "sub_text_delta",
        "agent_id": "researcher",
        "round": 1,
        "delta": "你好",
    }
    assert seen[1]["delta"] == "，世界"

    events = journal.read_all()
    assert len(events) == 2
    for ev in events:
        assert isinstance(ev, SubTextDeltaEvent)
        assert ev.role_id == "researcher"
        assert ev.round == 1


def test_emit_noops_without_session() -> None:
    """Best-effort: no session bound → no crash, no journal write."""

    journal = InMemoryJournal()
    seen: list[dict[str, Any]] = []

    def emitter(event: dict[str, Any]) -> None:
        seen.append(event)

    _emit_sub_text_delta("researcher", 1, "solo", emitter=emitter)
    # The emitter still fires (pure in-memory forward); journal is absent.
    assert len(seen) == 1
    assert journal.read_all() == []


def test_derive_reconstructs_multi_round_prose_in_order() -> None:
    journal = InMemoryJournal()
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="第一步 "))
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="结论。"))
    journal.write(SubTextDeltaEvent(role_id="critic", round=1, delta="反对:证据不足"))
    journal.write(SubTextDeltaEvent(role_id="researcher", round=2, delta="补充数据"))

    streams = derive_subagent_streams(journal)
    assert streams == [
        SubagentRoundStream(role_id="researcher", round=1, text="第一步 结论。", chunk_count=2),
        SubagentRoundStream(role_id="critic", round=1, text="反对:证据不足", chunk_count=1),
        SubagentRoundStream(role_id="researcher", round=2, text="补充数据", chunk_count=1),
    ]


def test_derive_filters_by_role() -> None:
    journal = InMemoryJournal()
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="A"))
    journal.write(SubTextDeltaEvent(role_id="critic", round=1, delta="B"))

    streams = derive_subagent_streams(journal, role_id="critic")
    assert streams == [SubagentRoundStream(role_id="critic", round=1, text="B", chunk_count=1)]


def test_derive_empty_journal_yields_nothing() -> None:
    assert derive_subagent_streams(InMemoryJournal()) == []


def test_derive_skips_non_delta_events() -> None:
    journal = InMemoryJournal()
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="live text"))
    journal.write_user_message("普通消息")

    streams = derive_subagent_streams(journal)
    assert streams == [
        SubagentRoundStream(role_id="researcher", round=1, text="live text", chunk_count=1)
    ]


def test_assert_logged_stream_reconstructs_roundtrip() -> None:
    journal = InMemoryJournal()
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="hi "))
    journal.write(SubTextDeltaEvent(role_id="researcher", round=1, delta="there"))

    assert_logged_stream_reconstructs(
        journal,
        [SubagentRoundStream(role_id="researcher", round=1, text="hi there", chunk_count=2)],
    )


def test_emit_writes_session_id_to_journal() -> None:
    journal = InMemoryJournal()
    seen: list[dict[str, Any]] = []

    def emitter(event: dict[str, Any]) -> None:
        seen.append(event)

    with session_scope(_scoped_session_with_journal(journal)):
        _emit_sub_text_delta(
            "researcher",
            1,
            "needle",
            session_id="0123456789abcdef0123456789abcdef",
            emitter=emitter,
        )

    # The emitter payload is unchanged (no session_id leaks into SSE).
    assert seen[0] == {
        "type": "sub_text_delta",
        "agent_id": "researcher",
        "round": 1,
        "delta": "needle",
    }
    ev = journal.read_all()[0]
    assert ev.session_id == "0123456789abcdef0123456789abcdef"


def test_derive_filters_by_session_id() -> None:
    journal = InMemoryJournal()
    sid1 = "11111111111111111111111111111111"
    sid2 = "22222222222222222222222222222222"
    # Same role, two sessions — role_id alone cannot tell them apart.
    journal.write(SubTextDeltaEvent(session_id=sid1, role_id="researcher", round=1, delta="A"))
    journal.write(SubTextDeltaEvent(session_id=sid2, role_id="researcher", round=1, delta="B"))

    assert [(s.session_id, s.text) for s in derive_subagent_streams(journal)] == [
        (sid1, "A"),
        (sid2, "B"),
    ]
    assert [(s.session_id, s.text) for s in derive_subagent_streams(journal, session_id=sid2)] == [
        (sid2, "B")
    ]


def test_surface_events_from_journal_interleaves_prompts_and_rounds() -> None:
    from runtime.memory.journal.derive import surface_events_from_journal

    journal = InMemoryJournal()
    sid = "33333333333333333333333333333333"
    journal.write(SubTextDeltaEvent(session_id=sid, role_id="researcher", round=1, delta="结论A"))
    journal.write(SubTextDeltaEvent(session_id=sid, role_id="researcher", round=2, delta="补充B"))
    # A different session's prose must not leak in.
    journal.write(
        SubTextDeltaEvent(
            session_id="44444444444444444444444444444444",
            role_id="researcher",
            round=1,
            delta="别处",
        )
    )
    other = "55555555555555555555555555555555"
    journal.write(SubTextDeltaEvent(session_id=other, role_id="writer", round=1, delta="X"))

    surface = surface_events_from_journal(journal, session_id=sid, prompts=["p1", "p2"])
    assert [e["type"] for e in surface] == [
        "user/message",
        "assistant/message",
        "user/message",
        "assistant/message",
    ]
    assert surface[0]["data"]["content"][0]["text"] == "p1"
    assert surface[1]["data"]["message"]["content"][0]["text"] == "结论A"
    assert surface[2]["data"]["content"][0]["text"] == "p2"
    assert surface[3]["data"]["message"]["content"][0]["text"] == "补充B"


def test_surface_events_from_journal_feeds_projection() -> None:
    from runtime.execution.tool_engine.session_projection import (
        retain_session_reference,
    )
    from runtime.memory.journal.derive import surface_events_from_journal

    journal = InMemoryJournal()
    sid = "66666666666666666666666666666666"
    journal.write(SubTextDeltaEvent(session_id=sid, role_id="researcher", round=1, delta="结论"))

    surface = surface_events_from_journal(journal, session_id=sid, prompts=["问题"])
    retained = retain_session_reference(
        surface,
        session_id=sid,
        label="researcher session",
        max_bytes=4096,
    )
    assert retained is not None
    data, stats = retained
    assert data.session_id == sid
    roles = [item["role"] for item in data.conversation]
    assert roles == ["user", "assistant"]
    assert data.conversation[0]["text"] == "问题"
    assert data.conversation[1]["text"] == "结论"
    assert stats.original_messages == 2
