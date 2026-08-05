/* Implementation note. */

import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  ClockIcon,
  CopyIcon,
  GlobeIcon,
  MenuIcon,
  PlusIcon,
  SearchIcon,
  StarIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CopilotPanel } from "@/components/browser/copilot-panel";

import { TabBar } from "@/components/browser/tab-bar";
import { UrlBar } from "@/components/browser/url-bar";
import {
  BROWSER_HOME_URL,
  BROWSER_OPEN_URL_REQUEST_KEY,
  BrowserStoreProvider,
  setAppMode,
  useBrowserStore,
  type BrowserOpenUrlRequest,
} from "@/components/browser/browser-store";
import {
  WebviewTab,
  type WebviewTabHandle,
} from "@/components/browser/webview-tab";
import { WorkspaceSurfaceHeader } from "@/components/workspace/workspace-surface-header";

const isWindows = (): boolean =>
  typeof navigator !== "undefined" && navigator.userAgent.includes("Windows");
const inElectron = (): boolean =>
  typeof window !== "undefined" && !!window.octopus?.isElectron;

const CHROME_WEB_STORE_EXTENSIONS_URL =
  "https://chromewebstore.google.com/category/extensions";

const isBrowserDevice = (
  value: unknown,
): value is BrowserOpenUrlRequest["device"] =>
  value === "desktop" || value === "tablet" || value === "mobile";

/* Implementation note. */
const DEVICE_STAGE = {
  desktop: {
    width: 0,
    height: 0,
    label: "Desktop",
    description: "Fluid viewport",
  },
  tablet: {
    width: 768,
    height: 1024,
    label: "iPad",
    description: "768 x 1024",
  },
  mobile: {
    width: 390,
    height: 844,
    label: "iPhone",
    description: "390 x 844",
  },
} as const;

function BrowserShell() {
  const { t } = useI18n();
  const {
    state,
    activeTab,
    patchTab,
    openTab,
    closeTab,
    activateTab,
    recordVisit,
  } = useBrowserStore();
  // Implementation note.
  const handlesRef = useRef<Map<string, WebviewTabHandle | null>>(new Map());
  // Implementation note.
  const [activeHandle, setActiveHandle] = useState<WebviewTabHandle | null>(
    null,
  );
  const [sidePanelHovered, setSidePanelHovered] = useState(false);
  const [sidePanelPinned, setSidePanelPinned] = useState(false);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const stageRef = useRef<HTMLDivElement>(null);
  const sidePanelCloseTimerRef = useRef<number | null>(null);
  const electron = inElectron();
  const activeTabId = activeTab?.id ?? null;
  const activeTabUrl = activeTab?.url ?? "";
  const activeTabTitle = activeTab?.title ?? "";
  const activeTabFavicon = activeTab?.favicon;
  const activeTabLoading = activeTab?.isLoading ?? false;

  const openExtensionsStore = useCallback(() => {
    if (window.octopus?.app?.openExternal) {
      void window.octopus.app.openExternal(CHROME_WEB_STORE_EXTENSIONS_URL);
      return;
    }

    const opened = window.open(
      CHROME_WEB_STORE_EXTENSIONS_URL,
      "_blank",
      "noopener,noreferrer",
    );
    if (!opened) openTab(CHROME_WEB_STORE_EXTENSIONS_URL);
  }, [openTab]);

  // Implementation note.
  // Implementation note.
  useEffect(() => {
    if (!activeTabId) {
      setActiveHandle(null);
      window.octopus?.bridge.setActiveTab(null);
      return;
    }
    const h = handlesRef.current.get(activeTabId) ?? null;
    setActiveHandle(h);
    const wcId = h?.getWebContentsId() ?? null;
    if (wcId != null) window.octopus?.bridge.setActiveTab(wcId);
  }, [activeTabId]);

  const activeDevice = activeTab?.device ?? "desktop";
  const renderDevice =
    activeTabUrl === BROWSER_HOME_URL &&
    activeDevice === "desktop" &&
    stageSize.width > 0 &&
    stageSize.width < 640
      ? "mobile"
      : activeDevice;
  const activeStage = DEVICE_STAGE[renderDevice];
  const activeScale =
    renderDevice === "desktop"
      ? 1
      : Math.min(
          1,
          Math.max(0.2, (stageSize.width - 40) / activeStage.width),
          Math.max(0.2, (stageSize.height - 40) / activeStage.height),
        );

  useEffect(() => {
    const node = stageRef.current;
    if (!node) return;
    const update = () => {
      const rect = node.getBoundingClientRect();
      setStageSize({ width: rect.width, height: rect.height });
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Implementation note.
  // Implementation note.
  useEffect(() => {
    if (!activeTabUrl || activeTabLoading) return;
    if (
      activeTabUrl.startsWith("about:") ||
      activeTabUrl.startsWith("octopus:")
    ) {
      return;
    }
    const t = setTimeout(() => {
      recordVisit({
        url: activeTabUrl,
        title: activeTabTitle || activeTabUrl,
        favicon: activeTabFavicon,
      });
    }, 800);
    return () => clearTimeout(t);
  }, [
    activeTabFavicon,
    activeTabLoading,
    activeTabTitle,
    activeTabUrl,
    recordVisit,
  ]);

  // Implementation note.
  useEffect(() => {
    if (!window.octopus) return;
    const off = window.octopus.on("browser:open-tab", (...args) => {
      const payload = args[0] as { url?: string } | undefined;
      if (payload?.url) openTab(payload.url);
    });
    return () => off();
  }, [openTab]);

  useEffect(() => {
    try {
      const rawRequest = localStorage.getItem(BROWSER_OPEN_URL_REQUEST_KEY);
      if (!rawRequest) return;
      localStorage.removeItem(BROWSER_OPEN_URL_REQUEST_KEY);
      let request: BrowserOpenUrlRequest | null = null;
      try {
        const parsed = JSON.parse(rawRequest) as Partial<BrowserOpenUrlRequest>;
        if (typeof parsed.url === "string" && parsed.url.trim()) {
          request = {
            url: parsed.url,
            title: typeof parsed.title === "string" ? parsed.title : undefined,
            device: isBrowserDevice(parsed.device) ? parsed.device : undefined,
            source:
              typeof parsed.source === "string" ? parsed.source : undefined,
            sessionId:
              typeof parsed.sessionId === "string"
                ? parsed.sessionId
                : undefined,
          };
        }
      } catch {
        request = { url: rawRequest };
      }
      if (!request?.url) return;
      openTab(request.url, {
        ...(request.title ? { title: request.title } : {}),
        ...(request.device ? { device: request.device } : {}),
      });
    } catch (e) {
      swallow(e);
    }
  }, [openTab]);

  // Implementation note.
  // Implementation note.
  // Implementation note.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isMac = navigator.userAgent.includes("Mac");
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (!mod) return;
      const k = e.key.toLowerCase();

      // Implementation note.
      if (k === "t" && !e.shiftKey) {
        e.preventDefault();
        openTab();
        return;
      }
      // Implementation note.
      if (k === "w" && !e.shiftKey) {
        e.preventDefault();
        if (activeTab) closeTab(activeTab.id);
        return;
      }
      // Implementation note.
      if (k === "l") {
        e.preventDefault();
        const input = document.querySelector<HTMLInputElement>(
          'input[placeholder="搜索或输入网址"]',
        );
        input?.focus();
        input?.select();
        return;
      }
      // Implementation note.
      if (e.key === "Tab") {
        e.preventDefault();
        const idx = state.tabs.findIndex((t) => t.id === state.activeId);
        const next = e.shiftKey
          ? (idx - 1 + state.tabs.length) % state.tabs.length
          : (idx + 1) % state.tabs.length;
        const tab = state.tabs[next];
        if (tab) activateTab(tab.id);
        return;
      }
      // Implementation note.
      if (/^[1-9]$/.test(e.key)) {
        e.preventDefault();
        const n = parseInt(e.key, 10);
        const idx = n === 9 ? state.tabs.length - 1 : n - 1;
        const tab = state.tabs[idx];
        if (tab) activateTab(tab.id);
        return;
      }
    };
    window.addEventListener("keydown", onKey);

    // Implementation note.
    // Implementation note.
    // Implementation note.
    const offIpc = window.octopus?.on(
      "browser:keyboard-shortcut",
      (...args) => {
        const p = args[0] as
          | {
              key: string;
              shift: boolean;
              alt: boolean;
              meta: boolean;
              control: boolean;
            }
          | undefined;
        if (!p) return;
        onKey(
          new KeyboardEvent("keydown", {
            key: p.key,
            shiftKey: p.shift,
            altKey: p.alt,
            metaKey: p.meta,
            ctrlKey: p.control,
          }),
        );
      },
    );

    return () => {
      window.removeEventListener("keydown", onKey);
      offIpc?.();
    };
  }, [openTab, closeTab, activateTab, activeTab, state.tabs, state.activeId]);

  // Implementation note.
  // Implementation note.
  // Implementation note.
  useEffect(() => {
    if (!isWindows() || !window.octopus) return;
    const apply = () => {
      // Implementation note.
      const root = document.documentElement;
      const bg = getComputedStyle(root).getPropertyValue("--background").trim();
      const fg = getComputedStyle(root).getPropertyValue("--foreground").trim();
      // Implementation note.
      const toCss = (v: string) =>
        v.startsWith("#") || v.startsWith("rgb") ? v : `hsl(${v})`;
      void window
        .octopus!.window.setTitleBarOverlay({
          color: toCss(bg) || "#f1f1f3",
          symbolColor: toCss(fg) || "#525252",
        })
        .catch((e) => {
          swallow(e);
        });
    };
    apply();
    const obs = new MutationObserver(apply);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    });
    return () => obs.disconnect();
  }, []);

  const sidePanelOpen = sidePanelHovered || sidePanelPinned;
  const clearSidePanelCloseTimer = useCallback(() => {
    if (sidePanelCloseTimerRef.current === null) return;
    window.clearTimeout(sidePanelCloseTimerRef.current);
    sidePanelCloseTimerRef.current = null;
  }, []);
  const showSidePanel = useCallback(() => {
    clearSidePanelCloseTimer();
    setSidePanelHovered(true);
  }, [clearSidePanelCloseTimer]);
  const scheduleSidePanelClose = useCallback(() => {
    clearSidePanelCloseTimer();
    sidePanelCloseTimerRef.current = window.setTimeout(() => {
      setSidePanelHovered(false);
      sidePanelCloseTimerRef.current = null;
    }, 180);
  }, [clearSidePanelCloseTimer]);

  useEffect(() => clearSidePanelCloseTimer, [clearSidePanelCloseTimer]);

  return (
    <div className="relative flex h-screen overflow-hidden bg-[linear-gradient(135deg,hsl(var(--muted))_0%,hsl(var(--background))_42%,hsl(var(--muted))_100%)]">
      <BrowserSidePanel
        open={sidePanelOpen}
        pinned={sidePanelPinned}
        onMouseEnter={showSidePanel}
        onMouseLeave={scheduleSidePanelClose}
      />
      {/* Implementation note. */}
      <div className="relative z-[1] flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="relative z-[80] shrink-0">
          <div
            className="flex h-11 shrink-0 items-center gap-0.5 rounded-none border-x-0 border-t-0 border-border-subtle px-1.5"
            style={
              {
                paddingLeft: 10,
                paddingRight: isWindows() && electron ? 154 : 6,
                WebkitAppRegion: "drag",
              } as React.CSSProperties
            }
          >
            <div
              className="flex h-8 shrink-0 items-center justify-start gap-2"
              style={
                {
                  WebkitAppRegion: "no-drag",
                } as React.CSSProperties
              }
            >
              <WorkspaceSurfaceHeader active="browser" />
            </div>
            <div className="flex h-8 min-w-0 flex-1 items-center">
              <TabBar />
            </div>
            <button
              type="button"
              title={
                sidePanelPinned
                  ? t.browser.sidePanel.unpin
                  : t.browser.sidePanel.expand
              }
              aria-label={
                sidePanelPinned
                  ? t.browser.sidePanel.unpin
                  : t.browser.sidePanel.expand
              }
              onMouseEnter={showSidePanel}
              onMouseLeave={scheduleSidePanelClose}
              onClick={() => {
                clearSidePanelCloseTimer();
                setSidePanelPinned((value) => {
                  const nextPinned = !value;
                  setSidePanelHovered(nextPinned);
                  return nextPinned;
                });
              }}
              className={cn(
                "grid size-7 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground",
                sidePanelOpen && "bg-foreground/5 text-foreground",
              )}
              style={
                {
                  WebkitAppRegion: "no-drag",
                } as React.CSSProperties
              }
            >
              <MenuIcon className="size-3.5" />
            </button>
          </div>

          {/* URL bar */}
          <UrlBar
            webviewHandle={activeHandle}
            onOpenExtensions={openExtensionsStore}
          />
        </div>

        <div className="relative z-0 flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex min-h-0 flex-1 overflow-hidden">
            {state.copilotOpen && (
              <div
                className="flex min-h-0 border-r border-border-subtle bg-background"
                style={{
                  flex:
                    renderDevice !== "desktop"
                      ? "1 1 0"
                      : `0 0 ${state.copilotWidth}px`,
                  minWidth: renderDevice !== "desktop" ? 280 : undefined,
                }}
              >
                <CopilotPanel webviewHandle={activeHandle} />
              </div>
            )}
            <div
              ref={stageRef}
              className={cn(
                "relative min-w-0 overflow-hidden bg-background",
                renderDevice === "desktop"
                  ? "flex-1"
                  : "flex flex-1 items-center justify-center bg-[radial-gradient(circle_at_top,hsl(var(--muted))_0%,hsl(var(--background))_58%)] p-5",
              )}
            >
              <div
                className={cn(
                  "relative overflow-hidden bg-background",
                  renderDevice === "desktop"
                    ? "h-full w-full"
                    : "h-full max-h-full max-w-full rounded-[28px] border-[6px] border-foreground/22 shadow-[0_22px_64px_rgba(15,23,42,0.18)]",
                )}
                style={
                  renderDevice === "desktop"
                    ? undefined
                    : {
                        width: activeStage.width,
                        height: activeStage.height,
                        flex: "0 0 auto",
                        transform: `scale(${activeScale})`,
                        transformOrigin: "center",
                      }
                }
              >
                {state.tabs.map((tab) => (
                  <WebviewTab
                    key={tab.id}
                    tab={tab}
                    active={tab.id === state.activeId}
                    renderDevice={
                      tab.id === state.activeId ? renderDevice : tab.device
                    }
                    onPatch={(patch) => patchTab(tab.id, patch)}
                    ref={(handle) => {
                      if (handle) {
                        handlesRef.current.set(tab.id, handle);
                        if (tab.id === state.activeId) {
                          setActiveHandle((prev) => prev ?? handle);
                        }
                      } else {
                        handlesRef.current.delete(tab.id);
                      }
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function BrowserSidePanel({
  open,
  pinned,
  onMouseEnter,
  onMouseLeave,
}: {
  open: boolean;
  pinned: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}) {
  const { t } = useI18n();
  const {
    state,
    activeTab,
    openTab,
    closeTab,
    activateTab,
    history,
    bookmarks,
  } = useBrowserStore();
  const [query, setQuery] = useState("");
  const [copiedField, setCopiedField] = useState<"url" | "title" | null>(null);
  const [panelMode, setPanelMode] = useState<"tabs" | "history" | "bookmarks">(
    "tabs",
  );
  const filteredTabs = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return state.tabs;
    return state.tabs.filter((tab) =>
      `${tab.title} ${tab.url}`.toLowerCase().includes(needle),
    );
  }, [query, state.tabs]);
  const filteredHistory = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const items = history.slice(0, 30);
    if (!needle) return items;
    return items.filter((item) =>
      `${item.title} ${item.url}`.toLowerCase().includes(needle),
    );
  }, [history, query]);
  const filteredBookmarks = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return bookmarks;
    return bookmarks.filter((item) =>
      `${item.title} ${item.url}`.toLowerCase().includes(needle),
    );
  }, [bookmarks, query]);
  const panelCounts = {
    tabs: state.tabs.length,
    history: history.length,
    bookmarks: bookmarks.length,
  };
  const visibleItems =
    panelMode === "tabs"
      ? filteredTabs.length
      : panelMode === "history"
        ? filteredHistory.length
        : filteredBookmarks.length;
  const emptyLabel =
    query.trim().length > 0
      ? t.browser.empty.noMatch
      : panelMode === "tabs"
        ? t.browser.empty.noTabs
        : panelMode === "history"
          ? t.browser.empty.noRecent
          : t.browser.empty.noFavorites;
  const activeTabLabel =
    activeTab?.title || activeTab?.url || t.browser.defaultTabTitle;
  const activeTabUrl = activeTab?.url ?? "";
  const canCopyActiveUrl =
    activeTabUrl.length > 0 && !activeTabUrl.startsWith("octopus:");

  const copyText = useCallback(async (text: string, field: "url" | "title") => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      window.setTimeout(() => setCopiedField(null), 1200);
    } catch (e) {
      swallow(e);
    }
  }, []);

  const closeOtherTabs = useCallback(() => {
    if (!activeTab) return;
    state.tabs
      .filter((tab) => tab.id !== activeTab.id)
      .forEach((tab) => closeTab(tab.id));
  }, [activeTab, closeTab, state.tabs]);

  return (
    <div
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={cn(
        "absolute right-3 top-[6.75rem] z-[40] hidden h-[calc(100vh-7.5rem)] w-[280px] flex-col rounded-2xl bg-popover px-3 py-3 text-popover-foreground shadow-lg transition-[opacity,transform] duration-160 md:flex",
        open ? "pointer-events-auto" : "pointer-events-none",
      )}
      style={{
        opacity: open ? 1 : 0,
        transform: open ? "translateY(0)" : "translateY(-8px)",
      }}
    >
      <div
        className="flex h-11 w-full items-center gap-2 rounded-xl px-1"
        style={
          {
            WebkitAppRegion: "no-drag",
          } as React.CSSProperties
        }
      >
        <div className="grid size-7 place-items-center bg-muted text-foreground">
          <MenuIcon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">{t.browser.pageTitle}</div>
          <div className="text-mini text-muted-foreground">
            {t.browser.pageSubtitle(pinned)}
          </div>
        </div>
      </div>

      <div className="mt-4 flex h-9 items-center gap-2 rounded-full bg-muted px-3 text-xs text-muted-foreground">
        <SearchIcon className="size-4 shrink-0" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t.browser.searchPlaceholder}
          aria-label={t.browser.searchPlaceholder}
          className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-muted-foreground"
        />
      </div>

      {activeTab && (
        <div className="mt-3 rounded-2xl bg-card p-2.5">
          <div className="flex items-start gap-2">
            {activeTab.favicon ? (
              <img
                src={activeTab.favicon}
                alt=""
                className="mt-0.5 size-4 shrink-0 rounded-sm"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            ) : (
              <GlobeIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold text-foreground">
                {activeTabLabel}
              </div>
              <div className="mt-0.5 truncate text-mini text-muted-foreground">
                {activeTabUrl}
              </div>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-2 gap-1.5">
            <button
              type="button"
              disabled={!canCopyActiveUrl}
              onClick={() => copyText(activeTabUrl, "url")}
              className="flex h-8 items-center justify-center gap-1.5 rounded-lg bg-muted/60 px-2 text-mini font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-45"
            >
              <CopyIcon className="size-3.5" />
              {copiedField === "url"
                ? t.browser.copy.copied
                : t.browser.copy.link}
            </button>
            <button
              type="button"
              onClick={() => copyText(activeTabLabel, "title")}
              className="flex h-8 items-center justify-center gap-1.5 rounded-lg bg-muted/60 px-2 text-mini font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <CopyIcon className="size-3.5" />
              {copiedField === "title"
                ? t.browser.copy.copied
                : t.browser.copy.title}
            </button>
            <button
              type="button"
              onClick={() => openTab(activeTabUrl)}
              className="flex h-8 items-center justify-center gap-1.5 rounded-lg bg-muted/60 px-2 text-mini font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PlusIcon className="size-3.5" />
              {t.browser.copy.tabMenuItem}
            </button>
            <button
              type="button"
              disabled={state.tabs.length <= 1}
              onClick={closeOtherTabs}
              className="flex h-8 items-center justify-center gap-1.5 rounded-lg bg-muted/60 px-2 text-mini font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-45"
            >
              <XIcon className="size-3.5" />
              {t.browser.menu.closeOtherTabs}
            </button>
          </div>
        </div>
      )}

      <div className="mt-3 grid grid-cols-3 rounded-xl bg-muted p-1 text-mini font-medium text-muted-foreground">
        {[
          { id: "tabs", label: t.browser.tabs.label, icon: MenuIcon },
          { id: "history", label: t.browser.tabs.recent, icon: ClockIcon },
          { id: "bookmarks", label: t.browser.tabs.favorites, icon: StarIcon },
        ].map((item) => {
          const Icon = item.icon;
          const active = panelMode === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() =>
                setPanelMode(item.id as "tabs" | "history" | "bookmarks")
              }
              className={cn(
                "flex h-8 items-center justify-center gap-1 rounded-lg transition-colors",
                active
                  ? "bg-background text-foreground shadow-[var(--shadow-xs)]"
                  : "hover:bg-background/60 hover:text-foreground",
              )}
            >
              <Icon className="size-3.5" />
              <span>{item.label}</span>
              <span className="text-micro text-muted-foreground">
                {panelCounts[item.id as keyof typeof panelCounts]}
              </span>
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => openTab()}
        className="mt-3 flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-background/70"
      >
        <PlusIcon className="size-4" />
        {t.browser.newTab}
      </button>

      <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {panelMode === "tabs" &&
          filteredTabs.map((tab) => {
            const active = tab.id === state.activeId;
            return (
              <div
                key={tab.id}
                role="button"
                tabIndex={0}
                onClick={() => activateTab(tab.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    activateTab(tab.id);
                  }
                }}
                className={cn(
                  "group flex h-10 cursor-pointer items-center gap-2 rounded-xl px-2.5 text-sm transition-colors",
                  active
                    ? "bg-background text-foreground shadow-[var(--shadow-xs)] ring-1 ring-border-default"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
                )}
                title={tab.title || tab.url}
              >
                {tab.favicon ? (
                  <img
                    src={tab.favicon}
                    alt=""
                    className="size-4 shrink-0 rounded-sm"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />
                ) : (
                  <GlobeIcon className="size-4 shrink-0 opacity-70" />
                )}
                <span className="min-w-0 flex-1 truncate">
                  {tab.title || tab.url}
                </span>
                {tab.device !== "desktop" && (
                  <span className="rounded-full bg-muted px-1.5 py-0.5 text-micro uppercase text-muted-foreground">
                    {tab.device}
                  </span>
                )}
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    closeTab(tab.id);
                  }}
                  className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity hover:bg-foreground/10 hover:text-foreground group-hover:opacity-100 data-[active=true]:opacity-100"
                  data-active={active}
                  title={t.browser.closeTab}
                >
                  <XIcon className="size-3.5" />
                </button>
              </div>
            );
          })}
        {panelMode === "history" &&
          filteredHistory.map((item) => (
            <button
              key={`${item.url}-${item.visitedAt}`}
              type="button"
              onClick={() => openTab(item.url)}
              className="group flex h-11 w-full items-center gap-2 rounded-xl px-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-background/60 hover:text-foreground"
              title={item.title || item.url}
            >
              {item.favicon ? (
                <img
                  src={item.favicon}
                  alt=""
                  className="size-4 shrink-0 rounded-sm"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <ClockIcon className="size-4 shrink-0 opacity-70" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-foreground">
                  {item.title || item.url}
                </span>
                <span className="block truncate text-mini">{item.url}</span>
              </span>
            </button>
          ))}
        {panelMode === "bookmarks" &&
          filteredBookmarks.map((item) => (
            <button
              key={item.url}
              type="button"
              onClick={() => openTab(item.url)}
              className="group flex h-11 w-full items-center gap-2 rounded-xl px-2.5 text-left text-sm text-muted-foreground transition-colors hover:bg-background/60 hover:text-foreground"
              title={item.title || item.url}
            >
              {item.favicon ? (
                <img
                  src={item.favicon}
                  alt=""
                  className="size-4 shrink-0 rounded-sm"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <StarIcon className="size-4 shrink-0 text-warning" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-foreground">
                  {item.title || item.url}
                </span>
                <span className="block truncate text-mini">{item.url}</span>
              </span>
            </button>
          ))}
        {visibleItems === 0 && (
          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
            {emptyLabel}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => openTab()}
        className="mt-3 flex h-10 items-center justify-center gap-2 rounded-xl bg-muted text-sm font-medium text-foreground"
      >
        <PlusIcon className="size-4" />
        {t.browser.newTabPage}
      </button>
    </div>
  );
}

export default function BrowserPage() {
  // Implementation note.
  useEffect(() => {
    setAppMode("browser");
  }, []);
  return (
    <BrowserStoreProvider>
      <BrowserShell />
    </BrowserStoreProvider>
  );
}
