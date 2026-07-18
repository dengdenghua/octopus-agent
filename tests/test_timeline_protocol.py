from runtime.memory.threads.event_log import EventLog
from runtime.protocol import (
    AgentMessageItem,
    CommandExecutionItem,
    ItemStatus,
    Turn,
    TurnParams,
)


def _turn() -> Turn:
    return Turn(
        id="turn-1",
        threadId="thread-1",
        params=TurnParams(
            threadId="thread-1",
            input=[{"type": "text", "text": "go"}],
        ),
    )


def test_item_timeline_coordinates_are_serialized_on_the_common_contract() -> None:
    item = CommandExecutionItem(
        command="read_file",
        timeline_sequence=2,
        parent_item_id="tool-1",
        phase_id="phase-1",
    )
    payload = item.model_dump(by_alias=True, mode="json")

    assert payload["timelineSequence"] == 2
    assert payload["parentItemId"] == "tool-1"
    assert payload["phaseId"] == "phase-1"


def test_replay_uses_timeline_sequence_and_never_regresses_completed_item(tmp_path) -> None:
    log = EventLog(tmp_path / "thread-1.jsonl")
    turn = _turn()
    log.turn_started("thread-1", turn)

    later_completed = AgentMessageItem(
        id="later",
        text="final",
        status=ItemStatus.COMPLETED,
        timeline_sequence=2,
        parent_item_id="earlier",
    )
    log.item_completed("thread-1", turn.id, later_completed)
    log.item_started(
        "thread-1",
        turn.id,
        AgentMessageItem(
            id="later",
            text="",
            timeline_sequence=2,
            parent_item_id="earlier",
        ),
    )
    log.item_started(
        "thread-1",
        turn.id,
        AgentMessageItem(id="earlier", text="checkpoint", timeline_sequence=1),
    )

    replayed = log.replay()[0]
    assert [item.id for item in replayed.items] == ["earlier", "later"]
    assert replayed.items[1].status == ItemStatus.COMPLETED
    assert replayed.items[1].text == "final"
