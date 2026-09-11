import {
  ChevronDownIcon,
  MessageCircleIcon,
  Maximize2Icon,
  Minimize2Icon,
} from "lucide-react";
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
import { useElectronTitleBar } from "@/components/electron-title-bar";
import { useResizablePanel } from "./use-resizable-panel";
import { createPortal } from "react-dom";
import { WorkbenchHeaderSlot } from "./workbench-header-slot";

// Resized drawer width is persisted so it survives reloads / remounts.
const SIDEBAR_WIDTH_KEY = "octopus:chatSidebarWidth";
const SECONDARY_PANEL_WIDTH_KEY = "octopus:chatSecondaryPanelWidth";
const MIN_SIDEBAR_PX = 280;
const MAX_SIDEBAR_PX = 800;
const MIN_SECONDARY_PX = 360;
const MAX_SECONDARY_PX = 800;
// Usable width the chat column must keep when panels are open. This is measured
// against ChatPageLayout's own container (after the global navigation), not the
// browser viewport, so a wide window cannot hide an already-cramped workspace.
const MIN_CHAT_COLUMN_PX = 620;

/** Clamp a panel width to its absolute range AND to the container, keeping
 *  MIN_CHAT_COLUMN_PX for the chat column plus ``reservedPx`` for the other
 *  open panel. The min floor wins over the container cap: when the workbench
 *  cannot fit it switches to overlay mode instead. */
function clampPanelWidth(
  px: number,
  minPx: number,
  maxPx: number,
  containerWidth: number,
  reservedPx: number,
): number {
  const containerCap = containerWidth - MIN_CHAT_COLUMN_PX - reservedPx;
  return Math.max(minPx, Math.min(px, maxPx, containerCap));
}

interface ChatPageLayoutProps {
  layoutKey?: string;
  composerNeedsAttention?: boolean;
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
  /** Invoked when a secondary overlay backdrop is tapped. */
  onSecondaryClose?: () => void;
}

export function ChatPageLayout({
  layoutKey,
  composerNeedsAttention = false,
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
  const [workbenchHeaderSlot, setWorkbenchHeaderSlot] =
    useState<HTMLDivElement | null>(null);
  const { controlsSide } = useElectronTitleBar();
  // Backwards compat: old callers pass Tailwind classes like "lg:w-72" or
  // "lg:w-[44rem]". Extract the pixel/rem value so we can drive inline
  // width (which animates) instead of fighting breakpoint classes.
  const defaultWidth = resolveSidebarWidth(sidebarWidth);
  const [isNarrowViewport, setIsNarrowViewport] = useState(false);
  const [contentFullWidth, setContentFullWidth] = useState(false);
  const [composerCompact, setComposerCompact] = useState(false);
  const [snapPreview, setSnapPreview] = useState(false);
  const composingRef = useRef(false);
  const compactButtonRef = useRef<HTMLButtonElement>(null);
  const composerExpanded = !composerCompact || composerNeedsAttention;
  const fullWorkbench =
    contentFullWidth && Boolean(secondaryPanel) && !isNarrowViewport;
  const layoutPreferenceKey = `echo:workbench-layout:${isNewThread ? "new" : (layoutKey ?? "default")}`;
  const layoutSnapshot = useRef({ contentFullWidth, composerCompact });
  layoutSnapshot.current = { contentFullWidth, composerCompact };
  useEffect(() => {
    try {
      const saved = JSON.parse(
        sessionStorage.getItem(layoutPreferenceKey) || "{}",
      );
      setContentFullWidth(saved.contentFullWidth === true);
      setComposerCompact(saved.composerCompact === true);
    } catch {
      setContentFullWidth(false);
      setComposerCompact(false);
    }
    return () => {
      try {
        sessionStorage.setItem(
          layoutPreferenceKey,
          JSON.stringify(layoutSnapshot.current),
        );
      } catch {
        /* Optional preference. */
      }
    };
  }, [layoutPreferenceKey]);
  // Mobile workbench drawer opens in a collapsed "peek" state and
  // only grows to its full 72vh height after an explicit tap / swipe-up on
  // the grab handle, so the first open doesn't take over the screen.
  const [mobileDrawerExpanded, setMobileDrawerExpanded] = useState(false);
  const [drawerDragDelta, setDrawerDragDelta] = useState(0);
  const drawerDragRef = useRef<{ startY: number } | null>(null);
  const drawerSuppressClickRef = useRef(false);
  const secondaryOverlayRef = useRef<HTMLElement>(null);
  const previousFocusedElementRef = useRef<HTMLElement | null>(null);
  const previousOverlayPresentationRef = useRef<
    "desktop-drawer" | "bottom-sheet" | null
  >(null);
  const layoutRootRef = useRef<HTMLDivElement>(null);
  // The component's actual available width drives panel clamps and the
  // workbench presentation. SSR renders unclamped (Infinity); the mount
  // measurement corrects it without consulting window.innerWidth.
  const [containerWidth, setContainerWidth] = useState(
    Number.POSITIVE_INFINITY,
  );
  const [inputOverlayHeight, setInputOverlayHeight] = useState(0);
  const inputOverlayRef = useRef<HTMLDivElement>(null);
  const secondaryDefaultWidth = resolveSidebarWidth(secondaryPanelWidth);
  const sidebarOpen = Boolean(sidebar) && showSidebar && !isNarrowViewport;
  // Keep the workbench inline whenever its minimum width and the chat's target
  // width actually fit. An open utility panel contributes its own minimum;
  // below that exact threshold only the workbench moves into the drawer.
  const inlineWorkbenchMinimumWidth =
    MIN_CHAT_COLUMN_PX + MIN_SECONDARY_PX + (sidebarOpen ? MIN_SIDEBAR_PX : 0);
  const isWorkbenchOverlayViewport =
    isNarrowViewport ||
    (Number.isFinite(containerWidth) &&
      containerWidth < inlineWorkbenchMinimumWidth);
  const secondaryOverlayPresentation =
    secondaryPanel && isWorkbenchOverlayViewport && !fullWorkbench
      ? isNarrowViewport
        ? ("bottom-sheet" as const)
        : ("desktop-drawer" as const)
      : null;
  const secondaryModalOpen = secondaryOverlayPresentation !== null;
  const secondaryOpen = Boolean(secondaryPanel) && !isWorkbenchOverlayViewport;
  // The sidebar is clamped first, reserving only the secondary panel's
  // minimum; the secondary panel then yields to the sidebar's actual width.
  // With both panels dragged wide, this keeps the chat column usable
  // instead of letting flex squeeze it to zero.
  const sidebarPanel = useResizablePanel({
    storageKey: SIDEBAR_WIDTH_KEY,
    minPx: MIN_SIDEBAR_PX,
    maxPx: MAX_SIDEBAR_PX,
    defaultCssWidth: defaultWidth,
    viewportWidth: containerWidth,
    clamp: (px) =>
      clampPanelWidth(
        px,
        MIN_SIDEBAR_PX,
        MAX_SIDEBAR_PX,
        containerWidth,
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
    viewportWidth: containerWidth,
    clamp: (px) =>
      clampPanelWidth(
        px,
        MIN_SECONDARY_PX,
        MAX_SECONDARY_PX,
        containerWidth,
        sidebarOpen ? sidebarPx : 0,
      ),
    fallbackPx: MIN_SECONDARY_PX,
    onDragMove: (width) =>
      setSnapPreview(
        Number.isFinite(containerWidth) && width >= containerWidth - 160,
      ),
    onDragEnd: (width) => {
      setSnapPreview(false);
      if (Number.isFinite(containerWidth) && width >= containerWidth - 160) {
        setContentFullWidth(true);
        return true;
      }
      return false;
    },
  });
  const secondaryPx = secondaryPanelCtrl.resolvedPx;
  // Render the clamped pixel width whenever a pixel basis exists — the raw
  // CSS default (e.g. "min(600px, 42vw)") bypasses the container clamp and
  // can squeeze the chat column below its minimum with both panels open.
  // The CSS string remains only for SSR (container unknown) or unparseable
  // width expressions.
  const resolvedWidth =
    sidebarPanel.basisPx != null && Number.isFinite(containerWidth)
      ? `${sidebarPx}px`
      : defaultWidth;
  const secondaryResolvedWidth =
    secondaryPanelCtrl.basisPx != null && Number.isFinite(containerWidth)
      ? `${secondaryPx}px`
      : secondaryDefaultWidth;
  // A desktop fit failure uses a full-height drawer inside this layout. Keep
  // the user's stored/default basis where possible; unlike an inline panel it
  // overlays the conversation, so it does not need the 620px chat clamp.
  const desktopOverlayWidth = Number.isFinite(containerWidth)
    ? `${Math.min(
        Math.max(
          secondaryPanelCtrl.basisPx ?? MIN_SECONDARY_PX,
          MIN_SECONDARY_PX,
        ),
        MAX_SECONDARY_PX,
        Math.max(0, containerWidth - 12),
      )}px`
    : secondaryDefaultWidth;
  const drawerWidth = isNarrowViewport
    ? "min(calc(100vw - 0.75rem), 420px)"
    : resolvedWidth;

  useEffect(() => {
    const update = () => {
      setIsNarrowViewport(window.innerWidth < 768);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    const node = layoutRootRef.current;
    if (!node) return;

    const measure = () => {
      const nextWidth = Math.floor(node.getBoundingClientRect().width);
      // A temporarily hidden ancestor can report zero. Preserve the last real
      // measurement so panels do not flash into overlay while routes animate.
      if (nextWidth <= 0) return;
      setContainerWidth((current) =>
        current === nextWidth ? current : nextWidth,
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

  useEffect(() => {
    const node = inputOverlayRef.current;
    if (!node) return;

    const measure = () => {
      const nextHeight = Math.ceil(node.getBoundingClientRect().height);
      if (nextHeight <= 0) return;
      setInputOverlayHeight((current) => {
        // Font rasterisation and fractional layout can make ResizeObserver
        // alternate by one pixel while scrolling. That moves the spacer and
        // floating controls on every observation and looks like the UI is
        // breathing. Ignore that noise while still accepting real composer,
        // approval, or todo expansion changes immediately.
        if (current > 0 && Math.abs(current - nextHeight) <= 1) return current;
        return nextHeight;
      });
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

  // Re-opening the drawer (or leaving the mobile viewport) always starts
  // from the collapsed peek height.
  useEffect(() => {
    if (!secondaryPanel || !isNarrowViewport) {
      setMobileDrawerExpanded(false);
      setDrawerDragDelta(0);
    }
  }, [secondaryPanel, isNarrowViewport]);

  const restoreSecondaryOverlayFocus = useCallback(() => {
    const previous = previousFocusedElementRef.current;
    previousFocusedElementRef.current = null;
    if (previous?.isConnected && previous !== document.body) {
      previous.focus({ preventScroll: true });
    } else {
      // A responsive transition may remove the original desktop trigger.
      // Return to the surviving composer instead of stranding focus on body.
      const input = inputOverlayRef.current?.querySelector<HTMLElement>(
        'textarea, [contenteditable="true"], input',
      );
      if (input?.isConnected) input.focus({ preventScroll: true });
    }
  }, []);

  // Treat overlay presentations as a single modal session. Focus is moved
  // only when the overlay first opens or changes presentation, so ordinary
  // panel renders never pull focus away from controls the user is operating.
  useEffect(() => {
    const previousPresentation = previousOverlayPresentationRef.current;

    if (secondaryOverlayPresentation) {
      if (!previousPresentation) {
        previousFocusedElementRef.current =
          document.activeElement instanceof HTMLElement
            ? document.activeElement
            : null;
      }
      previousOverlayPresentationRef.current = secondaryOverlayPresentation;
      secondaryOverlayRef.current?.focus({ preventScroll: true });
      return;
    }

    if (previousPresentation) {
      previousOverlayPresentationRef.current = null;
      if (fullWorkbench) {
        previousFocusedElementRef.current = null;
      } else {
        restoreSecondaryOverlayFocus();
      }
    }
  }, [
    secondaryOverlayPresentation,
    fullWorkbench,
    restoreSecondaryOverlayFocus,
  ]);

  // Restore focus even if the whole layout unmounts while its overlay is
  // open (for example during route navigation).
  useEffect(
    () => () => {
      if (previousOverlayPresentationRef.current) {
        previousOverlayPresentationRef.current = null;
        restoreSecondaryOverlayFocus();
      }
    },
    [restoreSecondaryOverlayFocus],
  );

  useEffect(() => {
    if (!secondaryModalOpen || !onSecondaryClose) return;

    const handleEscape = (event: KeyboardEvent) => {
      if (
        event.key !== "Escape" ||
        event.defaultPrevented ||
        escapeBelongsToNestedControl(event.target)
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      onSecondaryClose();
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onSecondaryClose, secondaryModalOpen]);

  // Removing the active utility/tab can leave focus on <body> without changing
  // the drawer presentation. Recover in that case on the next parent render,
  // while allowing Radix portals (menus/listboxes) to retain their own focus.
  useEffect(() => {
    if (!secondaryModalOpen) return;

    const overlay = secondaryOverlayRef.current;
    const active = document.activeElement;
    if (!overlay || !(active instanceof HTMLElement)) {
      overlay?.focus({ preventScroll: true });
      return;
    }
    if (isRadixPortalFocus(active)) return;

    const focusWasLost =
      active === document.body ||
      !active.isConnected ||
      active.closest("[inert]") !== null;
    if (focusWasLost) {
      overlay.focus({ preventScroll: true });
    }
  });

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
    <div
      ref={layoutRootRef}
      onPointerDownCapture={(event) => {
        if (!fullWorkbench || composerNeedsAttention || composingRef.current)
          return;
        if (
          !(event.target instanceof Element) ||
          !event.target.closest("aside")
        )
          return;
        const editor = inputOverlayRef.current?.querySelector<HTMLElement>(
          'textarea, [contenteditable="true"], input',
        );
        const draft =
          editor instanceof HTMLTextAreaElement ||
          editor instanceof HTMLInputElement
            ? editor.value
            : editor?.textContent;
        if (!draft?.trim()) setComposerCompact(true);
      }}
      data-chat-page-layout-root="true"
      data-workspace-layout={fullWorkbench ? "content-full" : "split"}
      className="relative flex h-full w-full min-h-0 overflow-hidden"
    >
      {snapPreview && (
        <div
          data-workbench-snap-preview="true"
          className="pointer-events-none absolute inset-1 z-[80] rounded-xl border-2 border-primary/40 bg-primary/5"
        >
          <span className="absolute top-4 left-1/2 -translate-x-1/2 rounded-full bg-background px-4 py-2 text-sm shadow-sm">
            {t.sidebar.expandWorkbench}
          </span>
        </div>
      )}
      <div
        data-chat-page-main-column="true"
        aria-hidden={secondaryModalOpen ? true : undefined}
        inert={secondaryModalOpen ? true : undefined}
        className={cn(
          "flex min-h-0 min-w-0 flex-1 flex-col",
          fullWorkbench
            ? "pointer-events-none absolute inset-0 z-[60]"
            : "relative overflow-hidden",
        )}
      >
        <header
          data-chat-page-header="true"
          hidden={fullWorkbench}
          inert={fullWorkbench || undefined}
          className={cn(
            "flex h-11 shrink-0 items-center justify-between overflow-hidden pl-12 pr-3",
            isNewThread
              ? "border-b border-transparent"
              : "border-b border-border-subtle",
            "bg-background/80 backdrop-blur-lg",
            fullWorkbench && "!hidden",
            headerClassName,
          )}
          style={
            {
              paddingRight:
                controlsSide === "right" && !secondaryPanel && !sidebarOpen
                  ? "calc(var(--window-controls-safe-inset, 138px) + 0.75rem)"
                  : undefined,
              WebkitAppRegion: controlsSide === "right" ? "drag" : undefined,
            } as CSSProperties
          }
        >
          <div
            className="flex min-w-0 flex-1 items-center"
            style={
              controlsSide === "right"
                ? ({ WebkitAppRegion: "no-drag" } as CSSProperties)
                : undefined
            }
          >
            {header}
          </div>
        </header>
        <section
          role="region"
          aria-label={t.sidebar.ariaChatWorkspace}
          className={cn(
            "relative flex min-h-0 flex-1 flex-col overscroll-none",
            !fullWorkbench && "overflow-hidden",
          )}
          style={
            {
              "--chat-input-overlay-height": `${inputOverlayHeight || 160}px`,
            } as CSSProperties
          }
        >
          {pageTitle && <h1 className="sr-only">{pageTitle}</h1>}
          {modeSwitcher && !fullWorkbench && (
            <div className="pointer-events-auto absolute top-2 left-1/2 z-50 -translate-x-1/2">
              {modeSwitcher}
            </div>
          )}
          <div
            aria-hidden={fullWorkbench || undefined}
            inert={fullWorkbench || undefined}
            className={cn(
              "flex size-full min-w-0 flex-col items-center overflow-hidden",
              fullWorkbench && "invisible",
            )}
          >
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
            data-composer-placement={fullWorkbench ? "floating" : "docked"}
            data-composer-state={
              fullWorkbench && !composerExpanded ? "compact" : "expanded"
            }
            className={cn(
              "absolute right-0 bottom-0 left-0 z-30 flex justify-center px-3 pb-3",
              fullWorkbench
                ? "pointer-events-none mx-auto w-full max-w-[760px] flex-col items-center gap-2 pb-6 pt-3 [&>*]:pointer-events-auto [&_[data-composer-context-strip]]:hidden [&_[data-composer-welcome]]:hidden [&_[data-composer-start]]:!translate-y-0"
                : "bg-gradient-to-t from-background via-background/92 to-transparent pt-8",
            )}
          >
            {fullWorkbench && !composerExpanded && (
              <button
                ref={compactButtonRef}
                type="button"
                className="flex h-12 w-56 items-center justify-center gap-3 rounded-full border border-border-subtle bg-background/95 text-sm text-muted-foreground shadow-lg backdrop-blur-xl transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  setComposerCompact(false);
                  requestAnimationFrame(() => {
                    inputOverlayRef.current
                      ?.querySelector<HTMLElement>(
                        'textarea, [contenteditable="true"], input',
                      )
                      ?.focus({ preventScroll: true });
                  });
                }}
              >
                <MessageCircleIcon className="size-4" />
                {t.sidebar.showComposer}
              </button>
            )}
            <div
              className={cn(
                "w-full min-w-0",
                fullWorkbench && !composerExpanded && "hidden",
                fullWorkbench &&
                  "rounded-3xl drop-shadow-[0_4px_16px_rgba(0,0,0,0.04)]",
              )}
              hidden={fullWorkbench && !composerExpanded}
              inert={(fullWorkbench && !composerExpanded) || undefined}
              onCompositionStartCapture={() => {
                composingRef.current = true;
              }}
              onCompositionEndCapture={() => {
                composingRef.current = false;
              }}
            >
              {fullWorkbench && composerExpanded && (
                <div className="flex justify-end px-2 pb-1">
                  <button
                    type="button"
                    disabled={composerNeedsAttention}
                    aria-label={t.sidebar.compactComposer}
                    title={t.sidebar.compactComposer}
                    className="rounded-full border border-border-subtle bg-background/95 p-1.5 text-muted-foreground shadow-sm hover:bg-muted disabled:opacity-40"
                    onClick={() => {
                      if (composingRef.current) return;
                      setComposerCompact(true);
                      requestAnimationFrame(() =>
                        compactButtonRef.current?.focus({
                          preventScroll: true,
                        }),
                      );
                    }}
                  >
                    <ChevronDownIcon className="size-4" />
                  </button>
                </div>
              )}
              <ErrorBoundary>{inputArea}</ErrorBoundary>
            </div>
          </div>
        </section>
      </div>
      {sidebar && (
        <aside
          aria-hidden={secondaryModalOpen || fullWorkbench || !showSidebar}
          inert={secondaryModalOpen || fullWorkbench ? true : undefined}
          aria-label={t.sidebar.ariaUtilityPanel}
          style={
            isNarrowViewport
              ? { height: "min(58vh, 520px)", width: "100%" }
              : { width: showSidebar ? drawerWidth : 0 }
          }
          className={cn(
            "relative z-20 flex flex-col overflow-hidden",
            fullWorkbench && "!hidden",
            isNarrowViewport
              ? cn(
                  "fixed right-0 bottom-0 left-0 z-40 rounded-t-2xl border-t border-border-default bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)] pt-0 shadow-[0_-18px_42px_-24px_rgba(0,0,0,0.28)] backdrop-blur-[10px]",
                  showSidebar
                    ? "translate-y-0 opacity-100"
                    : "translate-y-full opacity-0 pointer-events-none",
                )
              : cn(
                  "flex-shrink-0 border-l bg-background",
                  showSidebar
                    ? "border-border-default opacity-100"
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
          ref={secondaryOverlayRef}
          data-secondary-panel-presentation={
            fullWorkbench
              ? "full"
              : isWorkbenchOverlayViewport
                ? "desktop-drawer"
                : "inline"
          }
          role={secondaryModalOpen ? "dialog" : undefined}
          aria-modal={secondaryModalOpen || undefined}
          tabIndex={-1}
          aria-label={t.sidebar.ariaAgentWorkbench}
          style={{
            width: fullWorkbench
              ? "100%"
              : isWorkbenchOverlayViewport
                ? desktopOverlayWidth
                : secondaryResolvedWidth,
          }}
          className={cn(
            "flex flex-shrink-0 flex-col overflow-hidden border-border-default bg-background opacity-100",
            fullWorkbench
              ? "absolute inset-0 z-20"
              : isWorkbenchOverlayViewport
                ? "absolute inset-y-0 right-0 z-50 border-l shadow-xl"
                : "relative z-20 border-l",
          )}
        >
          <div
            role="separator"
            aria-orientation="vertical"
            tabIndex={0}
            hidden={fullWorkbench || isWorkbenchOverlayViewport}
            aria-valuenow={Math.round(secondaryPx)}
            aria-valuemin={MIN_SECONDARY_PX}
            aria-valuemax={MAX_SECONDARY_PX}
            onMouseDown={secondaryPanelCtrl.handleMouseDown}
            onKeyDown={secondaryPanelCtrl.handleKeyDown}
            className="absolute top-0 left-0 bottom-0 z-30 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50 focus-visible:bg-primary/50 focus-visible:outline-none"
            aria-label={t.sidebar.ariaResizeWorkbench}
          />
          {workbenchHeaderSlot ? (
            createPortal(
              <button
                type="button"
                aria-label={
                  fullWorkbench
                    ? t.sidebar.restoreWorkbenchSplit
                    : t.sidebar.expandWorkbench
                }
                title={
                  fullWorkbench
                    ? t.sidebar.restoreWorkbenchSplit
                    : t.sidebar.expandWorkbench
                }
                aria-pressed={fullWorkbench}
                onClick={() => setContentFullWidth((value) => !value)}
                className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/45 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {fullWorkbench ? (
                  <Minimize2Icon aria-hidden="true" className="size-3.5" />
                ) : (
                  <Maximize2Icon aria-hidden="true" className="size-3.5" />
                )}
              </button>,
              workbenchHeaderSlot,
            )
          ) : (
            <div className="flex h-8 shrink-0 items-center justify-end border-b border-border/60 px-2">
              <button
                type="button"
                aria-pressed={fullWorkbench}
                onClick={() => setContentFullWidth((value) => !value)}
                className="inline-flex h-6 items-center gap-1.5 rounded px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {fullWorkbench ? (
                  <Minimize2Icon aria-hidden="true" className="size-3" />
                ) : (
                  <Maximize2Icon aria-hidden="true" className="size-3" />
                )}
                {fullWorkbench
                  ? t.sidebar.restoreWorkbenchSplit
                  : t.sidebar.expandWorkbench}
              </button>
            </div>
          )}
          <WorkbenchHeaderSlot.Provider value={setWorkbenchHeaderSlot}>
            <ErrorBoundary>{secondaryPanel}</ErrorBoundary>
          </WorkbenchHeaderSlot.Provider>
        </aside>
      )}
      {secondaryModalOpen && !isNarrowViewport && (
        <div
          data-secondary-panel-backdrop="desktop-drawer"
          aria-hidden="true"
          onClick={onSecondaryClose}
          className={cn(
            "absolute inset-0 z-40 bg-black/30",
            onSecondaryClose && "cursor-pointer",
          )}
        />
      )}
      {secondaryPanel && isNarrowViewport && (
        <>
          {/* The compact viewport keeps the peek/expand sheet interaction. */}
          <div
            data-secondary-panel-backdrop="bottom-sheet"
            aria-hidden="true"
            onClick={onSecondaryClose}
            className={cn(
              "fixed inset-0 z-40 bg-black/40",
              onSecondaryClose && "cursor-pointer",
            )}
          />
          <aside
            ref={secondaryOverlayRef}
            data-secondary-panel-presentation="bottom-sheet"
            role="dialog"
            aria-modal="true"
            aria-label={t.sidebar.ariaAgentWorkbench}
            tabIndex={-1}
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

function escapeBelongsToNestedControl(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return Boolean(
    target.closest(
      'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="menu"], [role="menubar"], [role="listbox"], [role="combobox"]',
    ),
  );
}

function isRadixPortalFocus(element: HTMLElement): boolean {
  return Boolean(
    element.closest(
      '[data-radix-portal], [data-radix-popper-content-wrapper], [role="menu"], [role="listbox"]',
    ),
  );
}
