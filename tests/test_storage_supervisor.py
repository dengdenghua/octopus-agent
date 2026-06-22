"""Opt-in co-launch of octopus-storage (best-effort, mocked subprocess)."""

from __future__ import annotations

import runtime.sensing.gateway.storage_supervisor as ss


def test_autostart_gating(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_STORAGE_AUTOSTART", raising=False)
    assert ss._autostart_enabled() is False
    monkeypatch.setenv("OCTOPUS_STORAGE_AUTOSTART", "1")
    assert ss._autostart_enabled() is True


def test_resolve_explicit_cmd_appends_serve_and_port(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_CMD", "/opt/bin/octopus-storage")
    monkeypatch.delenv("OCTOPUS_STORAGE_URL", raising=False)
    assert ss.resolve_storage_command() == [
        "/opt/bin/octopus-storage",
        "serve",
        "--port",
        "8767",
    ]


def test_resolve_explicit_cmd_keeps_existing_serve(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_CMD", "octo-store serve --port 9000")
    assert ss.resolve_storage_command() == ["octo-store", "serve", "--port", "9000"]


def test_resolve_port_comes_from_storage_url(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_CMD", "octopus-storage")
    monkeypatch.setenv("OCTOPUS_STORAGE_URL", "http://127.0.0.1:9999")
    assert ss.resolve_storage_command() == ["octopus-storage", "serve", "--port", "9999"]


def test_disabled_does_not_spawn(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_STORAGE_AUTOSTART", raising=False)
    spawned = {"n": 0}
    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: spawned.__setitem__("n", 1))
    assert ss.maybe_start_storage() == "disabled"
    assert spawned["n"] == 0


def test_already_running_does_not_spawn(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_already_up", lambda: True)
    spawned = {"n": 0}
    monkeypatch.setattr(ss.subprocess, "Popen", lambda *a, **k: spawned.__setitem__("n", 1))
    assert ss.maybe_start_storage() == "already_running"
    assert spawned["n"] == 0


def test_not_found_when_unresolvable(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_STORAGE_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_already_up", lambda: False)
    monkeypatch.setattr(ss, "resolve_storage_command", lambda: None)
    assert ss.maybe_start_storage() == "not_found"


def test_spawns_with_resolved_cmd(monkeypatch) -> None:
    ss._proc = None
    monkeypatch.setenv("OCTOPUS_STORAGE_AUTOSTART", "1")
    monkeypatch.setattr(ss, "_already_up", lambda: False)
    monkeypatch.setattr(
        ss, "resolve_storage_command", lambda: ["/x/octopus-storage", "serve", "--port", "8767"]
    )
    seen: dict = {}

    class _FakeProc:
        pid = 4242

        def poll(self):
            return None

    def fake_popen(cmd, **_k):
        seen["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(ss.subprocess, "Popen", fake_popen)
    # don't run the real readiness thread
    monkeypatch.setattr(
        ss.threading, "Thread", lambda **_k: type("T", (), {"start": lambda self: None})()
    )
    assert ss.maybe_start_storage() == "started"
    assert seen["cmd"] == ["/x/octopus-storage", "serve", "--port", "8767"]
    ss._proc = None


def test_stop_storage_terminates_child() -> None:
    class _FakeProc:
        def __init__(self):
            self.terminated = False
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            self.terminated = True
            self._alive = False

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self._alive = False

    p = _FakeProc()
    ss._proc = p
    ss.stop_storage()
    assert p.terminated is True
    assert ss._proc is None
