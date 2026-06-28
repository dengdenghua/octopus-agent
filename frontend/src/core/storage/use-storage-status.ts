/**
 * Poll the agent's view of the octopus-storage sibling (本地数据库 / File Agent).
 *
 * The agent exposes `/api/storage/status` (backed by the co-launch heartbeat), so
 * the UI can show a live up/down light without talking to storage:8767 directly.
 * `up=false` means search_documents degrades; the heartbeat relaunches storage
 * when autostart owns its lifecycle.
 */
import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

export interface StorageStatus {
  up: boolean;
  heartbeat: boolean;
  restart_count?: number;
  last_check_ts?: number;
}

async function fetchStorageStatus(signal?: AbortSignal): Promise<StorageStatus> {
  const res = await fetch(`${getBackendBaseURL()}/api/storage/status`, {
    signal,
  });
  if (!res.ok) return { up: false, heartbeat: false };
  const data = (await res.json()) as Partial<StorageStatus>;
  return {
    up: Boolean(data.up),
    heartbeat: Boolean(data.heartbeat),
    restart_count: data.restart_count,
    last_check_ts: data.last_check_ts,
  };
}

export function useStorageStatus(): {
  status: StorageStatus | undefined;
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery({
    queryKey: ["storage-status"],
    queryFn: ({ signal }) => fetchStorageStatus(signal),
    refetchInterval: 20_000,
    staleTime: 15_000,
    refetchOnWindowFocus: false,
  });
  return { status: data, isLoading };
}
