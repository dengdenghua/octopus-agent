import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Boxes,
  CloudDownload,
  KeyRound,
  Link2,
  Loader2,
  Plug,
  PlugZap,
  RefreshCw,
  Search,
  SquareTerminal,
  Trash2,
  Unplug,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  connectConnector,
  disableConnector,
  disconnectConnector,
  enableConnector,
  getConnectorStatus,
  installConnector,
  listConnectors,
  uninstallConnector,
  type ConnectorInfo,
} from "@/core/agents/agent-world-api";
import { cn } from "@/lib/utils";

// 连接器市场(WorkBuddy 108 连接器 fork + 认证编排层)。
// 数据来自后端 /api/connectors(见 runtime/sensing/gateway/connector_router.py)。

const TYPE_META = {
  mcp: { badge: "bg-primary/10 text-primary", label: "MCP" },
  cli: { badge: "bg-chart-3/10 text-chart-3 dark:text-chart-3", label: "CLI" },
  "skill-only": {
    badge: "bg-chart-2/10 text-chart-2 dark:text-chart-2",
    label: "技能",
  },
  other: { badge: "bg-muted text-muted-foreground", label: "其他" },
} as const;

const AUTH_LABEL: Record<string, string> = {
  none: "无需认证",
  token: "Token",
  oauth: "OAuth",
  "server-side": "服务端",
  "oneid-token": "OneID",
};

function ConnectDialog({
  connector,
  open,
  onOpenChange,
  onConnected,
}: {
  connector: ConnectorInfo;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConnected: () => void;
}) {
  const [accessToken, setAccessToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setAccessToken("");
      setApiKey("");
      setMessage(null);
      setBusy(false);
    }
  }, [open]);

  const isCli = connector.type === "cli";

  const onSubmit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const tokens: Record<string, string> = {};
      if (accessToken.trim()) tokens.access_token = accessToken.trim();
      if (apiKey.trim()) tokens.api_key = apiKey.trim();
      const res = await connectConnector(connector.id, {
        tokens: Object.keys(tokens).length ? tokens : undefined,
        run_cli: isCli && Object.keys(tokens).length === 0,
      });
      if (res.connected) {
        setMessage("已连接 ✓");
        onConnected();
      } else if (res.command) {
        setMessage(`请在终端执行:\n${res.command}`);
      } else {
        setMessage(res.message || "连接未确认");
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="w-[min(420px,calc(100vw-2rem))] gap-3 rounded-lg p-4 sm:max-w-[420px]"
      >
        <DialogHeader className="gap-1 text-left">
          <DialogTitle className="text-[15px]">
            连接 · {connector.name_zh}
          </DialogTitle>
          <DialogDescription className="text-caption leading-5">
            类型 {TYPE_META[connector.type].label} · 认证{" "}
            {AUTH_LABEL[connector.auth_mode] ?? connector.auth_mode}
          </DialogDescription>
        </DialogHeader>

        {!isCli && (
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">
              access_token
            </label>
            <Input
              value={accessToken}
              onChange={(e) => setAccessToken(e.target.value)}
              placeholder="粘贴 access_token"
              className="h-8 text-sm"
            />
            <label className="text-xs text-muted-foreground">api_key</label>
            <Input
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="粘贴 api_key(可选)"
              className="h-8 text-sm"
            />
          </div>
        )}

        {isCli && (
          <p className="text-xs leading-5 text-muted-foreground">
            CLI 型连接器将执行 cli.json 的登录命令(浏览器/交互式)。
            可勾选在后台同步执行,或在本机终端手动执行。
          </p>
        )}

        {message ? (
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded-md bg-muted/60 px-2 py-1.5 text-xs text-foreground">
            {message}
          </pre>
        ) : null}

        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => void onSubmit()}
          >
            {busy ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <KeyRound className="mr-1 h-3 w-3" />
            )}
            {isCli ? "执行 CLI 登录" : "保存凭据"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ConnectorMarketPanel() {
  const [connectors, setConnectors] = useState<ConnectorInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<"all" | "mcp" | "cli" | "skill-only">(
    "all",
  );
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({});
  const [statusMap, setStatusMap] = useState<Record<string, boolean>>({});
  const [connectTarget, setConnectTarget] = useState<ConnectorInfo | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listConnectors({ limit: 500 });
      setConnectors(res.connectors);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 拉取已安装连接器的认证状态(是否已连接)
  const refreshStatus = useCallback(async (installed: ConnectorInfo[]) => {
    const next: Record<string, boolean> = {};
    await Promise.all(
      installed.map(async (c) => {
        try {
          const st = await getConnectorStatus(c.id);
          next[c.id] = !!st.connected;
        } catch {
          next[c.id] = false;
        }
      }),
    );
    setStatusMap((prev) => ({ ...prev, ...next }));
  }, []);

  useEffect(() => {
    const installed = connectors.filter((c) => c.installed);
    if (installed.length) void refreshStatus(installed);
  }, [connectors, refreshStatus]);

  const setBusy = (id: string, busy: boolean) =>
    setBusyMap((m) => ({ ...m, [id]: busy }));

  const q = query.trim().toLowerCase();
  const filtered = connectors.filter((c) => {
    if (typeFilter !== "all" && c.type !== typeFilter) return false;
    if (!q) return true;
    return [c.name, c.name_zh, c.id, c.description, c.description_zh]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: connectors.length };
    for (const c of connectors) {
      out[c.type] = (out[c.type] ?? 0) + 1;
    }
    return out;
  }, [connectors]);

  const onInstall = async (connector: ConnectorInfo) => {
    setBusy(connector.id, true);
    setError(null);
    try {
      await installConnector(connector.id);
      setConnectors((prev) =>
        prev.map((c) =>
          c.id === connector.id ? { ...c, installed: true, enabled: false } : c,
        ),
      );
      void refreshStatus([{ ...connector, installed: true, enabled: false }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(connector.id, false);
    }
  };

  const onUninstall = async (connector: ConnectorInfo) => {
    setBusy(connector.id, true);
    setError(null);
    try {
      await uninstallConnector(connector.id);
      setConnectors((prev) =>
        prev.map((c) =>
          c.id === connector.id ? { ...c, installed: false, enabled: false } : c,
        ),
      );
      setStatusMap((m) => ({ ...m, [connector.id]: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(connector.id, false);
    }
  };

  const onToggleEnabled = async (connector: ConnectorInfo) => {
    setBusy(connector.id, true);
    setError(null);
    try {
      if (connector.enabled) {
        await disableConnector(connector.id);
      } else {
        await enableConnector(connector.id);
      }
      setConnectors((prev) =>
        prev.map((c) =>
          c.id === connector.id ? { ...c, enabled: !c.enabled } : c,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(connector.id, false);
    }
  };

  const onDisconnect = async (connector: ConnectorInfo) => {
    setBusy(connector.id, true);
    setError(null);
    try {
      await disconnectConnector(connector.id);
      setStatusMap((m) => ({ ...m, [connector.id]: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(connector.id, false);
    }
  };

  return (
    <div className="space-y-3">
      {/* 类型 + 搜索 */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="flex shrink-0 items-center gap-1.5">
          {(["all", "mcp", "cli", "skill-only"] as const).map((tp) => (
            <Button
              key={tp}
              type="button"
              size="sm"
              variant={typeFilter === tp ? "secondary" : "ghost"}
              onClick={() => setTypeFilter(tp)}
              className="h-8 px-2.5 text-xs"
            >
              {tp === "all"
                ? "全部"
                : tp === "mcp"
                  ? "MCP"
                  : tp === "cli"
                    ? "CLI"
                    : "技能"}
              <span className="ml-1 text-xs text-muted-foreground">
                {counts[tp] ?? 0}
              </span>
            </Button>
          ))}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{connectors.length}
          </span>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索连接器"
              aria-label="搜索连接器"
              className="h-8 w-44 rounded-md border border-border-default bg-background pl-7 pr-2 text-sm outline-none focus:border-primary/50"
            />
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
            title="刷新连接器列表"
          >
            <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      {error ? (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex min-h-[200px] items-center justify-center text-muted-foreground">
          <Loader2 className="size-5 animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
          {filtered.map((connector) => {
            const typeMeta = TYPE_META[connector.type] ?? TYPE_META.mcp;
            const busy = busyMap[connector.id];
            const connected = statusMap[connector.id];
            return (
              <Card
                key={connector.id}
                className="gap-2.5 py-3 transition-colors hover:border-primary/40"
              >
                <CardHeader className="flex-row items-center gap-2.5 px-3 pt-0">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-muted text-base">
                    {connector.type === "mcp" ? (
                      <Plug className="size-4 text-primary" />
                    ) : connector.type === "cli" ? (
                      <SquareTerminal className="size-4 text-chart-3" />
                    ) : (
                      <Boxes className="size-4 text-chart-2" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <CardTitle className="truncate text-sm">
                      {connector.name_zh}
                    </CardTitle>
                    <CardDescription className="truncate text-xs">
                      {connector.id} ·{" "}
                      {AUTH_LABEL[connector.auth_mode] ?? connector.auth_mode}
                    </CardDescription>
                  </div>
                </CardHeader>
                <div className="flex flex-wrap items-center gap-1 px-3">
                  <Badge
                    className={cn(
                      "border-transparent text-[11px]",
                      typeMeta.badge,
                    )}
                  >
                    {typeMeta.label}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="text-[11px] font-normal text-muted-foreground"
                  >
                    技能 ×{connector.skill_count}
                  </Badge>
                  {connector.mcp_servers.length > 0 && (
                    <Badge
                      variant="outline"
                      className="text-[11px] font-normal text-muted-foreground"
                    >
                      MCP ×{connector.mcp_servers.length}
                    </Badge>
                  )}
                  {connector.installed && (
                    <Badge
                      className={cn(
                        "border-transparent text-[11px]",
                        connected
                          ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                          : "bg-amber-500/15 text-amber-600 dark:text-amber-400",
                      )}
                    >
                      {connected ? "已连接" : "未连接"}
                    </Badge>
                  )}
                </div>

                <div className="px-3">
                  <p className="line-clamp-2 text-xs leading-5 text-muted-foreground">
                    {connector.description_zh || connector.description}
                  </p>
                </div>

                <CardFooter className="flex flex-wrap gap-1.5 px-3 pb-0">
                  {!connector.installed ? (
                    <Button
                      size="sm"
                      variant="default"
                      className="h-7 rounded-sm px-3 text-xs"
                      disabled={busy}
                      onClick={() => void onInstall(connector)}
                    >
                      {busy ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <CloudDownload className="mr-1 h-3 w-3" />
                      )}
                      安装
                    </Button>
                  ) : (
                    <>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 rounded-sm px-3 text-xs"
                        disabled={busy}
                        onClick={() => void onToggleEnabled(connector)}
                        title={connector.enabled ? "禁用 MCP" : "启用 MCP"}
                      >
                        {busy ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : connector.enabled ? (
                          <PlugZap className="mr-1 h-3 w-3 text-emerald-500" />
                        ) : (
                          <Plug className="mr-1 h-3 w-3" />
                        )}
                        {connector.enabled ? "启用中" : "已禁用"}
                      </Button>
                      {connector.auth_mode !== "none" && (
                        <Button
                          size="sm"
                          variant={connected ? "outline" : "secondary"}
                          className="h-7 rounded-sm px-3 text-xs"
                          disabled={busy}
                          onClick={() =>
                            connected
                              ? void onDisconnect(connector)
                              : setConnectTarget(connector)
                          }
                          title={connected ? "断开并清除凭据" : "连接并认证"}
                        >
                          {connected ? (
                            <Unplug className="mr-1 h-3 w-3" />
                          ) : (
                            <Link2 className="mr-1 h-3 w-3" />
                          )}
                          {connected ? "断开" : "连接"}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 rounded-sm px-2 text-xs"
                        disabled={busy}
                        onClick={() => void onUninstall(connector)}
                        title="卸载"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      )}

      {!loading && !error && filtered.length === 0 ? (
        <div className="py-10 text-center text-sm text-muted-foreground">
          共 {connectors.length} 个连接器 · 无匹配结果
        </div>
      ) : null}

      {connectTarget && (
        <ConnectDialog
          connector={connectTarget}
          open={true}
          onOpenChange={(open) => {
            if (!open) setConnectTarget(null);
          }}
          onConnected={() =>
            setStatusMap((m) => ({ ...m, [connectTarget.id]: true }))
          }
        />
      )}
    </div>
  );
}

