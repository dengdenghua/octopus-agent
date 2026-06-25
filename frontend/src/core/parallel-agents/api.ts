/**
 * Single source of truth for the `/api/agents/parallel/*` backend contract
 * and its fetchers. Previously these types and polling calls were duplicated
 * between `parallel-agents-panel.tsx` (ops monitoring UI) and
 * `swarm/live-driver.ts` (Kimi-style workbench). Both now consume this module.
 */
import { swallow } from "@/core/utils/log";
import { getToken } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

// ---------------------------------------------------------------------------
// Backend shapes
// ---------------------------------------------------------------------------

export type ParallelTaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "partial";

export interface TaskResult {
  task_id: string;
  batch_id: string;
  description?: string | null;
  status: ParallelTaskStatus | string;
  result: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  subagent_name: string;
  work_contract?: WorkContract | null;
}

export interface SubagentRouteDecision {
  schema: "octopus.subagent_route_decision.v1";
  role: string;
  action: "allow" | "allow_with_warning" | "block" | string;
  reason: string;
  risk_level: "low" | "medium" | "high" | "critical" | string;
  verdict: string;
  score: number | null;
  confidence: number;
  evidence_item_ids: string[];
}

export interface WorkContract {
  contract_id: string;
  agent_id: string;
  role: string;
  task_ids: string[];
  depends_on: string[];
  owned_scope: string[];
  forbidden_scope: string[];
  success_criteria: string[];
}

export interface BatchPhase {
  phase_index: number;
  task_ids: string[];
  parallel: boolean;
}

export interface BatchPlan {
  batch_id: string;
  strategy: string;
  max_concurrency: number;
  phases: BatchPhase[];
  contracts: WorkContract[];
}

export interface BatchResult {
  batch_id: string;
  status: ParallelTaskStatus | string;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  cancelled_tasks: number;
  created_at: string | null;
  completed_at: string | null;
  results: TaskResult[];
  aggregated_content: string | null;
  aggregation_strategy: string | null;
  conflicts: string[];
  plan?: BatchPlan | null;
  event_log?: BatchStreamEvent[];
}

export interface OrchestratorStatus {
  active_count: number;
  pending_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  max_concurrency: number;
  batches: Record<string, string>;
}

export interface SplitTask {
  task_id: string;
  description: string;
  subagent_name: string;
  depends_on: string[];
  priority: number;
}

export interface SplitResult {
  tasks: SplitTask[];
  dag_levels: string[][];
  total_levels: number;
  is_parallelizable: boolean;
}

// ---------------------------------------------------------------------------
// Fetchers — return null on network/HTTP failure so callers can degrade
// gracefully instead of tearing down their render tree.
// ---------------------------------------------------------------------------

// Shared fetch options — include cookies for session-based auth and Bearer
// token for token-based auth. Match the rest of the app's auth pattern.
export function toBackendURL(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return `${getBackendBaseURL()}${pathOrUrl}`;
}

async function authedFetch(
  pathOrUrl: string,
  init?: RequestInit,
): Promise<Response> {
  const token = getToken();
  return fetch(toBackendURL(pathOrUrl), {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
}

export async function fetchOrchestratorStatus(): Promise<OrchestratorStatus | null> {
  try {
    const res = await authedFetch("/api/agents/parallel/status");
    if (!res.ok) return null;
    return (await res.json()) as OrchestratorStatus;
  } catch (e) {
    swallow(e);
    return null;
  }
}

export async function fetchBatch(batchId: string): Promise<BatchResult | null> {
  try {
    const res = await authedFetch(`/api/agents/parallel/batch/${batchId}`);
    if (!res.ok) return null;
    return (await res.json()) as BatchResult;
  } catch (e) {
    swallow(e);
    return null;
  }
}

export async function cancelTask(taskId: string): Promise<boolean> {
  try {
    const res = await authedFetch(`/api/agents/parallel/cancel/${taskId}`, {
      method: "POST",
    });
    return res.ok;
  } catch (e) {
    swallow(e);
    return false;
  }
}

export async function cancelAll(): Promise<boolean> {
  try {
    const res = await authedFetch("/api/agents/parallel/cancel-all", {
      method: "POST",
    });
    return res.ok;
  } catch (e) {
    swallow(e);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Status helpers — shared visual language across UIs.
// ---------------------------------------------------------------------------

export const STATUS_TEXT_COLOR: Record<string, string> = {
  pending: "text-muted-foreground",
  running: "text-blue-500",
  completed: "text-green-500",
  failed: "text-red-500",
  cancelled: "text-yellow-500",
  timed_out: "text-orange-500",
  partial: "text-amber-500",
};

export const STATUS_BG: Record<string, string> = {
  pending: "bg-muted/50",
  running: "bg-blue-500/10",
  completed: "bg-green-500/10",
  failed: "bg-red-500/10",
  cancelled: "bg-yellow-500/10",
  timed_out: "bg-orange-500/10",
  partial: "bg-amber-500/10",
};

/**
 * Pick the "most interesting" batch for a surface that shows a single batch.
 * Prefers a running batch; otherwise the first batch entry (typically most
 * recently touched). Returns null if the orchestrator has no batches.
 */
export async function fetchFocusBatch(): Promise<BatchResult | null> {
  const status = await fetchOrchestratorStatus();
  if (!status) return null;
  const running = Object.entries(status.batches).find(
    ([, s]) => s === "running",
  );
  const entry = running ?? Object.entries(status.batches)[0];
  if (!entry) return null;
  return fetchBatch(entry[0]);
}

// ---------------------------------------------------------------------------
// SSE streaming — real-time batch progress via EventSource
// ---------------------------------------------------------------------------

export interface BatchStreamEvent {
  type: "stage_change" | "task_update" | "tool_call" | "batch_complete";
  batch_id: string;
  sequence?: number | null;
  created_at?: string | null;
  task_id?: string;
  lane?: "workflow" | "agent" | "computer" | "timeline";
  status?: string;
  subagent_name?: string;
  phase?: string;
  stage?: string;
  tool_name?: string;
  tool_input_preview?: string;
  tool_output_preview?: string;
  artifact_paths?: string[];
  node_ids?: string[];
  payload?: Record<string, unknown>;
  progress?: number;
  message?: string;
  description?: string;
  result_preview?: string;
  duration_seconds?: number;
  error?: string;
}

/**
 * Callbacks for SSE batch streaming events.
 */
export interface BatchStreamCallbacks {
  onStageChange?: (event: BatchStreamEvent) => void;
  onTaskUpdate?: (event: BatchStreamEvent) => void;
  onBatchComplete?: (event: BatchStreamEvent) => void;
  onError?: (error: Error) => void;
  onReconnecting?: (attempt: number) => void;
}

function streamURL(batchId: string, afterSequence: number): string {
  const base = `/api/agents/parallel/stream/${batchId}`;
  if (afterSequence <= 0) return base;
  return `${base}?after_sequence=${afterSequence}`;
}

/**
 * Subscribe to real-time SSE events for a batch.
 * Returns a cleanup function that closes the EventSource.
 */
/**
 * Subscribe to real-time SSE events for a parallel agent batch.
 *
 * Uses `fetch` + `ReadableStream` (not `EventSource`) to support
 * Bearer token authentication via `authedFetch`.
 *
 * Features:
 * - Automatic exponential backoff reconnection (default 3 retries)
 * - `onReconnecting` callback for UI feedback
 * - Proper SSE event parsing (event type + data)
 * - Cleanup via returned function
 *
 * @param batchId - The batch ID to subscribe to
 * @param callbacks - Event callbacks (onTaskUpdate, onBatchComplete, onError, onReconnecting)
 * @param options - Retry options (maxRetries, baseDelay)
 * @returns Cleanup function that aborts the SSE connection
 */
export function streamBatch(
  batchId: string,
  callbacks: BatchStreamCallbacks,
  options?: { maxRetries?: number; baseDelay?: number },
): () => void {
  const maxRetries = options?.maxRetries ?? 3;
  const baseDelay = options?.baseDelay ?? 1000;
  let aborted = false;
  let retryCount = 0;
  let lastSequence = 0;
  let activeController = new AbortController();

  const connect = async () => {
    while (!aborted && retryCount <= maxRetries) {
      try {
        activeController = new AbortController();
        const res = await authedFetch(streamURL(batchId, lastSequence), {
          signal: activeController.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!res.ok || !res.body) {
          if (!aborted) {
            const err = new Error(`SSE HTTP ${res.status}`);
            if (retryCount < maxRetries) {
              retryCount++;
              callbacks.onReconnecting?.(retryCount);
              await sleep(baseDelay * Math.pow(2, retryCount - 1));
              continue;
            }
            callbacks.onError?.(err);
          }
          return;
        }

        retryCount = 0;

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let eventType = "";
        let eventData = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done || aborted) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              eventData = line.slice(5).trim();
            } else if (line === "") {
              if (eventType && eventData) {
                try {
                  const data = JSON.parse(eventData) as BatchStreamEvent;
                  if (
                    typeof data.sequence === "number" &&
                    data.sequence <= lastSequence
                  ) {
                    eventType = "";
                    eventData = "";
                    continue;
                  }
                  if (typeof data.sequence === "number") {
                    lastSequence = data.sequence;
                  }
                  if (eventType === "stage_change") {
                    callbacks.onStageChange?.(data);
                  } else if (eventType === "task_update") {
                    callbacks.onTaskUpdate?.(data);
                  } else if (eventType === "tool_call") {
                    callbacks.onTaskUpdate?.(data);
                  } else if (eventType === "batch_complete") {
                    callbacks.onBatchComplete?.(data);
                    return;
                  }
                } catch (e) {
                  swallow(e);
                }
              }
              eventType = "";
              eventData = "";
            }
          }
        }

        if (!aborted && retryCount < maxRetries) {
          retryCount++;
          callbacks.onReconnecting?.(retryCount);
          await sleep(baseDelay * Math.pow(2, retryCount - 1));
        }
      } catch (err) {
        swallow(err);
        if (aborted) return;
        if (retryCount < maxRetries) {
          retryCount++;
          callbacks.onReconnecting?.(retryCount);
          await sleep(baseDelay * Math.pow(2, retryCount - 1));
        } else {
          callbacks.onError?.(
            err instanceof Error ? err : new Error("SSE max retries exceeded"),
          );
          return;
        }
      }
    }
  };

  void connect();

  return () => {
    aborted = true;
    activeController.abort();
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface DispatchTaskInput {
  description: string;
  subagent_name?: string;
  task_id?: string;
  depends_on?: string[];
  priority?: number;
}

/**
 * Dispatch either a single prompt (wrapped as one task) or a pre-split
 * list of subtasks. When the backend's `/split` step has already produced
 * subtasks, pass them directly.
 */
export async function dispatchParallel(
  tasksOrPrompt: string | DispatchTaskInput[],
  options?: {
    subagent_name?: string;
    max_concurrency?: number;
    aggregation_strategy?: string;
    execution_mode?: string;
    thread_id?: string;
    model_name?: string;
  },
): Promise<BatchResult | null> {
  const tasks: DispatchTaskInput[] =
    typeof tasksOrPrompt === "string"
      ? [
          {
            description: tasksOrPrompt,
            subagent_name: options?.subagent_name ?? "general-purpose",
          },
        ]
      : tasksOrPrompt;
  try {
    const res = await authedFetch("/api/agents/parallel/dispatch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tasks,
        max_concurrency: options?.max_concurrency,
        aggregation_strategy: options?.aggregation_strategy,
        execution_mode: options?.execution_mode,
        thread_id: options?.thread_id,
        model_name: options?.model_name,
      }),
    });
    if (!res.ok) return null;
    return (await res.json()) as BatchResult;
  } catch (e) {
    swallow(e);
    return null;
  }
}

export async function splitTask(
  prompt: string,
  options?: {
    max_subtasks?: number;
    context?: string;
    model_name?: string;
  },
): Promise<SplitResult | null> {
  try {
    const res = await authedFetch("/api/agents/parallel/split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task: prompt,
        max_subtasks: options?.max_subtasks,
        context: options?.context,
        model_name: options?.model_name,
      }),
    });
    if (!res.ok) return null;
    return (await res.json()) as SplitResult;
  } catch (e) {
    swallow(e);
    return null;
  }
}
