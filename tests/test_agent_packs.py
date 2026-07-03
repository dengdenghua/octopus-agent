from __future__ import annotations

import json
from pathlib import Path

from runtime.execution.misc.agent_packs import import_agent_from_pack, scan_agent_pack


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_importable_market_research_pack(pack_root: Path) -> None:
    write(
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / ".claude-plugin"
        / "plugin.json",
        json.dumps(
            {
                "name": "market-researcher",
                "version": "0.1.1",
                "description": "Market research workflow",
                "author": {"name": "Example"},
            }
        ),
    )
    write(
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "agents"
        / "market-researcher.md",
        """---
name: market-researcher
description: Produces sector market research
tools: Read, Write, mcp__capiq__*
---

Use sector-overview and competitive-analysis to produce a short report.
""",
    )
    write(
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "skills"
        / "sector-overview"
        / "SKILL.md",
        """---
name: sector-overview
description: Build a sector overview
---

# Sector Overview
""",
    )
    write(
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "skills"
        / "competitive-analysis"
        / "SKILL.md",
        """---
name: competitive-analysis
description: Compare competitors
---

# Competitive Analysis
""",
    )
    write(
        pack_root / "plugins" / "agent-plugins" / "market-researcher" / ".mcp.json",
        json.dumps({"mcpServers": {"capiq": {"url": "https://example.invalid/mcp"}}}),
    )


def test_scan_agent_pack_discovers_claude_plugin_shapes(tmp_path: Path) -> None:
    write(
        tmp_path / ".claude-plugin" / "marketplace.json",
        json.dumps(
            {
                "name": "example-market",
                "plugins": [
                    {
                        "name": "pitch-agent",
                        "source": "./plugins/agent-plugins/pitch-agent",
                    }
                ],
            }
        ),
    )
    write(
        tmp_path / "plugins" / "agent-plugins" / "pitch-agent" / ".claude-plugin" / "plugin.json",
        json.dumps(
            {
                "name": "pitch-agent",
                "version": "0.1.0",
                "description": "Builds a pitch deck",
                "author": {"name": "Example"},
            }
        ),
    )
    write(
        tmp_path / "plugins" / "agent-plugins" / "pitch-agent" / "agents" / "pitch-agent.md",
        """---
name: pitch-agent
description: End-to-end pitch agent
tools: Read, Write, mcp__capiq__*
---

You are a pitch agent.
""",
    )
    write(
        tmp_path
        / "plugins"
        / "agent-plugins"
        / "pitch-agent"
        / "skills"
        / "dcf-model"
        / "SKILL.md",
        """---
name: dcf-model
description: Build DCF models
---

# DCF Model
""",
    )
    write(
        tmp_path / "plugins" / "agent-plugins" / "pitch-agent" / "commands" / "dcf.md",
        """---
description: Run a DCF
argument-hint: "[ticker]"
---

Load the dcf skill.
""",
    )
    write(
        tmp_path / "plugins" / "agent-plugins" / "pitch-agent" / ".mcp.json",
        json.dumps(
            {"mcpServers": {"capiq": {"type": "http", "url": "https://example.invalid/mcp"}}}
        ),
    )
    write(
        tmp_path / "managed-agent-cookbooks" / "pitch-agent" / "agent.yaml",
        """
name: pitch-agent
model: claude-opus
tools:
  - type: agent_toolset
    configs:
      - { name: write, enabled: true }
mcp_servers:
  - { type: url, name: capiq, url: "${CAPIQ_MCP_URL}" }
callable_agents:
  - { manifest: ./subagents/researcher.yaml }
""",
    )
    write(
        tmp_path / "managed-agent-cookbooks" / "pitch-agent" / "subagents" / "researcher.yaml",
        """
name: researcher
description: Pulls research data
tools:
  - type: agent_toolset
""",
    )

    preview = scan_agent_pack(tmp_path)

    assert preview.marketplace and preview.marketplace["name"] == "example-market"
    assert [plugin.name for plugin in preview.plugins] == ["pitch-agent"]
    assert [agent.name for agent in preview.agents] == ["pitch-agent"]
    assert preview.agents[0].metadata["tools"] == ["Read", "Write", "mcp__capiq__*"]
    assert [skill.name for skill in preview.skills] == ["dcf-model"]
    assert [command.name for command in preview.commands] == ["dcf"]
    assert [server.name for server in preview.mcp_servers] == ["capiq"]
    assert [agent.name for agent in preview.managed_agents] == ["pitch-agent"]
    assert [subagent.name for subagent in preview.subagents] == ["researcher"]
    assert any("MCP server" in warning for warning in preview.warnings)
    assert any("write-capable" in warning for warning in preview.warnings)


def test_scan_agent_pack_discovers_codex_plugin_shapes(tmp_path: Path) -> None:
    write(
        tmp_path / ".codex-plugin" / "marketplace.json",
        json.dumps(
            {
                "name": "codex-market",
                "plugins": [{"name": "browser-research", "source": "."}],
            }
        ),
    )
    write(
        tmp_path / ".codex-plugin" / "plugin.json",
        json.dumps(
            {
                "name": "browser-research",
                "version": "0.2.0",
                "description": "Browser research helpers",
                "author": "Example",
            }
        ),
    )
    write(
        tmp_path / "skills" / "research-brief" / "SKILL.md",
        """---
name: research-brief
description: Create a sourced research brief
---

# Research Brief
""",
    )
    write(
        tmp_path / ".mcp.json",
        json.dumps({"mcpServers": {"browser": {"command": "npx", "args": ["browser-mcp"]}}}),
    )
    write(
        tmp_path / ".app.json",
        json.dumps(
            {
                "id": "research-console",
                "name": "Research Console",
                "description": "Review sourced briefs and saved pages",
                "route": "/apps/research-console",
                "actions": {
                    "open_brief": {
                        "description": "Open a saved research brief",
                        "input_schema": {
                            "type": "object",
                            "properties": {"brief_id": {"type": "string"}},
                            "required": ["brief_id"],
                        },
                    },
                    "refresh_sources": {"description": "Refresh source metadata"},
                },
            }
        ),
    )

    preview = scan_agent_pack(tmp_path)

    assert preview.marketplace and preview.marketplace["_format"] == "codex"
    assert [plugin.name for plugin in preview.plugins] == ["browser-research"]
    assert preview.plugins[0].metadata["format"] == "codex"
    assert "app" in preview.plugins[0].metadata["layout"]
    assert [app.name for app in preview.apps] == ["research-console"]
    assert preview.apps[0].metadata["title"] == "Research Console"
    assert preview.apps[0].metadata["route"] == "/apps/research-console"
    assert preview.apps[0].metadata["action_count"] == 2
    assert preview.apps[0].metadata["actions"][0]["name"] == "open_brief"
    assert preview.apps[0].metadata["actions"][0]["input_schema"]["required"] == ["brief_id"]
    assert [skill.name for skill in preview.skills] == ["research-brief"]
    assert preview.skills[0].metadata["asset_count"] == 0
    assert [server.name for server in preview.mcp_servers] == ["browser"]
    assert any("MCP server" in warning for warning in preview.warnings)


def test_scan_agent_pack_discovers_octopus_app_jsonc(tmp_path: Path) -> None:
    write(
        tmp_path / ".codex-plugin" / "plugin.json",
        json.dumps(
            {
                "name": "workspace-apps",
                "version": "0.1.0",
                "description": "Workspace applications",
                "author": "Example",
            }
        ),
    )
    write(
        tmp_path / "octopus-app.jsonc",
        """
{
  // Octopus application manifest v1.
  "schema_version": "1",
  "apps": {
    "research-console": {
      "title": "Research Console",
      "description": "Review sourced briefs",
      "category": "research",
      "route": "/workspace/apps/research-console",
      "entry": "./apps/research-console/index.html",
      "permissions": ["workspace.read"],
      "actions": [
        {
          "name": "open_brief",
          "description": "Open a saved research brief",
          "input_schema": {
            "type": "object",
            "properties": { "brief_id": { "type": "string" } },
            "required": ["brief_id"],
          },
          "requires_confirmation": true,
        },
      ],
    },
  },
}
""",
    )

    preview = scan_agent_pack(tmp_path)

    assert [app.name for app in preview.apps] == ["research-console"]
    assert preview.apps[0].metadata["schema_version"] == "1"
    assert preview.apps[0].metadata["title"] == "Research Console"
    assert preview.apps[0].metadata["category"] == "research"
    assert preview.apps[0].metadata["permissions"] == ["workspace.read"]
    assert preview.apps[0].metadata["actions"][0]["requires_confirmation"] is True


def test_import_agent_from_pack_creates_local_agent_without_enabling_mcp(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    agents_root = tmp_path / "agents"
    skills_root = tmp_path / "skills" / "public"
    write_importable_market_research_pack(pack_root)

    result = import_agent_from_pack(pack_root, "market-researcher", agents_root, skills_root)

    agent_root = agents_root / "market_researcher"
    registry = json.loads(
        (agent_root / "agent-core" / "tool-registry.jsonc").read_text(encoding="utf-8")
    )
    profile = json.loads((agent_root / "profile.jsonc").read_text(encoding="utf-8"))
    assert result.agent_id == "market_researcher"
    assert result.copied_skills == ["competitive-analysis", "sector-overview"]
    assert profile["source_kind"] == "agent-pack-import"
    assert profile["managed_by"] == "agent-pack"
    assert "mcp__capiq__*" in registry["disabled_source_tools"]
    assert registry["arms"] == ["web_read", "fs_writer"]
    assert registry["private_skills"] == ["competitive-analysis", "sector-overview"]
    assert (skills_root / "sector-overview" / "SKILL.md").is_file()
    assert (agent_root / "profile.jsonc").is_file()


def test_import_agent_from_pack_rejects_unsafe_skill_name_and_cleans_up(
    tmp_path: Path,
) -> None:
    pack_root = tmp_path / "pack"
    agents_root = tmp_path / "agents"
    skills_root = tmp_path / "skills" / "public"
    write_importable_market_research_pack(pack_root)
    skill_file = (
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "skills"
        / "sector-overview"
        / "SKILL.md"
    )
    skill_file.write_text(
        """---
name: ../escape
description: Unsafe skill name
---

# Unsafe
""",
        encoding="utf-8",
    )
    agent_file = (
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "agents"
        / "market-researcher.md"
    )
    agent_file.write_text(
        """---
name: market-researcher
description: Produces sector market research
tools: Read, Write
---

Use ../escape to produce a short report.
""",
        encoding="utf-8",
    )

    try:
        import_agent_from_pack(pack_root, "market-researcher", agents_root, skills_root)
    except ValueError as exc:
        assert "invalid skill name" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("unsafe skill name should be rejected")

    assert not (agents_root / "market_researcher").exists()
    assert not (tmp_path / "skills" / "escape").exists()


def test_import_agent_from_pack_rejects_existing_agent_symlink(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    agents_root = tmp_path / "agents"
    skills_root = tmp_path / "skills" / "public"
    write_importable_market_research_pack(pack_root)
    agents_root.mkdir()
    outside = tmp_path / "outside-agent"
    outside.mkdir()
    (agents_root / "market_researcher").symlink_to(outside, target_is_directory=True)

    try:
        import_agent_from_pack(pack_root, "market-researcher", agents_root, skills_root)
    except FileExistsError as exc:
        assert "not a real directory" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("existing symlink should be rejected")

    assert outside.exists()
    assert not (skills_root / "sector-overview").exists()


def test_import_agent_from_pack_rejects_symlinked_agent_markdown(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    agents_root = tmp_path / "agents"
    skills_root = tmp_path / "skills" / "public"
    write_importable_market_research_pack(pack_root)
    outside_agent = tmp_path / "outside-agent.md"
    outside_agent.write_text(
        """---
name: market-researcher
description: Outside agent
---

Outside.
""",
        encoding="utf-8",
    )
    agent_file = (
        pack_root
        / "plugins"
        / "agent-plugins"
        / "market-researcher"
        / "agents"
        / "market-researcher.md"
    )
    agent_file.unlink()
    agent_file.symlink_to(outside_agent)

    try:
        import_agent_from_pack(pack_root, "market-researcher", agents_root, skills_root)
    except ValueError as exc:
        assert "must not be a symlink" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("symlinked agent markdown should be rejected")

    assert not (agents_root / "market_researcher").exists()
    assert not (skills_root / "sector-overview").exists()


def test_import_agent_from_pack_rejects_symlinked_skill_asset(tmp_path: Path) -> None:
    pack_root = tmp_path / "pack"
    agents_root = tmp_path / "agents"
    skills_root = tmp_path / "skills" / "public"
    write_importable_market_research_pack(pack_root)
    skill_dir = (
        pack_root / "plugins" / "agent-plugins" / "market-researcher" / "skills" / "sector-overview"
    )
    (skill_dir / "reference.md").symlink_to(tmp_path / "outside-reference.md")

    try:
        import_agent_from_pack(pack_root, "market-researcher", agents_root, skills_root)
    except ValueError as exc:
        assert "must not contain symlinks" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("symlinked skill asset should be rejected")

    assert not (agents_root / "market_researcher").exists()
    assert not (skills_root / "sector-overview").exists()
