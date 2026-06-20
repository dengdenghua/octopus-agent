import { ServerIcon, ShieldCheckIcon, ShieldAlertIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  approveMCPTrust,
  listMCPTrust,
  loadMCPConfig,
  revokeMCPTrust,
  updateMCPConfig,
  type MCPTrustEntry,
} from "@/core/mcp/api";
import type { MCPConfig } from "@/core/mcp/types";
import { SettingsSection } from "./settings-section";

interface McpServer {
  name: string;
  type: string;
  enabled: boolean;
  command?: string;
  url?: string;
  description?: string;
}

export function McpSettingsPage() {
  const { t } = useI18n();
  const [servers, setServers] = useState<McpServer[]>([]);
  const [rawConfig, setRawConfig] = useState<MCPConfig | null>(null);
  const [trustEntries, setTrustEntries] = useState<MCPTrustEntry[]>([]);

  const fetchServers = useCallback(async () => {
    try {
      const data = await loadMCPConfig();
      setRawConfig(data);
      const mcpServers = data.mcp_servers || {};
      setServers(
        Object.entries(mcpServers).map(([name, cfg]: [string, any]) => ({
          name,
          type: cfg.type || "stdio",
          enabled: cfg.enabled !== false,
          command: cfg.command,
          url: cfg.url,
          description: cfg.description || "",
        })),
      );
    } catch (error) {
      console.error(error);
      toast.error(t.mcpSettings.toastLoadConfigFailed);
    }
  }, [t]);

  const fetchTrust = useCallback(async () => {
    try {
      const { entries } = await listMCPTrust();
      setTrustEntries(entries || []);
    } catch (error) {
      console.error(error);
    }
  }, []);

  useEffect(() => {
    fetchServers();
    fetchTrust();
  }, [fetchServers, fetchTrust]);

  const trustOf = (name: string) =>
    trustEntries.find((e) => e.server_name === name);

  const approve = async (name: string) => {
    try {
      await approveMCPTrust(name, [], "approved via UI");
      toast.success(t.mcpSettings.toastTrustSuccess(name));
      fetchTrust();
    } catch {
      toast.error(t.mcpSettings.toastTrustFailed);
    }
  };

  const revoke = async (name: string) => {
    try {
      await revokeMCPTrust(name);
      toast.success(t.mcpSettings.toastRevokeSuccess(name));
      fetchTrust();
    } catch {
      toast.error(t.mcpSettings.toastRevokeFailed);
    }
  };

  const toggleServer = async (name: string, enabled: boolean) => {
    setServers((prev) =>
      prev.map((s) => (s.name === name ? { ...s, enabled } : s)),
    );
    try {
      const data = rawConfig ?? (await loadMCPConfig());
      const mcpServers = { ...data.mcp_servers };
      if (mcpServers[name]) {
        mcpServers[name] = { ...mcpServers[name], enabled };
      }
      await updateMCPConfig({ mcp_servers: mcpServers });
      toast.success(t.mcpSettings.toastToggleSuccess(name, enabled));
    } catch {
      fetchServers();
      toast.error(t.mcpSettings.toastUpdateFailed);
    }
  };

  return (
    <div className="space-y-6">
      <SettingsSection
        title={t.mcpSettings.title}
        description={t.mcpSettings.description}
      >
        <div className="space-y-2">
          {servers.map((server) => {
            const trust = trustOf(server.name);
            const trusted = !!trust?.approved;
            return (
              <div
                key={server.name}
                className="flex items-center justify-between rounded-lg border p-3"
              >
                <div className="flex items-center gap-3">
                  <ServerIcon className="size-4 text-muted-foreground" />
                  <div>
                    <div className="font-medium flex items-center gap-2">
                      {server.name}
                      {trusted ? (
                        <span className="inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                          <ShieldCheckIcon className="size-3" />{" "}
                          {t.mcpSettings.trustedTag}
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                          <ShieldAlertIcon className="size-3" />{" "}
                          {t.mcpSettings.untrustedTag}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      {server.type}{" "}
                      {server.command
                        ? `· ${server.command}`
                        : server.url
                          ? `· ${server.url}`
                          : ""}
                    </div>
                    {server.description && (
                      <div className="text-xs text-muted-foreground">
                        {server.description}
                      </div>
                    )}
                    {!trusted && server.enabled && (
                      <div className="text-xs text-amber-600 dark:text-amber-400 mt-1">
                        {t.mcpSettings.unapprovedHint}
                      </div>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {trusted ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => revoke(server.name)}
                    >
                      {t.mcpSettings.revokeButton}
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => approve(server.name)}
                    >
                      {t.mcpSettings.trustButton}
                    </Button>
                  )}
                  <Switch
                    checked={server.enabled}
                    onCheckedChange={(v) => toggleServer(server.name, v)}
                  />
                </div>
              </div>
            );
          })}
          {servers.length === 0 && (
            <div className="text-sm text-muted-foreground text-center py-4">
              {t.mcpSettings.noServers}
            </div>
          )}
        </div>
      </SettingsSection>
    </div>
  );
}
