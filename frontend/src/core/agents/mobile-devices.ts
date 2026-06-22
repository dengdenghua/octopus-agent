import { useQuery } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

import type { Agent } from "./types";

/** A phone (octopus-mobile) connected to this gateway. */
interface MobileDevice {
  device_id: string;
  agent_id: string;
  name: string;
  model: string;
  online: boolean;
  last_seen: number;
}

interface MobileDevicesResponse {
  devices: MobileDevice[];
}

/** Turn a connected phone into an `Agent` so it shows up in the team pickers
 * and roster exactly like a built-in agent — addable as a remote member. The
 * synthetic `name` (`mobile_*`) is what the team runner dispatches to. */
function deviceToAgent(d: MobileDevice): Agent {
  const label = d.name?.trim() || d.model?.trim() || "我的手机";
  const status = d.online ? "在线" : "离线";
  return {
    name: d.agent_id,
    display_name: label,
    description: `本机手机 · ${d.model || "Android"} · ${status},用无障碍直接操控设备`,
    icon: "📱",
    model: null,
    tool_groups: null,
  };
}

/**
 * Connected phones (octopus-mobile) as addable team members. Empty when none
 * are paired or the backend is offline — the pickers just fall back to the
 * built-in agents.
 */
export function useMobileDevices(): { mobileAgents: Agent[]; isLoading: boolean } {
  const { data, isLoading } = useQuery({
    queryKey: ["mobile-devices"],
    queryFn: async ({ signal }): Promise<MobileDevicesResponse | null> => {
      try {
        const res = await fetch(`${getBackendBaseURL()}/api/mobile/devices`, {
          signal,
        });
        if (!res.ok) return null;
        return (await res.json()) as MobileDevicesResponse;
      } catch {
        return null;
      }
    },
    refetchOnWindowFocus: false,
    // Phones come and go — refresh more often than the static agent list.
    staleTime: 15_000,
    refetchInterval: 20_000,
  });
  const mobileAgents = (data?.devices ?? []).map(deviceToAgent);
  return { mobileAgents, isLoading };
}
