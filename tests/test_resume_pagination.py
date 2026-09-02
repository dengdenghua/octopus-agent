"""thread/resume pagination.

Without params the response is byte-compatible with the old full
replay (plus additive totalTurns/hasMore fields). With ``limit`` the
newest window is returned; ``beforeTurnId`` pages backwards.
"""

from pathlib import Path

from runtime.memory.threads.event_log import EventLog, LoggedEvent
from runtime.protocol import AgentMessageItem, Turn, TurnParams, TurnStatus


def _turn(i: int) -> Turn:
    return Turn(
        id=f"turn-{i}",
        threadId="th-1",
        status=TurnStatus.COMPLETED,
        params=TurnParams(threadId="th-1", input=[{"type": "text", "text": str(i)}]),
    )


def _turns(n: int) -> list[Turn]:
    return [_turn(i) for i in range(n)]


class TestPaginateTurns:
    def test_no_limit_returns_everything(self):
        turns = _turns(5)
        window, has_more = EventLog.paginate_turns(turns)
        assert window == turns
        assert has_more is False

    def test_limit_keeps_newest_window(self):
        turns = _turns(10)
        window, has_more = EventLog.paginate_turns(turns, limit=3)
        assert [t.id for t in window] == ["turn-7", "turn-8", "turn-9"]
        assert has_more is True

    def test_limit_larger_than_list_is_full_list(self):
        turns = _turns(3)
        window, has_more = EventLog.paginate_turns(turns, limit=10)
        assert window == turns
        assert has_more is False

    def test_cursor_pages_backwards(self):
        turns = _turns(10)
        first, _ = EventLog.paginate_turns(turns, limit=3)
        older, has_more = EventLog.paginate_turns(turns, limit=3, before_turn_id=first[0].id)
        assert [t.id for t in older] == ["turn-4", "turn-5", "turn-6"]
        assert has_more is True

    def test_cursor_reaches_the_beginning(self):
        turns = _turns(4)
        older, has_more = EventLog.paginate_turns(turns, limit=10, before_turn_id="turn-2")
        assert [t.id for t in older] == ["turn-0", "turn-1"]
        assert has_more is False

    def test_unknown_cursor_falls_back_to_full_list(self):
        turns = _turns(4)
        window, has_more = EventLog.paginate_turns(turns, limit=2, before_turn_id="nope")
        assert [t.id for t in window] == ["turn-2", "turn-3"]
        assert has_more is True

    def test_zero_or_negative_limit_means_unlimited(self):
        turns = _turns(4)
        for limit in (0, -1):
            window, has_more = EventLog.paginate_turns(turns, limit=limit)
            assert window == turns
            assert has_more is False


def test_event_cursor_ignores_a_partial_trailing_write(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "th-1.jsonl")
    log.thread_started("th-1")
    partial = LoggedEvent(event="thread_started", threadId="th-1").model_dump_json(by_alias=True)
    with log.path.open("a", encoding="utf-8") as stream:
        stream.write(partial)
        stream.flush()

    assert log.latest_sequence() == 1
    assert len(list(log.iter_events_with_sequence())) == 1

    with log.path.open("a", encoding="utf-8") as stream:
        stream.write("\n")
        stream.flush()

    assert log.latest_sequence() == 2
    assert [sequence for sequence, _event in log.iter_events_with_sequence()] == [1, 2]


def test_snapshot_cursor_and_replay_share_one_file_boundary(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "th-1.jsonl")
    log.thread_started("th-1")
    first = _turn(0)
    log.turn_started("th-1", first)
    log.turn_completed("th-1", first.id, TurnStatus.COMPLETED)

    snapshot = log.snapshot()
    second = _turn(1)
    log.turn_started("th-1", second)
    log.turn_completed("th-1", second.id, TurnStatus.COMPLETED)

    assert snapshot.cursor == 3
    assert [turn.id for turn in snapshot.replay()] == ["turn-0"]
    changed_ids, next_sequence, requires_reset = log.cursor_delta(snapshot.cursor)
    assert changed_ids == ["turn-1"]
    assert next_sequence == 5
    assert requires_reset is False


def test_duplicate_event_id_is_applied_once_during_replay(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "th-1.jsonl")
    log.thread_started("th-1")
    turn = _turn(0)
    log.turn_started("th-1", turn)
    message = AgentMessageItem(id="msg-1", text="")
    log.item_started("th-1", turn.id, message)
    duplicate = LoggedEvent(
        event="item_delta",
        eventId="evt-fixed",
        threadId="th-1",
        turnId=turn.id,
        payload={"itemId": message.id, "kind": "agentMessage", "delta": "hello"},
    )
    log.append(duplicate)
    log.append(duplicate)

    snapshot = log.snapshot()
    replayed_message = next(item for item in snapshot.replay()[0].items if item.id == message.id)
    assert replayed_message.text == "hello"
    assert snapshot.cursor == 5
    assert len(snapshot.events) == 4


class TestEchoResumePagination:
    def _log_with_turns(self, tmp_path: Path, n: int) -> EventLog:
        log = EventLog(tmp_path / "th-1.jsonl")
        log.thread_started("th-1")
        for i in range(n):
            t = _turn(i)
            log.turn_started("th-1", t)
            log.turn_completed("th-1", t.id, TurnStatus.COMPLETED)
        return log

    def test_resume_default_is_full_and_flagged(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        self._log_with_turns(tmp_path, 5)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        out = asyncio.run(rt.handle_request("thread/resume", {"threadId": "th-1"}, _Emitter()))
        assert len(out["turns"]) == 5
        assert out["totalTurns"] == 5
        assert out["hasMore"] is False
        assert out["incremental"] is False
        assert out["lastTurnId"] == "turn-4"
        assert out["lastTurnStatus"] == "completed"
        assert out["nextEventSequence"] == 11
        assert out["eventStreamId"].startswith("stream_")

    def test_resume_with_limit_and_cursor(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        self._log_with_turns(tmp_path, 7)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        first = asyncio.run(
            rt.handle_request("thread/resume", {"threadId": "th-1", "limit": 2}, _Emitter())
        )
        assert [t["id"] for t in first["turns"]] == ["turn-5", "turn-6"]
        assert first["totalTurns"] == 7
        assert first["hasMore"] is True

        older = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {
                    "threadId": "th-1",
                    "limit": 2,
                    "beforeTurnId": first["turns"][0]["id"],
                },
                _Emitter(),
            )
        )
        assert [t["id"] for t in older["turns"]] == ["turn-3", "turn-4"]
        assert older["hasMore"] is True

    def test_resume_after_event_cursor_returns_only_changed_turns(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        log = self._log_with_turns(tmp_path, 2)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        full = asyncio.run(
            rt.handle_request("thread/resume", {"threadId": "th-1", "limit": 50}, _Emitter())
        )
        cursor = full["nextEventSequence"]
        assert cursor == 5

        changed = _turn(2)
        log.turn_started("th-1", changed)
        log.turn_completed("th-1", changed.id, TurnStatus.COMPLETED)

        delta = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {"threadId": "th-1", "limit": 50, "afterSequence": cursor},
                _Emitter(),
            )
        )
        assert delta["incremental"] is True
        assert [turn["id"] for turn in delta["turns"]] == ["turn-2"]
        assert delta["nextEventSequence"] == 7
        assert delta["totalTurns"] == 3

        unchanged = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {
                    "threadId": "th-1",
                    "limit": 50,
                    "afterSequence": delta["nextEventSequence"],
                },
                _Emitter(),
            )
        )
        assert unchanged["incremental"] is True
        assert unchanged["turns"] == []
        assert unchanged["nextEventSequence"] == 7

    def test_append_crossing_snapshot_boundary_arrives_on_next_resume(
        self,
        tmp_path: Path,
        monkeypatch,
    ) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        log = self._log_with_turns(tmp_path, 1)
        rt = EchoRuntime(logs_root=tmp_path)
        monkeypatch.setattr(rt, "_log_for", lambda _thread_id: log)
        capture = log.snapshot
        capture_count = 0
        appended = False

        def snapshot_with_racing_append():
            nonlocal capture_count, appended
            capture_count += 1
            snapshot = capture()
            # Inject immediately after the resume handler's immutable
            # ownership + history boundary has been fixed.
            if capture_count == 1 and not appended:
                appended = True
                racing_turn = _turn(1)
                log.turn_started("th-1", racing_turn)
                log.turn_completed("th-1", racing_turn.id, TurnStatus.COMPLETED)
            return snapshot

        monkeypatch.setattr(log, "snapshot", snapshot_with_racing_append)

        class _Emitter:
            actor_id = None

        first = asyncio.run(rt.handle_request("thread/resume", {"threadId": "th-1"}, _Emitter()))
        assert [turn["id"] for turn in first["turns"]] == ["turn-0"]
        assert first["nextEventSequence"] == 3

        delta = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {
                    "threadId": "th-1",
                    "afterSequence": first["nextEventSequence"],
                    "eventStreamId": first["eventStreamId"],
                },
                _Emitter(),
            )
        )
        assert delta["incremental"] is True
        assert [turn["id"] for turn in delta["turns"]] == ["turn-1"]
        assert delta["nextEventSequence"] == 5

    def test_invalid_future_cursor_falls_back_to_full_snapshot(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        self._log_with_turns(tmp_path, 2)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        out = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {"threadId": "th-1", "limit": 50, "afterSequence": 999},
                _Emitter(),
            )
        )
        assert out["incremental"] is False
        assert [turn["id"] for turn in out["turns"]] == ["turn-0", "turn-1"]
        assert out["nextEventSequence"] == 5

    def test_compaction_after_cursor_forces_full_snapshot(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        log = self._log_with_turns(tmp_path, 4)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        full = asyncio.run(
            rt.handle_request("thread/resume", {"threadId": "th-1", "limit": 50}, _Emitter())
        )
        log.turn_compacted("th-1", _turn(99), ["turn-0", "turn-1"])

        reset = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {
                    "threadId": "th-1",
                    "limit": 50,
                    "afterSequence": full["nextEventSequence"],
                },
                _Emitter(),
            )
        )
        assert reset["incremental"] is False
        assert [turn["id"] for turn in reset["turns"]] == [
            "turn-99",
            "turn-2",
            "turn-3",
        ]
        assert reset["nextEventSequence"] == full["nextEventSequence"] + 1

    def test_replaced_same_length_log_forces_full_snapshot(self, tmp_path: Path) -> None:
        import asyncio

        from runtime.sensing.gateway.realtime_echo import EchoRuntime

        original = self._log_with_turns(tmp_path, 1)
        rt = EchoRuntime(logs_root=tmp_path)

        class _Emitter:
            actor_id = None

        full = asyncio.run(rt.handle_request("thread/resume", {"threadId": "th-1"}, _Emitter()))
        original.path.unlink()
        replacement = EventLog(original.path)
        replacement.thread_started("th-1")
        replacement_turn = _turn(9)
        replacement.turn_started("th-1", replacement_turn)
        replacement.turn_completed(
            "th-1",
            replacement_turn.id,
            TurnStatus.COMPLETED,
        )
        assert replacement.latest_sequence() == full["nextEventSequence"]

        reset = asyncio.run(
            rt.handle_request(
                "thread/resume",
                {
                    "threadId": "th-1",
                    "afterSequence": full["nextEventSequence"],
                    "eventStreamId": full["eventStreamId"],
                },
                _Emitter(),
            )
        )
        assert reset["incremental"] is False
        assert [turn["id"] for turn in reset["turns"]] == ["turn-9"]
        assert reset["eventStreamId"] != full["eventStreamId"]
