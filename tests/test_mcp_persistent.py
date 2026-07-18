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
            notices.append(notification.root)

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
    assert notices[0].params.requestId == 17
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
