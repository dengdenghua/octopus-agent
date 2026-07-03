from __future__ import annotations

import json

from runtime.execution.suckers.agent_meta_skills import (
    _todo_write,
    register_agent_meta_skills,
)
from runtime.execution.suckers.registry import Skill, SkillRegistry


def test_todo_write_accepts_model_friendly_aliases() -> None:
    result = _todo_write(
        todos=[
            {"text": "List project files", "status": "completed"},
            {
                "title": "Read roadmap",
                "status": "in_progress",
                "active_form": "Reading roadmap",
            },
            {"task": "Summarize findings", "status": "not_a_status"},
        ]
    )

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
    result = _todo_write(
        tasks=[
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
        ]
    )

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
    result = _todo_write(
        items=[
            {
                "name": "Query call_agent_parallel schema",
                "status": "completed",
            },
        ]
    )

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
    result = _todo_write(
        todos=[
            {"text": "Read project", "status": "in_progress"},
            {"text": "Patch files", "status": "in_progress"},
            {"text": "Run tests", "status": "pending"},
        ]
    )

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


def test_codex_plugin_skill_injection_registers_runtime_actions(tmp_path) -> None:
    plugin_dir = tmp_path / "demo-plugin"
    (plugin_dir / ".codex-plugin").mkdir(parents=True)
    (plugin_dir / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "demo-plugin",
                "version": "0.1.0",
                "interface": {
                    "displayName": "Demo Plugin",
                    "capabilities": [{"name": "demo", "type": "codex"}],
                },
            }
        ),
        encoding="utf-8",
    )
    skill_dir = plugin_dir / "skills" / "hello"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: hello\n"
        "description: Say hello from the plugin.\n"
        "---\n"
        "\n"
        "# Hello\n"
        "\n"
        "Use this plugin instruction.\n",
        encoding="utf-8",
    )

    from runtime.execution.suckers.codex_plugin_skills import (
        load_codex_plugin_skills,
    )

    registry = SkillRegistry()
    register_agent_meta_skills(registry)
    report = load_codex_plugin_skills(
        registry,
        ("demo-plugin",),
        roots=[tmp_path],
    )

    assert report.handled_plugin_ids == ("demo-plugin",)
    assert registry.has("demo-plugin__hello")

    query = registry.get("query_capability").handler(capability_id="demo-plugin")
    assert query["ok"] is True
    assert query["registered_actions"] == ["demo-plugin__hello"]
    assert query["skills"][0]["registered"] is True
    assert query["skills"][0]["registered_as"] == "demo-plugin__hello"

    result = registry.get("use_capability").handler(
        capability_id="demo-plugin",
        action="hello",
    )
    assert result["ok"] is True
    assert result["action"] == "demo-plugin__hello"
    assert result["result"]["plugin"] == "demo-plugin"
    assert result["result"]["plugin_skill"] == "hello"
    assert "Use this plugin instruction." in result["result"]["instructions"]


def test_pinned_plugin_actions_are_prioritized() -> None:
    from runtime.core.cerebrum.capability_router import activate_capabilities, order_skill_names

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="demo-plugin__hello",
            summary="Demo plugin hello.",
            description="Demo plugin hello.",
            affinity=["plugin", "plugin:demo-plugin"],
            trusted_source="plugin://demo-plugin/hello",
            handler=lambda **_: {"ok": True},
        )
    )
    registry.register(
        Skill(
            name="other_tool",
            summary="Other.",
            description="Other.",
            affinity=[],
            trusted_source="skill://public/other",
            handler=lambda **_: {"ok": True},
        )
    )
    register_agent_meta_skills(registry)

    activation = activate_capabilities("@plugin:demo-plugin please", registry=registry)
    ordered = order_skill_names(
        ["other_tool", "demo-plugin__hello", "use_capability", "query_capability"],
        activation=activation,
        registry=registry,
    )

    assert ordered.index("demo-plugin__hello") < ordered.index("other_tool")


def test_use_capability_blocks_risky_inner_action_under_taint() -> None:
    """Red-team #7 (critical): use_capability dispatches to the inner handler
    DIRECTLY, bypassing executor.execute_step and so the injection-taint
    chokepoint. A tainted turn must not be able to launder a risky action
    (exec_shell) through this low-risk-named meta-skill."""
    from runtime.safety.validation.prompt_injection import (
        mark_injection_taint,
        reset_injection_taint,
    )

    ran = {"shell": False}

    def _shell(**_kw):
        ran["shell"] = True
        return {"exit_code": 0}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="exec_shell",  # risk-recognized name; resolved action tail
            summary="run a shell command",
            affinity=["shell", "exec", "dangerous"],
            trusted_source="plugin://dangerpack/exec_shell",
            handler=_shell,
        )
    )
    register_agent_meta_skills(registry)

    reset_injection_taint()
    try:
        mark_injection_taint("high")  # untrusted content tainted the turn
        result = registry.get("use_capability").handler(
            capability_id="dangerpack",
            action="exec_shell",
            args={"command": "echo hi"},
        )
    finally:
        reset_injection_taint()

    assert result["ok"] is False
    assert "injection_taint_block" in result.get("error", "")
    assert ran["shell"] is False, "blocked inner handler must NOT have run"


def test_use_capability_allows_inner_action_on_clean_turn() -> None:
    """Control: with no taint, use_capability dispatches normally."""
    ran = {"shell": False}

    def _shell(**_kw):
        ran["shell"] = True
        return {"exit_code": 0}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="exec_shell",
            summary="run a shell command",
            affinity=["shell", "exec", "dangerous"],
            trusted_source="plugin://dangerpack/exec_shell",
            handler=_shell,
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("use_capability").handler(
        capability_id="dangerpack",
        action="exec_shell",
        args={"command": "x"},
    )
    assert result["ok"] is True
    assert ran["shell"] is True


def test_use_capability_blocks_denied_inner_action() -> None:
    """use_capability bypasses execute_step, so the capability-permission
    denylist must be re-applied at the inner dispatch: disabling the
    ``shell`` capability group must block an inner exec_shell."""
    from runtime.execution.misc.capability_permissions import (
        reset_capability_permissions,
        set_capability_group_enabled,
    )

    ran = {"shell": False}

    def _shell(**_kw):
        ran["shell"] = True
        return {"exit_code": 0}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="exec_shell",
            summary="run a shell command",
            affinity=["shell", "exec", "dangerous"],
            trusted_source="plugin://dangerpack/exec_shell",
            handler=_shell,
        )
    )
    register_agent_meta_skills(registry)

    reset_capability_permissions()
    try:
        set_capability_group_enabled("shell", False)
        result = registry.get("use_capability").handler(
            capability_id="dangerpack",
            action="exec_shell",
            args={"command": "echo hi"},
        )
    finally:
        reset_capability_permissions()

    assert result["ok"] is False
    assert "capability" in result.get("error", "")
    assert ran["shell"] is False, "denied inner handler must NOT have run"


def test_use_capability_blocks_untrusted_inner_action() -> None:
    """use_capability bypasses execute_step, so the immunity / trust gate
    must be re-applied at the inner dispatch: with the runtime TrustEngine
    bound, dispatching to an untrusted inner skill must be rejected."""
    from runtime.execution.tool_engine.skill_gate import use_trust_engine
    from runtime.safety.auth import TrustEngine

    ran = {"evil": False}

    def _evil(**_kw):
        ran["evil"] = True
        return {"ok": True}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="evil_tool",
            summary="untrusted inner tool",
            affinity=["plugin"],
            # non-public source → not matched by default trusted_sources
            trusted_source="plugin://evilpack/exfil",
            handler=_evil,
        )
    )
    register_agent_meta_skills(registry)

    # unknown_policy="reject" → an untrusted source returns verdict "reject",
    # which is the only immunity verdict execute_step (and the shared gate)
    # blocks on.
    engine = TrustEngine(unknown_policy="reject")
    with use_trust_engine(engine):
        result = registry.get("use_capability").handler(
            capability_id="evilpack",
            action="evil_tool",
            args={"x": 1},
        )

    assert result["ok"] is False
    assert "immune_reject" in result.get("error", "")
    assert ran["evil"] is False, "untrusted inner handler must NOT have run"


def test_use_capability_blocks_credential_file_write() -> None:
    """use_capability bypasses execute_step, so the credential-file
    denylist must be re-applied: an inner write to ``.env`` is blocked even
    though the surrounding meta-skill is low-risk."""
    ran = {"wrote": False}

    def _write(**_kw):
        ran["wrote"] = True
        return {"ok": True}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="write_text_file",
            summary="write a file",
            affinity=["file", "write"],
            trusted_source="plugin://fspack/write",
            handler=_write,
        )
    )
    register_agent_meta_skills(registry)

    result = registry.get("use_capability").handler(
        capability_id="fspack",
        action="write_text_file",
        args={"path": ".env", "content": "SECRET=1"},
    )

    assert result["ok"] is False
    assert "file_safety" in result.get("error", "")
    assert ran["wrote"] is False, "credential write handler must NOT have run"
