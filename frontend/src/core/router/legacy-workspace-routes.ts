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
