"""Regression tests for §24 / §28 / §30 — the cheat-detection guards.

These three target the failure shape "model claims success without
actually fixing the underlying problem". They are independent of
§18-§23 (which guard the trajectory shape) — these guard the *content*
of edits and final answers.
"""

from __future__ import annotations

import json

import pytest

from runtime.core.cerebrum.react_guards import (
    _ambiguous_inflight_leader_election_guard,
    _broad_except_suppression_guard,
    _code_mode_missing_write_guard,
    _code_semantic_followup_guard,
    _commented_out_as_fix_guard,
    _concurrency_semantic_followup_guard,
    _destructive_waiter_result_guard,
    _explicit_tool_request_guard,
    _false_verification_claim_guard,
    _loader_barrier_deadlock_guard,
    _path_boundary_decode_guard,
    _stale_immutable_waiter_snapshot_guard,
    _terminal_pending_entry_leak_guard,
    _wait_while_lock_held_guard,
)
from runtime.core.cerebrum.react_parsing import (
    _final_answer_claims_verification,
    _has_language_specific_verification,
    _has_successful_verification_observation,
    _payload_has_ambiguous_inflight_leader_election,
    _payload_has_broad_except_suppression,
    _payload_has_destructive_waiter_result_pop,
    _payload_has_executable_python,
    _payload_has_inflight_identity_comparison,
    _payload_has_loader_barrier_deadlock,
    _payload_has_single_pass_url_decode,
    _payload_has_stale_immutable_waiter_snapshot,
    _payload_has_terminal_pending_entry_leak,
    _payload_has_wait_while_lock_held,
    _step_introduces_broad_except_suppression,
    _step_replaced_code_with_comment,
)
from runtime.core.cerebrum.react_types import ReActStep


def _step(
    iteration: int,
    *,
    thought: str = "",
    action: str = "",
    observation: str = "",
) -> ReActStep:
    return ReActStep(
        iteration=iteration,
        thought=thought,
        action=action,
        observation=observation,
    )


class TestPathBoundaryDecodeGuard:
    BAD = """\
from pathlib import Path
from urllib.parse import unquote

class PathBoundaryError(ValueError):
    pass

def safe_path(root: Path, user_path: str) -> Path:
    decoded = unquote(user_path)
    candidate = (root / decoded).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise PathBoundaryError(user_path) from exc
    return candidate
"""
    GOOD = """\
from pathlib import Path
from urllib.parse import unquote

class PathBoundaryError(ValueError):
    pass

def safe_path(root: Path, user_path: str) -> Path:
    decoded = user_path
    for _round in range(6):
        next_decoded = unquote(decoded)
        if next_decoded == decoded:
            break
        decoded = next_decoded
    else:
        raise PathBoundaryError(user_path)
    candidate = (root / decoded).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise PathBoundaryError(user_path) from exc
    return candidate
"""

    def test_detector_flags_only_single_pass_decode(self) -> None:
        assert _payload_has_single_pass_url_decode(self.BAD)
        assert not _payload_has_single_pass_url_decode(self.GOOD)

    def test_completion_and_midflight_guards_reject_single_pass_decode(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"file_service.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _path_boundary_decode_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        followup = _code_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None and "%252e" in message
        assert followup is not None and followup.startswith("Before verification:")

    def test_surgical_stable_decode_repair_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"file_service.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'edit_file({"path":"file_service.py",'
                    '"old_string":"decoded = unquote(user_path)",'
                    '"new_string":"decoded = user_path\\n    for _round in range(6):\\n'
                    '        next_decoded = unquote(decoded)\\n'
                    '        if next_decoded == decoded:\\n            break\\n'
                    '        decoded = next_decoded\\n    else:\\n'
                    '        raise PathBoundaryError(user_path)"})'
                ),
            ),
        ]

        assert (
            _path_boundary_decode_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


# ══════════════════════════════════════════════════════════════════
# §24 — false-verification claim
# ══════════════════════════════════════════════════════════════════


class TestFinalAnswerClaimsVerification:
    def test_english_phrases(self) -> None:
        assert _final_answer_claims_verification("All tests pass.")
        assert _final_answer_claims_verification("Tests passing now.")
        assert _final_answer_claims_verification("Verified the fix.")
        assert _final_answer_claims_verification("Build succeeded.")

    def test_chinese_phrases(self) -> None:
        assert _final_answer_claims_verification("全部测试通过")
        assert _final_answer_claims_verification("已通过测试")
        assert _final_answer_claims_verification("测试已通过，无错误")

    def test_numeric_pytest_summary(self) -> None:
        assert _final_answer_claims_verification("pytest tests/ -v → 4 passed")

    def test_neutral_summary_no_claim(self) -> None:
        assert not _final_answer_claims_verification("Reformatted the imports.")
        assert not _final_answer_claims_verification("已经完成重构")

    def test_empty_safe(self) -> None:
        assert not _final_answer_claims_verification("")
        assert not _final_answer_claims_verification(None)


class TestHasSuccessfulVerificationObservation:
    def test_clean_pytest_output(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "pytest tests/test_x.py"})',
                observation="===== 5 passed in 1.2s =====",
            ),
        ]
        assert _has_successful_verification_observation(steps)

    def test_module_not_found_excluded(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "pytest"})',
                observation="ModuleNotFoundError: No module named 'foo'",
            ),
        ]
        assert not _has_successful_verification_observation(steps)

    def test_traceback_excluded(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "pytest"})',
                observation="Traceback (most recent call last):\n  File...",
            ),
        ]
        assert not _has_successful_verification_observation(steps)

    def test_command_not_found_excluded(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "mypy ."})',
                observation="bash: mypy: command not found",
            ),
        ]
        assert not _has_successful_verification_observation(steps)

    def test_empty_observation_excluded(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "pytest"})',
                observation="",
            ),
        ]
        assert not _has_successful_verification_observation(steps)

    def test_node_verifier_script_is_green_evidence(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "node verify_all.js"})',
                observation="Static checks: 6/6 passed\nRace tests: 4/4 passed",
            ),
        ]

        assert _has_successful_verification_observation(steps)

    def test_node_inline_harness_requires_real_failure_branch(self) -> None:
        real_harness = [
            _step(
                1,
                action=(
                    "exec_shell({\"command\": \"node -e 'let fail = 0; "
                    "if (!check()) fail++; process.exit(fail > 0 ? 1 : 0);'\"})"
                ),
                observation="4/4 tests passed",
            ),
        ]
        fake_green = [
            _step(
                1,
                action=(
                    "exec_shell({\"command\": \"node -e 'console.log(4); "
                    "process.exit(0);'\"})"
                ),
                observation="4/4 tests passed",
            ),
        ]

        assert _has_successful_verification_observation(real_harness)
        assert not _has_successful_verification_observation(fake_green)

    def test_node_verifier_does_not_satisfy_python_specific_verification(self) -> None:
        steps = [
            _step(
                1,
                action='exec_shell({"command": "node verify_all.js"})',
                observation="6/6 checks passed",
            ),
        ]

        assert _has_language_specific_verification(steps, language="typescript")
        assert not _has_language_specific_verification(steps, language="python")


class TestFalseVerificationClaimGuard:
    def test_non_code_mode_silent(self) -> None:
        steps = [
            _step(1, action='exec_shell({"command": "pytest"})', observation="ModuleNotFoundError")
        ]
        assert (
            _false_verification_claim_guard(
                steps,
                "All tests pass!",
                is_code_mode=False,
            )
            is None
        )

    def test_no_claim_silent(self) -> None:
        steps = [
            _step(1, action='exec_shell({"command": "pytest"})', observation="ModuleNotFoundError")
        ]
        assert (
            _false_verification_claim_guard(
                steps,
                "Refactored the imports.",
                is_code_mode=True,
            )
            is None
        )


class TestCodeModeMissingWriteGuard:
    def test_implementation_without_write_fires(self) -> None:
        steps = [
            _step(
                1,
                action='read_file({"path": "config.py"})',
                observation='{"content":"max_turns = 8"}',
            )
        ]

        msg = _code_mode_missing_write_guard(
            steps,
            "Implemented the requested rename.",
            goal="Implement the configuration rename and update tests.",
        )

        assert msg is not None
        assert "no successful file write" in msg

    def test_failed_write_receipt_does_not_count(self) -> None:
        step = _step(
            1,
            action='edit_file({"path": "config.py"})',
            observation='{"error":"permission denied"}',
        )
        step.action_results = [
            {
                "tool_name": "edit_file",
                "ok": False,
                "observation": "permission denied",
            }
        ]

        assert (
            _code_mode_missing_write_guard(
                [step],
                "Done.",
                goal="Fix config.py.",
            )
            is not None
        )

    def test_successful_write_receipt_allows_completion(self) -> None:
        step = _step(
            1,
            action='edit_file({"path": "config.py"})',
            observation='{"ok":true}',
        )
        step.action_results = [
            {
                "tool_name": "edit_file",
                "ok": True,
                "observation": "updated config.py",
            }
        ]

        assert (
            _code_mode_missing_write_guard(
                [step],
                "Done.",
                goal="Fix config.py.",
            )
            is None
        )

    def test_read_only_review_does_not_require_write(self) -> None:
        assert (
            _code_mode_missing_write_guard(
                [],
                "Review complete.",
                goal="Inspect the repository and report risks.",
            )
            is None
        )

    @pytest.mark.parametrize(
        "goal",
        [
            "分析当前代码架构，不要修改任何文件。",
            "调研市场趋势；无需写入本地文件，最终输出报告。",
            "Inspect the repository but do not modify files.",
            "Analyze the event flow without changing any code.",
            (
                "严格界面测试：请立刻调用 exec_shell，command 参数必须为"
                "「printf approval-ui-test」。不要调用 todo_write、不要解释，"
                "调用后等待系统审批。"
            ),
        ],
    )
    def test_explicit_no_write_request_does_not_trigger_write_guard(
        self, goal: str
    ) -> None:
        assert _code_mode_missing_write_guard([], "Report complete.", goal=goal) is None


class TestExplicitToolRequestGuard:
    GOAL = (
        "严格回归测试：请立刻调用 exec_shell，command 参数必须为"
        "「printf approval-ui-fixed」。不要调用 todo_write、不要解释，"
        "调用后直接返回命令结果。"
    )

    def test_explicit_tool_request_without_receipt_fires(self) -> None:
        msg = _explicit_tool_request_guard([], "准备执行。", goal=self.GOAL)

        assert msg is not None
        assert "exec_shell" in msg
        assert "todo_write" not in msg

    def test_requested_tool_execution_receipt_allows_completion(self) -> None:
        step = _step(
            1,
            action='exec_shell({"command":"printf approval-ui-fixed"})',
            observation="approval-ui-fixed",
        )
        step.action_results = [
            {
                "tool_name": "exec_shell",
                "ok": True,
                "observation": "approval-ui-fixed",
            }
        ]

        assert (
            _explicit_tool_request_guard(
                [step],
                "approval-ui-fixed",
                goal=self.GOAL,
            )
            is None
        )

    def test_negated_tool_request_does_not_create_requirement(self) -> None:
        assert (
            _explicit_tool_request_guard(
                [],
                "Done.",
                goal="不要调用 todo_write，直接回答。",
            )
            is None
        )


class TestFalseVerificationClaimGuardOutcomes:
    def test_claim_with_failed_verifier_fires(self) -> None:
        steps = [
            _step(
                1,
                action='write_text_file({"path":"src/foo.py","content":"x=1"})',
            ),
            _step(
                2,
                action='exec_shell({"command": "pytest"})',
                observation="ModuleNotFoundError: No module named 'foo'",
            ),
        ]
        msg = _false_verification_claim_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        assert msg is not None
        assert "verifier" in msg.lower() or "verification" in msg.lower()

    def test_claim_with_clean_run_silent(self) -> None:
        steps = [
            _step(
                1,
                action='write_text_file({"path":"src/foo.py","content":"x=1"})',
            ),
            _step(
                2, action='exec_shell({"command": "pytest"})', observation="===== 5 passed ====="
            ),
        ]
        assert (
            _false_verification_claim_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )

    def test_help_request_short_circuits(self) -> None:
        steps = [
            _step(
                1,
                action='write_text_file({"path":"src/foo.py","content":"x=1"})',
            ),
            _step(2, action='exec_shell({"command": "pytest"})', observation="ModuleNotFoundError"),
        ]
        assert (
            _false_verification_claim_guard(
                steps,
                "Tests pass — but I cannot continue, please provide the API key.",
                is_code_mode=True,
            )
            is None
        )

    def test_read_only_reporting_documented_fact_is_silent(self) -> None:
        # A research/analysis turn reads the repo and reports "tests pass"
        # as a documented fact (README/CI) without modifying any code. It
        # must NOT be forced to run a verifier — that's the guard impasse
        # that buffered the final answer for hundreds of seconds and then
        # failed the turn.
        steps = [
            _step(1, action='exec_shell({"command": "ls"})', observation="src/ tests/"),
            _step(2, action='read_text_file({"path":"README.md"})', observation="跨语言一致性测试已通过"),
        ]
        assert (
            _false_verification_claim_guard(
                steps,
                "测试已通过，无错误",
                is_code_mode=True,
            )
            is None
        )


# ══════════════════════════════════════════════════════════════════
# §28 — commented-out-as-fix
# ══════════════════════════════════════════════════════════════════


class TestPayloadHasExecutablePython:
    def test_executable_call(self) -> None:
        assert _payload_has_executable_python("foo()\n")

    def test_function_def(self) -> None:
        assert _payload_has_executable_python("def hello():\n    pass\n")


class TestSingleFlightLeaderElectionGuard:
    BAD = """\
with self._lock:
    pending = self._pending.get(key)
    if pending is None:
        pending = Pending()
        self._pending[key] = pending
if self._pending.get(key) is not pending:
    pending.event.wait()
else:
    value = loader()
"""

    GOOD = """\
with self._lock:
    pending = self._pending.get(key)
    is_leader = pending is None
    if pending is None:
        pending = Pending()
        self._pending[key] = pending
if not is_leader:
    pending.event.wait()
else:
    value = loader()
"""

    def test_detector_flags_post_lock_identity_election(self) -> None:
        assert _payload_has_ambiguous_inflight_leader_election(self.BAD)
        assert not _payload_has_ambiguous_inflight_leader_election(self.GOOD)
        assert _payload_has_inflight_identity_comparison(
            "if self._pending.get(key) is not pending:\n    wait()"
        )

    def test_completion_guard_rejects_ambiguous_election(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path":"cache.py","old_string":"old",'
                    f'"new_string":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _ambiguous_inflight_leader_election_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )

        assert message is not None
        assert "explicit leader boolean" in message

    def test_later_replacement_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path":"cache.py","old_string":"old",'
                    f'"new_string":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'edit_file({"path":"cache.py",'
                    f'"old_string":{json.dumps(self.BAD)},'
                    f'"new_string":{json.dumps(self.GOOD)}}})'
                ),
            ),
        ]

        assert (
            _ambiguous_inflight_leader_election_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )

    def test_surgical_identity_replacement_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path":"cache.py","old_string":"old",'
                    f'"new_string":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'edit_file({"path":"cache.py",'
                    '"old_string":"if self._pending.get(key) is not pending:",'
                    '"new_string":"if not is_leader:"})'
                ),
            ),
        ]

        assert (
            _ambiguous_inflight_leader_election_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestPayloadHasExecutablePythonContinued:
    def test_assert(self) -> None:
        assert _payload_has_executable_python("    assert x > 0\n")

    def test_raise(self) -> None:
        assert _payload_has_executable_python("    raise ValueError('x')\n")

    def test_only_comments_false(self) -> None:
        assert not _payload_has_executable_python("# was: foo()\n# bar()\n")

    def test_only_blanks_false(self) -> None:
        assert not _payload_has_executable_python("\n\n   \n")

    def test_empty_false(self) -> None:
        assert not _payload_has_executable_python("")
        assert not _payload_has_executable_python(None)


class TestDestructiveWaiterResultGuard:
    BAD = """\
with self._cv:
    self._cv.wait_for(lambda: self._state.get(key) is None)
    result = self._results.pop(key, None)
    if result is not None:
        return result
"""

    def test_detector_and_completion_guard(self) -> None:
        assert _payload_has_destructive_waiter_result_pop(self.BAD)
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path":"cache.py","old_string":"old",'
                    f'"new_string":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _destructive_waiter_result_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )

        assert message is not None
        assert "first follower consumes" in message

    def test_midflight_guard_surfaces_before_verification(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _concurrency_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None
        assert message.startswith("Before verification:")

    def test_surgical_pop_to_get_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path":"cache.py","old_string":"old",'
                    f'"new_string":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'edit_file({"path":"cache.py",'
                    '"old_string":"self._results.pop(key, None)",'
                    '"new_string":"self._results.get(key)"})'
                ),
            ),
        ]

        assert (
            _destructive_waiter_result_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestStaleImmutableWaiterSnapshotGuard:
    BAD = """\
with self._lock:
    pending = self._pending.get(key)
    if pending is not None:
        event, result, exc = pending
        self._lock.release()
        event.wait()
        self._lock.acquire()
        finished = self._pending.get(key, pending)
        _event, result, exc = finished
        return result
    event = threading.Event()
    self._pending[key] = (event, None, None)
value = loader()
with self._lock:
    self._pending[key] = (event, value, None)
    event.set()
    del self._pending[key]
"""

    GOOD = """\
with self._lock:
    pending = self._pending.get(key)
    is_leader = pending is None
    if is_leader:
        pending = Pending()
        self._pending[key] = pending
if not is_leader:
    pending.event.wait()
    if pending.exception is not None:
        raise pending.exception
    return pending.result
value = loader()
pending.result = value
pending.event.set()
"""
    DIRECT_DELETED_READ = """\
with self._lock:
    if key in self._pending:
        event = self._pending[key][0]
        is_leader = False
    else:
        event = threading.Event()
        self._pending[key] = (event, None, None)
        is_leader = True
if is_leader:
    value = loader()
    with self._lock:
        self._pending[key] = (event, value, None)
        event.set()
        del self._pending[key]
else:
    event.wait()
    with self._lock:
        _, result, exc = self._pending[key]
        return result
"""

    def test_detector_flags_stale_tuple_fallback(self) -> None:
        assert _payload_has_stale_immutable_waiter_snapshot(self.BAD)
        assert _payload_has_stale_immutable_waiter_snapshot(self.DIRECT_DELETED_READ)
        assert not _payload_has_stale_immutable_waiter_snapshot(self.GOOD)

    def test_completion_and_midflight_guards_reject_snapshot(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _stale_immutable_waiter_snapshot_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        followup = _concurrency_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None and "immutable pending tuple" in message
        assert followup is not None and followup.startswith("Before verification:")

    def test_clean_full_rewrite_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.GOOD)}}})'
                ),
            ),
        ]

        assert (
            _stale_immutable_waiter_snapshot_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestTerminalPendingEntryLeakGuard:
    BAD = """\
with self._lock:
    pending = self._pending.get(key)
    if pending is not None:
        event, result, exc = pending
        event.wait()
        return result
    event = threading.Event()
    self._pending[key] = (event, None, None)
try:
    value = loader()
except BaseException as exc:
    with self._lock:
        self._pending[key] = (event, None, exc)
        event.set()
    raise
with self._lock:
    self._pending[key] = (event, value, None)
    event.set()
return value
"""
    GOOD = """\
with self._lock:
    pending = self._pending.get(key)
    is_leader = pending is None
    if is_leader:
        pending = Pending()
        self._pending[key] = pending
if not is_leader:
    pending.event.wait()
    if pending.exception is not None:
        raise pending.exception
    return pending.result
try:
    value = loader()
except BaseException as exc:
    pending.exception = exc
    pending.event.set()
    with self._lock:
        self._pending.pop(key, None)
    raise
pending.result = value
pending.event.set()
with self._lock:
    self._pending.pop(key, None)
return value
"""

    def test_detector_flags_terminal_pending_entry_leak(self) -> None:
        assert _payload_has_terminal_pending_entry_leak(self.BAD)
        assert not _payload_has_terminal_pending_entry_leak(self.GOOD)

    def test_completion_and_midflight_guards_reject_leak(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _terminal_pending_entry_leak_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        followup = _concurrency_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None and "expired TTL value" in message
        assert followup is not None and followup.startswith("Before verification:")

    def test_clean_full_rewrite_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.GOOD)}}})'
                ),
            ),
        ]

        assert (
            _terminal_pending_entry_leak_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestLoaderBarrierDeadlockGuard:
    BAD = """\
def test_single_flight():
    cache = TTLCache(60)
    all_followers_ready = threading.Barrier(5)

    def loader():
        all_followers_ready.wait()
        return 99

    def worker():
        results.append(cache.get_or_load("key", loader))
"""
    GOOD = """\
def test_single_flight():
    cache = TTLCache(60)
    callers_ready = threading.Barrier(5)
    release_loader = threading.Event()

    def loader():
        release_loader.wait(timeout=2)
        return 99

    def worker():
        callers_ready.wait()
        results.append(cache.get_or_load("key", loader))
"""
    BAD_MAIN_PARTICIPANT = """\
def test_single_flight():
    ready = threading.Barrier(5)
    def loader():
        ready.wait()
        return 99
    def worker():
        results.append(cache.get_or_load("key", loader))
    for thread in threads:
        thread.start()
    ready.wait()
"""
    GOOD_TWO_PARTY = """\
def test_loader_rendezvous():
    ready = threading.Barrier(2)
    def loader():
        ready.wait()
        return 99
    thread = threading.Thread(target=lambda: cache.get_or_load("key", loader))
    thread.start()
    ready.wait()
"""

    def test_detector_flags_loader_barrier_deadlock(self) -> None:
        assert _payload_has_loader_barrier_deadlock(self.BAD)
        assert _payload_has_loader_barrier_deadlock(self.BAD_MAIN_PARTICIPANT)
        assert not _payload_has_loader_barrier_deadlock(self.GOOD)
        assert not _payload_has_loader_barrier_deadlock(self.GOOD_TWO_PARTY)

    def test_completion_and_midflight_guards_reject_deadlock(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"tests/test_cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _loader_barrier_deadlock_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        followup = _concurrency_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None and "barrier can never fill" in message
        assert followup is not None and followup.startswith("Before verification:")

    def test_clean_full_rewrite_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"tests/test_cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'write_text_file({"path":"tests/test_cache.py",'
                    f'"content":{json.dumps(self.GOOD)}}})'
                ),
            ),
        ]

        assert (
            _loader_barrier_deadlock_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestWaitWhileLockHeldGuard:
    BAD = """\
with self._lock:
    pending = self._pending.get(key)
    if pending is not None:
        pending.event.wait()
        return pending.result
    pending = Pending()
    self._pending[key] = pending
value = loader()
with self._lock:
    self._values[key] = value
pending.event.set()
return value
"""
    BAD_MANUAL = """\
self._lock.acquire()
pending = self._pending[key]
pending.event.wait()
self._lock.release()
"""
    GOOD = """\
with self._lock:
    pending = self._pending.get(key)
    is_leader = pending is None
    if is_leader:
        pending = Pending()
        self._pending[key] = pending
if not is_leader:
    pending.event.wait()
    return pending.result
value = loader()
with self._lock:
    self._values[key] = value
pending.event.set()
return value
"""

    def test_detector_flags_wait_under_lock(self) -> None:
        assert _payload_has_wait_while_lock_held(self.BAD)
        assert _payload_has_wait_while_lock_held(self.BAD_MANUAL)
        assert not _payload_has_wait_while_lock_held(self.GOOD)

    def test_completion_and_midflight_guards_reject_deadlock(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            )
        ]

        message = _wait_while_lock_held_guard(
            steps,
            "All tests pass.",
            is_code_mode=True,
        )
        followup = _concurrency_semantic_followup_guard(steps, is_code_mode=True)

        assert message is not None and "two sides deadlock" in message
        assert followup is not None and followup.startswith("Before verification:")

    def test_clean_full_rewrite_clears_guard(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.BAD)}}})'
                ),
            ),
            _step(
                2,
                action=(
                    'write_text_file({"path":"cache.py",'
                    f'"content":{json.dumps(self.GOOD)}}})'
                ),
            ),
        ]

        assert (
            _wait_while_lock_held_guard(
                steps,
                "All tests pass.",
                is_code_mode=True,
            )
            is None
        )


class TestStepReplacedCodeWithComment:
    def test_executable_to_comment_detected(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "runtime/foo.py", '
                '"old_string": "    raise ValueError(x)", '
                '"new_string": "    # was: raise ValueError(x)"})'
            ),
        )
        assert _step_replaced_code_with_comment(step)

    def test_executable_to_executable_silent(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "runtime/foo.py", '
                '"old_string": "x = 1", "new_string": "x = 2"})'
            ),
        )
        assert not _step_replaced_code_with_comment(step)

    def test_test_path_skipped(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "tests/test_foo.py", '
                '"old_string": "    assert x", "new_string": "    # disabled"})'
            ),
        )
        assert not _step_replaced_code_with_comment(step)

    def test_non_python_skipped(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "x.tsx", "old_string": "doStuff()", "new_string": "// gone"})'
            ),
        )
        assert not _step_replaced_code_with_comment(step)

    def test_multi_edit_one_pair_triggers(self) -> None:
        step = _step(
            1,
            action=(
                'multi_edit_file({"path": "runtime/foo.py", "edits": ['
                '{"old_string": "x=1", "new_string": "x=2"},'
                '{"old_string": "raise X", "new_string": "# was: raise X"}'
                "]})"
            ),
        )
        assert _step_replaced_code_with_comment(step)


class TestCommentedOutAsFixGuard:
    def test_non_code_mode_silent(self) -> None:
        steps = [
            _step(
                1,
                action='edit_file({"path": "runtime/foo.py", "old_string": "raise X", "new_string": "# gone"})',
            ),
        ]
        assert (
            _commented_out_as_fix_guard(
                steps,
                "done",
                is_code_mode=False,
            )
            is None
        )

    def test_no_replacement_silent(self) -> None:
        steps = [
            _step(
                1,
                action='edit_file({"path": "runtime/foo.py", "old_string": "x", "new_string": "y"})',
            )
        ]
        assert (
            _commented_out_as_fix_guard(
                steps,
                "done",
                is_code_mode=True,
            )
            is None
        )

    def test_executable_to_comment_fires(self) -> None:
        steps = [
            _step(
                1,
                action='edit_file({"path": "runtime/foo.py", "old_string": "    raise ValueError(x)", "new_string": "    # was: raise ValueError(x)"})',
            ),
        ]
        msg = _commented_out_as_fix_guard(
            steps,
            "done",
            is_code_mode=True,
        )
        assert msg is not None
        assert "comment" in msg.lower()

    def test_help_request_short_circuits(self) -> None:
        steps = [
            _step(
                1,
                action='edit_file({"path": "runtime/foo.py", "old_string": "raise X", "new_string": "# gone"})',
            ),
        ]
        assert (
            _commented_out_as_fix_guard(
                steps,
                "I cannot continue — please provide the API key.",
                is_code_mode=True,
            )
            is None
        )


# ══════════════════════════════════════════════════════════════════
# §30 — broad-except suppression
# ══════════════════════════════════════════════════════════════════


class TestPayloadHasBroadExceptSuppression:
    def test_except_exception_pass(self) -> None:
        text = "try:\n    foo()\nexcept Exception:\n    pass\n"
        assert _payload_has_broad_except_suppression(text)

    def test_except_bare_pass(self) -> None:
        text = "try:\n    foo()\nexcept:\n    pass\n"
        assert _payload_has_broad_except_suppression(text)

    def test_except_baseexception_ellipsis(self) -> None:
        text = "try:\n    foo()\nexcept BaseException:\n    ...\n"
        assert _payload_has_broad_except_suppression(text)

    def test_except_exception_comment_only(self) -> None:
        text = "try:\n    foo()\nexcept Exception:\n    # ignore\n"
        assert _payload_has_broad_except_suppression(text)

    def test_except_with_real_handling_silent(self) -> None:
        text = "try:\n    foo()\nexcept Exception as e:\n    log.error(e)\n"
        assert not _payload_has_broad_except_suppression(text)

    def test_specific_exception_silent(self) -> None:
        text = "try:\n    foo()\nexcept ValueError:\n    pass\n"
        assert not _payload_has_broad_except_suppression(text)

    def test_no_try_silent(self) -> None:
        assert not _payload_has_broad_except_suppression("def hello():\n    return 1\n")


class TestStepIntroducesBroadExceptSuppression:
    def test_new_suppression_in_runtime_detected(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "runtime/foo.py", '
                '"old_string": "x = 1", '
                '"new_string": "try:\\n    x = 1\\nexcept Exception:\\n    pass"})'
            ),
        )
        assert _step_introduces_broad_except_suppression(step)

    def test_pre_existing_suppression_silent(self) -> None:
        # Already in old_string — moving it doesn't count as new.
        step = _step(
            1,
            action=(
                'edit_file({"path": "runtime/foo.py", '
                '"old_string": "try:\\n    x = 1\\nexcept Exception:\\n    pass", '
                '"new_string": "try:\\n    x = 2\\nexcept Exception:\\n    pass"})'
            ),
        )
        assert not _step_introduces_broad_except_suppression(step)

    def test_test_path_skipped(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "tests/test_foo.py", '
                '"old_string": "x", '
                '"new_string": "try: x\\nexcept Exception: pass"})'
            ),
        )
        assert not _step_introduces_broad_except_suppression(step)

    def test_specific_exception_silent(self) -> None:
        step = _step(
            1,
            action=(
                'edit_file({"path": "runtime/foo.py", '
                '"old_string": "x = 1", '
                '"new_string": "try:\\n    x = 1\\nexcept ValueError:\\n    pass"})'
            ),
        )
        assert not _step_introduces_broad_except_suppression(step)


class TestBroadExceptSuppressionGuard:
    def test_non_code_mode_silent(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path": "runtime/foo.py", '
                    '"old_string": "x", "new_string": "try: x\\nexcept Exception: pass"})'
                ),
            ),
        ]
        assert (
            _broad_except_suppression_guard(
                steps,
                "done",
                is_code_mode=False,
            )
            is None
        )

    def test_no_new_suppression_silent(self) -> None:
        steps = [
            _step(
                1,
                action='edit_file({"path": "runtime/foo.py", "old_string": "x", "new_string": "y"})',
            )
        ]
        assert (
            _broad_except_suppression_guard(
                steps,
                "done",
                is_code_mode=True,
            )
            is None
        )

    def test_new_suppression_fires(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path": "runtime/foo.py", '
                    '"old_string": "x = 1", '
                    '"new_string": "try:\\n    x = 1\\nexcept Exception:\\n    pass"})'
                ),
            ),
        ]
        msg = _broad_except_suppression_guard(
            steps,
            "done",
            is_code_mode=True,
        )
        assert msg is not None
        assert "except" in msg.lower()

    def test_help_request_short_circuits(self) -> None:
        steps = [
            _step(
                1,
                action=(
                    'edit_file({"path": "runtime/foo.py", '
                    '"old_string": "x", '
                    '"new_string": "try: x\\nexcept Exception: pass"})'
                ),
            ),
        ]
        assert (
            _broad_except_suppression_guard(
                steps,
                "I cannot continue — please provide the API key.",
                is_code_mode=True,
            )
            is None
        )


# ─── browser-mode scoping of the evidence guards ──────────────────────


class TestEvidenceGuardsBrowserScope:
    """Browser turns prove work via browser-action evidence, not file
    writes. A CRUD-style browser goal ("create/edit/delete …") matches the
    mutation markers, so without the browser_operation_mode skip the write
    guard derails the model into writing throwaway files (observed live:
    browser.dynamic-crud burned 25+ iterations appeasing it)."""

    def _browser_ctx(self, **overrides):
        from runtime.core.cerebrum.react_guards import GuardContext
        from runtime.core.cerebrum.react_types import ReActStep

        defaults = dict(
            steps=[
                ReActStep(
                    iteration=1,
                    action='browser_navigate({"url": "http://127.0.0.1:8123/"})',
                    observation="page loaded",
                )
            ],
            final_answer="Created, edited and deleted the plan through the UI.",
            is_code_mode=True,
            tools_active=True,
            goal="Use the browser UI to create, edit and delete a plan entry.",
            browser_operation_mode=True,
        )
        defaults.update(overrides)
        return GuardContext(**defaults)

    def test_write_guard_skips_browser_mode(self) -> None:
        from runtime.core.cerebrum.react_guards import _invoke_missing_write

        assert _invoke_missing_write(self._browser_ctx()) is None

    def test_inspection_guard_skips_browser_mode(self) -> None:
        from runtime.core.cerebrum.react_guards import _invoke_missing_inspection

        assert _invoke_missing_inspection(self._browser_ctx()) is None

    def test_write_guard_still_fires_for_plain_code_mode(self) -> None:
        from runtime.core.cerebrum.react_guards import _invoke_missing_write

        ctx = self._browser_ctx(
            browser_operation_mode=False,
            goal="Fix the cache implementation and verify it.",
            final_answer="Implemented the fix and verified it.",
        )
        assert _invoke_missing_write(ctx) is not None

    def test_write_guard_still_fires_for_mixed_browser_and_code_task(self) -> None:
        from runtime.core.cerebrum.react_guards import _invoke_missing_write

        ctx = self._browser_ctx(
            goal=(
                "Use the browser UI to reproduce the bug, then fix the source code and run tests."
            ),
            final_answer="Reproduced the bug, implemented the fix, and ran tests.",
        )
        assert _invoke_missing_write(ctx) is not None

    def test_inspection_guard_still_fires_for_mixed_browser_and_code_task(self) -> None:
        from runtime.core.cerebrum.react_guards import _invoke_missing_inspection

        ctx = self._browser_ctx(
            goal=(
                "Use the browser UI to reproduce the bug, then inspect the project files "
                "and fix the source code."
            ),
            final_answer="Inspected the project and fixed the source code.",
            file_inspection_tools_visible=True,
        )
        assert _invoke_missing_inspection(ctx) is not None

    @pytest.mark.parametrize(
        "goal",
        [
            "Reproduce it in the browser, patch repo, and verify with pytest.",
            "Use the UI to confirm the issue; update the backend module and run tests.",
            "先在浏览器界面复现，再修改代码仓库里的实现并运行测试。",
        ],
    )
    def test_common_mixed_task_phrasings_are_not_ui_only(self, goal: str) -> None:
        from runtime.core.cerebrum.react_guards import _browser_goal_is_ui_only

        assert _browser_goal_is_ui_only(goal) is False

    @pytest.mark.parametrize(
        "goal",
        [
            "Use the browser UI to upload a file and test the form.",
            "In the browser, edit the repository settings and save them.",
            "通过 UI 编辑项目计划并下载文件。",
        ],
    )
    def test_browser_entities_and_uploaded_files_remain_ui_only(self, goal: str) -> None:
        from runtime.core.cerebrum.react_guards import _browser_goal_is_ui_only

        assert _browser_goal_is_ui_only(goal) is True
