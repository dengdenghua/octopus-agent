# ruff: noqa: E402 — module-level imports below are intentionally late
"""Implementation note."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.core.graph_runtime import GraphRuntime
from runtime.execution.agents import (
    Agent,
    AgentRegistry,
    make_all_agent_presets,
    make_general_agent,
)
from runtime.execution.arms.base import ArmPool, Worker
from runtime.execution.arms.presets import make_web_read_arm
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway import agent_world_router
from runtime.sensing.gateway import agents_router as agents_router_module
from runtime.sensing.gateway.agent_world_router import create_agent_world_router
from runtime.sensing.gateway.agents_router import create_agents_router

# ═══════════════════════════════════════════════════════════
# fixtures
# ═══════════════════════════════════════════════════════════


class _FakeExecutor:
    journal = None


def _rt():
    return GraphRuntime(executor=_FakeExecutor(), journal=None)


def _image_bytes(image) -> bytes:  # noqa: ANN001
    out = BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _png_bytes(color: tuple[int, int, int, int]) -> bytes:
    from PIL import Image

    return _image_bytes(Image.new("RGBA", (8, 8), color))


@pytest.fixture
def registry_with_presets() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register_all(make_all_agent_presets(_rt()))
    return reg


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestListAgents:
    def test_lists_all_registered(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        r = TestClient(app).get("/api/agents")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        names = {a["name"] for a in data}
        # The preset roster grows over time as new agents ship under
        # agents/. We assert on REQUIRED names being present rather
        # than exact count so adding a new preset doesn't break the
        # test. Six core presets must always be there.
        required = {
            "general",
            "coder",
            "vibe_selling",
            "ecommerce_mind",
            "market_researcher",
        }
        missing = required - names
        assert not missing, f"missing required presets: {missing}"
        assert len(data) >= len(required)

    def test_wire_format_matches_ts_interface(self, registry_with_presets):
        """Implementation note."""
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        data = TestClient(app).get("/api/agents").json()
        for agent in data:
            for key in [
                "name",
                "display_name",
                "description",
                "icon",
                "avatar_url",
                "visual_urls",
                "model",
                "tool_groups",
                "soul",
            ]:
                assert key in agent, f"missing '{key}' in {agent['name']}"

    def test_tool_groups_are_arm_ids(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        data = TestClient(app).get("/api/agents").json()
        coder = next(a for a in data if a["name"] == "coder")
        assert coder["tool_groups"] == [
            "web_read_arm",
            "fs_writer_arm",
            "git_arm",
            "shell_arm",
            "coder_private_arm",
        ]

    def test_empty_registry_returns_empty_list(self):
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry()))
        assert TestClient(app).get("/api/agents").json() == []

    def test_system_and_capability_agents_are_hidden_from_list(self):
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="Octopus",
                description="",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        registry.register(
            Agent(
                agent_id="admin",
                display_name="Admin",
                description="",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        registry.register(
            Agent(
                agent_id="desktop_operator",
                display_name="Desktop Operator",
                description="[legacy] desktop automation persona",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        data = TestClient(app).get("/api/agents").json()

        assert [agent["name"] for agent in data] == ["general"]


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestAgentDetail:
    def test_found_returns_full_detail(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        r = TestClient(app).get("/api/agents/coder")
        assert r.status_code == 200
        data = r.json()
        # Implementation note.
        assert data["name"] == "coder"
        assert data["display_name"] == "Kane"
        # Implementation note.
        assert len(data["arms"]) == 5
        arm_ids = [a["arm_id"] for a in data["arms"]]
        assert arm_ids == [
            "web_read_arm",
            "fs_writer_arm",
            "git_arm",
            "shell_arm",
            "coder_private_arm",
        ]
        # Implementation note.
        assert "git_commit" in data["allowed_skills"]
        assert "write_text_file" in data["allowed_skills"]
        assert "exec_shell" in data["allowed_skills"]
        # extra_affinity
        assert "code" in data["extra_affinity"]

    def test_not_found_404(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        r = TestClient(app).get("/api/agents/ghost")
        assert r.status_code == 404

    def test_delete_agent_removes_disk_and_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        (tmp_path / "custom_agent" / "agent-core").mkdir(parents=True)
        (tmp_path / "custom_agent" / "profile.jsonc").write_text("{}", encoding="utf-8")
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="custom_agent",
                display_name="Custom Agent",
                description="",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).delete("/api/agents/custom_agent")

        assert r.status_code == 204
        assert not registry.has("custom_agent")
        assert not (tmp_path / "custom_agent").exists()

    def test_delete_builtin_agent_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text("{}", encoding="utf-8")
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="General",
                description="",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).delete("/api/agents/general")

        assert r.status_code == 400
        assert registry.has("general")
        assert (tmp_path / "general").exists()

    def test_delete_agent_rejects_symlink_without_removing_target(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path / "agents"))
        agents_root = tmp_path / "agents"
        agents_root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "marker.txt").write_text("keep", encoding="utf-8")
        (agents_root / "custom_agent").symlink_to(outside, target_is_directory=True)
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="custom_agent",
                display_name="Custom Agent",
                description="",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).delete("/api/agents/custom_agent")

        assert r.status_code == 409
        assert (outside / "marker.txt").read_text(encoding="utf-8") == "keep"
        assert registry.has("custom_agent")

    def test_create_agent_cleans_directory_when_load_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))

        def fail_load(*_args, **_kwargs):
            raise ValueError("bad profile")

        monkeypatch.setattr("runtime.execution.agents.loader.load_agent", fail_load)
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))

        r = TestClient(app).post(
            "/api/agents",
            json={"name": "custom_agent", "description": "Custom"},
        )

        assert r.status_code == 500
        assert not (tmp_path / "custom_agent").exists()

    def test_market_install_hot_registers_and_uninstall_removes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        runtime = _rt()
        registry = AgentRegistry()
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=runtime))
        app.include_router(create_agent_world_router(registry=registry, runtime=runtime))
        client = TestClient(app)

        assert client.get("/api/agents/test_writer").status_code == 404

        install = client.post("/api/agent-market/store/test_writer/install")

        assert install.status_code == 200
        assert registry.has("test_writer")
        assert (tmp_path / "test_writer" / "profile.jsonc").is_file()
        assert client.get("/api/agents/test_writer").status_code == 200

        uninstall = client.delete("/api/agent-market/store/test_writer/install")

        assert uninstall.status_code == 200
        assert not registry.has("test_writer")
        assert not (tmp_path / "test_writer").exists()

    def test_market_install_rejects_unsafe_agent_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        app = FastAPI()
        app.include_router(create_agent_world_router())
        client = TestClient(app)

        r = client.post("/api/agent-market/store/bad:agent/install")

        assert r.status_code == 400
        assert not any(tmp_path.iterdir())
        assert not (tmp_path / "installed.json").exists()

    def test_market_install_does_not_overwrite_local_same_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        existing = tmp_path / "test_writer"
        (existing / "agent-core").mkdir(parents=True)
        profile = existing / "profile.jsonc"
        profile.write_text(
            '{"id":"test_writer","templateId":"test_writer","creator":"user"}',
            encoding="utf-8",
        )
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).post("/api/agent-market/store/test_writer/install")

        assert r.status_code == 409
        assert profile.read_text(encoding="utf-8") == (
            '{"id":"test_writer","templateId":"test_writer","creator":"user"}'
        )
        assert not (tmp_path / "installed.json").exists()

    def test_market_uninstall_does_not_remove_local_same_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        existing = tmp_path / "test_writer"
        (existing / "agent-core").mkdir(parents=True)
        profile = existing / "profile.jsonc"
        profile.write_text(
            '{"id":"test_writer","templateId":"test_writer","creator":"user"}',
            encoding="utf-8",
        )
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).delete("/api/agent-market/store/test_writer/install")

        assert r.status_code == 409
        assert existing.exists()
        assert profile.is_file()
        assert not (tmp_path / "installed.json").exists()

    def test_market_install_state_recovers_backup_and_filters_unsafe_ids(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        install_state = tmp_path / "installed.json"
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", install_state)
        install_state.write_text("{broken", encoding="utf-8")
        install_state.with_suffix(".json.bak").write_text(
            '{"installed":["test_writer","../escape","bad:agent","code_reviewer"]}',
            encoding="utf-8",
        )

        assert agent_world_router._read_install_state() == {"test_writer", "code_reviewer"}

    def test_market_install_cleans_new_agent_when_template_skill_name_is_invalid(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path / "agents"))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        original = agent_world_router._template_skill_catalog

        def fake_catalog(template: dict[str, object]) -> list[str]:
            if template.get("id") == "financial_pitch_agent":
                return ["../escape"]
            return original(template)  # type: ignore[arg-type]

        monkeypatch.setattr(agent_world_router, "_template_skill_catalog", fake_catalog)
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).post("/api/agent-market/store/financial_pitch_agent/install")

        assert r.status_code == 400
        assert not (tmp_path / "agents" / "financial_pitch_agent").exists()
        assert not (tmp_path / "installed.json").exists()

    def test_market_uninstall_rejects_local_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text("{}", encoding="utf-8")
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).delete("/api/agent-market/store/general/install")

        assert r.status_code == 400
        assert (tmp_path / "general").exists()

    def test_market_store_preserves_local_agent_tool_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        agent_core = tmp_path / "analyst" / "agent-core"
        agent_core.mkdir(parents=True)
        visuals = tmp_path / "analyst" / "visuals"
        visuals.mkdir()
        (tmp_path / "analyst" / "profile.jsonc").write_text(
            '{"id":"analyst","name":"Analyst","description":"analysis","tags":["analysis"],"model":{"provider":"auto","name":"gpt-test"},"character_profile":{"epithet":"Signal Reader","quote":"Read the signal."}}',
            encoding="utf-8",
        )
        (visuals / "front.svg").write_text("<svg></svg>", encoding="utf-8")
        (visuals / "side.svg").write_text("<svg></svg>", encoding="utf-8")
        (visuals / "back.svg").write_text("<svg></svg>", encoding="utf-8")
        (agent_core / "tool-registry.jsonc").write_text(
            '{"arms":["web_read","shell"],"extra_affinity":["market"],"private_skills":["pitch-deck","xlsx-author"]}',
            encoding="utf-8",
        )
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).get("/api/agent-market/store/analyst")

        assert r.status_code == 200
        data = r.json()
        assert data["model"] == "gpt-test"
        assert data["tool_groups"] == ["web_read", "shell"]
        assert data["extra_affinity"] == ["market"]
        assert data["private_skills"] == ["pitch-deck", "xlsx-author"]
        assert data["key_skills"] == ["pitch-deck", "xlsx-author"]
        assert set(data["visual_urls"]) == {"front", "side", "back"}
        assert data["character_profile"]["epithet"] == "Signal Reader"

    def test_market_requires_auth_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        store = IdentityStore()
        store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
        app = FastAPI()
        app.include_router(
            create_agent_world_router(
                identity_store=store,
                require_auth=True,
            )
        )
        client = TestClient(app)

        assert client.get("/api/agent-market/store").status_code == 401
        assert (
            client.get(
                "/api/agent-market/store",
                headers={"Authorization": "Bearer sk-alice"},
            ).status_code
            == 200
        )

    def test_update_agent_display_name_writes_profile_and_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        agent_core = tmp_path / "general" / "agent-core"
        agent_core.mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text(
            '{"id":"general","name":"Old Name","description":"old","model":{"provider":"auto","name":"auto"}}',
            encoding="utf-8",
        )
        (agent_core / "SOUL.md").write_text("old soul", encoding="utf-8")
        (agent_core / "tool-registry.jsonc").write_text(
            '{"arms":["web_read"],"extra_affinity":[],"private_skills":[]}',
            encoding="utf-8",
        )
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="Old Name",
                description="old",
                soul="old soul",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).put(
            "/api/agents/general",
            json={
                "display_name": "New Name",
                "description": "new",
                "model": None,
                "soul": "new soul",
            },
        )

        assert r.status_code == 200
        assert r.json()["display_name"] == "New Name"
        assert registry.get("general").display_name == "New Name"
        assert "New Name" in (tmp_path / "general" / "profile.jsonc").read_text(encoding="utf-8")
        assert (agent_core / "SOUL.md").read_text(encoding="utf-8") == "new soul"

    def test_update_agent_rolls_back_files_when_load_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        agent_core = tmp_path / "general" / "agent-core"
        agent_core.mkdir(parents=True)
        profile_path = tmp_path / "general" / "profile.jsonc"
        old_profile = (
            '{"id":"general","name":"Old Name","description":"old",'
            '"model":{"provider":"auto","name":"auto"}}'
        )
        profile_path.write_text(old_profile, encoding="utf-8")
        soul_path = agent_core / "SOUL.md"
        soul_path.write_text("old soul", encoding="utf-8")
        (agent_core / "tool-registry.jsonc").write_text(
            '{"arms":["web_read"],"extra_affinity":[],"private_skills":[]}',
            encoding="utf-8",
        )
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="Old Name",
                description="old",
                soul="old soul",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )

        def fail_load(*_args, **_kwargs):
            raise ValueError("broken reload")

        monkeypatch.setattr("runtime.execution.agents.loader.load_agent", fail_load)
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).put(
            "/api/agents/general",
            json={"display_name": "New Name", "description": "new", "soul": "new soul"},
        )

        assert r.status_code == 500
        assert profile_path.read_text(encoding="utf-8") == old_profile
        assert soul_path.read_text(encoding="utf-8") == "old soul"
        assert registry.get("general").display_name == "Old Name"

    def test_tool_registry_update_rolls_back_when_load_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        agent_core = tmp_path / "general" / "agent-core"
        agent_core.mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text(
            '{"id":"general","name":"Old Name","description":"old"}',
            encoding="utf-8",
        )
        tool_registry = agent_core / "tool-registry.jsonc"
        old_tool_registry = '{"arms":["web_read"],"extra_affinity":[],"private_skills":[]}'
        tool_registry.write_text(old_tool_registry, encoding="utf-8")
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="Old Name",
                description="old",
                soul="old soul",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )

        def fail_load(*_args, **_kwargs):
            raise ValueError("broken registry")

        monkeypatch.setattr("runtime.execution.agents.loader.load_agent", fail_load)
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).put(
            "/api/agents/general/tool-registry",
            json={"arms": ["web_read"], "extra_affinity": ["new"]},
        )

        assert r.status_code == 400
        assert tool_registry.read_text(encoding="utf-8") == old_tool_registry

    def test_detail_arm_fields(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        data = TestClient(app).get("/api/agents/coder").json()
        arm = data["arms"][0]
        for key in ["arm_id", "display_name", "description", "affinity", "icon"]:
            assert key in arm

    def test_generate_agent_visuals_mock_writes_three_views(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setenv("OCTOPUS_IMAGE_GEN_PROVIDER", "mock")
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text(
            '{"id":"general","name":"Octopus","description":"general"}',
            encoding="utf-8",
        )
        registry = AgentRegistry()
        registry.register(
            Agent(
                agent_id="general",
                display_name="Octopus",
                description="general",
                soul="",
                arms=ArmPool([make_web_read_arm(_rt())]),
            )
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).post("/api/agents/general/visuals/generate", json={})

        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "mock"
        assert set(data["visual_urls"]) == {"front", "side", "back"}
        assert data["avatar_url"].startswith("/api/agents/general/avatar?v=")
        for view in ("front", "side", "back"):
            assert (tmp_path / "general" / "visuals" / f"{view}.svg").is_file()
        assert (tmp_path / "general" / "avatar.svg").is_file()

    def test_agent_visual_prompt_requests_standee_not_infocard(self):
        from runtime.execution.misc.image_generation import (
            _agent_visual_view_prompt,
            build_agent_visual_prompt,
        )

        prompt = build_agent_visual_prompt(
            agent_id="coder",
            display_name="Coder",
            description="Writes code",
            style_prompt="sharp jacket, calm engineer",
        )
        view_prompt = _agent_visual_view_prompt(
            base_prompt=prompt,
            view="front",
            agent_id="coder",
            display_name="Coder",
        )

        assert "full-body character standee" in prompt
        assert "agent-visual-kit" in prompt
        assert "separate replacement avatar.png generated" in prompt
        assert "separate large headshot avatar" in prompt
        assert "full head, hair, hands, and feet" in prompt
        assert "profile card" in prompt
        assert "half-body crop" in prompt
        assert "No text" in prompt
        assert "no UI frame" in prompt
        assert "no stat panels" in prompt
        assert "agent-visual-kit" in view_prompt
        assert "around the hair" in view_prompt
        assert "chroma-key" in view_prompt
        assert "info card" not in view_prompt.lower()
        assert "labels for name" not in view_prompt.lower()

    def test_postprocess_agent_visual_removes_chroma_and_makes_avatar(self, tmp_path: Path):
        pytest.importorskip("PIL")
        from PIL import Image, ImageDraw

        from runtime.execution.misc.image_generation import (
            _make_avatar_from_front,
            _postprocess_agent_visual,
        )

        path = tmp_path / "front.png"
        image = Image.new("RGBA", (320, 480), (0, 255, 0, 255))
        draw = ImageDraw.Draw(image)
        draw.ellipse((125, 40, 195, 110), fill=(240, 220, 205, 255))
        draw.rectangle((105, 112, 215, 370), fill=(48, 68, 96, 255))
        image.save(path)

        _postprocess_agent_visual(path)
        processed = Image.open(path).convert("RGBA")

        assert processed.getchannel("A").getextrema()[0] == 0
        bbox = processed.getchannel("A").getbbox()
        assert bbox is not None
        assert bbox[0] > 0
        assert bbox[1] > 0
        assert bbox[2] < processed.width
        assert bbox[3] < processed.height

        avatar = _make_avatar_from_front(path, tmp_path / "avatar.png")
        assert avatar is not None
        avatar_image = Image.open(avatar).convert("RGBA")
        assert avatar_image.size == (512, 512)
        avatar_bbox = avatar_image.getchannel("A").getbbox()
        assert avatar_bbox is not None
        assert avatar_bbox[2] - avatar_bbox[0] >= 430
        assert avatar_bbox[3] - avatar_bbox[1] >= 400

    def test_agnes_generation_payload_accepts_reference_images(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import json
        from contextlib import contextmanager

        from runtime.execution.misc import image_generation

        captured: dict[str, object] = {}

        class FakeResponse:
            def read(self) -> bytes:
                return b'{"data":[{"b64_json":"AA=="}]}'

        @contextmanager
        def fake_urlopen(req, timeout):  # noqa: ANN001
            captured["timeout"] = timeout
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            yield FakeResponse()

        monkeypatch.setattr(image_generation.urllib.request, "urlopen", fake_urlopen)

        data = image_generation._post_agnes_image_generation(
            base_url="https://example.test/v1",
            api_key="secret",
            model="agnes-image-2.0-flash",
            prompt="front view",
            size="1024x1536",
            timeout=12,
            reference_images=["data:image/png;base64,abc", "https://img.test/ref.png"],
        )

        assert data["data"][0]["b64_json"] == "AA=="
        assert captured["url"] == "https://example.test/v1/images/generations"
        assert captured["timeout"] == 12
        body = captured["body"]
        assert isinstance(body, dict)
        assert body["model"] == "agnes-image-2.0-flash"
        assert body["extra_body"] == {
            "image": ["data:image/png;base64,abc", "https://img.test/ref.png"]
        }

    def test_agnes_generates_separate_avatar_image(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        import base64

        pytest.importorskip("PIL")
        from PIL import Image

        from runtime.execution.misc import image_generation

        prompts: list[tuple[str, str]] = []

        def fake_post_agnes_image_generation(**kwargs):  # noqa: ANN003, ANN202
            prompts.append((kwargs["size"], kwargs["prompt"]))
            return {
                "data": [
                    {"b64_json": base64.b64encode(_png_bytes((0, 255, 0, 255))).decode("ascii")}
                ]
            }

        def fake_write(data, output, *, timeout):  # noqa: ANN001
            image = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
            draw = Image.new("RGBA", (320, 420), (240, 220, 205, 255))
            image.alpha_composite(draw, (96, 46))
            output.write_bytes(_image_bytes(image))

        monkeypatch.setenv("AGNES_API_KEY", "test-key")
        monkeypatch.setattr(
            image_generation,
            "_post_agnes_image_generation",
            fake_post_agnes_image_generation,
        )
        monkeypatch.setattr(image_generation, "_write_agnes_image_result", fake_write)

        result = image_generation.generate_agent_visuals(
            agent_id="coder",
            display_name="Coder",
            description="Writes code",
            output_dir=tmp_path / "coder" / "visuals",
            provider="agnes",
        )

        assert len(prompts) == 4
        assert prompts[-1][0] == "512x512"
        assert "square close-up avatar portrait" in prompts[-1][1]
        assert "no full body" in prompts[-1][1]
        assert (tmp_path / "coder" / "avatar.png").is_file()
        assert result.files["avatar"] == tmp_path / "coder" / "avatar.png"

    def test_get_agent_visual_serves_generated_view(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        visuals = tmp_path / "general" / "visuals"
        visuals.mkdir(parents=True)
        (visuals / "front.svg").write_text("<svg></svg>", encoding="utf-8")
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry()))

        r = TestClient(app).get("/api/agents/general/visuals/front")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestLocalPartners:
    def test_list_local_partners_reports_detection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))

        def fake_which(commands: list[str]) -> tuple[str | None, str | None]:
            if any(cmd.startswith("codex") for cmd in commands):
                return "codex", str(tmp_path / "codex.exe")
            if "trae-cli" in commands:
                return "trae-cli", str(tmp_path / "trae-cli")
            if "codebuddy" in commands:
                return "codebuddy", str(tmp_path / "codebuddy")
            return None, None

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            fake_which,
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))

        r = TestClient(app).get("/api/agents/local-partners")

        assert r.status_code == 200
        partners = {p["id"]: p for p in r.json()["partners"]}
        assert partners["codex-cli"]["detected"] is True
        assert partners["codex-cli"]["registered"] is False
        assert partners["codex-cli"]["agent_id"] == "local_codex_cli"
        assert partners["codex-cli"]["avatar_url"] == "https://chatgpt.com/favicon.ico"
        assert partners["codex-cli"]["ready"] is True
        assert partners["codex-cli"]["headless_supported"] is True
        assert partners["codex-cli"]["readiness_status"] == "ready"
        assert partners["codex-cli"]["native_command"] == "codex"
        assert partners["codex-cli"]["native_launch_command"].startswith("cd ")
        assert partners["codex-cli"]["native_launch_command"].endswith(" && codex")
        assert "codex exec" in partners["codex-cli"]["verify_command"]
        assert "/model <模型名>" in partners["codex-cli"]["interaction_hint"]
        assert partners["codex-cli"]["command_hints"][0] == {
            "command": "/model <模型名>",
            "scope": "一次性覆盖",
            "behavior": "换行接任务时，转成该 CLI 本次调用的模型参数。",
        }
        assert partners["trae-cli"]["detected"] is True
        assert partners["trae-cli"]["agent_id"] == "local_trae_cli"
        assert "traecdn" in partners["trae-cli"]["avatar_url"]
        assert partners["trae-cli"]["native_command"] == "trae-cli"
        assert partners["trae-cli"]["native_launch_command"].endswith(" && trae-cli")
        assert partners["trae-cli"]["verify_command"] == "trae-cli models --json"
        assert "模型选择" in partners["trae-cli"]["setup_hint"]
        assert "Trae CLI 自己管理" in partners["trae-cli"]["interaction_hint"]
        assert partners["trae-cli"]["command_hints"][0]["scope"] == "CLI 默认"
        assert partners["trae-cli"]["command_hints"][-1]["command"] == "trae-cli models --json"
        assert partners["qoder-cli"]["detected"] is False
        assert partners["qoder-cli"]["agent_id"] == "local_qoder_cli"
        assert "alicdn" in partners["qoder-cli"]["avatar_url"]
        assert partners["qoder-cli"]["native_command"] is None
        assert partners["kimi-cli"]["detected"] is False
        assert partners["kimi-cli"]["agent_id"] == "local_kimi_cli"
        assert partners["kimi-cli"]["avatar_url"] == "https://www.kimi.com/favicon.ico"
        assert partners["kimi-cli"]["ready"] is False
        assert partners["codebuddy-cli"]["detected"] is True
        assert partners["codebuddy-cli"]["agent_id"] == "local_codebuddy_cli"
        assert "codebuddy" in partners["codebuddy-cli"]["avatar_url"]
        assert partners["codebuddy-cli"]["ready"] is True
        assert partners["codebuddy-cli"]["native_command"] == "codebuddy"
        assert partners["codebuddy-cli"]["native_launch_command"].endswith(" && codebuddy")
        assert "codebuddy -p --output-format text" in partners["codebuddy-cli"]["verify_command"]
        assert partners["codebuddy-cli"]["install_command"] is None
        assert "原生 CLI 使用" in partners["codebuddy-cli"]["interaction_hint"]
        assert partners["codebuddy-cli"]["command_hints"][0]["scope"] == "一次性覆盖"
        assert partners["openclaw"]["detected"] is False
        assert partners["openclaw"]["readiness_status"] == "missing"

    def test_local_partner_copy_commands_quote_shell_special_paths(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        executable = tmp_path / "Code Buddy (Beta)" / "codebuddy"
        executable.parent.mkdir()
        executable.touch()

        def fake_which(commands: list[str]) -> tuple[str | None, str | None]:
            if "codebuddy" in commands:
                return str(executable), str(executable)
            return None, None

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            fake_which,
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))

        r = TestClient(app).get("/api/agents/local-partners")

        assert r.status_code == 200
        partners = {p["id"]: p for p in r.json()["partners"]}
        codebuddy = partners["codebuddy-cli"]
        assert codebuddy["native_command"].startswith("'")
        assert "Code Buddy (Beta)" in codebuddy["native_command"]
        assert codebuddy["native_launch_command"].endswith(
            f" && {codebuddy['native_command']}"
        )

    def test_register_local_partner_creates_real_agent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))

        def fake_which(commands: list[str]) -> tuple[str | None, str | None]:
            if any(cmd.startswith("codex") for cmd in commands):
                return "codex", str(tmp_path / "codex.exe")
            return None, None

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            fake_which,
        )
        registry = AgentRegistry()
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))
        client = TestClient(app)

        r = client.post(
            "/api/agents/local-partners/register",
            json={"partners": [{"id": "codex-cli", "alias": "Codex 本地伙伴"}]},
        )

        assert r.status_code == 200
        data = r.json()
        assert data["registered_count"] == 1
        assert data["results"][0]["status"] == "registered"
        assert registry.has("local_codex_cli")
        assert (tmp_path / "local_codex_cli" / "profile.jsonc").is_file()
        assert (tmp_path / "local_codex_cli" / "agent-core" / "SOUL.md").is_file()

        agents = client.get("/api/agents").json()
        local_agent = next(a for a in agents if a["name"] == "local_codex_cli")
        assert local_agent["display_name"] == "Codex 本地伙伴"
        assert local_agent["capabilities"]["local_partner"] is True

        duplicate = client.post(
            "/api/agents/local-partners/register",
            json={"partners": [{"id": "codex-cli"}]},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["already_exists_count"] == 1
        assert duplicate.json()["results"][0]["status"] == "already_exists"

    def test_register_missing_local_partner_skips_without_creating_agent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda _commands: (None, None),
        )
        registry = AgentRegistry()
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).post(
            "/api/agents/local-partners/register",
            json={"partners": [{"id": "openclaw"}]},
        )

        assert r.status_code == 200
        assert r.json()["skipped_count"] == 1
        assert r.json()["results"][0]["status"] == "not_detected"
        assert not registry.has("local_openclaw")
        assert not (tmp_path / "local_openclaw").exists()

    def test_codebuddy_launcher_only_is_detected_but_not_registerable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))

        launcher = "/Users/me/.codebuddy/bin/buddy"
        app_code = "/Volumes/CodeBuddy/CodeBuddy.app/Contents/Resources/app/bin/code"

        def fake_which(commands: list[str]) -> tuple[str | None, str | None]:
            if "~/.codebuddy/bin/buddy" in commands:
                return launcher, app_code
            return None, None

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            fake_which,
        )
        registry = AgentRegistry()
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))
        client = TestClient(app)

        partners = {p["id"]: p for p in client.get("/api/agents/local-partners").json()["partners"]}
        assert partners["codebuddy-cli"]["detected"] is True
        assert partners["codebuddy-cli"]["ready"] is False
        assert partners["codebuddy-cli"]["readiness_status"] == "launcher_only"
        assert "headless CLI" in partners["codebuddy-cli"]["readiness_message"]
        assert partners["codebuddy-cli"]["native_command"] == launcher
        assert partners["codebuddy-cli"]["verify_command"] is None
        assert partners["codebuddy-cli"]["install_command"] is None

        r = client.post(
            "/api/agents/local-partners/register",
            json={"partners": [{"id": "codebuddy-cli"}]},
        )

        assert r.status_code == 200
        assert r.json()["skipped_count"] == 1
        assert r.json()["results"][0]["status"] == "launcher_only"
        assert not registry.has("local_codebuddy_cli")

    def test_codebuddy_missing_reports_install_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: (None, None),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        partners = {p["id"]: p for p in client.get("/api/agents/local-partners").json()["partners"]}

        assert partners["codebuddy-cli"]["detected"] is False
        assert partners["codebuddy-cli"]["install_command"] == (
            "npm install -g @tencent-ai/codebuddy-code"
        )
        assert partners["codebuddy-cli"]["native_command"] is None
        assert partners["codebuddy-cli"]["verify_command"] is None

    def test_local_partner_command_hints_have_explicit_openapi_schema(self):
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))

        schemas = app.openapi()["components"]["schemas"]

        assert schemas["LocalPartnerCommandHint"]["properties"] == {
            "command": {"title": "Command", "type": "string"},
            "scope": {"title": "Scope", "type": "string"},
            "behavior": {"title": "Behavior", "type": "string"},
        }
        command_hints = schemas["LocalPartnerWire"]["properties"]["command_hints"]
        assert command_hints["items"]["$ref"] == "#/components/schemas/LocalPartnerCommandHint"

    def test_probe_local_partner_success(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.execution.agents.local_partner_bridge import LocalPartnerResult
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: ("codex", str(tmp_path / "codex"))
            if any(cmd.startswith("codex") for cmd in commands)
            else (None, None),
        )
        monkeypatch.setattr(agents_router_module, "_safe_local_partner_executable", lambda _: True)
        seen: dict = {}

        def fake_run(**kw):
            seen.update(kw)
            return LocalPartnerResult(ok=True, output="OK", exit_code=0)

        monkeypatch.setattr(agents_local_partner, "run_local_partner", fake_run)
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.post("/api/agents/local-partners/codex-cli/probe")

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "ok"
        assert data["output"] == "OK"
        assert data["detected"] is True
        assert data["ready"] is True
        assert data["failure_kind"] is None
        assert seen["partner_id"] == "codex-cli"
        assert seen["command"] == str(tmp_path / "codex")
        assert "不要修改文件" in seen["prompt"]

    def test_probe_local_partner_surfaces_diagnosis(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.execution.agents.local_partner_bridge import LocalPartnerResult
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: ("codex", str(tmp_path / "codex"))
            if any(cmd.startswith("codex") for cmd in commands)
            else (None, None),
        )
        monkeypatch.setattr(agents_router_module, "_safe_local_partner_executable", lambda _: True)

        monkeypatch.setattr(
            agents_local_partner,
            "run_local_partner",
            lambda **kw: LocalPartnerResult(
                ok=False,
                error="Codex CLI 需要登录或授权\n建议：打开原生 CLI。\n\n原始错误：\nnot logged in",
                raw_error="not logged in",
                exit_code=1,
                failure_kind="auth",
                failure_title="Codex CLI 需要登录或授权",
                fix_hint="请打开原生 CLI：`codex`。",
            ),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.post("/api/agents/local-partners/codex-cli/probe")

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["status"] == "auth"
        assert data["raw_error"] == "not logged in"
        assert data["failure_kind"] == "auth"
        assert data["failure_title"] == "Codex CLI 需要登录或授权"
        assert "原生 CLI" in data["fix_hint"]

    def test_probe_local_partner_reports_not_ready_without_spawning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: ("trae-cli", str(tmp_path / "trae-cli"))
            if "trae-cli" in commands
            else (None, None),
        )
        monkeypatch.setattr(agents_router_module, "_safe_local_partner_executable", lambda _: True)

        class _Proc:
            stdout = "[]"

        monkeypatch.setattr(
            agents_local_partner.subprocess,
            "run",
            lambda *args, **kwargs: _Proc(),
        )
        monkeypatch.setattr(
            agents_local_partner,
            "run_local_partner",
            lambda **kw: (_ for _ in ()).throw(AssertionError("should not spawn")),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.post("/api/agents/local-partners/trae-cli/probe")

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["detected"] is True
        assert data["ready"] is False
        assert data["status"] == "model_unconfigured"
        assert "没有有效模型配置" in data["error"]

    def test_probe_local_partner_rejects_unsafe_executable(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: ("codex", str(tmp_path / "codex"))
            if any(cmd.startswith("codex") for cmd in commands)
            else (None, None),
        )
        monkeypatch.setattr(agents_router_module, "_safe_local_partner_executable", lambda _: False)
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.post("/api/agents/local-partners/codex-cli/probe")

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is False
        assert data["status"] == "unsafe_executable"
        assert data["failure_kind"] == "unsafe_executable"

    def test_register_trae_local_partner_creates_real_agent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))

        def fake_which(commands: list[str]) -> tuple[str | None, str | None]:
            if "trae-cli" in commands:
                return "trae-cli", str(tmp_path / "trae-cli")
            return None, None

        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            fake_which,
        )
        registry = AgentRegistry()
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).post(
            "/api/agents/local-partners/register",
            json={"partners": [{"id": "trae-cli", "alias": "Trae 本地伙伴"}]},
        )

        assert r.status_code == 200
        data = r.json()
        assert data["registered_count"] == 1
        assert data["results"][0]["status"] == "registered"
        assert registry.has("local_trae_cli")
        profile = tmp_path / "local_trae_cli" / "profile.jsonc"
        assert profile.is_file()
        text = profile.read_text(encoding="utf-8")
        assert '"local_partner_id": "trae-cli"' in text
        assert '"local_partner_command": "trae-cli"' in text
        agents = TestClient(app).get("/api/agents").json()
        local_agent = next(a for a in agents if a["name"] == "local_trae_cli")
        assert "traecdn" in local_agent["avatar_url"]

    def test_local_partner_model_reports_domestic_cli_defaults(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_local_partner,
            "which_command",
            lambda commands: ("trae-cli", "/usr/bin/trae-cli")
            if "trae-cli" in commands
            else (None, None),
        )

        class _Proc:
            stdout = '[{"name":"trae-default"}]'

        monkeypatch.setattr(
            agents_local_partner.subprocess,
            "run",
            lambda *args, **kwargs: _Proc(),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        trae = client.get("/api/agents/local-partners/trae-cli/model")
        qoder = client.get("/api/agents/local-partners/qoder-cli/model")
        kimi = client.get("/api/agents/local-partners/kimi-cli/model")
        codebuddy = client.get("/api/agents/local-partners/codebuddy-cli/model")

        assert trae.status_code == 200
        assert trae.json() == {
            "partner_id": "trae-cli",
            "model": "Trae CLI 默认",
            "source": "trae-cli",
        }
        assert qoder.status_code == 200
        assert qoder.json()["model"] == "Qoder CLI 默认"
        assert kimi.status_code == 200
        assert kimi.json()["model"] == "Kimi CLI 默认"
        assert codebuddy.status_code == 200
        assert codebuddy.json()["model"] == "CodeBuddy 默认"

    def test_trae_partner_model_reports_unconfigured_when_models_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            agents_router_module,
            "_which_local_partner_command",
            lambda commands: ("trae-cli", "/usr/bin/trae-cli")
            if "trae-cli" in commands
            else (None, None),
        )
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_local_partner,
            "which_command",
            lambda commands: ("trae-cli", "/usr/bin/trae-cli")
            if "trae-cli" in commands
            else (None, None),
        )

        class _Proc:
            stdout = "[]"

        monkeypatch.setattr(
            agents_local_partner.subprocess,
            "run",
            lambda *args, **kwargs: _Proc(),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.get("/api/agents/local-partners/trae-cli/model")

        assert r.status_code == 200
        assert r.json() == {
            "partner_id": "trae-cli",
            "model": "未配置模型",
            "source": "trae-cli models --json",
        }

    def test_codebuddy_partner_model_reports_supported_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from runtime.sensing.gateway import agents_local_partner

        monkeypatch.setattr(
            agents_local_partner,
            "which_command",
            lambda commands: ("codebuddy", "/usr/bin/codebuddy")
            if "codebuddy" in commands
            else (None, None),
        )

        class _Proc:
            stdout = (
                "Usage: codebuddy [options]\n"
                "  --model <model>  Currently supported: "
                "(default-model, gpt-5.5, gpt-5.3-codex, kimi-k2.5)"
            )
            stderr = ""

        monkeypatch.setattr(
            agents_local_partner.subprocess,
            "run",
            lambda *args, **kwargs: _Proc(),
        )
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry(), runtime=_rt()))
        client = TestClient(app)

        r = client.get("/api/agents/local-partners/codebuddy-cli/model")

        assert r.status_code == 200
        assert r.json() == {
            "partner_id": "codebuddy-cli",
            "model": "CodeBuddy 默认",
            "source": "codebuddy --help",
            "models": ["default-model", "gpt-5.5", "gpt-5.3-codex", "kimi-k2.5"],
        }


class TestAuth:
    def test_require_auth_blocks_anon(self, registry_with_presets):
        store = IdentityStore()
        app = FastAPI()
        app.include_router(
            create_agents_router(
                registry=registry_with_presets,
                identity_store=store,
                require_auth=True,
            )
        )
        r = TestClient(app).get("/api/agents")
        assert r.status_code == 401

    def test_api_key_lets_through(self, registry_with_presets):
        store = IdentityStore()
        store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
        app = FastAPI()
        app.include_router(
            create_agents_router(
                registry=registry_with_presets,
                identity_store=store,
                require_auth=True,
            )
        )
        r = TestClient(app).get(
            "/api/agents",
            headers={"Authorization": "Bearer sk-alice"},
        )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


def _build_chat_stack(tmp_path: Path):

    from runtime.core.cerebrum import StaticPlanner
    from runtime.core.cerebrum.planner import Rule
    from runtime.execution.suckers import SkillRegistry
    from runtime.execution.suckers.builtins import register_all
    from runtime.execution.tool_engine import ToolExecutor
    from runtime.memory.journal import JSONLJournal
    from runtime.platform.models import BudgetSpec, SkillId
    from runtime.safety.auth import TrustEngine

    journal = JSONLJournal(tmp_path / "events.jsonl")
    registry = SkillRegistry()
    register_all(registry)
    executor = ToolExecutor(
        registry=registry,
        immunity=TrustEngine(trusted_sources=["skill://public/*"]),
        journal=journal,
    )
    runtime = GraphRuntime(executor=executor, journal=journal)
    planner = StaticPlanner(
        rules=[
            Rule(
                name="default",
                intent_types=["task"],
                skill_sequence=[SkillId("list_cwd")],
            )
        ],
        default_budget=BudgetSpec(tokens=10_000, usd=0.10),
        fallback_skill=SkillId("list_cwd"),
    )

    class _Stack:
        pass

    s = _Stack()
    s.planner = planner
    s.runtime = runtime
    s.registry = registry
    s.journal = journal
    return s


class TestChatAgentRouting:
    def test_valid_agent_id_accepted(self, tmp_path: Path):
        """Implementation note."""
        from runtime.sensing.gateway.openai_gateway_router import create_openai_router

        stack = _build_chat_stack(tmp_path)
        agent_reg = AgentRegistry()
        agent_reg.register(make_general_agent(_rt()))

        app = FastAPI()
        app.include_router(
            create_openai_router(
                stack,
                agent_registry=agent_reg,
            )
        )
        r = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "octopus-agent",
                "messages": [{"role": "user", "content": "list files"}],
                "agent": "general",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["octopus"]["agent"] == "general"

    def test_unknown_agent_falls_back_gracefully(self, tmp_path: Path):
        """Implementation note."""
        from runtime.sensing.gateway.openai_gateway_router import create_openai_router

        stack = _build_chat_stack(tmp_path)
        agent_reg = AgentRegistry()

        app = FastAPI()
        app.include_router(
            create_openai_router(
                stack,
                agent_registry=agent_reg,
            )
        )
        r = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "octopus-agent",
                "messages": [{"role": "user", "content": "x"}],
                "agent": "ghost",
            },
        )
        assert r.status_code == 200

    def test_agent_param_without_registry_400(self, tmp_path: Path):
        """Implementation note."""
        from runtime.sensing.gateway.openai_gateway_router import create_openai_router

        stack = _build_chat_stack(tmp_path)
        app = FastAPI()
        app.include_router(create_openai_router(stack))  # no agent_registry
        r = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "x",
                "messages": [{"role": "user", "content": "x"}],
                "agent": "coder",
            },
        )
        assert r.status_code == 400

    def test_no_agent_param_backward_compat(self, tmp_path: Path):
        """Implementation note."""
        from runtime.sensing.gateway.openai_gateway_router import create_openai_router

        stack = _build_chat_stack(tmp_path)
        agent_reg = AgentRegistry()
        agent_reg.register(make_general_agent(_rt()))

        app = FastAPI()
        app.include_router(
            create_openai_router(
                stack,
                agent_registry=agent_reg,
            )
        )
        r = TestClient(app).post(
            "/v1/chat/completions",
            json={
                "model": "x",
                "messages": [{"role": "user", "content": "list files"}],
            },
        )
        assert r.status_code == 200
        # Implementation note.
        assert "agent" not in r.json()["octopus"]


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestIsolation:
    def test_coder_vs_general_allowed_skills_differ(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        client = TestClient(app)

        coder = client.get("/api/agents/coder").json()
        general = client.get("/api/agents/general").json()

        coder_skills = set(coder["allowed_skills"])
        general_skills = set(general["allowed_skills"])

        # General currently uses a wildcard private-skills grant. The
        # configuration UI owns narrowing it later; this endpoint should
        # preserve the wildcard instead of expanding it into a stale list.
        assert "git_commit" in coder_skills
        assert "*" in general_skills

        # Implementation note.
        assert "web_search" in coder_skills

    def test_custom_agent_with_narrow_tool_set(self):
        """Implementation note."""
        rt = _rt()
        # Implementation note.
        readonly_git_arm = Worker(
            arm_id="git_readonly",
            affinity=["git", "readonly"],
            allowed_skills=[],  # Implementation note.
            runtime=rt,
            display_name="Git Read-Only",
            icon="🔎",
        )
        from runtime.execution.agents import Agent

        custom = Agent(
            agent_id="git_auditor",
            display_name="Git Auditor",
            description="Read-only git inspector.",
            soul="You audit git history without modifying it.",
            icon="🕵️",
            arms=ArmPool([readonly_git_arm, make_web_read_arm(rt)]),
            extra_affinity=["audit"],
        )
        reg = AgentRegistry()
        reg.register(custom)

        app = FastAPI()
        app.include_router(create_agents_router(registry=reg))
        r = TestClient(app).get("/api/agents/git_auditor")
        assert r.status_code == 200
        data = r.json()
        assert data["display_name"] == "Git Auditor"
        assert "audit" in data["extra_affinity"]
        # Implementation note.
        assert set(data["tool_groups"]) == {"git_readonly", "web_read_arm"}
