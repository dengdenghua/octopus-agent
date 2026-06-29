export function legacyTeamWorkspaceTarget(
  threadId?: string | null,
  search = "",
): string {
  const suffix = search ? (search.startsWith("?") ? search : `?${search}`) : "";
  const cleanId = threadId?.trim();
  if (!cleanId || cleanId === "new") {
    return `/workspace/realtime/new${suffix}`;
  }
  return `/workspace/realtime/${encodeURIComponent(cleanId)}${suffix}`;
}

export function legacyAgentChatWorkspaceTarget(
  agentName?: string | null,
  threadId?: string | null,
  search = "",
): string {
  const params = new URLSearchParams(search);
  const agent = agentName?.trim();
  if (agent && !params.has("agent")) {
    params.set("agent", agent);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const cleanId = threadId?.trim();
  if (!cleanId || cleanId === "new") {
    return `/workspace/realtime/new${suffix}`;
  }
  return `/workspace/realtime/${encodeURIComponent(cleanId)}${suffix}`;
}
