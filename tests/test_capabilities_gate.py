"""Tests for runtime.platform.runtime_policy.capabilities.

The capability gate is the single user-facing knob for browser /
desktop automation. Each test pins one observable contract so a
regression in disabled_skill_groups() — like the original miss of the
``browser_act`` group, which left the live Electron bridge skills
reachable even after the user opted out of browser automation —
fails loudly here rather than silently in production.
"""

from __future__ import annotations

import json
from uuid import uuid4

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.memory.journal import InMemoryJournal
from runtime.platform import capabilities as caps_mod
from runtime.platform.models import ArmId, Budget, BudgetLimits, SkillId, TaskId
from runtime.platform.runtime_policy.capabilities import Capabilities
from runtime.safety.auth import TrustEngine


def test_defaults_enable_both():
    caps = Capabilities.defaults()
    assert caps.browser_automation is True
    assert caps.desktop_automation is True
    assert caps.disabled_skill_groups() == set()


def test_disabling_browser_disables_both_browser_groups():
    """browser_automation must gate BOTH the headless Playwright pool
    (``browser``) AND the live bridge to the Electron webview
    (``browser_act``). Disabling only ``browser`` previously left
    ``live_browser_*`` skills wired up — those skills drive the user's
    real, logged-in browser, so leaving them on after a privacy opt-out
    is worse than leaving the headless ones on."""
    caps = Capabilities(browser_automation=False, desktop_automation=True)
    disabled = caps.disabled_skill_groups()
    assert "browser" in disabled
    assert "browser_act" in disabled
    assert "computer" not in disabled


def test_disabling_desktop_disables_only_computer_group():
    caps = Capabilities(browser_automation=True, desktop_automation=False)
    disabled = caps.disabled_skill_groups()
    assert disabled == {"computer"}


def test_disabling_both_disables_all_three_automation_groups():
    caps = Capabilities(browser_automation=False, desktop_automation=False)
    assert caps.disabled_skill_groups() == {"browser", "browser_act", "computer"}


def test_from_dict_round_trip_preserves_state():
    original = Capabilities(browser_automation=False, desktop_automation=False)
    revived = Capabilities.from_dict(original.to_dict())
    assert revived == original


def test_from_dict_treats_missing_keys_as_enabled():
    # A partial config file (e.g. user only persisted desktop_automation)
    # must not silently flip the absent toggle off.
    revived = Capabilities.from_dict({"desktop_automation": False})
    assert revived.browser_automation is True
    assert revived.desktop_automation is False


def test_load_falls_back_to_defaults_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        caps_mod,
        "_store_path",
        lambda: tmp_path / "capabilities.json",
    )
    loaded = caps_mod.load()
    assert loaded == Capabilities.defaults()


def test_load_falls_back_when_file_is_malformed(tmp_path, monkeypatch):
    path = tmp_path / "capabilities.json"
    path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(caps_mod, "_store_path", lambda: path)
    loaded = caps_mod.load()
    assert loaded == Capabilities.defaults()


def test_load_falls_back_when_top_level_is_not_object(tmp_path, monkeypatch):
    path = tmp_path / "capabilities.json"
    path.write_text("[1,2,3]", encoding="utf-8")
    monkeypatch.setattr(caps_mod, "_store_path", lambda: path)
    loaded = caps_mod.load()
    assert loaded == Capabilities.defaults()


def test_save_then_load_round_trips_via_disk(tmp_path, monkeypatch):
    path = tmp_path / "capabilities.json"
    monkeypatch.setattr(caps_mod, "_store_path", lambda: path)
    expected = Capabilities(browser_automation=False, desktop_automation=True)
    caps_mod.save(expected)
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == {"browser_automation": False, "desktop_automation": True}
    assert caps_mod.load() == expected


def test_disabled_groups_match_actual_registrar_keys():
    """Every group name returned by ``disabled_skill_groups`` must be
    a real key in ``_GROUP_REGISTRARS``. Otherwise the gate silently
    no-ops and the user's opt-out has no effect — exactly the failure
    mode this fix targets."""
    from runtime.execution.all_skills import _GROUP_REGISTRARS

    all_disabled: set[str] = set()
    for browser in (True, False):
        for desktop in (True, False):
            all_disabled.update(
                Capabilities(
                    browser_automation=browser,
                    desktop_automation=desktop,
                ).disabled_skill_groups()
            )
    unknown = all_disabled - set(_GROUP_REGISTRARS)
    assert not unknown, (
        f"capabilities gate references unknown skill groups: {sorted(unknown)}; "
        f"_GROUP_REGISTRARS keys: {sorted(_GROUP_REGISTRARS)}"
    )


def test_executor_gate_applies_browser_opt_out_without_registry_restart(monkeypatch):
    from runtime.execution.tool_engine.executor import _runtime_automation_gate

    monkeypatch.setattr(
        "runtime.platform.runtime_policy.capabilities.load",
        lambda: Capabilities(browser_automation=False, desktop_automation=True),
    )

    assert _runtime_automation_gate("live_browser_click") == (True, "browser_act")
    assert _runtime_automation_gate("browser_navigate") == (True, "browser")
    assert _runtime_automation_gate("mouse_click") == (False, "computer")
    assert _runtime_automation_gate("read_file") == (False, "builtin")


def test_executor_gate_applies_desktop_opt_out_without_registry_restart(monkeypatch):
    from runtime.execution.tool_engine.executor import _runtime_automation_gate

    monkeypatch.setattr(
        "runtime.platform.runtime_policy.capabilities.load",
        lambda: Capabilities(browser_automation=True, desktop_automation=False),
    )

    assert _runtime_automation_gate("mouse_click") == (True, "computer")
    assert _runtime_automation_gate("live_browser_click") == (False, "browser_act")


def test_executor_rejects_a_registered_automation_handler_after_live_opt_out(monkeypatch):
    calls: list[dict[str, object]] = []
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="mouse_click",
            description="test native click",
            affinity=["computer"],
            trusted_source="builtin://computer",
            handler=lambda **kwargs: calls.append(kwargs) or {"ok": True},
        )
    )
    monkeypatch.setattr(
        "runtime.platform.runtime_policy.capabilities.load",
        lambda: Capabilities(browser_automation=True, desktop_automation=False),
    )
    task_id = TaskId(uuid4())
    step = ToolExecutor(
        registry,
        TrustEngine(trusted_sources=["builtin://*"]),
        InMemoryJournal(),
    ).execute_step(
        step_id=1,
        node_id="desktop_1",
        sucker_id=SkillId("mouse_click"),
        args={"x": 10, "y": 20},
        caller="test",
        task_id=task_id,
        arm_id=ArmId("arm_1"),
        budget=Budget(task_id=task_id, limits=BudgetLimits(tokens=1000, usd=1)),
    )

    assert step.result.status == "failed"
    assert "automation capability disabled: computer" in step.result.stderr_tags
    assert calls == []
