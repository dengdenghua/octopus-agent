import { CrosshairIcon, XIcon } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { dispatchInspectSelected } from "./inspect-bus";

type IncomingMessage =
  | { type: "octopus:inspect:ready" }
  | { type: "octopus:inspect:state"; active: boolean }
  | {
      type: "octopus:inspect:select";
      payload: {
        selector: string;
        tagName: string;
        outerHTML: string;
        textContent: string;
        rect: { x: number; y: number; w: number; h: number };
      };
    };

export function InspectOverlay({
  iframeRef,
  filepath,
  enabled,
  className,
  children,
}: {
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  filepath: string;
  /** When false, renders children pass-through with no inspect chrome. */
  enabled: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [active, setActive] = useState(false);
  const [iframeReady, setIframeReady] = useState(false);
  const filepathRef = useRef(filepath);
  filepathRef.current = filepath;

  useEffect(() => {
    if (!enabled) return;
    function onMessage(e: MessageEvent) {
      if (!iframeRef.current) return;
      if (e.source !== iframeRef.current.contentWindow) return;
      const data = e.data as IncomingMessage | null;
      if (!data || typeof data !== "object") return;
      if (data.type === "octopus:inspect:ready") {
        setIframeReady(true);
      } else if (data.type === "octopus:inspect:state") {
        setActive(!!data.active);
      } else if (data.type === "octopus:inspect:select") {
        dispatchInspectSelected({ ...data.payload, filepath: filepathRef.current });
        setActive(false);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [enabled, iframeRef]);

  // Reset readiness when the file changes — new srcDoc means new injected script lifecycle.
  useEffect(() => {
    setIframeReady(false);
    setActive(false);
  }, [filepath]);

  if (!enabled) {
    return <div className={cn("relative size-full", className)}>{children}</div>;
  }

  function toggle() {
    const win = iframeRef.current?.contentWindow;
    if (!win) return;
    const next = !active;
    win.postMessage(
      { type: next ? "octopus:inspect:enable" : "octopus:inspect:disable" },
      "*",
    );
    setActive(next);
  }

  return (
    <div className={cn("relative size-full", className)}>
      {children}
      <div className="pointer-events-none absolute top-2 right-2 z-10 flex items-center gap-1.5">
        {active && (
          <span className="pointer-events-none rounded-md bg-violet-600/90 px-2 py-1 text-[11px] text-white shadow-md">
            Click an element · Esc to cancel
          </span>
        )}
        <Button
          aria-label={active ? "Cancel inspect" : "Inspect element"}
          className={cn(
            "pointer-events-auto h-7 gap-1.5 px-2 text-xs shadow-md",
            active && "bg-violet-600 text-white hover:bg-violet-700",
          )}
          disabled={!iframeReady}
          onClick={toggle}
          size="sm"
          title={
            iframeReady
              ? active
                ? "Cancel inspect"
                : "Click to pick an element"
              : "Preview is loading…"
          }
          type="button"
          variant={active ? "default" : "secondary"}
        >
          {active ? (
            <XIcon className="size-3" />
          ) : (
            <CrosshairIcon className="size-3" />
          )}
          {active ? "Cancel" : "Inspect"}
        </Button>
      </div>
    </div>
  );
}
