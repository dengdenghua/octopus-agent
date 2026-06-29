export function toHashRouterShellUrl(route: string) {
  if (!route) return "/#/";
  if (route.startsWith("/#/")) return route;
  if (route.startsWith("#/")) return `/${route}`;
  const normalized = route.startsWith("/") ? route : `/${route}`;
  return `/#${canonicalWorkspaceHashRoute(normalized).slice(1)}`;
}

function safeDecodePathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

function canonicalWorkspaceHashRoute(route: string): string {
  const normalized = route.startsWith("/") ? route : `/${route}`;

  if (
    normalized === "/workspace" ||
    normalized === "/workspace/" ||
    normalized === "/workspace/realtime" ||
    normalized === "/workspace/realtime/"
  ) {
    return "#/workspace/realtime/new";
  }

  if (normalized === "/workspace/swarm" || normalized === "/workspace/swarm/") {
    return "#/workspace/realtime/new";
  }

  if (
    normalized === "/workspace/code" ||
    normalized === "/workspace/code/new" ||
    normalized === "/workspace/team" ||
    normalized === "/workspace/team/new"
  ) {
    return "#/workspace/realtime/new";
  }

  const legacyCodeThread = normalized.match(/^\/workspace\/code\/([^/?#]+)$/);
  if (legacyCodeThread) {
    return `#/workspace/realtime/${legacyCodeThread[1]}`;
  }

  const legacyTeamThread = normalized.match(
    /^\/workspace\/team\/(?!join(?:[/?#]|$))([^?#]+)(\?[^#]*)?$/,
  );
  if (legacyTeamThread) {
    const [, threadId, search = ""] = legacyTeamThread;
    return `#/workspace/realtime/${threadId}${search}`;
  }

  const legacyAgentChat = normalized.match(
    /^\/workspace\/agents\/([^/?#]+)\/chats\/([^?#]+)(\?[^#]*)?$/,
  );
  if (legacyAgentChat) {
    const [, agent, threadId, search = ""] = legacyAgentChat;
    const params = new URLSearchParams(search);
    if (agent && !params.has("agent")) {
      params.set("agent", safeDecodePathSegment(agent));
    }
    const query = params.toString() ? `?${params.toString()}` : "";
    return threadId === "new"
      ? `#/workspace/realtime/new${query}`
      : `#/workspace/realtime/${threadId}${query}`;
  }

  return `#${normalized}`;
}

function normalizeLegacyHashRoute(hash: string): string {
  const route = hash.startsWith("#") ? hash.slice(1) : hash;
  const normalized = route.startsWith("/") ? route : `/${route}`;
  const canonical = canonicalWorkspaceHashRoute(normalized);
  if (canonical !== `#${normalized}`) return canonical;
  return hash;
}

function normalizeHistoryUrl(
  url: string | URL | null | undefined,
): string | URL | null | undefined {
  if (typeof url !== "string") return url;
  if (url.startsWith("/#/")) return url;
  if (url.startsWith("#/")) return `/${url}`;
  if (!url.startsWith("/")) return url;
  return toHashRouterShellUrl(url);
}

export function normalizeHashRouterShellUrl() {
  if (typeof window === "undefined") return;
  const { pathname, search, hash } = window.location;
  if (!hash.startsWith("#/")) {
    if (pathname === "/" || pathname === "") return;
    window.history.replaceState(
      window.history.state,
      "",
      toHashRouterShellUrl(`${pathname}${search}`),
    );
    return;
  }
  const normalizedHash = normalizeLegacyHashRoute(hash);
  if ((pathname === "/" || pathname === "") && normalizedHash === hash) return;
  window.history.replaceState(
    window.history.state,
    "",
    `/${search}${normalizedHash}`,
  );
}

export function installHashRouterShellUrlNormalizer() {
  normalizeHashRouterShellUrl();
  if (typeof window === "undefined") return;
  const win = window as Window & {
    __octopusHashRouterPatched?: boolean;
  };
  if (!win.__octopusHashRouterPatched) {
    const originalPushState = window.history.pushState.bind(window.history);
    const originalReplaceState = window.history.replaceState.bind(
      window.history,
    );
    window.history.pushState = function patchedPushState(data, unused, url) {
      return originalPushState(data, unused, normalizeHistoryUrl(url));
    } as typeof window.history.pushState;
    window.history.replaceState = function patchedReplaceState(
      data,
      unused,
      url,
    ) {
      return originalReplaceState(data, unused, normalizeHistoryUrl(url));
    } as typeof window.history.replaceState;
    win.__octopusHashRouterPatched = true;
  }
  window.addEventListener("hashchange", normalizeHashRouterShellUrl);
}
