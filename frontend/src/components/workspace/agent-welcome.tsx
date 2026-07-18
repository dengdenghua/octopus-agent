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
        "mx-auto flex w-full flex-col items-center justify-center gap-4 px-5 py-6 text-center sm:px-8",
        className,
      )}
    >
      <div className="relative">
        <div className="absolute -inset-3 rounded-2xl bg-gradient-to-br from-primary/20 via-primary/8 to-transparent blur-2xl" />
        <div className="relative flex size-[80px] items-center justify-center overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-card to-muted/50 shadow-[var(--shadow-lg)]">
          {agent?.avatar_url ? (
            <img
              src={`${getBackendBaseURL()}${withAgentAvatarVersion(agent.avatar_url)}`}
              alt={displayName}
              className="h-full w-full object-cover"
            />
          ) : (
            <span className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/15 to-primary/5">
              <BotIcon className="text-primary h-9 w-9 drop-shadow-sm" strokeWidth={1.5} />
            </span>
          )}
        </div>
        <span className="absolute -right-1.5 -bottom-1.5 flex h-5.5 items-center gap-1 rounded-lg border border-border bg-background/95 px-2 text-[10px] font-semibold tracking-wide text-muted-foreground/90 shadow-[var(--shadow-sm)] backdrop-blur-sm">
          <span className="size-1.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />
          {typeBadge}
        </span>
      </div>
      <div className="space-y-2">
        <h2 className="bg-gradient-to-r from-foreground via-foreground to-foreground/80 bg-clip-text text-[22px] font-bold tracking-tight text-transparent">
          {displayName}
        </h2>
        {description ? (
          <p className="text-muted-foreground/80 max-w-md text-[13px] leading-relaxed">
            {description}
          </p>
        ) : (
          <p className="text-muted-foreground/70 max-w-md text-[13px] leading-relaxed">
            Ready for the next turn.
          </p>
        )}
      </div>
    </div>
  );
}
