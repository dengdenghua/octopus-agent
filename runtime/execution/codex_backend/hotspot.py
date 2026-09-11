"""Host-owned subscription authentication and isolated remote Codex execution."""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .client import CodexAppServerClient
from .command import resolve_codex_app_server_command
from .types import CodexAppServerConfig


class SubscriptionUnavailable(RuntimeError):
    pass


class SubscriptionAuth:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.lock = asyncio.Lock()
        self.refreshed_at = 0.0

    async def refresh(self, *, force: bool = False) -> None:
        async with self.lock:
            if not force and time.monotonic() - self.refreshed_at < 60:
                return
            config = CodexAppServerConfig(
                command=resolve_codex_app_server_command(),
                env_overrides={"CODEX_HOME": str(self.home)},
            )
            # Avoid unnecessary refresh requests for desktop-managed sessions;
            # a valid cached token does not need to be rotated on every call.
            refresh_token = False
            try:
                access = self.headers()["Authorization"].removeprefix("Bearer ")
                payload = access.split(".")[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
                refresh_token = float(claims.get("exp", 0)) < time.time() + 120
            except (ValueError, IndexError, KeyError, SubscriptionUnavailable):
                refresh_token = True
            async with CodexAppServerClient(config) as client:
                result = await client.account_read(refresh_token=refresh_token)
                if (result.get("account") or {}).get("type") != "chatgpt":
                    raise SubscriptionUnavailable("请先在本机 Codex 登录 ChatGPT 套餐账号。")
            self.refreshed_at = time.monotonic()

    def headers(self) -> dict[str, str]:
        # The native client owns OAuth refresh. Never export refresh tokens,
        # fall back to API keys, or accept caller-supplied account headers.
        try:
            path = self.home / "auth.json"
            if path.is_symlink() or path.stat().st_size > 256_000:
                raise ValueError
            data = json.loads(path.read_text(encoding="utf-8"))
            tokens = data.get("tokens") or {}
            access, account = tokens.get("access_token"), tokens.get("account_id")
            if data.get("auth_mode") not in {None, "chatgpt"} or not access or not account:
                raise ValueError
            if any(c in access + account for c in "\r\n"):
                raise ValueError
            return {"Authorization": "Bearer " + access, "ChatGPT-Account-Id": account}
        except (OSError, ValueError, TypeError, KeyError):
            raise SubscriptionUnavailable("本机套餐凭证不可用；需要 Codex 文件凭证登录。") from None


@dataclass(frozen=True)
class CodexRemoteConfig:
    data_dir: Path
    source_home: Path
    auth: SubscriptionAuth
    model: str | None = None
    permission_mode: str = "workspace-write"
    timeout: float = 300


async def stream_codex(config: CodexRemoteConfig, prompt: str, workspace: Path, resume=None):
    from runtime.execution.codex_backend.backend import CodexExecutionRequest, CodexExecutionSession
    from runtime.execution.codex_backend.security import CodexSecurityPolicy, CodexSidecarSecurity
    from runtime.safety.approval.approval_gate import AutoDenyProvider

    await config.auth.refresh()
    config.auth.headers()  # Fail before execution when the auth source cannot be seeded.
    request = CodexExecutionRequest(
        outer_thread_id=workspace.parent.name,
        outer_turn_id=uuid.uuid4().hex,
        realm_id="codex-hotspot",
        tenant_id=config.data_dir.name,
        principal_id="invited-member",
        workspace=workspace.resolve(),
        prompt=prompt,
        command=resolve_codex_app_server_command(),
        source_codex_home=config.source_home,
        model=config.model,
        sandbox_mode=config.permission_mode,
        approval_policy="never",
        developer_instructions="Complete this delegated task in the assigned workspace. Do not send messages to third parties unless the user explicitly asks. Do not bypass denied permissions.",
    )
    session = CodexExecutionSession(
        request,
        security=CodexSidecarSecurity(
            CodexSecurityPolicy(
                state_root=(config.data_dir / "runtime").resolve(),
                allowed_workspace_roots=(config.data_dir.resolve(),),
            )
        ),
        approval_provider=AutoDenyProvider(),
        is_interrupted=lambda: False,
    )
    final_text = ""
    try:
        async with asyncio.timeout(config.timeout):
            await session.start()
            async for event in session.notifications():
                if event.method == "item/agentMessage/delta":
                    yield {
                        "type": "stream_event",
                        "event": {
                            "delta": {"type": "text_delta", "text": event.params.get("delta", "")}
                        },
                    }
                elif event.method == "item/completed":
                    item = event.params.get("item") or {}
                    if item.get("type") == "agentMessage":
                        final_text = str(item.get("text") or final_text)
                elif event.method == "turn/completed":
                    turn = event.params.get("turn") or {}
                    yield {
                        "type": "result",
                        "subtype": "success" if turn.get("status") == "completed" else "error",
                        "is_error": turn.get("status") != "completed",
                        "result": final_text,
                    }
                    break
    finally:
        await session.close()
