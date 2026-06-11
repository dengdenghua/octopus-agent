/**
 * Adapter that turns the shared `core/parallel-agents` backend contract into
 * the `SwarmSession` shape consumed by the Kimi-style workbench UI. Holds no
 * types or fetchers of its own — just mapping logic.
 */
import {
  fetchFocusBatch,
  type BatchResult,
  type BatchStreamEvent,
  type TaskResult,
} from "@/core/parallel-agents/api";

import type {
  AgentHandoff,
  AgentStatus,
  DeliverableFile,
  SwarmPhaseReport,
  SwarmPlan,
  SwarmAgent,
  SwarmSession,
  TraceEntry,
} from "./types";

function mapStatus(raw: string): AgentStatus {
  switch (raw) {
    case "completed":
    case "partial":
    case "failed":
    case "cancelled":
    case "timed_out":
      return "done"; // terminal states collapse to "done" for UI purposes
    case "pending":
      return "pending";
    case "running":
      return "reasoning";
    default:
      return "reasoning";
  }
}

// Deterministic hue per subagent name so the same agent keeps its color.
function hashHue(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h) % 360;
}

const ROLE_EMOJI: Record<string, string> = {
  researcher: "🔍",
  writer: "✍️",
  coder: "💻",
  reviewer: "🧐",
  analyst: "📊",
  tester: "🧪",
};

function guessEmoji(name: string): string {
  const lower = name.toLowerCase();
  for (const [k, v] of Object.entries(ROLE_EMOJI)) {
    if (lower.includes(k)) return v;
  }
  return "🤖";
}

function taskToAgent(task: TaskResult, index: number): SwarmAgent {
  const name = task.subagent_name;
  let progress = 0;
  if (task.status === "running") progress = 0.5;
  else if (task.completed_at) progress = 1;
  return {
    id: task.task_id,
    index: index + 1,
    name,
    role: name,
    motto: "",
    avatarEmoji: guessEmoji(name),
    hue: hashHue(name),
    skills: [],
    // Short `task` for pill / dispatch card; full content lives in `result`.
    task: task.result ? task.result.slice(0, 120) : name,
    status: mapStatus(task.status),
    progress,
    details: task.error ? [`错误: ${task.error}`] : undefined,
    result: task.result ?? undefined,
    error: task.error ?? undefined,
    durationSeconds: task.duration_seconds ?? undefined,
  };
}

function mapPlan(batch: BatchResult): SwarmPlan | undefined {
  if (!batch.plan) return undefined;
  return {
    batchId: batch.plan.batch_id,
    strategy: batch.plan.strategy,
    maxConcurrency: batch.plan.max_concurrency,
    phases: batch.plan.phases.map((phase) => ({
      phaseIndex: phase.phase_index,
      taskIds: phase.task_ids,
      parallel: phase.parallel,
    })),
    contracts: batch.plan.contracts.map((contract) => ({
      contractId: contract.contract_id,
      agentId: contract.agent_id,
      role: contract.role,
      taskIds: contract.task_ids,
      dependsOn: contract.depends_on,
      ownedScope: contract.owned_scope,
      forbiddenScope: contract.forbidden_scope,
      successCriteria: contract.success_criteria,
    })),
  };
}

function extractDeliverables(batch: BatchResult): DeliverableFile[] {
  if (!batch.aggregated_content) return [];
  const files: DeliverableFile[] = [];
  const pathRe = /(?:\/[\w.-]+)+\.\w+/g;
  const matches = batch.aggregated_content.match(pathRe) ?? [];
  const byOwner = batch.results.map((r) => r.task_id);
  for (const p of new Set(matches)) {
    files.push({
      name: p.split(/[/\\]/).pop() ?? p,
      path: p,
      ownerAgentIds: byOwner,
    });
  }
  return files;
}

function mapHandoffs(batch: BatchResult): AgentHandoff[] {
  return batch.results.map((task) => ({
    agentId: task.subagent_name,
    taskId: task.task_id,
    phaseIndex: findTaskPhase(batch, task.task_id),
    nodeIds: [task.task_id],
    status: task.status,
    summary: task.result ?? task.error ?? "",
    artifacts: extractTaskArtifacts(task.result ?? ""),
    costUsd: 0,
    reason: task.error ?? undefined,
  }));
}

function mapPhaseReports(batch: BatchResult): SwarmPhaseReport[] {
  if (!batch.plan) return [];
  return batch.plan.phases.map((phase) => {
    const phaseTasks = batch.results.filter((task) =>
      phase.task_ids.includes(task.task_id),
    );
    const succeeded = phaseTasks.filter((task) => task.status === "completed").length;
    const failed = phaseTasks.filter((task) => task.status === "failed").length;
    const status =
      phaseTasks.length === 0
        ? "empty"
        : succeeded === phaseTasks.length
          ? "success"
          : succeeded === 0 && failed > 0
            ? "failed"
            : "partial";
    return {
      phaseIndex: phase.phase_index,
      nodeIds: [...phase.task_ids],
      assignmentCount: phase.task_ids.length,
      handoffCount: phaseTasks.length,
      succeeded,
      failed,
      status,
      wallMs: phaseTasks.reduce(
        (total, task) => total + ((task.duration_seconds ?? 0) * 1000),
        0,
      ),
      costUsd: 0,
    };
  });
}

function findTaskPhase(batch: BatchResult, taskId: string): number {
  const phase = batch.plan?.phases.find((candidate) =>
    candidate.task_ids.includes(taskId),
  );
  return phase?.phase_index ?? 0;
}

function extractTaskArtifacts(text: string): string[] {
  const pathRe = /(?:\/[\w.-]+)+\.\w+/g;
  return [...new Set(text.match(pathRe) ?? [])];
}

function eventTimestamp(event: BatchStreamEvent, index: number): number {
  if (event.created_at) {
    const parsed = Date.parse(event.created_at);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Date.now() + index;
}

function eventSequence(event: BatchStreamEvent, index: number): number {
  return typeof event.sequence === "number" ? event.sequence : index + 1;
}

function eventToTrace(event: BatchStreamEvent, index: number): TraceEntry {
  const baseTs = eventTimestamp(event, index);
  const sequence = eventSequence(event, index);
  if (event.type === "stage_change") {
    return {
      id: `replay-stage-${sequence}`,
      agentId: "__stage__",
      timestamp: baseTs,
      kind: event.stage === "final_report" ? "write" : "think",
      title: event.message ?? event.stage ?? "Workflow update",
      detail: event.stage,
      sequence,
      status: event.status,
    };
  }
  if (event.type === "tool_call") {
    return {
      id: `replay-tool-${event.task_id ?? "agent"}-${sequence}`,
      agentId: event.task_id ?? event.subagent_name ?? "agent",
      timestamp: baseTs,
      kind: "tool",
      title: event.tool_name
        ? `Tool: ${event.tool_name}`
        : event.message ?? "Tool call",
      detail: event.tool_output_preview ?? event.tool_input_preview ?? event.message,
      sequence,
      toolName: event.tool_name,
      inputPreview: event.tool_input_preview,
      outputPreview: event.tool_output_preview,
      artifactPaths: event.artifact_paths,
      status: event.status,
    };
  }
  if (event.type === "task_update") {
    const terminal = ["completed", "failed", "cancelled", "timed_out"].includes(
      event.status ?? "",
    );
    return {
      id: `replay-task-${event.task_id ?? index}-${sequence}`,
      agentId: event.task_id ?? event.subagent_name ?? "agent",
      timestamp: baseTs,
      kind: terminal ? "write" : event.phase === "started" ? "think" : "tool",
      title: event.subagent_name
        ? `${event.subagent_name}: ${event.status ?? event.phase ?? "update"}`
        : event.message ?? "Agent update",
      detail: event.result_preview ?? event.error ?? event.description ?? event.message,
      sequence,
      status: event.status,
    };
  }
  return {
    id: `replay-complete-${sequence}`,
    agentId: "__stage__",
    timestamp: baseTs,
    kind: "write",
    title: "Batch complete",
    detail: event.status,
    sequence,
    status: event.status,
  };
}

function mapReplayTrace(batch: BatchResult): TraceEntry[] {
  if (!batch.event_log?.length) return [];
  return batch.event_log
    .map(eventToTrace)
    .sort((a, b) => (a.sequence ?? 0) - (b.sequence ?? 0));
}

export function batchToSession(
  batch: BatchResult,
  title?: string,
): SwarmSession {
  return {
    id: batch.batch_id,
    title: title ?? `Batch ${batch.batch_id.slice(0, 8)}`,
    status: batch.status === "running" ? "running" : "done",
    mode: batch.status === "running" ? "live" : "result",
    agents: batch.results.map(taskToAgent),
    trace: mapReplayTrace(batch),
    deliverables: extractDeliverables(batch),
    handoffs: mapHandoffs(batch),
    phaseReports: mapPhaseReports(batch),
    workflow: {
      stage: batch.completed_at ? "final_report" : undefined,
      status: batch.status,
      progress: batch.total_tasks > 0
        ? (batch.completed_tasks + batch.failed_tasks + batch.cancelled_tasks) /
          batch.total_tasks
        : undefined,
      totalTasks: batch.total_tasks,
      completedTasks: batch.completed_tasks,
      failedTasks: batch.failed_tasks,
      cancelledTasks: batch.cancelled_tasks,
      updatedAt: Date.now(),
    },
    plan: mapPlan(batch),
    summary: batch.aggregated_content ?? undefined,
    sourcePrompt: batch.results.map((task) => task.description).filter(Boolean).join("\n\n"),
  };
}

/**
 * High-level helper used by the workbench: one call returns the session for
 * the orchestrator's current focus batch, or null if nothing is available.
 */
export async function fetchFirstRunningSession(): Promise<SwarmSession | null> {
  const batch = await fetchFocusBatch();
  return batch ? batchToSession(batch) : null;
}
