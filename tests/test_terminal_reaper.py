"""Regression tests for terminal_router.reap_sessions — bounds _sessions growth.

A terminal shell is kept across ws reconnects (persistent shell), but a client
that disconnects and never returns would otherwise leak its shell + subprocess
forever. reap_sessions() — called on each new connection — drops dead shells,
reaps idle-beyond-TTL ones, and hard-caps the live count (least-recently-active
evicted first), while never touching the session being (re)connected to.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from runtime.sensing.gateway import terminal_router as tr


@pytest.fixture(autouse=True)
def _clean_sessions() -> Iterator[None]:
    tr._sessions.clear()
    yield
    tr._sessions.clear()


def _session(sid: str, *, alive: bool, idle_seconds: float = 0.0) -> tr.ShellSession:
    sess = tr.ShellSession(sid)
    sess._alive = alive
    sess.last_activity = time.monotonic() - idle_seconds
    tr._sessions[sid] = sess
    return sess


@pytest.mark.asyncio
async def test_reaps_dead_sessions() -> None:
    _session("dead", alive=False)
    _session("alive", alive=True)
    await tr.reap_sessions()
    assert "dead" not in tr._sessions
    assert "alive" in tr._sessions


@pytest.mark.asyncio
async def test_reaps_idle_alive_sessions() -> None:
    _session("idle", alive=True, idle_seconds=tr._IDLE_TTL_SECONDS + 60)
    _session("fresh", alive=True, idle_seconds=1.0)
    await tr.reap_sessions()
    assert "idle" not in tr._sessions
    assert "fresh" in tr._sessions


@pytest.mark.asyncio
async def test_exclude_id_never_reaped() -> None:
    # Even a session that looks dead + idle is kept if it's the one being
    # (re)connected to — so a reconnect within the window keeps its shell.
    _session("reconnecting", alive=False, idle_seconds=tr._IDLE_TTL_SECONDS + 60)
    await tr.reap_sessions(exclude_id="reconnecting")
    assert "reconnecting" in tr._sessions


@pytest.mark.asyncio
async def test_hard_cap_evicts_least_recently_active() -> None:
    # All alive and well within the idle TTL, but over the hard cap → the
    # least-recently-active sessions are evicted down to _MAX_SESSIONS.
    overflow = 5
    for i in range(tr._MAX_SESSIONS + overflow):
        # s0 most-idle (largest idle), last one freshest — all idle << TTL.
        _session(f"s{i}", alive=True, idle_seconds=float(tr._MAX_SESSIONS + overflow - i))
    await tr.reap_sessions()
    assert len(tr._sessions) == tr._MAX_SESSIONS
    # The most-idle ones are the evicted set.
    for i in range(overflow):
        assert f"s{i}" not in tr._sessions
    assert f"s{tr._MAX_SESSIONS + overflow - 1}" in tr._sessions  # freshest kept
