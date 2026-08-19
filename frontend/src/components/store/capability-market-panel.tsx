import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Boxes,
  CloudDownload,
  KeyRound,
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
  connectCapability,
  disconnectCapability,
  getCapabilityStatus,
  installCapability,
  listCapabilities,
  setCapabilityEnabled,
  uninstallCapability,
  type CapabilityInfo,
} from "@/core/agents/agent-world-api";
import { cn } from "@/lib/utils";

// 统一「能力包」市场 —— 连接器(WorkBuddy 108)+ Codex 插件(我们正在运行的)
// 一个市场统一管理:安装→技能/MCP,连接→认证编排,插件直接就绪。
// 数据来自后端 /api/capabilities(见 runtime/sensing/gateway/capability_router.py)。

const TYPE_META: Record<
  string,
  { badge: string; label: string }
> = {
  mcp: { badge: "bg-primary/10 text-primary", label: "MCP" },
  cli: {
    badge: "bg-chart-3/10 text-chart-3 dark:text-chart-3",
    label: "CLI",
  },
  "skill-only": {
    badge: "bg-chart-2/10 text-chart-2 dark:text-chart-2",
    label: "技能",
  },
  plugin: {
    badge: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
    label: "插件",
  },
  other: { badge: "bg-muted text-muted-foreground", label: "其他" },
};

const SOURCE_LABEL: Record<string, { label: string; cls: string }> = {
  connector: { label: "连接器", cls: "bg-sky-500/10 text-sky-700 dark:text-sky-300" },
  codex_plugin: { label: "插件", cls: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400" },
};

const DEFAULT_TYPE_META = {
  badge: "bg-muted text-muted-foreground",
  label: "其他",
};
const DEFAULT_SOURCE = { label: "连接器", cls: "bg-sky-500/10 text-sky-700 dark:text-sky-300" };

const AUTH_LABEL: Record<string, string> = {
  none: "无需认证",
  token: "Token",
  oauth: "OAuth",
  "server-side": "服务端",
  "oneid-token": "OneID",
};

function ConnectDialog({
  capability,
  open,
  onOpenChange,
  onConnected,
}: {
  capability: CapabilityInfo;
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

  const isCli = capability.type === "cli";
  const isPlugin = capability.source === "codex_plugin";

  const onSubmit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const tokens: Record<string, string> = {};
      if (accessToken.trim()) tokens.access_token = accessToken.trim();
      if (apiKey.trim()) tokens.api_key = apiKey.trim();
      const res = await connectCapability(capability.id, {
        tokens: Object.keys(tokens).length ? tokens : undefined,
        run_cli: isCli && Object.keys(tokens).length === 0,
      });
      if (res.connected) {
        setMessage(isPlugin ? "插件无需认证,已就绪 ✓" : "已连接 ✓");
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
            连接 · {capability.name_zh}
          </DialogTitle>
          <DialogDescription className="text-caption leading-5">
            类型 {(TYPE_META[capability.type] ?? DEFAULT_TYPE_META).label} · 认证{" "}
            {AUTH_LABEL[capability.auth_mode] ?? capability.auth_mode}
          </DialogDescription>
        </DialogHeader>

        {isPlugin && (
          <p className="text-xs leading-5 text-muted-foreground">
            插件(Codex 插件)无需认证,安装后技能即可用。点「保存凭据」直接确认就绪。
          </p>
        )}

        {!isCli && !isPlugin && (
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

export function CapabilityMarketPanel() {
  const [items, setItems] = useState<CapabilityInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<
    "all" | "connector" | "codex_plugin"
  >("all");
  const [typeFilter, setTypeFilter] = useState<
    "all" | "mcp" | "cli" | "skill-only" | "plugin"
  >("all");
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({});
  const [statusMap, setStatusMap] = useState<Record<string, boolean>>({});
  const [connectTarget, setConnectTarget] = useState<CapabilityInfo | null>(
    null,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCapabilities({ limit: 500 });
      setItems(res.capabilities);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 拉取已安装能力的连接状态
  const refreshStatus = useCallback(async (installed: CapabilityInfo[]) => {
    const next: Record<string, boolean> = {};
    await Promise.all(
      installed.map(async (c) => {
        try {
          const st = await getCapabilityStatus(c.id);
          next[c.id] = !!st.connected;
        } catch {
          next[c.id] = false;
        }
      }),
    );
    setStatusMap((prev) => ({ ...prev, ...next }));
  }, []);

  useEffect(() => {
    const installed = items.filter((c) => c.installed);
    if (installed.length) void refreshStatus(installed);
  }, [items, refreshStatus]);

  const setBusy = (id: string, busy: boolean) =>
    setBusyMap((m) => ({ ...m, [id]: busy }));

  const q = query.trim().toLowerCase();
  const filtered = items.filter((c) => {
    if (sourceFilter !== "all" && c.source !== sourceFilter) return false;
    if (typeFilter !== "all" && c.type !== typeFilter) return false;
    if (!q) return true;
    return [c.name, c.name_zh, c.id, c.description, c.description_zh, c.author]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  const counts = useMemo(() => {
    const out: Record<string, number> = { all: items.length };
    for (const c of items) {
      out[c.source] = (out[c.source] ?? 0) + 1;
      out[c.type] = (out[c.type] ?? 0) + 1;
    }
    return out;
  }, [items]);

  const onInstall = async (cap: CapabilityInfo) => {
    setBusy(cap.id, true);
    setError(null);
    try {
      await installCapability(cap.id);
      setItems((prev) =>
        prev.map((c) =>
          c.id === cap.id ? { ...c, installed: true, enabled: false } : c,
        ),
      );
      void refreshStatus([{ ...cap, installed: true, enabled: false }]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(cap.id, false);
    }
  };

  const onUninstall = async (cap: CapabilityInfo) => {
    setBusy(cap.id, true);
    setError(null);
    try {
      await uninstallCapability(cap.id);
      setItems((prev) =>
        prev.map((c) =>
          c.id === cap.id ? { ...c, installed: false, enabled: false } : c,
        ),
      );
      setStatusMap((m) => ({ ...m, [cap.id]: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(cap.id, false);
    }
  };

  const onToggleEnabled = async (cap: CapabilityInfo) => {
    setBusy(cap.id, true);
    setError(null);
    try {
      await setCapabilityEnabled(cap.id, !cap.enabled);
      setItems((prev) =>
        prev.map((c) =>
          c.id === cap.id ? { ...c, enabled: !c.enabled } : c,
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(cap.id, false);
    }
  };

  const onDisconnect = async (cap: CapabilityInfo) => {
    setBusy(cap.id, true);
    setError(null);
    try {
      await disconnectCapability(cap.id);
      setStatusMap((m) => ({ ...m, [cap.id]: false }));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(cap.id, false);
    }
  };

  const openConnect = (cap: CapabilityInfo) => {
    // 插件无需认证,直接确认就绪
    if (cap.source === "codex_plugin") {
      setBusy(cap.id, true);
      void connectCapability(cap.id)
        .then(() => {
          setStatusMap((m) => ({ ...m, [cap.id]: true }));
        })
        .catch((err) =>
          setError(err instanceof Error ? err.message : String(err)),
        )
        .finally(() => setBusy(cap.id, false));
      return;
    }
    setConnectTarget(cap);
  };

  return (
    <div className="space-y-3">
      {/* 来源 + 类型 + 搜索 */}
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="flex flex-wrap items-center gap-1.5">
          <Button
            type="button"
            size="sm"
            variant={sourceFilter === "all" ? "secondary" : "ghost"}
            onClick={() => setSourceFilter("all")}
            className="h-8 px-2.5 text-xs"
          >
            全部<span className="ml-1 text-xs text-muted-foreground">{counts.all}</span>
          </Button>
          <Button
            type="button"
            size="sm"
            variant={sourceFilter === "connector" ? "secondary" : "ghost"}
            onClick={() => setSourceFilter("connector")}
            className="h-8 px-2.5 text-xs"
          >
            连接器<span className="ml-1 text-xs text-muted-foreground">{counts.connector ?? 0}</span>
          </Button>
          <Button
            type="button"
            size="sm"
            variant={sourceFilter === "codex_plugin" ? "secondary" : "ghost"}
            onClick={() => setSourceFilter("codex_plugin")}
            className="h-8 px-2.5 text-xs"
          >
            插件<span className="ml-1 text-xs text-muted-foreground">{counts.codex_plugin ?? 0}</span>
          </Button>
          <span className="mx-1 h-4 w-px bg-border-default" />
          {(["all", "mcp", "cli", "skill-only", "plugin"] as const).map(
            (tp) => (
              <Button
                key={tp}
                type="button"
                size="sm"
                variant={typeFilter === tp ? "secondary" : "ghost"}
                onClick={() => setTypeFilter(tp)}
                className="h-8 px-2.5 text-xs"
              >
                {tp === "all"
                  ? "全部类型"
                  : tp === "mcp"
                    ? "MCP"
                    : tp === "cli"
                      ? "CLI"
                      : tp === "plugin"
                        ? "插件"
                        : "技能"}
                <span className="ml-1 text-xs text-muted-foreground">
                  {counts[tp] ?? 0}
                </span>
              </Button>
            ),
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <span className="text-xs text-muted-foreground">
            {filtered.length}/{items.length}
          </span>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索连接器 / 插件"
              aria-label="搜索连接器 / 插件"
              className="h-8 w-44 rounded-md border border-border-default bg-background pl-7 pr-2 text-sm outline-none focus:border-primary/50"
            />
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
            title="刷新能力列表"
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
          {filtered.map((cap) => {
            const typeMeta = TYPE_META[cap.type] ?? DEFAULT_TYPE_META;
            const sourceMeta = SOURCE_LABEL[cap.source] ?? DEFAULT_SOURCE;
            const busy = busyMap[cap.id];
            const connected = statusMap[cap.id];
            const isPlugin = cap.source === "codex_plugin";
            return (
              <Card
                key={cap.id}
                className="gap-2.5 py-3 transition-colors hover:border-primary/40"
              >
                <CardHeader className="flex-row items-center gap-2.5 px-3 pt-0">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-border-default bg-muted text-base">
                    {isPlugin ? (
                      <Boxes className="size-4 text-indigo-500" />
                    ) : cap.type === "mcp" ? (
                      <Plug className="size-4 text-primary" />
                    ) : cap.type === "cli" ? (
                      <SquareTerminal className="size-4 text-chart-3" />
                    ) : (
                      <Boxes className="size-4 text-chart-2" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <CardTitle className="truncate text-sm">
                      {cap.name_zh}
                    </CardTitle>
                    <CardDescription className="truncate text-xs">
                      {cap.id} ·{" "}
                      {AUTH_LABEL[cap.auth_mode] ?? cap.auth_mode}
                    </CardDescription>
                  </div>
                </CardHeader>
                <div className="flex flex-wrap items-center gap-1 px-3">
                  <Badge className={cn("border-transparent text-[11px]", sourceMeta.cls)}>
                    {sourceMeta.label}
                  </Badge>
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
                    技能 ×{cap.skill_count}
                  </Badge>
                  {cap.mcp_servers.length > 0 && (
                    <Badge
                      variant="outline"
                      className="text-[11px] font-normal text-muted-foreground"
                    >
                      MCP ×{cap.mcp_servers.length}
                    </Badge>
                  )}
                  {cap.installed && (
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
                    {cap.description_zh || cap.description}
                  </p>
                  {cap.author ? (
                    <p className="mt-0.5 text-[11px] text-muted-foreground/70">
                      作者:{cap.author}
                    </p>
                  ) : null}
                </div>

                <CardFooter className="flex flex-wrap gap-1.5 px-3 pb-0">
                  {!cap.installed ? (
                    <Button
                      size="sm"
                      variant="default"
                      className="h-7 rounded-sm px-3 text-xs"
                      disabled={busy}
                      onClick={() => void onInstall(cap)}
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
                        onClick={() => void onToggleEnabled(cap)}
                        title={cap.enabled ? "禁用" : "启用"}
                      >
                        {busy ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : cap.enabled ? (
                          <PlugZap className="mr-1 h-3 w-3 text-emerald-500" />
                        ) : (
                          <Plug className="mr-1 h-3 w-3" />
                        )}
                        {cap.enabled ? "启用中" : "已禁用"}
                      </Button>
                      <Button
                        size="sm"
                        variant={connected ? "outline" : "secondary"}
                        className="h-7 rounded-sm px-3 text-xs"
                        disabled={busy}
                        onClick={() =>
                          connected
                            ? void onDisconnect(cap)
                            : openConnect(cap)
                        }
                        title={connected ? "断开并清除凭据" : "连接/认证"}
                      >
                        {busy ? (
                          <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                        ) : connected ? (
                          <Unplug className="mr-1 h-3 w-3" />
                        ) : (
                          <KeyRound className="mr-1 h-3 w-3" />
                        )}
                        {connected ? "断开" : "连接"}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 rounded-sm px-2 text-xs text-muted-foreground"
                        disabled={busy}
                        onClick={() => void onUninstall(cap)}
                        title="卸载能力包"
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </>
                  )}
                </CardFooter>
              </Card>
            );
          })}
          {filtered.length === 0 && !loading && (
            <div className="col-span-full py-8 text-center text-sm text-muted-foreground">
              没有匹配的连接器或插件
            </div>
          )}
        </div>
      )}

      {connectTarget ? (
        <ConnectDialog
          capability={connectTarget}
          open={!!connectTarget}
          onOpenChange={(open) => {
            if (!open) setConnectTarget(null);
          }}
          onConnected={() => {
            setStatusMap((m) => ({
              ...m,
              [connectTarget.id]: true,
            }));
          }}
        />
      ) : null}
    </div>
  );
}
