"""Cowork storage guardrails for collaboration/session ids and message bounds."""

from __future__ import annotations

import pytest

from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.ids import MAX_COWORK_MESSAGE_TEXT_LENGTH
from runtime.memory.cowork.presence import PresenceStore
from runtime.memory.cowork.room_messages import RoomMessageStore


def test_group_store_rejects_invalid_thread_and_member_ids(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="thread_id"):
        store.append("../escape", MemberEvent(action="invite", actor="u", target_id="alice"))

    with pytest.raises(ValueError, match="target_id"):
        store.append("thread-1", MemberEvent(action="invite", actor="u", target_id="../agent"))


def test_room_messages_reject_invalid_ids_and_oversized_text(tmp_path) -> None:
    store = RoomMessageStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="room_id"):
        store.append("room/escape", text="hello")

    with pytest.raises(ValueError, match="participant_id"):
        store.append("room-1", text="hello", participant_id="bad participant")

    with pytest.raises(ValueError, match="text"):
        store.append("room-1", text="x" * (MAX_COWORK_MESSAGE_TEXT_LENGTH + 1))


def test_presence_store_rejects_invalid_ids_and_negative_cursor(tmp_path) -> None:
    store = PresenceStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="member_id"):
        store.heartbeat("thread-1", "bad/member")

    with pytest.raises(ValueError, match="position"):
        store.mark_read("thread-1", "alice", -1)


def test_collaboration_store_rejects_invalid_room_task_and_participant_ids(tmp_path) -> None:
    store = CollaborationStore(base_dir=tmp_path)

    with pytest.raises(ValueError, match="room_id"):
        store.upsert_room("thread-1", {"id": "../room"})

    store.upsert_room("thread-1", {"id": "room-1"})

    with pytest.raises(ValueError, match="task_id"):
        store.upsert_task("thread-1", {"id": "task/1", "room_id": "room-1"})

    with pytest.raises(ValueError, match="participant_id"):
        store.append_message(
            "thread-1",
            room_id="room-1",
            text="hello",
            participant_id="bad participant",
        )


def test_collaboration_store_keeps_compatible_email_style_ids(tmp_path) -> None:
    store = CollaborationStore(base_dir=tmp_path)
    store.upsert_room("oct:alice@example.com", {"id": "room-1"})
    seq = store.append_message(
        "oct:alice@example.com",
        room_id="room-1",
        text="hello",
        participant_id="oct:bob@example.com",
    )

    assert seq == 1
    assert store.session_id_for_room("room-1") == "oct:alice@example.com"
