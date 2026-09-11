import type { ThreadCollaborationRosterEntry } from "@/core/collaboration/thread-collaboration";

import type { CollaborationSession, CoworkGroupResponse, CoworkMember } from "./types";

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
  identity?: {
    kind?: "agent" | "role";
    driver?: "ai" | "human";
    accountable_owner?: string | null;
  },
): ThreadCollaborationRosterEntry {
  const profile = profileFor(id, profiles);
  const entry: ThreadCollaborationRosterEntry = {
    agent_id: id,
    name: profile?.name ?? id,
    display_name: profile?.display_name?.trim() || profile?.name || id,
    avatar_url: profile?.avatar_url ?? null,
    icon: profile?.icon ?? null,
    role,
  };
  // The identity axes default to their narrowest values (bare AI, self-driven,
  // no owner) — matching the backend fold defaults for legacy rosters that
  // predate the role/driver fields.
  entry.kind = identity?.kind ?? "agent";
  entry.driver = identity?.driver ?? "ai";
  entry.accountable_owner = identity?.accountable_owner ?? "";
  return entry;
}

function membersToCollaborationRoster(
  members: CoworkMember[] | null | undefined,
  leaderId: string,
  profiles: CoworkAgentProfile[],
): ThreadCollaborationRosterEntry[] {
  // 数字员工 (kind="role") speak in the room like any other AI-side member —
  // only humans are excluded from the collaboration roster.
  const agentMembers =
    members?.filter(
      (member) =>
        member.kind !== "human" &&
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

  if (leader) {
    const leaderMember = members?.find((member) => member.id === leader);
    add(
      entryFor(leader, "tl", profiles, {
        kind: leaderMember && leaderMember.kind !== "human" ? leaderMember.kind : "agent",
        driver: leaderMember?.driver,
        accountable_owner: leaderMember?.accountable_owner,
      }),
    );
  }
  for (const member of agentMembers) {
    add(
      entryFor(member.id, member.id === leader ? "tl" : "member", profiles, {
        kind: member.kind === "role" ? "role" : "agent",
        driver: member.driver,
        accountable_owner: member.accountable_owner,
      }),
    );
  }
  if (roster.length === 0) return [];
  if (roster.some((entry) => entry.role === "tl")) return roster;
  return roster.map((entry, index) => ({
    ...entry,
    role: index === 0 ? "tl" : "member",
  }));
}

export function coworkGroupToCollaborationRoster(
  group: CoworkGroupResponse | null | undefined,
  leaderId: string,
  profiles: CoworkAgentProfile[],
): ThreadCollaborationRosterEntry[] {
  return membersToCollaborationRoster(group?.state.roster, leaderId, profiles);
}

export function coworkSessionToCollaborationRoster(
  session: CollaborationSession | null | undefined,
  leaderId: string,
  profiles: CoworkAgentProfile[],
): ThreadCollaborationRosterEntry[] {
  return membersToCollaborationRoster(session?.roster, leaderId, profiles);
}
