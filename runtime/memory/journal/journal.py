from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path
from threading import Lock
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
from runtime.safety.invariants import AppendOnlyList
from runtime.safety.invariants.enforce import enforces

from .journal_context import current_agent_id, current_conversation_id

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════

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


# ╔════════════════════════════════════════════════════════════════════════╗
# ║ journal.py · navigation map (1405 lines).                              ║
# ║                                                                        ║
# ║   §1  JournalEvent base                                ~L79            ║
# ║   §2  Per-event-type subclasses (Step/Trajectory/...)  ~L95-360        ║
# ║       StepEvent / TrajectoryEvent / ImmuneEvent /                      ║
# ║       BudgetEvent / TaskStarted / NodeStarted /                        ║
# ║       Checkpoints / Pause/Resume / TokenUsage /                        ║
# ║       FileOp / Rollback / PreviewRefresh /                             ║
# ║       Reflex/SkillProposal/Curriculum/Mcp/Protocol /                   ║
# ║       SubTool / BrowserArtifact                                        ║
# ║   §3  Journal abstract base                            ~L366           ║
# ║   §4  InMemoryJournal                                  ~L972           ║
# ║   §5  JSONLJournal (file-backed, the production impl)  ~L995           ║
# ║   §6  _migrate_event + _parse_event                    ~L1382          ║
# ╚════════════════════════════════════════════════════════════════════════╝


class JournalEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: int = CURRENT_SCHEMA_VERSION
    event_id: UUID = Field(default_factory=new_id)
    event_type: JournalEventType
    task_id: TaskId | None = None
    arm_id: ArmId | None = None
    actor: str | None = None
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


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class Journal:
    def write(self, event: JournalEvent) -> None:
        raise NotImplementedError

    def read_all(self) -> list[JournalEvent]:
        raise NotImplementedError

    def diagnostics(self) -> dict[str, Any]:
        events = self.read_all()
        return {
            "schema": "octopus.journal_diagnostics.v1",
            "path": "",
            "parsed_events": len(events),
            "cache_byte_pos": 0,
            "parsed_line_count": len(events),
            "skipped_total": 0,
            "skipped_lines": [],
            "pending_tail_bytes": 0,
        }

    def read_by_task(self, task_id: TaskId) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.task_id == task_id]

    def read_by_type(self, event_type: JournalEventType) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.event_type == event_type]

    def read_since(self, ts: datetime) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.ts >= ts]

    def read_by_actor(self, actor: str) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.actor == actor]

    def read_by_agent(self, agent_id: str) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.agent_id == agent_id]

    def file_transaction_summary(
        self,
        *,
        task_id: TaskId | str | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        from runtime.memory.runtime_state.file_transactions import summarize_file_ops

        events = self.read_by_type("file_op")
        if task_id is not None:
            events = [e for e in events if str(e.task_id or "") == str(task_id)]
        if actor is not None:
            events = [e for e in events if e.actor == actor]
        return summarize_file_ops(events).to_dict()

    def read_by_conversation(
        self,
        conversation_id: str,
    ) -> list[JournalEvent]:
        return [e for e in self.read_all() if e.conversation_id == conversation_id]

    def list_conversations(
        self,
        *,
        agent_id: str | None = None,
    ) -> list[str]:
        seen: dict[str, datetime] = {}
        for e in self.read_all():
            cid = e.conversation_id
            if cid is None:
                continue
            if agent_id is not None and e.agent_id != agent_id:
                continue
            if cid not in seen or e.ts < seen[cid]:
                seen[cid] = e.ts
        return [cid for cid, _ts in sorted(seen.items(), key=lambda kv: kv[1])]

    def export_trajectories(
        self,
        *,
        task_id: TaskId | None = None,
        format: str = "sharegpt",  # noqa: A002
    ) -> list[dict[str, Any]]:
        """Export execution trajectories as training data.

        Converts ``StepEvent`` + ``TrajectoryEvent`` sequences into
        a format suitable for LLM fine-tuning.

        Parameters
        ----------
        task_id:
            If given, export only events for this task. Otherwise
            export all tasks.
        format:
            ``"sharegpt"`` (default) — ShareGPT-compatible JSONL
            conversations format commonly used by chat-model
            fine-tuning pipelines::

                {
                  "conversations": [
                    {"from": "human", "value": "<goal>"},
                    {"from": "gpt",   "value": "<thought>"},
                    {"from": "tool",  "value": "<tool_call>"},
                    {"from": "tool_result", "value": "<result>"},
                    ...
                  ],
                  "task_id": "...",
                  "outcome": "pass|fail|pass_degraded|unknown",
                  "total_cost_tokens": 0,
                }

            ``"raw"`` — list of dicts with all event fields.

        Returns
        -------
        list[dict]
            One entry per task (ShareGPT) or one entry per event
            (raw).
        """
        events = self.read_all()
        if task_id is not None:
            events = [e for e in events if e.task_id == task_id]

        if format == "raw":
            import json as _json

            return [_json.loads(e.model_dump_json()) for e in events]

        # ── ShareGPT format ──────────────────────────────────────
        # Group events by task_id, then build a conversation thread
        # from the step sequence.
        from collections import defaultdict

        by_task: dict[str, list[JournalEvent]] = defaultdict(list)
        for e in events:
            key = str(e.task_id) if e.task_id else "__unbound__"
            by_task[key].append(e)

        records: list[dict[str, Any]] = []
        for tid, task_events in by_task.items():
            task_events.sort(key=lambda e: e.ts)
            conversations: list[dict[str, str]] = []
            outcome = "unknown"
            total_tokens = 0

            for ev in task_events:
                if isinstance(ev, TaskStartedEvent):
                    goal = getattr(ev, "goal", None) or ""
                    if goal:
                        conversations.append(
                            {"from": "human", "value": goal},
                        )
                elif isinstance(ev, StepEvent):
                    step = getattr(ev, "step", None)
                    if step is None:
                        continue
                    action = getattr(step, "action", None)
                    result = getattr(step, "result", None)
                    if action is not None:
                        import json as _json

                        try:
                            args_str = _json.dumps(
                                getattr(action, "args", {}),
                                ensure_ascii=False,
                            )
                        except (TypeError, ValueError):
                            args_str = str(getattr(action, "args", ""))
                        conversations.append(
                            {
                                "from": "tool",
                                "value": (f"{getattr(action, 'sucker_id', '?')}({args_str})"),
                            }
                        )
                    if result is not None:
                        try:
                            import json as _json

                            out_str = _json.dumps(
                                getattr(result, "output", ""),
                                ensure_ascii=False,
                            )
                        except (TypeError, ValueError):
                            out_str = str(getattr(result, "output", ""))
                        conversations.append(
                            {
                                "from": "tool_result",
                                "value": out_str[:2000],
                            }
                        )
                        cost = getattr(result, "cost", None)
                        if cost is not None:
                            total_tokens += (
                                (getattr(cost, "tokens_in", 0) or 0)
                                + (getattr(cost, "tokens_out", 0) or 0)
                                # legacy field name kept for compat
                                + (getattr(cost, "tokens", 0) or 0)
                            )
                elif isinstance(ev, TrajectoryEvent):
                    traj = getattr(ev, "trajectory", None)
                    if traj is not None:
                        traj_outcome = getattr(traj, "outcome", None)
                        if traj_outcome is not None:
                            # ``TrajectoryOutcome`` exposes ``success`` /
                            # ``degraded`` — there is no ``status`` field,
                            # so derive the label from the real booleans.
                            if getattr(traj_outcome, "success", False):
                                outcome = (
                                    "pass_degraded"
                                    if getattr(traj_outcome, "degraded", False)
                                    else "pass"
                                )
                            else:
                                outcome = "fail"

            if conversations:
                records.append(
                    {
                        "conversations": conversations,
                        "task_id": tid,
                        "outcome": outcome,
                        "total_cost_tokens": total_tokens,
                    }
                )

        return records

    def write_step(
        self,
        task_id: TaskId,
        arm_id: ArmId,
        step: Step,
        *,
        actor: str | None = None,
    ) -> None:
        self.write(
            StepEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                step=step,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_trajectory(
        self,
        trajectory: Trajectory,
        *,
        actor: str | None = None,
    ) -> None:
        self.write(
            TrajectoryEvent(
                task_id=trajectory.task_id,
                arm_id=trajectory.arm_id,
                actor=actor,
                trajectory=trajectory,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_task_started(
        self,
        task_id: TaskId,
        *,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        total_nodes: int = 0,
        strategy: str = "",
        task_type: str = "",
        recipe_hash: str | None = None,
    ) -> None:
        self.write(
            TaskStartedEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                total_nodes=total_nodes,
                strategy=strategy,
                task_type=task_type,
                recipe_hash=recipe_hash,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_node_started(
        self,
        task_id: TaskId,
        arm_id: ArmId,
        *,
        actor: str | None = None,
        node_id: str,
        skill_ref: str,
        node_index: int,
    ) -> None:
        self.write(
            NodeStartedEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                node_id=node_id,
                skill_ref=skill_ref,
                node_index=node_index,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_checkpoint(
        self,
        task_id: TaskId,
        *,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        nodes_completed: int,
        total_nodes: int,
        tokens_spent: int = 0,
        usd_spent: float = 0.0,
    ) -> None:
        self.write(
            TaskCheckpointEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                nodes_completed=nodes_completed,
                total_nodes=total_nodes,
                tokens_spent=tokens_spent,
                usd_spent=usd_spent,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_react_checkpoint(
        self,
        task_id: TaskId,
        *,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        iteration_completed: int,
        max_iterations: int,
        messages_snapshot: list[dict[str, Any]],
        steps_snapshot: list[dict[str, Any]],
        has_final_answer: bool = False,
        final_answer: str = "",
        working_set_snapshot: list[dict[str, Any]] | None = None,
        progress_summary: str = "",
        current_phase: str = "",
    ) -> None:
        self.write(
            ReactCheckpointEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                iteration_completed=iteration_completed,
                max_iterations=max_iterations,
                messages_snapshot=messages_snapshot,
                steps_snapshot=steps_snapshot,
                has_final_answer=has_final_answer,
                final_answer=final_answer,
                working_set_snapshot=working_set_snapshot or [],
                progress_summary=progress_summary,
                current_phase=current_phase,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_task_paused(
        self,
        task_id: str,
        *,
        reason: str = "user_request",
        requested_by: str = "",
        iteration: int = 0,
    ) -> None:
        self.write(
            TaskPausedEvent(
                task_id=task_id,
                reason=reason,
                requested_by=requested_by,
                iteration=iteration,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_task_resumed(
        self,
        task_id: str,
        *,
        resumed_by: str = "",
        extra_tokens: int = 0,
        extra_usd: float = 0.0,
        extra_iterations: int = 0,
    ) -> None:
        self.write(
            TaskResumedEvent(
                task_id=task_id,
                resumed_by=resumed_by,
                extra_tokens=extra_tokens,
                extra_usd=extra_usd,
                extra_iterations=extra_iterations,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_token_usage(
        self,
        task_id: str,
        *,
        iteration: int,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        model: str = "",
    ) -> None:
        if input_tokens == 0 and output_tokens == 0:
            return  # Implementation note.
        self.write(
            TokenUsageEvent(
                task_id=task_id,
                iteration=iteration,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
                model=model,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_file_op(
        self,
        *,
        path: str,
        action: str = "write",
        sucker_id: str = "",
        task_id: TaskId | None = None,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        old_size: int | None = None,
        new_size: int | None = None,
        diff: str | None = None,
        rollback: dict[str, Any] | None = None,
    ) -> None:
        delta = 0
        if old_size is not None and new_size is not None:
            delta = new_size - old_size
        elif new_size is not None and action in ("create", "write"):
            delta = new_size
        elif old_size is not None and action == "delete":
            delta = -old_size
        self.write(
            FileOpEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                path=path,
                action=action,  # type: ignore[arg-type]
                old_size=old_size,
                new_size=new_size,
                bytes_delta=delta,
                sucker_id=sucker_id,
                diff=diff,
                rollback=rollback,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_preview_refresh(
        self,
        *,
        target: str = "",
        trigger_path: str = "",
        reason: str = "",
        task_id: TaskId | None = None,
        arm_id: ArmId | None = None,
        actor: str | None = None,
    ) -> None:
        self.write(
            PreviewRefreshEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                target=target,
                trigger_path=trigger_path,
                reason=reason,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_reflex_hit(
        self,
        *,
        task_id: TaskId | None = None,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        rule_id: str,
        kind: str,
        latency_ms: float,
        intent_goal: str,
        response: Any = None,  # noqa: F821
    ) -> None:
        self.write(
            ReflexHitEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                rule_id=rule_id,
                kind=kind,
                latency_ms=latency_ms,
                intent_goal=intent_goal,
                response=response,
            )
        )

    def write_immune(
        self,
        verdict: ImmuneVerdict,
        signature: AntigenSignature,
        task_id: TaskId | None = None,
        arm_id: ArmId | None = None,
        actor: str | None = None,
        reason: str = "",
    ) -> None:
        self.write(
            ImmuneEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                verdict=verdict,
                signature=signature,
                reason=reason,
            )
        )

    def write_budget(
        self,
        event_type: Literal["budget_squirt", "budget_commit"],
        task_id: TaskId,
        *,
        actor: str | None = None,
        reason: str = "",
        cost: CostEntry | None = None,
    ) -> None:
        self.write(
            BudgetEvent(
                event_type=event_type,
                task_id=task_id,
                actor=actor,
                reason=reason,
                cost=cost or CostEntry(),
            )
        )

    def write_budget_breaker_reset(
        self,
        *,
        component: str,
        reason: str = "",
        actor: str | None = None,
    ) -> None:
        self.write(
            BudgetBreakerResetEvent(
                actor=actor,
                component=component,
                reason=reason,
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_skill_proposal_decision(
        self,
        *,
        proposal_name: str,
        decision: str,
        candidate_id: str = "",
        proposal_kind: str = "skill_forge",
        reason: str = "",
        details: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        self.write(
            SkillProposalDecisionEvent(
                actor=actor,
                proposal_kind=proposal_kind,
                proposal_name=proposal_name,
                candidate_id=candidate_id,
                decision=decision,
                reason=reason,
                details=details or {},
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_curriculum_goal_decision(
        self,
        *,
        goal_id: int,
        cluster_key: str,
        status: str,
        covered_by: str | None = None,
        reason: str = "",
        details: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        self.write(
            CurriculumGoalDecisionEvent(
                actor=actor,
                goal_id=goal_id,
                cluster_key=cluster_key,
                status=status,
                covered_by=covered_by,
                reason=reason,
                details=details or {},
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_mcp_proposal_decision(
        self,
        *,
        server_name: str,
        status: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        self.write(
            McpProposalDecisionEvent(
                actor=actor,
                server_name=server_name,
                status=status,
                reason=reason,
                details=details or {},
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )

    def write_protocol_drift_decision(
        self,
        *,
        drift_id: int,
        protocol_id: str,
        status: str,
        reason: str = "",
        details: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> None:
        self.write(
            ProtocolDriftDecisionEvent(
                actor=actor,
                drift_id=drift_id,
                protocol_id=protocol_id,
                status=status,
                reason=reason,
                details=details or {},
                agent_id=current_agent_id(),
                conversation_id=current_conversation_id(),
            )
        )


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class InMemoryJournal(Journal):
    def __init__(self) -> None:
        self._events = AppendOnlyList[JournalEvent](rule_id="CC-5")
        self._lock = Lock()

    @enforces("CC-5")
    def write(self, event: JournalEvent) -> None:
        with self._lock:
            self._events.append(event)

    def read_all(self) -> list[JournalEvent]:
        with self._lock:
            return self._events.snapshot()

    def __len__(self) -> int:
        return len(self._events)


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


class JSONLJournal(Journal):
    def __init__(
        self,
        path: Path | str,
        *,
        max_size_bytes: int | None = None,
        keep_ratio: float = 0.5,
        audit_chain: Any = None,
        redactor: Any = None,
        trace_store: Any = None,
    ) -> None:
        """
        Parameters
        ----------
        path :
            On-disk location for the JSONL file.
        max_size_bytes :
            Optional cap. When the file grows past this, the oldest
            lines are dropped so roughly ``keep_ratio`` of the cap
            worth of most-recent events survive. ``None`` (default)
            disables rotation — the journal grows forever, matching
            older behavior. Recommended ~10-50 MB for a demo setup.
        keep_ratio :
            Fraction of ``max_size_bytes`` retained after a rotation.
            Default 0.5 keeps the last half. Higher = less frequent
            rotation but less headroom before the next one.
        audit_chain :
            Optional ``runtime.safety.audit.audit_chain.AuditChain`` instance.
            When provided, every ``write(event)`` also appends a
            signed record to the chain so tampering with the JSONL
            file (or dropping/reordering lines) is detectable via
            ``audit_chain.verify()``. ``None`` disables audit signing —
            matches the prior default behaviour.
        redactor :
            Optional ``runtime.platform.observability.redactor.Redactor`` instance.
            When provided, the JSON payload is run through
            ``redactor.redact()`` before persistence so accidental
            secrets in tool outputs / args don't land on disk.
            ``None`` (default) disables redaction.
        trace_store :
            Optional ``runtime.memory.diagnostics.trace_store.AgentTraceStore`` sidecar.
            When provided, selected journal events are mirrored into
            SQLite tables for fast audit and recovery queries.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: list[JournalEvent] = []
        self._cache_byte_pos: int = 0
        self._cache_line_count: int = 0
        self._skipped_total: int = 0
        self._skipped_lines: list[dict[str, Any]] = []
        self._pending_tail_bytes: int = 0
        self._max_size_bytes = max_size_bytes
        self._keep_ratio = max(0.1, min(0.9, keep_ratio))
        self._audit_chain = audit_chain
        self._redactor = redactor
        self._trace_store = trace_store

    def attach_trace_store(self, trace_store: Any) -> None:
        """Attach or replace the optional SQLite trace sidecar."""
        self._trace_store = trace_store

    @contextlib.contextmanager
    def _interprocess_lock(self) -> Any:
        """Exclusive cross-process lock on a STABLE sidecar (``<path>.lock``),
        held across BOTH the append and the rotation below.

        Rotation does a ``tmp.replace`` rename, which swaps the journal inode —
        so a per-fd ``flock`` on the journal file itself cannot serialise a
        concurrent worker's append against a rename (the appender ends up
        writing the orphaned inode and its events are lost under
        ``uvicorn --workers N``). Locking a sidecar that is never renamed gives
        every writer a single, stable mutex. Best-effort: degrades to the
        process-internal ``self._lock`` the caller already holds when
        ``fcntl``/``msvcrt`` aren't importable (e.g. a WASM build)."""
        import os as _os

        lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        try:
            lock_file = lock_path.open("a")
        except OSError:
            yield
            return
        fd = lock_file.fileno()
        locked = False
        try:
            try:
                if _os.name == "nt":
                    import msvcrt as _msvcrt

                    _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                    locked = True
                else:
                    import fcntl as _fcntl

                    _fcntl.flock(fd, _fcntl.LOCK_EX)
                    locked = True
            except (OSError, ImportError):
                locked = False
            yield
        finally:
            if locked:
                try:
                    if _os.name == "nt":
                        import msvcrt as _msvcrt

                        with contextlib.suppress(OSError):
                            lock_file.seek(0)
                        _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl as _fcntl

                        _fcntl.flock(fd, _fcntl.LOCK_UN)
                except OSError:
                    pass
            with contextlib.suppress(OSError):
                lock_file.close()

    @enforces("CC-5")
    def write(self, event: JournalEvent) -> None:
        line = event.model_dump_json()
        # Optional secret/PII scrubbing. Done on the serialised JSON
        # string so we cover every nested ``output`` / ``args`` field
        # without having to walk the Pydantic model. Best-effort: a
        # broken redactor must not block journaling.
        if self._redactor is not None:
            with contextlib.suppress(Exception):
                line = self._redactor.redact(line)
        line = line + "\n"
        with self._lock, self._interprocess_lock():
            # Cross-process lock. ``self._lock`` only serialises writers
            # inside this Python process — with ``uvicorn --workers N``
            # two processes can interleave ``write`` + ``flush`` cycles.
            # POSIX ``O_APPEND`` is atomic only for writes ≤ PIPE_BUF
            # (~4 KB); trajectory dumps routinely blow past that. On
            # Windows ``"a"`` mode is never atomic across processes.
            # Wrap the actual ``write/flush`` in an OS-level file lock
            # keyed on the journal path so one writer at a time touches
            # the JSONL. Falls back silently when ``fcntl``/``msvcrt``
            # aren't importable (e.g. WASM build).
            import os as _os

            with self._path.open("a", encoding="utf-8") as f:
                fd = f.fileno()
                _locked = False
                try:
                    if _os.name == "nt":
                        try:
                            import msvcrt as _msvcrt

                            # LK_LOCK: block up to ~10s per attempt, retry
                            # a few times. LK_LOCK retries internally, so
                            # a single call is enough in practice.
                            _msvcrt.locking(fd, _msvcrt.LK_LOCK, 1)
                            _locked = True
                        except OSError:
                            _locked = False
                    else:
                        try:
                            import fcntl as _fcntl

                            _fcntl.flock(fd, _fcntl.LOCK_EX)
                            _locked = True
                        except (OSError, ImportError):
                            _locked = False
                    # Seek to end: another process may have extended the
                    # file since our ``open("a")`` computed the cursor.
                    try:  # noqa: SIM105
                        f.seek(0, 2)
                    except OSError:  # noqa: BLE001 — seek-to-end best-effort; writes still append
                        pass
                    f.write(line)
                    f.flush()
                    try:  # noqa: SIM105
                        _os.fsync(fd)
                    except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                        pass
                finally:
                    if _locked:
                        try:
                            if _os.name == "nt":
                                import msvcrt as _msvcrt

                                # Seek back to the lock byte before unlocking.
                                try:  # noqa: SIM105
                                    f.seek(0, 0)
                                except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                                    pass
                                _msvcrt.locking(fd, _msvcrt.LK_UNLCK, 1)
                            else:
                                import fcntl as _fcntl

                                _fcntl.flock(fd, _fcntl.LOCK_UN)
                        except OSError:  # noqa: BLE001 — file lock/seek/fsync best-effort
                            pass
            # Mirror the event into the audit chain. Best-effort —
            # an audit-chain write failure must NOT take down the
            # journal write path (which is on every step).
            if self._audit_chain is not None:
                try:
                    self._audit_chain.append(
                        kind=type(event).__name__,
                        payload={
                            "event_type": getattr(event, "event_type", None),
                            "ts": (
                                event.ts.isoformat()
                                if hasattr(event, "ts") and event.ts is not None
                                else None
                            ),
                        },
                    )
                except Exception:  # noqa: BLE001 — audit mirror is best-effort; never break the hot write path
                    import logging

                    logging.getLogger(__name__).warning(
                        "journal %s: audit chain append failed",
                        self._path,
                    )
            # Rotate if we've blown past the cap. Cheap check (stat
            # call) · only triggers rewrite when actually needed.
            if self._max_size_bytes is not None:
                try:
                    size = self._path.stat().st_size
                except OSError:
                    return
                if size > self._max_size_bytes:
                    self._rotate_locked()
        self._mirror_trace_event(event)

    def _mirror_trace_event(self, event: JournalEvent) -> None:
        if self._trace_store is None:
            return
        try:
            payload = event.model_dump(mode="json")
            task_id = str(event.task_id) if event.task_id is not None else None
            thread_id = str(event.conversation_id or "") or None
            agent_id = str(event.agent_id or "") or None
            ts = event.ts.isoformat() if event.ts is not None else None
            self._trace_store.record_event(
                event_type=str(event.event_type),
                payload=payload,
                thread_id=thread_id,
                task_id=task_id,
                agent_id=agent_id,
                ts=ts,
            )
            if isinstance(event, TokenUsageEvent):
                self._trace_store.record_token_usage(
                    task_id=task_id,
                    thread_id=thread_id,
                    agent_id=agent_id,
                    iteration=event.iteration,
                    model=event.model,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    cost_usd=event.cost_usd,
                    ts=ts,
                )
            elif isinstance(event, ReactCheckpointEvent):
                self._trace_store.record_checkpoint(
                    task_id=str(event.task_id or ""),
                    thread_id=thread_id,
                    agent_id=agent_id,
                    checkpoint_type="react",
                    iteration=event.iteration_completed,
                    summary=event.progress_summary,
                    state={
                        "iteration_completed": event.iteration_completed,
                        "max_iterations": event.max_iterations,
                        "messages_snapshot": event.messages_snapshot,
                        "steps_snapshot": event.steps_snapshot,
                        "has_final_answer": event.has_final_answer,
                        "final_answer": event.final_answer,
                        "working_set_snapshot": event.working_set_snapshot,
                        "progress_summary": event.progress_summary,
                        "current_phase": event.current_phase,
                    },
                    ts=ts,
                )
            elif isinstance(event, TaskCheckpointEvent):
                self._trace_store.record_checkpoint(
                    task_id=str(event.task_id or ""),
                    thread_id=thread_id,
                    agent_id=agent_id,
                    checkpoint_type="task",
                    iteration=event.nodes_completed,
                    summary=f"{event.nodes_completed}/{event.total_nodes} nodes",
                    state={
                        "nodes_completed": event.nodes_completed,
                        "total_nodes": event.total_nodes,
                        "tokens_spent": event.tokens_spent,
                        "usd_spent": event.usd_spent,
                    },
                    ts=ts,
                )
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug(
                "journal %s: trace mirror failed",
                self._path,
                exc_info=True,
            )

    def _rotate_locked(self) -> None:
        """Trim the file to the last ``keep_ratio * max_size_bytes``
        from the tail (so the most-recent events survive). Caller must
        hold ``self._lock``. Invalidates the incremental read cache
        because byte offsets shift.
        """
        if self._max_size_bytes is None:
            return
        keep_bytes = int(self._max_size_bytes * self._keep_ratio)
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        if size <= keep_bytes:
            return
        # Read tail + find next newline so we start at a clean line boundary.
        seek_to = size - keep_bytes
        with self._path.open("rb") as f:
            f.seek(seek_to)
            # Skip partial first line
            chunk = f.read()
        nl_idx = chunk.find(b"\n")
        if nl_idx == -1:
            import logging

            logging.getLogger(__name__).warning(
                "journal %s: rotate skipped · no newline in tail",
                self._path,
            )
            return
        tail = chunk[nl_idx + 1 :]
        # Atomic replace: write to .tmp then rename.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(tail)
        tmp.replace(self._path)
        # Invalidate cache · next read_all() reparses from scratch.
        self._cache = []
        self._cache_byte_pos = 0
        self._cache_line_count = 0
        self._skipped_total = 0
        self._skipped_lines = []
        self._pending_tail_bytes = 0
        import logging

        logging.getLogger(__name__).info(
            "journal %s rotated · kept tail %d bytes (was %d)",
            self._path,
            len(tail),
            size,
        )

    def read_all(self) -> list[JournalEvent]:
        with self._lock:
            if not self._path.exists():
                # File gone entirely → reset cache (a fresh file may
                # appear later and we want to parse it from scratch).
                self._cache = []
                self._cache_byte_pos = 0
                self._cache_line_count = 0
                self._skipped_total = 0
                self._skipped_lines = []
                self._pending_tail_bytes = 0
                return []

            file_size = self._path.stat().st_size
            if file_size == self._cache_byte_pos:
                # Nothing new — hand back cached list (shallow copy so
                # caller mutations don't poison the cache).
                return list(self._cache)
            if file_size < self._cache_byte_pos:
                # File shrank (manual truncate / rotation) → invalidate.
                self._cache = []
                self._cache_byte_pos = 0
                self._cache_line_count = 0
                self._skipped_total = 0
                self._skipped_lines = []
                self._pending_tail_bytes = 0

            # Read only the tail that's new since last parse. Using
            # binary mode + seek avoids decoder issues when a multi-byte
            # char straddles a read boundary — we read to the current
            # end-of-file which always aligns to a line boundary in
            # append-only usage.
            with self._path.open("rb") as f:
                f.seek(self._cache_byte_pos)
                new_bytes = f.read()
            parse_bytes = new_bytes
            if new_bytes and not new_bytes.endswith(b"\n"):
                last_newline = new_bytes.rfind(b"\n")
                if last_newline < 0:
                    self._pending_tail_bytes = len(new_bytes)
                    return list(self._cache)
                parse_bytes = new_bytes[: last_newline + 1]
                self._pending_tail_bytes = len(new_bytes) - len(parse_bytes)
            else:
                self._pending_tail_bytes = 0
            new_pos = self._cache_byte_pos + len(parse_bytes)

            byte_offset = self._cache_byte_pos
            for raw_bytes in parse_bytes.splitlines(keepends=True):
                self._cache_line_count += 1
                line_byte_offset = byte_offset
                byte_offset += len(raw_bytes)
                raw = raw_bytes.decode("utf-8", errors="replace")
                line = raw.strip()
                if not line:
                    continue
                try:
                    self._cache.append(_parse_event(line))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    self._skipped_total += 1
                    skipped = {
                        "line_number": self._cache_line_count,
                        "byte_offset": line_byte_offset,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:240],
                    }
                    self._skipped_lines.append(skipped)
                    self._skipped_lines = self._skipped_lines[-20:]
                    if self._skipped_total == 1:
                        import logging

                        logging.getLogger(__name__).warning(
                            "journal %s: unparseable event %s at "
                            "line %d byte ~%d · skipping corrupted line and "
                            "continuing with subsequent events",
                            self._path,
                            type(exc).__name__,
                            self._cache_line_count,
                            line_byte_offset,
                        )
            self._cache_byte_pos = new_pos
            return list(self._cache)

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": "octopus.journal_diagnostics.v1",
                "path": str(self._path),
                "parsed_events": len(self._cache),
                "cache_byte_pos": self._cache_byte_pos,
                "parsed_line_count": self._cache_line_count,
                "skipped_total": self._skipped_total,
                "skipped_lines": list(self._skipped_lines),
                "pending_tail_bytes": self._pending_tail_bytes,
            }

    def __len__(self) -> int:
        if not self._path.exists():
            return 0
        with self._path.open("r", encoding="utf-8") as f:
            return sum(1 for _ in f)


# ═══════════════════════════════════════════════════════════
# Helpers · event parsing + schema migration
# ═══════════════════════════════════════════════════════════


_EVENT_CLASSES: dict[str, type[JournalEvent]] = {
    "step": StepEvent,
    "trajectory": TrajectoryEvent,
    "immune": ImmuneEvent,
    "budget_squirt": BudgetEvent,
    "budget_commit": BudgetEvent,
    "budget_breaker_reset": BudgetBreakerResetEvent,
    "task_started": TaskStartedEvent,
    "node_started": NodeStartedEvent,
    "task_checkpoint": TaskCheckpointEvent,
    "react_checkpoint": ReactCheckpointEvent,
    "task_paused": TaskPausedEvent,
    "task_resumed": TaskResumedEvent,
    "token_usage": TokenUsageEvent,
    "reflex_hit": ReflexHitEvent,
    "file_op": FileOpEvent,
    "preview_refresh": PreviewRefreshEvent,
    "skill_proposal_decision": SkillProposalDecisionEvent,
    "curriculum_goal_decision": CurriculumGoalDecisionEvent,
    "mcp_proposal_decision": McpProposalDecisionEvent,
    "protocol_drift_decision": ProtocolDriftDecisionEvent,
    "file_rollback": FileRollbackEvent,
    "sub_tool_start": SubToolStartEvent,
    "sub_tool_end": SubToolEndEvent,
    "browser_artifact": BrowserArtifactEvent,
}


# Migrations · key = schema_version the event was written at;
# value = function that mutates the dict in place, moving it ONE version
# forward. For an event at v1, chain: v1 → v2 → v3 → ... → CURRENT.
# Today there's no v2 yet — so this dict is empty. When we add v2,
# register `_EVENT_MIGRATIONS[1] = migrate_v1_to_v2`.
_EVENT_MIGRATIONS: dict[int, Any] = {}


def _migrate_event(data: dict) -> dict:
    """Walk ``data`` forward through ``_EVENT_MIGRATIONS`` until it's at
    ``CURRENT_SCHEMA_VERSION``. Events without a version field are
    assumed to be v1 (the version this mechanism was introduced at).
    """
    version = int(data.get("schema_version") or 1)
    while version < CURRENT_SCHEMA_VERSION:
        migrator = _EVENT_MIGRATIONS.get(version)
        if migrator is None:
            # No migration path — write through the current version
            # and let pydantic decide if it still validates.
            break
        data = migrator(data)
        version += 1
    data["schema_version"] = version
    return data


def _parse_event(line: str) -> JournalEvent:
    data = json.loads(line)
    data = _migrate_event(data)
    event_type = data.get("event_type")
    cls = _EVENT_CLASSES.get(event_type, JournalEvent)
    return cls.model_validate(data)
