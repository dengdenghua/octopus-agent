// 资产 Registry 消费端 API(母体接 registry · octopus-runtime)。
// 走后端 /api/registry/* 路由(registry_consumer_router),浏览/安装公网 registry 技能。
import { getBackendBaseURL } from "@/core/config";

export interface RegistrySkill {
  id: string; // "skill/<slug>"
  type: string;
  kind: string; // data | code
  version: string;
  name: string;
  description: string;
  category?: string | null;
  tags?: string[] | null;
  platforms?: string[] | null;
  content?: { checksum?: string | null } | null;
}

export interface RegistrySkillsResponse {
  skills: RegistrySkill[];
  total: number;
  offset: number;
  limit: number;
  source: string;
}

export interface InstallResult {
  installed: string;
  path: string | null;
  registered_now: number;
}

export function registrySlug(id: string): string {
  return id.split("/").pop() ?? id;
}

export async function listRegistrySkills(params?: {
  search?: string;
  category?: string;
  limit?: number;
}): Promise<RegistrySkillsResponse> {
  const q = new URLSearchParams();
  if (params?.search) q.set("search", params.search);
  if (params?.category) q.set("category", params.category);
  q.set("limit", String(params?.limit ?? 300));
  const res = await fetch(`${getBackendBaseURL()}/api/registry/skills?${q.toString()}`);
  if (!res.ok) throw new Error(`registry list failed: HTTP ${res.status}`);
  return (await res.json()) as RegistrySkillsResponse;
}

export async function installRegistrySkill(slug: string): Promise<InstallResult> {
  const bare = registrySlug(slug);
  const res = await fetch(
    `${getBackendBaseURL()}/api/registry/skills/${encodeURIComponent(bare)}/install`,
    { method: "POST" },
  );
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`install failed: HTTP ${res.status} ${txt}`.trim());
  }
  return (await res.json()) as InstallResult;
}
