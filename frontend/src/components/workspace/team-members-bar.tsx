import { UsersIcon } from "lucide-react";

import { getBackendBaseURL } from "@/core/config";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Agent } from "@/core/agents/types";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function TeamMembersBar({
  members,
  leaderId,
  className,
}: {
  members: Agent[];
  leaderId?: string | null;
  className?: string;
}) {
  if (members.length === 0) return null;

  return (
    <div className={cn("flex items-center gap-1.5", className)}>
      {/* Stacked avatars */}
      <div className="flex -space-x-2">
        {members.slice(0, 6).map((agent) => {
          const displayName = agent.display_name ?? agent.name;
          const isLeader = agent.name === leaderId;
          return (
            <Tooltip key={agent.name}>
              <TooltipTrigger asChild>
                <div
                  className={cn(
                    "relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-lg border-2 border-background",
                    isLeader && "ring-2 ring-green-500",
                  )}
                >
                  {agent.avatar_url ? (
                    <img
                      src={`${getBackendBaseURL()}${withAgentAvatarVersion(agent.avatar_url)}`}
                      alt={displayName}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <span className="bg-primary/10 flex h-full w-full items-center justify-center text-xs font-medium">
                      {displayName.charAt(0)}
                    </span>
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {displayName}
                {isLeader && " (TL)"}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>

      {/* Count */}
      <span className="text-muted-foreground flex items-center gap-1 text-xs">
        <UsersIcon className="size-3" />
        {members.length}
      </span>
    </div>
  );
}
