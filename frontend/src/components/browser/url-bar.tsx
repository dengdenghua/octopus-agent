/* Implementation note. */

import {
  ArrowLeftIcon,
  ArrowRightIcon,
  MinusIcon,
  MoreHorizontalIcon,
  PlusIcon,
  RefreshCwIcon,
  HouseIcon,
  ImageIcon,
  LaptopIcon,
  PuzzleIcon,
  TabletIcon,
  SmartphoneIcon,
  SparklesIcon,
  StarIcon,
  ShieldCheckIcon,
  ClockIcon,
  Trash2Icon,
  ExternalLinkIcon,
  SearchIcon,
  RotateCcwIcon,
  DownloadIcon,
  FolderOpenIcon,
  FileIcon,
  CheckCircleIcon,
  AlertCircleIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { toast } from "sonner";

import {
  queueComposerImageEntry,
  readLastComposerTarget,
} from "@/core/composer-image-inbox";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import type { DevicePreset } from "../workspace/embedded-browser/browser-context";
import { LiquidGlass } from "./liquid-glass";
import {
  BROWSER_HOME_URL,
  SEARCH_ENGINE_URLS,
  useBrowserStore,
  type Bookmark,
  type HistoryEntry,
} from "./browser-store";
import type { WebviewTabHandle } from "./webview-tab";

const DEVICE_ORDER: DevicePreset[] = ["desktop", "tablet", "mobile"];
const DEVICE_ICONS = {
  desktop: LaptopIcon,
  tablet: TabletIcon,
  mobile: SmartphoneIcon,
} as const;

type BrowserDownloadState =
  | "progressing"
  | "completed"
  | "cancelled"
  | "interrupted";

interface BrowserDownload {
  id: string;
  filename: string;
  url: string;
  state: BrowserDownloadState;
  receivedBytes: number;
  totalBytes: number;
  savePath?: string;
  createdAt: number;
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`;
}

function looksLikeUrl(input: string): boolean {
  if (/^https?:\/\//i.test(input)) return true;
  if (/^[a-zA-Z0-9-]+:\/\//.test(input)) return true;
  if (/\s/.test(input)) return false;
  return /\./.test(input);
}

function normalize(input: string, searchUrl: string): string {
  const trimmed = input.trim();
  if (!trimmed) return "";
  if (looksLikeUrl(trimmed)) {
    return /^[a-zA-Z]+:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`;
  }
  return `${searchUrl}${encodeURIComponent(trimmed)}`;
}

interface Props {
  webviewHandle: WebviewTabHandle | null;
  onOpenExtensions?: () => void;
}

export function UrlBar({ webviewHandle, onOpenExtensions }: Props) {
  const { t } = useI18n();
  const ub = t.browser.urlBar;
  const bp = t.browserPreviewPanel;
  const {
    activeTab,
    patchTab,
    toggleCopilot,
    state,
    history,
    bookmarks,
    addBookmark,
    removeBookmark,
    isBookmarked,
    clearHistory,
    settings,
  } = useBrowserStore();
  const [draft, setDraft] = useState(activeTab?.url ?? "");
  const [canBack, setCanBack] = useState(false);
  const [canForward, setCanForward] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [siteInfoOpen, setSiteInfoOpen] = useState(false);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [suggestionIndex, setSuggestionIndex] = useState(-1);
  const [downloadsOpen, setDownloadsOpen] = useState(false);
  const [downloads, setDownloads] = useState<BrowserDownload[]>([]);
  const [siteDataStatus, setSiteDataStatus] = useState<string | null>(null);
  const [actionsOpen, setActionsOpen] = useState(false);
  const [zoomByTab, setZoomByTab] = useState<Record<string, number>>({});
  const historyBtnRef = useRef<HTMLButtonElement>(null);
  const downloadsBtnRef = useRef<HTMLButtonElement>(null);
  const actionsBtnRef = useRef<HTMLButtonElement>(null);
  const addressBarRef = useRef<HTMLDivElement>(null);
  const siteInfoBtnRef = useRef<HTMLButtonElement>(null);
  const siteInfoPanelRef = useRef<HTMLDivElement>(null);
  const { confirm, confirmDialog } = useConfirmDialog();

  const deviceLabelMap = useMemo<Record<DevicePreset, string>>(
    () => ({
      desktop: ub.deviceDesktop,
      tablet: ub.deviceTablet,
      mobile: ub.deviceMobile,
    }),
    [ub],
  );

  useEffect(() => {
    setDraft(activeTab?.url ?? "");
  }, [activeTab?.id, activeTab?.url]);

  useEffect(() => {
    if (!webviewHandle) {
      setCanBack(false);
      setCanForward(false);
      return;
    }
    setCanBack(webviewHandle.canGoBack());
    setCanForward(webviewHandle.canGoForward());
  }, [webviewHandle, activeTab?.isLoading, activeTab?.url]);

  const submit = useCallback(() => {
    const target = normalize(draft, SEARCH_ENGINE_URLS[settings.searchEngine]);
    if (!target) return;
    if (activeTab && webviewHandle) {
      webviewHandle.loadURL(target);
      patchTab(activeTab.id, { url: target });
    }
    setSuggestionsOpen(false);
    setSuggestionIndex(-1);
  }, [activeTab, draft, patchTab, settings.searchEngine, webviewHandle]);

  const addressSuggestions = useMemo(() => {
    const query = draft.trim().toLowerCase();
    if (!query) return [];
    const seen = new Set<string>();
    const merged = [
      ...bookmarks.map((item) => ({ ...item, source: "bookmark" as const })),
      ...history.map((item) => ({ ...item, source: "history" as const })),
    ];
    return merged
      .filter((item) => {
        if (!item.url || seen.has(item.url)) return false;
        seen.add(item.url);
        const haystack = `${item.title || ""} ${item.url}`.toLowerCase();
        return haystack.includes(query);
      })
      .slice(0, 6);
  }, [bookmarks, draft, history]);

  const onDeviceChange = useCallback(
    (device: DevicePreset) => {
      if (activeTab) patchTab(activeTab.id, { device });
    },
    [activeTab, patchTab],
  );

  const toggleBookmark = useCallback(() => {
    if (!activeTab) return;
    if (isBookmarked(activeTab.url)) {
      removeBookmark(activeTab.url);
    } else {
      addBookmark({
        url: activeTab.url,
        title: activeTab.title || activeTab.url,
        favicon: activeTab.favicon,
      });
    }
  }, [activeTab, addBookmark, removeBookmark, isBookmarked]);

  const goHome = useCallback(() => {
    if (!activeTab) return;
    patchTab(activeTab.id, {
      url: BROWSER_HOME_URL,
      title: t.browser.webviewTab.aiBrowserDesktop,
      isLoading: false,
    });
    setDraft(BROWSER_HOME_URL);
  }, [activeTab, patchTab, t.browser.webviewTab.aiBrowserDesktop]);

  const attachScreenshotToNextComposer = useCallback(async () => {
    if (!webviewHandle) return;
    try {
      const shot = await webviewHandle.capturePage();
      if (!shot?.dataUrl) {
        toast.error(bp.attachScreenshotFailed);
        return;
      }
      const host = (() => {
        try {
          return activeTab?.url ? new URL(activeTab.url).hostname : "browser";
        } catch {
          return "browser";
        }
      })();
      queueComposerImageEntry({
        dataUrl: shot.dataUrl,
        filename: `browser-shot-${host}-${Date.now()}.png`,
        sourceLabel: bp.attachScreenshotSource,
      });
      const target = readLastComposerTarget();
      if (target) {
        window.location.hash = target;
      }
      toast.success(bp.attachScreenshotSuccess);
    } catch (error) {
      swallow(error);
      toast.error(bp.attachScreenshotFailed);
    }
  }, [activeTab?.url, bp, webviewHandle]);

  const goTo = useCallback(
    (url: string) => {
      if (activeTab && webviewHandle) {
        webviewHandle.loadURL(url);
        patchTab(activeTab.id, { url });
        setDraft(url);
      }
      setHistoryOpen(false);
      setSuggestionsOpen(false);
      setSuggestionIndex(-1);
    },
    [activeTab, patchTab, webviewHandle],
  );

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "ArrowDown" && addressSuggestions.length > 0) {
        e.preventDefault();
        setSuggestionsOpen(true);
        setSuggestionIndex((i) =>
          Math.min(i + 1, addressSuggestions.length - 1),
        );
        return;
      }
      if (e.key === "ArrowUp" && addressSuggestions.length > 0) {
        e.preventDefault();
        setSuggestionsOpen(true);
        setSuggestionIndex((i) => Math.max(i - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        if (
          suggestionsOpen &&
          suggestionIndex >= 0 &&
          addressSuggestions[suggestionIndex]
        ) {
          e.preventDefault();
          goTo(addressSuggestions[suggestionIndex].url);
          return;
        }
        submit();
      }
      if (e.key === "Escape") {
        setDraft(activeTab?.url ?? "");
        setSuggestionsOpen(false);
        setSuggestionIndex(-1);
      }
    },
    [
      activeTab?.url,
      addressSuggestions,
      goTo,
      submit,
      suggestionIndex,
      suggestionsOpen,
    ],
  );

  const clearCurrentSiteData = useCallback(async () => {
    if (!webviewHandle || !window.octopus?.browser) return;
    const wcId = webviewHandle.getWebContentsId();
    if (wcId == null) return;
    const confirmed = await confirm({
      title: ub.clearData,
      description: ub.confirmClearSiteData,
      confirmLabel: ub.clearData,
    });
    if (!confirmed) return;
    setSiteDataStatus(ub.clearingSiteData);
    try {
      const result = await window.octopus.browser.clearSiteData(wcId);
      if (!result.ok) {
        setSiteDataStatus(result.error || ub.clearFailed);
        return;
      }
      setSiteDataStatus(ub.siteCleared(result.origin || ub.currentSite));
      setSiteInfoOpen(false);
      webviewHandle.reload();
    } catch (error) {
      swallow(error);
      setSiteDataStatus(
        error instanceof Error ? error.message : ub.clearFailed,
      );
    }
  }, [confirm, ub, webviewHandle]);

  const siteOrigin = useMemo(() => {
    if (!activeTab?.url) return null;
    try {
      const parsed = new URL(activeTab.url);
      if (!["http:", "https:"].includes(parsed.protocol)) return null;
      return parsed.origin;
    } catch (e) {
      swallow(e);
      return null;
    }
  }, [activeTab?.url]);

  const openExternalCurrentSite = useCallback(() => {
    if (!activeTab?.url || !window.octopus?.app) return;
    void window.octopus.app.openExternal(activeTab.url);
    setSiteInfoOpen(false);
  }, [activeTab?.url]);

  const device = activeTab?.device ?? "desktop";
  const activeZoom = activeTab ? (zoomByTab[activeTab.id] ?? 100) : 100;
  const bookmarked = activeTab ? isBookmarked(activeTab.url) : false;
  const activeDownloadCount = downloads.filter(
    (d) => d.state === "progressing",
  ).length;
  const latestDownload = downloads[0] ?? null;
  const canManageSiteData =
    typeof window !== "undefined" &&
    !!window.octopus?.browser &&
    !!activeTab?.url &&
    (activeTab.url.startsWith("http://") ||
      activeTab.url.startsWith("https://"));
  const canUsePageActions = Boolean(
    activeTab?.url &&
    !activeTab.url.startsWith("octopus:") &&
    !activeTab.url.startsWith("about:"),
  );

  const applyZoom = useCallback(
    (nextZoom: number) => {
      const normalized = Math.max(50, Math.min(200, nextZoom));
      if (activeTab) {
        setZoomByTab((prev) => ({ ...prev, [activeTab.id]: normalized }));
      }
      if (!webviewHandle || !canUsePageActions) return;
      const scale = (normalized / 100).toFixed(2);
      void webviewHandle.executeJS(`
        (() => {
          const scale = ${JSON.stringify(scale)};
          document.documentElement.style.zoom = scale;
          document.body.style.zoom = scale;
          return true;
        })();
      `);
    },
    [activeTab, canUsePageActions, webviewHandle],
  );

  const findInPage = useCallback(() => {
    if (!webviewHandle || !canUsePageActions) return;
    const query = window.prompt(ub.findPrompt);
    if (!query) return;
    setActionsOpen(false);
    void webviewHandle.executeJS(`
      (() => window.find(${JSON.stringify(query)}, false, false, true, false, true, false))();
    `);
  }, [canUsePageActions, ub.findPrompt, webviewHandle]);

  useEffect(() => {
    if (!window.octopus?.on) return;
    return window.octopus.on("browser:download-event", (payload) => {
      const item = payload as BrowserDownload;
      if (!item?.id) return;
      setDownloads((prev) => {
        const next = [
          item,
          ...prev.filter((download) => download.id !== item.id),
        ].sort((a, b) => b.createdAt - a.createdAt);
        return next.slice(0, 20);
      });
      setDownloadsOpen(true);
    });
  }, []);

  useEffect(() => {
    if (!siteInfoOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (siteInfoPanelRef.current?.contains(target)) return;
      if (siteInfoBtnRef.current?.contains(target)) return;
      setSiteInfoOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [siteInfoOpen]);

  useEffect(() => {
    setSiteInfoOpen(false);
  }, [activeTab?.id, activeTab?.url]);

  useEffect(() => {
    if (!activeTab || !webviewHandle || !canUsePageActions) return;
    const zoom = zoomByTab[activeTab.id] ?? 100;
    const scale = (zoom / 100).toFixed(2);
    void webviewHandle.executeJS(`
      (() => {
        const scale = ${JSON.stringify(scale)};
        document.documentElement.style.zoom = scale;
        document.body.style.zoom = scale;
        return true;
      })();
    `);
  }, [
    activeTab?.id,
    activeTab?.url,
    activeTab,
    canUsePageActions,
    webviewHandle,
    zoomByTab,
  ]);

  useEffect(() => {
    if (!suggestionsOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (addressBarRef.current?.contains(target)) return;
      setSuggestionsOpen(false);
      setSuggestionIndex(-1);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [suggestionsOpen]);

  useEffect(() => {
    setSuggestionIndex(-1);
    if (draft.trim().length === 0 || addressSuggestions.length === 0) {
      setSuggestionsOpen(false);
    }
  }, [addressSuggestions.length, draft]);

  return (
    <LiquidGlass
      material="dock"
      className="flex h-14 min-w-0 items-center gap-1 rounded-none border-x-0 border-border-subtle px-2 sm:gap-2 sm:px-3"
      style={{ WebkitAppRegion: "no-drag" } as CSSProperties}
    >
      <button
        onClick={() => webviewHandle?.goBack()}
        disabled={!canBack}
        className="grid size-8 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground disabled:pointer-events-none disabled:opacity-25 sm:size-9"
        title={ub.back}
      >
        <ArrowLeftIcon className="size-4" />
      </button>
      <button
        onClick={() => webviewHandle?.goForward()}
        disabled={!canForward}
        className="grid size-8 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground disabled:pointer-events-none disabled:opacity-25 sm:size-9"
        title={ub.forward}
      >
        <ArrowRightIcon className="size-4" />
      </button>
      <button
        onClick={() => webviewHandle?.reload()}
        disabled={activeTab?.url === BROWSER_HOME_URL}
        className="hidden size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground disabled:pointer-events-none disabled:opacity-25 sm:grid"
        title={ub.refresh}
      >
        <RefreshCwIcon className="size-4" />
      </button>
      <button
        type="button"
        onClick={() => void attachScreenshotToNextComposer()}
        disabled={!webviewHandle || activeTab?.url === BROWSER_HOME_URL}
        className="hidden size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground disabled:pointer-events-none disabled:opacity-25 sm:grid"
        title={bp.attachScreenshotToComposer}
      >
        <ImageIcon className="size-4" />
      </button>
      <button
        onClick={goHome}
        disabled={!activeTab || activeTab.url === BROWSER_HOME_URL}
        className="hidden size-9 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground disabled:pointer-events-none disabled:opacity-25 sm:grid"
        title={ub.backToHome}
      >
        <HouseIcon className="size-4" />
      </button>
      <div ref={addressBarRef} className="relative ml-1 min-w-0 flex-1">
        <LiquidGlass
          material="input"
          interactive
          className="flex h-10 items-center gap-1 rounded-[18px] border-border-subtle px-3 transition-colors focus-within:border-primary/25 focus-within:ring-2 focus-within:ring-primary/12"
        >
          <input
            type="text"
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              setSuggestionsOpen(e.target.value.trim().length > 0);
            }}
            onKeyDown={onKey}
            onFocus={(e) => {
              e.currentTarget.select();
              if (addressSuggestions.length > 0) setSuggestionsOpen(true);
            }}
            placeholder={ub.searchOrUrl}
            className="min-w-0 flex-1 bg-transparent px-2 text-sm font-medium outline-none placeholder:text-muted-foreground/65"
          />
          {canManageSiteData && (
            <div className="relative">
              <button
                ref={siteInfoBtnRef}
                onClick={() => setSiteInfoOpen((v) => !v)}
                className={cn(
                  "grid size-7 place-items-center rounded-full transition-colors",
                  siteInfoOpen
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
                )}
                title={ub.siteInfo}
                aria-label={ub.siteInfo}
              >
                <ShieldCheckIcon className="size-3.5" />
              </button>
              {siteInfoOpen && (
                <div
                  ref={siteInfoPanelRef}
                  className="octo-liquid-glass octo-liquid-glass--sheet absolute right-0 top-full z-50 mt-2 w-[320px] max-w-[calc(100vw-1rem)] rounded-xl p-3 text-popover-foreground"
                >
                  <div className="flex items-start gap-2.5">
                    <div className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
                      <ShieldCheckIcon className="size-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold">{ub.siteInfo}</div>
                      <div className="mt-0.5 truncate text-xs text-muted-foreground">
                        {siteOrigin || activeTab?.url}
                      </div>
                    </div>
                  </div>
                  <div className="mt-3 rounded-lg bg-muted/50 px-3 py-2 text-xs leading-5 text-muted-foreground">
                    {ub.siteInfoDesc}
                  </div>
                  {siteDataStatus && (
                    <div className="mt-2 rounded-lg border border-border-default px-3 py-2 text-xs text-muted-foreground">
                      {siteDataStatus}
                    </div>
                  )}
                  <div className="mt-3 flex items-center gap-2">
                    <button
                      onClick={clearCurrentSiteData}
                      className="flex h-8 flex-1 items-center justify-center gap-1.5 border border-border-default bg-background text-xs font-medium text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2Icon className="size-3.5" />
                      {ub.clearData}
                    </button>
                    <button
                      onClick={openExternalCurrentSite}
                      className="flex h-8 flex-1 items-center justify-center gap-1.5 bg-primary text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                    >
                      <ExternalLinkIcon className="size-3.5" />
                      {ub.openExternally}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          {/* Implementation note. */}
          {activeTab &&
            activeTab.url &&
            !activeTab.url.startsWith("about:") &&
            !activeTab.url.startsWith("octopus:") && (
              <button
                onClick={toggleBookmark}
                className={cn(
                  "grid size-7 place-items-center rounded-full transition-colors",
                  bookmarked
                    ? "text-amber-500 hover:bg-amber-500/10"
                    : "text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
                )}
                title={bookmarked ? ub.removeBookmark : ub.addBookmark}
              >
                <StarIcon
                  className={cn("size-3.5", bookmarked && "fill-amber-500")}
                />
              </button>
            )}
        </LiquidGlass>
        {suggestionsOpen && addressSuggestions.length > 0 && (
          <div className="octo-liquid-glass octo-liquid-glass--sheet absolute left-0 right-0 top-full z-40 mt-2 overflow-hidden rounded-xl py-1.5 text-popover-foreground">
            {addressSuggestions.map((item, index) => {
              const active = index === suggestionIndex;
              const Icon = item.source === "bookmark" ? StarIcon : ClockIcon;
              return (
                <button
                  key={`${item.source}-${item.url}`}
                  onMouseEnter={() => setSuggestionIndex(index)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => goTo(item.url)}
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left transition-colors",
                    active ? "bg-primary/10" : "hover:bg-muted/70",
                  )}
                >
                  {item.favicon ? (
                    <img
                      src={item.favicon}
                      alt=""
                      className="size-4 shrink-0 rounded-sm"
                      onError={(e) => (e.currentTarget.style.display = "none")}
                    />
                  ) : (
                    <Icon className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">
                      {item.title || item.url}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {item.url}
                    </div>
                  </div>
                  <div className="shrink-0 rounded-full bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">
                    {item.source === "bookmark"
                      ? ub.bookmarkLabel
                      : ub.historyLabel}
                  </div>
                </button>
              );
            })}
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={submit}
              className="mt-1 flex w-full items-center gap-2 border-t border-border-default px-3 py-2 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
            >
              <SearchIcon className="size-4" />
              {ub.searchOrOpen(draft.trim())}
            </button>
          </div>
        )}
      </div>

      {/* Implementation note. */}
      <div className="relative">
        <button
          ref={downloadsBtnRef}
          onClick={() => setDownloadsOpen((v) => !v)}
          className={cn(
            "ml-1 grid size-8 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground sm:size-9",
            activeDownloadCount > 0 && "text-primary",
          )}
          title={ub.downloads}
          aria-label={ub.downloads}
        >
          <DownloadIcon className="size-4" />
          {activeDownloadCount > 0 && (
            <span className="absolute right-0.5 top-0.5 size-2 rounded-full bg-primary" />
          )}
        </button>
        {downloadsOpen && (
          <DownloadDropdown
            downloads={downloads}
            latestDownload={latestDownload}
            onClose={() => setDownloadsOpen(false)}
            anchorRef={downloadsBtnRef}
          />
        )}
      </div>

      <div className="relative">
        <button
          ref={historyBtnRef}
          onClick={() => setHistoryOpen((v) => !v)}
          className="grid size-8 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground sm:size-9"
          title={ub.historyAndBookmarks}
        >
          <ClockIcon className="size-4" />
        </button>
        {historyOpen && (
          <HistoryDropdown
            history={history}
            bookmarks={bookmarks}
            onPick={goTo}
            onRemoveBookmark={removeBookmark}
            onClearHistory={clearHistory}
            onClose={() => setHistoryOpen(false)}
            anchorRef={historyBtnRef}
          />
        )}
      </div>

      {/* AI copilot toggle */}
      <button
        onClick={toggleCopilot}
        className={cn(
          "ml-1 hidden h-10 items-center gap-1.5 rounded-[18px] border px-3 text-xs font-semibold shadow-[inset_0_1px_1px_rgba(255,255,255,0.45),0_4px_14px_rgba(15,23,42,0.04)] transition-colors sm:flex",
          state.copilotOpen
            ? "border-primary/35 bg-primary/12 text-primary"
            : "border-border-subtle bg-background/50 text-muted-foreground hover:bg-background/70 hover:text-foreground",
        )}
        title={ub.aiAssistant}
      >
        <SparklesIcon className="size-3.5" />
        <span>AI</span>
      </button>

      <div className="relative">
        <button
          ref={actionsBtnRef}
          onClick={() => setActionsOpen((v) => !v)}
          className="ml-1 grid size-8 shrink-0 place-items-center rounded-xl text-muted-foreground transition-colors hover:bg-background/62 hover:text-foreground sm:size-9"
          title={ub.moreActions}
          aria-label={ub.moreActions}
        >
          <MoreHorizontalIcon className="size-4" />
        </button>
        {actionsOpen && (
          <BrowserActionsMenu
            activeZoom={activeZoom}
            anchorRef={actionsBtnRef}
            canManageSiteData={canManageSiteData}
            canUsePageActions={canUsePageActions}
            device={device}
            deviceLabelMap={deviceLabelMap}
            onClearSiteData={clearCurrentSiteData}
            onClose={() => setActionsOpen(false)}
            onDeviceChange={onDeviceChange}
            onFindInPage={findInPage}
            onOpenExtensions={onOpenExtensions}
            onReload={() => webviewHandle?.reload()}
            onZoomChange={applyZoom}
            siteDataStatus={siteDataStatus}
          />
        )}
      </div>
      {confirmDialog}
    </LiquidGlass>
  );
}

interface BrowserActionsMenuProps {
  activeZoom: number;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  canManageSiteData: boolean;
  canUsePageActions: boolean;
  device: DevicePreset;
  deviceLabelMap: Record<DevicePreset, string>;
  onClearSiteData: () => void;
  onClose: () => void;
  onDeviceChange: (device: DevicePreset) => void;
  onFindInPage: () => void;
  onOpenExtensions?: () => void;
  onReload: () => void;
  onZoomChange: (zoom: number) => void;
  siteDataStatus: string | null;
}

function BrowserActionsMenu({
  activeZoom,
  anchorRef,
  canManageSiteData,
  canUsePageActions,
  device,
  deviceLabelMap,
  onClearSiteData,
  onClose,
  onDeviceChange,
  onFindInPage,
  onOpenExtensions,
  onReload,
  onZoomChange,
  siteDataStatus,
}: BrowserActionsMenuProps) {
  const { t } = useI18n();
  const ub = t.browser.urlBar;
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [anchorRef, onClose]);

  const menuButtonClass =
    "flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:bg-background/70 hover:text-foreground disabled:pointer-events-none disabled:opacity-40";

  return (
    <div
      ref={ref}
      className="octo-liquid-glass octo-liquid-glass--sheet absolute right-0 top-full z-50 mt-1 w-[292px] overflow-hidden rounded-xl p-2 text-popover-foreground"
    >
      <div className="px-1.5 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {ub.pageActions}
      </div>
      <button
        type="button"
        disabled={!canUsePageActions}
        onClick={() => {
          onReload();
          onClose();
        }}
        className={menuButtonClass}
      >
        <RefreshCwIcon className="size-4" />
        {ub.refresh}
      </button>
      <button
        type="button"
        disabled={!canUsePageActions}
        onClick={onFindInPage}
        className={menuButtonClass}
      >
        <SearchIcon className="size-4" />
        {ub.findInPage}
      </button>

      <div className="my-2 h-px bg-border/55" />

      <div className="flex h-10 items-center gap-2 rounded-xl bg-background/45 px-2">
        <span className="min-w-0 flex-1 text-xs font-medium text-muted-foreground">
          {ub.zoom}
        </span>
        <button
          type="button"
          disabled={!canUsePageActions || activeZoom <= 50}
          onClick={() => onZoomChange(activeZoom - 10)}
          className="grid size-7 place-items-center text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
          title={ub.zoomOut}
          aria-label={ub.zoomOut}
        >
          <MinusIcon className="size-3.5" />
        </button>
        <span className="w-12 text-center text-sm font-semibold tabular-nums">
          {activeZoom}%
        </span>
        <button
          type="button"
          disabled={!canUsePageActions || activeZoom >= 200}
          onClick={() => onZoomChange(activeZoom + 10)}
          className="grid size-7 place-items-center text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
          title={ub.zoomIn}
          aria-label={ub.zoomIn}
        >
          <PlusIcon className="size-3.5" />
        </button>
        <button
          type="button"
          disabled={!canUsePageActions || activeZoom === 100}
          onClick={() => onZoomChange(100)}
          className="grid size-7 place-items-center text-muted-foreground transition-colors hover:bg-background hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
          title={ub.resetZoom}
          aria-label={ub.resetZoom}
        >
          <RotateCcwIcon className="size-3.5" />
        </button>
      </div>

      <div className="mt-2 rounded-xl bg-background/35 p-1">
        <div className="px-1.5 pb-1.5 text-[11px] font-medium text-muted-foreground">
          {ub.devicePreview}
        </div>
        <div className="grid grid-cols-3 gap-1">
          {DEVICE_ORDER.map((d) => {
            const Icon = DEVICE_ICONS[d];
            const active = device === d;
            return (
              <button
                key={d}
                type="button"
                onClick={() => onDeviceChange(d)}
                className={cn(
                  "flex h-8 items-center justify-center gap-1 rounded-lg text-xs font-medium transition-colors",
                  active
                    ? "bg-background text-foreground shadow-[var(--shadow-xs)] ring-1 ring-border-subtle"
                    : "text-muted-foreground hover:bg-background/65 hover:text-foreground",
                )}
                title={ub.switchToDevice(deviceLabelMap[d])}
                aria-label={ub.switchToDevice(deviceLabelMap[d])}
              >
                <Icon className="size-3.5" />
                <span>{deviceLabelMap[d]}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="my-2 h-px bg-border/55" />

      <button
        type="button"
        onClick={() => {
          onOpenExtensions?.();
          onClose();
        }}
        className={menuButtonClass}
      >
        <PuzzleIcon className="size-4" />
        {ub.browserExtensions}
      </button>
      <button
        type="button"
        disabled={!canManageSiteData}
        onClick={onClearSiteData}
        className={cn(
          menuButtonClass,
          "hover:bg-destructive/10 hover:text-destructive",
        )}
      >
        <Trash2Icon className="size-4" />
        {ub.clearData}
      </button>
      {siteDataStatus && (
        <div className="mt-1 rounded-lg border border-border-default px-2.5 py-2 text-[11px] text-muted-foreground">
          {siteDataStatus}
        </div>
      )}
    </div>
  );
}

interface HistoryDropdownProps {
  history: HistoryEntry[];
  bookmarks: Bookmark[];
  onPick: (url: string) => void;
  onRemoveBookmark: (url: string) => void;
  onClearHistory: () => void;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
}

interface DownloadDropdownProps {
  downloads: BrowserDownload[];
  latestDownload: BrowserDownload | null;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
}

function DownloadDropdown({
  downloads,
  latestDownload,
  onClose,
  anchorRef,
}: DownloadDropdownProps) {
  const { t } = useI18n();
  const ub = t.browser.urlBar;
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [anchorRef, onClose]);

  const hasActive = downloads.some((item) => item.state === "progressing");
  const title = hasActive
    ? ub.downloading
    : latestDownload
      ? ub.recentDownload
      : ub.downloads;

  return (
    <div
      ref={ref}
      className="octo-liquid-glass octo-liquid-glass--sheet absolute right-0 top-full z-50 mt-1 w-[360px] max-w-[calc(100vw-1rem)] overflow-hidden rounded-xl text-popover-foreground"
    >
      <div className="flex items-center justify-between border-b border-border-default px-3 py-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <DownloadIcon className="size-4" />
          {title}
        </div>
        <span className="text-[11px] text-muted-foreground">
          {downloads.length > 0
            ? ub.downloadCount(downloads.length)
            : ub.noDownloads}
        </span>
      </div>
      <div className="max-h-[360px] overflow-y-auto py-1">
        {downloads.length === 0 ? (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            {ub.noDownloadRecords}
          </div>
        ) : (
          downloads.map((item) => {
            const completed = item.state === "completed";
            const failed =
              item.state === "cancelled" || item.state === "interrupted";
            const percent =
              item.totalBytes > 0
                ? Math.min(
                    100,
                    Math.round((item.receivedBytes / item.totalBytes) * 100),
                  )
                : 0;
            return (
              <div
                key={item.id}
                className="group px-3 py-2 transition-colors hover:bg-muted/60"
              >
                <div className="flex items-start gap-2">
                  <div
                    className={cn(
                      "mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg",
                      completed
                        ? "bg-emerald-500/10 text-emerald-600"
                        : failed
                          ? "bg-destructive/10 text-destructive"
                          : "bg-primary/10 text-primary",
                    )}
                  >
                    {completed ? (
                      <CheckCircleIcon className="size-4" />
                    ) : failed ? (
                      <AlertCircleIcon className="size-4" />
                    ) : (
                      <FileIcon className="size-4" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-medium">
                      {item.filename || ub.unnamedDownload}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                      {completed
                        ? ub.downloadCompleted
                        : failed
                          ? ub.downloadIncomplete
                          : `${formatBytes(item.receivedBytes)} / ${
                              item.totalBytes > 0
                                ? formatBytes(item.totalBytes)
                                : ub.unknownSize
                            }`}
                    </div>
                    {!completed && !failed && (
                      <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${percent || 8}%` }}
                        />
                      </div>
                    )}
                  </div>
                </div>
                {completed && (
                  <div className="mt-2 flex justify-end gap-1.5">
                    <button
                      onClick={() =>
                        void window.octopus?.browser.openDownload(item.id)
                      }
                      className="rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                    >
                      {ub.openFile}
                    </button>
                    <button
                      onClick={() =>
                        void window.octopus?.browser.showDownloadInFolder(
                          item.id,
                        )
                      }
                      className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                    >
                      <FolderOpenIcon className="size-3" />
                      {ub.openFolder}
                    </button>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function HistoryDropdown({
  history,
  bookmarks,
  onPick,
  onRemoveBookmark,
  onClearHistory,
  onClose,
  anchorRef,
}: HistoryDropdownProps) {
  const { t } = useI18n();
  const ub = t.browser.urlBar;
  const [tab, setTab] = useState<"history" | "bookmarks">("bookmarks");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target)) return;
      if (anchorRef.current?.contains(target)) return;
      onClose();
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [anchorRef, onClose]);

  const items = tab === "history" ? history : bookmarks;

  return (
    <div
      ref={ref}
      className="octo-liquid-glass octo-liquid-glass--sheet absolute right-0 top-full z-50 mt-1 w-[420px] max-w-[calc(100vw-1rem)] rounded-lg"
    >
      <div className="flex items-center justify-between border-b">
        <div className="flex">
          <button
            onClick={() => setTab("bookmarks")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs",
              tab === "bookmarks"
                ? "border-b-2 border-primary text-foreground font-medium"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <StarIcon className="size-3.5" />
            {ub.bookmarksTab(bookmarks.length)}
          </button>
          <button
            onClick={() => setTab("history")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-2 text-xs",
              tab === "history"
                ? "border-b-2 border-primary text-foreground font-medium"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <ClockIcon className="size-3.5" />
            {ub.historyTab(history.length)}
          </button>
        </div>
        {tab === "history" && history.length > 0 && (
          <button
            onClick={onClearHistory}
            className="mr-2 flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-muted-foreground hover:bg-muted hover:text-destructive"
            title={ub.clearHistoryTitle}
          >
            <Trash2Icon className="size-3" />
            {ub.clearHistory}
          </button>
        )}
      </div>
      <div className="max-h-[420px] overflow-y-auto py-1">
        {items.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-muted-foreground">
            {tab === "bookmarks" ? ub.noBookmarks : ub.noHistory}
          </div>
        ) : (
          items.map((item) => {
            const isBookmark = "addedAt" in item;
            const ts = isBookmark ? item.addedAt : item.visitedAt;
            return (
              <div
                key={`${item.url}-${ts}`}
                className="group flex items-center gap-2 px-3 py-1.5 hover:bg-muted/60"
              >
                {item.favicon ? (
                  <img
                    src={item.favicon}
                    alt=""
                    className="size-4 shrink-0"
                    onError={(e) => (e.currentTarget.style.display = "none")}
                  />
                ) : (
                  <div className="size-4 shrink-0 rounded bg-muted-foreground/20" />
                )}
                <button
                  onClick={() => onPick(item.url)}
                  className="flex min-w-0 flex-1 flex-col text-left"
                >
                  <div className="truncate text-xs font-medium">
                    {item.title || item.url}
                  </div>
                  <div className="truncate text-[10px] text-muted-foreground">
                    {item.url}
                  </div>
                </button>
                {isBookmark && (
                  <button
                    onClick={() => onRemoveBookmark(item.url)}
                    className="grid size-5 shrink-0 place-items-center rounded text-muted-foreground/40 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                    title={ub.removeBookmarkTitle}
                  >
                    <Trash2Icon className="size-3" />
                  </button>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
