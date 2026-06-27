import {
  ArrowLeftIcon,
  ArrowRightIcon,
  ChevronDownIcon,
  ExternalLinkIcon,
  FileTextIcon,
  GlobeIcon,
  ImageIcon,
  Loader2Icon,
  MousePointerClickIcon,
  MonitorIcon,
  PlayIcon,
  RefreshCwIcon,
  ServerIcon,
  SmartphoneIcon,
  SquareIcon,
  TabletIcon,
  TypeIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { toast } from "sonner";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import {
  createOctopusBrowserSessionIdentity,
  type OctopusBrowserSessionIdentity,
} from "@/core/browser/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  BROWSER_OPEN_URL_REQUEST_KEY,
  type BrowserOpenUrlRequest,
  type BrowserTab,
} from "@/components/browser/browser-store";
import {
  WebviewTab,
  type WebviewTabHandle,
} from "@/components/browser/webview-tab";

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
  viewport_width?: number;
  viewport_height?: number;
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
  status?: string;
  error?: string;
  metadata?: Record<string, unknown>;
  timestamp: number;
}

interface PageInfo {
  url: string;
  title: string;
}

async function dataUrlToFile(
  dataUrl: string,
  filename: string,
  fallbackMime = "image/png",
): Promise<File> {
  const response = await fetch(dataUrl);
  const blob = await response.blob();
  return new File([blob], filename, {
    type: blob.type || fallbackMime,
  });
}

interface BrowserSessionHealth {
  schema: "octopus.browser_session_health.v1";
  exists: boolean;
  healthy: boolean;
  score: number;
  issues: string[];
  session: BrowserSession;
  recent_actions: ActionLogEntry[];
  replay_ready: boolean;
  stale_seconds?: number;
}

const DEVICE_PREVIEW_PRESETS = {
  desktop: {
    label: "Desktop",
    width: 1440,
    height: 900,
    Icon: MonitorIcon,
  },
  laptop: {
    label: "Laptop",
    width: 1024,
    height: 768,
    Icon: MonitorIcon,
  },
  fourK: {
    label: "4K",
    width: 3840,
    height: 2160,
    Icon: MonitorIcon,
  },
  ipadAir: {
    label: "iPad Air",
    width: 768,
    height: 1024,
    Icon: TabletIcon,
  },
  ipadMini: {
    label: "iPad mini",
    width: 744,
    height: 1133,
    Icon: TabletIcon,
  },
  surfacePro7: {
    label: "Surface Pro",
    width: 912,
    height: 1368,
    Icon: TabletIcon,
  },
  surfaceDuo: {
    label: "Surface Duo",
    width: 540,
    height: 720,
    Icon: SmartphoneIcon,
  },
  iphone15ProMax: {
    label: "iPhone 15 PM",
    width: 430,
    height: 932,
    Icon: SmartphoneIcon,
  },
  pixel8: {
    label: "Pixel 8",
    width: 412,
    height: 915,
    Icon: SmartphoneIcon,
  },
  iphone15Pro: {
    label: "iPhone 15 Pro",
    width: 390,
    height: 844,
    Icon: SmartphoneIcon,
  },
  galaxyS24Ultra: {
    label: "Galaxy S24",
    width: 412,
    height: 915,
    Icon: SmartphoneIcon,
  },
  iphoneSE: {
    label: "iPhone SE",
    width: 375,
    height: 667,
    Icon: SmartphoneIcon,
  },
} as const;

type DevicePreviewPreset = keyof typeof DEVICE_PREVIEW_PRESETS;
type PreviewSurfaceMode = "screenshot" | "live";

interface BrowserSemanticSnapshot {
  role?: string;
  name?: string;
  url?: string;
  text?: string;
  truncated?: boolean;
}

interface ScreenshotPointerPoint {
  x: number;
  y: number;
  mode: "click" | "double";
  timestamp: number;
}

function presetForViewport(
  width?: number,
  height?: number,
): DevicePreviewPreset | null {
  if (!width || !height) return null;
  const match = (
    Object.keys(DEVICE_PREVIEW_PRESETS) as DevicePreviewPreset[]
  ).find((preset) => {
    const target = DEVICE_PREVIEW_PRESETS[preset];
    return target.width === width && target.height === height;
  });
  return match ?? null;
}

function normalizePreviewUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  if (
    /^(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|::1)(:\d+)?(\/|$)/i.test(
      trimmed,
    )
  ) {
    return `http://${trimmed}`;
  }
  return "";
}

function browserTabDeviceForPreset(
  preset: DevicePreviewPreset,
): BrowserTab["device"] {
  if (preset === "desktop" || preset === "laptop" || preset === "fourK") {
    return "desktop";
  }
  return DEVICE_PREVIEW_PRESETS[preset].width <= 540 ? "mobile" : "tablet";
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const browserApi = {
  async sessionStatus(
    sessionId: string,
  ): Promise<{ exists: boolean; session: BrowserSession }> {
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
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/session/ensure`,
      {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          session_id: identity.sessionId,
          project_id: identity.projectId,
          profile_id: identity.profileId,
          headless: true,
        }),
      },
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(data.detail || "Failed to start browser session");
    }
    return res.json();
  },

  async setViewport(
    identity: OctopusBrowserSessionIdentity,
    width: number,
    height: number,
  ): Promise<{ ok: boolean; session: BrowserSession }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/session/viewport`,
      {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          session_id: identity.sessionId,
          project_id: identity.projectId,
          profile_id: identity.profileId,
          width,
          height,
          headless: true,
        }),
      },
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(data.detail || "Failed to update browser viewport");
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

  async navigate(
    identity: OctopusBrowserSessionIdentity,
    url: string,
  ): Promise<PageInfo> {
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

  async semanticSnapshot(
    identity: OctopusBrowserSessionIdentity,
  ): Promise<BrowserSemanticSnapshot> {
    const res = await fetch(`${getBackendBaseURL()}/api/browser/action`, {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        session_id: identity.sessionId,
        project_id: identity.projectId,
        profile_id: identity.profileId,
        action: "aria",
      }),
    });
    if (!res.ok) throw new Error("Semantic snapshot failed");
    const data = await res.json();
    return (data.nodes ?? {}) as BrowserSemanticSnapshot;
  },

  async queueReplayCase(sessionId: string): Promise<{ ok: boolean }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/session/replay-case/queue`,
      {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          session_id: sessionId,
          reason: "agent preview handoff",
          priority: "normal",
        }),
      },
    );
    if (!res.ok) {
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(data.detail || "Failed to queue replay case");
    }
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

  async sessionHealth(sessionId: string): Promise<BrowserSessionHealth | null> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/browser/session/health?session_id=${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return null;
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
    case "click_at":
    case "double_click_at":
      return <MousePointerClickIcon className="size-3 text-orange-500" />;
    case "type":
      return <TypeIcon className="size-3 text-green-500" />;
    case "screenshot":
      return <ImageIcon className="size-3 text-purple-500" />;
    case "viewport":
      return <MonitorIcon className="size-3 text-cyan-500" />;
    case "scroll":
      return <ArrowLeftIcon className="size-3 text-muted-foreground" />;
    default:
      return <PlayIcon className="size-3 text-muted-foreground" />;
  }
}

function actionStatusLabel(
  entry: ActionLogEntry,
  t: { actionPending: string; actionSuccess: string; actionFailed: string },
): string {
  if (!entry.status) return t.actionPending;
  if (entry.status === "ok") return t.actionSuccess;
  if (entry.status === "error") return t.actionFailed;
  return entry.status;
}

function actionStatusClass(entry: ActionLogEntry): string {
  if (entry.status === "ok") return "bg-emerald-500/10 text-emerald-600";
  if (entry.status && entry.status !== "ok") {
    return "bg-destructive/10 text-destructive";
  }
  return "bg-muted text-muted-foreground";
}

function actionCoordinateLabel(entry: ActionLogEntry): string | null {
  const point = actionCoordinatePoint(entry);
  return point ? `${point.x}, ${point.y}` : null;
}

function actionCoordinatePoint(
  entry: ActionLogEntry,
): Pick<ScreenshotPointerPoint, "x" | "y"> | null {
  const x = entry.metadata?.x;
  const y = entry.metadata?.y;
  if (typeof x === "number" && typeof y === "number") {
    return { x: Math.round(x), y: Math.round(y) };
  }
  const match = entry.detail.match(/x[=:]\s*(\d+).*y[=:]\s*(\d+)/i);
  return match ? { x: Number(match[1]), y: Number(match[2]) } : null;
}

function actionDetailLabel(
  entry: ActionLogEntry,
  t: { coordinateLabel: (coord: string) => string; noDetail: string },
): string {
  if (entry.error) return entry.error;
  if (entry.detail) return entry.detail;
  const coord = actionCoordinateLabel(entry);
  return coord ? t.coordinateLabel(coord) : t.noDetail;
}

function actionEntryKey(entry: ActionLogEntry, absoluteIndex: number): string {
  return `${entry.timestamp}-${entry.action}-${absoluteIndex}`;
}

// ---------------------------------------------------------------------------
// BrowserPreviewPanel
// ---------------------------------------------------------------------------

interface BrowserPreviewPanelProps {
  threadId: string;
  workspacePath?: string | null;
  /** Seed the panel with a URL to load on mount — lets the live-preview panel
   * delegate its URL mode here (and the agent regression preview point at it)
   * so there is one controllable URL-preview surface. Additive: when unset the
   * panel behaves exactly as before. */
  initialUrl?: string;
  className?: string;
}

export function BrowserPreviewPanel({
  threadId,
  workspacePath,
  initialUrl,
  className,
}: BrowserPreviewPanelProps) {
  const { t } = useI18n();
  const bp = t.browserPreviewPanel;
  const [session, setSession] = useState<BrowserSession | null>(null);
  const [pageInfo, setPageInfo] = useState<PageInfo>({ url: "", title: "" });
  const [screenshot, setScreenshot] = useState<string>("");
  const [screenshotSize, setScreenshotSize] = useState({ width: 0, height: 0 });
  const [actionLog, setActionLog] = useState<ActionLogEntry[]>([]);
  const [selectedActionKey, setSelectedActionKey] = useState<string | null>(
    null,
  );
  const [sessionHealth, setSessionHealth] =
    useState<BrowserSessionHealth | null>(null);
  const [actionLogExpanded, setActionLogExpanded] = useState(false);
  const [urlInput, setUrlInput] = useState(initialUrl ?? "");
  const [loading, setLoading] = useState(true);
  const [viewportChanging, setViewportChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [detectedServices, setDetectedServices] = useState<DetectedService[]>(
    [],
  );
  const [scanningPorts, setScanningPorts] = useState(false);
  const [semanticSnapshot] = useState<BrowserSemanticSnapshot | null>(null);
  const [semanticOpen, setSemanticOpen] = useState(false);
  const [pointerMode] = useState<"click" | "double">("click");
  const [hoverPoint, setHoverPoint] = useState<ScreenshotPointerPoint | null>(
    null,
  );
  const [clickMarker, setClickMarker] = useState<ScreenshotPointerPoint | null>(
    null,
  );
  const [surfaceMode, setSurfaceMode] =
    useState<PreviewSurfaceMode>("screenshot");
  const [liveFrameLoaded, setLiveFrameLoaded] = useState(false);
  const [devicePreview, setDevicePreview] =
    useState<DevicePreviewPreset>("desktop");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const logEndRef = useRef<HTMLDivElement>(null);
  const clickMarkerTimeoutRef = useRef<number | null>(null);

  const sessionIdentity = useMemo(
    () => createOctopusBrowserSessionIdentity({ threadId, workspacePath }),
    [threadId, workspacePath],
  );
  const sessionId = sessionIdentity.sessionId;
  const liveWebviewRef = useRef<WebviewTabHandle | null>(null);
  const [liveTab, setLiveTab] = useState<BrowserTab>(() => ({
    id: `agent-live-${Date.now().toString(36)}`,
    url: "about:blank",
    title: bp.livePreviewTitle,
    isLoading: false,
    device: "desktop",
  }));

  const applySessionSnapshot = useCallback((next: BrowserSession | null) => {
    setSession(next);
    if (!next) return;
    const matchedPreset = presetForViewport(
      next.viewport_width,
      next.viewport_height,
    );
    if (matchedPreset) {
      setDevicePreview(matchedPreset);
    }
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
    const [shotResult, logResult, healthResult] = await Promise.allSettled([
      browserApi.screenshotBase64(sessionId),
      browserApi.actionLog(sessionId),
      browserApi.sessionHealth(sessionId),
    ]);

    if (shotResult.status === "fulfilled") {
      setScreenshot(shotResult.value.base64);
      setScreenshotSize({
        width: shotResult.value.width,
        height: shotResult.value.height,
      });
    } else {
      swallow(shotResult.reason);
    }

    if (logResult.status === "fulfilled") {
      setActionLog(logResult.value.actions);
    } else {
      swallow(logResult.reason);
    }

    if (healthResult.status === "fulfilled") {
      setSessionHealth(healthResult.value);
    } else {
      swallow(healthResult.reason);
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
          setError(
            err instanceof Error ? err.message : "Failed to launch browser",
          );
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
  }, [
    applySessionSnapshot,
    refreshBrowserArtifacts,
    sessionId,
    sessionIdentity,
  ]);

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
        const [logData, healthData] = await Promise.all([
          browserApi.actionLog(sessionId),
          browserApi.sessionHealth(sessionId),
        ]);
        setActionLog(logData.actions);
        setSessionHealth(healthData);
        await refreshSessionStatus();
      } catch (err) {
        swallow(err);
        setError(err instanceof Error ? err.message : "Navigation failed");
      } finally {
        setLoading(false);
      }
    },
    [
      applySessionSnapshot,
      refreshSessionStatus,
      session,
      sessionId,
      sessionIdentity,
    ],
  );

  // Auto-refresh screenshot
  useEffect(() => {
    if (autoRefresh && session) {
      intervalRef.current = setInterval(async () => {
        try {
          const [shotData, info, logData, healthData] = await Promise.all([
            browserApi.screenshotBase64(sessionId),
            browserApi.pageInfo(sessionId),
            browserApi.actionLog(sessionId),
            browserApi.sessionHealth(sessionId),
          ]);
          setScreenshot(shotData.base64);
          setScreenshotSize({ width: shotData.width, height: shotData.height });
          setPageInfo(info);
          setActionLog(logData.actions);
          setSessionHealth(healthData);
          void refreshSessionStatus().catch((e) => {
            swallow(e);
          });
        } catch (e) {
          swallow(e);
        }
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

  useEffect(() => {
    setLiveFrameLoaded(false);
  }, [pageInfo.url, urlInput]);

  useEffect(
    () => () => {
      if (clickMarkerTimeoutRef.current) {
        clearTimeout(clickMarkerTimeoutRef.current);
      }
    },
    [],
  );

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
      const [logData, healthData] = await Promise.all([
        browserApi.actionLog(sessionId),
        browserApi.sessionHealth(sessionId),
      ]);
      setActionLog(logData.actions);
      setSessionHealth(healthData);
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
      const [shotData, info, logData, healthData] = await Promise.all([
        browserApi.screenshotBase64(sessionId),
        browserApi.pageInfo(sessionId),
        browserApi.actionLog(sessionId),
        browserApi.sessionHealth(sessionId),
      ]);
      setScreenshot(shotData.base64);
      setScreenshotSize({ width: shotData.width, height: shotData.height });
      setPageInfo(info);
      setActionLog(logData.actions);
      setSessionHealth(healthData);
      await refreshSessionStatus();
    } catch (e) {
      swallow(e);
    }
  }, [refreshSessionStatus, session, sessionId]);

  const handleAttachScreenshotToComposer = useCallback(async () => {
    try {
      let screenshotDataUrl = screenshot
        ? `data:image/png;base64,${screenshot}`
        : "";
      if (!screenshotDataUrl && session) {
        const shotData = await browserApi.screenshotBase64(sessionId);
        setScreenshot(shotData.base64);
        setScreenshotSize({ width: shotData.width, height: shotData.height });
        screenshotDataUrl = `data:image/png;base64,${shotData.base64}`;
      }
      if (!screenshotDataUrl) {
        toast.error(bp.noReadableText);
        return;
      }
      const host = (() => {
        try {
          return pageInfo.url ? new URL(pageInfo.url).hostname : "browser";
        } catch {
          return "browser";
        }
      })();
      const file = await dataUrlToFile(
        screenshotDataUrl,
        `browser-shot-${host}-${Date.now()}.png`,
      );
      window.dispatchEvent(
        new CustomEvent("octopus:inject-composer-images", {
          detail: {
            threadId,
            images: [file],
            sourceLabel: bp.attachScreenshotSource,
          },
        }),
      );
      toast.success(bp.attachScreenshotSuccess);
    } catch (error) {
      swallow(error);
      toast.error(bp.attachScreenshotFailed);
    }
  }, [bp, pageInfo.url, screenshot, session, sessionId, threadId]);

  const handleBack = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "back");
      if (data.url)
        setPageInfo({
          url: data.url as string,
          title: (data.title as string) || "",
        });
      setUrlInput((data.url as string) || "");
      await handleRefreshScreenshot();
    } catch (e) {
      swallow(e);
    }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleForward = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "forward");
      if (data.url)
        setPageInfo({
          url: data.url as string,
          title: (data.title as string) || "",
        });
      setUrlInput((data.url as string) || "");
      await handleRefreshScreenshot();
    } catch (e) {
      swallow(e);
    }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleReload = useCallback(async () => {
    if (!session) return;
    try {
      const data = await browserApi.action(sessionIdentity, "reload");
      if (data.url)
        setPageInfo({
          url: data.url as string,
          title: (data.title as string) || "",
        });
      await handleRefreshScreenshot();
    } catch (e) {
      swallow(e);
    }
  }, [session, sessionIdentity, handleRefreshScreenshot]);

  const handleDevicePreviewChange = useCallback(
    async (preset: DevicePreviewPreset) => {
      const target = DEVICE_PREVIEW_PRESETS[preset];
      setDevicePreview(preset);
      setViewportChanging(true);
      setError(null);
      try {
        const data = await browserApi.setViewport(
          sessionIdentity,
          target.width,
          target.height,
        );
        applySessionSnapshot(data.session);
        await refreshBrowserArtifacts();
      } catch (err) {
        swallow(err);
        setError(
          err instanceof Error ? err.message : "Failed to update viewport",
        );
      } finally {
        setViewportChanging(false);
      }
    },
    [applySessionSnapshot, refreshBrowserArtifacts, sessionIdentity],
  );

  const handleScreenshotPointer = useCallback(
    async (event: ReactMouseEvent<HTMLImageElement>) => {
      if (!session || screenshotSize.width <= 0 || screenshotSize.height <= 0) {
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      const x = Math.round(
        ((event.clientX - rect.left) / Math.max(1, rect.width)) *
          screenshotSize.width,
      );
      const y = Math.round(
        ((event.clientY - rect.top) / Math.max(1, rect.height)) *
          screenshotSize.height,
      );
      setClickMarker({
        x,
        y,
        mode: pointerMode,
        timestamp: Date.now(),
      });
      if (clickMarkerTimeoutRef.current) {
        clearTimeout(clickMarkerTimeoutRef.current);
      }
      clickMarkerTimeoutRef.current = window.setTimeout(
        () => setClickMarker(null),
        1800,
      );
      setLoading(true);
      setError(null);
      try {
        await browserApi.action(
          sessionIdentity,
          pointerMode === "double" ? "double_click_at" : "click_at",
          { x, y },
        );
        await handleRefreshScreenshot();
      } catch (err) {
        swallow(err);
        setError(err instanceof Error ? err.message : "Browser click failed");
      } finally {
        setLoading(false);
      }
    },
    [
      handleRefreshScreenshot,
      pointerMode,
      screenshotSize.height,
      screenshotSize.width,
      session,
      sessionIdentity,
    ],
  );

  const handleScreenshotHover = useCallback(
    (event: ReactMouseEvent<HTMLImageElement>) => {
      if (screenshotSize.width <= 0 || screenshotSize.height <= 0) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const x = Math.round(
        ((event.clientX - rect.left) / Math.max(1, rect.width)) *
          screenshotSize.width,
      );
      const y = Math.round(
        ((event.clientY - rect.top) / Math.max(1, rect.height)) *
          screenshotSize.height,
      );
      setHoverPoint({ x, y, mode: pointerMode, timestamp: Date.now() });
    },
    [pointerMode, screenshotSize.height, screenshotSize.width],
  );

  const focusActionEntry = useCallback(
    (entry: ActionLogEntry, absoluteIndex: number) => {
      setSelectedActionKey(
        `${entry.timestamp}-${entry.action}-${absoluteIndex}`,
      );
      setActionLogExpanded(true);
      const point = actionCoordinatePoint(entry);
      if (!point) return;
      setClickMarker({
        ...point,
        mode: entry.action === "double_click_at" ? "double" : "click",
        timestamp: Date.now(),
      });
      if (clickMarkerTimeoutRef.current) {
        clearTimeout(clickMarkerTimeoutRef.current);
      }
      clickMarkerTimeoutRef.current = window.setTimeout(
        () => setClickMarker(null),
        2600,
      );
    },
    [],
  );

  const handleClose = useCallback(async () => {
    try {
      await browserApi.reset(sessionIdentity);
      setSession(null);
      setScreenshot("");
      setPageInfo({ url: "", title: "" });
      setActionLog([]);
      setSelectedActionKey(null);
      setSessionHealth(null);
      setAutoRefresh(false);
    } catch (e) {
      swallow(e);
    }
  }, [sessionIdentity]);

  const openInFullBrowser = useCallback(() => {
    const target = pageInfo.url || urlInput.trim();
    if (target) {
      try {
        const request: BrowserOpenUrlRequest = {
          url: target,
          title: pageInfo.title || target,
          device: browserTabDeviceForPreset(devicePreview),
          source: "agent-preview",
          sessionId,
        };
        localStorage.setItem(
          BROWSER_OPEN_URL_REQUEST_KEY,
          JSON.stringify(request),
        );
      } catch (e) {
        swallow(e);
      }
    }
    window.location.hash = "/browser";
  }, [devicePreview, pageInfo.title, pageInfo.url, sessionId, urlInput]);

  const runtimeLabel = session?.runtime || session?.mode || "mock";
  const sessionHealthy = (sessionHealth?.healthy ?? session?.healthy) !== false;
  const sessionIssues = sessionHealth?.issues ?? [];
  const visibleActions = actionLog.slice(-20);
  const visibleActionStartIndex = actionLog.length - visibleActions.length;
  const actionFailureCount = actionLog.filter(
    (entry) => entry.status && entry.status !== "ok",
  ).length;
  const actionCoordinateCount = actionLog.filter((entry) =>
    Boolean(actionCoordinatePoint(entry)),
  ).length;
  const selectedAction =
    selectedActionKey == null
      ? null
      : (actionLog
          .map((entry, index) => ({ entry, index }))
          .find(
            ({ entry, index }) =>
              actionEntryKey(entry, index) === selectedActionKey,
          ) ?? null);
  const activeDevicePreview = DEVICE_PREVIEW_PRESETS[devicePreview];
  const deviceFrameKind =
    devicePreview === "desktop"
      ? "desktop"
      : activeDevicePreview.width <= 540
        ? "phone"
        : "tablet";
  const currentViewportLabel = `${activeDevicePreview.width}x${activeDevicePreview.height}`;
  const livePreviewUrl = normalizePreviewUrl(pageInfo.url || urlInput);
  const canLivePreview = Boolean(livePreviewUrl);
  const effectiveSurfaceMode =
    surfaceMode === "live" && canLivePreview ? "live" : "screenshot";
  const electronLiveSurface =
    typeof window !== "undefined" && Boolean(window.octopus?.isElectron);

  useEffect(() => {
    if (!livePreviewUrl) return;
    setLiveTab((prev) => ({
      ...prev,
      url: livePreviewUrl,
      title: pageInfo.title || livePreviewUrl,
      isLoading: false,
      device: browserTabDeviceForPreset(devicePreview),
    }));
  }, [devicePreview, livePreviewUrl, pageInfo.title]);

  // Seed-and-load an externally supplied URL (initialUrl). Fires once per
  // distinct URL: ensures the session and navigates, so a caller that delegates
  // its preview here (live-preview-panel URL mode, agent regression preview)
  // loads that page in this one controllable surface. Inert when initialUrl is
  // unset, so existing callers are unaffected.
  const initialUrlLoadedRef = useRef<string | null>(null);
  useEffect(() => {
    const target = (initialUrl ?? "").trim();
    if (!target || initialUrlLoadedRef.current === target) return;
    initialUrlLoadedRef.current = target;
    let url = target;
    if (!/^https?:\/\//i.test(url) && !url.startsWith("about:")) {
      url = "https://" + url;
    }
    setUrlInput(url);
    void (async () => {
      try {
        const data = await browserApi.ensure(sessionIdentity);
        applySessionSnapshot(data.session);
        const info = await browserApi.navigate(sessionIdentity, url);
        setPageInfo(info);
        setUrlInput(info.url);
      } catch (err) {
        swallow(err);
      }
    })();
  }, [initialUrl, sessionIdentity, applySessionSnapshot]);

  // ----- Render ------------------------------------------------------------

  // Starting state
  if (!session) {
    return (
      <div
        className={cn(
          "relative flex h-full flex-col items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.10),transparent_38%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.42))] p-6 text-center",
          className,
        )}
      >
        <div className="absolute inset-x-8 top-6 h-px bg-gradient-to-r from-transparent via-border/70 to-transparent" />
        <div className="grid size-14 place-items-center rounded-2xl border border-border/60 bg-background/82 shadow-sm backdrop-blur">
          {loading ? (
            <Loader2Icon className="size-8 animate-spin text-primary" />
          ) : (
            <GlobeIcon className="size-8 text-muted-foreground/60" />
          )}
        </div>
        <div className="max-w-sm">
          <h3 className="text-sm font-semibold text-foreground">
            {t.browser.browserAutomation}
          </h3>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {loading
              ? t.browser.launchingBrowser
              : t.browser.browserAutomationDesc}
          </p>
        </div>
        {error && <p className="text-destructive text-xs">{error}</p>}
        {!loading && (
          <button
            onClick={handleLaunch}
            disabled={loading}
            className="inline-flex h-8 items-center gap-2 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? (
              <Loader2Icon className="size-3 animate-spin" />
            ) : (
              <PlayIcon className="size-3" />
            )}
            {t.browser.launchBrowser}
          </button>
        )}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex h-full flex-col overflow-hidden bg-background",
        className,
      )}
    >
      {/* URL Bar */}
      <div className="flex shrink-0 items-center gap-1 border-b border-border/60 bg-background/82 px-2 py-1.5 shadow-[inset_0_-1px_0_rgba(255,255,255,0.22)] backdrop-blur-xl">
        <button
          onClick={handleBack}
          className="grid size-7 place-items-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border/60 hover:bg-muted/65 hover:text-foreground"
          title={t.browser.back}
        >
          <ArrowLeftIcon className="size-3.5" />
        </button>
        <button
          onClick={handleForward}
          className="grid size-7 place-items-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border/60 hover:bg-muted/65 hover:text-foreground"
          title={t.browser.forward}
        >
          <ArrowRightIcon className="size-3.5" />
        </button>
        <button
          onClick={handleReload}
          className="grid size-7 place-items-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border/60 hover:bg-muted/65 hover:text-foreground"
          title={t.browser.reload}
        >
          <RefreshCwIcon className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => void handleAttachScreenshotToComposer()}
          className="grid size-7 place-items-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border/60 hover:bg-muted/65 hover:text-foreground"
          title={bp.attachScreenshotToComposer}
        >
          <ImageIcon className="size-3.5" />
        </button>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleNavigate();
          }}
          className="flex min-w-0 flex-1 items-center"
        >
          <div className="relative flex h-7 min-w-0 flex-1 items-center rounded-md border border-border/60 bg-muted/45 shadow-inner transition-colors focus-within:border-ring focus-within:bg-background/80">
            <GlobeIcon className="absolute left-2 size-3 text-muted-foreground" />
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder={t.browser.urlPlaceholder}
              className="h-full w-full bg-transparent pl-7 pr-2 text-[11px] outline-none"
            />
          </div>
        </form>

        <button
          type="button"
          onClick={() =>
            setSurfaceMode(
              effectiveSurfaceMode === "live" ? "screenshot" : "live",
            )
          }
          disabled={!canLivePreview}
          className={cn(
            "hidden h-7 shrink-0 items-center gap-1 rounded-md border border-transparent px-1.5 text-[10px] font-medium transition-colors sm:inline-flex",
            effectiveSurfaceMode === "live"
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:border-border/60 hover:bg-muted/65 hover:text-foreground",
            !canLivePreview && "pointer-events-none opacity-35",
          )}
          title={bp.toggleSurfaceMode}
        >
          {effectiveSurfaceMode === "live" ? (
            <MonitorIcon className="size-3" />
          ) : (
            <ImageIcon className="size-3" />
          )}
          {effectiveSurfaceMode === "live"
            ? bp.surfaceModeLive
            : bp.surfaceModeScreenshot}
        </button>

        <select
          value={devicePreview}
          onChange={(event) =>
            void handleDevicePreviewChange(
              event.target.value as DevicePreviewPreset,
            )
          }
          disabled={viewportChanging}
          className="hidden h-7 max-w-[112px] shrink-0 rounded-md border border-border/50 bg-background/70 px-1.5 text-[10px] font-medium text-muted-foreground outline-none hover:text-foreground md:block"
          title={bp.selectDevicePreset}
        >
          {(Object.keys(DEVICE_PREVIEW_PRESETS) as DevicePreviewPreset[]).map(
            (preset) => {
              const device = DEVICE_PREVIEW_PRESETS[preset];
              return (
                <option key={preset} value={preset}>
                  {preset === "desktop" ? bp.desktopLabel : device.label}
                </option>
              );
            },
          )}
        </select>

        <button
          onClick={() => setAutoRefresh(!autoRefresh)}
          className={cn(
            "hidden size-7 place-items-center rounded-md border border-transparent transition-colors lg:grid",
            autoRefresh
              ? "border-primary/20 bg-primary/15 text-primary"
              : "text-muted-foreground hover:border-border/60 hover:bg-muted/65 hover:text-foreground",
          )}
          title={
            autoRefresh ? t.browser.stopAutoRefresh : t.browser.startAutoRefresh
          }
        >
          {autoRefresh ? (
            <SquareIcon className="size-3" />
          ) : (
            <RefreshCwIcon className="size-3" />
          )}
        </button>

        <span
          className={cn(
            "hidden size-7 shrink-0 place-items-center rounded-md text-[10px] lg:grid",
            sessionHealthy
              ? "text-muted-foreground"
              : "bg-destructive/10 text-destructive",
          )}
          title={`${sessionHealthy ? "Session healthy" : sessionIssues.join(", ") || "needs reset"} · ${runtimeLabel}`}
        >
          <span
            className={cn(
              "size-1.5 rounded-full",
              sessionHealthy ? "bg-emerald-500" : "bg-destructive",
            )}
          />
        </span>

        <button
          type="button"
          onClick={openInFullBrowser}
          className="flex h-7 shrink-0 items-center gap-1 rounded-md border border-primary/15 bg-primary/10 px-2 text-[10px] font-medium text-primary shadow-sm transition-colors hover:bg-primary/15"
          title={bp.continueInFullBrowser}
        >
          <ExternalLinkIcon className="size-3" />
          <span>{bp.takeoverButton}</span>
        </button>

        <button
          onClick={handleClose}
          className="grid size-7 place-items-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-destructive/20 hover:bg-destructive/10 hover:text-destructive"
          title={t.browser.closeSession}
        >
          <XIcon className="size-3.5" />
        </button>
      </div>

      {!sessionHealthy && sessionIssues.length > 0 && (
        <div className="flex h-8 shrink-0 items-center gap-2 border-b border-destructive/20 bg-destructive/8 px-2 text-[11px] text-destructive">
          <span className="relative flex size-4 shrink-0 items-center justify-center rounded-full bg-destructive/10">
            <span className="size-1.5 rounded-full bg-destructive" />
          </span>
          <span className="min-w-0 flex-1 truncate">
            {bp.sessionNeedsAttention(sessionIssues.join(" · "))}
          </span>
          <button
            type="button"
            onClick={() => void handleLaunch()}
            className="h-5 shrink-0 rounded border border-destructive/25 px-1.5 text-[10px] font-medium transition-colors hover:bg-destructive/10"
          >
            {bp.reconnectButton}
          </button>
        </div>
      )}

      {semanticOpen && semanticSnapshot && (
        <div className="shrink-0 border-b border-border/45 bg-background/90 px-2 py-2">
          <div className="mb-1 flex items-center gap-2">
            <FileTextIcon className="size-3.5 text-primary" />
            <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-foreground">
              {semanticSnapshot.name ||
                semanticSnapshot.url ||
                bp.semanticSnapshotFallback}
            </span>
            {semanticSnapshot.truncated && (
              <span className="rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-600">
                {bp.truncatedBadge}
              </span>
            )}
            <button
              type="button"
              onClick={() => setSemanticOpen(false)}
              className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title={bp.closeSemanticSnapshot}
            >
              <XIcon className="size-3" />
            </button>
          </div>
          <pre className="max-h-28 overflow-auto whitespace-pre-wrap rounded-md bg-muted/45 p-2 text-[10px] leading-relaxed text-muted-foreground">
            {(semanticSnapshot.text || bp.noReadableText).slice(0, 3000)}
          </pre>
        </div>
      )}

      {/* Screenshot area */}
      <div className="relative flex-1 overflow-auto bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.08),transparent_34%),linear-gradient(180deg,hsl(var(--muted)/0.34),hsl(var(--background)))] [&::-webkit-scrollbar]:size-2 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border/80 [&::-webkit-scrollbar-track]:bg-transparent">
        {effectiveSurfaceMode === "live" ? (
          <div className="flex min-h-full items-center justify-center p-3">
            <div
              className={cn(
                "relative overflow-hidden bg-background ring-1 ring-black/5 shadow-[0_18px_48px_rgba(15,23,42,0.18)]",
                devicePreview === "desktop"
                  ? "w-full rounded-lg border border-border/55"
                  : "border-[5px] border-foreground/80",
                deviceFrameKind === "tablet" &&
                  "max-h-full rounded-[24px] shadow-[0_22px_64px_rgba(15,23,42,0.24)]",
                deviceFrameKind === "phone" &&
                  "max-h-full rounded-[28px] shadow-[0_24px_70px_rgba(15,23,42,0.28)]",
              )}
              style={{
                aspectRatio:
                  devicePreview === "desktop"
                    ? undefined
                    : `${activeDevicePreview.width} / ${activeDevicePreview.height}`,
                maxWidth:
                  devicePreview === "desktop"
                    ? undefined
                    : deviceFrameKind === "tablet"
                      ? 420
                      : 240,
                width: devicePreview === "desktop" ? "100%" : "70%",
                minHeight: devicePreview === "desktop" ? "100%" : undefined,
              }}
            >
              {!electronLiveSurface && !liveFrameLoaded && (
                <div className="absolute inset-0 z-10 grid place-items-center bg-background/70">
                  <div className="flex items-center gap-2 rounded-full border bg-background/90 px-3 py-1.5 text-[11px] text-muted-foreground shadow-sm">
                    <Loader2Icon className="size-3.5 animate-spin text-primary" />
                    {bp.loadingLivePage}
                  </div>
                </div>
              )}
              {electronLiveSurface ? (
                <WebviewTab
                  key={liveTab.id}
                  tab={liveTab}
                  active
                  onPatch={(patch) =>
                    setLiveTab((prev) => ({ ...prev, ...patch }))
                  }
                  ref={liveWebviewRef}
                />
              ) : (
                <iframe
                  key={`${livePreviewUrl}-${currentViewportLabel}`}
                  src={livePreviewUrl}
                  title={
                    pageInfo.title || livePreviewUrl || "Live browser preview"
                  }
                  className="size-full border-0 bg-background"
                  onLoad={() => setLiveFrameLoaded(true)}
                  allow="clipboard-read; clipboard-write; fullscreen"
                  referrerPolicy="no-referrer-when-downgrade"
                />
              )}
            </div>
          </div>
        ) : screenshot ? (
          <div className="flex min-h-full items-center justify-center p-3">
            <div
              className={cn(
                "relative overflow-hidden bg-background ring-1 ring-black/5 shadow-[0_18px_48px_rgba(15,23,42,0.18)]",
                devicePreview === "desktop"
                  ? "w-full rounded-lg border border-border/55"
                  : "border-[5px] border-foreground/80",
                deviceFrameKind === "tablet" &&
                  "max-h-full rounded-[24px] shadow-[0_22px_64px_rgba(15,23,42,0.24)]",
                deviceFrameKind === "phone" &&
                  "max-h-full rounded-[28px] shadow-[0_24px_70px_rgba(15,23,42,0.28)]",
              )}
              style={{
                aspectRatio:
                  devicePreview === "desktop"
                    ? undefined
                    : `${activeDevicePreview.width} / ${activeDevicePreview.height}`,
                maxWidth:
                  devicePreview === "desktop"
                    ? undefined
                    : deviceFrameKind === "tablet"
                      ? 420
                      : 240,
                width: devicePreview === "desktop" ? "100%" : "70%",
              }}
            >
              <img
                src={`data:image/png;base64,${screenshot}`}
                alt={t.browser.browserAutomation}
                className={cn(
                  "size-full",
                  devicePreview === "desktop"
                    ? "object-contain"
                    : "object-cover object-left-top",
                )}
                onClick={(event) => void handleScreenshotPointer(event)}
                onError={() => setScreenshot("")}
                onMouseMove={handleScreenshotHover}
                onMouseLeave={() => setHoverPoint(null)}
                title={bp.screenshotClickTitle(
                  pointerMode === "double" ? bp.doubleClickMode : bp.clickMode,
                  currentViewportLabel,
                )}
                style={{ cursor: "crosshair" }}
              />
              {hoverPoint && screenshotSize.width > 0 && (
                <div className="pointer-events-none absolute bottom-2 left-2 z-30 rounded-full border border-border/55 bg-background/88 px-2 py-1 font-mono text-[10px] text-muted-foreground shadow-sm backdrop-blur">
                  x {hoverPoint.x} · y {hoverPoint.y}
                </div>
              )}
              {clickMarker && screenshotSize.width > 0 && (
                <div
                  className="pointer-events-none absolute z-30 grid size-9 -translate-x-1/2 -translate-y-1/2 place-items-center"
                  style={{
                    left: `${(clickMarker.x / screenshotSize.width) * 100}%`,
                    top: `${(clickMarker.y / screenshotSize.height) * 100}%`,
                  }}
                >
                  <span className="absolute size-9 rounded-full border border-primary/40 bg-primary/10 animate-ping" />
                  <span className="grid size-5 place-items-center rounded-full border border-primary/55 bg-background/90 text-[8px] font-bold text-primary shadow-sm">
                    {clickMarker.mode === "double" ? "2x" : "1x"}
                  </span>
                </div>
              )}
            </div>
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center p-5">
            {/* 本地服务快速入口 */}
            {detectedServices.length > 0 ? (
              <div className="w-full max-w-sm space-y-3 rounded-2xl border border-border/55 bg-background/82 p-3 shadow-sm backdrop-blur">
                <div className="flex items-center gap-2">
                  <div className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary">
                    <ServerIcon className="size-3.5" />
                  </div>
                  <span className="text-[11px] font-semibold text-foreground">
                    {bp.localServices}
                  </span>
                  <button
                    onClick={handleRescanPorts}
                    disabled={scanningPorts}
                    className="ml-auto flex h-6 items-center gap-1 rounded-md border border-border/50 px-1.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
                  >
                    {scanningPorts ? (
                      <Loader2Icon className="size-3 animate-spin" />
                    ) : (
                      <RefreshCwIcon className="size-3" />
                    )}
                    {bp.scanButton}
                  </button>
                </div>
                <div className="space-y-1.5">
                  {detectedServices.map((svc) => (
                    <button
                      key={svc.port}
                      onClick={() => handleQuickNavigate(svc.url)}
                      className="group flex w-full items-center gap-3 rounded-lg border border-border/55 bg-muted/25 px-3 py-2 text-left shadow-sm transition-colors hover:border-primary/25 hover:bg-primary/5"
                    >
                      <div
                        className={cn(
                          "flex size-8 shrink-0 items-center justify-center rounded-md text-xs font-bold transition-transform group-hover:scale-[1.03]",
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
                        {svc.type === "frontend"
                          ? bp.serviceTypeFrontend
                          : svc.type === "backend"
                            ? bp.serviceTypeBackend
                            : bp.serviceTypeOther}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="max-w-sm rounded-2xl border border-border/55 bg-background/82 p-5 text-center shadow-sm backdrop-blur">
                <div className="mx-auto grid size-10 place-items-center rounded-xl bg-muted/60">
                  <ImageIcon className="size-5 text-muted-foreground/45" />
                </div>
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  {t.browser.navigateHint}
                </p>
                <button
                  onClick={handleRescanPorts}
                  disabled={scanningPorts}
                  className="mx-auto mt-3 flex h-8 items-center gap-1.5 rounded-md border border-border/55 px-3 text-[11px] text-muted-foreground shadow-sm transition-colors hover:bg-muted/50 hover:text-foreground disabled:opacity-50"
                >
                  {scanningPorts ? (
                    <Loader2Icon className="size-3 animate-spin" />
                  ) : (
                    <RefreshCwIcon className="size-3" />
                  )}
                  {bp.scanLocalServices}
                </button>
              </div>
            )}
          </div>
        )}
        {(loading || viewportChanging) && (
          <div className="absolute inset-0 flex items-center justify-center bg-background/60">
            <Loader2Icon className="text-primary size-6 animate-spin" />
          </div>
        )}
        {screenshotSize.width > 0 && (
          <span className="text-muted-foreground/50 absolute right-1 bottom-1 text-[9px]">
            {screenshotSize.width}x{screenshotSize.height} · {pointerMode}
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
            {actionFailureCount > 0
              ? ` · ${bp.failureCount(actionFailureCount)}`
              : ""}
            {actionCoordinateCount > 0
              ? ` · ${bp.coordinateCount(actionCoordinateCount)}`
              : ""}
          </span>
        </button>
        {selectedAction && (
          <div className="border-t border-border/35 bg-primary/5 px-2 py-1.5 text-[10px]">
            <div className="flex min-w-0 items-center gap-1.5">
              <ActionIcon action={selectedAction.entry.action} />
              <span className="shrink-0 font-semibold text-foreground/85">
                {bp.selectedAction(selectedAction.entry.action)}
              </span>
              <span
                className={cn(
                  "shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium",
                  actionStatusClass(selectedAction.entry),
                )}
              >
                {actionStatusLabel(selectedAction.entry, bp)}
              </span>
              {actionCoordinateLabel(selectedAction.entry) && (
                <button
                  type="button"
                  onClick={() =>
                    focusActionEntry(selectedAction.entry, selectedAction.index)
                  }
                  className="shrink-0 rounded-full border border-primary/25 bg-background/80 px-1.5 py-0.5 font-mono text-[9px] text-primary transition-colors hover:bg-primary/10"
                  title={bp.locateActionTitle}
                >
                  {actionCoordinateLabel(selectedAction.entry)}
                </button>
              )}
              <button
                type="button"
                onClick={() => setSelectedActionKey(null)}
                className="ml-auto grid size-5 shrink-0 place-items-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                title={bp.deselectTitle}
              >
                <XIcon className="size-3" />
              </button>
            </div>
            <div className="mt-1 truncate text-muted-foreground">
              {actionDetailLabel(selectedAction.entry, bp)}
            </div>
          </div>
        )}
        {actionLogExpanded && (
          <div className="max-h-52 overflow-auto px-2 pb-2 [&::-webkit-scrollbar]:size-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-border/80 [&::-webkit-scrollbar-track]:bg-transparent">
            {actionLog.length === 0 ? (
              <p className="text-muted-foreground/50 py-2 text-center text-[10px]">
                {t.browser.noActions}
              </p>
            ) : (
              <div className="space-y-1">
                {visibleActions.map((entry, i) => {
                  const absoluteIndex = visibleActionStartIndex + i;
                  const entryKey = actionEntryKey(entry, absoluteIndex);
                  const coordinateLabel = actionCoordinateLabel(entry);
                  const failed = Boolean(entry.status && entry.status !== "ok");
                  return (
                    <button
                      key={entryKey}
                      type="button"
                      onClick={() => focusActionEntry(entry, absoluteIndex)}
                      className={cn(
                        "group flex w-full items-start gap-2 rounded-lg border border-border/45 bg-muted/22 px-2 py-1.5 text-left text-[10px] transition-colors hover:bg-muted/38",
                        failed && "border-destructive/25 bg-destructive/8",
                        selectedActionKey === entryKey &&
                          "border-primary/35 bg-primary/10",
                      )}
                    >
                      <div className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md bg-background/75">
                        <ActionIcon action={entry.action} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-1.5">
                          <span className="truncate font-semibold text-foreground/85">
                            {entry.action}
                          </span>
                          <span
                            className={cn(
                              "shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-medium",
                              actionStatusClass(entry),
                            )}
                          >
                            {actionStatusLabel(entry, bp)}
                          </span>
                          {coordinateLabel && (
                            <span className="shrink-0 rounded-full bg-background/75 px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground">
                              {coordinateLabel}
                            </span>
                          )}
                          <span className="ml-auto shrink-0 font-mono text-[9px] text-muted-foreground/50">
                            {new Date(
                              entry.timestamp * 1000,
                            ).toLocaleTimeString([], {
                              hour: "2-digit",
                              minute: "2-digit",
                              second: "2-digit",
                            })}
                          </span>
                        </div>
                        <div
                          className={cn(
                            "mt-0.5 truncate text-muted-foreground",
                            failed && "text-destructive/85",
                          )}
                        >
                          {actionDetailLabel(entry, bp)}
                        </div>
                      </div>
                    </button>
                  );
                })}
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
