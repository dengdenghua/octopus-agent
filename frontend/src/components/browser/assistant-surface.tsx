import {
  useEffect,
  useRef,
  useState,
  createContext,
  useContext,
  useId,
  type ReactNode,
  type PointerEvent,
} from "react";
import {
  GripHorizontal,
  MessageSquare,
  Minus,
  PanelsTopLeft,
  PanelRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

type Bounds = { width: number; height: number };
type Placement = Bounds & { right: number; bottom: number };
const AssistantPresentation = createContext<{
  compact: boolean;
  expanded: boolean;
  setExpanded: (value: boolean) => void;
  controls: ReactNode;
  dragHandle: ReactNode;
  contentId: string;
} | null>(null);
export const useAssistantPresentation = () => useContext(AssistantPresentation);
export function fitAssistant(bounds: Bounds, placement: Placement): Placement {
  const width = Math.min(
    Math.max(320, placement.width),
    Math.max(0, bounds.width - 24),
  );
  const height = Math.min(
    Math.max(320, placement.height),
    Math.max(0, bounds.height - 24),
  );
  return {
    width,
    height,
    right: Math.max(12, Math.min(placement.right, bounds.width - width - 12)),
    bottom: Math.max(
      12,
      Math.min(placement.bottom, bounds.height - height - 12),
    ),
  };
}

/** One mounted conversation; only its presentation changes. */
export function AssistantSurface({
  open,
  onOpenChange,
  dockWidth,
  onDockWidthChange,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dockWidth: number;
  onDockWidthChange: (width: number) => void;
  children: ReactNode;
}) {
  const root = useRef<HTMLElement>(null);
  const [activated, setActivated] = useState(open);
  const [floating, setFloating] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const contentId = useId();
  const [bounds, setBounds] = useState<Bounds>({ width: 1000, height: 700 });
  const [placement, setPlacement] = useState<Placement>({
    width: 736,
    height: 520,
    right: 16,
    bottom: 16,
  });
  const [dragging, setDragging] = useState(false);
  const [positioned, setPositioned] = useState(false);
  const gesture = useRef<{
    x: number;
    y: number;
    placement: Placement;
    resize: boolean;
  } | null>(null);
  const dockGesture = useRef<{ x: number; width: number } | null>(null);
  const restoreButton = useRef<HTMLButtonElement>(null);
  const titleBar = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(open);
  const narrow = bounds.width < 720;
  const overlay = floating || narrow;
  const collapsed = overlay && !expanded;
  const fitted = fitAssistant(bounds, {
    ...placement,
    right: positioned ? placement.right : (bounds.width - placement.width) / 2,
  });
  useEffect(() => {
    if (open) setActivated(true);
  }, [open]);
  useEffect(() => {
    if (open && !wasOpen.current)
      root.current?.querySelector("textarea")?.focus();
    if (!open && wasOpen.current) restoreButton.current?.focus();
    wasOpen.current = open;
  }, [open]);
  useEffect(() => {
    const host = root.current?.parentElement;
    if (!host) return;
    const measure = () => {
      const r = host.getBoundingClientRect();
      setBounds({ width: r.width, height: r.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(host);
    return () => observer.disconnect();
  }, []);
  const start = (event: PointerEvent<HTMLElement>, resize = false) => {
    if (!overlay || narrow || event.button !== 0) return;
    if (!resize && (event.target as HTMLElement).closest("button")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    gesture.current = {
      x: event.clientX,
      y: event.clientY,
      placement: fitted,
      resize,
    };
    setDragging(true);
  };
  const move = (event: PointerEvent<HTMLElement>) => {
    const g = gesture.current;
    if (!g) return;
    const dx = event.clientX - g.x,
      dy = event.clientY - g.y;
    setPositioned(true);
    setPlacement(
      fitAssistant(
        bounds,
        g.resize
          ? {
              ...g.placement,
              width: g.placement.width - dx,
              height: g.placement.height - dy,
            }
          : {
              ...g.placement,
              right: g.placement.right - dx,
              bottom: g.placement.bottom - dy,
            },
      ),
    );
  };
  const end = () => {
    gesture.current = null;
    dockGesture.current = null;
    setDragging(false);
  };
  const controls = (
    <div className="flex shrink-0 items-center gap-0.5">
      {!narrow && (
        <button
          type="button"
          aria-label="停靠到右侧"
          title="停靠到右侧"
          onClick={() => setFloating(false)}
          className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        >
          <PanelRight className="size-4" />
        </button>
      )}
      <button
        type="button"
        aria-label="收起聊天"
        title="收起聊天，任务继续运行"
        onClick={() => onOpenChange(false)}
        className="grid size-9 place-items-center rounded-lg text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Minus className="size-4" />
      </button>
    </div>
  );
  const dragHandle = !narrow ? (
    <div
      tabIndex={0}
      aria-label="拖动聊天窗口，方向键移动"
      className="grid h-9 w-5 shrink-0 cursor-grab touch-none place-items-center rounded text-muted-foreground/60 focus-visible:ring-2 focus-visible:ring-ring"
      onPointerDown={start}
      onPointerMove={move}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onKeyDown={(event) => {
        if (!event.key.startsWith("Arrow")) return;
        event.preventDefault();
        setPositioned(true);
        setPlacement(
          fitAssistant(bounds, {
            ...fitted,
            right:
              fitted.right +
              (event.key === "ArrowLeft"
                ? 20
                : event.key === "ArrowRight"
                  ? -20
                  : 0),
            bottom:
              fitted.bottom +
              (event.key === "ArrowUp"
                ? 20
                : event.key === "ArrowDown"
                  ? -20
                  : 0),
          }),
        );
      }}
    >
      <GripHorizontal className="size-4" />
    </div>
  ) : null;
  return (
    <>
      {dragging && <div className="absolute inset-0 z-40" aria-hidden="true" />}
      <aside
        ref={root}
        aria-label="浏览器助手"
        data-presentation={narrow ? "sheet" : floating ? "floating" : "docked"}
        data-expanded={!collapsed}
        className={cn(
          "min-h-0 min-w-0 flex-col text-foreground",
          overlay
            ? "absolute z-50"
            : "relative shrink-0 border-l border-border-subtle bg-background",
        )}
        style={{
          display: open ? "flex" : "none",
          ...(overlay
            ? {
                width: narrow ? Math.max(0, bounds.width - 24) : fitted.width,
                height: collapsed
                  ? 78
                  : narrow
                    ? Math.max(0, Math.min(640, bounds.height - 24))
                    : fitted.height,
                right: narrow ? 12 : fitted.right,
                bottom: narrow ? 12 : fitted.bottom,
              }
            : {
                width: Math.min(dockWidth, bounds.width * 0.48),
                height: "100%",
              }),
        }}
      >
        {!overlay && (
          <div
            role="separator"
            aria-label="调整聊天栏宽度"
            aria-orientation="vertical"
            tabIndex={0}
            aria-valuenow={Math.round(Math.min(dockWidth, bounds.width * 0.48))}
            aria-valuemin={280}
            aria-valuemax={Math.round(bounds.width * 0.48)}
            className="absolute -left-1 top-0 z-10 h-full w-2 touch-none cursor-col-resize hover:bg-primary/15 focus-visible:bg-primary/20 focus-visible:outline-none"
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              dockGesture.current = {
                x: event.clientX,
                width: Math.min(dockWidth, bounds.width * 0.48),
              };
              setDragging(true);
            }}
            onPointerMove={(event) => {
              if (dockGesture.current)
                onDockWidthChange(
                  Math.max(
                    280,
                    Math.min(
                      bounds.width * 0.48,
                      dockGesture.current.width +
                        dockGesture.current.x -
                        event.clientX,
                    ),
                  ),
                );
            }}
            onPointerUp={end}
            onPointerCancel={end}
            onLostPointerCapture={end}
            onKeyDown={(event) => {
              if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
              event.preventDefault();
              onDockWidthChange(
                Math.max(
                  280,
                  Math.min(
                    bounds.width * 0.48,
                    dockWidth + (event.key === "ArrowLeft" ? 20 : -20),
                  ),
                ),
              );
            }}
          />
        )}
        {!overlay && (
          <div
            ref={titleBar}
            tabIndex={0}
            aria-label={
              overlay && !narrow
                ? "拖动聊天窗口，方向键移动"
                : "浏览器助手标题栏"
            }
            className={cn(
              "flex h-11 shrink-0 items-center gap-2 border-b border-border-subtle px-3 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
              floating && !narrow && "pl-9",
              overlay &&
                !narrow &&
                "cursor-grab touch-none select-none active:cursor-grabbing",
            )}
            onPointerDown={start}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
            onLostPointerCapture={end}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.stopPropagation();
                onOpenChange(false);
              }
              if (
                event.target !== event.currentTarget ||
                !overlay ||
                narrow ||
                !event.key.startsWith("Arrow")
              )
                return;
              event.preventDefault();
              setPlacement(
                fitAssistant(bounds, {
                  ...fitted,
                  right:
                    fitted.right +
                    (event.key === "ArrowLeft"
                      ? 20
                      : event.key === "ArrowRight"
                        ? -20
                        : 0),
                  bottom:
                    fitted.bottom +
                    (event.key === "ArrowUp"
                      ? 20
                      : event.key === "ArrowDown"
                        ? -20
                        : 0),
                }),
              );
            }}
          >
            {overlay && !narrow ? (
              <GripHorizontal className="size-4 text-muted-foreground" />
            ) : (
              <MessageSquare className="size-4 text-muted-foreground" />
            )}
            <span className="flex-1 text-sm font-medium">浏览器助手</span>
            {!narrow && (
              <button
                type="button"
                className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                title={floating ? "停靠到右侧" : "悬浮聊天"}
                aria-label={floating ? "停靠到右侧" : "悬浮聊天"}
                onClick={() => setFloating(!floating)}
              >
                {floating ? (
                  <PanelRight className="size-4" />
                ) : (
                  <PanelsTopLeft className="size-4" />
                )}
              </button>
            )}
            <button
              type="button"
              title="收起聊天，任务继续运行"
              aria-label="收起聊天"
              onClick={() => onOpenChange(false)}
              className="grid size-8 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Minus className="size-4" />
            </button>
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col">
          <AssistantPresentation.Provider
            value={{
              compact: overlay,
              expanded: !collapsed,
              setExpanded,
              controls,
              dragHandle,
              contentId,
            }}
          >
            {activated && children}
          </AssistantPresentation.Provider>
        </div>
        {floating && expanded && !narrow && (
          <button
            type="button"
            aria-label="调整悬浮聊天大小"
            title="拖动调整大小；方向键微调"
            className="absolute left-1/2 top-0 z-10 grid h-3 w-12 -translate-x-1/2 touch-none cursor-nwse-resize place-items-center rounded-b text-muted-foreground/40 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
            onPointerDown={(event) => start(event, true)}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
            onLostPointerCapture={end}
            onKeyDown={(event) => {
              if (!event.key.startsWith("Arrow")) return;
              event.preventDefault();
              setPlacement(
                fitAssistant(bounds, {
                  ...fitted,
                  width:
                    fitted.width +
                    (event.key === "ArrowRight"
                      ? 20
                      : event.key === "ArrowLeft"
                        ? -20
                        : 0),
                  height:
                    fitted.height +
                    (event.key === "ArrowDown"
                      ? 20
                      : event.key === "ArrowUp"
                        ? -20
                        : 0),
                }),
              );
            }}
          >
            <GripHorizontal className="size-3" />
          </button>
        )}
      </aside>
      {!open && activated && (
        <button
          ref={restoreButton}
          type="button"
          aria-label="恢复浏览器聊天"
          onClick={() => onOpenChange(true)}
          className="absolute bottom-4 right-4 z-40 flex h-11 items-center gap-2 rounded-full border border-border-default bg-background px-4 text-sm text-foreground shadow-[var(--shadow-floating)] hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
        >
          <MessageSquare className="size-4" />
          继续对话
        </button>
      )}
    </>
  );
}
