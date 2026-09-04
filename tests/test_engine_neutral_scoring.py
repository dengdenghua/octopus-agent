from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from runtime.memory.learning import turn_scoring
from runtime.protocol import (
    AgentMessageItem,
    CommandExecutionItem,
    ItemStatus,
    Turn,
    TurnParams,
    TurnStatus,
)
from runtime.safety.auth.scope import TenantScope
from runtime.sensing.gateway import _tool_bridge_scoring as bridge_scoring


def _turn(*, status: TurnStatus = TurnStatus.COMPLETED, final: bool = True) -> Turn:
    started = datetime.now(UTC) - timedelta(seconds=2)
    turn = Turn(
        id="trn_codex_score",
        threadId="thread-score",
        status=status,
        startedAt=started,
        completedAt=started + timedelta(seconds=2),
        params=TurnParams(
            threadId="thread-score",
            tenant_id="tenant-a",
            owner_actor_id="owner-a",
        ),
    )
    turn.execution_engine = "codex"
    turn.execution_agent_id = "coder"
    turn.items.append(
        CommandExecutionItem(
            id="cmd-1",
            command="pytest -q",
            status=ItemStatus.FAILED if status is TurnStatus.FAILED else ItemStatus.COMPLETED,
        )
    )
    if final:
        turn.items.append(
            AgentMessageItem(
                id="msg-1",
                text="已完成",
                status=ItemStatus.COMPLETED,
            )
        )
    return turn


def test_codex_turn_uses_shared_score_and_private_scope(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def record(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(turn_scoring, "record_turn_score", record)
    monkeypatch.setattr(bridge_scoring, "_auto_evolve_tick_safe", lambda *_a, **_kw: None)

    bridge_scoring._record_codex_turn_score_safe(
        turn=_turn(),
    )

    assert captured["agent_id"] == "coder"
    assert captured["turn_id"] == "trn_codex_score"
    assert captured["thread_id"] == "thread-score"
    assert captured["score"] == 1.0
    assert captured["scope"] == TenantScope(tenant_id="tenant-a", actor_id="owner-a")


def test_codex_failed_tool_is_visible_to_same_heuristic(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(turn_scoring, "record_turn_score", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(bridge_scoring, "_auto_evolve_tick_safe", lambda *_a, **_kw: None)

    bridge_scoring._record_codex_turn_score_safe(
        turn=_turn(status=TurnStatus.FAILED),
        agent=SimpleNamespace(agent_id="coder"),
    )

    assert captured["score"] == 0.5
    assert captured["reason"] == "tool_errors"
