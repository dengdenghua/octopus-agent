/* Implementation note. */

import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";
import { GlobeIcon, MenuIcon, PlusIcon, SearchIcon, XIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { CopilotPanel } from "@/components/browser/copilot-panel";
import { TabBar } from "@/components/browser/tab-bar";
import { UrlBar } from "@/components/browser/url-bar";
import { UnifiedStoreOverlay } from "@/components/store/unified-store";
import {
  BrowserStoreProvider,
  setAppMode,
  useBrowserStore,
} from "@/components/browser/browser-store";
import {
  WebviewTab,
  type WebviewTabHandle,
} from "@/components/browser/webview-tab";
import { WorkspaceSurfaceSwitch } from "@/components/workspace/workspace-sidebar";

const isWindows = (): boolean =>
  typeof navigator !== "undefined" && navigator.userAgent.includes("Windows");
const isMac = (): boolean =>
  typeof navigator !== "undefined" && navigator.userAgent.includes("Mac");

/* Implementation note. */
const ACTIVE_DEVICE_WIDTH = {
  desktop: 0,
  tablet: 768,
  mobile: 375,
} as const;

function BrowserShell() {
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
  const [storeOpen, setStoreOpen] = useState(false);
  const [sidePanelHovered, setSidePanelHovered] = useState(false);
  const [sidePanelPinned, setSidePanelPinned] = useState(false);
  const sidePanelCloseTimerRef = useRef<number | null>(null);
  const activeTabId = activeTab?.id ?? null;
  const activeTabUrl = activeTab?.url ?? "";
  const activeTabTitle = activeTab?.title ?? "";
  const activeTabFavicon = activeTab?.favicon;
  const activeTabLoading = activeTab?.isLoading ?? false;

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
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div
          className="flex h-12 shrink-0 items-center gap-2 border-b border-border/45 bg-sidebar/65 px-2 shadow-[inset_0_-1px_0_rgba(255,255,255,0.36)] backdrop-blur-2xl"
          style={
            {
              paddingLeft: isMac() ? 80 : 8,
              paddingRight: isWindows() ? 160 : 8,
              WebkitAppRegion: "drag",
            } as React.CSSProperties
          }
        >
          <div
            className="-ml-2 flex h-8 w-[209px] shrink-0 items-center justify-center"
            style={
              {
                WebkitAppRegion: "no-drag",
              } as React.CSSProperties
            }
          >
            <WorkspaceSurfaceSwitch active="browser" />
          </div>
          <div className="flex h-8 min-w-0 flex-1 items-center">
            <TabBar />
          </div>
          <button
            type="button"
            title={sidePanelPinned ? "取消固定标签工作区" : "展开标签工作区"}
            aria-label={
              sidePanelPinned ? "取消固定标签工作区" : "展开标签工作区"
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
              "grid size-8 shrink-0 place-items-center rounded-[14px] border border-border/55 bg-background/55 text-muted-foreground shadow-[inset_0_1px_1px_rgba(255,255,255,0.48),0_8px_22px_rgba(15,23,42,0.08)] transition-colors hover:bg-background/70 hover:text-foreground",
              sidePanelOpen && "bg-background text-foreground",
            )}
            style={
              {
                WebkitAppRegion: "no-drag",
              } as React.CSSProperties
            }
          >
            <MenuIcon className="size-4" />
          </button>
        </div>

        {/* URL bar */}
        <UrlBar
          webviewHandle={activeHandle}
          onOpenExtensions={() => setStoreOpen(true)}
        />

        {/* Implementation note. */}
        <div className="min-h-0 flex-1 p-3">
          <div className="flex h-full min-h-0 overflow-hidden rounded-xl border border-border/70 bg-background/95 shadow-[0_18px_48px_rgba(15,23,42,0.12)]">
            {state.copilotOpen && (
              <div
                className="flex min-h-0 border-r border-border/60 bg-background"
                style={{
                  // Implementation note.
                  flex:
                    activeDevice !== "desktop"
                      ? "1 1 0"
                      : `0 0 ${state.copilotWidth}px`,
                  minWidth: activeDevice !== "desktop" ? 280 : undefined,
                }}
              >
                <CopilotPanel webviewHandle={activeHandle} />
              </div>
            )}
            <div
              className="relative overflow-hidden bg-background"
              style={{
                // Implementation note.
                flex:
                  activeDevice !== "desktop"
                    ? `0 0 ${ACTIVE_DEVICE_WIDTH[activeDevice]}px`
                    : "1 1 0",
              }}
            >
              {state.tabs.map((tab) => (
                <WebviewTab
                  key={tab.id}
                  tab={tab}
                  active={tab.id === state.activeId}
                  onPatch={(patch) => patchTab(tab.id, patch)}
                  ref={(handle) => {
                    if (handle) {
                      handlesRef.current.set(tab.id, handle);
                      // Implementation note.
                      // Implementation note.
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
      <UnifiedStoreOverlay open={storeOpen} onOpenChange={setStoreOpen} />
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
  const { state, openTab, closeTab, activateTab } = useBrowserStore();

  return (
    <aside
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      className={cn(
        "absolute right-3 top-12 z-40 hidden h-[calc(100vh-4rem)] w-[280px] flex-col rounded-2xl border border-white/60 bg-[linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--muted))_100%)] px-3 py-3 shadow-[0_24px_70px_rgba(15,23,42,0.20)] backdrop-blur-xl transition-[opacity,transform] duration-160 md:flex",
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
        <div className="grid size-7 place-items-center rounded-lg bg-background/80 text-foreground shadow-sm ring-1 ring-border/60">
          <MenuIcon className="size-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">浏览器</div>
          <div className="text-[11px] text-muted-foreground">
            标签工作区{pinned ? " · 已固定" : ""}
          </div>
        </div>
      </div>

      <div className="mt-4 flex h-9 items-center gap-2 rounded-full bg-background/72 px-3 text-xs text-muted-foreground shadow-sm ring-1 ring-border/50">
        <SearchIcon className="size-4 shrink-0" />
        <span className="truncate">搜索标签页...</span>
      </div>

      <button
        type="button"
        onClick={() => openTab()}
        className="mt-3 flex h-9 items-center gap-2 rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-background/70"
      >
        <PlusIcon className="size-4" />
        新标签页
      </button>

      <div className="mt-2 min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {state.tabs.map((tab) => {
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
                  ? "bg-background text-foreground shadow-sm ring-1 ring-border/60"
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
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  closeTab(tab.id);
                }}
                className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground/70 opacity-0 transition-opacity hover:bg-foreground/10 hover:text-foreground group-hover:opacity-100 data-[active=true]:opacity-100"
                data-active={active}
                title="关闭标签页"
              >
                <XIcon className="size-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => openTab()}
        className="mt-3 flex h-10 items-center justify-center gap-2 rounded-xl border border-border/60 bg-background/72 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-background"
      >
        <PlusIcon className="size-4" />
        新建标签页
      </button>
    </aside>
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
