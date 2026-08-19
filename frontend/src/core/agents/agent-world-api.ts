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

// ---------------------------------------------------------------------------
// WorkBuddy 专家商城 · 云端源(替换第三方 octoapk 角色商城)
// 后端: runtime/platform/plugins/cloud_expert_store.py
//   GET  /api/agent-market/cloud/store
//   GET  /api/agent-market/cloud/store/categories
//   POST /api/agent-market/cloud/store/{id}/install
// ---------------------------------------------------------------------------

export interface CloudExpertAgent {
  id: string;
  name: string;
  display_name: string;
  description: string;
  author: string;
  category: string;
  category_id?: string;
  tags: string[];
  icon: string;
  avatar_url?: string;
  is_team?: boolean;
  is_installed?: boolean;
  bundle_url?: string;
  quick_prompts?: string[];
  profession?: string;
  source?: string;
  created_at?: string;
}

export interface CloudStoreResponse {
  agents: CloudExpertAgent[];
  total: number;
  page: number;
  page_size: number;
}

export interface CloudStoreCategory {
  id: string;
  name: { en: string; zh: string };
  description?: { en?: string; zh?: string };
}

export interface CloudStoreCategoriesResponse {
  categories: CloudStoreCategory[];
  meta?: Record<string, unknown>;
}

export interface CloudStoreInstallResult {
  installed: boolean;
  already_exists?: boolean;
  agent_id?: string;
  agent_name?: string;
  agent_path?: string;
  copied_skills?: string[];
  warnings?: string[];
  message?: string;
}

/** 拉取云端 WorkBuddy 专家商城(421 位)。refresh=1 强制清缓存重拉。 */
export async function listCloudStoreExperts(
  params: {
    category?: string;
    search?: string;
    sort?: string;
    refresh?: boolean;
    limit?: number;
  } = {},
): Promise<CloudStoreResponse> {
  const qs = new URLSearchParams();
  if (params.category) qs.set("category", params.category);
  if (params.search) qs.set("search", params.search);
  if (params.sort) qs.set("sort", params.sort);
  if (params.refresh) qs.set("refresh", "1");
  qs.set("limit", String(params.limit ?? 500));
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/cloud/store?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`WorkBuddy cloud store failed: HTTP ${res.status}`);
  return res.json() as Promise<CloudStoreResponse>;
}

/** 拉取云端商城分类(15 大类)。 */
export async function listCloudStoreCategories(): Promise<CloudStoreCategoriesResponse> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/cloud/store/categories`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`WorkBuddy cloud categories failed: HTTP ${res.status}`);
  return res.json() as Promise<CloudStoreCategoriesResponse>;
}

/** 安装云端专家:后端下载 bundle → 解包 → 导入为本地 agent。 */
export async function installCloudExpert(
  expertId: string,
): Promise<CloudStoreInstallResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${AGENT_MARKET_API}/cloud/store/${encodeURIComponent(
      expertId,
    )}/install`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`WorkBuddy install failed: HTTP ${res.status} ${txt}`.trim());
  }
  return res.json() as Promise<CloudStoreInstallResult>;
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
// 连接器市场(WorkBuddy 108 连接器 fork + 认证编排层)
// 后端: runtime/sensing/gateway/connector_router.py
//   GET    /api/connectors                      列表(含安装/启用状态)
//   POST   /api/connectors/{id}/install         安装(技能→skills,MCP 默认禁用)
//   DELETE /api/connectors/{id}/install         卸载
//   POST   /api/connectors/{id}/enable|disable  启用/禁用 MCP
//   GET    /api/connectors/{id}/status          认证状态
//   POST   /api/connectors/{id}/connect         认证编排(带 tokens / 返回 CLI 命令)
//   POST   /api/connectors/{id}/disconnect      断开并清除凭据
// ---------------------------------------------------------------------------

export type ConnectorType = "mcp" | "cli" | "skill-only" | "other";

export interface ConnectorInfo {
  id: string;
  name: string;
  name_zh: string;
  description: string;
  description_zh: string;
  type: ConnectorType;
  auth_mode: string;
  source: string;
  provider_id?: string;
  mcp_servers: string[];
  skill_count: number;
  examples_zh?: string[];
  installed: boolean;
  enabled: boolean;
  version: string;
}

export interface ConnectorListResponse {
  connectors: ConnectorInfo[];
  total: number;
}

export interface ConnectorStatusResponse {
  connector_id: string;
  auth_mode: string;
  connected: boolean;
  has_token?: boolean;
  stored_keys?: string[];
  cli_status?: {
    exit_code: number;
    output: string;
    connected: boolean;
  };
}

export interface ConnectorConnectResult {
  connected: boolean;
  connector_id?: string;
  message?: string;
  command?: string;
  exit_code?: number;
  output?: string;
  stored_keys?: string[];
}

export interface ConnectorInstallResult {
  installed: boolean;
  connector_id: string;
  type: string;
  auth_mode: string;
  copied_skills?: string[];
  mcp_servers?: string[];
  enabled?: boolean;
  message?: string;
}

const CONNECTOR_API = "/api/connectors";

/** 连接器列表(WorkBuddy 108 fork + 本地)。 */
export async function listConnectors(params: {
  search?: string;
  type?: string;
  limit?: number;
} = {}): Promise<ConnectorListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.type) qs.set("type", params.type);
  qs.set("limit", String(params.limit ?? 500));
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector list failed: HTTP ${res.status}`);
  return res.json() as Promise<ConnectorListResponse>;
}

/** 安装连接器(技能→~/.octopus/skills,MCP 默认禁用)。 */
export async function installConnector(
  connectorId: string,
): Promise<ConnectorInstallResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/install`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`Connector install failed: HTTP ${res.status} ${txt}`.trim());
  }
  return res.json() as Promise<ConnectorInstallResult>;
}

/** 卸载连接器。 */
export async function uninstallConnector(connectorId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/install`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector uninstall failed: HTTP ${res.status}`);
}

/** 启用连接器 MCP(需已连接)。 */
export async function enableConnector(connectorId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/enable`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector enable failed: HTTP ${res.status}`);
}

/** 禁用连接器 MCP。 */
export async function disableConnector(connectorId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/disable`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector disable failed: HTTP ${res.status}`);
}

/** 连接器认证状态。 */
export async function getConnectorStatus(
  connectorId: string,
): Promise<ConnectorStatusResponse> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/status`,
    { headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector status failed: HTTP ${res.status}`);
  return res.json() as Promise<ConnectorStatusResponse>;
}

/** 认证编排:带 tokens 走 token/oauth,否则 CLI 型返回终端命令。 */
export async function connectConnector(
  connectorId: string,
  body: { tokens?: Record<string, string>; run_cli?: boolean } = {},
): Promise<ConnectorConnectResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/connect`,
    { method: "POST", headers: jsonAuthHeaders(), body: JSON.stringify(body) },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`Connector connect failed: HTTP ${res.status} ${txt}`.trim());
  }
  return res.json() as Promise<ConnectorConnectResult>;
}

/** 断开连接器并清除凭据。 */
export async function disconnectConnector(connectorId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CONNECTOR_API}/${encodeURIComponent(
      connectorId,
    )}/disconnect`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok)
    throw new Error(`Connector disconnect failed: HTTP ${res.status}`);
}


// ---------------------------------------------------------------------------
// 统一「能力包」市场 —— 连接器 + Codex 插件一个市场
// 后端: runtime/sensing/gateway/capability_router.py
//   GET  /api/capabilities                    统一列表
//   POST /api/capabilities/{id}/install       安装(技能→skills, 连接器+MCP)
//   POST /api/capabilities/{id}/enable|disable
//   POST /api/capabilities/{id}/connect       认证编排
//   GET  /api/capabilities/{id}/status
// ---------------------------------------------------------------------------

const CAPABILITY_API = "/api/capabilities";

export type CapabilitySource = "connector" | "codex_plugin";

export interface CapabilityInfo {
  id: string;
  name: string;
  name_zh: string;
  description: string;
  description_zh: string;
  type: string;
  auth_mode: string;
  source: CapabilitySource;
  provider_id?: string;
  author?: string;
  category?: string;
  icon?: string;
  mcp_servers: string[];
  skill_count: number;
  examples_zh?: string[];
  installed: boolean;
  enabled: boolean;
  connected?: boolean;
  version: string;
}

export interface CapabilityListResponse {
  capabilities: CapabilityInfo[];
  total: number;
}

export interface CapabilityConnectResult {
  connected: boolean;
  message?: string;
  command?: string;
  capability_id?: string;
}

/** 统一插件市场列表(WorkBuddy MCP 服务 + Codex 插件)。 */
export async function listCapabilities(opts: {
  search?: string;
  source?: CapabilitySource | "";
  limit?: number;
} = {}): Promise<CapabilityListResponse> {
  const qs = new URLSearchParams();
  if (opts.search) qs.set("search", opts.search);
  if (opts.source) qs.set("source", opts.source);
  qs.set("limit", String(opts.limit ?? 500));
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}?${qs.toString()}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Capability list failed: HTTP ${res.status}`);
  return res.json() as Promise<CapabilityListResponse>;
}

/** 安装插件(技能→~/.octopus/skills;带 MCP 的插件额外登记 MCP)。 */
export async function installCapability(
  capabilityId: string,
): Promise<{ installed: boolean; copied_skills?: string[] }> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/install`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`Capability install failed: HTTP ${res.status} ${txt}`.trim());
  }
  return res.json();
}

/** 卸载能力包。 */
export async function uninstallCapability(capabilityId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/install`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Capability uninstall failed: HTTP ${res.status}`);
}

/** 启用/禁用能力。 */
export async function setCapabilityEnabled(
  capabilityId: string,
  enabled: boolean,
): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/${enabled ? "enable" : "disable"}`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Capability ${enabled ? "enable" : "disable"} failed: HTTP ${res.status}`);
}

/** 能力认证/连接状态。 */
export async function getCapabilityStatus(
  capabilityId: string,
): Promise<{ connected: boolean; auth_mode?: string }> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/status`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Capability status failed: HTTP ${res.status}`);
  return res.json();
}

/** 认证编排:带认证的插件走 tokens / 其余直接就绪。 */
export async function connectCapability(
  capabilityId: string,
  body: { tokens?: Record<string, string>; run_cli?: boolean } = {},
): Promise<CapabilityConnectResult> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/connect`,
    { method: "POST", headers: jsonAuthHeaders(), body: JSON.stringify(body) },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`Capability connect failed: HTTP ${res.status} ${txt}`.trim());
  }
  return res.json();
}

/** 断开插件(清除已存凭据)。 */
export async function disconnectCapability(capabilityId: string): Promise<void> {
  const res = await fetch(
    `${getBackendBaseURL()}${CAPABILITY_API}/${encodeURIComponent(
      capabilityId,
    )}/disconnect`,
    { method: "POST", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Capability disconnect failed: HTTP ${res.status}`);
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
