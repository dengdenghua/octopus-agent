import {
  ExternalLinkIcon,
  Globe2Icon,
  GripHorizontalIcon,
  Loader2Icon,
  MonitorIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import {
  type PointerEvent as ReactPointerEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { captureBrowserRelayPreview } from "@/core/browser/api";
import {
  captureComputerScreen,
  type AutomationTarget,
} from "@/core/computer/api";
import { useI18n } from "@/core/i18n/hooks";
import { BROWSER_WORKSPACE_ROUTE } from "@/core/workspace/sidebar-routing";
import { cn } from "@/lib/utils";

type AutomationPictureInPictureProps = {
  threadId: string;
  target: AutomationTarget;
  open: boolean;
  active: boolean;
  paused: boolean;
  relayConnected: boolean;
  stateLabel: string;
  onOpenChange: (open: boolean) => void;
};

type PreviewFrame = {
  dataUrl: string;
  sourceName?: string;
  matched?: boolean;
};

type Placement = {
  x: number;
  y: number;
  width: number;
  height: number;
};

const MIN_WIDTH = 300;
const MIN_HEIGHT = 196;
const EDGE_GAP = 14;

function placementKey(threadId: string) {
  return `octopus:automation-pip:${threadId || "new"}`;
}

function defaultPlacement(): Placement {
  const viewportWidth =
    typeof window === "undefined" ? 1280 : window.innerWidth;
  return {
    x: Math.max(EDGE_GAP, viewportWidth - 390),
    y: 66,
    width: 376,
    height: 244,
  };
}

function clampPlacement(next: Placement): Placement {
  if (typeof window === "undefined") return next;
  const width = Math.min(
    Math.max(next.width, MIN_WIDTH),
    window.innerWidth - EDGE_GAP * 2,
  );
  const height = Math.min(
    Math.max(next.height, MIN_HEIGHT),
    window.innerHeight - EDGE_GAP * 2,
  );
  return {
    width,
    height,
    x: Math.min(
      Math.max(EDGE_GAP, next.x),
      window.innerWidth - width - EDGE_GAP,
    ),
    y: Math.min(
      Math.max(EDGE_GAP, next.y),
      window.innerHeight - height - EDGE_GAP,
    ),
  };
}

function readPlacement(threadId: string): Placement {
  if (typeof window === "undefined") return defaultPlacement();
  try {
    const raw = window.localStorage.getItem(placementKey(threadId));
    if (!raw) return defaultPlacement();
    const value = JSON.parse(raw) as Partial<Placement>;
    if (
      ![value.x, value.y, value.width, value.height].every(
        (part) => typeof part === "number" && Number.isFinite(part),
      )
    ) {
      return defaultPlacement();
    }
    return clampPlacement(value as Placement);
  } catch {
    return defaultPlacement();
  }
}

async function capturePreviewFrame(
  threadId: string,
  target: AutomationTarget,
  relayConnected: boolean,
): Promise<PreviewFrame> {
  const nativeCapture = window.octopus?.desktop.captureAutomationPreview;
  if (nativeCapture) {
    const result = await nativeCapture({
      kind: target.kind,
      id: target.id,
      title: target.title,
      appId: target.app_id,
      appName: target.app_name,
      width: 960,
      height: 540,
    });
    if (!result.ok || !result.dataUrl) {
      throw new Error(result.error || "Unable to capture the selected window");
    }
    return {
      dataUrl: result.dataUrl,
      sourceName: result.sourceName,
      matched: result.matched,
    };
  }

  if (target.kind === "browser_tab") {
    if (!relayConnected) throw new Error("Browser relay is offline");
    return captureBrowserRelayPreview(target);
  }

  const result = await captureComputerScreen({
    controlSessionId: `thread:${threadId || "new"}`,
  });
  if (!result.ok || !result.data_url) {
    throw new Error(result.error || "Unable to capture the desktop");
  }
  return { dataUrl: result.data_url, matched: true };
}

export function AutomationPictureInPicture({
  threadId,
  target,
  open,
  active,
  paused,
  relayConnected,
  stateLabel,
  onOpenChange,
}: AutomationPictureInPictureProps) {
  const { t } = useI18n();
  const [placement, setPlacement] = useState<Placement>(() =>
    readPlacement(threadId),
  );
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const inFlightRef = useRef(false);
  const dragRef = useRef<{ offsetX: number; offsetY: number } | null>(null);

  const persistPlacement = useCallback(
    (next: Placement) => {
      try {
        window.localStorage.setItem(
          placementKey(threadId),
          JSON.stringify(next),
        );
      } catch {
        // Local storage can be unavailable in restricted renderer contexts.
      }
    },
    [threadId],
  );

  useEffect(() => {
    setPlacement(readPlacement(threadId));
    setFrame(null);
    setError(null);
  }, [target.id, threadId]);

  const refresh = useCallback(async () => {
    if (!open || inFlightRef.current || document.hidden) return;
    inFlightRef.current = true;
    setRefreshing(true);
    try {
      const next = await capturePreviewFrame(threadId, target, relayConnected);
      setFrame(next);
      setError(null);
    } catch (captureError) {
      setError(
        captureError instanceof Error
          ? captureError.message
          : String(captureError),
      );
    } finally {
      setRefreshing(false);
      inFlightRef.current = false;
    }
  }, [open, relayConnected, target, threadId]);

  useEffect(() => {
    if (!open) return;
    void refresh();
    const interval = window.setInterval(
      () => void refresh(),
      window.octopus?.isElectron ? 1200 : 2200,
    );
    const handleVisibility = () => {
      if (!document.hidden) void refresh();
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [open, refresh]);

  useEffect(() => {
    if (!open) return;
    const handleResize = () => {
      setPlacement((current) => {
        const next = clampPlacement(current);
        persistPlacement(next);
        return next;
      });
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [open, persistPlacement]);

  useEffect(() => {
    if (!open || typeof ResizeObserver === "undefined") return;
    const surface = surfaceRef.current;
    if (!surface) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const width = Math.round(entry.contentRect.width);
      const height = Math.round(entry.contentRect.height);
      setPlacement((current) => {
        if (current.width === width && current.height === height)
          return current;
        const next = clampPlacement({ ...current, width, height });
        persistPlacement(next);
        return next;
      });
    });
    observer.observe(surface);
    return () => observer.disconnect();
  }, [open, persistPlacement]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest("button"))
      return;
    const rect = surfaceRef.current?.getBoundingClientRect();
    if (!rect) return;
    dragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    setPlacement((current) =>
      clampPlacement({
        ...current,
        x: event.clientX - dragRef.current!.offsetX,
        y: event.clientY - dragRef.current!.offsetY,
      }),
    );
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
    setPlacement((current) => {
      const rightEdge = window.innerWidth - current.width - EDGE_GAP;
      const bottomEdge = window.innerHeight - current.height - EDGE_GAP;
      const next = clampPlacement({
        ...current,
        x:
          current.x < 42
            ? EDGE_GAP
            : current.x > rightEdge - 28
              ? rightEdge
              : current.x,
        y:
          current.y < 48
            ? EDGE_GAP
            : current.y > bottomEdge - 28
              ? bottomEdge
              : current.y,
      });
      persistPlacement(next);
      return next;
    });
  };

  const openFullView = () => {
    window.location.hash =
      target.kind === "browser_tab"
        ? BROWSER_WORKSPACE_ROUTE
        : "/workspace/computer";
  };

  if (!open || typeof document === "undefined") return null;

  return createPortal(
    <div
      ref={surfaceRef}
      data-testid="automation-picture-in-picture"
      className="fixed z-[80] flex min-h-[196px] min-w-[300px] resize flex-col overflow-hidden rounded-2xl border border-border/70 bg-background/96 shadow-[0_20px_64px_rgba(15,23,42,0.28)] backdrop-blur-xl"
      style={{
        left: placement.x,
        top: placement.y,
        width: placement.width,
        height: placement.height,
      }}
    >
      <div
        className="flex h-10 shrink-0 cursor-grab touch-none items-center gap-2 border-b border-border/70 px-2.5 active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        <GripHorizontalIcon className="size-3.5 shrink-0 text-muted-foreground/60" />
        {target.kind === "browser_tab" ? (
          <Globe2Icon className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <MonitorIcon className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium">{target.title}</div>
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
            <span
              className={cn(
                "size-1.5 rounded-full",
                paused
                  ? "bg-warning"
                  : active
                    ? "animate-pulse bg-success"
                    : "bg-muted-foreground/45",
              )}
            />
            <span className="truncate">
              {stateLabel} · {t.common.preview}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          className="grid size-7 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label={t.common.preview}
        >
          <RefreshCwIcon
            className={cn("size-3.5", refreshing && "animate-spin")}
          />
        </button>
        <button
          type="button"
          onClick={openFullView}
          className="grid size-7 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label={t.common.openInNewWindow}
        >
          <ExternalLinkIcon className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={() => onOpenChange(false)}
          className="grid size-7 place-items-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label={t.common.close}
        >
          <XIcon className="size-3.5" />
        </button>
      </div>

      <button
        type="button"
        onClick={openFullView}
        className="group relative min-h-0 flex-1 overflow-hidden bg-black/90 text-left"
        aria-label={t.common.openInNewWindow}
      >
        {frame ? (
          <img
            src={frame.dataUrl}
            alt={target.title}
            className="size-full object-contain"
            draggable={false}
          />
        ) : (
          <div className="grid size-full place-items-center text-xs text-white/60">
            <Loader2Icon className="size-5 animate-spin" />
          </div>
        )}
        {frame?.matched === false ? (
          <span className="absolute bottom-2 left-2 rounded-md bg-black/65 px-2 py-1 text-[10px] text-white/80">
            {frame.sourceName || target.title}
          </span>
        ) : null}
        {error ? (
          <div className="absolute inset-x-2 bottom-2 rounded-lg bg-black/72 px-2.5 py-1.5 text-[10px] text-white/85 backdrop-blur">
            {error}
          </div>
        ) : null}
      </button>
    </div>,
    document.body,
  );
}
