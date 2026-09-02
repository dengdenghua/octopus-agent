from __future__ import annotations

import asyncio
import json

import pytest

from runtime import cli_mcp
from runtime.adapters.mcp_client.trust import reset_trust_store_for_tests
from runtime.cli import main


def test_mcp_add_list_remove(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    reset_trust_store_for_tests()

    assert (
        main(
            [
                "--no-color",
                "mcp",
                "add",
                "fs",
                "--env",
                "ROOT=.",
                "--",
                "npx",
                "-y",
                "@modelcontextprotocol/server-filesystem",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["--no-color", "mcp", "list", "--output-format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcpServers"][0]["name"] == "fs"
    assert payload["mcpServers"][0]["command"] == "npx"
    assert payload["mcpServers"][0]["trusted"] is False

    assert main(["--no-color", "mcp", "remove", "fs"]) == 0
    assert "Removed MCP server fs." in capsys.readouterr().out


def test_mcp_trust_and_revoke(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    reset_trust_store_for_tests()

    assert main(["--no-color", "mcp", "trust", "fs", "--tool", "read_file"]) == 0
    capsys.readouterr()
    assert main(["--no-color", "mcp", "list", "--output-format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["mcpServers"] == []

    assert main(["--no-color", "mcp", "add", "fs", "--", "node", "server.js"]) == 0
    capsys.readouterr()
    assert main(["--no-color", "mcp", "list", "--output-format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcpServers"][0]["trusted"] is True

    assert main(["--no-color", "mcp", "revoke", "fs"]) == 0
    capsys.readouterr()
    assert main(["--no-color", "mcp", "list", "--output-format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mcpServers"][0]["trusted"] is False


class _FakeCoordinator:
    instances: list[_FakeCoordinator] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


async def _cancel_server_loop(_seconds: float) -> None:
    raise asyncio.CancelledError


def _install_fake_sse_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeCoordinator.instances.clear()
    monkeypatch.setattr("runtime.tentacle.coordinator.TentacleCoordinator", _FakeCoordinator)
    monkeypatch.setattr(cli_mcp.asyncio, "sleep", _cancel_server_loop)


def test_mcp_sse_loopback_is_explicit_anonymous_local_mode(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_TENTACLE_TOKEN", raising=False)
    _install_fake_sse_runtime(monkeypatch)

    assert asyncio.run(cli_mcp._run_sse_server("127.0.0.1", 8766)) == 0

    coordinator = _FakeCoordinator.instances[-1]
    assert coordinator.started is True
    assert coordinator.stopped is True
    assert coordinator.kwargs == {
        "host": "127.0.0.1",
        "port": 8765,
        "dashboard_port": 8766,
        "dashboard_host": "127.0.0.1",
        "mcp_server": True,
        "auth_token": None,
        "dashboard_require_auth": False,
    }


def test_mcp_sse_refuses_network_bind_without_token(monkeypatch, capsys) -> None:
    monkeypatch.delenv("OCTOPUS_TENTACLE_TOKEN", raising=False)
    _FakeCoordinator.instances.clear()
    monkeypatch.setattr("runtime.tentacle.coordinator.TentacleCoordinator", _FakeCoordinator)

    assert asyncio.run(cli_mcp._run_sse_server("0.0.0.0", 8766)) == 2
    assert _FakeCoordinator.instances == []
    assert "refusing to expose" in capsys.readouterr().err


def test_mcp_sse_network_bind_reuses_token_for_both_listeners(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_TENTACLE_TOKEN", "pairing-secret")
    _install_fake_sse_runtime(monkeypatch)

    assert asyncio.run(cli_mcp._run_sse_server("0.0.0.0", 8766)) == 0

    coordinator = _FakeCoordinator.instances[-1]
    assert coordinator.kwargs["host"] == "0.0.0.0"
    assert coordinator.kwargs["dashboard_host"] == "0.0.0.0"
    assert coordinator.kwargs["auth_token"] == "pairing-secret"
    assert coordinator.kwargs["dashboard_require_auth"] is True
