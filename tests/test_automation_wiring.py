"""Regression tests for automation-stack wiring fixes.

* computer_use_loop is now registered at serve time (app.py) from a
  router-backed VisionPlanner, so the desktop_operator_arm's
  ``computer_use_loop`` allowlist entry actually resolves. Previously only
  the demo server registered it.
"""

from __future__ import annotations


def test_computer_use_loop_registers_from_router_planner():
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.computer_use_loop import (
        ModelRouterVisionPlanner,
        register_computer_use_loop,
    )
    from runtime.sensing.model_router import MockModelRouter

    reg = SkillRegistry()
    planner = ModelRouterVisionPlanner(router=MockModelRouter())
    n = register_computer_use_loop(reg, planner)

    assert n == 1
    assert reg.has("computer_use_loop")


def test_desktop_operator_arm_references_a_registrable_loop():
    # The preset arm allowlists computer_use_loop; this guards that the name
    # the arm references is exactly the one the registrar registers.
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.computer_use_loop import (
        ModelRouterVisionPlanner,
        register_computer_use_loop,
    )
    from runtime.sensing.model_router import MockModelRouter

    reg = SkillRegistry()
    register_computer_use_loop(reg, ModelRouterVisionPlanner(router=MockModelRouter()))
    assert "computer_use_loop" in reg.all_names()


# ── browser_router now honours require_auth (was unauthenticated) ──


def _browser_client(**kwargs):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.platform.ui.browser_router import create_browser_router

    app = FastAPI()
    app.include_router(create_browser_router(**kwargs))
    return TestClient(app)


def test_browser_endpoints_open_by_default():
    # Default (require_auth off) → _resolve_actor is a no-op → local preview
    # unchanged. A browser endpoint must NOT 401.
    c = _browser_client()
    assert c.get("/api/browser/config").status_code != 401


def test_browser_endpoints_enforce_auth_when_enabled():
    # require_auth on + an identity store + no bearer token → 401 across the
    # router (previously these endpoints had no auth at all).
    c = _browser_client(require_auth=True, identity_store=object())
    assert c.get("/api/browser/config").status_code == 401


# ── vision-loop semantic grounding (window list into the planner prompt) ──


class _RecordingRouter:
    """Captures the ModelRequest the planner sends and returns a done action."""

    def __init__(self) -> None:
        self.last = None

    def call(self, request):
        self.last = request

        class _R:
            text = '{"action": "done"}'

        return _R()


def test_window_grounding_returns_str_and_never_raises():
    from runtime.execution.suckers.desktop_grounding import window_grounding

    out = window_grounding()
    # macOS: a non-empty window list; other platforms / no perms: "".
    assert isinstance(out, str)


def test_ax_control_grounding_returns_str_and_never_raises():
    from runtime.execution.suckers.desktop_grounding import ax_control_grounding

    # macOS+trusted: actionable AX controls of the frontmost app; otherwise "".
    # Must never raise into the vision loop regardless of platform/permission.
    assert isinstance(ax_control_grounding(), str)


def test_combined_grounding_merges_best_effort_parts():
    from runtime.execution.suckers.desktop_grounding import combined_grounding

    out = combined_grounding()
    assert isinstance(out, str)  # window list + AX controls, each best-effort


# ── browser skills route through the 3-track resolver (EXT>ELEC>PW) ──


class _FakeTrack:
    """A recording higher-priority backend for the resolver."""

    def __init__(self):
        from runtime.execution.suckers.browser_backend import Track
        self.track = Track.ELECTRON
        self.calls = []

    def available(self):
        return True

    def _call(self, action, payload):
        from runtime.execution.suckers.browser_backend import BrowserResult, Track
        self.calls.append((action, dict(payload)))
        return BrowserResult.from_track(Track.ELECTRON, {"ok": True, "action": action})


def test_with_page_navigate_then_acts_on_higher_track(monkeypatch):
    from runtime.execution.suckers import browser_skills as bs

    fake = _FakeTrack()
    monkeypatch.setattr(bs, "_higher_track_backends", lambda: [fake])
    # PW closure must NOT run — the higher track serves it.
    out = bs._with_page(
        None, lambda p: {"pw": True}, verb="click",
        payload={"selector": "#go"}, url="http://h.test",
    )
    assert ("navigate", {"url": "http://h.test"}) in fake.calls  # navigate first
    assert ("click", {"selector": "#go"}) in fake.calls           # then act
    assert out.get("action") == "click" and out.get("pw") is None


def test_navigate_verb_has_no_separate_prenavigate(monkeypatch):
    from runtime.execution.suckers import browser_skills as bs

    fake = _FakeTrack()
    monkeypatch.setattr(bs, "_higher_track_backends", lambda: [fake])
    bs._with_page(None, lambda p: {"pw": True}, verb="navigate",
                  payload={"url": "http://h.test"}, url="http://h.test")
    assert fake.calls == [("navigate", {"url": "http://h.test"})]


def test_falls_back_to_pw_when_no_higher_track(monkeypatch):
    from runtime.execution.suckers import browser_skills as bs

    monkeypatch.setattr(bs, "_higher_track_backends", lambda: [])
    # no higher track available → None, so _with_page uses the Playwright path
    assert bs._dispatch_higher_track("click", {"selector": "#x"}, url="http://h") is None


def test_unavailable_higher_track_is_skipped(monkeypatch):
    from runtime.execution.suckers import browser_skills as bs

    class _Down(_FakeTrack):
        def available(self):
            return False

    monkeypatch.setattr(bs, "_higher_track_backends", lambda: [_Down()])
    assert bs._dispatch_higher_track("click", {"selector": "#x"}) is None


def test_planner_injects_grounding_into_prompt(tmp_path):
    from runtime.execution.suckers.computer_use_loop import ModelRouterVisionPlanner

    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG\r\n")
    rec = _RecordingRouter()
    planner = ModelRouterVisionPlanner(
        router=rec, grounding=lambda: "On-screen windows:\n- Finder @ (0,0) 800x600",
    )
    planner.next_action(goal="open a file", screenshot_path=str(shot), history=[])

    user_msg = rec.last.messages[1].content
    assert "On-screen windows" in user_msg
    assert "Finder" in user_msg


def test_planner_pure_pixel_without_grounding(tmp_path):
    from runtime.execution.suckers.computer_use_loop import ModelRouterVisionPlanner

    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG\r\n")
    rec = _RecordingRouter()
    planner = ModelRouterVisionPlanner(router=rec)  # grounding=None (default)
    planner.next_action(goal="open a file", screenshot_path=str(shot), history=[])

    assert "On-screen windows" not in rec.last.messages[1].content


def test_planner_grounding_failure_is_swallowed(tmp_path):
    from runtime.execution.suckers.computer_use_loop import ModelRouterVisionPlanner

    def _boom() -> str:
        raise RuntimeError("grounding blew up")

    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG\r\n")
    planner = ModelRouterVisionPlanner(router=_RecordingRouter(), grounding=_boom)
    # A failing grounding hook must NOT break the planner step.
    out = planner.next_action(goal="g", screenshot_path=str(shot), history=[])
    assert isinstance(out, dict)
