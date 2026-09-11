import { useEffect, useState } from "react";
import { listAgents } from "./api";
import type { Agent } from "./types";
import presets from "./profession-blueprints.json";

export const blueprints = presets;
export type Profession = {
  id: string; name: string; category: string; boundary: string;
  original_jobs: string[]; configuration_dimensions: string;
  candidates: { role_id: string; role_name: string; source: string; author: string; match: string }[];
};
export function professionName(agent: Agent) {
  return (agent.display_name || agent.name).replace(/(?:数字|数位)?分身$/, "").trim();
}
// Reviewed occupational equivalence only. A reusable candidate is not necessarily
// the same profession (e.g. embedded engineering must not disappear into mobile).
const aliases: Record<string, string> = {
  twin_product: "产品经理", twin_project: "项目经理", twin_test_engineer: "测试工程师",
  twin_industrial_design: "工业设计师", twin_quality: "质量工程师",
  twin_supplier_quality_expert: "质量工程师", twin_supply_chain: "采购与供应链",
  twin_procurement_manager_buyer: "采购与供应链", twin_sales: "销售与商务",
  twin_legal: "法务与合规", twin_hr: "人力与组织运营",
};
const normalize = (name: string) => name.replace(/\s+/g, "").toLowerCase();
export function mergeProfessions(agents: Agent[]): Profession[] {
  const roles: Profession[] = presets.map(r => ({ ...r, original_jobs: [...r.original_jobs], candidates: [...r.candidates] }));
  const byName = new Map(roles.map(r => [normalize(r.name), r]));
  const seen = new Set<string>();
  for (const agent of agents) {
    if (!agent.name.startsWith("twin_") || seen.has(agent.name)) continue;
    seen.add(agent.name);
    const name = professionName(agent);
    const match = byName.get(normalize(aliases[agent.name] || name));
    const candidate = { role_id: agent.name, role_name: name, source: "本地职业模板", author: "原作者未标注", match: "职业模板" };
    if (match) {
      if (!match.original_jobs.includes(name)) match.original_jobs.push(name);
      if (!match.candidates.some(c => c.role_id === agent.name)) match.candidates.push(candidate);
    } else {
      const role: Profession = { id: agent.name.replace(/^twin_/, "").replace(/_/g, "-"), name, category: "专业职业", boundary: agent.description || name, original_jobs: [name], configuration_dimensions: "按实际业务与工具配置", candidates: [candidate] };
      roles.push(role); byName.set(normalize(name), role);
    }
  }
  return roles;
}
export function useProfessionCatalog() {
  const [roles, setRoles] = useState<Profession[]>(() => mergeProfessions([]));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false);
    listAgents({ signal: controller.signal }).then(agents => {
      if (!controller.signal.aborted) setRoles(mergeProfessions(agents));
    }).catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);
  return { roles, loading, error, retry: () => setAttempt(n => n + 1) };
}
