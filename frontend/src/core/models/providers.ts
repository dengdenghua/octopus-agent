import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "../config";
import { authHeaders } from "@/core/auth/api";

import type { ProviderCapabilities } from "./types";

async function loadProviders(): Promise<ProviderCapabilities[]> {
  const res = await fetch(`${getBackendBaseURL()}/api/providers`, {
    headers: authHeaders(),
  });
  if (!res.ok) {
    throw new Error(`Failed to load providers: ${res.status}`);
  }
  const body = (await res.json()) as { providers?: ProviderCapabilities[] };
  return body.providers ?? [];
}

/**
 * Hook: providers + capability flags. Backs features like
 * "grey upload-image when provider.supports_vision === false" and
 * "show a ⚡ cache badge on models whose provider supports it".
 *
 * Cached for 5 min — capability flags are static per deploy.
 */
export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: loadProviders,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Convenience: look up one provider's caps by name. Returns null when
 * providers haven't loaded yet or the name isn't registered.
 */
export function useProvider(name?: string | null): ProviderCapabilities | null {
  const { data } = useProviders();
  if (!name || !data) return null;
  return data.find((p) => p.name === name) ?? null;
}
