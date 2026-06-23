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
  // Local CLI partners (Codex CLI / Claude Code / …) are not regular in-process
  // agents — label the badge so it doesn't read as a generic "Agent".
  const isLocalPartner =
    agentName.startsWith("local_") || (agent?.name ?? "").startsWith("local_");
  const typeBadge = isLocalPartner ? "本地伙伴" : "Agent";

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-center justify-center gap-3 px-5 py-5 text-center sm:px-8",
        className,
      )}
    >
      <div className="relative">
        <div className="flex size-[72px] items-center justify-center overflow-hidden rounded-lg border border-border/70 bg-card shadow-sm">
          {agent?.avatar_url ? (
            <img
              src={`${getBackendBaseURL()}${withAgentAvatarVersion(agent.avatar_url)}`}
              alt={displayName}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="flex h-full w-full items-center justify-center bg-primary/10">
              <BotIcon className="text-primary h-8 w-8" />
            </span>
          )}
        </div>
        <span className="absolute -right-1 -bottom-1 flex h-5 items-center rounded-md border border-border bg-background px-1.5 text-[10px] font-medium text-muted-foreground shadow-sm">
          {typeBadge}
        </span>
      </div>
      <div className="space-y-1.5">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">
          {displayName}
        </h2>
        {description ? (
          <p className="text-muted-foreground max-w-md text-sm leading-6">
            {description}
          </p>
        ) : (
          <p className="text-muted-foreground max-w-md text-sm leading-6">
            Ready for the next turn.
          </p>
        )}
      </div>
    </div>
  );
}
