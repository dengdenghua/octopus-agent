import { BotIcon, MessageSquarePlus } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

function OctopusLogo({ size = 24 }: { size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-lg bg-card text-foreground ring-1 ring-border-subtle transition-colors hover:bg-muted"
      style={{ width: size, height: size }}
    >
      <BotIcon style={{ width: size * 0.62, height: size * 0.62 }} />
    </div>
  );
}

function getNewChatPath(): string {
  return "/workspace/realtime/new";
}

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { state, toggleSidebar } = useSidebar();
  const { pathname } = useLocation();

  // In collapsed mode, both the logo and the new-chat button render as
  // identical SidebarMenuButton tiles — same radius, same hover, same size —
  // so the top of the sidebar reads as one consistent button stack. The
  // logo's gradient only shows in expanded mode where the brand text is
  // also present; when collapsed the logo becomes a plain ghost-icon tile
  // matching the new-chat tile next to it.
  const iconTileClass =
    "transition-all hover:bg-muted hover:text-foreground text-muted-foreground group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:size-9 group-data-[collapsible=icon]:p-0";

  return (
    <>
      {state === "collapsed" ? (
        // Collapsed: two matching icon tiles (logo, new-chat). No gradient
        // background on the logo here — the shared tile treatment is what
        // unifies the pair visually.
        <SidebarMenu>
          <SidebarMenuItem className="group-data-[collapsible=icon]:px-0 px-2">
            <SidebarMenuButton
              asChild
              className={iconTileClass}
              tooltip="Octopus"
            >
              <button
                type="button"
                onClick={() => toggleSidebar()}
                aria-label="Expand sidebar"
              >
                <OctopusLogo size={18} />
              </button>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem className="group-data-[collapsible=icon]:px-0 px-2">
            <SidebarMenuButton
              isActive={pathname?.endsWith("/new")}
              asChild
              className={cn(
                iconTileClass,
                "data-[active=true]:bg-muted data-[active=true]:text-foreground data-[active=true]:font-medium",
              )}
              tooltip={t.sidebar.newChat}
            >
              <Link to={getNewChatPath()}>
                <MessageSquarePlus className="size-[15px] transition-transform group-hover:rotate-12" />
                <span className="leading-none">{t.sidebar.newChat}</span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      ) : (
        // Expanded: keep the branded header + full-width new-chat button.
        <>
          <div className="group-data-[collapsible=icon]:px-0 px-1.5">
            <div
              className={cn(
                "group/workspace-header flex h-8 flex-col justify-center transition-all",
                className,
              )}
            >
              <div className="flex h-full items-center justify-between gap-2 px-1">
                {env.STATIC_WEBSITE_ONLY ? (
                  <Link
                    to="/"
                    className="ml-0.5 flex h-full items-center transition-opacity hover:opacity-80"
                  >
                    <OctopusLogo size={18} />
                  </Link>
                ) : (
                  <div className="ml-0.5 flex h-full items-center">
                    <OctopusLogo size={18} />
                  </div>
                )}
                <SidebarTrigger className="flex h-7 w-7 items-center justify-center transition-all hover:scale-105 hover:bg-accent/40" />
              </div>
            </div>
          </div>
          <SidebarMenu>
            <SidebarMenuItem className="px-1.5">
              <SidebarMenuButton
                isActive={pathname?.endsWith("/new")}
                asChild
                className="py-1.5 text-sm transition-all hover:bg-muted hover:text-foreground data-[active=true]:bg-muted data-[active=true]:text-foreground data-[active=true]:font-medium text-muted-foreground"
              >
                <Link
                  className="flex h-full items-center gap-2"
                  to={getNewChatPath()}
                >
                  <MessageSquarePlus className="size-[15px] transition-transform group-hover:rotate-12" />
                  <span className="leading-none">{t.sidebar.newChat}</span>
                </Link>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </>
      )}
    </>
  );
}
