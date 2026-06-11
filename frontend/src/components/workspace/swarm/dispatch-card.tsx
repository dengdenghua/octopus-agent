import { ChevronRightIcon, UsersIcon } from "lucide-react";
import { useState } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { DotProgress } from "./dot-progress";
import { STATUS_LABELS, type SwarmAgent } from "./types";

interface DispatchCardProps {
  agents: SwarmAgent[];
  title?: string;
  onAgentClick?: (agent: SwarmAgent) => void;
  selectedAgentId?: string;
  className?: string;
}

/* Implementation note. */
export function DispatchCard({
  agents,
  title,
  onAgentClick,
  selectedAgentId,
  className,
}: DispatchCardProps) {
  const { t } = useI18n();
  return (
    <div
      className={cn(
        "w-full overflow-hidden rounded-lg border border-border bg-card",
        className,
      )}
    >
      <div className="flex items-center gap-2 border-b border-border/60 bg-muted/30 px-4 py-2">
        <UsersIcon className="size-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-foreground">
          {title ?? t.dispatchCard.agentSwarmTitle}
        </span>
        <span className="text-muted-foreground text-xs">
          · {t.dispatchCard.parallelTasks(agents.length)}
        </span>
      </div>
      <ul className="divide-y divide-border/50">
        {agents.map((agent) => (
          <DispatchRow
            key={agent.id}
            agent={agent}
            selected={agent.id === selectedAgentId}
            onClick={() => onAgentClick?.(agent)}
          />
        ))}
      </ul>
    </div>
  );
}

function DispatchRow({
  agent,
  selected,
  onClick,
}: {
  agent: SwarmAgent;
  selected: boolean;
  onClick: () => void;
}) {
  const { t } = useI18n();
  const [hovered, setHovered] = useState(false);
  const isDone = agent.status === "done";
  return (
    <HoverCard openDelay={120} closeDelay={80}>
      <HoverCardTrigger asChild>
        <li
          role="button"
          tabIndex={0}
          onClick={onClick}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onKeyDown={(e) => (e.key === "Enter" ? onClick() : null)}
          className={cn(
            "flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors",
            "hover:bg-muted/40",
            selected && "bg-primary/5",
          )}
        >
          <AgentAvatar agent={agent} size={30} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">{agent.name}</span>
              <span className="text-muted-foreground truncate text-xs">
                {agent.role}
              </span>
            </div>
            <p className="text-muted-foreground mt-0.5 line-clamp-1 text-xs">
              {agent.task}
            </p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <span className="flex items-center gap-1.5 text-[11px]">
              <span
                className={cn(
                  "size-1.5 rounded-lg",
                  isDone ? "bg-emerald-500" : "animate-pulse",
                )}
                style={{
                  background: isDone
                    ? undefined
                    : `hsl(${agent.hue} 70% 50%)`,
                }}
              />
              <span
                className={cn(
                  "text-muted-foreground",
                  isDone && "text-emerald-600 dark:text-emerald-400",
                )}
              >
                {STATUS_LABELS[agent.status]}
              </span>
              <span className="text-muted-foreground/60 tabular-nums">
                {String(agent.index).padStart(2, "0")}
              </span>
            </span>
            {isDone ? (
              <div className="text-[10px] text-emerald-600 dark:text-emerald-400">
                ✓ {t.dispatchCard.done}
              </div>
            ) : (
              <DotProgress
                progress={agent.progress}
                hue={agent.hue}
                cols={14}
                rows={3}
              />
            )}
          </div>
          <ChevronRightIcon
            className={cn(
              "size-3.5 shrink-0 text-muted-foreground/40 transition-transform",
              hovered && "translate-x-0.5 text-muted-foreground",
            )}
          />
        </li>
      </HoverCardTrigger>
      <HoverCardContent side="right" align="start" className="w-80 p-0">
        <AgentPopoverContent agent={agent} />
      </HoverCardContent>
    </HoverCard>
  );
}

function AgentAvatar({ agent, size = 32 }: { agent: SwarmAgent; size?: number }) {
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-lg"
      style={{
        width: size,
        height: size,
        background: `hsl(${agent.hue} 70% 92%)`,
        fontSize: size * 0.55,
      }}
    >
      <span>{agent.avatarEmoji}</span>
    </div>
  );
}

function AgentPopoverContent({ agent }: { agent: SwarmAgent }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col">
      <div
        className="flex items-center gap-3 px-4 py-3"
        style={{ background: `hsl(${agent.hue} 70% 96%)` }}
      >
        <AgentAvatar agent={agent} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">{agent.name}</span>
            <span className="text-muted-foreground text-xs">
              {agent.role}
            </span>
          </div>
          <p className="text-muted-foreground mt-0.5 line-clamp-1 text-xs italic">
            "{agent.motto}"
          </p>
        </div>
      </div>
      <div className="border-b border-border/60 px-4 py-2 text-xs">
        <div className="text-muted-foreground mb-1">{t.dispatchCard.researchFocus}</div>
        <ol className="list-decimal space-y-0.5 pl-4 text-foreground/80">
          {(agent.details ?? [agent.task]).map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ol>
      </div>
      {(agent.skills.length > 0 || agent.stats || agent.personality) && (
        <div className="space-y-1.5 px-4 py-2 text-[11px]">
          {agent.skills.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-muted-foreground">{t.dispatchCard.equipment}</span>
              {agent.skills.map((s) => (
                <span
                  key={s}
                  className="rounded-lg bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  ⚙ {s}
                </span>
              ))}
            </div>
          )}
          {agent.personality && agent.personality.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-muted-foreground">{t.dispatchCard.personalityLabel}</span>
              {agent.personality.map((p) => (
                <span
                  key={p}
                  className="rounded-lg border border-border px-1.5 py-0.5 text-[10px]"
                >
                  {p}
                </span>
              ))}
            </div>
          )}
          {agent.stats && (
            <div className="text-muted-foreground">
              {t.dispatchCard.battleRecord(agent.stats.taskCount ?? 0)}
              {agent.stats.rating ? t.dispatchCard.ratingSuffix(agent.stats.rating.toFixed(1)) : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
