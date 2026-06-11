
import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ChevronDownIcon,
  ExternalLinkIcon,
  GlobeIcon,
  ImageIcon,
  Loader2Icon,
  MousePointerClickIcon,
  PlayIcon,
  RefreshCwIcon,
  ServerIcon,
  SquareIcon,
  TypeIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import {
  createOctopusBrowserSessionIdentity,
  type OctopusBrowserSessionIdentity,
} from "@/core/browser/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BrowserSession {
  session_id: string;
  project_id?: string;
  profile_id?: string;
  profile_dir?: string;
  automation_mode?: string;
  uses_system_mouse?: boolean;
  desktop_lease_required?: boolean;
  is_launched: boolean;
  created_at: number;
  last_activity: number;
  action_count: number;
  headless?: boolean;
  mode?: string;
  runtime?: string;
  has_page?: boolean;
  healthy?: boolean;
  current_url?: string;
  current_title?: string;
}

interface ActionLogEntry {
  action: string;
  detail: string;
  timestamp: number;
}

interface PageInfo {
  url: string;
  title: string;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const browserApi = {
  async sessionStatus(sessionId: string): Promise<{ exists: boolean; session: BrowserSession }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/session/status?session_id=${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(data.detail || "Failed to get browser session status");
    }
    return res.json();
  },

  async ensure(
    identity: OctopusBrowserSessionIdentity,
  ): Promise<{ status: string; session: BrowserSession }> {
    const res = await fetch(`${getBackendBaseURL()}/api/browser/session/ensure`, {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        session_id: identity.sessionId,
        project_id: identity.projectId,
        profile_id: identity.profileId,
        headless: true,
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(data.detail || "Failed to start browser session");
    }
    return res.json();
  },

  async reset(identity: OctopusBrowserSessionIdentity): Promise<void> {
    await fetch(`${getBackendBaseURL()}/api/browser/session/reset`, {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        session_id: identity.sessionId,
        project_id: identity.projectId,
        profile_id: identity.profileId,
      }),
    });
  },

  async navigate(identity: OctopusBrowserSessionIdentity, url: string): Promise<PageInfo> {
    const res = await fetch(`${getBackendBaseURL()}/api/browser/navigate`, {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        session_id: identity.sessionId,
        project_id: identity.projectId,
        profile_id: identity.profileId,
        url,
      }),
    });
    if (!res.ok) throw new Error("Navigation failed");
    return res.json();
  },

  async action(
    identity: OctopusBrowserSessionIdentity,
    action: string,
    params: Record<string, unknown> = {},
  ): Promise<Record<string, unknown>> {
    const res = await fetch(`${getBackendBaseURL()}/api/browser/action`, {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        session_id: identity.sessionId,
        project_id: identity.projectId,
        profile_id: identity.profileId,
        action,
        ...params,
      }),
    });
    if (!res.ok) throw new Error("Action failed");
    return res.json();
  },

  async screenshotBase64(
    sessionId: string,
  ): Promise<{ base64: string; width: number; height: number }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/screenshot/base64?session_id=${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error("Screenshot failed");
    return res.json();
  },

  async pageInfo(sessionId: string): Promise<PageInfo> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/page-info?session_id=${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error("Failed to get page info");
    return res.json();
  },

  async actionLog(
    sessionId: string,
    limit = 50,
  ): Promise<{ actions: ActionLogEntry[] }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/action-log?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return { actions: [] };
    return res.json();
  },
};

// ---------------------------------------------------------------------------
// Local port detection
// ---------------------------------------------------------------------------

interface DetectedService {
  port: number;
  name: string;
  type: "frontend" | "backend" | "other";
  url: string;
}

const COMMON_DEV_PORTS = [
  { port: 5173, name: "Vite", type: "frontend" as const },
  { port: 5174, name: "Vite", type: "frontend" as const },
  { port: 3000, name: "React/Next.js", type: "frontend" as const },
  { port: 3001, name: "React", type: "frontend" as const },
  { port: 4000, name: "Remix/Svelte", type: "frontend" as const },
  { port: 4200, name: "Angular", type: "frontend" as const },
  { port: 8080, name: "HTTP Server", type: "other" as const },
  { port: 8000, name: "FastAPI/Django", type: "backend" as const },
  { port: 8001, name: "FastAPI", type: "backend" as const },
  { port: 8888, name: "Jupyter", type: "backend" as const },
  { port: 5000, name: "Flask", type: "backend" as const },
  { port: 4321, name: "Astro", type: "frontend" as const },
];

async function detectLocalServices(): Promise<DetectedService[]> {
  const results: DetectedService[] = [];
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000);

  await Promise.allSettled(
    COMMON_DEV_PORTS.map(async ({ port, name, type }) => {
      try {
        const res = await fetch(`http://localhost:${port}/`, {
          method: "HEAD",
          signal: controller.signal,
          mode: "no-cors",
        });
        // no-cors always returns opaque response, but if we get here the port is open
        if (res.type === "opaque" || res.ok) {
          results.push({ port, name, type, url: `http://localhost:${port}` });
        }
      } catch {
        // Port not available
      }
    }),
  );

  clearTimeout(timeout);
  return results.sort((a, b) => a.port - b.port);
}

// ---------------------------------------------------------------------------
// Action icon helper
// ---------------------------------------------------------------------------

function ActionIcon({ action }: { action: string }) {
  switch (action) {
    case "navigate":
      return <GlobeIcon className="size-3 text-blue-500" />;
    case "click":
      return <MousePointerClickIcon className="size-3 text-orange-500" />;
    case "type":
      return <TypeIcon className="size-3 text-green-500" />;
    case "screenshot":
      return <ImageIcon className="size-3 text-purple-500" />;
    case "scroll":
      return <ArrowLeftIcon className="size-3 text-gray-500" />;
    default:
      return <PlayIcon className="size-3 text-gray-400" />;
  }
}

// ---------------------------------------------------------------------------
// BrowserPreviewPanel
// ---------------------------------------------------------------------------

interface BrowserPreviewPanelProps {
  threadId: string;
  workspacePath?: string | null;
  className?: string;
}

export function BrowserPreviewPanel({
  threadId,
  workspacePath,
  className,
}: BrowserPreviewPanelProps) {
  const { t } = useI18n();
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [pageInfo, setPageInfo] = useState<PageInfo>({ url: "", title: "" });
  const [screenshot, setScreenshot] = useState<string>("");
  const [screenshotSize, setScreenshotSize] = useState({ width: 0, height: 0 });
  const [actionLog, setActionLog] = useState<ActionLogEntry[]>([]);
  const [actionLogExpanded, setActionLogExpanded] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [detectedServices, setDetectedServices] = useState<DetectedService[]>([]);
  const [scanningPorts, setScanningPorts] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);

  const sessionIdentity = useMemo(
    () => createOctopusBrowserSessionIdentity({ threadId, workspacePath }),
    [threadId, workspacePath],
  );
  const sessionId = sessionIdentity.sessionId;

  const applySessionSnapshot = useCallback((next: BrowserSession | null) => {
    setSession(next);
    if (!next) return;
    const snapshotUrl = next.current_url || "";
    const snapshotTitle = next.current_title || "";
    if (snapshotUrl || snapshotTitle) {
      setPageInfo({ url: snapshotUrl, title: snapshotTitle });
      setUrlInput(snapshotUrl);
    }
  }, []);

  const refreshSessionStatus = useCallback(async () => {
    const data = await browserApi.sessionStatus(sessionId);
    applySessionSnapshot(data.exists ? data.session : null);
    return data;
  }, [applySessionSnapshot, sessionId]);

  const refreshBrowserArtifacts = useCallback(async () => {
    const [shotResult, logResult] = await Promise.allSettled([
      browserApi.screenshotBase64(sessionId),
      browserApi.actionLog(sessionId),
    ]);

    if (shotResult.status === "fulfilled") {
      setScreenshot(shotResult.value.base64);
      setScreenshotSize({ width: shotResult.value.width, height: shotResult.value.height });
    } else {
      swallow(shotResult.reason);
    }

    if (logResult.status === "fulfilled") {
      setActionLog(logResult.value.actions);
    } else {
      swallow(logResult.reason);
    }
  }, [sessionId]);

  // Start or reconnect the browser as soon as the panel is opened.
  useEffect(() => {
    let cancelled = false;

    async function ensureSession() {
      setLoading(true);
      setError(null);
      try {
        const status = await browserApi.sessionStatus(sessionId);
        if (cancelled) return;

        if (status.exists) {
          applySessionSnapshot(status.session);
        } else {
          const data = await browserApi.ensure(sessionIdentity);
          if (cancelled) return;
          applySessionSnapshot(data.session);
        }

        await refreshBrowserArtifacts();
      } catch (err) {
        swallow(err);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to launch browser");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void ensureSession();

    return () => {
      cancelled = true;
    };
  }, [applySessionSnapshot, refreshBrowserArtifacts, sessionId, sessionIdentity]);

  // Scan for local services on mount
  useEffect(() => {
    setScanningPorts(true);
    detectLocalServices()
      .then(setDetectedServices)
      .catch(() => setDetectedServices([]))
      .finally(() => setScanningPorts(false));
  }, []);

  const handleRescanPorts = useCallback(() => {
    setScanningPorts(true);
    detectLocalServices()
      .then(setDetectedServices)
      .catch(() => setDetectedServices([]))
      .finally(() => setScanningPorts(false));
  }, []);

  const handleQuickNavigate = useCallback(
    async (url: string) => {
      setUrlInput(url);
      setLoading(true);
      setError(null);
      try {
        if (!session) {
          const data = await browserApi.ensure(sessionIdentity);
          applySessionSnapshot(data.session);
        }
        const info = await browserApi.navigate(sessionIdentity, url);
        setPageInfo(info);
        setUrlInput(info.url);
        const shotData = await browserApi.screenshotBase64(sessionId);
        setScreenshot(shotData.base64);
        setScreenshotSize({ width: shotData.width, height: shotData.height });
        const logData = await browserApi.actionLog(sessionId);
        setActionLog(logData.actions);
        await refreshSessionStatus();
      } catch (err) {
        swallow(err);
        setError(err instanceof Error ? err.message : "Navigation failed");
      } finally {
        setLoading(false);
      }
    },
    [applySessionSnapshot, refreshSessionStatus, session, sessionId, sessionIdentity],
  );

  // Auto-refresh screenshot
  useEffect(() => {
    if (autoRefresh && session) {
      intervalRef.current = setInterval(async () => {
        try {
          const [shotData, info, logData] = await Promise.all([
            browserApi.screenshotBase64(sessionId),
            browserApi.pageInfo(sessionId),
            browserApi.actionLog(sessionId),
          ]);
          setScreenshot(shotData.base64);
          setScreenshotSize({ width: shotData.width, height: shotData.height });
          setPageInfo(info);
          setActionLog(logData.actions);
          void refreshSessionStatus().catch((e) => { swallow(e); });
        } catch (e) { swallow(e); }
      }, 2000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [autoRefresh, refreshSessionStatus, session, sessionId]);

  // Scroll action log to bottom on update
  useEffect(() => {
    if (!actionLogExpanded) return;
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [actionLog.length, actionLogExpanded]);

  const handleLaunch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await browserApi.ensure(sessionIdentity);
      applySessionSnapshot(data.session);
      await refreshBrowserArtifacts();
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : "Failed to launch browser");
    } finally {
      setLoading(false);
    }
  }, [applySessionSnapshot, refreshBrowserArtifacts, sessionIdentity]);

  const handleNavigate = useCallback(async () => {
    if (!urlInput.trim()) return;
    setLoading(true);
    setError(null);
    try {
      // Ensure session exists
      if (!session) {
        const data = await browserApi.ensure(sessionIdentity);
        applySessionSnapshot(data.session);
      }
      let url = urlInput.trim();
      if (!url.startsWith("http://") && !url.startsWith("https://")) {
        url = "https://" + url;
      }
      const info = await browserApi.navigate(sessionIdentity, url);
      setPageInfo(info);
      setUrlInput(info.url);
      // Refresh screenshot
      const shotData = await browserApi.screenshotBase64(sessionId);
      setScreenshot(shotData.base64);
      setScreenshotSize({ width: shotData.width, height: shotData.height });
      // Refresh log
      const logData = await browserApi.actionLog(sessionId);
      setActionLog(logData.actions);
      await refreshSessionStatus();
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : "Navigation failed");
    } finally {
      setLoading(false);
    }
  }, [
    applySessionSnapshot,
    refreshSessionStatus,
    urlInput,
    session,
    sessionId,
    sessionIdentity,
  ]);

  const handleRefreshScreenshot = useCallback(async () => {
    if (!session) return;
    try {
      const [shotData, info, logData] = await Promise.all([
        browserApi.screenshotBase64(sessionId),
        browserApi.pageInfo(sessionId),
        browserApi.actionLog(sessionId),
      ]);
      setScreenshot(shotData.base64);
      setScreenshotSize({ width: shotData.width, height: shotData.height });
      setPageInfo(info);
      setActionLog(logData.actions);
      await refreshSessionStatus();
    } catch (e) { swallow(e); }
  }, [refreshSessionStatus, session, sessionId]);

  const handleBack = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "back");
      if (data.url) setPageInfo({ url: data.url as string, title: (data.title as string) || "" });
      setUrlInput((data.url as string) || "");
      await handleRefreshScreenshot();
    } catch (e) { swallow(e); }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleForward = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "forward");
      if (data.url) setPageInfo({ url: data.url as string, title: (data.title as string) || "" });
      setUrlInput((data.url as string) || "");
      await handleRefreshScreenshot();
    } catch (e) { swallow(e); }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleReload = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "reload");
      if (data.url) setPageInfo({ url: data.url as string, title: (data.title as string) || "" });
      await handleRefreshScreenshot();
    } catch (e) { swallow(e); }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleClose = useCallback(async () => {
    try {
      await browserApi.reset(sessionIdentity);
      setSession(null);
      setScreenshot("");
      setPageInfo({ url: "", title: "" });
      setActionLog([]);
      setAutoRefresh(false);
    } catch (e) { swallow(e); }
  }, [sessionIdentity]);

  const runtimeLabel = session?.runtime || session?.mode || "mock";
  const sessionHealthy = session?.healthy !== false;

  // ----- Render ------------------------------------------------------------

  // Starting state
  if (!session) {
    return (
      <div className={cn("flex flex-col items-center justify-center gap-4 p-6 text-center", className)}>
        {loading ? (
          <Loader2Icon className="text-primary size-10 animate-spin" />
        ) : (
          <GlobeIcon className="text-muted-foreground/50 size-12" />
        )}
        <div>
          <h3 className="text-foreground text-sm font-medium">
            {t.browser.browserAutomation}
          </h3>
          <p className="text-muted-foreground mt-1 text-xs">
            {loading ? t.browser.launchingBrowser : t.browser.browserAutomationDesc}
          </p>
        </div>
        {error && (
          <p className="text-destructive text-xs">{error}</p>
        )}
        {!loading && (
          <button
            onClick={handleLaunch}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? <Loader2Icon className="size-3 animate-spin" /> : <PlayIcon className="size-3" />}
            {t.browser.launchBrowser}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={cn("flex h-full flex-col overflow-hidden", className)}>
      {/* URL Bar */}
      <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5">
        <button
          onClick={handleBack}
          className="text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded transition-colors"
          title={t.browser.back}
        >
          <ArrowLeftIcon className="size-3.5" />
        </button>
        <button
          onClick={handleForward}
          className="text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded transition-colors"
          title={t.browser.forward}
        >
          <ArrowRightIcon className="size-3.5" />
        </button>
        <button
          onClick={handleReload}
          className="text-muted-foreground hover:text-foreground flex size-6 items-center justify-center rounded transition-colors"
          title={t.browser.reload}
        >
          <RefreshCwIcon className="size-3.5" />
        </button>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleNavigate();
          }}
          className="flex min-w-0 flex-1 items-center"
        >
          <div className="relative flex min-w-0 flex-1 items-center">
            <GlobeIcon className="text-muted-foreground absolute left-2 size-3" />
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder={t.browser.urlPlaceholder}
              className="h-7 w-full rounded border border-border bg-muted/50 pl-7 pr-2 text-[11px] outline-none focus:border-ring"
            />
          </div>
        </form>

        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={cn(
            "flex size-6 items-center justify-center rounded transition-colors",
            autoRefresh
              ? "bg-primary/20 text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
          title={autoRefresh ? t.browser.stopAutoRefresh : t.browser.startAutoRefresh}
        >
          {autoRefresh ? (
            <SquareIcon className="size-3" />
          ) : (
            <RefreshCwIcon className="size-3" />
          )}
        </button>

        <span
          className={cn(
            "hidden h-6 shrink-0 items-center gap-1 rounded px-1.5 text-[10px] md:inline-flex",
            sessionHealthy
              ? "text-muted-foreground"
              : "bg-destructive/10 text-destructive",
          )}
          title={`Session ${sessionHealthy ? "healthy" : "needs reset"} · ${runtimeLabel}`}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              sessionHealthy ? "bg-emerald-500" : "bg-destructive",
            )}
          />
          {runtimeLabel}
        </span>

        <button
          onClick={handleClose}
          className="text-muted-foreground hover:text-destructive flex size-6 items-center justify-center rounded transition-colors"
          title={t.browser.closeSession}
        >
          <XIcon className="size-3.5" />
        </button>
      </div>

      {/* Page title */}
      {pageInfo.title && (
        <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1">
          <span className="text-muted-foreground truncate text-[10px]">
            {pageInfo.title}
          </span>
          {pageInfo.url && (
            <a
              href={pageInfo.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground/60 hover:text-foreground shrink-0"
              title={t.browser.openExternal}
            >
              <ExternalLinkIcon className="size-3" />
            </a>
          )}
        </div>
      )}

      {/* Screenshot area */}
      <div className="relative flex-1 overflow-auto bg-black/5">
        {screenshot ? (
          <img
            src={`data:image/png;base64,${screenshot}`}
            alt={t.browser.browserAutomation}
            className="w-full object-contain"
            onClick={handleRefreshScreenshot}
            title={t.browser.clickToRefresh}
            style={{ cursor: "pointer" }}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center p-4">
            {/* 本地服务快速入口 */}
            {detectedServices.length > 0 ? (
              <div className="w-full max-w-xs space-y-3">
                <div className="flex items-center gap-2">
                  <ServerIcon className="size-3.5 text-muted-foreground" />
                  <span className="text-[11px] font-medium text-foreground">
                    本地服务
                  </span>
                  <button
                    onClick={handleRescanPorts}
                    disabled={scanningPorts}
                    className="ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
                  >
                    {scanningPorts ? (
                      <Loader2Icon className="size-3 animate-spin" />
                    ) : (
                      <RefreshCwIcon className="size-3" />
                    )}
                    扫描
                  </button>
                </div>
                <div className="space-y-1.5">
                  {detectedServices.map((svc) => (
                    <button
                      key={svc.port}
                      onClick={() => handleQuickNavigate(svc.url)}
                      className="flex w-full items-center gap-3 rounded-lg border border-border/55 bg-background/80 px-3 py-2 text-left transition-colors hover:border-border hover:bg-muted/50"
                    >
                      <div
                        className={cn(
                          "flex size-8 shrink-0 items-center justify-center rounded-md text-xs font-bold",
                          svc.type === "frontend"
                            ? "bg-blue-500/10 text-blue-600"
                            : svc.type === "backend"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : "bg-muted text-muted-foreground",
                        )}
                      >
                        {svc.port}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium text-foreground">
                          {svc.name}
                        </div>
                        <div className="truncate text-[10px] text-muted-foreground">
                          localhost:{svc.port}
                        </div>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-0.5 text-[9px] font-medium",
                          svc.type === "frontend"
                            ? "bg-blue-500/10 text-blue-600"
                            : svc.type === "backend"
                              ? "bg-emerald-500/10 text-emerald-600"
                              : "bg-muted text-muted-foreground",
                        )}
                      >
                        {svc.type === "frontend" ? "前端" : svc.type === "backend" ? "后端" : "服务"}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center">
                <ImageIcon className="text-muted-foreground/30 mx-auto size-8" />
                <p className="text-muted-foreground/50 mt-2 text-xs">
                  {t.browser.navigateHint}
                </p>
                <button
                  onClick={handleRescanPorts}
                  disabled={scanningPorts}
                  className="mt-3 flex items-center gap-1.5 rounded-md border border-border/55 px-3 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
                >
                  {scanningPorts ? (
                    <Loader2Icon className="size-3 animate-spin" />
                  ) : (
                    <RefreshCwIcon className="size-3" />
                  )}
                  扫描本地服务
                </button>
              </div>
            )}
          </div>
        )}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/60">
            <Loader2Icon className="text-primary size-6 animate-spin" />
          </div>
        )}
        {screenshotSize.width > 0 && (
          <span className="text-muted-foreground/50 absolute right-1 bottom-1 text-[9px]">
            {screenshotSize.width}x{screenshotSize.height}
          </span>
        )}
      </div>

      {/* Action Log */}
      <div className="shrink-0 border-t">
        <button
          type="button"
          onClick={() => setActionLogExpanded((value) => !value)}
          aria-expanded={actionLogExpanded}
          className="flex w-full items-center justify-between gap-2 px-2 py-1 text-left transition-colors hover:bg-muted/45"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <ChevronDownIcon
              className={cn(
                "text-muted-foreground/70 size-3 shrink-0 transition-transform",
                !actionLogExpanded && "-rotate-90",
              )}
            />
            <span className="text-muted-foreground truncate text-[10px] font-medium uppercase tracking-wide">
              {t.browser.actionLog}
            </span>
          </span>
          <span className="text-muted-foreground/60 shrink-0 text-[10px]">
            {t.browser.actions(actionLog.length)}
          </span>
        </button>
        {actionLogExpanded && (
          <div className="max-h-32 overflow-auto px-2 pb-2">
            {actionLog.length === 0 ? (
              <p className="text-muted-foreground/50 py-2 text-center text-[10px]">
                {t.browser.noActions}
              </p>
            ) : (
              <div className="space-y-0.5">
                {actionLog.slice(-20).map((entry, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-1.5 text-[10px]"
                  >
                    <ActionIcon action={entry.action} />
                    <span className="text-foreground/80 font-medium">
                      {entry.action}
                    </span>
                    <span className="text-muted-foreground min-w-0 truncate">
                      {entry.detail}
                    </span>
                    <span className="text-muted-foreground/40 ml-auto shrink-0 tabular-nums">
                      {new Date(entry.timestamp * 1000).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                  </div>
                ))}
                <div ref={logEndRef} />
              </div>
            )}
          </div>
        )}
      </div>

      {error && (
        <div className="border-destructive/30 bg-destructive/10 shrink-0 border-t px-2 py-1">
          <p className="text-destructive text-[10px]">{error}</p>
        </div>
      )}
    </div>
  );
}
