import type { CloudExpertAgent } from "@/core/agents/agent-world-api";

// Shared with Project OS recruitment so hidden roles cannot re-enter through staffing.
import catalog from "../../../../runtime/projectos/role_catalog.json";
export const DIGITAL_EMPLOYEE_GROUPS = catalog.groups;
export const DIGITAL_EMPLOYEE_IDS = new Set(DIGITAL_EMPLOYEE_GROUPS.flatMap(group => group.ids));
export const FINANCE_TEAM_IDS = catalog.finance_team_ids;
export const CURATED_TEAM_IDS = new Set(catalog.team_ids);
export const CURATED_ROLE_NAMES: Record<string, string> = catalog.names;
const GROUP_BY_ID = new Map(DIGITAL_EMPLOYEE_GROUPS.flatMap((group) => group.ids.map((id) => [id, group.id] as const)));
const FINANCE_TEAMS = new Set(FINANCE_TEAM_IDS);
export function selectDigitalEmployees(experts: CloudExpertAgent[], includePreviouslyAdded = false): CloudExpertAgent[] {
  return experts.filter((expert) => (expert.is_team ? CURATED_TEAM_IDS.has(expert.id) : DIGITAL_EMPLOYEE_IDS.has(expert.id)) || (includePreviouslyAdded && expert.is_installed))
    .map((expert) => ({
      ...expert,
      ...(GROUP_BY_ID.has(expert.id) && !expert.is_team ? { category_id: GROUP_BY_ID.get(expert.id) } : {}),
      ...(expert.is_team && FINANCE_TEAMS.has(expert.id) ? { category_id: "finance" } : {}),
      ...(CURATED_ROLE_NAMES[expert.id] ? { display_name: CURATED_ROLE_NAMES[expert.id] } : {}),
    }));
}
