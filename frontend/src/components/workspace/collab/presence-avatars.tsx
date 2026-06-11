import { UsersIcon } from "lucide-react";
import type { CSSProperties } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCollab } from "./collab-provider";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface PresenceAvatarsProps {
  className?: string;
}

export function PresenceAvatars({ className }: PresenceAvatarsProps) {
  const { t } = useI18n();
  const { users, currentUser } = useCollab();

  const displayUsers = users.slice(0, 5);
  const remainingCount = Math.max(0, users.length - 5);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="flex items-center gap-1">
        {displayUsers.map((user) => {
          const avatarStyle = {
            "--presence-color": user.color,
          } as CSSProperties;

          return (
            <Tooltip key={user.id}>
              <TooltipTrigger asChild>
                <div
                  className="relative flex h-8 shrink-0 items-center"
                  style={avatarStyle}
                >
                  {user.avatar ? (
                    <img
                      src={user.avatar}
                      alt={user.name}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <span className="px-0.5 text-xs font-semibold text-[color:color-mix(in_oklch,var(--presence-color)_72%,var(--foreground))]">
                      {user.name.charAt(0).toUpperCase()}
                    </span>
                  )}
                  {user.id === currentUser?.id && (
                    <span className="absolute -bottom-0.5 left-1/2 size-1.5 -translate-x-1/2 rounded-full bg-emerald-500" />
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent>{user.name}</TooltipContent>
            </Tooltip>
          );
        })}
        {remainingCount > 0 && (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex h-8 shrink-0 items-center px-0.5 text-xs font-medium text-muted-foreground">
                +{remainingCount}
              </div>
            </TooltipTrigger>
            <TooltipContent>
              {t.collab.onlineCount(remainingCount)}
            </TooltipContent>
          </Tooltip>
        )}
      </div>
      <div className="flex h-8 items-center gap-1 text-xs text-muted-foreground">
        <UsersIcon className="size-3.5" />
        <span>{t.collab.onlineCount(users.length)}</span>
      </div>
    </div>
  );
}
