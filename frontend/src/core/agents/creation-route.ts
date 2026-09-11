export function agentCreationRoute(options: { cloudExpertId?: string; roleId?: string; role?: string; focus?: string; capability?: string; template?: string; returnTo?: "hud" } = {}) {
  const params = new URLSearchParams();
  if (options.cloudExpertId) params.set("cloudExpert", options.cloudExpertId);
  for (const key of ["roleId", "role", "focus", "capability", "template"] as const) {
    if (options[key]) params.set(key, options[key]!);
  }
  if (options.returnTo) params.set("return", options.returnTo);
  return `/workspace/agents/new${params.size ? `?${params}` : ""}`;
}
