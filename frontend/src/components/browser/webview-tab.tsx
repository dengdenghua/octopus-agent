/* Implementation note. */

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
} from "react";
import {
  BookOpenIcon,
  BotIcon,
  BrainCircuitIcon,
  CalendarDaysIcon,
  CirclePlusIcon,
  Clock3Icon,
  CopyIcon,
  FileTextIcon,
  Gamepad2Icon,
  GraduationCapIcon,
  HomeIcon,
  ImageIcon,
  LayoutGridIcon,
  MessageCircleIcon,
  PaletteIcon,
  PanelLeftIcon,
  PlugIcon,
  SearchIcon,
  SettingsIcon,
  SparklesIcon,
  VideoIcon,
  type LucideIcon,
} from "lucide-react";

import { swallow } from "@/core/utils/log";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { copyTextToClipboard } from "@/core/clipboard";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { BROWSER_HOME_URL, type BrowserTab } from "./browser-store";
import { BrowserHome } from "./browser-home";

interface Props {
  tab: BrowserTab;
  active: boolean;
  onPatch: (patch: Partial<BrowserTab>) => void;
}

/* Implementation note. */
interface CrashInfo {
  reason: string;
  exitCode: number;
}

type WebviewElement = HTMLElement & {
  src: string;
  getWebContentsId: () => number;
  reload: () => void;
  goBack: () => void;
  goForward: () => void;
  canGoBack: () => boolean;
  canGoForward: () => boolean;
  getTitle: () => string;
  isLoading: () => boolean;
  loadURL: (url: string) => Promise<void>;
};

export interface WebviewTabHandle {
  reload: () => void;
  goBack: () => void;
  goForward: () => void;
  loadURL: (url: string) => void;
  canGoBack: () => boolean;
  canGoForward: () => boolean;
  executeJS: (code: string) => Promise<unknown>;
  getWebContentsId: () => number | null;
  extractText: () => Promise<{
    url: string;
    title: string;
    text: string;
    truncated?: boolean;
    textLength?: number;
    pageAgent?: unknown;
  }>;
  capturePage: () => Promise<{
    dataUrl: string;
    width: number;
    height: number;
  }>;
  runAction: (
    action: string,
    params?: Record<string, unknown>,
  ) => Promise<Record<string, unknown>>;
}

interface BrowserRelayStatus {
  connected: boolean;
  extension_version?: string;
  active_tab?: {
    id?: number | string;
    url?: string;
    title?: string;
  } | null;
  manifest_exists?: boolean;
  pending_commands?: number;
}

interface BrowserDesktopApp {
  name: string;
  url: string;
  icon: LucideIcon;
  color: string;
  description: string;
}

interface BrowserDesktopWidget {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  color: string;
}

type DesktopPanelId =
  | "home"
  | "theme"
  | "widgets"
  | "wallpaper"
  | "games"
  | "add"
  | "settings";

const AI_DESKTOP_APPS: BrowserDesktopApp[] = [
  {
    name: "Gemini",
    url: "https://gemini.google.com/app",
    icon: SparklesIcon,
    color: "from-blue-500 to-cyan-400",
    description: "综合搜索、多轮分析",
  },
  {
    name: "NotebookLM",
    url: "https://notebooklm.google.com/",
    icon: BookOpenIcon,
    color: "from-amber-500 to-orange-400",
    description: "资料库、引用、文档研究",
  },
  {
    name: "豆包",
    url: "https://www.doubao.com/chat/",
    icon: MessageCircleIcon,
    color: "from-emerald-500 to-teal-400",
    description: "中文调研、中文改写",
  },
  {
    name: "Perplexity",
    url: "https://www.perplexity.ai/",
    icon: SearchIcon,
    color: "from-sky-500 to-indigo-500",
    description: "网页检索、来源线索",
  },
  {
    name: "ChatGPT",
    url: "https://chatgpt.com/",
    icon: BotIcon,
    color: "from-zinc-700 to-zinc-500",
    description: "通用对话、代码辅助",
  },
  {
    name: "Claude",
    url: "https://claude.ai/",
    icon: BrainCircuitIcon,
    color: "from-stone-600 to-rose-400",
    description: "长文分析、写作整理",
  },
  {
    name: "Kimi",
    url: "https://www.kimi.com/",
    icon: GraduationCapIcon,
    color: "from-violet-500 to-fuchsia-500",
    description: "长上下文、中文资料",
  },
];

const DESKTOP_WIDGETS: BrowserDesktopWidget[] = [
  {
    title: "调研记录",
    subtitle: "REC 模式会把外部 AI 结果沉淀为简报",
    icon: FileTextIcon,
    color: "from-slate-700 to-slate-500",
  },
  {
    title: "今日任务",
    subtitle: "打开平台、收集结论、核查来源",
    icon: LayoutGridIcon,
    color: "from-indigo-500 to-blue-400",
  },
];

const DESKTOP_APP_ORDER_KEY = "octopus:browser-desktop-app-order";

const DESKTOP_SIDE_NAV: Array<{
  id: DesktopPanelId;
  label: string;
  icon: LucideIcon;
}> = [
  { id: "home", label: "桌面", icon: HomeIcon },
  { id: "theme", label: "主题", icon: PaletteIcon },
  { id: "widgets", label: "小组件", icon: PanelLeftIcon },
  { id: "wallpaper", label: "壁纸", icon: ImageIcon },
  { id: "games", label: "娱乐", icon: Gamepad2Icon },
];

function labelFromMap(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}

function loadDesktopAppOrder(): string[] {
  if (typeof window === "undefined")
    return AI_DESKTOP_APPS.map((app) => app.url);
  try {
    const parsed = JSON.parse(
      localStorage.getItem(DESKTOP_APP_ORDER_KEY) || "[]",
    );
    if (!Array.isArray(parsed)) return AI_DESKTOP_APPS.map((app) => app.url);
    const known = new Set(AI_DESKTOP_APPS.map((app) => app.url));
    const saved = parsed.filter(
      (item): item is string => typeof item === "string" && known.has(item),
    );
    const missing = AI_DESKTOP_APPS.map((app) => app.url).filter(
      (url) => !saved.includes(url),
    );
    return [...saved, ...missing];
  } catch (e) {
    swallow(e);
    return AI_DESKTOP_APPS.map((app) => app.url);
  }
}

function orderDesktopApps(order: string[]): BrowserDesktopApp[] {
  const byUrl = new Map(AI_DESKTOP_APPS.map((app) => [app.url, app]));
  return order
    .map((url) => byUrl.get(url))
    .filter((app): app is BrowserDesktopApp => Boolean(app));
}

function moveDesktopApp(
  order: string[],
  fromUrl: string,
  toUrl: string,
): string[] {
  if (fromUrl === toUrl) return order;
  const next = order.filter((url) => url !== fromUrl);
  const targetIndex = next.indexOf(toUrl);
  if (targetIndex < 0) return order;
  next.splice(targetIndex, 0, fromUrl);
  return next;
}

async function browserJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBackendBaseURL()}${path}`, init);
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

function BackendBrowserTab({
  tab,
  active,
  onPatch,
  imperativeRef,
}: Props & {
  imperativeRef: React.ForwardedRef<WebviewTabHandle>;
}) {
  const sessionId = `browser-page:${tab.id}`;
  const { t } = useI18n();
  const wt = t.browser.webviewTab;
  const [screenshot, setScreenshot] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [extensionHint, setExtensionHint] = useState("");
  const [extensionPath, setExtensionPath] = useState("");
  const [extensionGuideOpen, setExtensionGuideOpen] = useState(false);
  const [relayStatus, setRelayStatus] = useState<BrowserRelayStatus | null>(
    null,
  );
  const bookmarkletHref = `javascript:(()=>{const s=document.createElement("script");s.src=${JSON.stringify(
    `${getBackendBaseURL()}/api/browser/relay/bookmarklet.js?app=`,
  )}+encodeURIComponent(location.origin)+"&t="+Date.now();document.documentElement.appendChild(s);})()`;

  const refreshRelayStatus = async () => {
    const status = await browserJson<BrowserRelayStatus>(
      "/api/browser/relay/status",
      {
        headers: authHeaders(),
      },
    );
    setRelayStatus(status);
    return status;
  };

  const openExtensionFolder = async () => {
    try {
      const data = await browserJson<{ opened: boolean; path: string }>(
        "/api/browser/open-extension-folder",
        { method: "POST", headers: jsonAuthHeaders() },
      );
      setExtensionPath(data.path);
      setExtensionHint(wt.pluginDirectoryOpened(data.path));
      setExtensionGuideOpen(true);
    } catch (e) {
      swallow(e);
      setExtensionHint(e instanceof Error ? e.message : String(e));
    }
  };

  const copyExtensionPath = async () => {
    if (!extensionPath) {
      await openExtensionFolder();
      return;
    }
    try {
      await copyTextToClipboard(extensionPath);
      setExtensionHint(wt.pluginPathCopied);
    } catch (e) {
      swallow(e);
      setExtensionHint(extensionPath);
    }
  };

  const copyBookmarklet = async () => {
    try {
      await copyTextToClipboard(bookmarkletHref);
      setExtensionHint(wt.bookmarkletCopied);
    } catch (e) {
      swallow(e);
      setExtensionHint(bookmarkletHref);
    }
  };

  const relayCommand = async (
    action: string,
    params: Record<string, unknown> = {},
  ) =>
    browserJson<Record<string, unknown>>("/api/browser/relay/command", {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ action, timeout_seconds: 12, ...params }),
    });

  const preferRelay = async () => {
    const status = relayStatus?.connected
      ? relayStatus
      : await refreshRelayStatus();
    return Boolean(status.connected);
  };

  const refreshScreenshot = async () => {
    if (await preferRelay()) {
      const shot = await relayCommand("screenshot");
      if (typeof shot.dataUrl === "string") {
        setScreenshot(shot.dataUrl);
        return;
      }
    }
    const shot = await browserJson<{
      base64: string;
      width: number;
      height: number;
    }>(
      `/api/browser/screenshot/base64?session_id=${encodeURIComponent(sessionId)}`,
      { headers: authHeaders() },
    );
    setScreenshot(`data:image/png;base64,${shot.base64}`);
  };

  const launch = async () => {
    await browserJson<{ status: string }>("/api/browser/launch", {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ session_id: sessionId, headless: false }),
    });
  };

  const navigate = async (url: string) => {
    setLoading(true);
    setError(null);
    onPatch({ isLoading: true });
    try {
      if (await preferRelay()) {
        const info = await relayCommand("navigate", { url });
        const nextUrl = typeof info.url === "string" ? info.url : url;
        const nextTitle = typeof info.title === "string" ? info.title : nextUrl;
        onPatch({ url: nextUrl, title: nextTitle, isLoading: false });
        await refreshScreenshot();
        return;
      }
      await launch();
      const info = await browserJson<{ url: string; title: string }>(
        "/api/browser/navigate",
        {
          method: "POST",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({ session_id: sessionId, url }),
        },
      );
      onPatch({ url: info.url, title: info.title, isLoading: false });
      await refreshScreenshot();
    } catch (e) {
      swallow(e);
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      onPatch({ isLoading: false });
    } finally {
      setLoading(false);
    }
  };

  const runAction = async (
    action: string,
    params: Record<string, unknown> = {},
  ) => {
    if (await preferRelay()) {
      const data = await relayCommand(action, params);
      const nextUrl = typeof data.url === "string" ? data.url : undefined;
      const nextTitle = typeof data.title === "string" ? data.title : undefined;
      if (nextUrl || nextTitle) {
        onPatch({
          ...(nextUrl ? { url: nextUrl } : {}),
          ...(nextTitle ? { title: nextTitle } : {}),
        });
      }
      await refreshScreenshot().catch((e) => {
        swallow(e);
      });
      return data;
    }
    await launch();
    const data = await browserJson<Record<string, unknown>>(
      "/api/browser/action",
      {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ session_id: sessionId, action, ...params }),
      },
    );
    const nextUrl = typeof data.url === "string" ? data.url : undefined;
    const nextTitle = typeof data.title === "string" ? data.title : undefined;
    if (nextUrl || nextTitle) {
      onPatch({
        ...(nextUrl ? { url: nextUrl } : {}),
        ...(nextTitle ? { title: nextTitle } : {}),
      });
    }
    await refreshScreenshot().catch((e) => {
      swallow(e);
    });
    return data;
  };

  useImperativeHandle(
    imperativeRef,
    () => ({
      reload: () => void runAction("reload"),
      goBack: () => void runAction("back"),
      goForward: () => void runAction("forward"),
      loadURL: (url) => void navigate(url),
      canGoBack: () => true,
      canGoForward: () => true,
      executeJS: async () => undefined,
      getWebContentsId: () => null,
      extractText: async () => {
        if (await preferRelay()) {
          const data = await relayCommand("extract");
          return {
            url: typeof data.url === "string" ? data.url : "",
            title: typeof data.title === "string" ? data.title : "",
            text: typeof data.text === "string" ? data.text : "",
            truncated: Boolean(data.truncated),
            textLength:
              typeof data.textLength === "number" ? data.textLength : undefined,
            pageAgent: data.pageAgent,
          };
        }
        await launch();
        return browserJson<{
          url: string;
          title: string;
          text: string;
          truncated?: boolean;
          textLength?: number;
        }>(
          `/api/browser/extract-text?session_id=${encodeURIComponent(sessionId)}`,
          { headers: authHeaders() },
        );
      },
      capturePage: async () => {
        if (await preferRelay()) {
          const shot = await relayCommand("screenshot");
          const dataUrl = typeof shot.dataUrl === "string" ? shot.dataUrl : "";
          if (dataUrl) {
            setScreenshot(dataUrl);
            return { dataUrl, width: 0, height: 0 };
          }
        }
        await launch();
        const shot = await browserJson<{
          base64: string;
          width: number;
          height: number;
        }>(
          `/api/browser/screenshot/base64?session_id=${encodeURIComponent(sessionId)}`,
          { headers: authHeaders() },
        );
        const dataUrl = `data:image/png;base64,${shot.base64}`;
        setScreenshot(dataUrl);
        return { dataUrl, width: shot.width, height: shot.height };
      },
      runAction,
    }),
    [sessionId, tab.url, relayStatus?.connected],
  );

  useEffect(() => {
    if (!active) return;
    void navigate(tab.url);
    // The tab URL is the source of truth; URL-bar navigation updates it.
  }, [active, tab.id]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const status = await browserJson<BrowserRelayStatus>(
          "/api/browser/relay/status",
          {
            headers: authHeaders(),
          },
        );
        if (!cancelled) setRelayStatus(status);
      } catch (e) {
        swallow(e);
        if (!cancelled) setRelayStatus(null);
      }
    };
    void tick();
    const timer = window.setInterval(() => void tick(), 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [active]);

  return (
    <div
      style={
        active
          ? { display: "flex", width: "100%", height: "100%" }
          : {
              display: "flex",
              position: "absolute",
              width: 0,
              height: 0,
              visibility: "hidden",
              pointerEvents: "none",
            }
      }
      className="relative flex-col overflow-auto bg-muted/20"
    >
      <div className="absolute right-3 top-3 z-10 flex items-center gap-1.5 rounded-full border bg-background/90 p-1 text-[11px] shadow-sm backdrop-blur">
        <button
          type="button"
          onClick={() => setExtensionGuideOpen((v) => !v)}
          className={cn(
            "flex h-7 items-center gap-1.5 rounded-full px-2.5 font-medium transition-colors",
            relayStatus?.connected
              ? "bg-emerald-500/10 text-emerald-700"
              : "text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
        >
          <PlugIcon className="size-3.5" />
          {wt.extPluginButton}
        </button>
        <button
          type="button"
          className="h-7 rounded-full bg-primary px-2.5 font-medium text-primary-foreground hover:bg-primary/90"
          onClick={openExtensionFolder}
        >
          {wt.openDirectory}
        </button>
        {extensionGuideOpen && (
          <div className="absolute right-0 top-full mt-2 w-[360px] rounded-2xl border bg-background/98 p-4 text-left shadow-xl backdrop-blur">
            <div className="flex items-start gap-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary">
                <PlugIcon className="size-5" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold text-foreground">
                  {wt.extPluginTitle}
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  {wt.extPluginDesc}
                </div>
              </div>
            </div>
            <div className="mt-3 rounded-2xl border bg-primary/5 p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold text-foreground">
                    {wt.dragToBookmarks}
                  </div>
                  <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                    {wt.dragToBookmarksDesc}
                  </div>
                </div>
                <a
                  href={bookmarkletHref}
                  draggable
                  onClick={(event) => event.preventDefault()}
                  className="shrink-0 rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
                  title={wt.dragToBookmarksTitle}
                >
                  Octopus Agent
                </a>
              </div>
            </div>
            <div className="mt-3 grid gap-2 text-xs">
              <div className="rounded-xl bg-muted/55 px-3 py-2">
                {wt.step1Temporary}
              </div>
              <div className="rounded-xl bg-muted/55 px-3 py-2">
                {wt.step2LongTerm}
              </div>
              <div className="rounded-xl bg-muted/55 px-3 py-2">
                {wt.step3LoadExtension}
              </div>
            </div>
            {extensionPath && (
              <div className="mt-3 rounded-xl border bg-muted/25 px-3 py-2">
                <div className="text-[11px] text-muted-foreground">
                  {wt.pluginDirectory}
                </div>
                <div className="mt-1 break-all font-mono text-[11px] text-foreground">
                  {extensionPath}
                </div>
              </div>
            )}
            <div className="mt-3 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={copyBookmarklet}
                className="flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <CopyIcon className="size-3.5" />
                {wt.copyBookmarklet}
              </button>
              <button
                type="button"
                onClick={copyExtensionPath}
                className="h-8 rounded-full border px-3 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                {wt.copyPath}
              </button>
              <button
                type="button"
                onClick={openExtensionFolder}
                className="h-8 rounded-full bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90"
              >
                {wt.openPluginDirectory}
              </button>
            </div>
          </div>
        )}
      </div>
      {screenshot ? (
        <img
          src={screenshot}
          alt={tab.title || tab.url}
          className="w-full object-contain"
          onClick={() => void refreshScreenshot()}
        />
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
          <div className="text-sm font-medium">{wt.connectingPlugin}</div>
          <div className="max-w-sm text-xs leading-relaxed text-muted-foreground">
            {wt.connectingPluginDesc}
          </div>
        </div>
      )}
      {loading && (
        <div className="absolute inset-0 grid place-items-center bg-background/60 text-xs text-muted-foreground">
          Loading...
        </div>
      )}
      {error && (
        <div className="absolute left-3 right-3 top-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      {extensionHint && (
        <div className="absolute bottom-3 left-3 right-3 rounded-md border bg-background/95 px-3 py-2 text-xs text-muted-foreground shadow-sm">
          {extensionHint}
        </div>
      )}
    </div>
  );
}

function BrowserDesktopHome({
  active,
  device,
  onOpen,
}: {
  active: boolean;
  device: BrowserTab["device"];
  onOpen: (url: string) => void;
}) {
  const [query, setQuery] = useState("");
  const { t } = useI18n();
  const wt = t.browser.webviewTab;
  const [activePanel, setActivePanel] = useState<DesktopPanelId>("home");
  const [editMode, setEditMode] = useState(false);
  const [appOrder, setAppOrder] = useState<string[]>(() =>
    loadDesktopAppOrder(),
  );
  const [draggingUrl, setDraggingUrl] = useState<string | null>(null);
  const orderedApps = orderDesktopApps(appOrder);
  const compactDesktop = device !== "desktop";
  const tabletDesktop = device === "tablet";
  const mobileDesktop = device === "mobile";
  const today = new Date();
  const day = today.getDate().toString().padStart(2, "0");
  const month = wt.monthFormat(today.getFullYear(), today.getMonth() + 1);
  const week = wt.weekdays[today.getDay()];

  const appNameMap = useMemo<Record<string, string>>(
    () => ({
      "Cocoloop 社区": wt.appNameCocoloopCommunity,
      "Cocoloop 市场": wt.appNameCocoloopMarket,
    }),
    [wt.appNameCocoloopCommunity, wt.appNameCocoloopMarket],
  );

  const appDescMap = useMemo<Record<string, string>>(
    () => ({
      "Cocoloop 社区": wt.appDescCocoloopCommunity,
      "Cocoloop 市场": wt.appDescCocoloopMarket,
      Gemini: wt.appDescGemini,
      NotebookLM: wt.appDescNotebookLM,
      豆包: wt.appDescDoubao,
      Perplexity: wt.appDescPerplexity,
      ChatGPT: wt.appDescChatGPT,
      Claude: wt.appDescClaude,
      Kimi: wt.appDescKimi,
    }),
    [
      wt.appDescCocoloopCommunity,
      wt.appDescCocoloopMarket,
      wt.appDescGemini,
      wt.appDescNotebookLM,
      wt.appDescDoubao,
      wt.appDescPerplexity,
      wt.appDescChatGPT,
      wt.appDescClaude,
      wt.appDescKimi,
    ],
  );

  const widgetTitleMap = useMemo<Record<string, string>>(
    () => ({
      调研记录: wt.widgetTitleResearch,
      今日任务: wt.widgetTitleTodayTasks,
    }),
    [wt.widgetTitleResearch, wt.widgetTitleTodayTasks],
  );

  const widgetSubtitleMap = useMemo<Record<string, string>>(
    () => ({
      调研记录: wt.widgetSubtitleResearch,
      今日任务: wt.widgetSubtitleTodayTasks,
    }),
    [wt.widgetSubtitleResearch, wt.widgetSubtitleTodayTasks],
  );

  const navLabelMap = useMemo<Record<string, string>>(
    () => ({
      桌面: wt.navHome,
      主题: wt.navTheme,
      小组件: wt.navWidgets,
      壁纸: wt.navWallpaper,
      娱乐: wt.navGames,
    }),
    [wt.navHome, wt.navTheme, wt.navWidgets, wt.navWallpaper, wt.navGames],
  );

  const submitSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    const target = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(trimmed)
      ? trimmed
      : /\s/.test(trimmed) || !trimmed.includes(".")
        ? `https://www.baidu.com/s?wd=${encodeURIComponent(trimmed)}`
        : `https://${trimmed}`;
    onOpen(target);
  };

  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") submitSearch();
  };

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem(DESKTOP_APP_ORDER_KEY, JSON.stringify(appOrder));
  }, [appOrder]);

  const startAppDrag = (event: DragEvent<HTMLElement>, url: string) => {
    if (!editMode) return;
    setDraggingUrl(url);
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", url);
  };

  const dropApp = (event: DragEvent<HTMLElement>, targetUrl: string) => {
    if (!editMode) return;
    event.preventDefault();
    const sourceUrl = draggingUrl || event.dataTransfer.getData("text/plain");
    if (!sourceUrl) return;
    setAppOrder((prev) => moveDesktopApp(prev, sourceUrl, targetUrl));
    setDraggingUrl(null);
  };

  const resetDesktopLayout = () => {
    setAppOrder(AI_DESKTOP_APPS.map((app) => app.url));
    setDraggingUrl(null);
  };

  return (
    <div
      style={
        active
          ? { display: "flex", width: "100%", height: "100%" }
          : {
              display: "flex",
              position: "absolute",
              width: 0,
              height: 0,
              visibility: "hidden",
              pointerEvents: "none",
            }
      }
      className="relative min-h-0 flex-col overflow-hidden bg-[radial-gradient(circle_at_18%_16%,rgba(255,255,255,0.62),transparent_25%),radial-gradient(circle_at_80%_8%,rgba(128,145,165,0.34),transparent_28%),linear-gradient(145deg,#9fa8b2_0%,#b7a09b_54%,#c5a093_100%)] text-white"
    >
      <div
        className={cn(
          "absolute left-4 top-5 z-10 flex h-[calc(100%-2.5rem)] w-12 flex-col items-center rounded-[24px] bg-black/20 py-4 shadow-2xl shadow-black/10 backdrop-blur-md",
          compactDesktop && "left-3 top-4 h-[calc(100%-2rem)]",
          mobileDesktop && "left-2 w-11",
        )}
      >
        <div className="grid size-8 place-items-center rounded-2xl bg-white/70 text-slate-700 shadow-sm">
          <BotIcon className="size-5" />
        </div>
        <div className="mt-8 flex flex-col gap-4">
          {DESKTOP_SIDE_NAV.map((item) => {
            const Icon = item.icon;
            const selected = activePanel === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActivePanel(item.id)}
                className={cn(
                  "grid size-9 place-items-center rounded-2xl text-white/70 transition hover:bg-white/16 hover:text-white",
                  selected && "bg-white/16 text-white",
                )}
                title={labelFromMap(navLabelMap, item.label)}
              >
                <Icon className="size-5" />
              </button>
            );
          })}
        </div>
        <div className="mt-auto flex flex-col gap-4">
          <button
            type="button"
            onClick={() => setActivePanel("add")}
            className={cn(
              "grid size-9 place-items-center rounded-2xl bg-white/15 text-white transition hover:bg-white/25",
              activePanel === "add" && "bg-white/25",
            )}
            title={wt.addTitle}
          >
            <CirclePlusIcon className="size-5" />
          </button>
          <button
            type="button"
            onClick={() => setActivePanel("settings")}
            className={cn(
              "grid size-9 place-items-center rounded-2xl text-white/75 transition hover:bg-white/16 hover:text-white",
              activePanel === "settings" && "bg-white/16 text-white",
            )}
            title={wt.settingsTitle}
          >
            <SettingsIcon className="size-5" />
          </button>
        </div>
      </div>

      <div
        className={cn(
          "flex h-full min-h-0 flex-col pl-24 pr-12 pt-8",
          compactDesktop && "pl-20 pr-5 pt-6 pb-28",
          tabletDesktop && "pl-24 pr-8",
          mobileDesktop && "pl-16 pr-4 pt-5 pb-24",
        )}
      >
        <div
          className={cn(
            "mx-auto flex h-14 w-full max-w-[720px] items-center gap-3 rounded-[18px] bg-white/82 px-5 text-slate-600 shadow-xl shadow-black/10 backdrop-blur-xl",
            compactDesktop && "max-w-none",
            tabletDesktop && "max-w-[760px]",
            mobileDesktop && "h-12 rounded-2xl px-4",
          )}
        >
          <SearchIcon className="size-5 shrink-0 text-blue-600" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onSearchKey}
            placeholder={wt.searchPlaceholder}
            className="min-w-0 flex-1 bg-transparent text-lg font-medium text-slate-700 outline-none placeholder:text-slate-400"
          />
        </div>
        <div
          className={cn(
            "absolute right-12 top-8 flex items-center gap-2",
            compactDesktop && "right-6 top-7",
            tabletDesktop && "right-8",
            mobileDesktop && "right-5 top-6",
          )}
        >
          {editMode && (
            <button
              type="button"
              onClick={resetDesktopLayout}
              className="rounded-full bg-white/55 px-3 py-1.5 text-xs font-medium text-slate-700 shadow-lg shadow-black/10 backdrop-blur-xl transition hover:bg-white/75"
            >
              {wt.resetLayout}
            </button>
          )}
          <button
            type="button"
            onClick={() => setEditMode((value) => !value)}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium shadow-lg shadow-black/10 backdrop-blur-xl transition",
              editMode
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-white/55 text-slate-700 hover:bg-white/75",
            )}
          >
            {editMode ? wt.finishEditing : wt.editDesktop}
          </button>
        </div>
        {editMode && (
          <div
            className={cn(
              "absolute left-24 top-8 rounded-full bg-black/22 px-3 py-1.5 text-xs font-medium text-white shadow-lg backdrop-blur",
              compactDesktop && "left-20 top-24",
              tabletDesktop && "left-24",
              mobileDesktop && "left-16 right-4 text-center",
            )}
          >
            {wt.dragHint}
          </div>
        )}

        <div
          className={cn(
            "grid min-h-0 flex-1 grid-cols-[360px_minmax(360px,1fr)_220px] gap-12 py-14",
            compactDesktop &&
              "grid-cols-1 gap-8 overflow-y-auto pb-8 pt-8 pr-1",
            tabletDesktop &&
              "grid-cols-[300px_minmax(360px,1fr)] gap-8 pb-32 pr-2",
            mobileDesktop && "gap-6 pb-6 pt-6",
          )}
        >
          <div
            className={cn(
              "flex flex-col items-center gap-8",
              compactDesktop && "gap-6",
              tabletDesktop && "justify-start",
            )}
          >
            <div className="text-center">
              <div className="flex overflow-hidden rounded-[20px] bg-white/90 text-slate-700 shadow-lg shadow-black/10">
                <div
                  className={cn(
                    "grid w-24 place-items-center bg-white px-4 py-3 text-center",
                    mobileDesktop && "w-20 px-3 py-2",
                  )}
                >
                  <div
                    className={cn(
                      "text-4xl font-semibold text-rose-500",
                      mobileDesktop && "text-3xl",
                    )}
                  >
                    {day}
                  </div>
                  <div className="text-sm font-medium text-rose-500">
                    {week}
                  </div>
                </div>
                <div
                  className={cn(
                    "flex min-w-40 flex-col justify-center px-5 text-left",
                    mobileDesktop && "min-w-32 px-4",
                  )}
                >
                  <div
                    className={cn(
                      "text-lg font-semibold",
                      mobileDesktop && "text-base",
                    )}
                  >
                    {month}
                  </div>
                  <div className="text-sm text-slate-500">
                    {wt.aiBrowserDesktop}
                  </div>
                </div>
              </div>
              <div className="mt-3 text-sm font-medium text-white/88">
                {wt.calendarLabel}
              </div>
            </div>

            <div>
              <div
                className={cn(
                  "grid grid-cols-2 gap-4 rounded-[22px] bg-white/55 p-5 shadow-xl shadow-black/10 backdrop-blur-xl",
                  mobileDesktop && "gap-3 rounded-[20px] p-4",
                )}
              >
                {orderedApps.slice(0, 4).map((app) => (
                  <DesktopAppIcon
                    key={app.url}
                    app={app}
                    onOpen={onOpen}
                    compact
                    editMode={editMode}
                    dragging={draggingUrl === app.url}
                    onDragStart={startAppDrag}
                    onDrop={dropApp}
                    onDragEnd={() => setDraggingUrl(null)}
                    appNameMap={appNameMap}
                    appDescMap={appDescMap}
                  />
                ))}
              </div>
              <div className="mt-3 text-center text-sm font-medium text-white/88">
                {wt.aiToolFolder}
              </div>
            </div>
          </div>

          <div className={cn("flex flex-col gap-9", compactDesktop && "gap-7")}>
            <div>
              <div
                className={cn(
                  "grid h-56 grid-cols-[220px_1fr] overflow-hidden rounded-[22px] bg-black/36 shadow-2xl shadow-black/10 backdrop-blur-xl",
                  compactDesktop && "mx-auto h-auto max-w-[520px] grid-cols-1",
                  tabletDesktop && "h-52 max-w-none grid-cols-[190px_1fr]",
                  mobileDesktop && "max-w-[320px]",
                )}
              >
                <div
                  className={cn(
                    "m-4 rounded-[16px] bg-white/25 p-5",
                    compactDesktop && "mb-0",
                    tabletDesktop && "mb-4",
                  )}
                >
                  <div className="text-base font-medium text-white/90">
                    AI research
                  </div>
                  <div className="mt-5 flex items-end gap-2">
                    <span
                      className={cn(
                        "text-7xl font-semibold leading-none",
                        mobileDesktop && "text-5xl",
                      )}
                    >
                      15
                    </span>
                    <span className="pb-2 text-lg text-white/70">steps</span>
                  </div>
                  <div className="mt-4 text-sm text-white/65">
                    Start from desktop apps
                  </div>
                </div>
                <div
                  className={cn(
                    "space-y-5 p-6",
                    compactDesktop && "space-y-3 p-4",
                  )}
                >
                  {DESKTOP_WIDGETS.map((widget) => {
                    const Icon = widget.icon;
                    return (
                      <div
                        key={widget.title}
                        className="flex items-center gap-4 border-b border-white/20 pb-4 last:border-0"
                      >
                        <span
                          className={cn(
                            "grid size-10 place-items-center rounded-2xl bg-gradient-to-br",
                            widget.color,
                          )}
                        >
                          <Icon className="size-5 text-white" />
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-lg font-semibold">
                            {labelFromMap(widgetTitleMap, widget.title)}
                          </div>
                          <div className="truncate text-sm text-white/64">
                            {labelFromMap(widgetSubtitleMap, widget.subtitle)}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="mt-3 text-center text-sm font-medium text-white/88">
                {wt.researchWidgets}
              </div>
            </div>

            <div
              className={cn(
                "grid grid-cols-4 gap-8 self-center",
                compactDesktop && "grid-cols-3 gap-6",
                tabletDesktop && "grid-cols-4 gap-6",
                mobileDesktop && "grid-cols-2 gap-5",
              )}
            >
              {orderedApps.slice(2, 6).map((app) => (
                <DesktopAppIcon
                  key={app.url}
                  app={app}
                  onOpen={onOpen}
                  editMode={editMode}
                  dragging={draggingUrl === app.url}
                  onDragStart={startAppDrag}
                  onDrop={dropApp}
                  onDragEnd={() => setDraggingUrl(null)}
                  appNameMap={appNameMap}
                  appDescMap={appDescMap}
                />
              ))}
            </div>
          </div>

          <div
            className={cn(
              "flex flex-col items-center justify-center gap-9",
              compactDesktop && "hidden",
            )}
          >
            {orderedApps.slice(0, 3).map((app) => (
              <DesktopAppIcon
                key={app.url}
                app={app}
                onOpen={onOpen}
                editMode={editMode}
                dragging={draggingUrl === app.url}
                onDragStart={startAppDrag}
                onDrop={dropApp}
                onDragEnd={() => setDraggingUrl(null)}
                appNameMap={appNameMap}
                appDescMap={appDescMap}
              />
            ))}
          </div>
        </div>

        <div
          className={cn(
            "mx-auto mb-7 flex max-w-[780px] items-center gap-5 rounded-[26px] bg-white/66 px-5 py-3 shadow-2xl shadow-black/16 backdrop-blur-xl",
            compactDesktop &&
              "absolute bottom-5 left-20 right-5 z-10 mx-0 mb-0 justify-start gap-3 overflow-x-auto rounded-[22px] px-4 py-3",
            tabletDesktop &&
              "left-24 right-8 justify-center gap-4 rounded-[26px] px-5",
            mobileDesktop && "bottom-4 left-16 right-4 gap-2 px-3",
          )}
        >
          {orderedApps.map((app) => {
            const Icon = app.icon;
            return (
              <button
                key={app.url}
                type="button"
                draggable={editMode}
                onClick={() => {
                  if (!editMode) onOpen(app.url);
                }}
                onDragStart={(event) => startAppDrag(event, app.url)}
                onDragOver={(event) => {
                  if (editMode) event.preventDefault();
                }}
                onDrop={(event) => dropApp(event, app.url)}
                onDragEnd={() => setDraggingUrl(null)}
                className={cn(
                  "grid size-16 place-items-center rounded-[18px] bg-gradient-to-br text-white shadow-lg shadow-black/12 transition hover:-translate-y-1 hover:shadow-xl",
                  app.color,
                  compactDesktop && "size-13 shrink-0 rounded-2xl",
                  tabletDesktop && "size-14",
                  mobileDesktop && "size-11 rounded-[15px]",
                  editMode &&
                    "cursor-move ring-2 ring-white/35 hover:translate-y-0",
                  draggingUrl === app.url && "scale-95 opacity-45",
                )}
                title={`${labelFromMap(appNameMap, app.name)} · ${labelFromMap(appDescMap, app.description)}`}
              >
                <Icon
                  className={cn(
                    "size-8",
                    compactDesktop && "size-7",
                    mobileDesktop && "size-6",
                  )}
                />
              </button>
            );
          })}
        </div>
      </div>
      {activePanel !== "home" && (
        <DesktopControlPanel
          panel={activePanel}
          onClose={() => setActivePanel("home")}
          onOpen={onOpen}
        />
      )}
    </div>
  );
}

function DesktopControlPanel({
  panel,
  onClose,
  onOpen,
}: {
  panel: DesktopPanelId;
  onClose: () => void;
  onOpen: (url: string) => void;
}) {
  const { t } = useI18n();
  const wt = t.browser.webviewTab;
  const appNameMap = useMemo<Record<string, string>>(
    () => ({
      "Cocoloop 社区": wt.appNameCocoloopCommunity,
      "Cocoloop 市场": wt.appNameCocoloopMarket,
    }),
    [wt.appNameCocoloopCommunity, wt.appNameCocoloopMarket],
  );
  const title =
    panel === "theme"
      ? wt.panelTitleTheme
      : panel === "widgets"
        ? wt.panelTitleWidgets
        : panel === "wallpaper"
          ? wt.panelTitleWallpaper
          : panel === "games"
            ? wt.panelTitleGames
            : panel === "add"
              ? wt.panelTitleAddApp
              : wt.panelTitleDesktopSettings;

  return (
    <div className="absolute bottom-7 left-24 top-24 z-20 w-[360px] overflow-hidden rounded-[28px] border border-white/30 bg-white/72 text-slate-800 shadow-2xl shadow-black/20 backdrop-blur-2xl">
      <div className="flex items-center justify-between border-b border-white/45 px-5 py-4">
        <div>
          <div className="text-base font-semibold">{title}</div>
          <div className="text-xs text-slate-500">{wt.panelSubtitle}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full bg-slate-900/8 px-3 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-900/14"
        >
          {wt.panelClose}
        </button>
      </div>

      <div className="max-h-[calc(100%-72px)] overflow-y-auto p-5">
        {panel === "theme" && (
          <div className="space-y-4">
            {wt.themeNames.map((name, index) => (
              <button
                key={name}
                type="button"
                className={cn(
                  "flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition hover:bg-white/70",
                  index === 0
                    ? "border-blue-400 bg-white/70"
                    : "border-white/60 bg-white/38",
                )}
              >
                <span className="size-10 rounded-2xl bg-gradient-to-br from-slate-400 via-zinc-300 to-rose-300 shadow-inner" />
                <span>
                  <span className="block text-sm font-semibold">{name}</span>
                  <span className="block text-xs text-slate-500">
                    {wt.themeDescs[index]}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}

        {panel === "widgets" && (
          <div className="space-y-3">
            {[CalendarDaysIcon, FileTextIcon, Clock3Icon, LayoutGridIcon].map(
              (Icon, index) => {
                return (
                  <div
                    key={wt.widgetPanelNames[index]}
                    className="flex items-center gap-3 rounded-2xl bg-white/46 p-3"
                  >
                    <span className="grid size-10 place-items-center rounded-2xl bg-blue-500 text-white">
                      <Icon className="size-5" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold">
                        {wt.widgetPanelNames[index]}
                      </div>
                      <div className="truncate text-xs text-slate-500">
                        {wt.widgetPanelDescs[index]}
                      </div>
                    </div>
                    <span className="rounded-full bg-emerald-500/14 px-2 py-1 text-[10px] font-medium text-emerald-700">
                      {wt.widgetEnabled}
                    </span>
                  </div>
                );
              },
            )}
          </div>
        )}

        {panel === "wallpaper" && (
          <div className="grid grid-cols-2 gap-3">
            {[
              "from-slate-400 via-zinc-300 to-rose-300",
              "from-sky-300 via-indigo-300 to-slate-500",
              "from-emerald-300 via-teal-400 to-slate-600",
              "from-stone-500 via-neutral-400 to-orange-200",
            ].map((gradient, index) => (
              <button
                key={gradient}
                type="button"
                className={cn(
                  "h-24 rounded-3xl bg-gradient-to-br shadow-inner",
                  gradient,
                )}
                title={wt.wallpaperTitle(index + 1)}
              />
            ))}
          </div>
        )}

        {panel === "games" && (
          <div className="space-y-3">
            {wt.gameNames.map((name, index) => {
              const Icon =
                index === 0
                  ? VideoIcon
                  : index === 1
                    ? Gamepad2Icon
                    : SparklesIcon;
              return (
                <button
                  key={name}
                  type="button"
                  className="flex w-full items-center gap-3 rounded-2xl bg-white/46 p-3 text-left transition hover:bg-white/74"
                  onClick={() => {
                    if (index === 0) onOpen("https://www.bilibili.com/");
                  }}
                >
                  <span className="grid size-10 place-items-center rounded-2xl bg-gradient-to-br from-blue-500 to-cyan-400 text-white">
                    <Icon className="size-5" />
                  </span>
                  <span className="text-sm font-semibold">{name}</span>
                </button>
              );
            })}
          </div>
        )}

        {panel === "add" && (
          <div className="space-y-3">
            {AI_DESKTOP_APPS.map((app) => {
              const Icon = app.icon;
              return (
                <button
                  key={app.url}
                  type="button"
                  onClick={() => onOpen(app.url)}
                  className="flex w-full items-center gap-3 rounded-2xl bg-white/46 p-3 text-left transition hover:bg-white/74"
                >
                  <span
                    className={cn(
                      "grid size-10 place-items-center rounded-2xl bg-gradient-to-br text-white",
                      app.color,
                    )}
                  >
                    <Icon className="size-5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold">
                      {appNameMap[app.name] ?? app.name}
                    </span>
                    <span className="block truncate text-xs text-slate-500">
                      {app.url}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        )}

        {panel === "settings" && (
          <div className="space-y-3">
            {wt.settingNames.map((name, index) => (
              <div key={name} className="rounded-2xl bg-white/46 p-3">
                <div className="text-sm font-semibold">{name}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {wt.settingDescs[index]}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DesktopAppIcon({
  app,
  onOpen,
  compact,
  editMode,
  dragging,
  onDragStart,
  onDrop,
  onDragEnd,
  appNameMap,
  appDescMap,
}: {
  app: BrowserDesktopApp;
  onOpen: (url: string) => void;
  compact?: boolean;
  editMode?: boolean;
  dragging?: boolean;
  onDragStart?: (event: DragEvent<HTMLElement>, url: string) => void;
  onDrop?: (event: DragEvent<HTMLElement>, url: string) => void;
  onDragEnd?: () => void;
  appNameMap?: Record<string, string>;
  appDescMap?: Record<string, string>;
}) {
  const Icon = app.icon;
  const displayName = appNameMap?.[app.name] ?? app.name;
  const displayDesc = appDescMap?.[app.description] ?? app.description;
  return (
    <button
      type="button"
      draggable={editMode}
      onClick={() => {
        if (!editMode) onOpen(app.url);
      }}
      onDragStart={(event) => onDragStart?.(event, app.url)}
      onDragOver={(event) => {
        if (editMode) event.preventDefault();
      }}
      onDrop={(event) => onDrop?.(event, app.url)}
      onDragEnd={onDragEnd}
      className={cn(
        "group flex min-w-0 flex-col items-center gap-2 rounded-2xl p-1 text-center transition hover:bg-white/16 focus:outline-none focus:ring-2 focus:ring-white/45",
        editMode && "cursor-move ring-2 ring-white/35",
        dragging && "scale-95 opacity-45",
      )}
      title={`${displayName} · ${displayDesc}`}
    >
      <span
        className={cn(
          "grid place-items-center rounded-[18px] bg-gradient-to-br text-white shadow-lg shadow-black/14 transition group-hover:-translate-y-0.5 group-hover:shadow-xl",
          compact ? "size-16" : "size-[72px]",
          app.color,
        )}
      >
        <Icon className={compact ? "size-8" : "size-9"} />
      </span>
      <span className="w-24 truncate text-sm font-medium text-white drop-shadow">
        {displayName}
      </span>
      {!compact && (
        <span className="line-clamp-1 w-28 text-[11px] text-white/72">
          {displayDesc}
        </span>
      )}
    </button>
  );
}

export const WebviewTab = forwardRef<WebviewTabHandle, Props>(
  function WebviewTab({ tab, active, onPatch }, imperativeRef) {
    const ref = useRef<WebviewElement | null>(null);
    const { t } = useI18n();
    const wt = t.browser.webviewTab;
    const [crash, setCrash] = useState<CrashInfo | null>(null);
    const [reloadSeed, setReloadSeed] = useState(0); // Implementation note.

    // Implementation note.
    // Implementation note.
    // "The WebView must be attached to the DOM and the dom-ready event
    // emitted before this method can be called."
    const readyRef = useRef(false);

    // Implementation note.
    const safe = <T,>(fn: () => T, fallback: T): T => {
      if (!ref.current || !readyRef.current) return fallback;
      try {
        return fn();
      } catch (e) {
        swallow(e);
        return fallback;
      }
    };

    useImperativeHandle(
      imperativeRef,
      () => ({
        reload: () =>
          safe(() => {
            ref.current!.reload();
            return undefined;
          }, undefined),
        goBack: () =>
          safe(() => {
            ref.current!.goBack();
            return undefined;
          }, undefined),
        goForward: () =>
          safe(() => {
            ref.current!.goForward();
            return undefined;
          }, undefined),
        loadURL: (url) => {
          if (!ref.current || !readyRef.current) {
            // Implementation note.
            if (ref.current) ref.current.src = url;
            return;
          }
          try {
            void ref.current.loadURL(url).catch((e) => {
              swallow(e);
            });
          } catch (e) {
            swallow(e);
            ref.current.src = url;
          }
        },
        canGoBack: () => safe(() => ref.current!.canGoBack(), false),
        canGoForward: () => safe(() => ref.current!.canGoForward(), false),
        executeJS: async (code) => {
          const wv = ref.current;
          const api = window.octopus;
          if (!wv || !api || !readyRef.current) return undefined;
          try {
            return await api.browser.executeJS(wv.getWebContentsId(), code);
          } catch (e) {
            swallow(e);
            return undefined;
          }
        },
        getWebContentsId: () =>
          safe(() => ref.current!.getWebContentsId(), null),
        extractText: async () => {
          const wv = ref.current;
          const api = window.octopus;
          if (!wv || !api || !readyRef.current) {
            throw new Error("webview not ready");
          }
          return api.browser.extractText(wv.getWebContentsId());
        },
        capturePage: async () => {
          const wv = ref.current;
          const api = window.octopus;
          if (!wv || !api || !readyRef.current) {
            throw new Error("webview not ready");
          }
          return api.browser.capturePage(wv.getWebContentsId());
        },
        runAction: async (action, params = {}) => {
          const wv = ref.current;
          const api = window.octopus;
          if (!wv || !api || !readyRef.current) {
            throw new Error("webview not ready");
          }
          const wcId = wv.getWebContentsId();
          switch (action) {
            case "click":
              return api.browser.click(wcId, String(params.selector || ""));
            case "type":
              return api.browser.type(
                wcId,
                String(params.selector || ""),
                String(params.text || ""),
                { clear: !!params.clear },
              );
            case "hover":
              return api.browser.hover(wcId, String(params.selector || ""));
            case "scroll":
              return api.browser.scroll(wcId, params);
            case "wait":
              return api.browser.waitFor(
                wcId,
                String(params.selector || ""),
                Number(params.timeout || 10_000),
              );
            case "press":
              return api.browser.pressKey(wcId, String(params.key || "Enter"));
            case "aria":
              return api.browser.getAriaTree(wcId, {
                maxDepth:
                  typeof params.maxDepth === "number"
                    ? params.maxDepth
                    : undefined,
              });
            default:
              return { ok: false, error: `unsupported action: ${action}` };
          }
        },
      }),
      [],
    );

    // Implementation note.
    useEffect(() => {
      const wv = ref.current;
      if (!wv) return;

      const onDomReady = () => {
        readyRef.current = true;
      };
      wv.addEventListener("dom-ready", onDomReady);

      const onTitle = (e: Event & { title?: string }) => {
        const t = e.title || wv.getTitle();
        if (t) onPatch({ title: t });
      };
      const onFavicon = (e: Event & { favicons?: string[] }) => {
        const f = e.favicons?.[0];
        if (f) onPatch({ favicon: f });
      };
      const onStart = () => onPatch({ isLoading: true });
      const onStop = () => onPatch({ isLoading: false });
      const onNavigated = (e: Event & { url?: string }) => {
        if (e.url) onPatch({ url: e.url });
      };

      // Implementation note.
      const onCrashed = (e: Event & { reason?: string; exitCode?: number }) => {
        readyRef.current = false;
        setCrash({
          reason: e.reason || "render-process-gone",
          exitCode: e.exitCode ?? -1,
        });
        onPatch({ isLoading: false });
      };

      wv.addEventListener("page-title-updated", onTitle as EventListener);
      wv.addEventListener("page-favicon-updated", onFavicon as EventListener);
      wv.addEventListener("did-start-loading", onStart);
      wv.addEventListener("did-stop-loading", onStop);
      wv.addEventListener("did-navigate", onNavigated as EventListener);
      wv.addEventListener("crashed", onCrashed as EventListener);
      wv.addEventListener("render-process-gone", onCrashed as EventListener);
      wv.addEventListener("did-navigate-in-page", onNavigated as EventListener);

      return () => {
        wv.removeEventListener("dom-ready", onDomReady);
        wv.removeEventListener("page-title-updated", onTitle as EventListener);
        wv.removeEventListener(
          "page-favicon-updated",
          onFavicon as EventListener,
        );
        wv.removeEventListener("did-start-loading", onStart);
        wv.removeEventListener("did-stop-loading", onStop);
        wv.removeEventListener("did-navigate", onNavigated as EventListener);
        wv.removeEventListener(
          "did-navigate-in-page",
          onNavigated as EventListener,
        );
        wv.removeEventListener("crashed", onCrashed as EventListener);
        wv.removeEventListener(
          "render-process-gone",
          onCrashed as EventListener,
        );
      };
    }, [onPatch, reloadSeed]);

    // Implementation note.
    useEffect(() => {
      const wv = ref.current;
      const api = window.octopus;
      if (!wv || !api) return;
      let cancelled = false;
      const apply = async () => {
        try {
          if (cancelled) return;
          const id = wv.getWebContentsId();
          await api.browser.setDevice(id, tab.device);
        } catch (e) {
          swallow(e);
        }
      };
      const handler = () => void apply();
      if (readyRef.current) {
        void apply();
      } else {
        wv.addEventListener("dom-ready", handler, { once: true });
      }
      return () => {
        cancelled = true;
        wv.removeEventListener("dom-ready", handler);
      };
    }, [tab.device]);

    // Implementation note.
    // Implementation note.
    const style: CSSProperties = active
      ? { display: "inline-flex", width: "100%", height: "100%" }
      : {
          display: "inline-flex",
          position: "absolute",
          width: 0,
          height: 0,
          visibility: "hidden",
          pointerEvents: "none",
        };

    // Implementation note.
    // Implementation note.
    const onReloadAfterCrash = () => {
      setCrash(null);
      setReloadSeed((s) => s + 1);
    };

    if (tab.url === BROWSER_HOME_URL) {
      return (
        <BrowserHome
          active={active}
          device={tab.device}
          onOpen={(url) => onPatch({ url, title: url, isLoading: true })}
        />
      );
    }

    if (crash && active) {
      return (
        <div
          style={{ width: "100%", height: "100%" }}
          className="flex flex-col items-center justify-center gap-3 bg-muted/30 px-6 text-center"
        >
          <div className="text-4xl">😵</div>
          <div className="text-base font-semibold">{wt.crashTitle}</div>
          <div className="max-w-md text-xs text-muted-foreground">
            {crash.reason} (exit {crash.exitCode}) · {wt.crashDesc}
          </div>
          <button
            onClick={onReloadAfterCrash}
            className="rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground transition-colors hover:bg-primary/90"
          >
            {wt.crashReload}
          </button>
        </div>
      );
    }

    if (!window.octopus?.isElectron) {
      return (
        <BackendBrowserTab
          tab={tab}
          active={active}
          onPatch={onPatch}
          imperativeRef={imperativeRef}
        />
      );
    }

    return (
      <webview
        key={`wv-${tab.id}-${reloadSeed}`}
        ref={ref as unknown as React.RefObject<HTMLElement>}
        src={tab.url}
        partition="persist:octopus-browser"
        style={style}
      />
    );
  },
);
