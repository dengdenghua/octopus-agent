import {
  LoaderCircleIcon,
  ServerIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
import { isSupportedMcpUrl } from "./settings-resilience";
import { getSettingsUxCopy } from "./settings-ux-copy";

interface McpServer {
  name: string;
  type: string;
  enabled: boolean;
  command?: string;
  url?: string;
  description?: string;
}

type LoadState = "loading" | "ready" | "error";

export function McpSettingsPage() {
  const { t, locale } = useI18n();
  const copy = getSettingsUxCopy(locale).mcp;
  const [servers, setServers] = useState<McpServer[]>([]);
  const [serversLoadState, setServersLoadState] =
    useState<LoadState>("loading");
  const [rawConfig, setRawConfig] = useState<MCPConfig | null>(null);
  const [trustEntries, setTrustEntries] = useState<MCPTrustEntry[]>([]);
  const [trustLoadState, setTrustLoadState] = useState<LoadState>("loading");
  const [addName, setAddName] = useState("");
  const [addUrl, setAddUrl] = useState("");
  const [addAuth, setAddAuth] = useState("");
  const [adding, setAdding] = useState(false);
  const [pendingServer, setPendingServer] = useState<string | null>(null);

  const fetchServers = useCallback(async (showLoading = true) => {
    if (showLoading) setServersLoadState("loading");
    try {
      const data = await loadMCPConfig();
      setRawConfig(data);
      const mcpServers = data.mcp_servers || {};
      setServers(
        Object.entries(mcpServers).map(([name, cfg]) => {
          const c = cfg as Partial<{
            type: string;
            command: string;
            url: string;
            enabled: boolean;
            description: string;
          }>;
          return {
            name,
            type: c.type || "stdio",
            enabled: c.enabled !== false,
            command: c.command,
            url: c.url,
            description: c.description || "",
          };
        }),
      );
      setServersLoadState("ready");
    } catch (error) {
      console.error(error);
      setServersLoadState("error");
    }
  }, []);

  const fetchTrust = useCallback(async () => {
    setTrustLoadState("loading");
    try {
      const { entries } = await listMCPTrust();
      setTrustEntries(entries || []);
      setTrustLoadState("ready");
    } catch (error) {
      console.error(error);
      setTrustEntries([]);
      setTrustLoadState("error");
    }
  }, []);

  useEffect(() => {
    void fetchServers();
    void fetchTrust();
  }, [fetchServers, fetchTrust]);

  const trustOf = (name: string) =>
    trustEntries.find((e) => e.server_name === name);

  const approve = async (name: string) => {
    if (pendingServer || trustLoadState !== "ready") return;
    setPendingServer(name);
    try {
      await approveMCPTrust(name, [], "approved via UI");
      toast.success(t.mcpSettings.toastTrustSuccess(name));
      await fetchTrust();
    } catch {
      toast.error(t.mcpSettings.toastTrustFailed);
    } finally {
      setPendingServer(null);
    }
  };

  const revoke = async (name: string) => {
    if (pendingServer || trustLoadState !== "ready") return;
    setPendingServer(name);
    try {
      await revokeMCPTrust(name);
      toast.success(t.mcpSettings.toastRevokeSuccess(name));
      await fetchTrust();
    } catch {
      toast.error(t.mcpSettings.toastRevokeFailed);
    } finally {
      setPendingServer(null);
    }
  };

  const toggleServer = async (name: string, enabled: boolean) => {
    if (pendingServer || serversLoadState !== "ready") return;
    const previousServers = servers;
    setPendingServer(name);
    setServers((prev) =>
      prev.map((s) => (s.name === name ? { ...s, enabled } : s)),
    );
    try {
      const data = rawConfig ?? (await loadMCPConfig());
      const mcpServers = { ...data.mcp_servers };
      if (mcpServers[name]) {
        mcpServers[name] = { ...mcpServers[name], enabled };
      }
      const nextConfig = { ...data, mcp_servers: mcpServers };
      await updateMCPConfig(nextConfig);
      setRawConfig(nextConfig);
      toast.success(t.mcpSettings.toastToggleSuccess(name, enabled));
    } catch {
      setServers(previousServers);
      toast.error(t.mcpSettings.toastUpdateFailed);
    } finally {
      setPendingServer(null);
    }
  };

  const addServer = async () => {
    const name = addName.trim();
    const url = addUrl.trim();
    const duplicate = servers.some(
      (server) => server.name.toLowerCase() === name.toLowerCase(),
    );
    if (!name || !isSupportedMcpUrl(url)) {
      toast.error(t.mcpSettings.toastAddInvalid);
      return;
    }
    if (duplicate) {
      toast.error(copy.duplicateName(name));
      return;
    }
    if (serversLoadState !== "ready") return;
    setAdding(true);
    try {
      const data = rawConfig ?? (await loadMCPConfig());
      const token = addAuth.trim();
      const mcpServers = {
        ...data.mcp_servers,
        [name]: {
          enabled: true,
          description: "",
          transport: "http",
          url,
          ...(token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
        },
      };
      const nextConfig = { ...data, mcp_servers: mcpServers };
      await updateMCPConfig(nextConfig);
      setRawConfig(nextConfig);
      toast.success(t.mcpSettings.toastAddSuccess(name));
      setAddName("");
      setAddUrl("");
      setAddAuth("");
      await fetchServers(false);
    } catch {
      toast.error(t.mcpSettings.toastAddFailed);
    } finally {
      setAdding(false);
    }
  };

  const normalizedAddName = addName.trim();
  const normalizedAddUrl = addUrl.trim();
  const duplicateAddName = servers.some(
    (server) => server.name.toLowerCase() === normalizedAddName.toLowerCase(),
  );
  const invalidAddUrl =
    normalizedAddUrl.length > 0 && !isSupportedMcpUrl(normalizedAddUrl);
  const canAdd =
    serversLoadState === "ready" &&
    normalizedAddName.length > 0 &&
    normalizedAddUrl.length > 0 &&
    !invalidAddUrl &&
    !duplicateAddName &&
    !adding;

  return (
    <div className="space-y-6">
      <SettingsSection title={copy.title} description={copy.description}>
        {serversLoadState === "loading" ? (
          <McpStateNotice state="loading" copy={copy} />
        ) : serversLoadState === "error" ? (
          <McpStateNotice
            state="error"
            copy={copy}
            onRetry={() => void fetchServers()}
          />
        ) : (
          <div className="space-y-2">
            {trustLoadState === "error" && (
              <div
                role="alert"
                className="rounded-lg border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300"
              >
                {copy.trustLoadFailed}
              </div>
            )}
            {servers.map((server) => {
              const trust = trustOf(server.name);
              const trustKnown = trustLoadState === "ready";
              const trusted = trustKnown && !!trust?.approved;
              const pending = pendingServer === server.name;
              return (
                <div
                  key={server.name}
                  className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-lg border p-3"
                >
                  <div className="flex items-center gap-3">
                    <ServerIcon className="size-4 text-muted-foreground" />
                    <div>
                      <div className="font-medium flex flex-wrap items-center gap-2">
                        {server.name}
                        {!trustKnown ? (
                          <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            <ShieldAlertIcon className="size-3" />{" "}
                            {copy.trustUnknown}
                          </span>
                        ) : trusted ? (
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
                      <div className="text-xs text-muted-foreground break-words">
                        {server.type}{" "}
                        {server.command
                          ? `· ${server.command}`
                          : server.url
                            ? `· ${server.url}`
                            : ""}
                      </div>
                      {server.description && (
                        <div className="text-xs text-muted-foreground break-words">
                          {server.description}
                        </div>
                      )}
                      {trustKnown && !trusted && server.enabled && (
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
                        disabled={pendingServer !== null || !trustKnown}
                        aria-label={copy.revokeLabel(server.name)}
                      >
                        {t.mcpSettings.revokeButton}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => approve(server.name)}
                        disabled={pendingServer !== null || !trustKnown}
                        aria-label={copy.trustLabel(server.name)}
                      >
                        {pending ? t.common.loading : t.mcpSettings.trustButton}
                      </Button>
                    )}
                    <Switch
                      aria-label={copy.toggleLabel(server.name)}
                      checked={server.enabled}
                      disabled={pendingServer !== null}
                      onCheckedChange={(v) => toggleServer(server.name, v)}
                    />
                  </div>
                </div>
              );
            })}
            {servers.length === 0 && (
              <div className="text-sm text-muted-foreground text-center py-4">
                {copy.noServers}
              </div>
            )}
          </div>
        )}
      </SettingsSection>
      <SettingsSection title={t.mcpSettings.addRemoteTitle}>
        <form
          className="grid gap-3 sm:grid-cols-[minmax(8rem,0.7fr)_minmax(12rem,1.4fr)_minmax(10rem,1fr)_auto] sm:items-start"
          onSubmit={(event) => {
            event.preventDefault();
            void addServer();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="mcp-server-name" className="text-xs">
              {copy.nameLabel}
            </Label>
            <Input
              id="mcp-server-name"
              name="mcp-server-name"
              autoComplete="off"
              placeholder={t.mcpSettings.addNamePlaceholder}
              value={addName}
              onChange={(e) => setAddName(e.target.value)}
              disabled={adding || serversLoadState !== "ready"}
              aria-invalid={duplicateAddName || undefined}
              aria-describedby={
                duplicateAddName ? "mcp-server-name-error" : undefined
              }
            />
            {duplicateAddName && normalizedAddName ? (
              <p
                id="mcp-server-name-error"
                role="alert"
                className="text-[11px] leading-snug text-destructive"
              >
                {copy.duplicateName(normalizedAddName)}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mcp-server-url" className="text-xs">
              {copy.urlLabel}
            </Label>
            <Input
              id="mcp-server-url"
              name="mcp-server-url"
              type="url"
              inputMode="url"
              autoComplete="url"
              autoCapitalize="none"
              spellCheck={false}
              placeholder={t.mcpSettings.addUrlPlaceholder}
              value={addUrl}
              onChange={(e) => setAddUrl(e.target.value)}
              disabled={adding || serversLoadState !== "ready"}
              aria-invalid={invalidAddUrl || undefined}
              aria-describedby={
                invalidAddUrl ? "mcp-server-url-error" : undefined
              }
            />
            {invalidAddUrl ? (
              <p
                id="mcp-server-url-error"
                role="alert"
                className="text-[11px] leading-snug text-destructive"
              >
                {copy.invalidUrl}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="mcp-server-token" className="text-xs">
              {copy.tokenLabel}
            </Label>
            <Input
              id="mcp-server-token"
              name="mcp-server-token"
              type="password"
              autoComplete="new-password"
              autoCapitalize="none"
              spellCheck={false}
              placeholder={t.mcpSettings.addAuthPlaceholder}
              value={addAuth}
              onChange={(e) => setAddAuth(e.target.value)}
              disabled={adding || serversLoadState !== "ready"}
              aria-describedby="mcp-server-token-hint"
            />
            <p
              id="mcp-server-token-hint"
              className="text-[11px] leading-snug text-muted-foreground"
            >
              {copy.tokenHint}
            </p>
          </div>
          <Button type="submit" className="sm:mt-[1.375rem]" disabled={!canAdd}>
            {adding ? copy.adding : copy.add}
          </Button>
        </form>
      </SettingsSection>
    </div>
  );
}

function McpStateNotice({
  state,
  copy,
  onRetry,
}: {
  state: Exclude<LoadState, "ready">;
  copy: Pick<
    ReturnType<typeof getSettingsUxCopy>["mcp"],
    "loading" | "loadFailed" | "retry"
  >;
  onRetry?: () => void;
}) {
  const failed = state === "error";
  return (
    <div
      role={failed ? "alert" : "status"}
      aria-live="polite"
      className={
        failed
          ? "flex items-center justify-between gap-3 rounded-lg border border-destructive/25 bg-destructive/5 px-3 py-3 text-xs text-destructive"
          : "flex items-center gap-2 rounded-lg border border-border-subtle bg-muted/25 px-3 py-3 text-xs text-muted-foreground"
      }
    >
      <span className="flex min-w-0 items-center gap-2">
        {failed ? null : (
          <LoaderCircleIcon className="size-3.5 shrink-0 animate-spin" />
        )}
        <span>{failed ? copy.loadFailed : copy.loading}</span>
      </span>
      {failed && onRetry ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 shrink-0 px-2 text-xs"
          onClick={onRetry}
        >
          {copy.retry}
        </Button>
      ) : null}
    </div>
  );
}
