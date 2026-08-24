import { useEffect } from "react";

import {
  fetchCloudInstalled,
  fetchRuntimePluginStatus,
  type RuntimePluginStatus,
} from "@/core/agents/agent-world-api";
import { setModuleAvailabilitySnapshot } from "@/core/modules/enabled-modules";
import { swallow } from "@/core/utils/log";

import { WORKBENCH_BUILTIN_APPS } from "./apps";

let inFlight: Promise<Record<string, boolean>> | null = null;

async function runtimeAvailability(
  runtimePlugin: string,
  installedFallback: boolean,
): Promise<{ available: boolean; status: RuntimePluginStatus | null }> {
  try {
    const status = await fetchRuntimePluginStatus(runtimePlugin);
    return {
      available: Boolean(status.installed && status.enabled),
      status,
    };
  } catch (error) {
    // Older backends do not expose the lifecycle endpoint. Keep their package
    // install result usable while upgrades roll out.
    swallow(error);
    return { available: installedFallback, status: null };
  }
}

/**
 * Reconcile mutable workbench packages with navigation surfaces. This is the
 * single source for direct-route, sidebar, desktop and Dock availability.
 */
export function syncWorkbenchAvailability(): Promise<Record<string, boolean>> {
  if (inFlight) return inFlight;
  inFlight = (async () => {
    const installed = await fetchCloudInstalled();
    const installedSet = new Set(installed.plugins);
    const availability: Record<string, boolean> = {};

    await Promise.all(
      WORKBENCH_BUILTIN_APPS.map(async (app) => {
        if (app.delivery !== "remote") {
          availability[app.moduleId] = true;
          return;
        }
        const installedFallback = app.packageId
          ? installedSet.has(app.packageId)
          : false;
        if (app.runtimePlugin) {
          availability[app.moduleId] = (
            await runtimeAvailability(app.runtimePlugin, installedFallback)
          ).available;
          return;
        }
        availability[app.moduleId] = installedFallback;
      }),
    );

    setModuleAvailabilitySnapshot(availability);
    return availability;
  })().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

export function useWorkbenchAvailabilitySync(): void {
  useEffect(() => {
    void syncWorkbenchAvailability().catch(swallow);
  }, []);
}
