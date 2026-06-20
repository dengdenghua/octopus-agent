import { getBackendBaseURL } from "@/core/config";

import type {
  AgentWorldAgent,
  AgentWorldListParams,
  AgentWorldListResponse,
  AgentProfile,
  AgentMemory,
  AgentRating,
  AgentRelationship,
} from "./types";

const AGENT_MARKET_API = "/api/agent-market";

export interface AgentPackModule {
  id: string;
  kind: string;
  name: string;
  path: string;
  description?: string;
  source_plugin?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AgentPackPreview {
  root: string;
  marketplace?: Record<string, unknown> | null;
  plugins: AgentPackModule[];
  apps: AgentPackModule[];
  agents: AgentPackModule[];
  skills: AgentPackModule[];
  commands: AgentPackModule[];
  mcp_servers: AgentPackModule[];
  managed_agents: AgentPackModule[];
  subagents: AgentPackModule[];
  warnings: string[];
}

export interface AgentPackImportResult {
  agent_id: string;
  agent_name: string;
  agent_path: string;
  copied_skills: string[];
  skipped_skills: string[];
  warnings: string[];
  already_exists?: boolean;
}

export interface AgentInstallResult {
  installed: boolean;
  agent_id: string;
  key_skills?: string[];
  available_skills?: string[];
  registered_skills?: number;
  tool_registry?: string;
}

export async function previewAgentPack(
  path: string,
): Promise<AgentPackPreview> {
  const qs = new URLSearchParams({ path });
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/packs/preview?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to preview agent pack: ${res.statusText}`);
  return res.json() as Promise<AgentPackPreview>;
}

export async function importAgentFromPack(args: {
  path: string;
  agentName: string;
}): Promise<AgentPackImportResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/packs/import-agent`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ path: args.path, agent_name: args.agentName }),
    },
  );
  if (!res.ok)
    throw new Error(`Failed to import agent pack: ${res.statusText}`);
  return res.json() as Promise<AgentPackImportResult>;
}

// ---------------------------------------------------------------------------
// Store – browse & search
// ---------------------------------------------------------------------------

export async function listStoreAgents(
  params: AgentWorldListParams = {},
): Promise<AgentWorldListResponse> {
  // Featured agents use a dedicated endpoint
  if (params.featured) {
    const qs = new URLSearchParams();
    if (params.page_size) qs.set("limit", String(params.page_size));
    const res = await fetch(
      `${getBackendBaseURL()}${AGENT_MARKET_API}/store/featured?${qs.toString()}`,
      { headers: authHeaders() },
    );
    if (!res.ok)
      throw new Error(`Failed to load featured agents: ${res.statusText}`);
    return res.json() as Promise<AgentWorldListResponse>;
  }

  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.search) qs.set("search", params.search);
  if (params.sort_by) qs.set("sort", params.sort_by);
  if (params.page !== undefined)
    qs.set(
      "offset",
      String(((params.page ?? 1) - 1) * (params.page_size ?? 50)),
    );
  if (params.page_size !== undefined) qs.set("limit", String(params.page_size));

  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load store agents: ${res.statusText}`);
  return res.json() as Promise<AgentWorldListResponse>;
}

// ── 企业版角色资产(消费侧)─────────────────────
export type EnterpriseAsset = {
  id: string;
  name: string;
  description: string;
  category: string;
  tags: string[];
  icon: string;
  source: string;
  kind: string;
};

export type EnterpriseAssetsResponse = {
  available: boolean;
  items: EnterpriseAsset[];
  error?: string | null;
};

/** 列举企业版托管的角色资产。未配 OCTOPUS_ENTERPRISE_URL → available:false。 */
export async function listEnterpriseAssets(
  params: { category?: string; search?: string } = {},
): Promise<EnterpriseAssetsResponse> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.search) qs.set("search", params.search);
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/enterprise?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok) return { available: false, items: [] };
  return res.json() as Promise<EnterpriseAssetsResponse>;
}

/** 把企业版角色导入本地(后端 scaffold + load+register),并刷新本地角色名册。 */
export async function installEnterpriseAsset(
  id: string,
): Promise<{ installed: boolean; agent_id: string; name?: string }> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/enterprise/${id}/install`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`安装失败: ${res.statusText}`);
  const result = await res.json();
  await fetch(`${getBackendBaseURL()}/api/agents/reload`, {
    method: "POST",
    headers: authHeaders(),
  }).catch(() => {});
  return result;
}

export async function getStoreAgent(id: string): Promise<AgentWorldAgent> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store/${id}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Agent not found: ${res.statusText}`);
  return res.json() as Promise<AgentWorldAgent>;
}

// ---------------------------------------------------------------------------
// Install / Uninstall
// ---------------------------------------------------------------------------

export async function installAgent(id: string): Promise<AgentInstallResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store/${id}/install`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to install agent: ${res.statusText}`);
  const result = (await res.json()) as AgentInstallResult;
  await fetch(`${getBackendBaseURL()}/api/agents/reload`, {
    method: "POST",
    headers: authHeaders(),
  }).catch(() => undefined);
  return result;
}

export async function uninstallAgent(id: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store/${id}/install`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to uninstall agent: ${res.statusText}`);
}

// ---------------------------------------------------------------------------
// Profile
// ---------------------------------------------------------------------------

export async function getAgentProfile(
  agentName: string,
): Promise<AgentProfile> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/profile/${agentName}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load agent profile: ${res.statusText}`);
  return res.json() as Promise<AgentProfile>;
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export async function listAgentMemories(
  agentName: string,
): Promise<AgentMemory[]> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/memory/${agentName}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load agent memories: ${res.statusText}`);
  const data = (await res.json()) as { memories: AgentMemory[] };
  return data.memories;
}

export async function addAgentMemory(
  agentName: string,
  memory: { memory_type: AgentMemory["memory_type"]; content: string },
): Promise<AgentMemory> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/memory/${agentName}/remember`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(memory),
    },
  );
  if (!res.ok) throw new Error(`Failed to add memory: ${res.statusText}`);
  return res.json() as Promise<AgentMemory>;
}

export async function deleteAgentMemory(
  agentName: string,
  memoryId: string,
): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/memory/${agentName}/${memoryId}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to delete memory: ${res.statusText}`);
}

// ---------------------------------------------------------------------------
// Implementation note.
// ---------------------------------------------------------------------------

export type JournalMood =
  | "insight"
  | "mistake"
  | "pride"
  | "tired"
  | "question";

export interface AgentJournalEntry {
  timestamp: string;
  thread_id: string | null;
  title: string;
  body: string;
  mood: JournalMood;
  /**
   * True when the backend sanitiser redacted the body because it looked like
   * it quoted private user content (names, emails, long verbatim quotes).
   * The `body` field in that case is a neutral placeholder; callers should
   * render a hint so the user knows the entry was dropped on purpose.
   */
  body_redacted?: boolean;
}

export async function listAgentJournal(
  agentName: string,
  limit = 50,
): Promise<AgentJournalEntry[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/agents/${agentName}/journal?limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load agent journal: ${res.statusText}`);
  const data = (await res.json()) as { entries: AgentJournalEntry[] };
  return data.entries;
}

// ---------------------------------------------------------------------------
// Ratings / Reviews
// ---------------------------------------------------------------------------

export async function listAgentRatings(
  agentId: string,
): Promise<AgentRating[]> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store/${agentId}/ratings`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to load ratings: ${res.statusText}`);
  const data = (await res.json()) as { ratings: AgentRating[] };
  return data.ratings;
}

export async function submitAgentRating(
  agentId: string,
  rating: { rating: number; review_text?: string },
): Promise<AgentRating> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/store/${agentId}/rate`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(rating),
    },
  );
  if (!res.ok) throw new Error(`Failed to submit rating: ${res.statusText}`);
  return res.json() as Promise<AgentRating>;
}

// ---------------------------------------------------------------------------
// Social / Relationships
// ---------------------------------------------------------------------------

export async function listAgentRelationships(
  agentName: string,
): Promise<AgentRelationship[]> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/social/${agentName}/relationships`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Failed to load relationships: ${res.statusText}`);
  const data = (await res.json()) as { relationships: AgentRelationship[] };
  return data.relationships;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("octopus:token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonAuthHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...authHeaders(),
  };
}
