import { cn } from "@/lib/utils";
import { useWorkbenchSurface } from "@/core/workbench/workbench-surface";
import { useElectronTitleBar } from "@/components/electron-title-bar";
import { SidebarTrigger } from "@/components/ui/sidebar";

export function WorkspaceContainer({
  className,
  children,
  mobileNavigation = false,
  ...props
}: React.ComponentProps<"div"> & { mobileNavigation?: boolean }) {
  const surface = useWorkbenchSurface();
  const embeddedInBrowser = surface === "browser";
  const { titleBarHeight, contentTopInset } = useElectronTitleBar();
  // Implementation note.
  // Implementation note.
  return (
    <div
      className={cn(
        "flex w-full flex-col px-3 pb-3 md:px-4",
        embeddedInBrowser ? "h-full" : "h-screen",
        className,
      )}
      style={
        titleBarHeight > 0 && !embeddedInBrowser
          ? { height: `calc(100dvh - ${contentTopInset})` }
          : undefined
      }
      {...props}
    >
      {mobileNavigation && !embeddedInBrowser && (
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border/60 md:hidden">
          <SidebarTrigger className="size-10" />
          <span className="text-sm font-medium">Echo</span>
        </div>
      )}
      {children}
    </div>
  );
}

export function WorkspaceBody({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="workspace-body"
      className={cn(
        "relative flex min-h-0 w-full flex-1 flex-col items-center overflow-y-auto overflow-x-hidden pt-3",
        className,
      )}
      {...props}
    >
      {/* ``flex-1 min-h-0`` on the inner wrapper so children using
          ``h-full`` / ``size-full`` get a non-zero parent height.
          Without this, React-Flow-based pages (workflows editor) log
          "The React Flow parent container needs a width and a height
          to render the graph" and render blank. Regression discovered
          2026-04-24 by browser-side regression sweep. */}
      <div className="flex w-full flex-1 min-h-0 flex-col items-center">
        {children}
      </div>
    </div>
  );
}
