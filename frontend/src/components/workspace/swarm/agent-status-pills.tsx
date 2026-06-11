import { CheckIcon, XIcon, ClockIcon } from "lucide-react";

import { cn } from "@/lib/utils";

import { STATUS_LABELS, type SwarmAgent } from "./types";

interface Props {
  agents: SwarmAgent[];
  selectedId: string;
  onSelect: (id: string) => void;
}

function getTerminalBadge(status: string) {
  if (status === "done") return <CheckIcon className="size-2" strokeWidth={3} />;
  if (status === "failed") return <XIcon className="size-2" strokeWidth={3} />;
  if (status === "cancelled") return <XIcon className="size-2" strokeWidth={3} />;
  if (status === "timed_out") return <ClockIcon className="size-2" strokeWidth={3} />;
  return null;
}

function getTerminalBadgeColor(status: string) {
  if (status === "done") return "bg-emerald-500";
  if (status === "failed") return "bg-red-500";
  if (status === "cancelled") return "bg-yellow-500";
  if (status === "timed_out") return "bg-orange-500";
  return "";
}

function getTerminalTextColor(status: string) {
  if (status === "done") return "text-emerald-600 dark:text-emerald-400";
  if (status === "failed") return "text-red-600 dark:text-red-400";
  if (status === "cancelled") return "text-yellow-600 dark:text-yellow-400";
  if (status === "timed_out") return "text-orange-600 dark:text-orange-400";
  return "text-foreground";
}

export function AgentStatusPills({ agents, selectedId, onSelect }: Props) {
  return (
    <div className="flex items-center gap-2 overflow-x-auto px-3 py-2">
      {agents.map((agent) => {
        const isTerminal = agent.status === "done" || agent.status === "failed" || agent.status === "cancelled" || agent.status === "timed_out";
        const isSelected = agent.id === selectedId;
        const badge = getTerminalBadge(agent.status);
        return (
          <button
            key={agent.id}
            type="button"
            onClick={() => onSelect(agent.id)}
            className={cn(
              "group shrink-0 rounded-lg border bg-card px-3 py-1.5 text-xs transition-all",
              "hover:border-primary/40",
              isSelected
                ? "border-primary/60 bg-primary/5 ring-2 ring-primary/20"
                : "border-border/60",
            )}
          >
            <div className="flex items-center gap-2">
              <div
                className="relative flex size-6 shrink-0 items-center justify-center rounded-lg text-sm"
                style={{ background: `hsl(${agent.hue} 70% 92%)` }}
              >
                <span>{agent.avatarEmoji}</span>
                {isTerminal && badge && (
                  <span className={cn("absolute -right-0.5 -bottom-0.5 flex size-3 items-center justify-center rounded-lg text-white", getTerminalBadgeColor(agent.status))}>
                    {badge}
                  </span>
                )}
              </div>
              <span className="text-muted-foreground tabular-nums text-[10px]">
                {String(agent.index).padStart(2, "0")}
              </span>
              <span
                className={cn(
                  "text-[11px]",
                  isTerminal ? getTerminalTextColor(agent.status) : "text-foreground",
                )}
              >
                {STATUS_LABELS[agent.status]}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
