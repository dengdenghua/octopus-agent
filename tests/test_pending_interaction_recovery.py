import asyncio
from types import SimpleNamespace

import pytest

from runtime.sensing.gateway._realtime_detached_turn import _DetachedTurnEmitter
from runtime.sensing.gateway._realtime_gateway_approval import SharedTurnInterrupts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["item/commandExecution/requestApproval", "item/tool/requestUserInput"]
)
async def test_pending_interaction_moves_to_authorized_reconnected_client(method):
    opened = asyncio.Event()
    pending = asyncio.get_running_loop().create_future()
    received = []
    budgets = []

    async def original(method, params, *, timeout):
        budgets.append(timeout)
        opened.set()
        return await pending

    async def restored(method, params, *, timeout):
        budgets.append(timeout)
        received.append((method, params))
        return {"action": "accept"}

    owner = SimpleNamespace(_closed=False, actor_id="alice", request_approval=original)
    watcher = SimpleNamespace(
        _closed=False, actor_id="alice", watched_threads={"thread"}, request_approval=restored
    )
    outsider = SimpleNamespace(
        _closed=False, actor_id="bob", watched_threads={"thread"}, request_approval=restored
    )
    shared = SharedTurnInterrupts()
    shared.register("turn")
    gateway = SimpleNamespace(
        _connections=[outsider, watcher],
        _shared_interrupts=shared,
        _connection_can_access_thread=lambda thread, conn: conn.actor_id == "alice",
    )
    emitter = _DetachedTurnEmitter(gateway, "thread", owner)
    params = {"threadId": "thread", "turnId": "turn", "question": "Continue?"}
    task = asyncio.create_task(emitter.request_approval(method, params, timeout=2))
    await opened.wait()
    owner._closed = True
    pending.cancel()
    assert await asyncio.wait_for(task, 2) == {"action": "accept"}
    assert received == [(method, params)]
    assert 0 < budgets[1] < budgets[0] <= 2


@pytest.mark.asyncio
async def test_stop_during_disconnection_does_not_reissue_approval():
    shared = SharedTurnInterrupts()
    shared.register("turn")
    owner = SimpleNamespace(_closed=True)
    gateway = SimpleNamespace(_connections=[], _shared_interrupts=shared)
    emitter = _DetachedTurnEmitter(gateway, "thread", owner)
    task = asyncio.create_task(emitter.request_approval("approval", {"turnId": "turn"}, timeout=2))
    await asyncio.sleep(0)
    shared.request_interrupt("turn")
    assert await asyncio.wait_for(task, 1) == {"action": "decline", "reason": "turn interrupted"}
