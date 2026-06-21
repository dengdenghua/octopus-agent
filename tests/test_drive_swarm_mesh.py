"""_drive_swarm_mesh — serve-side mesh swarm driver + safe react fallback."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from runtime.sensing.gateway import realtime_team_stream as mod


class _Emitter:
    def __init__(self) -> None:
        self.calls: list = []

    async def notify(self, method, params):
        self.calls.append((method, params))


class _Log:
    def item_started(self, *a):
        pass

    def item_completed(self, *a):
        pass


def test_drive_swarm_mesh_emits_arm_results_and_summary(monkeypatch):
    result = SimpleNamespace(arm_results=[
        SimpleNamespace(arm_id="code_arm", status="success", reason="found X"),
        SimpleNamespace(arm_id="text_arm", status="failed", reason="err"),
    ])

    async def fake_to_thread(fn):
        return (result, 5)

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    turn = SimpleNamespace(thread_id="th", id="t1", items=[])
    intent = SimpleNamespace(user_context={})
    asyncio.run(
        mod._drive_swarm_mesh(SimpleNamespace(), turn, _Log(), _Emitter(), intent, text="g"),
    )

    assert len(turn.items) == 3  # 2 arm results + 1 summary
    bodies = [it.text for it in turn.items]
    assert any("code_arm" in b and "found X" in b for b in bodies)
    assert any(
        "mesh swarm complete" in b and "2 arm" in b and "5 coordination" in b
        for b in bodies
    )


def test_drive_swarm_mesh_falls_back_to_react_on_error(monkeypatch):
    async def boom(fn):
        raise RuntimeError("swarm exploded")

    monkeypatch.setattr(asyncio, "to_thread", boom)
    monkeypatch.setattr(mod, "GatewayApprovalProvider", lambda *a, **k: object())

    react = {"called": False}

    async def fake_drive_react(*a, **k):
        react["called"] = True

    runtime = SimpleNamespace(
        _trace_store=None,
        _wrap_with_policy=lambda p: p,
        _resolve_agent=lambda *a, **k: None,
        _drive_react=fake_drive_react,
    )
    turn = SimpleNamespace(thread_id="th", id="t1", items=[])
    intent = SimpleNamespace(user_context={})
    asyncio.run(
        mod._drive_swarm_mesh(runtime, turn, _Log(), _Emitter(), intent, text="g"),
    )

    assert react["called"] is True  # fell back; the turn is not broken
    assert turn.items == []          # no mesh items emitted on failure
