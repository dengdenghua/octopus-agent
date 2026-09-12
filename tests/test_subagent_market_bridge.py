"""子 agent 与角色市场的身份桥：已安装角色是职位与头像的唯一来源。

三条铁律：
1. 正向——已安装角色自动成为可派发子 agent（scope=market，优先级最低）；
2. 反查——任何子 agent 名字都能反查到市场职位与头像；
3. 晋升——使用中没有合适岗位时，子 agent 定义可转正进"我的安装"，
   幂等、不覆盖用户改过的文件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.execution.subagents.market_bridge import (
    market_definitions,
    promote_definition_to_market,
    resolve_market_identity,
)
from runtime.execution.subagents.registry import (
    SubagentDefinition,
    load_subagent_registry,
)


def _make_market_agent(
    root: Path,
    agent_id: str,
    *,
    display_name: str = "",
    description: str = "does things",
    soul: str = "You are the role.",
) -> Path:
    agent_dir = root / agent_id
    core = agent_dir / "agent-core"
    core.mkdir(parents=True, exist_ok=True)
    profile = {
        "id": agent_id,
        "name": display_name or agent_id,
        "description": description,
        "avatar": "avatar.svg",
    }
    (agent_dir / "profile.jsonc").write_text(
        json.dumps(profile, ensure_ascii=False), encoding="utf-8"
    )
    (agent_dir / "avatar.svg").write_text("<svg/>", encoding="utf-8")
    (core / "SOUL.md").write_text(soul, encoding="utf-8")
    return agent_dir


@pytest.fixture()
def agents_root(tmp_path: Path) -> Path:
    root = tmp_path / "agents"
    root.mkdir()
    return root


# ── 正向：市场角色 → 子 agent ──────────────────────────


def test_market_definitions_become_subagents(agents_root: Path):
    _make_market_agent(agents_root, "market-analyst", display_name="市场分析师")
    defs = market_definitions(agents_root)
    assert [d.name for d in defs] == ["market-analyst"]
    d = defs[0]
    assert d.scope == "market"
    assert d.display_name == "市场分析师"
    assert d.system_prompt == "You are the role."
    assert d.avatar_url.startswith("/api/agents/market-analyst/avatar?v=")


def test_market_agent_without_soul_gets_synthesized_prompt(agents_root: Path):
    agent_dir = _make_market_agent(agents_root, "no-soul")
    (agent_dir / "agent-core" / "SOUL.md").unlink()
    defs = market_definitions(agents_root)
    assert "no-soul" in defs[0].system_prompt
    assert defs[0].system_prompt.startswith("You are")


def test_project_definition_overrides_market_same_name(
    agents_root: Path, tmp_path: Path
):
    _make_market_agent(agents_root, "shared", soul="market soul")
    project = tmp_path / "project"
    (project / ".claude" / "agents").mkdir(parents=True)
    (project / ".claude" / "agents" / "shared.md").write_text(
        "---\nname: shared\ndescription: project level\n---\nproject soul",
        encoding="utf-8",
    )
    registry = load_subagent_registry(project_root=project, agents_root=agents_root)
    d = registry.get("shared")
    assert d.scope == "project"
    assert d.system_prompt == "project soul"
    assert registry.has("market-analyst") is False


# ── 反查：子 agent 名字 → 市场身份 ──────────────────────


def test_resolve_identity_matches_id_display_name_and_aliases(
    agents_root: Path,
):
    _make_market_agent(agents_root, "twin-sales", display_name="销售商务")
    by_id = resolve_market_identity("twin-sales", agents_root)
    assert by_id is not None and by_id.display_name == "销售商务"
    by_display = resolve_market_identity("销售商务", agents_root)
    assert by_display is not None and by_display.agent_id == "twin-sales"
    assert resolve_market_identity("nobody", agents_root) is None
    assert resolve_market_identity("", agents_root) is None


# ── 晋升：子 agent → 市场岗位（我的安装）────────────────


def _definition() -> SubagentDefinition:
    return SubagentDefinition(
        name="incident-commander",
        description="指挥故障响应",
        system_prompt="You coordinate incidents.",
        display_name="故障指挥官",
    )


def test_promote_creates_market_agent(agents_root: Path):
    result = promote_definition_to_market(_definition(), agents_root)
    assert result["created"] is True
    assert result["display_name"] == "故障指挥官"
    agent_dir = agents_root / "incident-commander"
    profile = json.loads((agent_dir / "profile.jsonc").read_text(encoding="utf-8"))
    assert profile["name"] == "故障指挥官"
    assert profile["source_kind"] == "subagent-promoted"
    assert (agent_dir / "avatar.svg").is_file()
    soul = (agent_dir / "agent-core" / "SOUL.md").read_text(encoding="utf-8")
    assert soul == "You coordinate incidents."
    # 转正后立刻能被反查、能进可派发池
    identity = resolve_market_identity("incident-commander", agents_root)
    assert identity is not None and identity.display_name == "故障指挥官"
    assert any(d.name == "incident-commander" for d in market_definitions(agents_root))


def test_promote_is_idempotent(agents_root: Path):
    promote_definition_to_market(_definition(), agents_root)
    (agents_root / "incident-commander" / "profile.jsonc").write_text(
        json.dumps({"id": "incident-commander", "name": "用户改过的名字"}),
        encoding="utf-8",
    )
    result = promote_definition_to_market(_definition(), agents_root)
    assert result["created"] is False
    assert result["display_name"] == "用户改过的名字"


def test_promote_rejects_unsafe_names(agents_root: Path):
    bad = SubagentDefinition(name="../escape", description="", system_prompt="")
    with pytest.raises(ValueError):
        promote_definition_to_market(bad, agents_root)


# ── HTTP 层：晋升端点 ──────────────────────────────────


def test_promote_endpoint_creates_installed_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from runtime.execution.subagents import bridge as _bridge
    from runtime.execution.subagents.registry import SubagentRegistry
    from runtime.sensing.gateway.agent_world_router import create_agent_world_router

    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    import runtime.sensing.gateway.agent_world_router as _awr
    import runtime.sensing.gateway._agent_world_helpers as _awh

    monkeypatch.setattr(_awr, "default_agents_root", lambda: agents_root)
    monkeypatch.setattr(_awh, "default_agents_root", lambda: agents_root)
    registry = SubagentRegistry([_definition()])
    monkeypatch.setattr(_bridge, "_REGISTRY", registry)

    app = FastAPI()
    app.include_router(create_agent_world_router())
    client = TestClient(app)

    resp = client.post(
        "/api/agent-market/from-subagent",
        json={"subagent": "incident-commander"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["created"] is True
    assert body["source_subagent"] == "incident-commander"
    assert (agents_root / "incident-commander" / "profile.jsonc").is_file()

    # 出现在"我的安装"（本地角色列表）
    store = client.get("/api/agent-market/store").json()
    ids = {a["id"] for a in store["agents"]}
    assert "incident-commander" in ids

    # 幂等：再晋升一次不报错、不重建
    again = client.post(
        "/api/agent-market/from-subagent",
        json={"subagent": "incident-commander"},
    )
    assert again.status_code == 200
    assert again.json()["created"] is False

    # 未知子 agent 404
    missing = client.post(
        "/api/agent-market/from-subagent", json={"subagent": "ghost"}
    )
    assert missing.status_code == 404


# ── 自动晋升：没有合适岗位时现造一个 ────────────────────


def test_auto_promote_creates_position_for_unknown_lane(agents_root: Path):
    from runtime.execution.subagents.market_bridge import (
        auto_promote_if_unpositioned,
        resolve_market_identity,
    )

    result = auto_promote_if_unpositioned(
        name="incident-commander",
        has_registry_definition=False,
        has_builtin_display=False,
        mission_preview="Handle the production incident end to end.",
        agents_root=agents_root,
    )

    assert result is not None
    assert result["created"] is True
    assert result["display_name"] == "Incident Commander"
    assert result["avatar_url"]
    # 晋升后立刻可反查到市场身份
    identity = resolve_market_identity("incident-commander", agents_root)
    assert identity is not None
    assert identity.display_name == "Incident Commander"
    # SOUL 是临时章程，带首次派发任务预览，可后续在"我的安装"里编辑
    soul = (
        agents_root / "incident-commander" / "agent-core" / "SOUL.md"
    ).read_text(encoding="utf-8")
    assert "production incident" in soul


def test_auto_promote_refuses_known_positions(agents_root: Path):
    from runtime.execution.subagents.market_bridge import (
        auto_promote_if_unpositioned,
    )

    # 有 registry 定义 / 有内置角色展示名的，都不是"没有合适的岗位"
    assert (
        auto_promote_if_unpositioned(
            name="some-lane",
            has_registry_definition=True,
            has_builtin_display=False,
            agents_root=agents_root,
        )
        is None
    )
    assert (
        auto_promote_if_unpositioned(
            name="some-lane",
            has_registry_definition=False,
            has_builtin_display=True,
            agents_root=agents_root,
        )
        is None
    )


def test_auto_promote_refuses_bad_names(agents_root: Path):
    from runtime.execution.subagents.market_bridge import (
        auto_promote_if_unpositioned,
    )

    for bad in ("ab", "123", "lane 1", "角色/路径", ""):
        assert (
            auto_promote_if_unpositioned(
                name=bad,
                has_registry_definition=False,
                has_builtin_display=False,
                agents_root=agents_root,
            )
            is None
        )


def test_auto_promote_kill_switch(agents_root: Path, monkeypatch: pytest.MonkeyPatch):
    from runtime.execution.subagents.market_bridge import (
        auto_promote_if_unpositioned,
    )

    monkeypatch.setenv("OCTOPUS_SUBAGENT_AUTOPROMOTE", "0")
    assert (
        auto_promote_if_unpositioned(
            name="incident-commander",
            has_registry_definition=False,
            has_builtin_display=False,
            agents_root=agents_root,
        )
        is None
    )
    assert not (agents_root / "incident-commander").exists()


def test_auto_promote_idempotent(agents_root: Path):
    from runtime.execution.subagents.market_bridge import (
        auto_promote_if_unpositioned,
    )

    first = auto_promote_if_unpositioned(
        name="incident-commander",
        has_registry_definition=False,
        has_builtin_display=False,
        mission_preview="first",
        agents_root=agents_root,
    )
    # 用户随后改了 SOUL
    soul_path = agents_root / "incident-commander" / "agent-core" / "SOUL.md"
    soul_path.write_text("用户自定义内容", encoding="utf-8")

    second = auto_promote_if_unpositioned(
        name="incident-commander",
        has_registry_definition=False,
        has_builtin_display=False,
        mission_preview="second",
        agents_root=agents_root,
    )

    assert first is not None and second is not None
    assert first["created"] is True and second["created"] is False
    assert soul_path.read_text(encoding="utf-8") == "用户自定义内容"
