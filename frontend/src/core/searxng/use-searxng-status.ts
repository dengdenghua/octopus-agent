/**
 * Drive the optional one-click local SearXNG (private web-search backend).
 *
 * `/api/searxng/status` (public) reports liveness; `/api/searxng/{enable,disable}`
 * (auth-gated) deploy / stop the Docker container. The agent's global fetch
 * interceptor attaches the bearer token, so plain `fetch` is enough here.
 *
 * `up=false` just means web search uses the zero-config DuckDuckGo backend — the
 * whole feature degrades gracefully when Docker is absent.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

export interface SearxngStatus {
  up: boolean;
  heartbeat: boolean;
  docker_present: boolean;
  managed: boolean;
  autostart: boolean;
  url?: string;
  port?: string;
  restart_count?: number;
}

const STATUS_KEY = ["searxng-status"] as const;

const EMPTY: SearxngStatus = {
  up: false,
  heartbeat: false,
  docker_present: false,
  managed: false,
  autostart: false,
};

async function fetchSearxngStatus(signal?: AbortSignal): Promise<SearxngStatus> {
  const res = await fetch(`${getBackendBaseURL()}/api/searxng/status`, { signal });
  if (!res.ok) return EMPTY;
  const d = (await res.json()) as Partial<SearxngStatus>;
  return {
    up: Boolean(d.up),
    heartbeat: Boolean(d.heartbeat),
    docker_present: Boolean(d.docker_present),
    managed: Boolean(d.managed),
    autostart: Boolean(d.autostart),
    url: d.url,
    port: d.port,
    restart_count: d.restart_count,
  };
}

export function useSearxngStatus(): {
  status: SearxngStatus | undefined;
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery({
    queryKey: STATUS_KEY,
    queryFn: ({ signal }) => fetchSearxngStatus(signal),
    // Poll fast while a managed container is still coming up (image pull + boot),
    // slow once it's settled.
    refetchInterval: (query) => {
      const s = query.state.data;
      return s && s.managed && !s.up ? 5_000 : 20_000;
    },
    staleTime: 4_000,
    refetchOnWindowFocus: false,
  });
  return { status: data, isLoading };
}

export function useSearxngControl(): {
  enable: () => void;
  disable: () => void;
  isPending: boolean;
} {
  const qc = useQueryClient();
  const post = async (action: "enable" | "disable"): Promise<void> => {
    const res = await fetch(`${getBackendBaseURL()}/api/searxng/${action}`, {
      method: "POST",
    });
    if (!res.ok) throw new Error(`searxng ${action} failed: ${res.status}`);
  };
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: STATUS_KEY });
  };
  const enable = useMutation({ mutationFn: () => post("enable"), onSettled: invalidate });
  const disable = useMutation({ mutationFn: () => post("disable"), onSettled: invalidate });
  return {
    enable: () => enable.mutate(),
    disable: () => disable.mutate(),
    isPending: enable.isPending || disable.isPending,
  };
}
