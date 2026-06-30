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

// Resized drawer width is persisted so it survives reloads / remounts.
const SIDEBAR_WIDTH_KEY = "octopus:chatSidebarWidth";
const MIN_SIDEBAR_PX = 280;
const MAX_SIDEBAR_PX = 800;

function readStoredSidebarWidth(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (!raw) return null;
    const px = Number.parseInt(raw, 10);
    if (Number.isFinite(px) && px >= MIN_SIDEBAR_PX && px <= MAX_SIDEBAR_PX) {
      return px;
    }
  } catch (e) {
    swallow(e, "storage");
  }
  return null;
}

function writeStoredSidebarWidth(px: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(px));
  } catch (e) {
    swallow(e, "storage");
  }
}

interface ChatPageLayoutProps {
  header: ReactNode;
  modeSwitcher?: ReactNode;
  messageList: ReactNode;
  inputArea: ReactNode;
  sidebar?: ReactNode;
  secondaryPanel?: ReactNode;
  isNewThread?: boolean;
  messageListClassName?: string;
  headerClassName?: string;
  showSidebar?: boolean;
  sidebarWidth?: string;
}

export function ChatPageLayout({
  header,
  modeSwitcher,
  messageList,
  inputArea,
  sidebar,
  secondaryPanel,
  isNewThread = false,
  messageListClassName,
  headerClassName,
  showSidebar = false,
  sidebarWidth = "min(300px, 36vw)",
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
  const [isNarrowViewport, setIsNarrowViewport] = useState(false);
  const resolvedWidth = customWidth ? `${customWidth}px` : defaultWidth;
  const drawerWidth = isNarrowViewport
    ? "min(calc(100vw - 0.75rem), 420px)"
    : resolvedWidth;
  const shouldOffsetMain = Boolean(sidebar && showSidebar && !isNarrowViewport);

  // Resize drag handling. ``latest`` mirrors the most recent width in a ref
  // (the document-level mouseup listener captures a stale ``customWidth``
  // closure, so it persists from the ref instead).
  const resizeRef = useRef<{
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

  useEffect(() => {
    const update = () => setIsNarrowViewport(window.innerWidth < 768);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const delta = resizeRef.current.startX - e.clientX;
      const newWidth = Math.max(
        MIN_SIDEBAR_PX,
        Math.min(MAX_SIDEBAR_PX, resizeRef.current.startWidth + delta),
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

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);
  return (
    <div className="relative flex size-full min-h-0 flex-col overflow-hidden">
      <div className="relative flex min-h-0 flex-1">
        <header
          className={cn(
            "absolute top-0 right-0 left-0 z-30 flex h-11 shrink-0 items-center justify-between overflow-hidden pl-12 pr-3",
            isNewThread
              ? "border-b border-border/20"
              : "border-b border-border/30",
            "bg-background/80 backdrop-blur-lg",
            headerClassName,
          )}
        >
          {header}
        </header>
        <div
          className="relative flex min-h-0 max-w-full grow overflow-hidden transition-[margin-right] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]"
          style={{
            marginRight: shouldOffsetMain ? resolvedWidth : "0px",
          }}
        >
          <main className="relative flex min-h-0 max-w-full grow flex-col overflow-hidden overscroll-none">
            {modeSwitcher && (
              <div className="pointer-events-auto absolute top-2 left-1/2 z-50 -translate-x-1/2">
                {modeSwitcher}
              </div>
            )}
            <div className="flex size-full min-w-0 flex-col items-center overflow-hidden">
              <div
                className={cn(
                  "w-full min-w-0 overflow-hidden",
                  !isNewThread && "pt-11",
                  messageListClassName,
                )}
              >
                {messageList}
              </div>
            </div>
            <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center bg-gradient-to-t from-background via-background/92 to-transparent px-3 pb-3 pt-8">
              {inputArea}
            </div>
          </main>
          {secondaryPanel}
        </div>
        {sidebar && (
          <aside
            aria-hidden={!showSidebar}
            style={
              isNarrowViewport
                ? { height: "min(58vh, 520px)", width: "100%" }
                : { width: drawerWidth }
            }
            className={cn(
              // Overlay drawer from the right, same language as the
              // artifact drawer in ChatBox — slides in regardless of
              // viewport width, with frosted glass + left shadow edge.
              "absolute z-20 flex flex-col overflow-hidden",
              "bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] backdrop-blur-[10px]",
              "transition-[transform,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
              isNarrowViewport
                ? cn(
                    "right-0 bottom-0 left-0 z-40 rounded-t-2xl border-t border-border/60 pt-0 shadow-[0_-18px_42px_-24px_rgba(0,0,0,0.28)]",
                    showSidebar
                      ? "translate-y-0 opacity-100"
                      : "translate-y-full opacity-0 pointer-events-none",
                  )
                : cn(
                    "top-0 right-0 bottom-0 z-20 border-l border-border/60 pt-11 shadow-[-12px_0_32px_-16px_rgba(0,0,0,0.12)]",
                    showSidebar
                      ? "translate-x-0 opacity-100"
                      : "translate-x-full opacity-0 pointer-events-none",
                  ),
            )}
          >
            {/* Resize handle on left edge */}
            {!isNarrowViewport && (
              <div
                onMouseDown={handleMouseDown}
                className="absolute top-0 left-0 bottom-0 z-30 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50"
                aria-label={t.sidebar.ariaResizeSidebar}
              />
            )}
            {sidebar}
          </aside>
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
