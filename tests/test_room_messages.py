"""Durable Team Room message log + the /api/teams/{id}/messages read path."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.room_messages import RoomMessageStore
from runtime.sensing.gateway.team_rooms_router import create_team_rooms_router


def test_append_assigns_monotonic_seq_per_room(tmp_path) -> None:
    s = RoomMessageStore(base_dir=tmp_path)
    assert s.append("r1", text="a") == 1
    assert s.append("r1", text="b") == 2
    assert s.append("r2", text="c") == 1  # seq restarts per room


def test_history_order_and_after_seq(tmp_path) -> None:
    s = RoomMessageStore(base_dir=tmp_path)
    for i in range(3):
        s.append("r1", text=f"m{i}", participant_id="p", display_name="P")
    assert [m["text"] for m in s.history("r1")] == ["m0", "m1", "m2"]
    assert [m["text"] for m in s.history("r1", after_seq=1)] == ["m1", "m2"]


def test_rooms_are_isolated(tmp_path) -> None:
    s = RoomMessageStore(base_dir=tmp_path)
    s.append("r1", text="x")
    s.append("r2", text="y")
    assert [m["text"] for m in s.history("r1")] == ["x"]
    assert [m["text"] for m in s.history("r2")] == ["y"]


def test_search_substring(tmp_path) -> None:
    s = RoomMessageStore(base_dir=tmp_path)
    s.append("r1", text="ship the nutrition report")
    s.append("r1", text="unrelated chatter")
    hits = s.search("r1", "nutrition")
    assert len(hits) == 1 and "nutrition" in hits[0]["text"]
    assert s.search("r1", "") == []


def test_survives_reopen(tmp_path) -> None:
    RoomMessageStore(base_dir=tmp_path).append("r1", text="durable")
    assert [m["text"] for m in RoomMessageStore(base_dir=tmp_path).history("r1")] == ["durable"]


def test_client_message_id_makes_retries_idempotent(tmp_path) -> None:
    store = RoomMessageStore(base_dir=tmp_path)
    first = store.append(
        "r1",
        text="send once",
        participant_id="p1",
        display_name="Alice",
        message_id="room-msg-stable",
        client_message_id="client-stable",
    )
    retry = store.append(
        "r1",
        text="send once",
        participant_id="p1",
        display_name="Alice",
        message_id="room-msg-stable",
        client_message_id="client-stable",
    )

    assert first == retry == 1
    history = store.history("r1")
    assert len(history) == 1
    assert history[0]["client_message_id"] == "client-stable"
    with pytest.raises(ValueError, match="different room message"):
        store.append(
            "r1",
            text="changed payload",
            participant_id="p1",
            display_name="Alice",
            message_id="room-msg-stable",
            client_message_id="client-stable",
        )

    # Client ids are scoped to their sender, so two participants may safely
    # generate the same local UUID.
    assert (
        store.append(
            "r1",
            text="another sender",
            participant_id="p2",
            message_id="room-msg-other",
            client_message_id="client-stable",
        )
        == 2
    )


def test_message_receipts_are_monotonic_and_durable(tmp_path) -> None:
    store = RoomMessageStore(base_dir=tmp_path)
    store.append(
        "r1",
        text="receipt me",
        participant_id="sender",
        message_id="room-msg-receipt",
    )

    delivered = store.record_receipt(
        "r1",
        message_id="room-msg-receipt",
        participant_id="reader",
        status="delivered",
        seq=1,
    )
    read = store.record_receipt(
        "r1",
        message_id="room-msg-receipt",
        participant_id="reader",
        status="read",
        seq=1,
    )
    regressed = store.record_receipt(
        "r1",
        message_id="room-msg-receipt",
        participant_id="reader",
        status="delivered",
        seq=1,
    )
    advanced = store.record_receipt(
        "r1",
        message_id="room-msg-receipt",
        participant_id="reader",
        status="read",
        seq=4,
    )
    stale_cursor = store.record_receipt(
        "r1",
        message_id="room-msg-receipt",
        participant_id="reader",
        status="delivered",
        seq=2,
    )

    assert delivered["status"] == "delivered"
    assert read["status"] == regressed["status"] == "read"
    assert advanced["status"] == stale_cursor["status"] == "read"
    assert advanced["seq"] == stale_cursor["seq"] == 4
    assert RoomMessageStore(base_dir=tmp_path).receipts("r1")[0]["status"] == "read"


def test_existing_room_message_database_is_migrated(tmp_path) -> None:
    db = tmp_path / "room_messages.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE room_messages ("
            "room_id TEXT NOT NULL, seq INTEGER NOT NULL, participant_id TEXT, "
            "display_name TEXT, text TEXT NOT NULL, ts TEXT NOT NULL, "
            "PRIMARY KEY (room_id, seq))"
        )
        conn.execute(
            "INSERT INTO room_messages VALUES (?, ?, ?, ?, ?, ?)",
            ("r1", 1, "p1", "Alice", "legacy", "2026-01-01T00:00:00Z"),
        )

    store = RoomMessageStore(base_dir=tmp_path)
    assert store.history("r1")[0]["text"] == "legacy"
    assert (
        store.append(
            "r1",
            text="new",
            message_id="room-msg-new",
            client_message_id="client-new",
        )
        == 2
    )


def test_messages_endpoint_reads_store(tmp_path) -> None:
    store = RoomMessageStore(base_dir=tmp_path)
    store.append("team-x", text="hello", participant_id="p1", display_name="Alice")
    store.append("team-x", text="find me nutrition", participant_id="p2", display_name="Bob")

    app = FastAPI()
    app.include_router(
        create_team_rooms_router(
            state_path=tmp_path / "team_rooms.json",
            room_message_store=store,
        )
    )
    c = TestClient(app)

    body = c.get("/api/teams/team-x/messages").json()
    assert [m["text"] for m in body["messages"]] == ["hello", "find me nutrition"]

    # after_seq catch-up
    tail = c.get("/api/teams/team-x/messages", params={"after_seq": 1}).json()
    assert [m["text"] for m in tail["messages"]] == ["find me nutrition"]

    # search
    found = c.get("/api/teams/team-x/messages", params={"q": "nutrition"}).json()
    assert len(found["messages"]) == 1


def test_messages_endpoint_prefers_canonical_provider(tmp_path) -> None:
    store = RoomMessageStore(base_dir=tmp_path / "legacy")
    store.append("team-x", text="legacy line", participant_id="old", display_name="Old")

    app = FastAPI()
    app.include_router(
        create_team_rooms_router(
            state_path=tmp_path / "team_rooms.json",
            room_message_store=store,
            room_message_provider=lambda team_id, limit, after_seq, q: [
                {
                    "seq": 1,
                    "participant_id": "p1",
                    "display_name": "Alice",
                    "text": "canonical nutrition line",
                    "ts": "t0",
                }
            ],
        )
    )
    c = TestClient(app)

    body = c.get("/api/teams/team-x/messages").json()
    assert [m["text"] for m in body["messages"]] == ["canonical nutrition line"]


def test_room_message_projection_receives_ws_persist_lines(tmp_path) -> None:
    from runtime.sensing.gateway.team_rooms_ws import TeamRoomWsContext, _remember_line

    projected: list[tuple[str, dict]] = []
    ctx = TeamRoomWsContext(
        teams={},
        lock=__import__("threading").Lock(),
        live_sockets={},
        auth=lambda _request: None,
        save=lambda: None,
        broadcast=lambda *args, **kwargs: None,
        broadcast_presence=lambda _team_id: None,
        broadcast_floor=lambda _team_id, _team: None,
        active_participant=lambda _team_id, _participant_id: None,
        message_store=RoomMessageStore(base_dir=tmp_path / "legacy"),
        message_projection=lambda room_id, message: projected.append((room_id, message)) or 7,
    )

    receipt = _remember_line(
        ctx,
        "team-x",
        "p1",
        "Alice",
        "hello from ws",
        message_id="room-msg-one",
        client_message_id="client-one",
    )

    assert receipt == {
        "message_id": "room-msg-one",
        "client_message_id": "client-one",
        "seq": 7,
    }
    assert projected == [
        (
            "team-x",
            {
                "participant_id": "p1",
                "display_name": "Alice",
                "text": "hello from ws",
                "metadata": {
                    "message_id": "room-msg-one",
                    "client_message_id": "client-one",
                    "source_message_id": "ws:room-msg-one",
                },
            },
        )
    ]


def test_persist_pool_append_persists(tmp_path) -> None:
    """The WS path offloads store.append to a background worker — verify that
    pooled append actually persists (no deadlock off the event loop)."""
    from runtime.sensing.gateway.team_rooms_ws import _persist_pool

    store = RoomMessageStore(base_dir=tmp_path)
    _persist_pool().submit(store.append, "r1", text="via pool").result(timeout=5)
    assert [m["text"] for m in store.history("r1")] == ["via pool"]


def test_plain_ws_message_persists_to_canonical_transcript_without_twin(tmp_path) -> None:
    canonical = CollaborationStore(base_dir=tmp_path / "canonical")
    legacy = RoomMessageStore(base_dir=tmp_path / "legacy")

    def project_message(room_id: str, message: dict) -> int | None:
        return canonical.append_message_for_room(
            room_id,
            text=message["text"],
            participant_id=message["participant_id"],
            display_name=message["display_name"],
            metadata=message.get("metadata"),
        )

    def project_receipt(room_id: str, receipt: dict) -> None:
        payload = dict(receipt)
        payload.pop("room_id", None)
        canonical.record_receipt_for_room(room_id, **payload)

    app = FastAPI()
    app.include_router(
        create_team_rooms_router(
            state_path=tmp_path / "team_rooms.json",
            room_message_store=legacy,
            room_message_projection=project_message,
            room_message_provider=lambda room_id, limit, after_seq, _q: canonical.messages_for_room(
                room_id,
                limit=limit,
                after_seq=after_seq,
            ),
            twin_responder=None,
        )
    )
    client = TestClient(app)
    room = client.post(
        "/api/teams",
        json={
            "name": "Canonical room",
            "thread_id": "thread-canonical",
            "members": [{"name": "general", "display_name": "General"}],
            "leaderId": "general",
        },
    ).json()
    room_id = room["id"]
    canonical.upsert_room("thread-canonical", room)

    with client.websocket_connect(
        f"/api/teams/{room_id}/ws?participant_id=owner-local&display_name=Owner"
    ) as ws:
        assert ws.receive_json()["type"] == "ready"
        assert ws.receive_json()["type"] == "presence"
        ws.send_json({"type": "message", "text": "ordinary durable line"})
        assert ws.receive_json()["text"] == "ordinary durable line"

    assert [message["text"] for message in canonical.messages_for_room(room_id)] == [
        "ordinary durable line"
    ]
    assert [
        message["text"]
        for message in client.get(f"/api/teams/{room_id}/messages").json()["messages"]
    ] == ["ordinary durable line"]


def test_ws_receipt_is_projected_to_canonical_store(tmp_path) -> None:
    canonical = CollaborationStore(base_dir=tmp_path / "canonical-receipt")
    legacy = RoomMessageStore(base_dir=tmp_path / "legacy-receipt")

    def project_message(room_id: str, message: dict) -> int | None:
        return canonical.append_message_for_room(
            room_id,
            text=message["text"],
            participant_id=message["participant_id"],
            display_name=message["display_name"],
            metadata=message.get("metadata"),
        )

    def project_receipt(room_id: str, receipt: dict) -> None:
        payload = dict(receipt)
        payload.pop("room_id", None)
        canonical.record_receipt_for_room(room_id, **payload)

    app = FastAPI()
    app.include_router(
        create_team_rooms_router(
            state_path=tmp_path / "team_rooms_receipt.json",
            room_message_store=legacy,
            room_message_projection=project_message,
            room_receipt_projection=project_receipt,
            twin_responder=None,
        )
    )
    client = TestClient(app)
    room = client.post(
        "/api/teams",
        json={
            "name": "Receipt room",
            "thread_id": "thread-receipt",
            "members": [{"name": "general"}],
        },
    ).json()
    room_id = room["id"]
    canonical.upsert_room_by_id(room)
    with client.websocket_connect(
        f"/api/teams/{room_id}/ws?participant_id=owner&display_name=Owner"
    ) as owner, client.websocket_connect(
        f"/api/teams/{room_id}/ws?participant_id=reader&display_name=Reader"
    ) as reader:
        owner.receive_json()
        owner.receive_json()
        reader.receive_json()
        reader.receive_json()
        owner.send_json({"type": "message", "text": "read me"})
        event = reader.receive_json()
        assert event["type"] == "message"
        reader.send_json({"type": "message:read", "message_id": event["message_id"], "seq": event["seq"]})
        receipt = owner.receive_json()
        while receipt.get("type") != "message:receipt":
            receipt = owner.receive_json()
        assert receipt["type"] == "message:receipt"

    canonical_receipt = canonical._connect().execute(
        "SELECT status FROM collaboration_message_receipts WHERE room_id=? AND message_id=?",
        (room_id, event["message_id"]),
    ).fetchone()
    assert canonical_receipt[0] == "read"


def test_canonical_receipts_keep_read_status_and_cursor_monotonic(tmp_path) -> None:
    canonical = CollaborationStore(base_dir=tmp_path)
    room_id = "room-receipt-monotonic"
    canonical.upsert_room("thread-receipt-monotonic", {"id": room_id, "name": "Room"})
    canonical.append_message_for_room(
        room_id,
        text="hello",
        participant_id="sender",
        display_name="Sender",
        metadata={"message_id": "room-msg-monotonic"},
    )

    first = canonical.record_receipt_for_room(
        room_id,
        message_id="room-msg-monotonic",
        participant_id="reader",
        status="read",
        seq=4,
    )
    stale = canonical.record_receipt_for_room(
        room_id,
        message_id="room-msg-monotonic",
        participant_id="reader",
        status="delivered",
        seq=2,
    )

    assert first["status"] == stale["status"] == "read"
    assert first["seq"] == stale["seq"] == 4
