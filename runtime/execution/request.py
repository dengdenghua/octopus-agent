"""Host-owned task context shared by execution engines.

These values are Python objects, never grants deserialized from model or
transport JSON. Engine conversations, credentials and checkpoint state remain
inside their adapters. A continuation changes the instruction, not the task's
identity, permission ceiling or resource policy.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from runtime.safety.approval.approval_gate import ApprovalProvider

from runtime.execution.artifact_contracts import ArtifactContract
from runtime.platform.process.scope import ExecutionScope, execution_scope_ceiling


class ExecutionDeadlineExceeded(TimeoutError):
    """The host's task deadline expired, including earlier invocations."""


@dataclass(frozen=True, slots=True)
class ExecutionResources:
    """Resource policy, separate from an engine's usage accounting.

    Token and USD targets retain the host's existing elastic-budget semantics.
    They are not promises of a hard spending cap: an adapter must report usage
    and support enforcement before such a promise can be made. The absolute
    monotonic deadline is enforced by the host across all continuations.
    """

    token_target: int
    usd_target: float
    deadline: float | None

    def __post_init__(self) -> None:
        if type(self.token_target) is not int or self.token_target <= 0:
            raise ValueError("token target must be a positive integer")
        if not math.isfinite(self.usd_target) or self.usd_target <= 0:
            raise ValueError("USD target must be positive and finite")
        if self.deadline is not None and not math.isfinite(self.deadline):
            raise ValueError("execution deadline must be finite")

    def remaining_seconds(self) -> float | None:
        if self.deadline is None:
            return None
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ExecutionDeadlineExceeded("task execution deadline exceeded")
        return remaining


@dataclass(frozen=True, slots=True)
class ExecutionTask:
    task_id: str
    thread_id: str
    actor_id: str | None
    tenant_id: str | None
    goal: str
    permissions: ExecutionScope
    resources: ExecutionResources
    parent_task_id: str | None = None
    artifacts: ArtifactContract | None = None
    execution_engine: Literal["octopus", "codex", "opencode"] | None = None
    approval_provider: ApprovalProvider | None = None
    server_auto_approve: bool = False
    authorization_intent: str = ""

    def __post_init__(self) -> None:
        if not self.task_id or not self.thread_id:
            raise ValueError("execution requires host task and thread coordinates")
        if bool(self.actor_id) != bool(self.tenant_id):
            raise ValueError("execution principal is incomplete")
        if self.execution_engine not in {None, "octopus", "codex", "opencode"}:
            raise ValueError("unknown execution engine")


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    task: ExecutionTask
    instruction: str


_CURRENT_REQUEST: ContextVar[ExecutionRequest | None] = ContextVar(
    "host_execution_request", default=None
)


def current_execution_request() -> ExecutionRequest | None:
    """Read the server-owned request without inspecting engine-private state."""
    return _CURRENT_REQUEST.get()


@contextmanager
def execution_request_scope(request: ExecutionRequest) -> Iterator[None]:
    token = _CURRENT_REQUEST.set(request)
    try:
        with execution_scope_ceiling(request.task.permissions):
            yield
    finally:
        _CURRENT_REQUEST.reset(token)
