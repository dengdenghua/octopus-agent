import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";

import type {
  FactCreateRequest,
  FactPatchRequest,
  MemoryConfig,
  MemoryConfigPatch,
  MemoryData,
  MemorySearchResult,
} from "./types";

export async function getMemory(): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to get memory: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}

export const loadMemory = getMemory;

export async function searchMemory(
  query: string,
  limit = 20,
): Promise<MemorySearchResult[]> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    { headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to search memory: ${res.statusText}`);
  return (await res.json()) as MemorySearchResult[];
}

export async function reloadMemory(): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/reload`, {
    method: "POST",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to reload memory: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}

export async function clearMemory(): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to clear memory: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}

export async function createFact(
  request: FactCreateRequest,
): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/facts`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to create fact: ${res.statusText}`);
  }
  return (await res.json()) as MemoryData;
}

export const createMemoryFact = createFact;

export async function deleteFact(factId: string): Promise<MemoryData> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
    { method: "DELETE", headers: authHeaders() },
  );
  if (!res.ok) throw new Error(`Failed to delete fact: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}

export const deleteMemoryFact = deleteFact;

export async function updateFact(
  factId: string,
  request: FactPatchRequest,
): Promise<MemoryData> {
  const res = await fetch(
    `${getBackendBaseURL()}/api/memory/facts/${encodeURIComponent(factId)}`,
    {
      method: "PATCH",
      headers: jsonAuthHeaders(),
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const err = (await res.json().catch(() => ({}))) as { detail?: string };
    throw new Error(err.detail ?? `Failed to update fact: ${res.statusText}`);
  }
  return (await res.json()) as MemoryData;
}

export const updateMemoryFact = updateFact;

export async function getMemoryConfig(): Promise<MemoryConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/config`, {
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to get memory config: ${res.statusText}`);
  return (await res.json()) as MemoryConfig;
}

export async function updateMemoryConfig(
  patch: MemoryConfigPatch,
): Promise<MemoryConfig> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/config`, {
    method: "PUT",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(patch),
  });
  if (!res.ok)
    throw new Error(`Failed to update memory config: ${res.statusText}`);
  return (await res.json()) as MemoryConfig;
}

export async function exportMemory(): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/export`, {
    headers: authHeaders(),
  });
  if (!res.ok) throw new Error(`Failed to export memory: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}

export async function importMemory(data: MemoryData): Promise<MemoryData> {
  const res = await fetch(`${getBackendBaseURL()}/api/memory/import`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to import memory: ${res.statusText}`);
  return (await res.json()) as MemoryData;
}
