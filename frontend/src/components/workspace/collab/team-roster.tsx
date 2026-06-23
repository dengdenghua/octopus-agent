import { AtSignIcon, BotIcon } from "lucide-react";

import { withAgentAvatarVersion } from "@/core/agents/avatar";
import type { Team } from "@/core/teams/api";
import { cn } from "@/lib/utils";

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
 * group, not a task board. Humans get a presence dot; agents get a bot badge
 * and are "随时待命".
 */
export function TeamRoster({
  team,
  currentParticipantId,
  onMention,
  className,
}: TeamRosterProps) {
  const humans = (team?.participants ?? []).filter((p) => p.status !== "removed");
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

      {/* AI members — always in attendance */}
      {agents.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 flex items-center gap-1.5 px-0.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            <BotIcon className="size-3" /> AI 成员 · 随时待命
          </div>
          <div className="space-y-1.5">
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
                <div
                  key={agent.name}
                  className="group flex items-center gap-2 rounded-lg border border-border/60 bg-background/85 px-3 py-2"
                >
                  <span className="relative grid size-8 shrink-0 place-items-center overflow-hidden rounded-lg bg-muted text-[15px] leading-none">
                    {avatarSrc ? (
                      <img
                        src={avatarSrc}
                        alt={name}
                        className="size-full object-cover"
                      />
                    ) : agent.icon?.trim() ? (
                      agent.icon
                    ) : (
                      <span className="text-xs font-semibold text-muted-foreground">
                        {name.charAt(0).toUpperCase()}
                      </span>
                    )}
                    <span className="absolute -bottom-0.5 -right-0.5 grid size-3 place-items-center rounded-full bg-background">
                      <BotIcon className="size-2 text-muted-foreground" />
                    </span>
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="truncate text-sm font-medium text-foreground">
                        {name}
                      </span>
                      {isLeader && (
                        <span className="shrink-0 rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                          队长
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {agent.description || "AI 成员"}
                    </span>
                  </span>
                  {onMention && (
                    <button
                      type="button"
                      onClick={() => onMention(agent.name)}
                      title={`@${name}`}
                      className="shrink-0 rounded-md p-1 text-muted-foreground opacity-0 transition-all hover:bg-primary/10 hover:text-primary group-hover:opacity-100"
                    >
                      <AtSignIcon className="size-3.5" />
                    </button>
                  )}
                </div>
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
          <div className="space-y-1.5">
            {humans.map((participant) => (
              <div
                key={participant.id}
                className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/85 px-3 py-2"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted text-xs font-semibold text-muted-foreground">
                  {participant.display_name.charAt(0)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-sm font-medium text-foreground">
                      {participant.display_name}
                    </span>
                    {participant.id === currentParticipantId && (
                      <span className="rounded-md bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                        You
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {participant.status === "active" ? "在线" : "离线"} ·{" "}
                    {participant.role}
                  </span>
                </span>
                <span
                  className={cn(
                    "size-2 rounded-full",
                    participant.status === "active"
                      ? "bg-emerald-500"
                      : "bg-muted-foreground/35",
                  )}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
