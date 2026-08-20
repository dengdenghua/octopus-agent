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
  deleteOAuthApp,
  getOAuthApp,
  oauthAuthorize,
  oauthStatus,
  saveOAuthApp,
} from "@/core/mcp/api";
import {
  connectCapability,
  disconnectCapability,
  getCapabilityStatus,
  installCapability,
  listCapabilities,
  setCapabilityEnabled,
  uninstallCapability,
  type CapabilityConnectResult,
  type CapabilityInfo,
} from "@/core/agents/agent-world-api";
import { cn } from "@/lib/utils";

// 统一「插件」市场 —— 所有外部能力(WorkBuddy MCP 服务、Codex 插件、注册表插件)统一叫插件。
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

const DEFAULT_TYPE_META = {
  badge: "bg-muted text-muted-foreground",
  label: "其他",
};
const AUTH_LABEL: Record<string, string> = {
  none: "无需认证",
  token: "Token",
  oauth: "OAuth",
  "server-side": "服务端",
  "oneid-token": "OneID",
};

/** 轮询 MCP OAuth 授权结果,直到已授权或超时(默认 90s)。 */
function pollOAuth(server: string, timeoutMs = 90_000): Promise<boolean> {
  return new Promise((resolve) => {
    const startedAt = Date.now();
    const tick = async () => {
      try {
        const st = await oauthStatus(server);
        if (st.authorized) {
          resolve(true);
          return;
        }
      } catch {
        // 网络抖动忽略,继续轮询
      }
      if (Date.now() - startedAt >= timeoutMs) {
        resolve(false);
        return;
      }
      window.setTimeout(tick, 1500);
    };
    void tick();
  });
}

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
  const [oneIdToken, setOneIdToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [deviceFlow, setDeviceFlow] = useState<
    CapabilityConnectResult["device_flow"] | null
  >(null);

  useEffect(() => {
    if (open) {
      setAccessToken("");
      setApiKey("");
      setOneIdToken("");
      setMessage(null);
      setBusy(false);
      setDeviceFlow(null);
    }
  }, [open]);

  const isCli = capability.type === "cli";
  const isPlugin = capability.source === "codex_plugin";
  const isOneId = capability.auth_mode === "oneid-token";

  /** 轮询连接状态直到成功或超时(设备流登录完成后 CLI status 返回 connected)。 */
  const pollConnected = (timeoutMs: number): Promise<boolean> =>
    new Promise((resolve) => {
      const startedAt = Date.now();
      const tick = async () => {
        try {
          const st = await getCapabilityStatus(capability.id);
          if (st.connected) {
            resolve(true);
            return;
          }
        } catch {
          // 网络抖动忽略,继续轮询
        }
        if (Date.now() - startedAt >= timeoutMs) {
          resolve(false);
          return;
        }
        window.setTimeout(tick, 2000);
      };
      void tick();
    });

  const onSubmit = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const tokens: Record<string, string> = {};
      if (isOneId) {
        if (oneIdToken.trim()) tokens.oneid_token = oneIdToken.trim();
      } else {
        if (accessToken.trim()) tokens.access_token = accessToken.trim();
        if (apiKey.trim()) tokens.api_key = apiKey.trim();
      }
      const res = await connectCapability(capability.id, {
        tokens: Object.keys(tokens).length ? tokens : undefined,
        run_cli: isCli && Object.keys(tokens).length === 0,
      });
      if (res.connected) {
        setMessage(isPlugin ? "插件无需认证,已就绪 ✓" : "已连接 ✓");
        onConnected();
      } else if (res.device_flow) {
        // CLI 设备流:展示授权地址 + 自动打开 + 轮询状态
        setDeviceFlow(res.device_flow);
        const uri = res.device_flow.verification_uri;
        if (uri) {
          const popup = window.open(
            uri,
            "octopus-device-flow",
            "popup=yes,width=560,height=720",
          );
          if (!popup) setMessage("已复制授权地址,请手动打开(浏览器拦截了弹窗)。");
        }
        const ok = await pollConnected(
          (res.device_flow.expires_in || 240) * 1000,
        );
        if (ok) {
          setMessage("设备流登录完成 ✓");
          setDeviceFlow(null);
          onConnected();
        } else {
          setMessage("设备流授权未在有效期内完成,可重试或手动执行 CLI 登录。");
        }
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
            插件(Octopus 插件)无需认证,安装后技能即可用。点「保存凭据」直接确认就绪。
          </p>
        )}

        {!isCli && !isPlugin && isOneId && (
          <div className="flex flex-col gap-2">
            <label className="text-xs text-muted-foreground">
              OneID Token(腾讯统一身份)
            </label>
            <Input
              value={oneIdToken}
              onChange={(e) => setOneIdToken(e.target.value)}
              placeholder="粘贴 OneID access token"
              className="h-8 text-sm"
            />
          </div>
        )}

        {!isCli && !isPlugin && !isOneId && (
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

        {isCli && !deviceFlow && (
          <p className="text-xs leading-5 text-muted-foreground">
            CLI 型插件将执行 cli.json 的登录命令(浏览器/设备流)。点「执行 CLI
            登录」自动开始。
          </p>
        )}

        {deviceFlow ? (
          <div className="space-y-1.5 rounded-md bg-muted/60 px-2.5 py-2 text-xs">
            <p className="text-foreground">
              {deviceFlow.message || "请在浏览器完成授权"}
            </p>
            {deviceFlow.user_code && !deviceFlow.code_embedded_in_uri ? (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">验证码</span>
                <code className="rounded bg-background px-1.5 py-0.5 font-mono text-[12px]">
                  {deviceFlow.user_code}
                </code>
              </div>
            ) : null}
            <div className="flex items-center gap-2 pt-0.5">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="h-7 px-2 text-xs"
                onClick={() =>
                  deviceFlow.verification_uri &&
                  window.open(deviceFlow.verification_uri, "_blank")
                }
              >
                打开授权页
              </Button>
              <span className="text-muted-foreground">
                等待授权完成…({deviceFlow.expires_in || 240}s)
              </span>
            </div>
          </div>
        ) : null}

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
            {deviceFlow ? "关闭" : "取消"}
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
            {isCli ? (deviceFlow ? "重新登录" : "执行 CLI 登录") : "保存凭据"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** 服务商 OAuth App 凭据配置弹窗(BYO OAuth)。
 *
 * GitHub / GitLab 等连接器不暴露 .well-known 元数据,网页登录靠用户在自己账号下
 * 注册一个 OAuth App(免费、几分钟)。这里收集 client_id + client_secret,加密存
 * 到后端(绝不返回明文 secret),保存后自动继续网页授权。
 */
function OAuthAppDialog({
  open,
  provider,
  providerName,
  docsUrl,
  redirectUri,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  provider: string;
  providerName: string;
  docsUrl: string;
  redirectUri: string;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [hasExisting, setHasExisting] = useState(false);
  const [existingMask, setExistingMask] = useState("");

  useEffect(() => {
    if (!open) return;
    setClientId("");
    setClientSecret("");
    setMessage(null);
    setBusy(false);
    void getOAuthApp(provider)
      .then((info) => {
        setHasExisting(info.configured);
        setExistingMask(info.client_id_masked);
      })
      .catch(() => setHasExisting(false));
  }, [open, provider]);

  const onSubmit = async () => {
    if (!clientId.trim()) {
      setMessage("请填写 client_id。");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      await saveOAuthApp(provider, clientId.trim(), clientSecret.trim());
      setMessage("凭据已保存,正在打开授权页…");
      onSaved();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const onRemove = async () => {
    setBusy(true);
    setMessage(null);
    try {
      await deleteOAuthApp(provider);
      setHasExisting(false);
      setExistingMask("");
      setMessage("已移除本地保存的 OAuth App 凭据。");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader className="gap-1 text-left">
          <DialogTitle className="text-[15px]">
            🔗 配置 {providerName} OAuth App
          </DialogTitle>
          <DialogDescription className="text-caption leading-5">
            该服务商不支持自动发现(MCP .well-known),网页登录需要你注册一个
            OAuth App 获取凭据,和 WorkBuddy 用自己平台注册的 App 一个原理。
            凭据仅保存在本机(加密),不会上传。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2 text-xs">
          {docsUrl ? (
            <a
              href={docsUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-primary underline underline-offset-2"
            >
              如何创建 {providerName} OAuth App(官方文档)
            </a>
          ) : null}
          <div className="rounded-md bg-muted/60 px-2.5 py-2 leading-5">
            <div className="font-medium text-foreground">回调地址(注册 App 时填写)</div>
            <code className="mt-0.5 block break-all text-[11px] text-muted-foreground">
              {redirectUri}
            </code>
          </div>
        </div>

        {hasExisting ? (
          <div className="flex items-center justify-between gap-2 rounded-md border border-border-default px-2.5 py-2 text-xs">
            <span className="text-muted-foreground">
              已保存 OAuth App:{' '}
              <code className="text-foreground">{existingMask || "已配置"}</code>
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void onRemove()}
            >
              移除
            </Button>
          </div>
        ) : null}

        <div className="space-y-2">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              client_id
            </label>
            <Input
              value={clientId}
              onChange={(e) => setClientId(e.target.value)}
              placeholder="Iv23xxxxxxxxxxxxxxxx"
              autoComplete="off"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              client_secret
            </label>
            <Input
              value={clientSecret}
              onChange={(e) => setClientSecret(e.target.value)}
              placeholder="gho_xxxxxxxxxxxxxxxx"
              autoComplete="off"
              type="password"
            />
          </div>
        </div>

        {message ? (
          <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded-md bg-muted/60 px-2 py-1.5 text-xs text-foreground">
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
          <Button type="button" size="sm" disabled={busy} onClick={() => void onSubmit()}>
            {busy ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <KeyRound className="mr-1 h-3 w-3" />
            )}
            保存并继续授权
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
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<
    "all" | "mcp" | "cli" | "skill-only" | "plugin"
  >("all");
  const [busyMap, setBusyMap] = useState<Record<string, boolean>>({});
  const [statusMap, setStatusMap] = useState<Record<string, boolean>>({});
  /** 显示只能手动填 token 的插件(默认隐藏,对齐「都能跳网页授权」)。 */
  const [showManual, setShowManual] = useState(false);
  const [connectTarget, setConnectTarget] = useState<CapabilityInfo | null>(
    null,
  );
  const [oauthAppDialog, setOAuthAppDialog] = useState<{
    provider: string;
    providerName: string;
    docsUrl: string;
    redirectUri: string;
    server: string;
    url: string;
    cap: CapabilityInfo;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listCapabilities({ limit: 500, includeManual: showManual });
      setItems(res.capabilities);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [showManual]);

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
      out[c.type] = (out[c.type] ?? 0) + 1;
    }
    return out;
  }, [items]);

  const onInstall = async (cap: CapabilityInfo) => {
    setBusy(cap.id, true);
    setError(null);
    setNotice(null);
    try {
      const res = await installCapability(cap.id);
      setItems((prev) =>
        prev.map((c) =>
          c.id === cap.id ? { ...c, installed: true, enabled: false } : c,
        ),
      );
      // CLI 连接器生命周期提示(init/版本)不阻断安装
      const cli = res.cli_lifecycle;
      if (cli?.has_cli) {
        const msgs: string[] = [];
        if (cli.init && !cli.init.ok && cli.init.error) {
          msgs.push(`CLI 工具未装好:${cli.init.error}`);
        }
        if (cli.version && !cli.version.ok && cli.version.error) {
          msgs.push(`版本提示:${cli.version.error}`);
        }
        if (msgs.length) setNotice(msgs.join(" "));
      }
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

  // 跑一遍「网页授权」:authorize → 弹窗 → 轮询回调结果。
  const runWebOAuth = async (cap: CapabilityInfo, server: string, url: string) => {
    const { authorize_url, needs_app_credentials, provider, provider_name, docs_url, redirect_uri } =
      await oauthAuthorize(server, url, cap.oauth_provider ?? undefined);
    // 服务商直连 OAuth(GitHub 等)还没配置 OAuth App 凭据 → 引导用户填写
    if (needs_app_credentials && provider) {
      setOAuthAppDialog({
        provider,
        providerName: provider_name ?? provider,
        docsUrl: docs_url ?? "",
        redirectUri: redirect_uri ?? "",
        server,
        url,
        cap,
      });
      return;
    }
    const popup = window.open(
      authorize_url,
      "octopus-mcp-oauth",
      "popup=yes,width=560,height=720",
    );
    if (!popup) {
      setError("授权窗口被浏览器拦截,请允许弹窗后重试");
      return;
    }
    const ok = await pollOAuth(server);
    if (ok) {
      setStatusMap((m) => ({ ...m, [cap.id]: true }));
    } else {
      setError("未完成网页授权(超时或取消),可重试或改用手动填写凭据");
    }
  };

  const openConnect = async (cap: CapabilityInfo) => {
    // 插件(Codex)无需认证,直接确认就绪
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

    // OneID(腾讯统一身份)特例:走 oneid-token 专用流程,不尝试网页 OAuth。
    if (cap.auth_mode === "oneid-token") {
      setConnectTarget(cap);
      return;
    }

    // MCP 型插件:优先走「网页登录授权」——打开服务商授权页,登录授权后回调。
    // 服务商不支持网页授权时才回退到手动填 token。
    const mcp = (cap.mcp_servers ?? []).find((s) => s && s.url);
    if (mcp) {
      setBusy(cap.id, true);
      setError(null);
      try {
        await runWebOAuth(cap, mcp.name, mcp.url);
      } catch {
        // 无 .well-known 发现 + 非服务商直连 OAuth → 回退到手动填写凭据
        setConnectTarget(cap);
      } finally {
        setBusy(cap.id, false);
      }
      return;
    }

    // 其余类型:打开手动填写凭据对话框
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
            variant={typeFilter === "all" ? "secondary" : "ghost"}
            onClick={() => setTypeFilter("all")}
            className="h-8 px-2.5 text-xs"
          >
            全部<span className="ml-1 text-xs text-muted-foreground">{counts.all}</span>
          </Button>
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
              placeholder="搜索插件"
              aria-label="搜索插件"
              className="h-8 w-44 rounded-md border border-border-default bg-background pl-7 pr-2 text-sm outline-none focus:border-primary/50"
            />
          </div>
          <Button
            size="sm"
            variant={showManual ? "secondary" : "ghost"}
            disabled={loading}
            onClick={() => setShowManual((v) => !v)}
            title="显示只能手动填 token、不能跳网页授权的插件"
          >
            {showManual ? "隐藏手动填" : "显示手动填"}
          </Button>
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

      {notice ? (
        <div className="rounded-md bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          {notice}
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
                  <Badge
                    className={cn(
                      "border-transparent text-[11px]",
                      typeMeta.badge,
                    )}
                  >
                    {typeMeta.label}
                  </Badge>
                  {(cap.oauth_supported || cap.has_cli_auth) && (
                    <Badge
                      className="border-transparent bg-sky-500/15 text-[11px] text-sky-600 dark:text-sky-400"
                      title="支持跳转网页登录授权,无需手动填 token"
                    >
                      🔗 网页登录
                    </Badge>
                  )}
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
                            : void openConnect(cap)
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
              没有匹配的插件
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

      {oauthAppDialog ? (
        <OAuthAppDialog
          open
          provider={oauthAppDialog.provider}
          providerName={oauthAppDialog.providerName}
          docsUrl={oauthAppDialog.docsUrl}
          redirectUri={oauthAppDialog.redirectUri}
          onOpenChange={(open) => {
            if (!open) setOAuthAppDialog(null);
          }}
          onSaved={async () => {
            const dlg = oauthAppDialog;
            setOAuthAppDialog(null);
            if (!dlg) return;
            setBusy(dlg.cap.id, true);
            setError(null);
            try {
              await runWebOAuth(dlg.cap, dlg.server, dlg.url);
            } catch {
              setConnectTarget(dlg.cap);
            } finally {
              setBusy(dlg.cap.id, false);
            }
          }}
        />
      ) : null}
    </div>
  );
}
