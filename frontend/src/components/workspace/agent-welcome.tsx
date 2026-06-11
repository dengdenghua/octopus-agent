
import { BotIcon } from "lucide-react";

import { type Agent } from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { getBackendBaseURL } from "@/core/config";
import { cn } from "@/lib/utils";

export function AgentWelcome({
  className,
  agent,
  agentName,
}: {
  className?: string;
  agent: Agent | null | undefined;
  agentName: string;
}) {
  const displayName =
    agent?.display_name ??
    agent?.name ??
    (agentName === "general" ? "Octopus Agent" : agentName);
  const description = agent?.description;

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-4 px-8 py-6 text-center",
        className,
      )}
    >
      <div className="relative group">
        <div className="absolute -inset-1 bg-gradient-to-r from-primary/20 via-violet-500/20 to-primary/20 rounded-lg blur-md opacity-60 group-hover:opacity-100 transition-opacity duration-500" />
        <div className="relative flex h-20 w-20 items-center justify-center overflow-hidden rounded-lg ring-1 ring-primary/10 shadow-xl shadow-primary/10 bg-gradient-to-br from-background to-muted/50 transition-transform duration-300 group-hover:scale-105">
          {agent?.avatar_url ? (
            <img
              src={`${getBackendBaseURL()}${withAgentAvatarVersion(agent.avatar_url)}`}
              alt={displayName}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="bg-gradient-to-br from-primary/10 to-violet-500/10 flex h-full w-full items-center justify-center">
              <BotIcon className="text-primary h-8 w-8" />
            </span>
          )}
        </div>
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
          {displayName}
        </h2>
        {description ? (
          <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
            {description}
          </p>
        ) : (
          <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
            Ready for the next turn.
          </p>
        )}
      </div>
    </div>
  );
}
