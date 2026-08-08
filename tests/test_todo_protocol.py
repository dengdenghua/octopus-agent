from runtime.core.cerebrum.react_guards import _todo_protocol_completion_guard
from runtime.core.cerebrum.react_parsing import _latest_todo_items
from runtime.core.cerebrum.react_types import ReActStep
from runtime.core.cerebrum.todo_protocol import (
    context_mode,
    render_todo_protocol_guidance,
    should_require_todo_protocol,
)


def test_todo_protocol_skips_short_acknowledgements() -> None:
    assert not should_require_todo_protocol("ok", {"metadata": {"mode": "code"}})
    assert not should_require_todo_protocol("嗯", {"metadata": {"mode": "team"}})
    assert not should_require_todo_protocol(
        "大家好",
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
        "整理一个方案",
        {"mode": "team"},
    )


def test_todo_protocol_skips_narrow_web_lookup_in_code_mode() -> None:
    assert not should_require_todo_protocol(
        "只做网页调研：搜索一个官方来源，然后给出一句结论和来源。"
        "不要读取、查看、修改或创建任何本地文件。",
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


def test_todo_protocol_respects_explicit_no_checklist_instruction() -> None:
    assert not should_require_todo_protocol(
        "严格回归测试：请立刻调用 exec_shell，command 参数必须为"
        "「printf approval-ui-fixed」。不要调用 todo_write、不要解释，"
        "调用后直接返回命令结果。",
        {"mode": "code", "capability_mode": "code"},
    )
    assert not should_require_todo_protocol(
        "运行一次 pwd，不要创建任务清单，直接返回结果。",
        {"mode": "code"},
    )
    assert not should_require_todo_protocol(
        "Run pwd once without a task checklist and return the result.",
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
        "调研并比较八个可靠来源，形成完整行业报告",
        {"mode": "research"},
    )


def test_todo_protocol_keeps_explicit_goal_contract_for_narrow_lookup() -> None:
    assert should_require_todo_protocol(
        "Search one official source and give a concise conclusion.",
        {"mode": "code", "goal_mode": True},
    )


def test_todo_protocol_detects_complex_freeform_requests() -> None:
    assert should_require_todo_protocol("audit the streaming modules")
    assert should_require_todo_protocol("继续优化深度研究")


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


def test_todo_protocol_detects_short_chinese_execution_requests() -> None:
    assert should_require_todo_protocol("把登录页改成暗色主题")
    assert should_require_todo_protocol("给项目接入微信支付")
    assert should_require_todo_protocol("把这个服务部署到预发环境")


def test_todo_protocol_cjk_density_lowers_length_threshold() -> None:
    assert should_require_todo_protocol(
        "帮我把这个仓库里面所有文档的目录结构重新整理一遍然后输出一份说明"
    )
    assert not should_require_todo_protocol("这个函数是做什么的")


# ══════════════════════════════════════════════════════════════════
# Change ① — trigger-layer exemption for short read-only analysis
# follow-ups ("不足点呢", "解释一下这段代码").  These must not be
# forced into checklist ceremony.  Broad audits, long reports, and
# short work directives are NOT exempted.
# ══════════════════════════════════════════════════════════════════


def test_todo_protocol_exempts_short_read_only_analysis_followup() -> None:
    # The user's primary pain point: a short read-only follow-up question
    # in code mode that previously triggered a forced checklist.
    assert not should_require_todo_protocol("不足点呢", {"mode": "code"})
    assert not should_require_todo_protocol("解释一下这段代码", {"mode": "code"})
    assert not should_require_todo_protocol("还有什么问题", {"mode": "code"})
    assert not should_require_todo_protocol("看看这段逻辑的风险", {"mode": "code"})


def test_todo_protocol_exempts_short_english_analysis_followup() -> None:
    assert not should_require_todo_protocol("explain this function", {"mode": "code"})
    assert not should_require_todo_protocol("summarize the approach", {"mode": "code"})


def test_todo_protocol_keeps_required_for_goal_mode_read_only_followup() -> None:
    # goal_mode short-circuits before the read-only exemption, so the
    # trigger layer still forces a checklist.  This is the entry point
    # for the change ② guard-layer safety net.
    assert should_require_todo_protocol("不足点呢", {"mode": "code", "goal_mode": True})


def test_todo_protocol_keeps_short_work_directive_required() -> None:
    # Short directives without an analysis cue stay required: "继续优化
    # 深度研究" has no _ANALYSIS_ONLY_RE hit, so it is not mistaken for
    # a read-only inquiry.
    assert should_require_todo_protocol("继续优化深度研究")
    assert should_require_todo_protocol("把登录页改成暗色主题", {"mode": "code"})


def test_todo_protocol_keeps_broad_read_only_audit_required() -> None:
    # Long read-only audits are multi-step and still need a checklist —
    # the exemption targets short follow-ups, not comprehensive reports.
    assert should_require_todo_protocol(
        "只读审计当前项目的实时消息架构，找出所有相关实现并形成完整报告。不要修改文件。",
        {"mode": "code"},
    )


def test_todo_protocol_keeps_analysis_with_write_intent_required() -> None:
    # An analysis cue with explicit write intent is not read-only.
    assert should_require_todo_protocol("分析一下架构然后修改代码", {"mode": "code"})


# ══════════════════════════════════════════════════════════════════
# Change ② — guard-layer safety net.  _todo_protocol_completion_guard
# downgrades from hard reject to silent pass for short read-only
# analysis follow-ups with no executed write tool.  Research, team
# coordination, implementation, and write-bearing turns stay hard.
# ══════════════════════════════════════════════════════════════════


def _gstep(
    iteration: int,
    *,
    action: str = "",
    observation: str = "",
    action_results: list[dict] | None = None,
) -> ReActStep:
    return ReActStep(
        iteration=iteration,
        action=action,
        actions=[action] if action else [],
        observation=observation,
        action_results=action_results or [],
    )


_TODO_DONE = 'todo_write({"todos": [{"title": "done", "status": "completed"}]})'
_TODO_OPEN = 'todo_write({"todos": [{"title": "work", "status": "pending"}]})'
_EDIT_OK = 'edit_file({"path": "foo.py", "old": "a", "new": "b"})'


def test_guard_downgrades_read_only_followup_without_todos() -> None:
    # "不足点呢" with no checklist and no writes: safety net fires.
    assert _todo_protocol_completion_guard([], "this is the analysis.", goal="不足点呢") is None


def test_guard_downgrades_read_only_followup_with_stale_todos() -> None:
    # Incomplete todos would normally reject; for a read-only follow-up
    # the guard downgrades to silent pass.
    steps = [_gstep(1, action=_TODO_OPEN)]
    assert (
        _todo_protocol_completion_guard(steps, "analysis answer.", goal="解释一下这段代码") is None
    )


def test_guard_still_rejects_implementation_goal_without_todos() -> None:
    # Mutation intent ("修改") is not read-only → guard stays hard.
    msg = _todo_protocol_completion_guard([], "done.", goal="修改这个函数的实现")
    assert msg is not None
    assert "todo_write checklist" in msg


def test_guard_still_rejects_team_coordination_goal_without_todos() -> None:
    # "coordinate a team implementation plan" — noun "implementation" is
    # not an analysis cue, so the safety net does not fire.
    msg = _todo_protocol_completion_guard(
        [], "plan ready.", goal="coordinate a team implementation plan"
    )
    assert msg is not None


def test_guard_still_rejects_research_goal_without_todos() -> None:
    # Long research goal is not a short follow-up → guard stays hard.
    msg = _todo_protocol_completion_guard(
        [], "结论。", goal="调研 Octopus agent 的流式架构并给出有来源的结论"
    )
    assert msg is not None


def test_guard_rejects_read_only_goal_when_write_tool_ran() -> None:
    # A read-only goal that nonetheless executed a write tool is not
    # exempted: the "no write executed" half of the condition fails,
    # so the stale-checklist contract still applies.
    steps = [_gstep(1, action=_EDIT_OK, action_results=[{"ok": True}])]
    msg = _todo_protocol_completion_guard(steps, "done.", goal="不足点呢")
    assert msg is not None


def test_guard_preserves_help_request_short_circuit() -> None:
    # A help-request final answer still passes through unchanged.
    assert _todo_protocol_completion_guard([], "请确认权限后再继续。", goal="修改这个函数") is None


def test_guard_still_rejects_completed_todos_with_post_todo_toolwork() -> None:
    # For a non-exempt (mutation) goal, completed todos followed by a
    # write tool still trip the stale-checklist guard.  (The edit step
    # needs an observation so _has_tool_work_after_latest_todo sees it
    # as real tool work.)
    steps = [
        _gstep(1, action=_TODO_DONE, action_results=[{"ok": True}]),
        _gstep(
            2,
            action=_EDIT_OK,
            observation="patched",
            action_results=[{"ok": True}],
        ),
    ]
    msg = _todo_protocol_completion_guard(steps, "done.", goal="修改这个函数的实现")
    assert msg is not None
    assert "used tools after the latest todo_write" in msg


# ══════════════════════════════════════════════════════════════════
# Root-cause fix — the todo_write tool accepts THREE input aliases
# (items / todos / tasks).  The guard's parsers previously only
# checked `items` and `todos`, so a model emitting
# ``todo_write({"tasks": [...]})`` (a valid, successfully-executing
# call) was invisible to the completion guard, which then rejected
# with "no todo_write checklist is recorded" and three-striked the
# turn.  This reproduces the exact failure mode of thread
# tJnjK3LevqUdg97iD0KaSJ (2026-07-28).
# ══════════════════════════════════════════════════════════════════

_TODO_DONE_VIA_TASKS = 'todo_write({"tasks": [{"title": "done", "status": "completed"}]})'
_TODO_OPEN_VIA_TASKS = 'todo_write({"tasks": [{"title": "work", "status": "in_progress"}]})'


def test_latest_todo_items_recognizes_tasks_alias() -> None:
    # The model emitted `tasks` (not `items`/`todos`) — the alias the
    # todo_write tool documents and accepts.  The parser must see it.
    steps = [_gstep(1, action=_TODO_DONE_VIA_TASKS)]
    items = _latest_todo_items(steps)
    assert items and items[0]["title"] == "done"


def test_guard_accepts_completed_checklist_via_tasks_alias() -> None:
    # A completed checklist delivered via the `tasks` alias must not
    # trigger the "no checklist recorded" rejection.  This is the
    # exact regression: thread tJnjK3LevqUdg97iD0KaSJ three-struck
    # because the guard could not see the `tasks`-keyed checklist.
    steps = [_gstep(1, action=_TODO_DONE_VIA_TASKS, action_results=[{"ok": True}])]
    # Non-read-only goal so the safety net does NOT fire — the only
    # thing that should let this through is the parser seeing `tasks`.
    assert (
        _todo_protocol_completion_guard(steps, "调研完成。", goal="调研 Octopus agent 的流式架构")
        is None
    )


def test_guard_rejects_open_checklist_via_tasks_alias() -> None:
    # An in_progress checklist delivered via `tasks` must still be
    # caught as incomplete — confirming the alias fix doesn't weaken
    # the incomplete-items check.
    steps = [_gstep(1, action=_TODO_OPEN_VIA_TASKS, action_results=[{"ok": True}])]
    msg = _todo_protocol_completion_guard(steps, "done.", goal="调研 Octopus agent 的流式架构")
    assert msg is not None
    assert "unfinished checklist items remain" in msg
