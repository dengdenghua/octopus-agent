"""Unified CollaborationSession read-model + the event-sourced room link (#1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.async_work import AsyncWorkStore
from runtime.memory.cowork.group import MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.presence import PresenceStore
from runtime.memory.cowork.room_messages import RoomMessageStore
from runtime.memory.cowork.session import link_room, resolve_session
from runtime.sensing.gateway.cowork_group_router import create_cowork_group_router


def test_room_link_event_sets_room_id(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u", target_id="alice",
                                   target_kind="agent"))
    assert store.state("t1").room_id is None
    link_room(store, "t1", "room-42")
    assert store.state("t1").room_id == "room-42"
    # event-sourced: replay before the link shows no room
    seq_before = store.events("t1")[0].seq
    assert store.state("t1", until_seq=seq_before).room_id is None


def test_resolve_session_composes_surfaces(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    aw = AsyncWorkStore(base_dir=store.base_dir, group_store=store)
    ps = PresenceStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u", target_id="alice",
                                   target_kind="agent"))
    store.append("t1", MemberEvent(action="mode", actor="u", mode="swarm"))
    store.blackboard("t1").write("plan", "ship it", writer="alice")
    aw.assign("t1", "alice", "do x", actor="u")
    link_room(store, "t1", "room-9")
    rms = RoomMessageStore(base_dir=tmp_path)
    rms.append("room-9", text="hi from the room", participant_id="p1", display_name="Bob")

    s = resolve_session(store, "t1", async_store=aw, presence_store=ps, room_message_store=rms)
    assert s.session_id == "t1"
    assert s.room_id == "room-9"
    assert s.mode == "swarm"
    assert {m["id"] for m in s.roster} == {"alice"}
    assert s.blackboard["plan"] == "ship it"
    assert len(s.tasks) == 1
    assert any(m["member_id"] == "alice" for m in s.presence)
    # linked room's transcript is folded into the session view
    assert [m["text"] for m in s.room_messages] == ["hi from the room"]


def test_unlinked_session_has_no_room_messages(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u", target_id="alice",
                                   target_kind="agent"))
    rms = RoomMessageStore(base_dir=tmp_path)
    rms.append("room-9", text="orphan", participant_id="p", display_name="P")
    # no link → the room's messages are NOT pulled in
    s = resolve_session(store, "t1", room_message_store=rms)
    assert s.room_id is None and s.room_messages == [] and s.room_participants == []


def test_session_folds_room_participants_via_provider(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u", target_id="alice",
                                   target_kind="agent"))
    link_room(store, "t1", "room-9")
    s = resolve_session(
        store, "t1",
        room_participants_provider=lambda rid: (
            [{"id": "p1", "display_name": "Bob"}] if rid == "room-9" else []
        ),
    )
    assert [p["display_name"] for p in s.room_participants] == ["Bob"]


def test_session_folds_room_tasks_via_provider(tmp_path) -> None:
    store = GroupStore(base_dir=tmp_path)
    store.append("t1", MemberEvent(action="invite", actor="u", target_id="alice",
                                   target_kind="agent"))
    link_room(store, "t1", "room-9")
    s = resolve_session(
        store, "t1",
        room_tasks_provider=lambda rid: (
            [{"id": "task-1", "title": "ship report", "status": "running"}]
            if rid == "room-9" else []
        ),
    )
    assert [t["title"] for t in s.room_tasks] == ["ship report"]
    # unlinked → no room tasks even with a provider
    s2 = resolve_session(store, "t2", room_tasks_provider=lambda rid: [{"id": "x"}])
    assert s2.room_tasks == []


def test_collab_endpoint_includes_room_tasks(tmp_path) -> None:
    from runtime.sensing.gateway.team_tasks_router import (
        TeamTaskWire,
    )
    from runtime.sensing.gateway.team_tasks_router import (
        _save_state as _save_tasks,
    )

    # Seed the team_tasks store the cowork router will read.
    tt_path = tmp_path / "team_tasks.json"
    task = TeamTaskWire(
        id="task-1", room_id="room-9", title="evaluate the merger",
        status="running", created_at="t0", updated_at="t1",
    )
    other = TeamTaskWire(
        id="task-2", room_id="room-OTHER", title="unrelated",
        created_at="t0", updated_at="t0",
    )
    _save_tasks(tt_path, {"task-1": task, "task-2": other})

    app = FastAPI()
    app.include_router(create_cowork_group_router(
        store=GroupStore(base_dir=tmp_path), team_tasks_state_path=tt_path,
    ))
    c = TestClient(app)
    c.post("/api/cowork/t1/members", json={"target_id": "alice", "kind": "agent"})
    c.post("/api/collab/t1/link-room", json={"room_id": "room-9"})

    sess = c.get("/api/collab/t1").json()
    # only this room's tasks, not the other room's
    assert [t["title"] for t in sess["room_tasks"]] == ["evaluate the merger"]

    # …and they are findable via session-wide search (room_task kind)
    hits = c.get("/api/cowork/t1/search", params={"q": "merger"}).json()["hits"]
    rt = next(h for h in hits if h["kind"] == "room_task")
    assert rt["ref"]["task_id"] == "task-1" and rt["ref"]["status"] == "running"


def _client(tmp_path) -> TestClient:
    app = FastAPI()
    app.include_router(create_cowork_group_router(store=GroupStore(base_dir=tmp_path)))
    return TestClient(app)


def test_collab_endpoints(tmp_path) -> None:
    rms = RoomMessageStore(base_dir=tmp_path / "rooms")
    app = FastAPI()
    app.include_router(create_cowork_group_router(
        store=GroupStore(base_dir=tmp_path), room_message_store=rms,
    ))
    c = TestClient(app)
    t = "thread-collab"
    c.post(f"/api/cowork/{t}/members", json={"target_id": "alice", "kind": "agent"})
    c.post(f"/api/cowork/{t}/blackboard", json={"key": "k", "value": "v"})
    rms.append("room-x", text="room line", participant_id="p", display_name="P")

    # link a room, then the unified session reflects it (incl. the transcript)
    assert c.post(f"/api/collab/{t}/link-room", json={"room_id": "room-x"}).status_code == 200
    sess = c.get(f"/api/collab/{t}").json()
    assert sess["session_id"] == t
    assert sess["room_id"] == "room-x"
    assert {m["id"] for m in sess["roster"]} == {"alice"}
    assert sess["blackboard"]["k"] == "v"
    assert [m["text"] for m in sess["room_messages"]] == ["room line"]
    assert "presence" in sess and "tasks" in sess


def test_post_room_message_requires_linked_room(tmp_path) -> None:
    app = FastAPI()
    app.include_router(create_cowork_group_router(
        store=GroupStore(base_dir=tmp_path),
        room_message_store=RoomMessageStore(base_dir=tmp_path / "rooms"),
    ))
    c = TestClient(app)
    # No room linked yet → the write side refuses (409), pointing at /link-room.
    r = c.post("/api/collab/t1/room-message", json={"text": "hello"})
    assert r.status_code == 409


def test_post_room_message_writes_into_session_transcript(tmp_path) -> None:
    rms = RoomMessageStore(base_dir=tmp_path / "rooms")
    app = FastAPI()
    app.include_router(create_cowork_group_router(
        store=GroupStore(base_dir=tmp_path), room_message_store=rms,
    ))
    c = TestClient(app)
    t = "thread-write"
    assert c.post(f"/api/collab/{t}/link-room", json={"room_id": "room-w"}).status_code == 200

    r = c.post(
        f"/api/collab/{t}/room-message",
        json={"text": "summary from the group", "display_name": "Planner"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["room_id"] == "room-w" and body["seq"] == 1

    # The write lands in the SAME transcript the unified read surfaces.
    sess = c.get(f"/api/collab/{t}").json()
    assert [m["text"] for m in sess["room_messages"]] == ["summary from the group"]
    # …and is findable via session-wide search (room_message kind).
    hits = c.get(f"/api/cowork/{t}/search", params={"q": "summary"}).json()["hits"]
    assert any(h["kind"] == "room_message" for h in hits)


def test_collab_endpoint_includes_room_participants(tmp_path) -> None:
    from runtime.sensing.gateway.team_rooms_router import (
        TeamParticipantWire,
        TeamRoomWire,
        _save_state,
    )

    # Seed the team_rooms store the cowork router will read.
    tr_path = tmp_path / "team_rooms.json"
    room = TeamRoomWire(
        id="room-9", name="R", created_at="t0", updated_at="t0",
        participants=[TeamParticipantWire(id="p1", display_name="Bob", joined_at="t0")],
    )
    _save_state(tr_path, {"room-9": room})

    app = FastAPI()
    app.include_router(create_cowork_group_router(
        store=GroupStore(base_dir=tmp_path), team_rooms_state_path=tr_path,
    ))
    c = TestClient(app)
    c.post("/api/cowork/t1/members", json={"target_id": "alice", "kind": "agent"})
    c.post("/api/collab/t1/link-room", json={"room_id": "room-9"})

    sess = c.get("/api/collab/t1").json()
    assert sess["room_id"] == "room-9"
    assert [p["display_name"] for p in sess["room_participants"]] == ["Bob"]
