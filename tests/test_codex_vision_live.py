"""Opt-in real model -> native broker -> isolated Chromium visual smoke.

Set OCTOPUS_RUN_CODEX_VISION_LIVE=1 to spend one authenticated Codex turn.
The fixture exposes pixels and bounded coordinates only, never DOM or answers.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.execution.codex_backend.backend import CodexExecutionRequest, CodexExecutionSession
from runtime.execution.codex_backend.command import resolve_codex_app_server_command
from runtime.execution.codex_backend.dynamic_tools import CodexDynamicToolBroker
from runtime.execution.codex_backend.security import CodexSecurityPolicy, CodexSidecarSecurity
from runtime.execution.suckers.registry import Skill, SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.memory.journal import InMemoryJournal
from runtime.safety.approval.approval_gate import AutoApproveProvider, AutoDenyProvider
from runtime.safety.auth import TrustEngine
from runtime.safety.sandboxing.sandbox import (
    effective_process_sandbox_mode,
    resolved_process_backend,
)


@pytest.mark.live
@pytest.mark.timeout(300)
@pytest.mark.skipif(
    os.environ.get("OCTOPUS_RUN_CODEX_VISION_LIVE") != "1",
    reason="real Codex vision smoke is opt-in",
)
@pytest.mark.asyncio
async def test_real_codex_reads_clicks_and_verifies_pixels() -> None:
    from playwright.async_api import async_playwright

    source_home = Path(
        os.environ.get("OCTOPUS_CODEX_LIVE_SOURCE_HOME", str(Path.home() / ".codex"))
    ).resolve()
    assert (source_home / "auth.json").is_file(), "An authenticated Codex home is required"
    command = resolve_codex_app_server_command(os.environ.get("OCTOPUS_CODEX_LIVE_BINARY"))
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    target = secrets.randbelow(6)
    loop = asyncio.get_running_loop()
    actions: list[dict] = []
    images_returned: list[int] = []
    final_messages: list[str] = []
    item_types: set[str] = set()
    # Auth state stays outside the granted workspace and is removed on exit.
    with tempfile.TemporaryDirectory(prefix=".codex-vision-", dir=Path.cwd()) as temp:
        root = Path(temp).resolve()
        workspace = root / "workspace"
        workspace.mkdir()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(channel="chrome", headless=True)
            try:
                page = await browser.new_page(viewport={"width": 800, "height": 600})
                await page.set_content(
                    '<body style="margin:0"><canvas width="800" height="600"></canvas>'
                )
                await page.evaluate(
                    """({target, code}) => {
                      const canvas = document.querySelector('canvas');
                      const ctx = canvas.getContext('2d');
                      window.fixtureDone = false;
                      ctx.fillStyle = '#f5f5f5'; ctx.fillRect(0,0,800,600);
                      ctx.fillStyle = '#111'; ctx.font = '28px sans-serif';
                      ctx.fillText('Click the orange START button', 70, 70);
                      for (let i=0; i<6; i++) {
                        const x=70+(i%3)*240, y=140+Math.floor(i/3)*170;
                        ctx.fillStyle=i===target ? '#ff9900' : '#dddddd';
                        ctx.fillRect(x,y,180,100);
                        ctx.fillStyle='#111'; ctx.font='bold 28px sans-serif';
                        ctx.fillText(i===target ? 'START' : 'WAIT',x+35,y+60);
                      }
                      canvas.onclick = e => {
                        const x=70+(target%3)*240, y=140+Math.floor(target/3)*170;
                        if(e.offsetX>=x && e.offsetX<x+180 && e.offsetY>=y && e.offsetY<y+100) {
                          window.fixtureDone=true;
                          ctx.fillStyle='#d8f9e3'; ctx.fillRect(0,0,800,600);
                          ctx.fillStyle='#132'; ctx.font='bold 40px monospace';
                          ctx.fillText('SUCCESS',80,210);
                          ctx.fillText(code,80,290);
                        }
                      };
                    }""",
                    {"target": target, "code": code},
                )

                async def screenshot_async() -> dict:
                    if len(actions) >= 8:
                        raise RuntimeError("Fixture action budget exhausted")
                    data = await page.screenshot(type="png")
                    actions.append(
                        {
                            "tool": "screenshot",
                            "after_success": await page.evaluate("window.fixtureDone"),
                        }
                    )
                    return {
                        "ok": True,
                        "dataUrl": "data:image/png;base64," + base64.b64encode(data).decode(),
                    }

                async def click_async(x: int, y: int) -> dict:
                    if (
                        type(x) is not int
                        or type(y) is not int
                        or not (0 <= x < 800 and 0 <= y < 600)
                    ):
                        raise ValueError("Coordinates must be integers within the 800x600 fixture")
                    if len(actions) >= 8 or sum(a["tool"] == "click" for a in actions) >= 3:
                        raise RuntimeError("Fixture action budget exhausted")
                    await page.mouse.click(x, y)
                    actions.append({"tool": "click", "x": x, "y": y})
                    return {"ok": True}

                def capture() -> dict:
                    return asyncio.run_coroutine_threadsafe(screenshot_async(), loop).result(20)

                def fixture_click(x: int, y: int) -> dict:
                    return asyncio.run_coroutine_threadsafe(click_async(x, y), loop).result(20)

                registry = SkillRegistry()
                names = ("live_browser_screenshot", "fixture_click")
                for name, handler, description in [
                    (names[0], capture, "Return an image of the isolated 800x600 browser fixture."),
                    (
                        names[1],
                        fixture_click,
                        "Click integer pixel coordinates x,y in this isolated browser fixture.",
                    ),
                ]:
                    registry.register(
                        Skill(
                            name=name,
                            handler=handler,
                            description=description,
                            trusted_source=f"skill://public/{name}",
                        ),
                        verify_tests=False,
                    )
                stack = SimpleNamespace(
                    executor=ToolExecutor(
                        registry=registry,
                        immunity=TrustEngine(trusted_sources=["skill://public/*"]),
                        journal=InMemoryJournal(),
                    )
                )
                agent = SimpleNamespace(
                    agent_id="vision",
                    extra_skills=[],
                    arms=[
                        SimpleNamespace(arm_id="vision", allowed_skills=list(names)),
                    ],
                )
                prompt = (
                    "Use only live_browser_screenshot and fixture_click for this task. "
                    "Take a screenshot, visually locate the orange START button, click its center "
                    "using screenshot pixel coordinates, then take another screenshot. "
                    "Read the verification code from the SUCCESS screen and return that code. "
                    "Do not use shell, files, DOM, web, or other tools. Maximum 8 tool calls."
                )
                broker = CodexDynamicToolBroker(
                    stack,
                    agent,
                    context={"browser_operation_mode": True},
                    goal=prompt,
                    outer_thread_id="vision-thread",
                    outer_turn_id="vision-turn",
                    workspace=str(workspace),
                    tenant_id="vision-fixture",
                    principal_id="vision-user",
                    approval_provider=AutoApproveProvider(),
                    is_interrupted=lambda: False,
                )

                class RecordingHandler:
                    bind_inner_scope = broker.bind_inner_scope

                    async def __call__(self, request):
                        result = await broker(request)
                        assert result["success"], result
                        images_returned.append(
                            sum(item["type"] == "inputImage" for item in result["contentItems"])
                        )
                        return result

                request = CodexExecutionRequest(
                    outer_thread_id="vision-thread",
                    outer_turn_id="vision-turn",
                    workspace=workspace,
                    realm_id="vision-realm",
                    tenant_id="vision-fixture",
                    principal_id="vision-user",
                    prompt=prompt,
                    command=command,
                    source_codex_home=source_home,
                    model=os.environ.get("OCTOPUS_CODEX_LIVE_MODEL") or "gpt-5.6-sol",
                    effort="low",
                    sandbox_mode="read-only",
                    host_env=os.environ,
                    dynamic_tools=broker.catalog.specs,
                    dynamic_tool_handler=RecordingHandler(),
                )
                session = CodexExecutionSession(
                    request,
                    security=CodexSidecarSecurity(
                        CodexSecurityPolicy(
                            state_root=root / "sidecar-state",
                            allowed_workspace_roots=(workspace,),
                            deployment_mode="local",
                        )
                    ),
                    approval_provider=AutoDenyProvider(),
                    is_interrupted=lambda: False,
                    process_backend=resolved_process_backend(effective_process_sandbox_mode()),
                )
                try:
                    async with asyncio.timeout(240):
                        await session.start()
                        async for notification in session.notifications():
                            item = notification.params.get("item", {})
                            if isinstance(item, dict) and isinstance(item.get("type"), str):
                                item_types.add(item["type"])
                            if (
                                notification.method == "item/completed"
                                and item.get("type") == "agentMessage"
                            ):
                                final_messages.append(item.get("text", ""))
                            if notification.method == "turn/completed":
                                assert notification.params["turn"]["status"] == "completed", (
                                    notification.params
                                )
                                break
                        else:
                            pytest.fail("App Server ended without turn/completed")
                    assert await page.evaluate("window.fixtureDone"), actions
                    assert actions[0]["tool"] == "screenshot", actions
                    assert actions[-1] == {"tool": "screenshot", "after_success": True}, actions
                    assert sum(images_returned) >= 2, images_returned
                    assert code in "\n".join(final_messages), final_messages
                    assert not item_types & {
                        "commandExecution",
                        "fileChange",
                        "mcpToolCall",
                        "webSearch",
                    }, item_types
                    print(
                        json.dumps(
                            {
                                "model": request.model,
                                "actions": actions,
                                "images": sum(images_returned),
                                "verified_code_from_pixels": True,
                                "item_types": sorted(item_types),
                            }
                        )
                    )
                finally:
                    await session.close()
            finally:
                await browser.close()
