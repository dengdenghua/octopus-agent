export function taskWorkspaceRoute({
  agentId,
  prompt,
}: {
  agentId?: string | null;
  prompt?: string | null;
} = {}) {
  const params = new URLSearchParams();
  const cleanPrompt = prompt?.trim() ?? "";
  const cleanAgent = agentId?.trim() ?? "";
  if (cleanPrompt) params.set("prompt", cleanPrompt);
  if (cleanAgent && cleanAgent !== "general") params.set("agent", cleanAgent);
  const query = params.toString() ? `?${params.toString()}` : "";
  return `/workspace/realtime/new${query}`;
}
