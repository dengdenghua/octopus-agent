from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.models import (
    AntigenSignature,
    ArmId,
    CostEntry,
    ImmuneVerdict,
    Source,
    Step,
    TaskId,
    Trajectory,
    new_id,
    now_utc,
)

JournalEventType = Literal[
    "step",
    "trajectory",
    "immune",
    "budget_squirt",
    "budget_commit",
    "budget_breaker_reset",
    "genome_patch",
    "reflex_hit",
    "task_started",
    "node_started",
    "task_checkpoint",
    "react_checkpoint",
    "tool_effect_intent",
    "tool_effect_reconciliation",
    "task_paused",
    "task_resumed",
    "token_usage",
    "file_op",
    "file_rollback",
    "preview_refresh",
    "skill_proposal_decision",
    "curriculum_goal_decision",
    "mcp_proposal_decision",
    "protocol_drift_decision",
    "sub_tool_start",
    "sub_tool_end",
    "browser_artifact",
]


# Event schema version. Bump when any event shape changes in a way
# that isn't purely additive (e.g. field rename, type narrowing,
# required-field addition). Readers honor this via `_EVENT_MIGRATIONS`
# below — old events parse through migration adapters to the current
# shape. The goal: past jsonl journals survive refactors.
#
# Version history:
#   1 — initial versioned schema (2026-04-19). Prior events lack
#       the field entirely; reader treats them as v1 since the shape
#       only changed additively up to this point. Any NEW breaking
#       change should introduce v2 and register a migration in
#       `_EVENT_MIGRATIONS`.
CURRENT_SCHEMA_VERSION = 1


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = CURRENT_SCHEMA_VERSION
    event_id: UUID = Field(default_factory=new_id)
    event_type: JournalEventType
    task_id: TaskId | None = None
    arm_id: ArmId | None = None
    actor: str | None = None
    # Tenant ownership is part of the event envelope so JSONL and every
    # derived read model carry the same authorization context.  Existing
    # events omit these fields and are treated as legacy during migration.
    tenant_id: str | None = None
    owner_actor_id: str | None = None
    agent_id: str | None = None
    conversation_id: str | None = None
    ts: datetime = Field(default_factory=now_utc)
    source: Source | None = None


class StepEvent(JournalEvent):
    event_type: Literal["step"] = "step"
    step: Step


class TrajectoryEvent(JournalEvent):
    event_type: Literal["trajectory"] = "trajectory"
    trajectory: Trajectory


class ImmuneEvent(JournalEvent):
    event_type: Literal["immune"] = "immune"
    verdict: ImmuneVerdict
    signature: AntigenSignature
    reason: str = ""


class BudgetEvent(JournalEvent):
    event_type: Literal["budget_squirt", "budget_commit"] = "budget_commit"
    reason: str = ""
    cost: CostEntry = Field(default_factory=CostEntry)


class BudgetBreakerResetEvent(JournalEvent):
    """Operator reset for a derived budget/circuit-breaker component."""

    event_type: Literal["budget_breaker_reset"] = "budget_breaker_reset"
    component: str = ""
    reason: str = ""


class TaskStartedEvent(JournalEvent):
    event_type: Literal["task_started"] = "task_started"
    total_nodes: int = 0
    strategy: str = ""
    task_type: str = ""
    recipe_hash: str | None = None


class NodeStartedEvent(JournalEvent):
    event_type: Literal["node_started"] = "node_started"
    node_id: str = ""
    skill_ref: str = ""
    node_index: int = 0  # Implementation note.


class TaskCheckpointEvent(JournalEvent):
    event_type: Literal["task_checkpoint"] = "task_checkpoint"
    nodes_completed: int = 0
    total_nodes: int = 0
    tokens_spent: int = 0
    usd_spent: float = 0.0


class ReactCheckpointEvent(JournalEvent):
    """ReAct iteration checkpoint · written after each completed
    thought→action→observation cycle so a crashed/refreshed session
    can resume from the last good iteration.

    ``messages_snapshot`` is the serialized LLM message list at the
    end of this iteration (system + history + all prior
    thought/observation pairs). ``steps_snapshot`` carries the
    structured ``ReActStep`` dicts accumulated so far.

    ``working_set_snapshot`` carries the set of files the agent has
    read or modified, so a resumed agent knows which files are in
    play without re-reading them all.

    ``progress_summary`` is a short human-readable summary of what
    has been accomplished so far, injected into the resumed agent's
    system prompt so it can pick up context quickly.
    """

    event_type: Literal["react_checkpoint"] = "react_checkpoint"
    iteration_completed: int = 0
    max_iterations: int = 8
    messages_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    steps_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    has_final_answer: bool = False
    final_answer: str = ""
    working_set_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    progress_summary: str = ""
    current_phase: str = ""


class ToolEffectIntentEvent(JournalEvent):
    """Durable write-ahead marker for one tool invocation.

    The marker is appended immediately before entering a handler. If the
    process dies before its :class:`StepEvent` is written, recovery knows the
    side effect is indeterminate and must not blindly execute it again.
    """

    event_type: Literal["tool_effect_intent"] = "tool_effect_intent"
    effect_key: str
    call_id: str
    step_id: int = 0
    node_id: str = ""
    sucker_id: str = ""
    args_fingerprint: str = ""
    side_effecting: bool = False


class ToolEffectReconciliationEvent(JournalEvent):
    """Auditable operator decision for an indeterminate external effect."""

    event_type: Literal["tool_effect_reconciliation"] = "tool_effect_reconciliation"
    effect_key: str
    fencing_token: int
    action: Literal["authorize_retry"] = "authorize_retry"
    reason: str


class TaskPausedEvent(JournalEvent):
    event_type: Literal["task_paused"] = "task_paused"
    reason: str = "user_request"
    requested_by: str = ""
    iteration: int = 0


class TaskResumedEvent(JournalEvent):
    event_type: Literal["task_resumed"] = "task_resumed"
    resumed_by: str = ""
    extra_tokens: int = 0
    extra_usd: float = 0.0
    extra_iterations: int = 0


class TokenUsageEvent(JournalEvent):
    event_type: Literal["token_usage"] = "token_usage"
    iteration: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""


class FileOpEvent(JournalEvent):
    event_type: Literal["file_op"] = "file_op"
    path: str = ""
    action: Literal["create", "write", "edit", "delete", "rename"] = "write"
    old_size: int | None = None
    new_size: int | None = None
    bytes_delta: int = 0
    sucker_id: str = ""
    diff: str | None = None
    rollback: dict[str, Any] | None = None


class FileRollbackEvent(JournalEvent):
    event_type: Literal["file_rollback"] = "file_rollback"
    dry_run: bool = False
    project_root: str = ""
    event_id_filter: str | None = None
    task_id_filter: str | None = None
    path_filter: str | None = None
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    source_event_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PreviewRefreshEvent(JournalEvent):
    event_type: Literal["preview_refresh"] = "preview_refresh"
    target: str = ""
    trigger_path: str = ""
    reason: str = ""


class ReflexHitEvent(JournalEvent):
    event_type: Literal["reflex_hit"] = "reflex_hit"
    rule_id: str = ""
    kind: str = "regex"  # regex / deterministic / cache / slm
    latency_ms: float = 0.0
    intent_goal: str = ""
    response: Any = None  # Implementation note.


class SkillProposalDecisionEvent(JournalEvent):
    """Operator decision for a self-evolution skill proposal."""

    event_type: Literal["skill_proposal_decision"] = "skill_proposal_decision"
    proposal_kind: str = "skill_forge"
    proposal_name: str = ""
    candidate_id: str = ""
    decision: str = ""
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class CurriculumGoalDecisionEvent(JournalEvent):
    """Operator decision for a journal-derived learning goal."""

    event_type: Literal["curriculum_goal_decision"] = "curriculum_goal_decision"
    goal_id: int = 0
    cluster_key: str = ""
    status: str = ""
    covered_by: str | None = None
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class McpProposalDecisionEvent(JournalEvent):
    """Operator/vet decision for a suggested MCP capability."""

    event_type: Literal["mcp_proposal_decision"] = "mcp_proposal_decision"
    server_name: str = ""
    status: str = ""
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class ProtocolDriftDecisionEvent(JournalEvent):
    """Operator decision for a detected protocol drift event."""

    event_type: Literal["protocol_drift_decision"] = "protocol_drift_decision"
    drift_id: int = 0
    protocol_id: str = ""
    status: str = ""
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class SubToolStartEvent(JournalEvent):
    """Emitted when a sub-agent begins a tool call.

    Mirrors the ``sub_tool_start`` shape the SSE pump streams to
    the UI (see ``ephemeral_runner._emit_sub_tool_event``). Pushed
    through the journal so any subscriber — SSE pump, observability
    panel, persistent log — sees it without separate plumbing.
    """

    event_type: Literal["sub_tool_start"] = "sub_tool_start"
    role_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    iteration: int = 0
    args_preview: str = ""
    parent_tool_use_id: str | None = None


class SubToolEndEvent(JournalEvent):
    """Emitted when a sub-agent finishes a tool call."""

    event_type: Literal["sub_tool_end"] = "sub_tool_end"
    role_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    iteration: int = 0
    is_error: bool = False
    duration_ms: int = 0
    output_preview: str = ""
    parent_tool_use_id: str | None = None


class BrowserArtifactEvent(JournalEvent):
    """A browser screenshot (or similar artifact) was produced.

    Saved to disk by ``browser_act_skills._emit_screenshot_artifact``.
    This event lets the SSE pump deliver the artifact inline in the
    chat stream, so screenshots appear as they're
    captured rather than only showing up in a separate panel.
    """

    event_type: Literal["browser_artifact"] = "browser_artifact"
    kind: str = "screenshot"
    url: str = ""
    filename: str = ""
    caption: str = ""
    mime_type: str = "image/png"
    width: int | None = None
    height: int | None = None
    thread_id: str = ""
