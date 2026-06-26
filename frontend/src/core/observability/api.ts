import { getBackendBaseURL } from "@/core/config";
import { authHeaders, authedEventSource, jsonAuthHeaders } from "@/core/auth/api";

import type {
  ActiveAlert,
  AlertRule,
  MetricsSummary,
  Span,
  TelemetryStats,
  TraceSummary,
} from "./types";

export async function getMetrics(): Promise<Record<string, unknown>> {
  const res = await fetch(`${getBackendBaseURL()}/api/metrics`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get metrics: ${res.statusText}`);
  return (await res.json()) as Record<string, unknown>;
}

export async function getMetricsSummary(): Promise<MetricsSummary> {
  const res = await fetch(`${getBackendBaseURL()}/api/metrics/summary`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to get metrics summary: ${res.statusText}`);
  return (await res.json()) as MetricsSummary;
}

export async function getTraces(limit = 100): Promise<TraceSummary[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/trace/recent?limit=${limit}`,
    {
      headers: authHeaders(),
    },
  );
  if (!res.ok) throw new Error(`Failed to get traces: ${res.statusText}`);
  return (await res.json()) as TraceSummary[];
}

export async function getTrace(traceId: string): Promise<Span[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/trace/${traceId}`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get trace: ${res.statusText}`);
  return (await res.json()) as Span[];
}

export async function getAlerts(): Promise<ActiveAlert[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/alerts`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get alerts: ${res.statusText}`);
  return (await res.json()) as ActiveAlert[];
}

export async function getAlertRules(): Promise<AlertRule[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/alerts/rules`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get alert rules: ${res.statusText}`);
  return (await res.json()) as AlertRule[];
}

export async function createAlertRule(rule: AlertRule): Promise<AlertRule> {
  const res = await fetch(`${getBackendBaseURL()}/api/alerts/rules`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(rule),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(
      err.detail ?? `Failed to create alert rule: ${res.statusText}`,
    );
  }
  return (await res.json()) as AlertRule;
}

export async function deleteAlertRule(
  name: string,
): Promise<{ success: boolean; name: string }> {
  const res = await fetch(`${getBackendBaseURL()}/api/alerts/rules/${name}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to delete alert rule: ${res.statusText}`);
  return (await res.json()) as { success: boolean; name: string };
}

export async function getTelemetryStats(): Promise<TelemetryStats> {
  const res = await fetch(`${getBackendBaseURL()}/api/telemetry/stats`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to get telemetry stats: ${res.statusText}`);
  return (await res.json()) as TelemetryStats;
}

export async function getObservabilityHealth(): Promise<
  Record<string, unknown>
> {
  const res = await fetch(`${getBackendBaseURL()}/api/observability/health`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to get observability health: ${res.statusText}`);
  return (await res.json()) as Record<string, unknown>;
}

// Implementation note.
// Implementation note.
// Implementation note.

export interface EvolutionStatus {
  enabled: boolean;
  reason?: string;
  rules_count?: number;
  memories_count?: number;
  rules_section?: string;
  memories_section?: string;
  rules_lines?: string[];
  memories_lines?: string[];
  trajectories?: {
    total: number;
    react_loop: number;
    react_loop_failures: number;
  };
  react_variants?: ReActVariantStat[];
}

export interface ReActVariantStat {
  name: string;
  max_iterations: number;
  temperature: number;
  assignments: number;
  successes: number;
  failures: number;
  success_rate: number;
}

export async function getEvolutionStatus(): Promise<EvolutionStatus> {
  const res = await fetch(`${getBackendBaseURL()}/api/evolution/status`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to get evolution status: ${res.statusText}`);
  }
  return (await res.json()) as EvolutionStatus;
}

export interface ReflectionReport {
  skill_forge?: unknown;
  rule_extractor?: { rules: number };
  kg?: { accepted: number; total: number };
  memory?: { memories: number };
  workflow?: { proposals: number; by_kind?: Record<string, number> };
  recipe?: { recipes: number; best: string | null };
  error?: string;
}

/* Implementation note. */
export async function kickReflection(): Promise<ReflectionReport> {
  const res = await fetch(`${getBackendBaseURL()}/api/reflect`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to kick reflection: ${res.statusText}`);
  }
  return (await res.json()) as ReflectionReport;
}

export async function forgetRule(
  index: number,
): Promise<{ dropped: string; remaining: number }> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/evolution/rules/${index}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to delete rule: ${res.statusText}`);
  return (await res.json()) as { dropped: string; remaining: number };
}

export async function forgetMemory(
  index: number,
): Promise<{ dropped: string; remaining: number }> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/evolution/memories/${index}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to delete memory: ${res.statusText}`);
  return (await res.json()) as { dropped: string; remaining: number };
}

// Implementation note.

export interface FileOpEvent {
  event_type: "file_op";
  ts: string;
  task_id: string | null;
  arm_id: string | null;
  path: string;
  action: "create" | "write" | "edit" | "delete" | "rename";
  bytes_delta: number;
  old_size: number | null;
  new_size: number | null;
  sucker_id: string;
  /* Implementation note. */
  diff: string | null;
}

/* Implementation note. */
export function subscribeFileOps(
  onEvent: (e: FileOpEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  // Implementation note.
  // Implementation note.
  const url = `${getBackendBaseURL()}/api/files/stream`;
  const es = authedEventSource(url);
  es.addEventListener("file_op", (raw) => {
    try {
      const data = JSON.parse((raw as MessageEvent).data) as FileOpEvent;
      onEvent(data);
    } catch (e) {
      console.error("file_op parse failed", e, raw);
    }
  });
  if (onError) es.addEventListener("error", onError);
  return () => es.close();
}

// ─── Preview refresh events ────────────────────────────────

export interface PreviewRefreshEvent {
  event_type: "preview_refresh";
  ts: string;
  target: string;
  trigger_path: string;
  reason: string;
}

/* Implementation note. */
export function subscribePreviewRefresh(
  onEvent: (e: PreviewRefreshEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const url = `${getBackendBaseURL()}/api/preview/stream`;
  const es = authedEventSource(url);
  es.addEventListener("preview_refresh", (raw) => {
    try {
      const data = JSON.parse(
        (raw as MessageEvent).data,
      ) as PreviewRefreshEvent;
      onEvent(data);
    } catch (e) {
      console.error("preview_refresh parse failed", e, raw);
    }
  });
  if (onError) es.addEventListener("error", onError);
  return () => es.close();
}
