import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

async function evolutionFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 8_000);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  try {
    return await fetch(`${getBackendBaseURL()}${path}`, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeoutId);
    init?.signal?.removeEventListener("abort", abortFromCaller);
  }
}

export interface EvolutionOverview {
  skills: {
    total: number;
    auto_extracted: number;
    manual: number;
    avg_success_rate: number;
  };
  memory: {
    total_facts: number;
    categories: {
      memories: number;
      rules: number;
      trajectories: number;
    };
  };
  knowledge_graph: { nodes: number; edges: number } | null;
  learning_events: number;
  improvement_score: number;
  proactive_learning: {
    enabled: boolean;
    is_running: boolean;
    total_reports: number;
    subscriptions: number;
    enabled_subscriptions: number;
    last_report_at: string | null;
    total_skills_created: number;
  };
  source: string;
}

export interface LearningCurvePoint {
  week: string;
  success_rate: number;
  avg_duration_ms: number;
  skills_used: number;
}

export interface SkillPerformance {
  name: string;
  usage_count: number;
  success_count: number;
  success_rate: number;
  avg_cost_usd: number;
  avg_tokens: number;
  source: string;
}

export interface MemoryGrowthPoint {
  date: string;
  fact: number;
  preference: number;
  learned_skill: number;
  relationship: number;
}

export interface Recommendation {
  type: string;
  title: string;
  description: string;
  severity: "info" | "warning" | "critical";
  action_label: string;
  meta: Record<string, unknown>;
}

export interface FitnessReport {
  ok: boolean;
  agent_id: string;
  ts: string;
  l1: {
    score: number;
    trend: string;
    success_rate: number;
    avg_rounds: number;
  } | null;
  l2: {
    score: number;
    dominant_failure: string;
    action: string;
    confidence: number;
  } | null;
  combined: number;
  verdict: string;
}

export interface DriftReport {
  ok: boolean;
  agent_id: string;
  ts: string;
  has_drift: boolean;
  max_severity: string;
  events: Array<{ kind: string; severity: string; detail: string }>;
}

export interface LedgerRecord {
  id: string;
  kind: string;
  description: string;
  status: string;
  proposer: string;
  ts: string;
  fitness_before: number | null;
  fitness_after: number | null;
}

export interface CanaryState {
  skill_name: string;
  phase: string;
  sample_count: number;
  success_count: number;
  current_rate: number;
  entered_ts: string;
}

export async function getEvolutionOverview(): Promise<EvolutionOverview> {
  const res = await evolutionFetch("/api/evolution/overview", {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to load evolution overview: ${res.statusText}`);
  return (await res.json()) as EvolutionOverview;
}

export async function getLearningCurve(
  weeks?: number,
): Promise<LearningCurvePoint[]> {
  const params = new URLSearchParams();
  if (weeks !== undefined) params.set("weeks", String(weeks));
  const qs = params.toString();
  const path = `/api/evolution/learning-curve${qs ? `?${qs}` : ""}`;
  const res = await evolutionFetch(path, { headers: authHeaders() });
  if (!res.ok)
    throw new Error(`Failed to load learning curve: ${res.statusText}`);
  return (await res.json()) as LearningCurvePoint[];
}

export async function getSkillPerformance(): Promise<SkillPerformance[]> {
  const res = await evolutionFetch("/api/evolution/skills/performance", {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to load skill performance: ${res.statusText}`);
  return (await res.json()) as SkillPerformance[];
}

export async function getMemoryGrowth(
  days?: number,
): Promise<MemoryGrowthPoint[]> {
  const params = new URLSearchParams();
  if (days !== undefined) params.set("days", String(days));
  const qs = params.toString();
  const path = `/api/evolution/memory/growth${qs ? `?${qs}` : ""}`;
  const res = await evolutionFetch(path, { headers: authHeaders() });
  if (!res.ok)
    throw new Error(`Failed to load memory growth: ${res.statusText}`);
  return (await res.json()) as MemoryGrowthPoint[];
}

export async function getRecommendations(): Promise<Recommendation[]> {
  const res = await evolutionFetch("/api/evolution/recommendations", {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to load recommendations: ${res.statusText}`);
  return (await res.json()) as Recommendation[];
}

export async function getFitness(
  agentId: string,
  window?: number,
): Promise<FitnessReport> {
  const params = new URLSearchParams();
  if (window !== undefined) params.set("window", String(window));
  const qs = params.toString();
  const url = `${getBackendBaseURL()}/api/evolution/fitness/${encodeURIComponent(agentId)}${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok)
    throw new Error(`Failed to load fitness report: ${res.statusText}`);
  return (await res.json()) as FitnessReport;
}

export async function getDrift(agentId: string): Promise<DriftReport> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/evolution/drift/${encodeURIComponent(agentId)}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load drift report: ${res.statusText}`);
  return (await res.json()) as DriftReport;
}

export async function getLedger(opts?: {
  status?: string;
  kind?: string;
  limit?: number;
}): Promise<{
  total: number;
  records: LedgerRecord[];
  stats: Record<string, unknown>;
}> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.kind) params.set("kind", opts.kind);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const url = `${getBackendBaseURL()}/api/evolution/ledger${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Failed to load ledger: ${res.statusText}`);
  return (await res.json()) as {
    total: number;
    records: LedgerRecord[];
    stats: Record<string, unknown>;
  };
}

export async function getCanary(): Promise<{
  active_count: number;
  canaries: CanaryState[];
}> {
  const res = await fetch(`${getBackendBaseURL()}/api/evolution/canary`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to load canary state: ${res.statusText}`);
  return (await res.json()) as {
    active_count: number;
    canaries: CanaryState[];
  };
}

export async function rollbackCanary(
  skillName: string,
): Promise<{ ok: boolean; skill_name: string; phase: string }> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/evolution/canary/${encodeURIComponent(skillName)}/rollback`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
    },
  );
  if (!res.ok) throw new Error(`Failed to rollback canary: ${res.statusText}`);
  return (await res.json()) as {
    ok: boolean;
    skill_name: string;
    phase: string;
  };
}
