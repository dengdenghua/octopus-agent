from __future__ import annotations

from pathlib import Path


def test_loads_claude_style_subagent_file(tmp_path: Path):
    from runtime.execution.subagents import load_subagent_file

    path = tmp_path / "code-reviewer.md"
    path.write_text(
        """---
name: code-reviewer
description: Reviews pull requests and flags risky changes.
tools: Read, Grep, Bash
model: sonnet
---

You are a senior code reviewer.
""",
        encoding="utf-8",
    )

    definition = load_subagent_file(path, scope="project")

    assert definition.name == "code-reviewer"
    assert definition.description.startswith("Reviews pull requests")
    assert definition.tools == ("Read", "Grep", "Bash")
    assert definition.model == "sonnet"
    assert "senior code reviewer" in definition.system_prompt


def test_project_subagent_overrides_user_definition(tmp_path: Path):
    from runtime.execution.subagents import load_subagent_registry

    project = tmp_path / "project"
    user_home = tmp_path / "home"
    (project / ".claude" / "agents").mkdir(parents=True)
    (user_home / ".claude" / "agents").mkdir(parents=True)
    (user_home / ".claude" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: user\n---\n\nuser prompt",
        encoding="utf-8",
    )
    (project / ".claude" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: project\n---\n\nproject prompt",
        encoding="utf-8",
    )

    registry = load_subagent_registry(project_root=project, user_home=user_home)

    assert registry.has("reviewer")
    assert registry.get("reviewer").description == "project"
    assert registry.get("reviewer").system_prompt == "project prompt"


def test_call_subagent_uses_markdown_definition(tmp_path: Path):
    from runtime.execution.subagents import (
        call_subagent,
        load_subagent_registry,
        set_subagent_registry,
    )
    from runtime.execution.suckers.ephemeral_agents import set_ephemeral_role_runner

    project = tmp_path / "project"
    (project / ".claude" / "agents").mkdir(parents=True)
    (project / ".claude" / "agents" / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Review code\ntools: Read\nmodel: sonnet\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    registry = load_subagent_registry(project_root=project, user_home=tmp_path / "home")
    captured = {}

    def _runner(call):
        captured["role_id"] = call.role.id
        captured["tools"] = call.context["tool_allowlist"]
        captured["model"] = call.context["model_name"]
        captured["system"] = call.composed_system_prompt
        return f"{call.role.id}: {call.user_prompt}"

    set_subagent_registry(registry)
    set_ephemeral_role_runner(_runner)
    try:
        result = call_subagent("reviewer", "please review")
    finally:
        set_subagent_registry(None)
        set_ephemeral_role_runner(None)

    assert result["success"] is True
    assert result["output"] == "reviewer: please review"
    assert captured["role_id"] == "reviewer"
    assert captured["tools"] == ["Read"]
    assert captured["model"] == "sonnet"
    assert "Review carefully." in captured["system"]
