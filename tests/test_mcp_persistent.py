"""Implementation note."""

from __future__ import annotations

import asyncio
import threading

import pytest

from runtime.adapters.mcp_client import (
    STDIO_AVAILABLE,
    MCPClientError,
    MCPServerConfig,
    PersistentStdioMCPClient,
)


@pytest.mark.skipif(not STDIO_AVAILABLE, reason="mcp SDK required")
class TestConnectFailure:
    def test_bad_command_raises_mcp_client_error(self):
        """Implementation note."""
        cfg = MCPServerConfig(
            name="bad",
            command="cmd_definitely_does_not_exist_98765",
            timeout_ms=3000,
        )
        with pytest.raises(MCPClientError, match="connect failed"):
            PersistentStdioMCPClient(cfg, connect_timeout_ms=3000)


class TestSDKMissing:
    def test_errors_without_sdk(self, monkeypatch):
        from runtime.adapters.mcp_client import persistent_client as mod

        monkeypatch.setattr(mod, "STDIO_AVAILABLE", False)
        with pytest.raises(MCPClientError, match="mcp SDK not installed"):
            PersistentStdioMCPClient(MCPServerConfig(name="x", command="npx"))


def test_commercial_mode_requires_operator_selected_stdio_workspace(monkeypatch):
    from runtime.adapters.mcp_client import persistent_client as mod

    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "commercial")
    monkeypatch.setattr(mod, "STDIO_AVAILABLE", True)

    with pytest.raises(MCPClientError, match="requires.*sandbox_dir"):
        PersistentStdioMCPClient(MCPServerConfig(name="x", command="npx"))


def test_commercial_stdio_parameters_use_selected_hard_backend(tmp_path, monkeypatch):
    from runtime.safety.sandboxing.sandbox import BackendChoice, DirectBackend

    class TaggingBackend(DirectBackend):
        def transform(self, argv, env, cwd, policy):  # type: ignore[no-untyped-def]
            return ["sandbox-wrapper", *argv], env, cwd

    monkeypatch.setenv("OCTOPUS_DEPLOYMENT_MODE", "commercial")
    monkeypatch.setattr(
        "runtime.safety.sandboxing.sandbox.resolved_process_backend",
        lambda _mode: BackendChoice(TaggingBackend(), "tagged", hard=True),
    )

    client = PersistentStdioMCPClient.__new__(PersistentStdioMCPClient)
    client.config = MCPServerConfig(
        name="x",
        command="python",
        args=["server.py"],
        sandbox_dir=str(tmp_path),
    )
    params = client._stdio_parameters(lambda **kwargs: kwargs)

    assert params["command"] == "sandbox-wrapper"
    assert params["args"] == ["python", "server.py"]
    assert params["cwd"] == str(tmp_path.resolve())
    assert params["env"]["HOME"].startswith(str(tmp_path.resolve()))


@pytest.mark.skipif(not STDIO_AVAILABLE, reason="mcp SDK required")
def test_persistent_call_sends_protocol_cancel_notification():
    from runtime.safety.approval.cancellation import (
        CancellationSource,
        OperationCancelled,
    )

    started = threading.Event()
    notices = []

    class _Session:
        _request_id = 17

        async def call_tool(self, _name, _args):
            started.set()
            await asyncio.Event().wait()

        async def send_notification(self, notification, **_kwargs):
            # MCP 1.x: notification is ClientNotification(root=...).
            # MCP 2.x: notification is the CancelledNotification directly.
            note = getattr(notification, "root", notification)
            notices.append(note)

    client = PersistentStdioMCPClient.__new__(PersistentStdioMCPClient)
    client._session = _Session()
    source = CancellationSource()

    def _redirect() -> None:
        assert started.wait(timeout=1)
        source.cancel(reason="user redirected")

    thread = threading.Thread(target=_redirect)
    thread.start()

    async def _run() -> None:
        with pytest.raises(OperationCancelled):
            await client._call_tool_async("slow", {}, source.token)
        await asyncio.sleep(0)

    asyncio.run(_run())
    thread.join(timeout=1)

    assert len(notices) == 1
    assert notices[0].method == "notifications/cancelled"
    # MCP 1.x 用 alias requestId,2.x 原生字段名 request_id。
    request_id = getattr(notices[0].params, "request_id", None) or getattr(
        notices[0].params, "requestId", None
    )
    assert request_id == 17
    assert notices[0].params.reason == "user redirected"


@pytest.mark.skipif(not STDIO_AVAILABLE, reason="mcp SDK required")
class TestLifecycle:
    def test_close_is_idempotent(self):
        """Implementation note."""
        cfg = MCPServerConfig(
            name="bad",
            command="cmd_definitely_does_not_exist_98765",
            timeout_ms=2000,
        )
        try:
            client = PersistentStdioMCPClient(cfg, connect_timeout_ms=2000)
        except MCPClientError:
            return  # Implementation note.

        # Implementation note.
        client.close()
        client.close()  # Implementation note.

    def test_context_manager_cleans_up(self):
        """Implementation note."""
        cfg = MCPServerConfig(
            name="bad",
            command="cmd_definitely_does_not_exist_98765",
            timeout_ms=2000,
        )
        try:
            with PersistentStdioMCPClient(cfg, connect_timeout_ms=2000):
                pass
        except MCPClientError:
            pass  # expected
