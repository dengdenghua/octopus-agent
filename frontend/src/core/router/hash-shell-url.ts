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

function splitRouteSearch(route: string): { pathname: string; search: string } {
  const queryIndex = route.indexOf("?");
  if (queryIndex === -1) return { pathname: route, search: "" };
  return {
    pathname: route.slice(0, queryIndex) || "/",
    search: route.slice(queryIndex),
  };
}

function canonicalWorkspaceHashRoute(route: string): string {
  const normalized = route.startsWith("/") ? route : `/${route}`;
  const { pathname, search } = splitRouteSearch(normalized);

  if (
    pathname === "/workspace" ||
    pathname === "/workspace/" ||
    pathname === "/workspace/realtime" ||
    pathname === "/workspace/realtime/"
  ) {
    return `#/workspace/realtime/new${search}`;
  }

  if (pathname === "/workspace/swarm" || pathname === "/workspace/swarm/") {
    return `#/workspace/realtime/new${search}`;
  }

  if (
    pathname === "/workspace/code" ||
    pathname === "/workspace/code/new" ||
    pathname === "/workspace/team" ||
    pathname === "/workspace/team/new"
  ) {
    return `#/workspace/realtime/new${search}`;
  }

  const legacyCodeThread = pathname.match(/^\/workspace\/code\/([^/?#]+)$/);
  if (legacyCodeThread) {
    return `#/workspace/realtime/${legacyCodeThread[1]}${search}`;
  }

  const legacyTeamThread = pathname.match(
    /^\/workspace\/team\/(?!join(?:\/|$))([^/?#]+)$/,
  );
  if (legacyTeamThread) {
    const [, threadId] = legacyTeamThread;
    return `#/workspace/realtime/${threadId}${search}`;
  }

  const legacyAgentChat = pathname.match(
    /^\/workspace\/agents\/([^/?#]+)\/chats\/([^/?#]+)$/,
  );
  if (legacyAgentChat) {
    const [, agent, threadId] = legacyAgentChat;
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
