"""Unit tests for ``runtime.core.cerebrum.leader``.

Spins up a real LeaderProcess on a temp UDS path. No subprocess —
the leader runs in a background thread within the test process so
failures surface as normal assertion errors instead of timeouts.

Uses ``/tmp`` short paths because macOS limits AF_UNIX socket paths
to 104 bytes — pytest's default ``tmp_path`` is often longer.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from runtime.core.cerebrum.leader import (
    LeaderAlreadyRunning,
    LeaderClient,
    LeaderError,
    LeaderNotRunning,
    LeaderProcess,
    LeaderState,
    _pid_alive,
    _pid_alive_windows,
    _read_frame,
    _write_frame,
    ensure_leader,
    main,
)


def _short_tmp_dir() -> Path:
    """A short-lived per-test dir under /tmp to dodge macOS UDS limits."""
    path = Path("/tmp") / f"octopus-leader-test-{os.getpid()}-{time.time_ns()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture()
def short_tmp() -> Path:
    path = _short_tmp_dir()
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def leader_socket(short_tmp: Path) -> Path:
    return short_tmp / "s.sock"


@pytest.fixture()
def leader_pid(short_tmp: Path) -> Path:
    return short_tmp / "s.pid"


@pytest.fixture()
def running_leader(leader_socket: Path, leader_pid: Path) -> LeaderProcess:
    """Start a non-blocking leader; teardown stops it."""
    proc = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    proc.start(blocking=False)
    # Wait briefly for the socket to come up.
    deadline = time.time() + 1.0
    while time.time() < deadline and not leader_socket.exists():
        time.sleep(0.01)
    if not leader_socket.exists():
        proc.stop()
        pytest.fail("leader socket did not come up")
    yield proc
    proc.stop()


# ── PID file management ─────────────────────────────────────


def test_pid_alive_for_current_process() -> None:
    assert _pid_alive(os.getpid()) is True


def test_pid_alive_for_dead_process() -> None:
    # pid 2**31-1 is very unlikely to exist on a normal test box.
    assert _pid_alive(2_147_483_647) is False


def test_pid_alive_for_invalid_pid() -> None:
    assert _pid_alive(-1) is False
    assert _pid_alive(0) is False


def test_pid_alive_uses_native_query_instead_of_signal_on_windows(monkeypatch) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    monkeypatch.setattr(leader_mod.sys, "platform", "win32")
    monkeypatch.setattr(leader_mod, "_pid_alive_windows", lambda pid: pid == 123)

    def _unexpected_kill(_pid: int, _signal: int) -> None:
        raise AssertionError("Windows PID probes must not call os.kill")

    monkeypatch.setattr(leader_mod.os, "kill", _unexpected_kill)
    assert leader_mod._pid_alive(123) is True
    assert leader_mod._pid_alive(456) is False


def test_pid_alive_handles_permission_and_generic_os_errors(monkeypatch) -> None:
    def permission_denied(_pid: int, _signal: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", permission_denied)
    assert _pid_alive(123) is True

    def generic_error(_pid: int, _signal: int) -> None:
        raise OSError

    monkeypatch.setattr(os, "kill", generic_error)
    assert _pid_alive(123) is False


def test_native_windows_pid_query_covers_handle_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeFunction:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    class FakeKernel:
        def __init__(self, *, handle: int, query_succeeds: bool, exit_code: int) -> None:
            self.closed: list[int] = []
            self.OpenProcess = FakeFunction(lambda *_args: handle)

            def get_exit_code(_handle, output) -> bool:
                output._obj.value = exit_code
                return query_succeeds

            self.GetExitCodeProcess = FakeFunction(get_exit_code)
            self.CloseHandle = FakeFunction(lambda value: self.closed.append(value) or True)

    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)
    missing = FakeKernel(handle=0, query_succeeds=True, exit_code=0)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: missing, raising=False)
    assert _pid_alive_windows(123) is True

    unreadable = FakeKernel(handle=7, query_succeeds=False, exit_code=0)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: unreadable, raising=False)
    assert _pid_alive_windows(123) is True
    assert unreadable.closed == [7]

    active = FakeKernel(handle=8, query_succeeds=True, exit_code=259)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: active, raising=False)
    assert _pid_alive_windows(123) is True

    exited = FakeKernel(handle=9, query_succeeds=True, exit_code=0)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: exited, raising=False)
    assert _pid_alive_windows(123) is False
    assert exited.closed == [9]


def test_leader_writes_pid_file(running_leader: LeaderProcess, leader_pid: Path) -> None:
    assert leader_pid.exists()
    pid_in_file = int(leader_pid.read_text().strip())
    assert pid_in_file == os.getpid()


# ── Single-instance enforcement ─────────────────────────────


def test_second_leader_fails_with_already_running(
    running_leader: LeaderProcess,
    leader_socket: Path,
    leader_pid: Path,
) -> None:
    second = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    with pytest.raises(LeaderAlreadyRunning):
        second.start(blocking=False)
    second.stop()
    with LeaderClient.connect(leader_socket) as client:
        assert client.call("ping", {})["pong"] is True


def test_stale_pid_file_is_reclaimed(short_tmp: Path) -> None:
    socket_path = short_tmp / "s.sock"
    pid_path = short_tmp / "s.pid"
    # Write a stale pid file pointing at a definitely-dead pid.
    pid_path.write_text("2_000_000")
    proc = LeaderProcess(socket_path=socket_path, pid_path=pid_path)
    proc.start(blocking=False)
    try:
        # Pid file should now point at OUR process.
        assert int(pid_path.read_text().strip()) == os.getpid()
    finally:
        proc.stop()


# ── Client / server round-trip ──────────────────────────────


def test_client_status_returns_snapshot(running_leader: LeaderProcess, leader_socket: Path) -> None:
    with LeaderClient.connect(leader_socket) as client:
        snapshot = client.call("status", {})
    assert snapshot["pid"] == os.getpid()
    assert snapshot["protocol_version"] == 1
    assert "uptime_seconds" in snapshot
    assert snapshot["task_status"] == {}


def test_client_ping(running_leader: LeaderProcess, leader_socket: Path) -> None:
    with LeaderClient.connect(leader_socket) as client:
        result = client.call("ping", {})
    assert result == {"pong": True, "pid": os.getpid()}


def test_authenticated_loopback_fallback_round_trip(
    leader_socket: Path,
    leader_pid: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    monkeypatch.setattr(leader_mod, "_uses_loopback_transport", lambda: True)
    proc = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    proc.start(blocking=False)
    try:
        endpoint = json.loads(leader_socket.read_text(encoding="utf-8"))
        assert endpoint["host"] == "127.0.0.1"
        assert len(endpoint["token"]) >= 32
        with LeaderClient.connect(leader_socket) as client:
            assert client.call("ping", {})["pong"] is True
    finally:
        proc.stop()


@pytest.mark.parametrize(
    "payload",
    (
        "not-json",
        "{}",
        '{"host":"0.0.0.0","port":1234,"token":"abcdefghijklmnopqrstuvwxyz123456"}',
        '{"host":"127.0.0.1","port":70000,"token":"abcdefghijklmnopqrstuvwxyz123456"}',
    ),
)
def test_loopback_rejects_invalid_endpoint_descriptors(
    leader_socket: Path,
    payload: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    monkeypatch.setattr(leader_mod, "_uses_loopback_transport", lambda: True)
    leader_socket.write_text(payload, encoding="utf-8")

    with pytest.raises(LeaderNotRunning, match="invalid leader endpoint"):
        LeaderClient.connect(leader_socket)


def test_loopback_rejects_client_with_wrong_token(
    leader_socket: Path,
    leader_pid: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    monkeypatch.setattr(leader_mod, "_uses_loopback_transport", lambda: True)
    proc = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    proc.start(blocking=False)
    try:
        endpoint = json.loads(leader_socket.read_text(encoding="utf-8"))
        endpoint["token"] = "x" * 43
        leader_socket.write_text(json.dumps(endpoint), encoding="utf-8")
        with (
            LeaderClient.connect(leader_socket) as client,
            pytest.raises((LeaderError, ConnectionResetError)),
        ):
            client.call("ping", {})
    finally:
        proc.stop()


def test_frame_reader_rejects_invalid_headers() -> None:
    left, right = socket.socketpair()
    try:
        right.sendall(b"not-a-length\n")
        with pytest.raises(LeaderError, match="invalid frame header"):
            _read_frame(left)
        right.sendall(b"0\n")
        with pytest.raises(LeaderError, match="length out of range"):
            _read_frame(left)
        right.sendall(b"9" * 65)
        with pytest.raises(LeaderError, match="header too long"):
            _read_frame(left)
    finally:
        left.close()
        right.close()


def test_frame_round_trip_and_truncated_payload() -> None:
    left, right = socket.socketpair()
    try:
        _write_frame(right, "hello")
        assert _read_frame(left) == "hello"
        right.sendall(b"5\nabc")
        right.shutdown(socket.SHUT_WR)
        assert _read_frame(left) is None
    finally:
        left.close()
        right.close()


def test_state_broadcast_discards_broken_clients() -> None:
    class BrokenSocket:
        def sendall(self, _payload: bytes) -> None:
            raise OSError("closed")

    state = LeaderState()
    broken = BrokenSocket()
    state.attach_client(broken)  # type: ignore[arg-type]

    state.broadcast("changed", {"ok": True})

    assert not state._clients


def test_server_returns_protocol_errors_and_survives_bad_notifications(
    leader_socket: Path,
    leader_pid: Path,
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    proc = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    left, right = socket.socketpair()
    try:
        proc._handle_message(left, "not-json")
        parse_error = leader_mod.decode_message(_read_frame(right) or "")
        assert parse_error.error.code == -32700

        response = leader_mod.JsonRpcResponse(jsonrpc="2.0", id=1, result={})
        proc._handle_message(left, leader_mod.encode_message(response))
        invalid = leader_mod.decode_message(_read_frame(right) or "")
        assert invalid.error.code == -32600

        proc.register_handler("bad-notification", lambda _params: 1 / 0)
        notification = leader_mod.Notification(jsonrpc="2.0", method="bad-notification", params={})
        proc._handle_message(left, leader_mod.encode_message(notification))
    finally:
        left.close()
        right.close()


def test_server_client_loop_rejects_bad_frame(
    leader_socket: Path,
    leader_pid: Path,
) -> None:
    proc = LeaderProcess(socket_path=leader_socket, pid_path=leader_pid)
    left, right = socket.socketpair()
    try:
        right.sendall(b"bad\n")
        proc._serve_client(left)
        assert not proc.state._clients
    finally:
        right.close()


def test_client_pause_and_resume(
    running_leader: LeaderProcess,
    leader_socket: Path,
) -> None:
    with LeaderClient.connect(leader_socket) as client:
        paused = client.call("pause", {"task_id": "task-1"})
        assert paused == {"ok": True, "task_id": "task-1", "status": "paused"}

        resumed = client.call("resume", {"task_id": "task-1"})
        assert resumed == {"ok": True, "task_id": "task-1", "status": "running"}

        snapshot = client.call("status", {})
        assert snapshot["task_status"]["task-1"] == "running"
        client.notify("pause", {"task_id": "notified"})
        snapshot = client.call("status", {})
        assert snapshot["task_status"]["notified"] == "paused"


def test_client_set_task_status_validates_status(
    running_leader: LeaderProcess,
    leader_socket: Path,
) -> None:
    with (
        LeaderClient.connect(leader_socket) as client,
        pytest.raises(LeaderError, match="invalid status"),
    ):
        client.call("set_task_status", {"task_id": "t", "status": "bogus"})


def test_client_set_task_status_requires_task_id(
    running_leader: LeaderProcess,
    leader_socket: Path,
) -> None:
    with (
        LeaderClient.connect(leader_socket) as client,
        pytest.raises(LeaderError, match="task_id required"),
    ):
        client.call("set_task_status", {"status": "running"})


def test_client_method_not_found(
    running_leader: LeaderProcess,
    leader_socket: Path,
) -> None:
    with (
        LeaderClient.connect(leader_socket) as client,
        pytest.raises(LeaderError, match="unknown method"),
    ):
        client.call("nonexistent_method", {})


# ── Client connection failures ──────────────────────────────


def test_connect_raises_when_socket_missing(short_tmp: Path) -> None:
    with pytest.raises(LeaderNotRunning):
        LeaderClient.connect(short_tmp / "missing.sock")


def test_connect_raises_when_socket_path_has_no_listener(
    short_tmp: Path,
) -> None:
    # Create the file but no one is listening on it.
    socket_path = short_tmp / "lonely.sock"
    socket_path.touch()
    with pytest.raises(LeaderNotRunning):
        LeaderClient.connect(socket_path)


# ── State broadcast ─────────────────────────────────────────


def test_register_handler_extends_protocol(
    running_leader: LeaderProcess,
    leader_socket: Path,
) -> None:
    running_leader.register_handler(
        "echo",
        lambda params: {"echoed": params},
    )
    with LeaderClient.connect(leader_socket) as client:
        result = client.call("echo", {"foo": "bar"})
    assert result == {"echoed": {"foo": "bar"}}


def test_register_handler_rejects_duplicates(
    running_leader: LeaderProcess,
) -> None:
    with pytest.raises(ValueError, match="already registered"):
        running_leader.register_handler("status", lambda _p: None)


# ── LeaderState ─────────────────────────────────────────────


def test_leader_state_snapshot_shape() -> None:
    state = LeaderState()
    snap = state.snapshot()
    assert snap["protocol_version"] == 1
    assert snap["pid"] == os.getpid()
    assert snap["task_status"] == {}
    assert snap["client_count"] == 0


def test_ensure_leader_reuses_existing_client(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    monkeypatch.setattr(LeaderClient, "connect", lambda _path: sentinel)

    assert ensure_leader("existing.sock", "existing.pid") is sentinel


def test_ensure_leader_starts_detached_process(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    sentinel = object()
    calls = 0

    def connect(_path: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LeaderNotRunning("missing")
        return sentinel

    popen_calls: list[tuple[object, object]] = []
    monkeypatch.setattr(LeaderClient, "connect", connect)
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda command, **kwargs: popen_calls.append((command, kwargs)),
    )
    monkeypatch.setattr(leader_mod.time, "sleep", lambda _seconds: None)

    assert ensure_leader("new.sock", "new.pid") is sentinel
    command, kwargs = popen_calls[0]
    assert command[-2:] == ["runtime.core.cerebrum.leader", "serve"]
    assert kwargs["start_new_session"] is True
    assert kwargs["env"]["OCTOPUS_LEADER_SOCKET"] == "new.sock"


def test_ensure_leader_reports_startup_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    monkeypatch.setattr(
        LeaderClient,
        "connect",
        lambda _path: (_ for _ in ()).throw(LeaderNotRunning("still missing")),
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: None)
    clock = iter((0.0, 0.0, 6.0))
    monkeypatch.setattr(leader_mod.time, "time", lambda: next(clock))
    monkeypatch.setattr(leader_mod.time, "sleep", lambda _seconds: None)

    with pytest.raises(LeaderNotRunning, match="did not come up"):
        ensure_leader("missing.sock", "missing.pid")


def test_main_status_and_stop_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    socket_path = tmp_path / "leader.sock"
    pid_path = tmp_path / "leader.pid"

    assert main(["status", "--socket", str(socket_path)]) == 1
    assert "leader not running" in capsys.readouterr().err
    assert main(["stop", "--pid", str(pid_path)]) == 1
    assert "no pid file" in capsys.readouterr().err

    pid_path.write_text("invalid", encoding="utf-8")
    assert main(["stop", "--pid", str(pid_path)]) == 1
    assert "invalid pid file" in capsys.readouterr().err

    pid_path.write_text("123", encoding="utf-8")
    monkeypatch.setattr(leader_mod, "_pid_alive", lambda _pid: False)
    assert main(["stop", "--pid", str(pid_path)]) == 0
    assert not pid_path.exists()


def test_main_status_serve_and_live_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from runtime.core.cerebrum import leader as leader_mod

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def call(self, _method: str, _params: dict[str, object]) -> dict[str, bool]:
            return {"ready": True}

    started: list[bool] = []

    class FakeLeader:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self, *, blocking: bool) -> None:
            started.append(blocking)

    monkeypatch.setattr(LeaderClient, "connect", lambda _path: FakeClient())
    assert main(["status", "--socket", str(tmp_path / "s")]) == 0
    assert '"ready": true' in capsys.readouterr().out

    monkeypatch.setattr(leader_mod, "LeaderProcess", FakeLeader)
    assert main(["serve", "--socket", "s", "--pid", "p"]) == 0
    assert started == [True]

    pid_path = tmp_path / "leader.pid"
    pid_path.write_text("456", encoding="utf-8")
    monkeypatch.setattr(leader_mod, "_pid_alive", lambda _pid: True)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(leader_mod.os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert main(["stop", "--pid", str(pid_path)]) == 0
    assert signals == [(456, signal.SIGTERM)]
    assert "sent SIGTERM" in capsys.readouterr().out

    monkeypatch.setattr(
        leader_mod.os,
        "kill",
        lambda _pid, _sig: (_ for _ in ()).throw(OSError("denied")),
    )
    assert main(["stop", "--pid", str(pid_path)]) == 1
    assert "failed to signal pid 456" in capsys.readouterr().err
