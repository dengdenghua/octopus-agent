import { GlobeIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import { Link, useLocation } from "react-router-dom";

import { useI18n } from "@/core/i18n/hooks";
import {
  BROWSER_WORKSPACE_ROUTE,
  workspaceAgentReturnRoute,
} from "@/core/workspace/sidebar-routing";
import { cn } from "@/lib/utils";

type WorkspaceSurfaceMode = "agent" | "browser";

// Each route owns a header instance; retain the previous position across remounts.
let lastSurface: WorkspaceSurfaceMode | null = null;
const sliderPosition = (surface: WorkspaceSurfaceMode) =>
  surface === "agent"
    ? { transform: "translateX(0)", width: "44px" }
    : { transform: "translateX(48px)", width: "44px" };

export const LAST_AGENT_WORKSPACE_ROUTE_KEY =
  "octopus:last-agent-workspace-route";

export function WorkspaceSurfaceSwitch({
  active,
}: {
  active: WorkspaceSurfaceMode;
}) {
  const { t } = useI18n();
  const location = useLocation();
  const slider = useRef<HTMLSpanElement>(null);
  useLayoutEffect(() => {
    const previous = lastSurface;
    lastSurface = active;
    if (
      !previous ||
      previous === active ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
      !slider.current?.animate
    )
      return;
    const animation = slider.current.animate(
      [sliderPosition(previous), sliderPosition(active)],
      { duration: 180, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
    );
    return () => animation.cancel();
  }, [active]);
  let rememberedAgentRoute: string | null = null;
  try {
    if (typeof window !== "undefined") {
      rememberedAgentRoute = window.sessionStorage.getItem(
        LAST_AGENT_WORKSPACE_ROUTE_KEY,
      );
    }
  } catch {
    // Storage may be disabled by the host; the primary route remains usable.
  }
  const agentReturnRoute = workspaceAgentReturnRoute(
    location.pathname,
    location.search,
    rememberedAgentRoute,
  );

  useEffect(() => {
    if (active !== "agent") return;
    try {
      if (typeof window !== "undefined") {
        window.sessionStorage.setItem(
          LAST_AGENT_WORKSPACE_ROUTE_KEY,
          agentReturnRoute,
        );
      }
    } catch {
      // A privacy-restricted host can still use the switch's default route.
    }
  }, [active, agentReturnRoute]);

  const items = [
    {
      to: agentReturnRoute,
      label: t.desktop.header.brand,
      text: t.desktop.header.brand,
      value: "agent" as const,
    },
    {
      to: BROWSER_WORKSPACE_ROUTE,
      label: t.sidebar.navBrowserSurface,
      value: "browser" as const,
    },
  ];
  const radiusVar = "var(--appearance-radius-control)";

  return (
    <div
      className={cn(
        "relative isolate grid h-7 w-[92px] shrink-0 grid-cols-2 items-center gap-1 bg-foreground/[0.045]",
        "group-data-[collapsible=icon]:hidden",
      )}
      style={{ borderRadius: radiusVar }}
      role="tablist"
      aria-label="Workspace surface"
    >
      <span
        ref={slider}
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0.5 left-0 bg-background shadow-sm dark:bg-foreground/[0.14]"
        style={{
          borderRadius: `max(4px, calc(${radiusVar} - 4px))`,
          ...sliderPosition(active),
        }}
      />
      {items.map((item) => {
        const isActive = item.value === active;
        return (
          <Link
            key={item.to}
            to={item.to}
            aria-current={isActive ? "page" : undefined}
            aria-label={item.label}
            title={item.label}
            role="tab"
            aria-selected={isActive}
            className={cn(
              "relative z-10 flex h-7 min-w-0 items-center justify-center gap-1.5 px-1 text-xs leading-none after:absolute after:inset-x-0 after:-inset-y-[2px] after:content-['']",
              "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
              isActive
                ? "font-medium text-foreground"
                : "font-medium text-muted-foreground hover:bg-foreground/[0.035] hover:text-foreground",
            )}
            style={{ borderRadius: `max(4px, calc(${radiusVar} - 4px))` }}
          >
            {item.value === "browser" && (
              <GlobeIcon
                className="size-[14px] shrink-0"
                strokeWidth={1.75}
                aria-hidden="true"
              />
            )}
            {item.value === "agent" && (
              <span className="min-w-0 truncate">{item.text}</span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
