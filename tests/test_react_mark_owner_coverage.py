"""Dense coverage for react_loop owner-status mirror (audit Q-05)."""

from __future__ import annotations

from runtime.core.cerebrum import react_loop as rl


class _FakeStore:
    def __init__(self):
        self.busy = []
        self.idle = []

    def mark_thread_busy(self, thread_id):
        self.busy.append(thread_id)

    def mark_thread_idle(self, thread_id):
        self.idle.append(thread_id)


def test_mark_owner_thread_busy_idle(monkeypatch) -> None:
    store = _FakeStore()
    import runtime.execution.subagents.sessions as sess

    monkeypatch.setattr(sess, "get_subagent_session_store", lambda: store)
    rl._mark_subagent_owner_thread("t1", busy=True)
    rl._mark_subagent_owner_thread("t1", busy=False)
    assert store.busy == ["t1"]
    assert store.idle == ["t1"]
    rl._mark_subagent_owner_thread("", busy=True)  # empty -> no-op


def test_mark_owner_thread_best_effort(monkeypatch) -> None:
    import runtime.execution.subagents.sessions as sess

    monkeypatch.setattr(sess, "get_subagent_session_store", lambda: None)
    rl._mark_subagent_owner_thread("t1", busy=True)  # store None -> no-op

    def _boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(sess, "get_subagent_session_store", _boom)
    rl._mark_subagent_owner_thread("t1", busy=True)  # failure swallowed


def test_sandbox_violation_detection() -> None:
    from runtime.core.cerebrum._react_execution_phase6d import (
        _can_escalate_sandbox,
        _looks_like_sandbox_violation,
    )

    assert _looks_like_sandbox_violation("sandbox_violation: /x") is True
    assert _looks_like_sandbox_violation("Sandbox-Violation detected") is True
    assert _looks_like_sandbox_violation("ordinary output") is False
    assert _looks_like_sandbox_violation(None) is False
    assert _can_escalate_sandbox("exec_shell") is True
    assert _can_escalate_sandbox("read_file") is False


def test_workspace_sandbox_absorbs_routine_shell_and_edit_approval(
    monkeypatch,
) -> None:
    import runtime.core.cerebrum._react_execution_phase6d as phase6d
    from runtime.core.cerebrum._react_execution_phase6d import (
        _workspace_sandbox_handles_ordinary_action,
    )
    from runtime.safety.approval.approval_gate import assess_approval_risk

    context = {
        "permission_mode": "acceptEdits",
        "execution_environment": "sandbox",
        "sandbox_mode": "sandbox",
    }
    monkeypatch.setattr(phase6d, "_hard_workspace_sandbox_available", lambda: True)
    assert _workspace_sandbox_handles_ordinary_action(
        "exec_shell",
        assess_approval_risk("exec_shell", "python -m pytest"),
        context,
    )
    assert _workspace_sandbox_handles_ordinary_action(
        "edit_text_file",
        assess_approval_risk("edit_text_file", '{"path": "src/app.py"}'),
        context,
    )


def test_workspace_sandbox_keeps_external_and_destructive_actions_at_the_gate(
    monkeypatch,
) -> None:
    import runtime.core.cerebrum._react_execution_phase6d as phase6d
    from runtime.core.cerebrum._react_execution_phase6d import (
        _workspace_sandbox_handles_ordinary_action,
    )
    from runtime.safety.approval.approval_gate import assess_approval_risk

    context = {
        "permission_mode": "default",
        "execution_environment": "sandbox",
        "sandbox_mode": "sandbox",
    }
    monkeypatch.setattr(phase6d, "_hard_workspace_sandbox_available", lambda: True)
    assert not _workspace_sandbox_handles_ordinary_action(
        "git_push",
        assess_approval_risk("git_push", "{}"),
        context,
    )
    assert not _workspace_sandbox_handles_ordinary_action(
        "exec_shell",
        assess_approval_risk("exec_shell", "Remove-Item -Recurse -Force ."),
        context,
    )


def test_soft_workspace_sandbox_keeps_native_command_at_the_gate(monkeypatch) -> None:
    import runtime.core.cerebrum._react_execution_phase6d as phase6d
    from runtime.safety.approval.approval_gate import assess_approval_risk

    monkeypatch.setattr(phase6d, "_hard_workspace_sandbox_available", lambda: False)
    assert not phase6d._workspace_sandbox_handles_ordinary_action(
        "exec_shell",
        assess_approval_risk("exec_shell", "python -m pytest"),
        {
            "permission_mode": "acceptEdits",
            "execution_environment": "sandbox",
            "sandbox_mode": "sandbox",
        },
    )
