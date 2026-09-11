"""Real local Chromium capture/action/capture; no remote site or model calls."""

import base64
import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops

from runtime.execution.suckers.browser_skills import _browser_click, _browser_screenshot
from runtime.execution.suckers.registry import Skill, SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.execution.tool_engine.native_tool_execution import execute_native_tool_call
from runtime.memory.journal import InMemoryJournal
from runtime.platform.process.session import Session, session_scope
from runtime.safety.auth import TrustEngine


@pytest.mark.integration
def test_real_browser_observations_change_after_native_click(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
            if "not found" in str(exc) or "doesn't exist" in str(exc):
                pytest.skip("Install Chrome for the real browser screenshot check")
            raise
        try:
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.set_content(
                '<body style="background:red"><button id="change" '
                "onclick=\"document.body.style.background='blue'\">Change</button>"
            )

            def capture(path: str, sandbox_dir: str | None = None, **_kw):
                return _browser_screenshot(path=path, sandbox_dir=sandbox_dir, page=page)

            def click(selector: str, **_kw):
                return _browser_click(selector=selector, page=page)

            registry = SkillRegistry()
            for name, handler in [("browser_screenshot", capture), ("browser_click", click)]:
                registry.register(
                    Skill(
                        name=name,
                        description=name,
                        handler=handler,
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
            session = Session(
                actor="fixture",
                thread_id="image-fixture",
                metadata={
                    "mode": "code",
                    "workspace_path": str(tmp_path),
                    "extra_workspaces": [str(tmp_path)],
                    "auto_approve": True,
                    "browser_operation_mode": True,
                },
            )
            observations = []
            with session_scope(session):
                for phase in ("before", "after"):
                    if phase == "after":
                        text, failed = execute_native_tool_call(
                            stack,
                            {
                                "id": "click",
                                "name": "browser_click",
                                "arguments": {"selector": "#change"},
                            },
                        )
                        assert not failed, text
                    images = []
                    text, failed = execute_native_tool_call(
                        stack,
                        {
                            "id": phase,
                            "name": "browser_screenshot",
                            "arguments": {"path": str(tmp_path / f"{phase}.png")},
                        },
                        image_items=images,
                    )
                    assert not failed and len(images) == 1, text
                    data = base64.b64decode(images[0]["imageUrl"].split(",")[1])
                    image = Image.open(io.BytesIO(data)).convert("RGB")
                    assert image.size == (800, 600)
                    observations.append(image)
            assert observations[0].getpixel((500, 500)) == (255, 0, 0)
            assert observations[1].getpixel((500, 500)) == (0, 0, 255)
            assert ImageChops.difference(*observations).getbbox() is not None
        finally:
            browser.close()
