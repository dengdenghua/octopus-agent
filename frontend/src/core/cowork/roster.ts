import type { ThreadCollaborationRosterEntry } from "@/core/collaboration/thread-collaboration";

import type { CoworkGroupResponse } from "./types";

export interface CoworkAgentProfile {
  name: string;
  display_name?: string | null;
  avatar_url?: string | null;
  icon?: string | null;
}

function profileFor(
  id: string,
  profiles: CoworkAgentProfile[],
): CoworkAgentProfile | null {
  return (
    profiles.find((agent) => agent.name === id || agent.display_name === id) ??
    null
  );
}

function entryFor(
  id: string,
  role: ThreadCollaborationRosterEntry["role"],
  profiles: CoworkAgentProfile[],
): ThreadCollaborationRosterEntry {
  const profile = profileFor(id, profiles);
  return {
    agent_id: id,
    name: profile?.name ?? id,
    display_name: profile?.display_name?.trim() || profile?.name || id,
    avatar_url: profile?.avatar_url ?? null,
    icon: profile?.icon ?? null,
    role,
  };
}

export function coworkGroupToCollaborationRoster(
  group: CoworkGroupResponse | null | undefined,
  leaderId: string,
  profiles: CoworkAgentProfile[],
): ThreadCollaborationRosterEntry[] {
  const agentMembers =
    group?.state.roster.filter(
      (member) =>
        member.kind === "agent" &&
        member.role === "participant" &&
        !member.muted,
    ) ?? [];
  if (agentMembers.length === 0) return [];

  const leader = leaderId.trim();
  const roster: ThreadCollaborationRosterEntry[] = [];
  const seen = new Set<string>();
  const add = (entry: ThreadCollaborationRosterEntry) => {
    if (!entry.agent_id || seen.has(entry.agent_id)) return;
    seen.add(entry.agent_id);
    roster.push(entry);
  };

  if (leader) add(entryFor(leader, "tl", profiles));
  for (const member of agentMembers) {
    add(entryFor(member.id, member.id === leader ? "tl" : "member", profiles));
  }
  if (roster.length === 0) return [];
  if (roster.some((entry) => entry.role === "tl")) return roster;
  return roster.map((entry, index) => ({
    ...entry,
    role: index === 0 ? "tl" : "member",
  }));
}
