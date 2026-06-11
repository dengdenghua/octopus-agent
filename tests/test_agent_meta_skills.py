from __future__ import annotations

from runtime.execution.suckers.agent_meta_skills import (
    _todo_write,
    register_agent_meta_skills,
)
from runtime.execution.suckers.registry import Skill, SkillRegistry


def test_todo_write_accepts_model_friendly_aliases() -> None:
    result = _todo_write(todos=[
        {"text": "List project files", "status": "completed"},
        {
            "title": "Read roadmap",
            "status": "in_progress",
            "active_form": "Reading roadmap",
        },
        {"task": "Summarize findings", "status": "not_a_status"},
    ])

    assert result["ok"] is True
    assert result["count"] == 3
    assert result["todos"] == [
        {
            "content": "List project files",
            "status": "completed",
            "activeForm": "List project files",
        },
        {
            "content": "Read roadmap",
            "status": "in_progress",
            "activeForm": "Reading roadmap",
        },
        {
            "content": "Summarize findings",
            "status": "pending",
            "activeForm": "Summarize findings",
        },
    ]


def test_todo_write_accepts_json_string_todos() -> None:
    result = _todo_write(
        todos=(
            '[{"text":"Confirm task","status":"completed"},'
            '{"text":"Check constraints","status":"in_progress",'
            '"activeForm":"Checking constraints"}]'
        )
    )

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["todos"] == [
        {
            "content": "Confirm task",
            "status": "completed",
            "activeForm": "Confirm task",
        },
        {
            "content": "Check constraints",
            "status": "in_progress",
            "activeForm": "Checking constraints",
        },
    ]


def test_todo_write_accepts_tasks_description_alias() -> None:
    result = _todo_write(tasks=[
        {
            "id": "1",
            "description": "Audit frontend streaming",
            "status": "completed",
        },
        {
            "id": "2",
            "description": "Check browser regression",
            "status": "in_progress",
        },
    ])

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["todos"] == [
        {
            "content": "Audit frontend streaming",
            "status": "completed",
            "activeForm": "Audit frontend streaming",
        },
        {
            "content": "Check browser regression",
            "status": "in_progress",
            "activeForm": "Check browser regression",
        },
    ]


def test_todo_write_accepts_name_alias() -> None:
    result = _todo_write(items=[
        {
            "name": "Query call_agent_parallel schema",
            "status": "completed",
        },
    ])

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["todos"] == [
        {
            "content": "Query call_agent_parallel schema",
            "status": "completed",
            "activeForm": "Query call_agent_parallel schema",
        },
    ]


def test_todo_write_allows_only_one_in_progress_item() -> None:
    result = _todo_write(todos=[
        {"text": "Read project", "status": "in_progress"},
        {"text": "Patch files", "status": "in_progress"},
        {"text": "Run tests", "status": "pending"},
    ])

    assert result["ok"] is True
    assert [item["status"] for item in result["todos"]] == [
        "in_progress",
        "pending",
        "pending",
    ]
    assert result["normalized"] is True
    assert "Only one todo can be in_progress" in result["warnings"][0]


def test_query_skill_returns_full_registered_skill_details() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="sample_tool",
            summary="Short sample summary.",
            description="Full sample description with argument details.",
            affinity=["demo", "read"],
            cost_profile="mid",
            trusted_source="skill://public/sample_tool",
            handler=lambda **kw: kw,
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("query_skill").handler(name="sample_tool")

    assert result["ok"] is True
    assert result["name"] == "sample_tool"
    assert result["summary"] == "Short sample summary."
    assert result["description"] == "Full sample description with argument details."
    assert result["affinity"] == ["demo", "read"]
    assert result["cost_profile"] == "mid"
    assert result["enabled"] is True


def test_query_skill_missing_returns_error_payload() -> None:
    registry = SkillRegistry()
    register_agent_meta_skills(registry)

    result = registry.get("query_skill").handler(name="missing_tool")

    assert result["ok"] is False
    assert result["error"] == "skill not found: missing_tool"


def test_search_skills_finds_registered_skill_by_description() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="hidden_parallel_tool",
            summary="Delegate independent work.",
            description="Spawn multiple subagents for independent research lanes.",
            affinity=["delegation", "subagent", "parallel"],
            trusted_source="skill://public/hidden_parallel_tool",
            handler=lambda **kw: kw,
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("search_skills").handler(
        query="subagent parallel",
        limit=5,
    )

    assert result["ok"] is True
    assert result["count"] >= 1
    assert result["results"][0]["name"] == "hidden_parallel_tool"


def test_search_capabilities_finds_runtime_plugin_package() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="demo_plugin.list_items",
            summary="List demo plugin items.",
            description="List items from the demo plugin.",
            affinity=["demo", "plugin"],
            trusted_source="plugin://demo-plugin/list_items",
            handler=lambda **kw: {"ok": True, "items": [kw.get("kind", "default")]},
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("search_capabilities").handler(query="demo plugin")

    assert result["ok"] is True
    assert result["count"] >= 1
    assert result["results"][0]["id"] == "demo-plugin"
    assert result["results"][0]["registered_actions"] == ["demo_plugin.list_items"]


def test_query_capability_returns_package_level_view() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="demo_plugin.list_items",
            summary="List demo plugin items.",
            affinity=["demo", "plugin"],
            trusted_source="plugin://demo-plugin/list_items",
            handler=lambda **kw: {"ok": True},
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("query_capability").handler(capability_id="demo-plugin")

    assert result["ok"] is True
    assert result["id"] == "demo-plugin"
    assert result["kind"] == "plugin"
    assert result["skills"][0]["name"] == "demo_plugin.list_items"


def test_use_capability_runs_registered_child_action() -> None:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="demo_plugin.list_items",
            summary="List demo plugin items.",
            affinity=["demo", "plugin"],
            trusted_source="plugin://demo-plugin/list_items",
            handler=lambda **kw: {"ok": True, "kind": kw.get("kind")},
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("use_capability").handler(
        capability_id="demo-plugin",
        action="list_items",
        args={"kind": "task"},
    )

    assert result["ok"] is True
    assert result["capability_id"] == "demo-plugin"
    assert result["action"] == "demo_plugin.list_items"
    assert result["result"] == {"ok": True, "kind": "task"}
