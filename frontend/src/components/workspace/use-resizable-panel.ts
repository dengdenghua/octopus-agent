import { useCallback, useEffect, useRef, useState } from "react";

import { swallow } from "@/core/utils/log";

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

function writeStoredWidth(key: string, px: number): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, String(px));
  } catch (e) {
    swallow(e, "storage");
  }
}

function readStoredWidthInRange(
  key: string,
  minPx: number,
  maxPx: number,
): number | null {
  const px = readStoredWidth(key);
  if (px && px >= minPx && px <= maxPx) return px;
  return null;
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

export interface UseResizablePanelOptions {
  /** localStorage key used to persist the dragged width. */
  storageKey: string;
  minPx: number;
  maxPx: number;
  /** The CSS width string (e.g. "min(300px, 36vw)") used as a fallback
   *  before any width has been dragged. */
  defaultCssWidth: string;
  /** Current viewport width; drives responsive clamps. */
  viewportWidth: number;
  /** Clamp a candidate width against the absolute range AND the viewport,
   *  reserving room for the other open panel. Re-created each render with
   *  the latest viewport / sibling-panel state. */
  clamp: (px: number) => number;
  /** Fallback px used when no stored width and the CSS default is unparseable. */
  fallbackPx: number;
  /** Return true to handle a drag as a layout transition and retain its prior width. */
  onDragMove?: (unclampedWidth: number) => void;
  onDragEnd?: (unclampedWidth: number) => boolean;
}

export interface ResizablePanelController {
  /** Numeric basis before clamping (stored width or parsed CSS default). */
  basisPx: number | null;
  /** Clamped width used for rendering / aria-valuenow. */
  resolvedPx: number;
  handleMouseDown: (e: React.MouseEvent) => void;
  handleKeyDown: (e: React.KeyboardEvent) => void;
}

/** Shared drag / keyboard resize handling for horizontally-resizable panels
 *  (the chat sidebar and the secondary workbench). Lazy-loads the persisted
 *  width from localStorage, throttles drag state updates to animation frames,
 *  flushes + persists on drag-end, and restores the body cursor/user-select.
 *  Viewport clamping is delegated to the caller via ``clamp`` so sibling-panel
 *  dependencies stay in the component. */
export function useResizablePanel({
  storageKey,
  minPx,
  maxPx,
  defaultCssWidth,
  viewportWidth,
  clamp,
  fallbackPx,
  onDragEnd,
  onDragMove,
}: UseResizablePanelOptions): ResizablePanelController {
  // Lazy init from localStorage so a previously-dragged width persists
  // across reloads / remounts (SSR-safe — returns null on the server).
  const [customWidth, setCustomWidth] = useState<number | null>(() =>
    readStoredWidthInRange(storageKey, minPx, maxPx),
  );
  const basisPx =
    customWidth ?? estimateCssWidthPx(defaultCssWidth, viewportWidth);
  const resolvedPx = clamp(basisPx ?? fallbackPx);

  // The document-level drag listeners are registered once ([] deps); route
  // them through a ref so they clamp against the current viewport state.
  const clampRef = useRef(clamp);
  clampRef.current = clamp;
  const onDragMoveRef = useRef(onDragMove);
  onDragMoveRef.current = onDragMove;
  const onDragEndRef = useRef(onDragEnd);
  onDragEndRef.current = onDragEnd;
  const customWidthRef = useRef(customWidth);
  customWidthRef.current = customWidth;

  // Resize drag handling. ``latest`` mirrors the most recent width in a ref
  // (the document-level mouseup listener captures a stale closure, so it
  // persists from the ref instead).
  const resizeRef = useRef<{
    startX: number;
    startWidth: number;
    latest: number;
    rawWidth: number;
    priorWidth: number | null;
    priorCursor: string;
    priorUserSelect: string;
    raf: number | null;
  } | null>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0 || resizeRef.current) return;
    e.preventDefault();
    const aside = (e.target as HTMLElement).parentElement;
    if (!aside) return;
    const rect = aside.getBoundingClientRect();
    resizeRef.current = {
      startX: e.clientX,
      startWidth: rect.width,
      latest: rect.width,
      rawWidth: rect.width,
      priorWidth: customWidthRef.current,
      priorCursor: document.body.style.cursor,
      priorUserSelect: document.body.style.userSelect,
      raf: null,
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      // Right-docked panel with a left-edge handle: dragging left widens.
      const delta = resizeRef.current.startX - e.clientX;
      resizeRef.current.rawWidth = resizeRef.current.startWidth + delta;
      onDragMoveRef.current?.(resizeRef.current.rawWidth);
      const newWidth = clampRef.current(resizeRef.current.rawWidth);
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
        if (onDragEndRef.current?.(resizeRef.current.rawWidth)) {
          setCustomWidth(resizeRef.current.priorWidth);
        } else {
          writeStoredWidth(storageKey, resizeRef.current.latest);
        }
        document.body.style.cursor = resizeRef.current.priorCursor;
        document.body.style.userSelect = resizeRef.current.priorUserSelect;
        resizeRef.current = null;
      }
    };

    const cancelDrag = () => {
      const drag = resizeRef.current;
      if (!drag) return;
      if (drag.raf) cancelAnimationFrame(drag.raf);
      setCustomWidth(drag.priorWidth);
      onDragMoveRef.current?.(drag.startWidth);
      document.body.style.cursor = drag.priorCursor;
      document.body.style.userSelect = drag.priorUserSelect;
      resizeRef.current = null;
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !resizeRef.current) return;
      event.preventDefault();
      cancelDrag();
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    document.addEventListener("keydown", handleEscape);
    window.addEventListener("blur", cancelDrag);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.removeEventListener("keydown", handleEscape);
      window.removeEventListener("blur", cancelDrag);
      if (resizeRef.current) {
        if (resizeRef.current.raf) cancelAnimationFrame(resizeRef.current.raf);
        document.body.style.cursor = resizeRef.current.priorCursor;
        document.body.style.userSelect = resizeRef.current.priorUserSelect;
        resizeRef.current = null;
      }
    };
  }, [storageKey]);

  // Left-edge handle on a right-docked panel: ArrowLeft moves the edge
  // left (wider), ArrowRight moves it right (narrower).
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const delta =
        e.key === "ArrowLeft"
          ? KEYBOARD_RESIZE_STEP_PX
          : e.key === "ArrowRight"
            ? -KEYBOARD_RESIZE_STEP_PX
            : 0;
      if (!delta) return;
      e.preventDefault();
      const next = clamp(resolvedPx + delta);
      setCustomWidth(next);
      writeStoredWidth(storageKey, next);
    },
    [clamp, resolvedPx, storageKey],
  );

  return { basisPx, resolvedPx, handleMouseDown, handleKeyDown };
}
