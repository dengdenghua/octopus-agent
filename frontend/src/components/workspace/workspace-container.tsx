import { Link, useLocation } from "react-router-dom";
import { useMemo } from "react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/* Implementation note. */
const ELECTRON_TITLE_BAR_HEIGHT = 36;
const inElectron = (): boolean =>
  typeof window !== "undefined" && !!window.octopus?.isElectron;

export function WorkspaceContainer({
  className,
  children,
  ...props
}: React.ComponentProps<"div">) {
  // Implementation note.
  // Implementation note.
  return (
    <div
      className={cn(
        "flex h-screen w-full flex-col px-3 pb-3 md:px-4",
        className,
      )}
      style={
        inElectron() ? { paddingTop: ELECTRON_TITLE_BAR_HEIGHT } : undefined
      }
      {...props}
    >
      {inElectron() && (
        <div
          aria-hidden
          className="pointer-events-none fixed left-0 right-0 top-0 z-50 h-9"
          style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
        />
      )}
      {children}
    </div>
  );
}

export function WorkspaceHeader({
  className,
  children,
  ...props
}: React.ComponentProps<"header">) {
  const { t } = useI18n();
  const { pathname } = useLocation();
  const segments = useMemo(() => {
    const parts = pathname?.split("/").filter(Boolean) || [];
    // Skip the leading "workspace" segment · it's the breadcrumb root.
    return parts[0] === "workspace" ? parts.slice(1) : parts;
  }, [pathname]);
  return (
    <header
      className={cn(
        "workspace-panel-subtle top-0 right-0 left-0 z-20 mt-3 flex h-16 shrink-0 items-center justify-between gap-2 rounded-lg px-1 transition-[width,height] ease-out group-has-data-[collapsible=icon]/sidebar-wrapper:h-12",
        className,
      )}
      {...props}
    >
      {/* Implementation note. */}
      <div className="flex min-w-0 items-center gap-2 pl-2 pr-4 md:pl-12">
        <SidebarTrigger className="flex size-8 opacity-100 md:hidden" />
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem className="hidden md:block">
              <BreadcrumbLink asChild>
                <Link to="/workspace">{t.breadcrumb.workspace}</Link>
              </BreadcrumbLink>
            </BreadcrumbItem>
            {segments.map((seg, idx) => {
              const href = `/workspace/${segments.slice(0, idx + 1).join("/")}`;
              const isLast = idx === segments.length - 1;
              return (
                <span key={seg + idx} className="flex items-center gap-2">
                  <BreadcrumbSeparator className="hidden md:block" />
                  <BreadcrumbItem className="min-w-0">
                    {isLast ? (
                      <BreadcrumbPage className="truncate">
                        {nameOfSegment(seg, t)}
                      </BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink asChild>
                        <Link to={href} className="truncate">
                          {nameOfSegment(seg, t)}
                        </Link>
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                </span>
              );
            })}
            {children && (
              <>
                <BreadcrumbSeparator />
                {children}
              </>
            )}
          </BreadcrumbList>
        </Breadcrumb>
      </div>
    </header>
  );
}

export function WorkspaceBody({
  className,
  children,
  ...props
}: React.ComponentProps<"main">) {
  return (
    <main
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
    </main>
  );
}

function nameOfSegment(
  segment: string | undefined,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (!segment) return t.common.home;
  if (segment === "workspace") return t.breadcrumb.workspace;
  if (segment === "chats") return t.breadcrumb.chats;
  if (segment === "store") return t.sidebar.navStore;
  if (segment === "intelligence") return t.sidebar.navIntelligence;
  if (segment === "channels") return t.sidebar.channels;
  if (segment === "desktop-organizer") return t.sidebar.navDesktopOrganizer;
  if (segment === "nas" || segment === "database") return t.sidebar.navDatabase;
  if (segment === "knowledge") return t.sidebar.navKnowledgeGraph;
  if (segment === "evolution") return t.sidebar.evolution;
  if (segment === "replay") return t.sidebar.navReplay;
  if (segment === "workflows") return "工作流";
  if (segment === "reflex") return t.sidebar.navReflex;
  if (segment === "observability") return t.sidebar.observability;
  if (segment === "diagnostics") return t.sidebar.diagnostics;
  if (segment === "plugins") return t.sidebar.plugins;
  if (segment === "mobile") return t.sidebar.navMobile;
  if (segment === "computer") return "本机助手";
  if (segment === "edit") return "Edit";
  if (segment === "new") return "New";
  // Fallback for dynamic IDs (thread id, agent name, etc.) ·
  // abbreviate to first 8 chars so a long UUID doesn't blow up
  // the breadcrumb. Capitalise for visual balance.
  if (segment.length > 16) {
    return segment.slice(0, 8) + "…";
  }
  return segment[0]?.toUpperCase() + segment.slice(1);
}
