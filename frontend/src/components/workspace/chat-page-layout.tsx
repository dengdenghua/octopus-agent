import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { ErrorBoundary } from "@/components/ui/error-boundary";

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
const KEYBOARD_RESIZE_STEP_PX = 16;

function readStoredWidth(key: string): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const px = Number.parseInt(raw, 10);
    if (Number.isFinite(px)) {
      return px;
    }
  } catch (e) {
    swallow(e, "storage");
  }
  return null;
}

function readStoredSidebarWidth(): number | null {
  const px = readStoredWidth(SIDEBAR_WIDTH_KEY);
  if (px && px >= MIN_SIDEBAR_PX && px <= MAX_SIDEBAR_PX) return px;
  return null;
}

function readStoredSecondaryWidth(): number | null {
  const px = readStoredWidth(SECONDARY_PANEL_WIDTH_KEY);
  if (px && px >= MIN_SECONDARY_PX && px <= MAX_SECONDARY_PX) return px;
  return null;
}

function writeStoredWidth(key: string, px: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, String(px));
  } catch (e) {
    swallow(e, "storage");
  }
}

function writeStoredSidebarWidth(px: number): void {
  writeStoredWidth(SIDEBAR_WIDTH_KEY, px);
}

function writeStoredSecondaryWidth(px: number): void {
  writeStoredWidth(SECONDARY_PANEL_WIDTH_KEY, px);
}

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

/** Numeric estimate for the width strings resolveSidebarWidth produces
 *  ("min(300px, 36vw)", "420px", "26rem"). Used for aria-valuenow, keyboard
 *  resizing and viewport clamping before any dragged width is stored. */
function estimateCssWidthPx(css: string, viewportWidth: number): number | null {
  const terms =
    css.startsWith("min(") && css.endsWith(")")
      ? css.slice(4, -1).split(",")
      : [css];
  const values: number[] = [];
  for (const term of terms) {
    const m = term.trim().match(/^(\d+(?:\.\d+)?)(px|rem|vw)$/);
    if (!m) return null;
    const n = Number(m[1]);
    values.push(
      m[2] === "px" ? n : m[2] === "rem" ? n * 16 : (n / 100) * viewportWidth,
    );
  }
  return Math.min(...values);
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
  // Lazy init from localStorage so a previously-dragged width persists
  // across reloads / remounts (SSR-safe — returns null on the server).
  const [customWidth, setCustomWidth] = useState<number | null>(
    readStoredSidebarWidth,
  );
  const [secondaryCustomWidth, setSecondaryCustomWidth] = useState<number | null>(
    readStoredSecondaryWidth,
  );
  const [isNarrowViewport, setIsNarrowViewport] = useState(false);
  // Viewport width drives the panel clamps; re-clamped on window resize.
  // SSR renders unclamped (Infinity), the mount effect corrects it.
  const [viewportWidth, setViewportWidth] = useState<number>(() =>
    typeof window === "undefined" ? Number.POSITIVE_INFINITY : window.innerWidth,
  );
  const secondaryDefaultWidth = resolveSidebarWidth(secondaryPanelWidth);
  const sidebarOpen = Boolean(sidebar) && showSidebar && !isNarrowViewport;
  const secondaryOpen = Boolean(secondaryPanel) && !isNarrowViewport;
  // The sidebar is clamped first, reserving only the secondary panel's
  // minimum; the secondary panel then yields to the sidebar's actual width.
  // With both panels dragged wide, this keeps the chat column usable
  // instead of letting flex squeeze it to zero.
  const clampSidebarPx = (px: number) =>
    clampPanelWidth(
      px,
      MIN_SIDEBAR_PX,
      MAX_SIDEBAR_PX,
      viewportWidth,
      secondaryOpen ? MIN_SECONDARY_PX : 0,
    );
  const sidebarBasisPx =
    customWidth ?? estimateCssWidthPx(defaultWidth, viewportWidth);
  const sidebarPx = clampSidebarPx(sidebarBasisPx ?? MIN_SIDEBAR_PX);
  const clampSecondaryPx = (px: number) =>
    clampPanelWidth(
      px,
      MIN_SECONDARY_PX,
      MAX_SECONDARY_PX,
      viewportWidth,
      sidebarOpen ? sidebarPx : 0,
    );
  const secondaryBasisPx =
    secondaryCustomWidth ??
    estimateCssWidthPx(secondaryDefaultWidth, viewportWidth);
  const secondaryPx = clampSecondaryPx(secondaryBasisPx ?? MIN_SECONDARY_PX);
  // Render the clamped pixel width whenever a pixel basis exists — the raw
  // CSS default (e.g. "min(600px, 42vw)") bypasses the viewport clamp and
  // can squeeze the chat column below its minimum with both panels open.
  // The CSS string remains only for SSR (viewport unknown) or unparseable
  // width expressions.
  const resolvedWidth =
    sidebarBasisPx != null && Number.isFinite(viewportWidth)
      ? `${sidebarPx}px`
      : defaultWidth;
  const secondaryResolvedWidth =
    secondaryBasisPx != null && Number.isFinite(viewportWidth)
      ? `${secondaryPx}px`
      : secondaryDefaultWidth;
  const drawerWidth = isNarrowViewport
    ? "min(calc(100vw - 0.75rem), 420px)"
    : resolvedWidth;
  // The document-level drag listeners are registered once ([] deps); route
  // them through refs so they clamp against the current viewport state.
  const clampSidebarPxRef = useRef(clampSidebarPx);
  clampSidebarPxRef.current = clampSidebarPx;
  const clampSecondaryPxRef = useRef(clampSecondaryPx);
  clampSecondaryPxRef.current = clampSecondaryPx;

  // Resize drag handling. ``latest`` mirrors the most recent width in a ref
  // (the document-level mouseup listener captures a stale ``customWidth``
  // closure, so it persists from the ref instead).
  const resizeRef = useRef<{
    startX: number;
    startWidth: number;
    latest: number;
    raf: number | null;
  } | null>(null);

  const secondaryResizeRef = useRef<{
    startX: number;
    startWidth: number;
    latest: number;
    raf: number | null;
  } | null>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const aside = (e.target as HTMLElement).parentElement;
    if (!aside) return;
    const rect = aside.getBoundingClientRect();
    resizeRef.current = {
      startX: e.clientX,
      startWidth: rect.width,
      latest: rect.width,
      raf: null,
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const handleSecondaryMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const aside = (e.target as HTMLElement).parentElement;
    if (!aside) return;
    const rect = aside.getBoundingClientRect();
    secondaryResizeRef.current = {
      startX: e.clientX,
      startWidth: rect.width,
      latest: rect.width,
      raf: null,
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

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
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      // Right-docked panel with a left-edge handle: dragging left widens.
      const delta = resizeRef.current.startX - e.clientX;
      const newWidth = clampSidebarPxRef.current(
        resizeRef.current.startWidth + delta,
      );
      resizeRef.current.latest = newWidth;
      // Throttle React state updates to animation frames to avoid
      // triggering reconciliation on every mousemove event.
      if (!resizeRef.current.raf) {
        resizeRef.current.raf = requestAnimationFrame(() => {
          resizeRef.current!.raf = null;
          setCustomWidth(resizeRef.current!.latest);
        });
      }
    };

    const handleSecondaryMouseMove = (e: MouseEvent) => {
      if (!secondaryResizeRef.current) return;
      // Same geometry as the main sidebar: dragging left widens.
      const delta = secondaryResizeRef.current.startX - e.clientX;
      const newWidth = clampSecondaryPxRef.current(
        secondaryResizeRef.current.startWidth + delta,
      );
      secondaryResizeRef.current.latest = newWidth;
      if (!secondaryResizeRef.current.raf) {
        secondaryResizeRef.current.raf = requestAnimationFrame(() => {
          secondaryResizeRef.current!.raf = null;
          setSecondaryCustomWidth(secondaryResizeRef.current!.latest);
        });
      }
    };

    const handleMouseUp = () => {
      if (resizeRef.current) {
        // Flush any pending RAF update before persisting.
        if (resizeRef.current.raf) {
          cancelAnimationFrame(resizeRef.current.raf);
          resizeRef.current.raf = null;
          setCustomWidth(resizeRef.current.latest);
        }
        // Persist only at drag-end (not per mousemove) to avoid thrashing
        // localStorage.
        writeStoredSidebarWidth(resizeRef.current.latest);
        resizeRef.current = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };

    const handleSecondaryMouseUp = () => {
      if (secondaryResizeRef.current) {
        if (secondaryResizeRef.current.raf) {
          cancelAnimationFrame(secondaryResizeRef.current.raf);
          secondaryResizeRef.current.raf = null;
          setSecondaryCustomWidth(secondaryResizeRef.current.latest);
        }
        writeStoredSecondaryWidth(secondaryResizeRef.current.latest);
        secondaryResizeRef.current = null;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.addEventListener("mousemove", handleSecondaryMouseMove);
    document.addEventListener("mouseup", handleSecondaryMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.removeEventListener("mousemove", handleSecondaryMouseMove);
      document.removeEventListener("mouseup", handleSecondaryMouseUp);
    };
  }, []);

  // Left-edge handle on a right-docked panel: ArrowLeft moves the edge
  // left (wider), ArrowRight moves it right (narrower).
  const keyboardResizeDelta = (e: React.KeyboardEvent): number => {
    if (e.key === "ArrowLeft") return KEYBOARD_RESIZE_STEP_PX;
    if (e.key === "ArrowRight") return -KEYBOARD_RESIZE_STEP_PX;
    return 0;
  };

  const handleSidebarResizeKeyDown = (e: React.KeyboardEvent) => {
    const delta = keyboardResizeDelta(e);
    if (!delta) return;
    e.preventDefault();
    const next = clampSidebarPx(sidebarPx + delta);
    setCustomWidth(next);
    writeStoredSidebarWidth(next);
  };

  const handleSecondaryResizeKeyDown = (e: React.KeyboardEvent) => {
    const delta = keyboardResizeDelta(e);
    if (!delta) return;
    e.preventDefault();
    const next = clampSecondaryPx(secondaryPx + delta);
    setSecondaryCustomWidth(next);
    writeStoredSecondaryWidth(next);
  };

  return (
    <div className="flex h-full w-full min-h-0 flex-col overflow-hidden">
      <header
        className={cn(
          "flex h-11 shrink-0 items-center justify-between overflow-hidden pl-12 pr-3",
          isNewThread ? "border-b border-transparent" : "border-b border-border-subtle",
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
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center bg-gradient-to-t from-background via-background/92 to-transparent px-3 pb-3 pt-8">
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
                onMouseDown={handleMouseDown}
                onKeyDown={handleSidebarResizeKeyDown}
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
              onMouseDown={handleSecondaryMouseDown}
              onKeyDown={handleSecondaryResizeKeyDown}
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
              style={{ height: "min(72vh, 640px)" }}
              className="fixed right-0 bottom-0 left-0 z-50 flex flex-col overflow-hidden rounded-t-2xl border-t border-border-default bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] shadow-[0_-18px_42px_-24px_rgba(0,0,0,0.28)] backdrop-blur-[10px]"
            >
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
