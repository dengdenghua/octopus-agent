import { AtSignIcon, BotIcon } from "lucide-react";

import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Team } from "@/core/teams/api";
import { cn } from "@/lib/utils";

import { WorkstationSeat } from "../workstation-seat";

interface TeamRosterProps {
  team: Team | null;
  currentParticipantId?: string;
  /** @mention a member into the composer (e.g. "@coder "). */
  onMention?: (name: string) => void;
  className?: string;
}

/**
 * The group's member list — humans (live collaborators) AND AI members
 * (agents/CLIs), always shown together so the team room reads like a work
 * group, not a task board. Both are rendered as compact "工位" seats
 * (``WorkstationSeat``) so a team member and an agent-mode subagent read as the
 * same kind of thing across the two right-side panels. Humans get a presence
 * dot; agents get a bot badge, are "随时待命", and @mention on click.
 */
export function TeamRoster({
  team,
  currentParticipantId,
  onMention,
  className,
}: TeamRosterProps) {
  const humans = (team?.participants ?? []).filter(
    (p) => p.status !== "removed",
  );
  const agents = team?.members ?? [];
  const onlineHumans = humans.filter((p) => p.status === "active").length;

  return (
    <div className={cn("min-h-0 flex-1 overflow-y-auto p-3", className)}>
      <div className="mb-3">
        <div className="text-sm font-medium text-foreground">群成员</div>
        <div className="mt-0.5 text-xs text-muted-foreground">
          {team?.name ?? "未选择 Team"} · {agents.length} 位 AI 成员 ·{" "}
          {onlineHumans}/{humans.length} 人在线
        </div>
      </div>

      {/* AI members — workstation seats, always in attendance */}
      {agents.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 flex items-center gap-1.5 px-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <BotIcon className="size-3" /> 工位 · 随时待命
          </div>
          <div className="flex flex-wrap gap-1.5">
            {agents.map((agent) => {
              const name = agent.display_name ?? agent.name;
              const isLeader = team?.leaderId === agent.name;
              // Local CLI partners may arrive without an avatar_url (older
              // roster snapshots only carried the emoji icon) — fall back to
              // their registered brand avatar endpoint so they match the chat.
              const rawAvatar =
                agent.avatar_url ??
                (agent.name.startsWith("local_")
                  ? `/api/agents/${agent.name}/avatar`
                  : undefined);
              const avatarSrc = rawAvatar
                ? withAgentAvatarVersion(rawAvatar)
                : undefined;
              return (
                <WorkstationSeat
                  key={agent.name}
                  className="max-w-full"
                  name={name}
                  avatar={agent.icon}
                  avatarUrl={avatarSrc}
                  showBotBadge
                  title={agent.description || "AI 成员"}
                  dotClassName="bg-muted-foreground/40"
                  dotLabel="随时待命"
                  badge={
                    isLeader ? (
                      <span className="shrink-0 rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        队长
                      </span>
                    ) : undefined
                  }
                  onClick={onMention ? () => onMention(agent.name) : undefined}
                  ariaLabel={onMention ? `@${name}` : name}
                  trailing={
                    onMention ? (
                      <AtSignIcon
                        className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/seat:opacity-100"
                        aria-hidden="true"
                      />
                    ) : undefined
                  }
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Human collaborators */}
      <div>
        <div className="mb-1.5 px-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          协作者
        </div>
        {humans.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border/70 bg-muted/15 px-4 py-6 text-center text-xs text-muted-foreground">
            还没有其他人 · 用上方「邀请」拉人进群
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {humans.map((participant) => (
              <WorkstationSeat
                key={participant.id}
                className="max-w-full"
                name={participant.display_name}
                fallbackInitial={participant.display_name.charAt(0)}
                title={
                  participant.status === "active"
                    ? `在线 · ${participant.role}`
                    : `离线 · ${participant.role}`
                }
                dotClassName={
                  participant.status === "active"
                    ? "bg-emerald-500"
                    : "bg-muted-foreground/35"
                }
                dotLabel={participant.status === "active" ? "在线" : "离线"}
                badge={
                  participant.id === currentParticipantId ? (
                    <span className="shrink-0 rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                      You
                    </span>
                  ) : undefined
                }
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
