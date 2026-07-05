import { cn } from "@/lib/utils";
import { MacWindowControls } from "./mac-window-controls";
import { WorkspaceSurfaceSwitch } from "./workspace-sidebar";

export function WorkspaceSurfaceHeader({
  active,
  className,
}: {
  active: "agent" | "browser";
  className?: string;
}) {
  return (
    <div
      className={cn(
        // Width follows content: MacWindowControls may render null (non-mac
        // Electron), collapsing the row to just the surface switch.
        "flex h-8 shrink-0 items-center justify-start gap-2",
        className,
      )}
    >
      <MacWindowControls />
      <WorkspaceSurfaceSwitch active={active} />
    </div>
  );
}
