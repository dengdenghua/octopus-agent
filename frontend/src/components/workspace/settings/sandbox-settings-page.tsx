import { useCallback } from "react";
import { toast } from "sonner";

import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import { normalizeNetworkAccess, normalizePermissionMode } from "@/core/permissions";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

type ExecutionEnvironment = "sandbox" | "local";
type SandboxPermissionMode = "default" | "acceptEdits" | "bypassPermissions";
type NetworkTier = "deny" | "common" | "full";

export default function SandboxSettingsPage() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const copy = t.sandboxSettings;

  const context = settings.context as typeof settings.context & {
    sandbox_mode?: string;
    approval_policy?: string;
    network_access?: unknown;
  };
  const environment: ExecutionEnvironment =
    context.execution_environment === "local" ? "local" : "sandbox";
  const permission = normalizePermissionMode(context.permission_mode);
  const networkTier: NetworkTier = normalizeNetworkAccess(context.network_access) ?? "deny";

  const applyEnvironment = useCallback(
    (next: ExecutionEnvironment) => {
      const label = copy.env[next].label;
      try {
        setSettings("context", {
          ...context,
          execution_environment: next,
          sandbox_mode: next === "local" ? "full" : "sandbox",
        } as Partial<typeof settings.context>);
        toast.success(copy.toastEnvSwitched(label));
      } catch {
        toast.error(copy.toastFailed(label));
      }
    },
    [context, copy, setSettings, settings],
  );

  const applyPermission = useCallback(
    (next: SandboxPermissionMode) => {
      const label = copy.permission[next].label;
      try {
        setSettings("context", {
          ...context,
          permission_mode: next,
          approval_policy: next === "bypassPermissions" ? "never" : "on-request",
        } as Partial<typeof settings.context>);
        toast.success(copy.toastPermissionSwitched(label));
      } catch {
        toast.error(copy.toastFailed(label));
      }
    },
    [context, copy, setSettings, settings],
  );

  const applyNetwork = useCallback(
    (next: NetworkTier) => {
      const label = copy.network[next].label;
      try {
        setSettings("context", {
          ...context,
          network_access: next,
        } as Partial<typeof settings.context>);
        toast.success(copy.toastNetworkSwitched(label));
      } catch {
        toast.error(copy.toastFailed(label));
      }
    },
    [context, copy, setSettings, settings],
  );

  return (
    <div className="flex flex-col gap-6 text-sm">
      <SettingsSection title={copy.title} description={copy.description}>
        {/* ─── Execution environment (independent axis) ─── */}
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {copy.envTitle}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">{copy.envDesc}</p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {(["sandbox", "local"] as const).map((id) => {
              const active = environment === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => applyEnvironment(id)}
                  disabled={active}
                  aria-pressed={active}
                  className={cn(
                    "flex flex-col gap-2 rounded-lg border p-4 text-left transition",
                    active
                      ? "border-primary bg-primary/5 ring-1 ring-primary/40"
                      : "border-border-default hover:border-primary/40",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {copy.env[id].label}
                    </span>
                    {active && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                        {copy.activeTag}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-snug text-muted-foreground">
                    {copy.env[id].description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* ─── Permission level (independent axis) ─── */}
        <div className="mt-8">
          <h3 className="text-sm font-semibold text-foreground">
            {copy.permissionTitle}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {copy.permissionDesc}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(
              ["default", "acceptEdits", "bypassPermissions"] as const
            ).map((id) => {
              const active = permission === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => applyPermission(id)}
                  disabled={active}
                  aria-pressed={active}
                  className={cn(
                    "flex flex-col gap-2 rounded-lg border p-4 text-left transition",
                    active
                      ? "border-primary bg-primary/5 ring-1 ring-primary/40"
                      : "border-border-default hover:border-primary/40",
                    id === "bypassPermissions" &&
                      !active &&
                      "text-warning/90 hover:text-warning",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {copy.permission[id].label}
                    </span>
                    {active && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                        {copy.activeTag}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-snug text-muted-foreground">
                    {copy.permission[id].description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        {/* ─── Network access (independent axis) ─── */}
        <div className="mt-8">
          <h3 className="text-sm font-semibold text-foreground">
            {copy.networkTitle}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {copy.networkDesc}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            {(["deny", "common", "full"] as const).map((id) => {
              const active = networkTier === id;
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => applyNetwork(id)}
                  disabled={active}
                  aria-pressed={active}
                  className={cn(
                    "flex flex-col gap-2 rounded-lg border p-4 text-left transition",
                    active
                      ? "border-primary bg-primary/5 ring-1 ring-primary/40"
                      : "border-border-default hover:border-primary/40",
                  )}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      {copy.network[id].label}
                    </span>
                    {active && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs font-medium text-primary">
                        {copy.activeTag}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-snug text-muted-foreground">
                    {copy.network[id].description}
                  </p>
                </button>
              );
            })}
          </div>
        </div>

        <p className="mt-4 text-xs text-muted-foreground/80">{copy.scopeNote}</p>
        <p className="mt-1.5 text-xs text-warning">{copy.restartHint}</p>
      </SettingsSection>
    </div>
  );
}
