"""Implementation note."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.core.graph_runtime import GraphRuntime
from runtime.execution.agents import AgentRegistry, make_desktop_operator_agent
from runtime.execution.arms.presets import make_desktop_operator_arm, make_web_read_arm

# ═══════════════════════════════════════════════════════════
# Desktop Operator preset
# ═══════════════════════════════════════════════════════════


class _FakeExecutor:
    journal = None


def _rt():
    return GraphRuntime(executor=_FakeExecutor(), journal=None)


def test_web_read_arm_exposes_native_reach_skills():
    names = {str(skill) for skill in make_web_read_arm(_rt()).allowed_skills}
    assert {
        "platform_search",
        "platform_read",
        "platform_collect",
        "platform_monitor",
        "reach_doctor",
    } <= names


class TestDesktopOperatorArm:
    def test_arm_includes_computer_skills(self):
        arm = make_desktop_operator_arm(_rt())
        names = {str(s) for s in arm.allowed_skills}
        assert "screen_capture" in names
        assert "mouse_click" in names
        assert "keyboard_type" in names
        assert "computer_use_loop" in names
        assert "computer_uia_tree" in names

    def test_arm_affinity_mentions_vision(self):
        arm = make_desktop_operator_arm(_rt())
        tags = set(arm.affinity)
        assert "desktop" in tags
        assert "vision" in tags

    def test_arm_has_display_name_and_icon(self):
        arm = make_desktop_operator_arm(_rt())
        assert arm.display_name == "Desktop Operator"
        assert arm.icon == "🖥️"


class TestDesktopOperatorAgent:
    def test_agent_constructs(self):
        agent = make_desktop_operator_agent(_rt())
        assert agent.agent_id == "desktop_operator"
        assert agent.display_name == "Raven"
        assert agent.icon == "🖥️"
        assert "desktop" in agent.extra_affinity

    def test_agent_has_one_arm(self):
        agent = make_desktop_operator_agent(_rt())
        assert len(agent.arms) == 1

    def test_agent_can_use_core_desktop_skills(self):
        agent = make_desktop_operator_agent(_rt())
        assert agent.can_use("screen_capture")
        assert agent.can_use("mouse_click")
        assert agent.can_use("keyboard_type")
        assert agent.can_use("computer_use_loop")
        assert agent.can_use("computer_uia_find")
        # Implementation note.
        assert agent.can_use("read_file")

    def test_is_part_of_default_preset_list(self):
        """desktop_operator is a first-class persona since #22 (CUA productization)."""
        from runtime.execution.agents import make_all_agent_presets

        roster_ids = {getattr(a, "agent_id", None) for a in make_all_agent_presets(_rt())}
        assert "desktop_operator" in roster_ids

    def test_general_agent_has_desktop_arm(self):
        """Implementation note."""
        from runtime.execution.agents import make_general_agent

        agent = make_general_agent(_rt())
        arm_ids = [str(a.arm_id) for a in agent.arms]
        assert "desktop_operator_arm" in arm_ids


# ═══════════════════════════════════════════════════════════
# /api/health
# ═══════════════════════════════════════════════════════════


fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.platform.ui import create_app  # noqa: E402


class TestHealthEndpoint:
    def test_basic_shape(self, tmp_path: Path):
        app = create_app(journal_path=tmp_path / "events.jsonl")
        r = TestClient(app).get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "ts" in data
        assert "skills" in data
        assert isinstance(data["skills"], int)
        assert "journal_events" in data
        assert isinstance(data["journal_events"], int)
        assert isinstance(data["channels"], list)
        assert data["runtime"] == {
            "name": "octopus-agent-runtime",
            "version": "0.2.0",
            "verifiedBundle": False,
        }

    def test_reports_only_a_launcher_verified_clean_source(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        source_id = "a" * 40
        monkeypatch.setenv("OCTOPUS_RUNTIME_SOURCE_ID", source_id)
        monkeypatch.setenv("OCTOPUS_RUNTIME_BUNDLE_VERIFIED", "1")

        app = create_app(journal_path=tmp_path / "events.jsonl")
        runtime = TestClient(app).get("/api/health").json()["runtime"]

        assert runtime == {
            "name": "octopus-agent-runtime",
            "version": "0.2.0",
            "sourceId": source_id,
            "verifiedBundle": True,
        }

    @pytest.mark.parametrize(
        ("source_id", "verified"),
        [("a" * 40, "0"), ("not-a-commit", "1"), ("A" * 40, "1")],
    )
    def test_rejects_unverified_or_noncanonical_runtime_source_identity(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        source_id: str,
        verified: str,
    ):
        monkeypatch.setenv("OCTOPUS_RUNTIME_SOURCE_ID", source_id)
        monkeypatch.setenv("OCTOPUS_RUNTIME_BUNDLE_VERIFIED", verified)

        app = create_app(journal_path=tmp_path / "events.jsonl")
        runtime = TestClient(app).get("/api/health").json()["runtime"]

        assert runtime["verifiedBundle"] is False
        assert "sourceId" not in runtime

    def test_reports_agents_count_when_registered(self, tmp_path: Path):
        from runtime.execution.agents import make_all_agent_presets

        presets = make_all_agent_presets(_rt())
        reg = AgentRegistry()
        reg.register_all(presets)

        app = create_app(
            journal_path=tmp_path / "events.jsonl",
            agent_registry=reg,
        )
        r = TestClient(app).get("/api/health")
        data = r.json()
        # health endpoint should report exactly the agents we registered
        assert data["agents"] == len(presets)
        assert data["agents"] >= 4, "expected at least the four user-facing presets"

    def test_reports_channels_when_manager_wired(self, tmp_path: Path):
        from runtime.adapters.channels import (
            Channel,
            ChannelManager,
            OutboundMessage,
        )

        class _Fake(Channel):
            channel_id = "fake_x"

            def start(self):
                pass

            def stop(self):
                pass

            def send(self, msg: OutboundMessage):
                pass

        # Implementation note.
        class _S:
            pass

        s = _S()
        s.planner = None
        s.runtime = None
        s.registry = None
        s.journal = None

        reg = AgentRegistry()
        mgr = ChannelManager(stack=s, agent_registry=reg)
        mgr.register(_Fake())

        app = create_app(
            journal_path=tmp_path / "events.jsonl",
            agent_registry=reg,
            channel_manager=mgr,
        )
        data = TestClient(app).get("/api/health").json()
        assert "fake_x" in data["channels"]

    def test_defaults_when_nothing_extra_wired(self, tmp_path: Path):
        """Implementation note."""
        app = create_app(journal_path=tmp_path / "events.jsonl")
        data = TestClient(app).get("/api/health").json()
        assert data["agents"] == 0
        assert data["channels"] == []
        assert data["groups"] == 0

    def test_runtime_self_check_reports_isolated_runtime_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        from runtime.platform.ui.health_router import build_runtime_self_check

        data_dir = tmp_path / "e2e-state" / "data"
        monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "ignored-home"))
        monkeypatch.setenv("OCTOPUS_DATA_DIR", str(data_dir))

        class _State:
            journal_path = None

        payload = build_runtime_self_check(request=None, state=_State())

        assert payload["paths"]["data_dir"] == str(data_dir.resolve())
        assert payload["paths"]["runtime_root"] == str(data_dir.resolve().parent)
        assert payload["paths"]["octopus_data_dir_env"] == str(data_dir)
        assert payload["paths"]["octopus_home_env"] == str(tmp_path / "ignored-home")
