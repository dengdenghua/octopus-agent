import { ChevronDownIcon } from "lucide-react";
import type { Agent } from "@/core/agents/types";
import { isPrimaryPersonaAgentId } from "@/core/agents/persona-policy";
import { emitAgentChanged } from "@/core/events";
import { useI18n } from "@/core/i18n/hooks";
import { AgentAvatar } from "@/components/workspace/agent-avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

export function BrowserAgentPicker({
  activeAgent,
  agents,
  activeAgentId,
}: {
  activeAgent: Agent | null;
  agents: Agent[];
  activeAgentId: string;
}) {
  const { t } = useI18n();
  const display =
    activeAgent?.display_name || activeAgent?.name || activeAgentId;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`${t.sidebar.switchAgent} · ${display}`}
          className="flex min-h-8 shrink-0 items-center gap-1.5 rounded-md px-1.5 py-1 text-sm font-medium hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <AgentAvatar agent={activeAgent ?? undefined} className="size-6" />
          <span className="max-w-32 truncate">{display}</span>
          <ChevronDownIcon className="size-3 text-muted-foreground" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        sideOffset={5}
        className="w-64 max-w-[calc(100vw-24px)]"
      >
        <DropdownMenuLabel className="px-2 py-1.5 text-xs font-normal text-muted-foreground">
          {t.sidebar.switchAgent}
        </DropdownMenuLabel>
        {agents.length === 0 ? (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {t.browser.assistant.noAgents}
          </div>
        ) : (
          agents.map((agent) => {
            const active = agent.name === activeAgentId;
            return (
              <DropdownMenuItem
                key={agent.name}
                aria-current={active ? "true" : undefined}
                onSelect={() => {
                  if (isPrimaryPersonaAgentId(agent.name))
                    emitAgentChanged(agent.name);
                }}
                className={cn(
                  "my-0.5 min-h-11 gap-2.5 rounded-md px-2",
                  active && "bg-foreground/[0.065]",
                )}
              >
                <AgentAvatar agent={agent} className="size-7" />
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      "block truncate text-xs",
                      active && "font-medium",
                    )}
                  >
                    {agent.display_name || agent.name}
                  </span>
                  <span className="block truncate text-[11px] text-muted-foreground">
                    {t.sidebar.agentRoleSummary[agent.name] ||
                      agent.description}
                  </span>
                </span>
              </DropdownMenuItem>
            );
          })
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
