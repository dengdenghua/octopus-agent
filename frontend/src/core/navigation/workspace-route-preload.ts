/** Lazy workspace route loaders shared by the router and sidebar prefetch. */

export const loadAgentsPage = () => import("@/app/workspace/agents/page");
export const loadCommunityPage = () => import("@/app/workspace/community/page");
export const loadIntelligencePage = () =>
  import("@/app/workspace/intelligence/page");
export const loadEvolutionPage = () => import("@/app/workspace/evolution/page");
export const loadProjectsPage = () => import("@/app/workspace/projects/page");
export const loadDesignPage = () => import("@/app/workspace/design/page");
export const loadPaperTradingPage = () =>
  import("@/app/workspace/paper-trading/page");

const loaders: ReadonlyArray<readonly [string, () => Promise<unknown>]> = [
  ["/workspace/agents", loadAgentsPage],
  ["/workspace/community", loadCommunityPage],
  ["/workspace/intelligence", loadIntelligencePage],
  ["/workspace/evolution", loadEvolutionPage],
  ["/workspace/projects", loadProjectsPage],
  ["/workspace/design", loadDesignPage],
  ["/workspace/paper-trading", loadPaperTradingPage],
];

/** Warm a route chunk on intent (hover/focus) without delaying navigation. */
export function preloadWorkspaceRoute(to: string): void {
  const pathname = to.split("?", 1)[0] || to;
  const loader = loaders.find(([prefix]) => pathname.startsWith(prefix))?.[1];
  if (loader) void loader().catch(() => undefined);
}
