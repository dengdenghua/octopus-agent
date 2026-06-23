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
            "general", "coder", "vibe_selling",
            "ecommerce_mind", "market_researcher",
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
                "name", "display_name", "description", "icon",
                "avatar_url", "visual_urls", "model", "tool_groups", "soul",
            ]:
                assert key in agent, f"missing '{key}' in {agent['name']}"

    def test_tool_groups_are_arm_ids(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        data = TestClient(app).get("/api/agents").json()
        coder = next(a for a in data if a["name"] == "coder")
        assert coder["tool_groups"] == [
            "web_read_arm", "fs_writer_arm", "git_arm", "shell_arm",
            "coder_private_arm",
        ]

    def test_empty_registry_returns_empty_list(self):
        app = FastAPI()
        app.include_router(create_agents_router(registry=AgentRegistry()))
        assert TestClient(app).get("/api/agents").json() == []

    def test_system_and_capability_agents_are_hidden_from_list(self):
        registry = AgentRegistry()
        registry.register(Agent(
            agent_id="general",
            display_name="Octopus",
            description="",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
        registry.register(Agent(
            agent_id="admin",
            display_name="Admin",
            description="",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
        registry.register(Agent(
            agent_id="desktop_operator",
            display_name="Desktop Operator",
            description="[legacy] desktop automation persona",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
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

    def test_delete_agent_removes_disk_and_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        (tmp_path / "custom_agent" / "agent-core").mkdir(parents=True)
        (tmp_path / "custom_agent" / "profile.jsonc").write_text("{}", encoding="utf-8")
        registry = AgentRegistry()
        registry.register(Agent(
            agent_id="custom_agent",
            display_name="Custom Agent",
            description="",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).delete("/api/agents/custom_agent")

        assert r.status_code == 204
        assert not registry.has("custom_agent")
        assert not (tmp_path / "custom_agent").exists()

    def test_delete_builtin_agent_is_rejected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text("{}", encoding="utf-8")
        registry = AgentRegistry()
        registry.register(Agent(
            agent_id="general",
            display_name="General",
            description="",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry))

        r = TestClient(app).delete("/api/agents/general")

        assert r.status_code == 400
        assert registry.has("general")
        assert (tmp_path / "general").exists()

    def test_market_install_hot_registers_and_uninstall_removes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    def test_market_uninstall_rejects_local_agent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setattr(agent_world_router, "_INSTALL_STATE", tmp_path / "installed.json")
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text("{}", encoding="utf-8")
        app = FastAPI()
        app.include_router(create_agent_world_router())

        r = TestClient(app).delete("/api/agent-market/store/general/install")

        assert r.status_code == 400
        assert (tmp_path / "general").exists()

    def test_market_store_preserves_local_agent_tool_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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

    def test_update_agent_display_name_writes_profile_and_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        registry.register(Agent(
            agent_id="general",
            display_name="Old Name",
            description="old",
            soul="old soul",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry, runtime=_rt()))

        r = TestClient(app).put(
            "/api/agents/general",
            json={"display_name": "New Name", "description": "new", "model": None, "soul": "new soul"},
        )

        assert r.status_code == 200
        assert r.json()["display_name"] == "New Name"
        assert registry.get("general").display_name == "New Name"
        assert "New Name" in (tmp_path / "general" / "profile.jsonc").read_text(encoding="utf-8")
        assert (agent_core / "SOUL.md").read_text(encoding="utf-8") == "new soul"

    def test_detail_arm_fields(self, registry_with_presets):
        app = FastAPI()
        app.include_router(create_agents_router(registry=registry_with_presets))
        data = TestClient(app).get("/api/agents/coder").json()
        arm = data["arms"][0]
        for key in ["arm_id", "display_name", "description", "affinity", "icon"]:
            assert key in arm

    def test_generate_agent_visuals_mock_writes_three_views(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("OCTOPUS_AGENTS_ROOT", str(tmp_path))
        monkeypatch.setenv("OCTOPUS_IMAGE_GEN_PROVIDER", "mock")
        (tmp_path / "general" / "agent-core").mkdir(parents=True)
        (tmp_path / "general" / "profile.jsonc").write_text(
            '{"id":"general","name":"Octopus","description":"general"}',
            encoding="utf-8",
        )
        registry = AgentRegistry()
        registry.register(Agent(
            agent_id="general",
            display_name="Octopus",
            description="general",
            soul="",
            arms=ArmPool([make_web_read_arm(_rt())]),
        ))
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

        from PIL import Image

        from runtime.execution.misc import image_generation

        prompts: list[tuple[str, str]] = []

        def fake_post_agnes_image_generation(**kwargs):  # noqa: ANN003, ANN202
            prompts.append((kwargs["size"], kwargs["prompt"]))
            return {
                "data": [
                    {
                        "b64_json": base64.b64encode(
                            _png_bytes((0, 255, 0, 255))
                        ).decode("ascii")
                    }
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

    def test_get_agent_visual_serves_generated_view(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        assert partners["openclaw"]["detected"] is False

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


class TestAuth:
    def test_require_auth_blocks_anon(self, registry_with_presets):
        store = IdentityStore()
        app = FastAPI()
        app.include_router(create_agents_router(
            registry=registry_with_presets,
            identity_store=store, require_auth=True,
        ))
        r = TestClient(app).get("/api/agents")
        assert r.status_code == 401

    def test_api_key_lets_through(self, registry_with_presets):
        store = IdentityStore()
        store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
        app = FastAPI()
        app.include_router(create_agents_router(
            registry=registry_with_presets,
            identity_store=store, require_auth=True,
        ))
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
        app.include_router(create_openai_router(
            stack,
            agent_registry=agent_reg,
        ))
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
        app.include_router(create_openai_router(
            stack, agent_registry=agent_reg,
        ))
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
        app.include_router(create_openai_router(
            stack, agent_registry=agent_reg,
        ))
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
