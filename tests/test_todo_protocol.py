from runtime.core.cerebrum.todo_protocol import (
    context_mode,
    render_todo_protocol_guidance,
    should_require_todo_protocol,
)


def test_todo_protocol_skips_short_acknowledgements() -> None:
    assert not should_require_todo_protocol("ok", {"metadata": {"mode": "code"}})
    assert not should_require_todo_protocol("\u55ef", {"metadata": {"mode": "team"}})
    assert not should_require_todo_protocol(
        "\u5927\u5bb6\u597d",
        {"metadata": {"mode": "team"}},
    )
    assert not should_require_todo_protocol(
        "hello everyone",
        {"metadata": {"mode": "team"}},
    )


def test_todo_protocol_requires_execution_modes() -> None:
    assert should_require_todo_protocol(
        "fix the frontend and run tests",
        {"metadata": {"mode": "code"}},
    )
    assert should_require_todo_protocol(
        "\u6574\u7406\u4e00\u4e2a\u65b9\u6848",
        {"mode": "team"},
    )


def test_todo_protocol_skips_narrow_web_lookup_in_code_mode() -> None:
    assert not should_require_todo_protocol(
        "\u53ea\u505a\u7f51\u9875\u8c03\u7814\uff1a\u641c\u7d22\u4e00\u4e2a\u5b98\u65b9\u6765\u6e90\uff0c\u7136\u540e\u7ed9\u51fa\u4e00\u53e5\u7ed3\u8bba\u548c\u6765\u6e90\u3002"
        "\u4e0d\u8981\u8bfb\u53d6\u3001\u67e5\u770b\u3001\u4fee\u6539\u6216\u521b\u5efa\u4efb\u4f55\u672c\u5730\u6587\u4ef6\u3002",
        {"mode": "code", "capability_mode": "code"},
    )


def test_todo_protocol_keeps_execution_after_narrow_lookup() -> None:
    assert should_require_todo_protocol(
        "Search one official source, give a concise conclusion, then update the code.",
        {"mode": "code"},
    )


def test_todo_protocol_skips_narrow_named_file_inspection_in_code_mode() -> None:
    assert not should_require_todo_protocol(
        "只读比较 runtime/protocol/items.py 与 frontend/src/core/realtime/items.ts "
        "中 phaseId、parentItemId、progressSequence 三个字段，用一句话回答。不要修改文件。",
        {"mode": "code", "capability_mode": "code"},
    )


def test_todo_protocol_skips_bounded_basename_inspection_in_code_mode() -> None:
    assert not should_require_todo_protocol(
        "只读读取 package.json，只用一句话告诉我项目名称；不要修改文件。",
        {"mode": "code", "capability_mode": "code"},
    )


def test_todo_protocol_skips_narrow_read_only_shell_command_in_code_mode() -> None:
    assert not should_require_todo_protocol(
        "只读权限语义验收：必须使用 exec_shell 在当前项目执行 pwd，"
        "不修改任何文件；命令结束后只回答输出目录。",
        {"mode": "code", "capability_mode": "code"},
    )
    assert not should_require_todo_protocol(
        "Use exec_shell to run pwd read-only and only report its output.",
        {"mode": "code"},
    )
    assert should_require_todo_protocol(
        "Use exec_shell to inspect the project, then update the code.",
        {"mode": "code"},
    )


def test_todo_protocol_keeps_broad_or_mutating_file_comparison() -> None:
    assert should_require_todo_protocol(
        "比较 runtime/protocol/items.py 与 frontend/src/core/realtime/items.ts，"
        "然后修改前端并运行测试。",
        {"mode": "code"},
    )
    assert not should_require_todo_protocol(
        "只读比较 runtime/a.py、runtime/b.py、runtime/c.py 和 runtime/d.py，"
        "用一句话回答。不要修改文件。",
        {"mode": "code"},
    )
    assert should_require_todo_protocol(
        "只读审计当前项目的实时消息架构，找出所有相关实现并形成完整报告。不要修改文件。",
        {"mode": "code"},
    )


def test_todo_protocol_keeps_real_long_research() -> None:
    assert should_require_todo_protocol(
        "\u8c03\u7814\u5e76\u6bd4\u8f83\u516b\u4e2a\u53ef\u9760\u6765\u6e90\uff0c\u5f62\u6210\u5b8c\u6574\u884c\u4e1a\u62a5\u544a",
        {"mode": "research"},
    )


def test_todo_protocol_keeps_explicit_goal_contract_for_narrow_lookup() -> None:
    assert should_require_todo_protocol(
        "Search one official source and give a concise conclusion.",
        {"mode": "code", "goal_mode": True},
    )


def test_todo_protocol_detects_complex_freeform_requests() -> None:
    assert should_require_todo_protocol("audit the streaming modules")
    assert should_require_todo_protocol("\u7ee7\u7eed\u4f18\u5316\u6df1\u5ea6\u7814\u7a76")


def test_todo_protocol_requires_goal_mode_even_for_short_tasks() -> None:
    assert should_require_todo_protocol(
        "rename this",
        {"mode": "code", "goal_mode": True},
    )
    assert should_require_todo_protocol(
        "rename this",
        {"metadata": {"completion_policy": "goal"}},
    )


def test_todo_protocol_context_mode_uses_metadata_and_workspace() -> None:
    assert context_mode({"metadata": {"mode": "deep_research"}}) == "deep_research"
    assert context_mode({"metadata": {"workspace_path": "/repo"}}) == "code"


def test_todo_protocol_guidance_marks_required_state() -> None:
    guidance = render_todo_protocol_guidance(required=True, mode="team")

    assert "TASK CHECKLIST PROTOCOL REQUIRED for team mode" in guidance
    assert "todo_write" in guidance
