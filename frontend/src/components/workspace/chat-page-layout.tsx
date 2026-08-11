import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { useResizablePanel } from "./use-resizable-panel";

// Resized drawer width is persisted so it survives reloads / remounts.
const SIDEBAR_WIDTH_KEY = "octopus:chatSidebarWidth";
const SECONDARY_PANEL_WIDTH_KEY = "octopus:chatSecondaryPanelWidth";
const MIN_SIDEBAR_PX = 280;
const MAX_SIDEBAR_PX = 800;
const MIN_SECONDARY_PX = 320;
const MAX_SECONDARY_PX = 900;
// Usable width the chat column must keep when panels are open; panel
// widths restored from storage on a smaller viewport are clamped to this.
const MIN_CHAT_COLUMN_PX = 360;

/** Clamp a panel width to its absolute range AND to the viewport, keeping
 *  MIN_CHAT_COLUMN_PX for the chat column plus ``reservedPx`` for the other
 *  open panel. The min floor wins over the viewport cap: on viewports too
 *  small to fit everything the <768px overlay mode takes over anyway. */
function clampPanelWidth(
  px: number,
  minPx: number,
  maxPx: number,
  viewportWidth: number,
  reservedPx: number,
): number {
  const viewportCap = viewportWidth - MIN_CHAT_COLUMN_PX - reservedPx;
  return Math.max(minPx, Math.min(px, maxPx, viewportCap));
}

interface ChatPageLayoutProps {
  header: ReactNode;
  modeSwitcher?: ReactNode;
  messageList: ReactNode;
  inputArea: ReactNode;
  sidebar?: ReactNode;
  secondaryPanel?: ReactNode;
  isNewThread?: boolean;
  pageTitle?: string;
  messageListClassName?: string;
  headerClassName?: string;
  showSidebar?: boolean;
  sidebarWidth?: string;
  secondaryPanelWidth?: string;
  /** Invoked when the narrow-viewport secondary overlay backdrop is tapped. */
  onSecondaryClose?: () => void;
}

export function ChatPageLayout({
  header,
  modeSwitcher,
  messageList,
  inputArea,
  sidebar,
  secondaryPanel,
  isNewThread = false,
  pageTitle,
  messageListClassName,
  headerClassName,
  showSidebar = false,
  sidebarWidth = "min(300px, 36vw)",
  secondaryPanelWidth = "min(420px, 36vw)",
  onSecondaryClose,
}: ChatPageLayoutProps) {
  const { t } = useI18n();
  // Backwards compat: old callers pass Tailwind classes like "lg:w-72" or
  // "lg:w-[44rem]". Extract the pixel/rem value so we can drive inline
  // width (which animates) instead of fighting breakpoint classes.
  const defaultWidth = resolveSidebarWidth(sidebarWidth);
  const [isNarrowViewport, setIsNarrowViewport] = useState(false);
  // Narrow-viewport workbench drawer opens in a collapsed "peek" state and
  // only grows to its full 72vh height after an explicit tap / swipe-up on
  // the grab handle, so the first open doesn't take over the screen.
  const [mobileDrawerExpanded, setMobileDrawerExpanded] = useState(false);
  const [drawerDragDelta, setDrawerDragDelta] = useState(0);
  const drawerDragRef = useRef<{ startY: number } | null>(null);
  const drawerSuppressClickRef = useRef(false);
  // Viewport width drives the panel clamps; re-clamped on window resize.
  // SSR renders unclamped (Infinity), the mount effect corrects it.
  const [viewportWidth, setViewportWidth] = useState<number>(() =>
    typeof window === "undefined"
      ? Number.POSITIVE_INFINITY
      : window.innerWidth,
  );
  const [inputOverlayHeight, setInputOverlayHeight] = useState(0);
  const inputOverlayRef = useRef<HTMLDivElement>(null);
  const secondaryDefaultWidth = resolveSidebarWidth(secondaryPanelWidth);
  const sidebarOpen = Boolean(sidebar) && showSidebar && !isNarrowViewport;
  const secondaryOpen = Boolean(secondaryPanel) && !isNarrowViewport;
  // The sidebar is clamped first, reserving only the secondary panel's
  // minimum; the secondary panel then yields to the sidebar's actual width.
  // With both panels dragged wide, this keeps the chat column usable
  // instead of letting flex squeeze it to zero.
  const sidebarPanel = useResizablePanel({
    storageKey: SIDEBAR_WIDTH_KEY,
    minPx: MIN_SIDEBAR_PX,
    maxPx: MAX_SIDEBAR_PX,
    defaultCssWidth: defaultWidth,
    viewportWidth,
    clamp: (px) =>
      clampPanelWidth(
        px,
        MIN_SIDEBAR_PX,
        MAX_SIDEBAR_PX,
        viewportWidth,
        secondaryOpen ? MIN_SECONDARY_PX : 0,
      ),
    fallbackPx: MIN_SIDEBAR_PX,
  });
  const sidebarPx = sidebarPanel.resolvedPx;
  const secondaryPanelCtrl = useResizablePanel({
    storageKey: SECONDARY_PANEL_WIDTH_KEY,
    minPx: MIN_SECONDARY_PX,
    maxPx: MAX_SECONDARY_PX,
    defaultCssWidth: secondaryDefaultWidth,
    viewportWidth,
    clamp: (px) =>
      clampPanelWidth(
        px,
        MIN_SECONDARY_PX,
        MAX_SECONDARY_PX,
        viewportWidth,
        sidebarOpen ? sidebarPx : 0,
      ),
    fallbackPx: MIN_SECONDARY_PX,
  });
  const secondaryPx = secondaryPanelCtrl.resolvedPx;
  // Render the clamped pixel width whenever a pixel basis exists — the raw
  // CSS default (e.g. "min(600px, 42vw)") bypasses the viewport clamp and
  // can squeeze the chat column below its minimum with both panels open.
  // The CSS string remains only for SSR (viewport unknown) or unparseable
  // width expressions.
  const resolvedWidth =
    sidebarPanel.basisPx != null && Number.isFinite(viewportWidth)
      ? `${sidebarPx}px`
      : defaultWidth;
  const secondaryResolvedWidth =
    secondaryPanelCtrl.basisPx != null && Number.isFinite(viewportWidth)
      ? `${secondaryPx}px`
      : secondaryDefaultWidth;
  const drawerWidth = isNarrowViewport
    ? "min(calc(100vw - 0.75rem), 420px)"
    : resolvedWidth;

  useEffect(() => {
    const update = () => {
      setIsNarrowViewport(window.innerWidth < 768);
      setViewportWidth(window.innerWidth);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    const node = inputOverlayRef.current;
    if (!node) return;

    const measure = () => {
      const nextHeight = Math.ceil(node.getBoundingClientRect().height);
      if (nextHeight <= 0) return;
      setInputOverlayHeight((current) =>
        current === nextHeight ? current : nextHeight,
      );
    };

    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }

    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  // Re-opening the drawer (or leaving the narrow viewport) always starts
  // from the collapsed peek height.
  useEffect(() => {
    if (!secondaryPanel || !isNarrowViewport) {
      setMobileDrawerExpanded(false);
      setDrawerDragDelta(0);
    }
  }, [secondaryPanel, isNarrowViewport]);

  // Grab-handle gestures: a tap toggles, a swipe up expands, a swipe down
  // collapses. Pointer capture keeps the gesture on the handle even if the
  // finger leaves its bounds mid-drag.
  const handleDrawerGrabStart = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      drawerDragRef.current = { startY: e.clientY };
    },
    [],
  );

  const handleDrawerGrabMove = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      if (!drawerDragRef.current) return;
      setDrawerDragDelta(e.clientY - drawerDragRef.current.startY);
    },
    [],
  );

  const handleDrawerGrabEnd = useCallback(
    (e: React.PointerEvent<HTMLButtonElement>) => {
      const drag = drawerDragRef.current;
      drawerDragRef.current = null;
      setDrawerDragDelta(0);
      if (!drag) return;
      const delta = e.clientY - drag.startY;
      if (delta < -40) {
        // A real swipe also fires a click on release; suppress it so the
        // gesture isn't immediately undone by the toggle.
        drawerSuppressClickRef.current = true;
        setMobileDrawerExpanded(true);
      } else if (delta > 40) {
        drawerSuppressClickRef.current = true;
        setMobileDrawerExpanded(false);
      }
    },
    [],
  );

  const handleDrawerHandleClick = useCallback(() => {
    if (drawerSuppressClickRef.current) {
      drawerSuppressClickRef.current = false;
      return;
    }
    setMobileDrawerExpanded((v) => !v);
  }, []);

  return (
    <div className="flex h-full w-full min-h-0 flex-col overflow-hidden">
      <header
        className={cn(
          "flex h-11 shrink-0 items-center justify-between overflow-hidden pl-12 pr-3",
          isNewThread
            ? "border-b border-transparent"
            : "border-b border-border-subtle",
          "bg-background/80 backdrop-blur-lg",
          headerClassName,
        )}
      >
        {header}
      </header>
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          <section
            role="region"
            aria-label={t.sidebar.ariaChatWorkspace}
            className="relative flex min-h-0 flex-1 flex-col overflow-hidden overscroll-none"
            style={
              {
                "--chat-input-overlay-height": `${inputOverlayHeight || 160}px`,
              } as CSSProperties
            }
          >
            {pageTitle && <h1 className="sr-only">{pageTitle}</h1>}
            {modeSwitcher && (
              <div className="pointer-events-auto absolute top-2 left-1/2 z-50 -translate-x-1/2">
                {modeSwitcher}
              </div>
            )}
            <div className="flex size-full min-w-0 flex-col items-center overflow-hidden">
              <div
                className={cn(
                  "w-full min-w-0 overflow-hidden",
                  messageListClassName,
                )}
              >
                <ErrorBoundary>{messageList}</ErrorBoundary>
              </div>
            </div>
            <div
              ref={inputOverlayRef}
              data-chat-input-overlay="true"
              className="absolute right-0 bottom-0 left-0 z-30 flex justify-center bg-gradient-to-t from-background via-background/92 to-transparent px-3 pb-3 pt-8"
            >
              <ErrorBoundary>{inputArea}</ErrorBoundary>
            </div>
          </section>
        </div>
        {sidebar && (
          <aside
            aria-hidden={!showSidebar}
            aria-label={t.sidebar.ariaUtilityPanel}
            style={
              isNarrowViewport
                ? { height: "min(58vh, 520px)", width: "100%" }
                : { width: showSidebar ? drawerWidth : 0 }
            }
            className={cn(
              "relative z-20 flex flex-col overflow-hidden bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] backdrop-blur-[10px]",
              isNarrowViewport
                ? cn(
                    "fixed right-0 bottom-0 left-0 z-40 rounded-t-2xl border-t border-border-default pt-0 shadow-[0_-18px_42px_-24px_rgba(0,0,0,0.28)]",
                    showSidebar
                      ? "translate-y-0 opacity-100"
                      : "translate-y-full opacity-0 pointer-events-none",
                  )
                : cn(
                    "flex-shrink-0 border-l",
                    showSidebar
                      ? "border-border-default opacity-100 shadow-[-12px_0_32px_-16px_rgba(0,0,0,0.12)]"
                      : "border-transparent opacity-0 pointer-events-none",
                  ),
            )}
          >
            {!isNarrowViewport && (
              <div
                role="separator"
                aria-orientation="vertical"
                tabIndex={0}
                aria-valuenow={Math.round(sidebarPx)}
                aria-valuemin={MIN_SIDEBAR_PX}
                aria-valuemax={MAX_SIDEBAR_PX}
                onMouseDown={sidebarPanel.handleMouseDown}
                onKeyDown={sidebarPanel.handleKeyDown}
                className={cn(
                  "absolute top-0 left-0 bottom-0 z-30 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50 focus-visible:bg-primary/50 focus-visible:outline-none",
                  showSidebar ? "pointer-events-auto" : "pointer-events-none",
                )}
                aria-label={t.sidebar.ariaResizeSidebar}
              />
            )}
            <ErrorBoundary>{sidebar}</ErrorBoundary>
          </aside>
        )}
        {secondaryPanel && !isNarrowViewport && (
          <aside
            aria-label={t.sidebar.ariaAgentWorkbench}
            style={{ width: secondaryResolvedWidth }}
            className={cn(
              "relative z-20 flex flex-col overflow-hidden bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] backdrop-blur-[10px]",
              "flex-shrink-0 border-l border-border-default opacity-100 shadow-[-12px_0_32px_-16px_rgba(0,0,0,0.12)]",
            )}
          >
            <div
              role="separator"
              aria-orientation="vertical"
              tabIndex={0}
              aria-valuenow={Math.round(secondaryPx)}
              aria-valuemin={MIN_SECONDARY_PX}
              aria-valuemax={MAX_SECONDARY_PX}
              onMouseDown={secondaryPanelCtrl.handleMouseDown}
              onKeyDown={secondaryPanelCtrl.handleKeyDown}
              className="absolute top-0 left-0 bottom-0 z-30 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50 focus-visible:bg-primary/50 focus-visible:outline-none"
              aria-label={t.sidebar.ariaResizeWorkbench}
            />
            <ErrorBoundary>{secondaryPanel}</ErrorBoundary>
          </aside>
        )}
        {secondaryPanel && isNarrowViewport && (
          <>
            {/* Backdrop keeps the overlay dismissible without relying on
                controls inside the panel; taps close via onSecondaryClose. */}
            <div
              aria-hidden="true"
              onClick={onSecondaryClose}
              className={cn(
                "fixed inset-0 z-40 bg-black/40",
                onSecondaryClose && "cursor-pointer",
              )}
            />
            <aside
              aria-label={t.sidebar.ariaAgentWorkbench}
              style={{
                height: mobileDrawerExpanded
                  ? "min(72vh, 640px)"
                  : "min(30vh, 280px)",
                transform: drawerDragDelta
                  ? `translateY(${drawerDragDelta}px)`
                  : undefined,
                transition: drawerDragDelta ? "none" : undefined,
              }}
              className="fixed right-0 bottom-0 left-0 z-50 flex flex-col overflow-hidden rounded-t-2xl border-t border-border-default bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] shadow-[0_-18px_42px_-24px_rgba(0,0,0,0.28)] backdrop-blur-[10px] transition-[height,transform] duration-slow ease-out"
            >
              <button
                type="button"
                aria-expanded={mobileDrawerExpanded}
                aria-label={t.sidebar.ariaToggleWorkbenchDrawer}
                onClick={handleDrawerHandleClick}
                onPointerDown={handleDrawerGrabStart}
                onPointerMove={handleDrawerGrabMove}
                onPointerUp={handleDrawerGrabEnd}
                onPointerCancel={handleDrawerGrabEnd}
                className="flex h-7 w-full shrink-0 cursor-grab touch-none items-center justify-center active:cursor-grabbing"
              >
                <span
                  className={cn(
                    "h-1 rounded-full bg-muted-foreground/30 transition-[width] duration-slow",
                    mobileDrawerExpanded ? "w-14" : "w-10",
                  )}
                />
              </button>
              <ErrorBoundary>{secondaryPanel}</ErrorBoundary>
            </aside>
          </>
        )}
      </div>
    </div>
  );
}

/** Map legacy sidebarWidth Tailwind prop values to concrete CSS widths.
 *  Existing callers pass strings like "lg:w-72" / "lg:w-[44rem]"; we
 *  translate those to the underlying rem/px so the overlay drawer can
 *  animate via inline width.  Falls through if the prop is already a
 *  valid CSS length (e.g. "min(380px, 42vw)"). */
function resolveSidebarWidth(raw: string): string {
  if (/[()]|vw|%/.test(raw)) return raw;

  const m = raw.match(/w-(?:\[(.+?)\]|(\d+))/);
  let px: string;
  if (m) {
    if (m[1]) px = m[1];
    else if (m[2]) px = `${Number(m[2]) * 0.25}rem`;
    else px = raw;
  } else {
    px = raw;
  }
  // Cap at 40vw so the drawer stays narrow — it's an overlay, so the
  // main column must still be the primary reading surface underneath.
  return `min(${px}, 40vw)`;
}
