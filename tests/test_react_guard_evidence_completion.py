"""Completion guards for evidence-backed project inspection answers."""

from __future__ import annotations

from runtime.core.cerebrum.react_guards import (
    _code_mode_inspection_answer_fragment_guard,
    _code_mode_missing_inspection_tool_guard,
    _explicit_source_paths,
    _incomplete_final_answer_guard,
)
from runtime.core.cerebrum.react_loop import _final_answer_needs_pre_emit_guard
from runtime.core.cerebrum.react_types import ReActStep


def test_explicit_source_paths_preserve_named_project_files() -> None:
    goal = (
        "比较 runtime/protocol/items.py 与 "
        "frontend/src/core/realtime/items.ts:42，并核对 README.md"
    )

    assert _explicit_source_paths(goal) == [
        "runtime/protocol/items.py",
        "frontend/src/core/realtime/items.ts",
        "readme.md",
    ]


def test_named_file_guard_reports_every_uncovered_file() -> None:
    message = _code_mode_missing_inspection_tool_guard(
        [],
        "两个定义一致。",
        goal=(
            "比较 runtime/protocol/items.py 与 "
            "frontend/src/core/realtime/items.ts"
        ),
        file_tools_visible=True,
        grounded_source_paths=frozenset({"runtime/protocol/items.py:100"}),
    )

    assert message is not None
    assert "frontend/src/core/realtime/items.ts" in message
    assert "runtime/protocol/items.py" not in message


def test_named_file_guard_accepts_exact_source_grounding() -> None:
    assert (
        _code_mode_missing_inspection_tool_guard(
            [],
            "两个定义一致。",
            goal=(
                "比较 runtime/protocol/items.py 与 "
                "frontend/src/core/realtime/items.ts"
            ),
            file_tools_visible=True,
            grounded_source_paths=frozenset(
                {
                    "runtime/protocol/items.py:108:1",
                    "frontend/src/core/realtime/items.ts:44",
                }
            ),
        )
        is None
    )


def test_named_file_guard_accepts_successful_reads_for_each_file() -> None:
    steps = [
        ReActStep(
            iteration=1,
            action='read_file({"path":"runtime/protocol/items.py"})',
            observation="class AgentMessageItem",
        ),
        ReActStep(
            iteration=2,
            action='read_file({"path":"frontend/src/core/realtime/items.ts"})',
            observation="export interface AgentMessageItem",
        ),
    ]

    assert (
        _code_mode_missing_inspection_tool_guard(
            steps,
            "两个定义一致。",
            goal=(
                "比较 runtime/protocol/items.py 与 "
                "frontend/src/core/realtime/items.ts"
            ),
            file_tools_visible=True,
        )
        is None
    )


def test_incomplete_final_answer_rejects_future_action_not_result() -> None:
    message = _incomplete_final_answer_guard(
        "我先 grep 确认这三个字段在两端的具体定义。"
    )

    assert message is not None
    assert "not a completed answer" in message


def test_incomplete_final_answer_rejects_negated_conclusion_signal() -> None:
    message = _incomplete_final_answer_guard(
        "我先 grep 确认具体定义，然后整理差异；现在还没有给出结论。"
    )

    assert message is not None
    assert "not a completed answer" in message


def test_incomplete_final_answer_rejects_failed_read_and_future_retry() -> None:
    message = _incomplete_final_answer_guard(
        "两次 `read_file` 都因为路径不对而失败。我先把项目目录探清楚再读。"
    )

    assert message is not None
    assert "not a completed answer" in message


def test_incomplete_final_answer_accepts_concrete_conclusion() -> None:
    assert (
        _incomplete_final_answer_guard(
            "结论：两端都定义 phaseId、parentItemId 和 progressSequence，字段命名一致。"
        )
        is None
    )


def test_incomplete_final_answer_accepts_short_concrete_reply() -> None:
    assert _incomplete_final_answer_guard("已思考") is None


def test_inspection_answer_fragment_guard_rejects_bare_source_line() -> None:
    message = _code_mode_inspection_answer_fragment_guard(
        'str = ""',
        goal="只读核对 runtime/core/cerebrum/react_loop.py，说明 public_update 如何进入公开时间线",
        file_tools_visible=True,
    )

    assert message is not None
    assert "bare source-code fragment" in message


def test_inspection_answer_fragment_guard_accepts_concrete_conclusion() -> None:
    assert (
        _code_mode_inspection_answer_fragment_guard(
            "结论：两个 realtime 标志会让每轮 public_update 进入公开时间线。",
            goal=(
                "只读核对 runtime/core/cerebrum/react_loop.py，"
                "说明 public_update 如何进入公开时间线"
            ),
            file_tools_visible=True,
        )
        is None
    )


def test_inspection_answer_fragment_guard_is_scoped_to_project_inspection() -> None:
    assert (
        _code_mode_inspection_answer_fragment_guard(
            'str = ""',
            goal="解释 Python 类型注解语法",
            file_tools_visible=True,
        )
        is None
    )


def test_pre_emit_buffers_preparatory_chat_but_not_conclusion() -> None:
    assert _final_answer_needs_pre_emit_guard(
        "我先搜索官方资料，当前还没有给出结论。",
        is_code_mode=False,
    )
    assert not _final_answer_needs_pre_emit_guard(
        "结论：两个实现都保留了因果顺序，但本项目还额外暴露了阶段标识。",
        is_code_mode=False,
    )
