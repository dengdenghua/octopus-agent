from __future__ import annotations

import asyncio
from pathlib import Path

from runtime.execution.codex_backend.approvals import CodexApprovalBroker
from runtime.execution.codex_backend.types import ApprovalRequest
from runtime.safety.approval.approval_gate import ApprovalDecision, ApprovalProvider


class _Provider(ApprovalProvider):
    def __init__(self, approved: bool = True) -> None:
        self.approved = approved
        self.requests = []

    def request(self, req, *, timeout: float = 120.0):
        self.requests.append((req, timeout))
        return ApprovalDecision(approved=self.approved, reason="test")


def _broker(tmp_path: Path, provider: _Provider, interrupted=lambda: False):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    broker = CodexApprovalBroker(
        provider,
        outer_thread_id="outer-thread",
        outer_turn_id="outer-turn",
        workspace=workspace,
        is_interrupted=interrupted,
    )
    broker.bind_inner_scope(thread_id="inner-thread", turn_id="inner-turn")
    return broker, workspace


def test_command_approval_uses_outer_provider_without_session_grant(tmp_path: Path) -> None:
    provider = _Provider(approved=True)
    broker, workspace = _broker(tmp_path, provider)

    result = asyncio.run(
        broker(
            ApprovalRequest(
                request_id=7,
                method="item/commandExecution/requestApproval",
                params={
                    "threadId": "inner-thread",
                    "turnId": "inner-turn",
                    "itemId": "command-1",
                    "command": "pytest -q",
                    "cwd": str(workspace),
                },
            )
        )
    )

    assert result == {"decision": "accept"}
    request, timeout = provider.requests[0]
    assert request.thread_id == "outer-thread"
    assert request.tool_name == "exec_shell"
    assert request.tool_call_id == "command-1"
    assert "pytest -q" in request.args_preview
    assert timeout == 120.0


def test_cross_turn_request_and_outside_grant_root_fail_closed(tmp_path: Path) -> None:
    provider = _Provider(approved=True)
    broker, _workspace = _broker(tmp_path, provider)

    cross_turn = asyncio.run(
        broker(
            ApprovalRequest(
                1,
                "item/commandExecution/requestApproval",
                {"threadId": "inner-thread", "turnId": "other", "itemId": "cmd"},
            )
        )
    )
    outside = asyncio.run(
        broker(
            ApprovalRequest(
                2,
                "item/fileChange/requestApproval",
                {
                    "threadId": "inner-thread",
                    "turnId": "inner-turn",
                    "itemId": "patch",
                    "grantRoot": "/etc",
                },
            )
        )
    )

    assert cross_turn == {"decision": "decline"}
    assert outside == {"decision": "decline"}
    assert provider.requests == []


def test_permission_expansion_is_never_forwarded_to_boolean_approval(tmp_path: Path) -> None:
    provider = _Provider(approved=True)
    broker, workspace = _broker(tmp_path, provider)

    result = asyncio.run(
        broker(
            ApprovalRequest(
                3,
                "item/permissions/requestApproval",
                {
                    "threadId": "inner-thread",
                    "turnId": "inner-turn",
                    "itemId": "permissions",
                    "cwd": str(workspace),
                    "permissions": {"network": {"enabled": True}},
                },
            )
        )
    )

    assert result == {"permissions": {}, "scope": "turn", "strictAutoReview": True}
    assert provider.requests == []


def test_interrupt_after_user_accept_translates_to_cancel(tmp_path: Path) -> None:
    provider = _Provider(approved=True)
    interrupted = {"value": False}

    class _InterruptingProvider(_Provider):
        def request(self, req, *, timeout: float = 120.0):
            interrupted["value"] = True
            return super().request(req, timeout=timeout)

    provider = _InterruptingProvider()
    broker, _workspace = _broker(tmp_path, provider, lambda: interrupted["value"])
    result = asyncio.run(
        broker(
            ApprovalRequest(
                4,
                "item/fileChange/requestApproval",
                {
                    "threadId": "inner-thread",
                    "turnId": "inner-turn",
                    "itemId": "patch",
                },
            )
        )
    )

    assert result == {"decision": "cancel"}
