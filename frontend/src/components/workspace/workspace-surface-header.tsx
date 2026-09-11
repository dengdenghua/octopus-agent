import { cn } from "@/lib/utils";
import { useRef, type PointerEvent } from "react";
import {
  isEmbeddedWindow,
  sendEmbeddedWindowDrag,
} from "./embedded-window-bridge";
import { WorkspaceSurfaceSwitch } from "./workspace-surface-switch";

export function WorkspaceSurfaceHeader({
  active,
  className,
}: {
  active: "agent" | "browser";
  className?: string;
}) {
  const embedded = isEmbeddedWindow();
  const dragPointer = useRef<number | null>(null);
  const onDrag = (phase: "start" | "move" | "end", event: PointerEvent) => {
    if (!embedded) return;
    if (phase === "start") {
      if (event.target !== event.currentTarget) return;
      dragPointer.current = event.pointerId;
      event.currentTarget.setPointerCapture(event.pointerId);
    } else if (dragPointer.current !== event.pointerId) {
      return;
    }
    sendEmbeddedWindowDrag(phase, event.screenX, event.screenY);
    if (phase === "end") dragPointer.current = null;
  };

  return (
    <div
      onPointerDown={(event) => onDrag("start", event)}
      onPointerMove={(event) => onDrag("move", event)}
      onPointerUp={(event) => onDrag("end", event)}
      onPointerCancel={(event) => onDrag("end", event)}
      className={cn(
        // Native shells own window controls; this row contains app navigation.
        "flex h-8 shrink-0 items-center justify-start gap-2",
        // Echo OS overlays its 64px system-control hit area above the iframe.
        // Preserve the former switch position so the two layers never overlap.
        embedded && "pl-14",
        className,
      )}
    >
      <WorkspaceSurfaceSwitch active={active} />
    </div>
  );
}
