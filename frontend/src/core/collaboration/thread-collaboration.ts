export interface ThreadCollaborationRosterEntry {
  agent_id: string;
  name: string;
  display_name: string;
  avatar_url?: string | null;
  icon?: string | null;
  role: "tl" | "member";
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function stringsFromUnknown(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter(Boolean);
}

function rosterFromUnknown(value: unknown): ThreadCollaborationRosterEntry[] {
  if (!Array.isArray(value)) return [];
  const roster: ThreadCollaborationRosterEntry[] = [];
  for (const item of value) {
    const record = recordFromUnknown(item);
    if (!record) continue;
    const agentId = firstString(
      record.agent_id,
      record.name,
      record.id,
      record.ref,
    );
    if (!agentId) continue;
    const role = record.role === "tl" ? "tl" : "member";
    roster.push({
      agent_id: agentId,
      name: firstString(record.name, agentId),
      display_name: firstString(record.display_name, record.name, agentId),
      avatar_url: firstString(record.avatar_url) || null,
      icon: firstString(record.icon) || null,
      role,
    });
  }
  return roster;
}

function collaborationSourcesFromThread(
  metadata?: Record<string, unknown> | null,
  values?: Record<string, unknown> | null,
): Record<string, unknown>[] {
  const sources: Record<string, unknown>[] = [];
  const meta = recordFromUnknown(metadata);
  const vals = recordFromUnknown(values);
  if (meta) {
    sources.push(meta);
    const context = recordFromUnknown(meta.context);
    if (context) sources.push(context);
  }
  if (vals) {
    sources.push(vals);
    const context = recordFromUnknown(vals.context);
    if (context) sources.push(context);
  }
  return sources;
}

export function collaborationRosterFromThread(
  metadata: Record<string, unknown> | null | undefined,
  values: Record<string, unknown> | null | undefined,
  leaderId: string,
): ThreadCollaborationRosterEntry[] {
  const byId = new Map<string, ThreadCollaborationRosterEntry>();
  const addEntry = (entry: ThreadCollaborationRosterEntry) => {
    if (!entry.agent_id || byId.has(entry.agent_id)) return;
    byId.set(entry.agent_id, entry);
  };

  const sources = collaborationSourcesFromThread(metadata, values);
  for (const source of sources) {
    for (const entry of rosterFromUnknown(source.agent_roster)) {
      addEntry(entry);
    }
  }

  const leader = leaderId.trim();
  if (byId.size === 0 && leader) {
    const taskAgentRefs = sources.flatMap((source) =>
      stringsFromUnknown(source.task_agent_refs),
    );
    const collaboratorRefs = Array.from(new Set(taskAgentRefs)).filter(
      (id) => id !== leader,
    );
    if (collaboratorRefs.length > 0) {
      addEntry({
        agent_id: leader,
        name: leader,
        display_name: leader,
        role: "tl",
      });
      for (const id of collaboratorRefs) {
        addEntry({
          agent_id: id,
          name: id,
          display_name: id,
          role: "member",
        });
      }
    }
  }

  const roster = Array.from(byId.values());
  if (roster.length === 0) return [];
  const hasLeader = roster.some((entry) => entry.role === "tl");
  if (hasLeader) return roster;
  return roster.map((entry, index) => ({
    ...entry,
    role:
      entry.agent_id === leader || (!leader && index === 0) ? "tl" : "member",
  }));
}
