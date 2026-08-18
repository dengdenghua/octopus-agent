/**
 * TaskCollaboratorControl — extracted from `workspace/realtime/[thread_id]/page.tsx`
 * (P3 decomposition). Behavior-preserving move: same code, same props, own module.
 */
import { useCallback, useMemo, useState } from "react";
import {
  CheckIcon,
  CopyIcon,
  SearchIcon,
  UserIcon,
  UsersRoundIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { AgentAvatar } from "@/components/workspace/sidebar-footer";
import {
  TEAM_MODES,
  useTeamModeMeta,
  type TeamMode,
} from "@/components/workspace/team-mode-picker";
import { type Agent } from "@/core/agents";
import { copyTextToClipboard } from "@/core/clipboard";
import { threadCollaborationLink } from "@/core/collaboration/thread-collaboration-link";
import { useCollabSession } from "@/core/cowork";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export type ChatCollaborationRosterEntry = {
  agent_id: string;
  name: string;
  display_name: string;
  avatar_url?: string | null;
  icon?: string | null;
  role: "tl" | "member";
};

function formatCollaboratorCount(count: number, unit: string): string {
  return unit.length <= 1 ? `${count}${unit}` : `${count} ${unit}`;
}

export function TaskCollaboratorControl({
  agents,
  selectedAgents,
  selectedAgentIds,
  currentAgentName,
  teamMode,
  open,
  onOpenChange,
  onSelectedAgentIdsChange,
  onTeamModeChange,
  roster,
  threadId,
  isNewThread,
}: {
  agents: Agent[];
  selectedAgents: Agent[];
  selectedAgentIds: string[];
  currentAgentName?: string | null;
  teamMode: TeamMode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onSelectedAgentIdsChange: (ids: string[]) => void;
  onTeamModeChange: (mode: TeamMode) => void;
  roster: ChatCollaborationRosterEntry[];
  threadId: string;
  isNewThread: boolean;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const selectedSet = useMemo(
    () => new Set(selectedAgentIds),
    [selectedAgentIds],
  );
  const agentByName = useMemo(() => {
    const map = new Map<string, Agent>();
    for (const agent of agents) {
      map.set(agent.name, agent);
    }
    return map;
  }, [agents]);
  const isTeamDraft = selectedAgents.length > 0;
  const teamSize = isTeamDraft
    ? selectedAgents.length + (currentAgentName ? 1 : 0)
    : 1;
  const teamModeMeta = useTeamModeMeta();
  const activeMeta = isTeamDraft ? teamModeMeta[teamMode] : null;
  const totalCount = Math.max(teamSize, roster.length || 1);
  const countLabel = formatCollaboratorCount(
    totalCount,
    t.chatInputBox.collaboratorsCountUnit,
  );
  const collabSession = useCollabSession(threadId);
  const onlineCount = useMemo(() => {
    const presence = collabSession.data?.presence ?? [];
    return presence.filter((m) => m.online).length;
  }, [collabSession.data]);
  const hasOnlineMembers = onlineCount > 0;
  const q = query.trim().toLowerCase();
  const availableAgents = useMemo(
    () =>
      agents.filter((agent) => {
        if (currentAgentName && agent.name === currentAgentName) return false;
        if (!q) return true;
        const label = agent.display_name ?? agent.name;
        return (
          label.toLowerCase().includes(q) ||
          agent.name.toLowerCase().includes(q) ||
          agent.description.toLowerCase().includes(q)
        );
      }),
    [agents, currentAgentName, q],
  );

  const toggleAgent = useCallback(
    (agent: Agent) => {
      if (selectedSet.has(agent.name)) {
        onSelectedAgentIdsChange(
          selectedAgentIds.filter((id) => id !== agent.name),
        );
        return;
      }
      if (selectedAgentIds.length === 0 && teamMode === "chat") {
        onTeamModeChange("cluster");
      }
      onSelectedAgentIdsChange([...selectedAgentIds, agent.name]);
    },
    [
      onSelectedAgentIdsChange,
      onTeamModeChange,
      selectedAgentIds,
      selectedSet,
      teamMode,
    ],
  );
  const handleCopyLink = async () => {
    try {
      await copyTextToClipboard(
        threadCollaborationLink({
          threadId,
          isNewThread,
          origin:
            typeof window === "undefined" ? undefined : window.location.origin,
          pathname:
            typeof window === "undefined"
              ? undefined
              : window.location.pathname,
        }),
      );
      toast.success(t.collab.linkCopied);
    } catch {
      toast.error(t.collab.copyFailed);
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "group inline-flex h-[42px] max-w-[11rem] items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium shadow-none transition-all duration-base sm:h-8 sm:px-2",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35",
            isTeamDraft
              ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15"
              : "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/50 hover:text-foreground",
          )}
          title={t.chatInputBox.collaborators}
        >
          {totalCount > 1 ? (
            <UsersRoundIcon className="size-4 shrink-0" />
          ) : (
            <UserIcon className="size-4 shrink-0" />
          )}
          <span className="hidden min-w-0 truncate sm:inline">
            {activeMeta?.label ?? t.chatInputBox.collaboratorsSingle}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 shrink-0 rounded-md px-1.5 py-0.5 mr-1 text-xs transition-all duration-base",
              isTeamDraft
                ? "bg-primary-foreground/80 text-primary font-semibold"
                : hasOnlineMembers
                  ? "bg-success/10 text-success"
                  : "bg-transparent text-muted-foreground group-hover:bg-background/75 group-hover:text-foreground",
            )}
          >
            {hasOnlineMembers && (
              <span className="size-1.5 rounded-full bg-success" />
            )}
            {hasOnlineMembers ? `${onlineCount}/${totalCount}` : countLabel}
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={8}
        className="w-[min(22rem,calc(100vw-1rem))] overflow-hidden rounded-lg border-border-default p-0 shadow-[var(--shadow-xs)]"
      >
        <div className="border-b border-border-subtle px-3 py-2.5">
          <div className="flex items-center justify-between gap-3">
            <div className="flex min-w-0 items-center gap-2 text-xs font-medium">
              <UsersRoundIcon className="size-4 text-primary" />
              <span className="truncate">{t.chatInputBox.collaborators}</span>
            </div>
            <button
              type="button"
              onClick={() => onSelectedAgentIdsChange([])}
              className="rounded-lg px-2 py-1 text-xs text-muted-foreground transition-all duration-base hover:bg-muted/70 hover:text-foreground"
            >
              {t.chatInputBox.collaboratorsSingle}
            </button>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {TEAM_MODES.map((mode) => {
              const meta = teamModeMeta[mode];
              const Icon = meta.icon;
              const active = isTeamDraft && teamMode === mode;
              return (
                <button
                  key={mode}
                  type="button"
                  disabled={!isTeamDraft}
                  onClick={() => onTeamModeChange(mode)}
                  title={meta.description}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition-all duration-base",
                    active
                      ? "border-primary/30 bg-primary/10 text-primary"
                      : "border-border-default text-muted-foreground hover:bg-muted/55 hover:text-foreground",
                    !isTeamDraft &&
                      "cursor-not-allowed opacity-45 hover:bg-transparent",
                  )}
                >
                  <Icon className="size-3.5" />
                  {meta.label}
                </button>
              );
            })}
          </div>
          {roster.length > 0 && (
            <div className="mt-2 grid grid-cols-1 gap-1">
              {roster.slice(0, 4).map((entry) => {
                const isLeader = entry.role === "tl";
                const agent = agentByName.get(entry.agent_id);
                const handleRemove = () => {
                  if (agent) {
                    toggleAgent(agent);
                  } else {
                    onSelectedAgentIdsChange(
                      selectedAgentIds.filter((id) => id !== entry.agent_id),
                    );
                  }
                };
                const content = (
                  <>
                    <span className="grid size-6 shrink-0 place-items-center overflow-hidden rounded-md bg-background text-xs font-semibold text-muted-foreground">
                      {entry.avatar_url ? (
                        <img
                          src={entry.avatar_url}
                          alt={entry.display_name}
                          className="size-full object-cover"
                        />
                      ) : entry.icon?.trim() ? (
                        <span className="text-sm leading-none">
                          {entry.icon}
                        </span>
                      ) : (
                        entry.display_name.charAt(0).toUpperCase()
                      )}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">
                      {entry.display_name}
                    </span>
                    {isLeader ? (
                      <span className="shrink-0 text-xs text-muted-foreground">
                        {t.agentWorkbenchPanel.mainController}
                      </span>
                    ) : (
                      <span className="shrink-0 rounded p-0.5 text-muted-foreground opacity-60 transition-all duration-base group-hover:opacity-100">
                        <XIcon className="size-3.5" />
                      </span>
                    )}
                  </>
                );
                if (isLeader) {
                  return (
                    <div
                      key={entry.agent_id}
                      className="flex min-w-0 items-center gap-2 rounded-lg bg-muted/35 px-2 py-1.5"
                    >
                      {content}
                    </div>
                  );
                }
                return (
                  <button
                    key={entry.agent_id}
                    type="button"
                    onClick={handleRemove}
                    className="group flex min-w-0 w-full items-center gap-2 rounded-lg bg-muted/35 px-2 py-1.5 text-left transition-all duration-base hover:bg-destructive/10 hover:text-destructive"
                    title="点击移除"
                  >
                    {content}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <div className="p-3">
          <label className="flex h-9 items-center gap-2 rounded-lg border border-border-default bg-background/45 px-2.5 transition-all duration-base hover:border-border-strong hover:bg-background/60 focus-within:border-ring focus-within:bg-background focus-within:ring-2 focus-within:ring-ring/20">
            <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={t.chatInputBox.collaboratorsSearchPlaceholder}
              aria-label={t.chatInputBox.collaboratorsSearchPlaceholder}
              className="h-auto min-w-0 flex-1 border-0 bg-transparent p-0 text-xs shadow-none outline-none placeholder:text-muted-foreground/45 focus-visible:ring-0 focus-visible:ring-offset-0"
            />
          </label>
          {selectedAgents.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedAgents.map((agent) => (
                <button
                  key={agent.name}
                  type="button"
                  onClick={() => toggleAgent(agent)}
                  className="group inline-flex max-w-full items-center gap-1 rounded-lg border border-primary/20 bg-primary/8 px-1.5 py-0.5 text-xs text-primary transition-all duration-base hover:bg-destructive/10 hover:border-destructive/30 hover:text-destructive"
                >
                  <AgentAvatar
                    agent={agent}
                    className="size-4 rounded text-xs"
                  />
                  <span className="truncate">
                    {agent.display_name ?? agent.name}
                  </span>
                  <XIcon className="size-3 shrink-0 opacity-60 transition-opacity group-hover:opacity-100" />
                </button>
              ))}
            </div>
          )}
          <div className="mt-2 max-h-60 overflow-y-auto pr-1">
            <div className="space-y-1">
              {availableAgents.slice(0, 18).map((agent) => {
                const selected = selectedSet.has(agent.name);
                const label = agent.display_name ?? agent.name;
                return (
                  <button
                    key={agent.name}
                    type="button"
                    onClick={() => toggleAgent(agent)}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-all duration-base",
                      selected ? "bg-primary/8" : "hover:bg-muted/55",
                    )}
                  >
                    <AgentAvatar
                      agent={agent}
                      className="size-7 rounded-md text-xs"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium">
                        {label}
                      </span>
                      <span className="block truncate text-xs text-muted-foreground">
                        {agent.description || agent.name}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "grid size-5 shrink-0 place-items-center rounded-md border transition-all duration-base",
                        selected
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border-default text-transparent",
                      )}
                    >
                      <CheckIcon className="size-3.5" />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end border-t border-border-subtle p-2">
          <button
            type="button"
            onClick={() => void handleCopyLink()}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-muted-foreground transition-all duration-base hover:bg-muted/60 hover:text-foreground"
          >
            <CopyIcon className="size-3.5" />
            {t.collab.copyLink}
          </button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
