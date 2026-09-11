import { createAgent, listAgents } from "./api";
import { installCloudExpert } from "./agent-world-api";

export interface RoleProvision {
  source: "hub" | "new";
  key: string;
  name: string;
  expert_id?: string;
  agent_id?: string;
  description?: string;
  soul?: string;
}

export async function provisionProjectRoles(requests: RoleProvision[], isActive: () => boolean = () => true): Promise<Record<string, string>> {
  const prepared: Record<string, string> = {};
  const agents = await listAgents();
  for (const role of requests) {
    if (!isActive()) throw new Error("Approval expired; prepared roles were retained.");
    if (role.source === "hub" && role.expert_id) {
      const result = await installCloudExpert(role.expert_id);
      if (!result.agent_id) throw new Error(`Role was not loaded: ${role.name}`);
      prepared[role.key] = result.agent_id;
    } else if (role.source === "new" && role.agent_id && role.soul && role.description) {
      const existing = agents.find((agent) => agent.name === role.agent_id);
      if (existing && existing.description !== role.description) throw new Error(`Role configuration changed: ${role.name}`);
      if (!existing) await createAgent({ name: role.agent_id, display_name: role.name, description: role.description, soul: role.soul });
      prepared[role.key] = role.agent_id;
    } else {
      throw new Error(`Invalid role proposal: ${role.name}`);
    }
  }
  if (!isActive()) throw new Error("Approval expired; prepared roles were retained.");
  return prepared;
}
