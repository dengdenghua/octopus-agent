import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

export interface AgentTraceTokenTotals {
  input_tokens: number;
  output_tokens: number;
  thinking_tokens: number;
  cached_tokens: number;
  cost_usd: number;
}

export interface AgentTraceStats {
  messages: number;
  events: number;
  approvals: number;
  checkpoints: number;
  resume_requests?: number;
  token_usage: number;
  token_totals: AgentTraceTokenTotals;
}

export interface AgentTraceEvent {
  id: number;
  ts: string;
  thread_id?: string | null;
  turn_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  item_id?: string | null;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface AgentTraceApproval {
  id: number;
  requested_at: string;
  decided_at?: string | null;
  thread_id?: string | null;
  turn_id?: string | null;
  task_id?: string | null;
  agent_id?: string | null;
  tool_name: string;
  tool_call_id: string;
  args_preview: string;
  decision: string;
  reason: string;
  metadata: Record<string, unknown>;
}

export interface AgentTraceCheckpoint {
  id: number;
  ts: string;
  task_id: string;
  thread_id?: string | null;
  turn_id?: string | null;
  agent_id?: string | null;
  checkpoint_type: string;
  iteration: number;
  summary: string;
  state: Record<string, unknown>;
}

export interface AgentTraceResumeProposal {
  checkpoint: {
    id: number;
    task_id?: string;
    taskId?: string;
    thread_id?: string | null;
    agent_id?: string | null;
    type: string;
    iteration: number;
    timestamp: string;
  };
  recovery_hints?: {
    phase: string | null;
    progress: string | null;
    message_count: number;
    step_count: number;
    working_set: string[];
  };
  recoveryHints?: {
    phase: string | null;
    progress: string | null;
    messageCount: number;
    stepCount: number;
    workingSet: string[];
  };
  resume_plan?: {
    title: string;
    steps: string[];
  };
  resumePlan?: {
    title: string;
    steps: string[];
  };
  safety: {
    raw_state_included?: boolean;
    raw_message_snapshots_included?: boolean;
    rawStateIncluded?: boolean;
    rawMessageSnapshotsIncluded?: boolean;
  };
}

export interface AgentTraceResumeRequest {
  id: number;
  ts: string;
  thread_id: string;
  checkpoint_id: number;
  task_id?: string | null;
  status: "pending" | "confirmed" | "consumed" | string;
  intent: {
    schema?: string;
    requires_confirmation?: boolean;
    confirmed?: boolean;
    source?: string;
    checkpoint_id?: number;
    task_id?: string | null;
    checkpoint_type?: string;
    iteration?: number;
    continue_from_iteration?: number;
    phase?: string | null;
    working_set?: string[];
    safety?: {
      raw_state_included?: boolean;
      raw_message_snapshots_included?: boolean;
    };
  };
  confirmed_at?: string | null;
  consumed_at?: string | null;
}

export interface AgentTraceTaskRun {
  task_id: string;
  thread_id?: string | null;
  turn_id?: string | null;
  agent_id?: string | null;
  title?: string | null;
  mode?: string | null;
  status?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
  summary?: string | null;
  tool_calls_started?: number;
  tool_calls_finished?: number;
  tool_errors?: number;
  tool_names?: string[];
  token_totals?: Partial<AgentTraceTokenTotals>;
}

export interface AgentTraceProcessTimelineNode {
  id?: string;
  lane: string;
  kind: string;
  ts?: string | null;
  title?: string;
  text?: string;
  severity?: string;
  status?: string;
  tool?: string;
  metadata?: Record<string, unknown>;
}

export interface AgentTraceProcessTimeline {
  schema: string;
  task_id: string;
  overview: {
    status?: string | null;
    score?: number | null;
    approval_count?: number;
    experience_record_count?: number;
    tool_error_count?: number;
    [key: string]: unknown;
  };
  timeline: AgentTraceProcessTimelineNode[];
  capabilities?: Array<Record<string, unknown>>;
  safety?: Record<string, unknown>;
}

export type AgentTraceReviewQueueStatus =
  | "pending"
  | "promoted"
  | "rejected"
  | "archived"
  | string;

export interface AgentTraceReviewQueueItem {
  id: string;
  created_at?: string;
  updated_at?: string;
  decided_at?: string;
  source: string;
  source_kind: string;
  candidate_kind: string;
  priority: "P0" | "P1" | "P2" | string;
  target_bucket: string;
  title: string;
  text: string;
  status: AgentTraceReviewQueueStatus;
  decision_reason?: string;
  promoted_to?: string;
  occurrences: number;
  last_seen_at?: string;
  source_task_ids?: string[];
  thread_ids?: string[];
  turn_ids?: string[];
  agent_ids?: string[];
  tags?: string[];
  metadata?: Record<string, unknown>;
  source_hash?: string;
}

export interface AgentTraceReviewQueueSummary {
  schema: string;
  total: number;
  pending_count: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_target_bucket: Record<string, number>;
  next_actions: Array<{
    priority: string;
    item_id: string;
    target_bucket: string;
    action: string;
  }>;
}

export interface AgentTracePromotionApplyResult {
  schema: string;
  dry_run: boolean;
  applied: number;
  failed: number;
  skipped: number;
  results: Array<Record<string, unknown>>;
}

export interface AgentTraceScope {
  threadId?: string | null;
  taskId?: string | null;
  agentId?: string | null;
  turnId?: string | null;
}

function appendScope(params: URLSearchParams, scope?: AgentTraceScope) {
  if (scope?.threadId) params.set("thread_id", scope.threadId);
  if (scope?.taskId) params.set("task_id", scope.taskId);
  if (scope?.agentId) params.set("agent_id", scope.agentId);
  if (scope?.turnId) params.set("turn_id", scope.turnId);
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${getBackendBaseURL()}${path}`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Agent trace request failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${getBackendBaseURL()}${path}`, {
    method: "POST",
    headers: {
      ...authHeaders(),
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`Agent trace request failed: ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function fetchAgentTraceStats(
  scope?: AgentTraceScope,
): Promise<AgentTraceStats> {
  const params = new URLSearchParams();
  appendScope(params, scope);
  const query = params.toString();
  return fetchJson<AgentTraceStats>(
    `/api/agent-trace/stats${query ? `?${query}` : ""}`,
  );
}

export async function fetchAgentTraceEvents(
  limit = 8,
  offset = 0,
  scope?: AgentTraceScope,
): Promise<AgentTraceEvent[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  const data = await fetchJson<{ events: AgentTraceEvent[] }>(
    `/api/agent-trace/events?${params.toString()}`,
  );
  return data.events;
}

export async function fetchAgentTraceTaskRuns(
  limit = 8,
  offset = 0,
  scope?: AgentTraceScope,
  status?: string,
): Promise<AgentTraceTaskRun[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  if (status) params.set("status", status);
  const data = await fetchJson<{ task_runs: AgentTraceTaskRun[] }>(
    `/api/agent-trace/task-runs?${params.toString()}`,
  );
  return data.task_runs;
}

export async function fetchAgentTraceProcessTimeline(
  taskId: string,
): Promise<AgentTraceProcessTimeline> {
  const data = await fetchJson<{ timeline: AgentTraceProcessTimeline }>(
    `/api/agent-trace/task-runs/${encodeURIComponent(taskId)}/process-timeline`,
  );
  return data.timeline;
}

export async function queueAgentTraceTaskRunReview(
  taskId: string,
): Promise<{
  created: number;
  updated: number;
  total: number;
  items: AgentTraceReviewQueueItem[];
}> {
  const data = await postJson<{
    queue: {
      created: number;
      updated: number;
      total: number;
      items: AgentTraceReviewQueueItem[];
    };
  }>(
    `/api/agent-trace/task-runs/${encodeURIComponent(taskId)}/review/queue`,
  );
  return data.queue;
}

export async function fetchAgentTraceReviewQueue(
  limit = 12,
  offset = 0,
  filters?: {
    status?: string;
    targetBucket?: string;
    priority?: string;
    sourceTaskId?: string;
  },
): Promise<AgentTraceReviewQueueItem[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  if (filters?.status) params.set("status", filters.status);
  if (filters?.targetBucket) params.set("target_bucket", filters.targetBucket);
  if (filters?.priority) params.set("priority", filters.priority);
  if (filters?.sourceTaskId) params.set("source_task_id", filters.sourceTaskId);
  const data = await fetchJson<{ items: AgentTraceReviewQueueItem[] }>(
    `/api/agent-trace/review-queue?${params.toString()}`,
  );
  return data.items;
}

export async function fetchAgentTraceReviewQueueSummary(): Promise<AgentTraceReviewQueueSummary> {
  return fetchJson<AgentTraceReviewQueueSummary>(
    "/api/agent-trace/review-queue/summary",
  );
}

export async function decideAgentTraceReviewQueueItem(
  itemId: string,
  decision: {
    action: "promoted" | "rejected" | "archived";
    reason?: string;
    promotedTo?: string;
  },
): Promise<AgentTraceReviewQueueItem> {
  const data = await postJson<{ item: AgentTraceReviewQueueItem }>(
    `/api/agent-trace/review-queue/${encodeURIComponent(itemId)}/decision`,
    {
      action: decision.action,
      reason: decision.reason ?? "",
      promoted_to: decision.promotedTo,
    },
  );
  return data.item;
}

export async function applyAgentTraceReviewQueuePromotions(
  options?: {
    itemId?: string;
    target?: string;
    limit?: number;
  },
): Promise<AgentTracePromotionApplyResult> {
  return postJson<AgentTracePromotionApplyResult>(
    "/api/agent-trace/review-queue/promotions/apply",
    {
      item_id: options?.itemId,
      target: options?.target,
      limit: options?.limit ?? 50,
    },
  );
}

export async function fetchAgentTraceApprovals(
  limit = 5,
  offset = 0,
  scope?: Pick<AgentTraceScope, "threadId" | "turnId">,
): Promise<AgentTraceApproval[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  const data = await fetchJson<{ approvals: AgentTraceApproval[] }>(
    `/api/agent-trace/approvals?${params.toString()}`,
  );
  return data.approvals;
}

export async function fetchAgentTraceCheckpoints(
  limit = 3,
  offset = 0,
  scope?: AgentTraceScope,
): Promise<AgentTraceCheckpoint[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  const data = await fetchJson<{ checkpoints: AgentTraceCheckpoint[] }>(
    `/api/agent-trace/checkpoints?${params.toString()}`,
  );
  return data.checkpoints;
}

export async function fetchAgentTraceResumeProposal(
  checkpointId: number,
): Promise<AgentTraceResumeProposal> {
  const data = await fetchJson<{ proposal: AgentTraceResumeProposal }>(
    `/api/agent-trace/checkpoints/${encodeURIComponent(String(checkpointId))}/resume-proposal`,
  );
  return data.proposal;
}

export async function fetchAgentTraceResumeProposals(
  limit = 3,
  offset = 0,
  scope?: AgentTraceScope,
): Promise<AgentTraceResumeProposal[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  const data = await fetchJson<{ proposals: AgentTraceResumeProposal[] }>(
    `/api/agent-trace/resume-proposals?${params.toString()}`,
  );
  return data.proposals;
}

export async function fetchAgentTraceResumeRequests(
  limit = 5,
  offset = 0,
  scope?: Pick<AgentTraceScope, "threadId">,
  status?: string,
): Promise<AgentTraceResumeRequest[]> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(Math.max(0, offset)),
  });
  appendScope(params, scope);
  if (status) params.set("status", status);
  const data = await fetchJson<{ requests: AgentTraceResumeRequest[] }>(
    `/api/agent-trace/resume-requests?${params.toString()}`,
  );
  return data.requests;
}
