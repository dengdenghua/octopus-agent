import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

import type { Agent, CreateAgentRequest, UpdateAgentRequest } from "./types";

const BACKEND_UNAVAILABLE_STATUSES = new Set([502, 503, 504]);
const HIDDEN_AGENT_IDS = new Set(["admin", "desktop_operator"]);

export class AgentNameCheckError extends Error {
  constructor(
    message: string,
    public readonly reason: "backend_unreachable" | "request_failed",
  ) {
    super(message);
    this.name = "AgentNameCheckError";
  }
}

export async function listAgents(opts?: { signal?: AbortSignal }): Promise<Agent[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`, {
    headers: authHeaders(),
    signal: opts?.signal,
  });
  if (!res.ok) throw new Error(`Failed to load agents: ${res.statusText}`);
  const data = (await res.json()) as Agent[] | { agents?: Agent[] };
  const agents = Array.isArray(data) ? data : (data.agents ?? []);
  return agents.filter((agent) => !HIDDEN_AGENT_IDS.has(agent.name));
}

export async function getAgent(name: string, opts?: { signal?: AbortSignal }): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}`, {
    headers: authHeaders(),
    signal: opts?.signal,
  });
  if (!res.ok) throw new Error(`Agent '${name}' not found`);
  return (await res.json()) as Agent;
}

export async function createAgent(request: CreateAgentRequest): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to create agent: ${res.statusText}`);
  }
  return (await res.json()) as Agent;
}

export interface LocalAgentPartner {
  id: string;
  agent_id: string;
  name: string;
  default_alias: string;
  description: string;
  detected: boolean;
  registered: boolean;
  status: "registered" | "detected" | "missing" | string;
  command?: string | null;
  executable?: string | null;
}

export interface LocalAgentPartnerRegisterResult {
  id: string;
  agent_id: string;
  status: "registered" | "already_exists" | "not_detected" | "error" | string;
  message: string;
  agent?: Agent | null;
}

export interface LocalAgentPartnerRegisterResponse {
  results: LocalAgentPartnerRegisterResult[];
  registered_count: number;
  already_exists_count: number;
  skipped_count: number;
}

export async function listLocalAgentPartners(opts?: {
  signal?: AbortSignal;
}): Promise<LocalAgentPartner[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/local-partners`, {
    headers: authHeaders(),
    signal: opts?.signal,
  });
  if (!res.ok)
    throw new Error(`Failed to load local partners: ${res.statusText}`);
  const data = (await res.json()) as { partners?: LocalAgentPartner[] };
  return data.partners ?? [];
}

export async function registerLocalAgentPartners(
  partners: Array<{ id: string; alias?: string | null }>,
): Promise<LocalAgentPartnerRegisterResponse> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/local-partners/register`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ partners }),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to register local partners: ${res.statusText}`);
  }
  return (await res.json()) as LocalAgentPartnerRegisterResponse;
}

export async function updateAgent(
  name: string,
  request: UpdateAgentRequest,
): Promise<Agent> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to update agent: ${res.statusText}`);
  }
  return (await res.json()) as Agent;
}

export async function generateAgentVisuals(
  name: string,
  request: { provider?: string; style_prompt?: string } = {},
): Promise<{
  agent_id: string;
  provider: string;
  visual_urls: Record<string, string>;
}> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}/visuals/generate`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to generate visuals: ${res.statusText}`);
  }
  return (await res.json()) as {
    agent_id: string;
    provider: string;
    visual_urls: Record<string, string>;
  };
}

export async function deleteAgent(name: string): Promise<void> {
  const res = await fetch(`${getBackendBaseURL()}/api/agents/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to delete agent: ${res.statusText}`);
}

export async function checkAgentName(
  name: string,
): Promise<{ available: boolean; name: string }> {
  let res: Response;
  try {
    res = await fetch(
      `${getBackendBaseURL()}/api/agents/check?name=${encodeURIComponent(name)}`,
      { headers: authHeaders() },
    );
  } catch (e) {
    swallow(e);
    throw new AgentNameCheckError(
      "Could not reach the Octopus backend.",
      "backend_unreachable",
    );
  }

  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    if (BACKEND_UNAVAILABLE_STATUSES.has(res.status)) {
      throw new AgentNameCheckError(
        "Could not reach the Octopus backend.",
        "backend_unreachable",
      );
    }
    throw new AgentNameCheckError(
      err.detail ?? `Failed to check agent name: ${res.statusText}`,
      "request_failed",
    );
  }
  return (await res.json()) as { available: boolean; name: string };
}
