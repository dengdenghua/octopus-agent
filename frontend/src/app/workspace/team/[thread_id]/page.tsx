import {
  BotIcon,
  CheckCircle2Icon,
  Code2Icon,
  ClipboardListIcon,
  FolderPlusIcon,
  Loader2Icon,
  MonitorIcon,
  PanelRightIcon,
  PauseCircleIcon,
  PlusIcon,
  UserCogIcon,
  UserPlusIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import { ChatHeaderMenuButton } from "@/components/workspace/chat-header-menu-button";
import { ChatsDrawer } from "@/components/workspace/chats-drawer";
import { ChatPageLayout } from "@/components/workspace/chat-page-layout";
import {
  CreateTeamDialog,
  type TeamConfig,
} from "@/components/workspace/create-team-dialog";
import { TeamInputBox } from "@/components/workspace/team-input-box";
import {
  CollabProvider,
  InviteDialog,
  PresenceAvatars,
  TeamMembersDialog,
  TeamWorkbenchPanel,
  type TeamTaskProgressEvent,
  type TeamWorkbenchTabId,
  useCollab,
} from "@/components/workspace/collab";
import {
  MessageList,
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
} from "@/components/workspace/messages";
import { ChatStreamingFooter } from "@/components/workspace/chat-streaming-footer";
import { ThreadProviders } from "@/components/workspace/messages/context";
import {
  PlanButton,
  PlanPanel,
  computePlanSteps,
} from "@/components/workspace/plan-panel";
import { TodoList } from "@/components/workspace/todo-list";
import { TokenUsageIndicator } from "@/components/workspace/token-usage-indicator";
import { Welcome } from "@/components/workspace/welcome";
import { WorkDirSelector } from "@/components/workspace/workdir-selector";
import { LocalAgentConnectDialog } from "@/components/workspace/agents/local-agent-connect-dialog";
import {
  useRegenerateHandler,
  usePlanActionHandler,
} from "@/components/workspace/use-thread-page";
import { swallow } from "@/core/utils/log";
import { SubtasksProvider } from "@/core/tasks/context";
import { useThreadSettings } from "@/core/settings";
import {
  createTeam,
  dispatchTeamUpdated,
  fetchTeams,
  migrateLegacyTeamsIfNeeded,
  readPreferredTeamId,
  readTeamParticipantIdForTeam,
  writePreferredTeam,
  type Team,
} from "@/core/teams";
import { useCreateTeamTask, type TaskAssignee } from "@/core/team-tasks";
import { useThreadStream } from "@/core/threads/hooks";
import { type TeamMode } from "@/components/workspace/team-mode-picker";
import { isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { isAIMessage } from "@/core/api/types";
import {
  extractCodeBlocks,
  hasPreviewableBlocks,
} from "@/lib/extract-code-blocks";

const LivePreviewPanel = lazy(() =>
  import("@/components/workspace/live-preview-panel").then((m) => ({
    default: m.LivePreviewPanel,
  })),
);

function isParticipantRemoved(team: Team, participantId: string) {
  return (
    team.participants?.some(
      (participant) =>
        participant.id === participantId && participant.status === "removed",
    ) ?? false
  );
}

function filterRemovedTeamsForLocalUser(teams: Team[]) {
  return teams.filter((team) => {
    const participantId = readTeamParticipantIdForTeam(team);
    return !isParticipantRemoved(team, participantId);
  });
}

function teamTaskTitleFromText(text: string) {
  const firstLine = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean);
  const title = firstLine || "Team task";
  return title.length > 80 ? `${title.slice(0, 77)}...` : title;
}

function readInitialTeamWorkDir(threadId?: string | null) {
  // No hardcoded fallback — first-time users must explicitly pick a
  // workspace folder. An empty string here means "no folder chosen
  // yet"; the WorkDirSelector renders a prompt CTA in that state.
  if (typeof window === "undefined") return "";
  try {
    const candidates = [
      threadId ? window.localStorage.getItem(`team:workdir:${threadId}`) : null,
      window.localStorage.getItem("team:workdir:lastUsed"),
      window.localStorage.getItem("code:workdir:lastUsed"),
    ];
    for (const candidate of candidates) {
      if (candidate && isAbsolutePath(candidate)) return candidate;
    }

    const recent = window.localStorage.getItem("octopus:recentWorkdirs");
    const parsed = recent ? JSON.parse(recent) : [];
    if (Array.isArray(parsed)) {
      const firstValid = parsed.find(
        (item): item is string =>
          typeof item === "string" && isAbsolutePath(item),
      );
      if (firstValid) return firstValid;
    }
  } catch (e) {
    swallow(e, "storage");
  }
  return "";
}

function TeamRoomMessageStrip() {
  const { currentUser, roomMessages } = useCollab();
  const remoteMessages = useMemo(
    () =>
      roomMessages
        .filter((message) => message.participant_id !== currentUser?.id)
        .slice(-3),
    [currentUser?.id, roomMessages],
  );

  if (remoteMessages.length === 0) return null;

  return (
    <div className="rounded-lg border border-border/60 bg-muted/25 px-3 py-2 shadow-sm">
      <div className="flex flex-col gap-1">
        {remoteMessages.map((message) => (
          <div
            key={message.message_id}
            className="flex min-w-0 items-center gap-2 text-xs"
          >
            <span className="shrink-0 font-medium text-foreground">
              {message.display_name}
            </span>
            <span className="min-w-0 truncate text-muted-foreground">
              {message.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TeamTaskProgressFeed({ onOpenTasks }: { onOpenTasks: () => void }) {
  const { taskEvents } = useCollab();
  const latestEvents = useMemo(() => {
    const byTask = new Map<string, TeamTaskProgressEvent>();
    for (const event of taskEvents) {
      byTask.set(event.task_id, event);
    }
    return Array.from(byTask.values())
      .sort((a, b) => a.server_time.localeCompare(b.server_time))
      .slice(-2);
  }, [taskEvents]);

  if (latestEvents.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {latestEvents.map((event) => (
        <TeamTaskProgressCard
          key={event.id}
          event={event}
          onOpenTasks={onOpenTasks}
        />
      ))}
    </div>
  );
}

function TeamTaskProgressCard({
  event,
  onOpenTasks,
}: {
  event: TeamTaskProgressEvent;
  onOpenTasks: () => void;
}) {
  const status = event.task?.status ?? "running";
  const statusMeta = getTeamTaskStatusMeta(status);
  const StatusIcon = statusMeta.Icon;
  const progress = getTeamTaskProgressPercent(event);
  const roleLabel = formatTeamRole(event.role);

  return (
    <section className="rounded-lg border border-border/65 bg-background/90 px-3 py-2.5 shadow-sm">
      <div className="flex min-w-0 items-start gap-2.5">
        <span
          className={cn(
            "mt-0.5 grid size-8 shrink-0 place-items-center rounded-md",
            statusMeta.iconClassName,
          )}
        >
          <StatusIcon
            className={cn("size-4", status === "running" && "animate-spin")}
          />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {event.task?.title || "Team 任务"}
            </h3>
            <span
              className={cn(
                "shrink-0 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                statusMeta.badgeClassName,
              )}
            >
              {statusMeta.label}
            </span>
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>{formatTeamTaskEvent(event.event, roleLabel)}</span>
            {event.completed_roles != null && event.total_roles != null && (
              <span>
                {event.completed_roles}/{event.total_roles} 角色完成
              </span>
            )}
            {event.error && (
              <span className="text-destructive">{event.error}</span>
            )}
          </div>
          {typeof progress === "number" && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-300",
                  status === "failed"
                    ? "bg-destructive"
                    : status === "done"
                      ? "bg-emerald-500"
                      : "bg-primary",
                )}
                style={{ width: `${progress}%` }}
              />
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 shrink-0 rounded-md px-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={onOpenTasks}
        >
          查看待办
        </Button>
      </div>
    </section>
  );
}

function getTeamTaskStatusMeta(status: string) {
  switch (status) {
    case "done":
      return {
        label: "已完成",
        Icon: CheckCircle2Icon,
        iconClassName: "bg-emerald-500/10 text-emerald-600",
        badgeClassName: "bg-emerald-500/10 text-emerald-700",
      };
    case "failed":
      return {
        label: "异常",
        Icon: XCircleIcon,
        iconClassName: "bg-destructive/10 text-destructive",
        badgeClassName: "bg-destructive/10 text-destructive",
      };
    case "cancelled":
      return {
        label: "已暂停",
        Icon: PauseCircleIcon,
        iconClassName: "bg-muted text-muted-foreground",
        badgeClassName: "bg-muted text-muted-foreground",
      };
    case "running":
      return {
        label: "运行中",
        Icon: Loader2Icon,
        iconClassName: "bg-primary/10 text-primary",
        badgeClassName: "bg-primary/10 text-primary",
      };
    default:
      return {
        label: "待运行",
        Icon: ClipboardListIcon,
        iconClassName: "bg-amber-500/10 text-amber-700",
        badgeClassName: "bg-amber-500/10 text-amber-700",
      };
  }
}

function getTeamTaskProgressPercent(event: TeamTaskProgressEvent) {
  if (event.task?.status === "done") return 100;
  if (event.task?.status === "failed" || event.task?.status === "cancelled") {
    return 100;
  }
  if (typeof event.progress === "number") {
    return Math.max(0, Math.min(100, Math.round(event.progress * 100)));
  }
  if (event.task?.status === "running") return 8;
  return undefined;
}

function formatTeamTaskEvent(event: string, roleLabel: string | null) {
  switch (event) {
    case "run_started":
      return "任务已启动";
    case "team_role_start":
      return roleLabel ? `${roleLabel} 开始执行` : "角色开始执行";
    case "role_completed":
    case "team_role_end":
      return roleLabel ? `${roleLabel} 已完成` : "一个角色已完成";
    case "run_done":
      return "任务完成，产物已写回";
    case "run_failed":
      return "任务运行失败";
    case "run_cancelled":
      return "任务已暂停";
    default:
      return roleLabel ? `${roleLabel} 有新进展` : "任务有新进展";
  }
}

function formatTeamRole(role?: string | null) {
  if (!role) return null;
  const normalized = role.replace(/^Role\./, "").toLowerCase();
  const labels: Record<string, string> = {
    planner: "规划者",
    researcher: "调研员",
    generator: "执行者",
    implementer: "执行者",
    critic: "评审者",
    synthesizer: "整理者",
    evaluator: "验收者",
  };
  return labels[normalized] ?? normalized;
}

function TeamThreadUpdateBridge({
  refresh,
  isLoading,
}: {
  refresh: () => Promise<void>;
  isLoading: boolean;
}) {
  const { notifyThreadUpdate } = useCollab();
  const wasLoadingRef = useRef(false);

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<{ reason?: string }>).detail;
      void refresh();
      if (detail?.reason === "submitted") {
        window.setTimeout(() => void refresh(), 1500);
      }
    };
    window.addEventListener("octopus:team-thread-update", handler);
    return () =>
      window.removeEventListener("octopus:team-thread-update", handler);
  }, [refresh]);

  useEffect(() => {
    if (isLoading && !wasLoadingRef.current) {
      notifyThreadUpdate("submitted");
    } else if (!isLoading && wasLoadingRef.current) {
      notifyThreadUpdate("finished");
    }
    wasLoadingRef.current = isLoading;
  }, [isLoading, notifyThreadUpdate]);

  return null;
}

export default function TeamPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { threadId, isNewThread, setIsNewThread } = useThreadChat();
  const [settings, setSettings] = useThreadSettings(threadId);
  const [mounted, setMounted] = useState(false);
  const [teamMode, setTeamMode] = useState<TeamMode>("chat");
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [teams, setTeams] = useState<Team[]>([]);
  const [teamConfig, setTeamConfig] = useState<Team | null>(null);
  const [workDir, setWorkDir] = useState(() =>
    readInitialTeamWorkDir(threadId),
  );
  // Right-side workbench mirrors the agent chat drawer: one shell,
  // multiple pages inside it.
  const [showTeamWorkbench, setShowTeamWorkbench] = useState(false);
  const [teamWorkbenchTab, setTeamWorkbenchTab] =
    useState<TeamWorkbenchTabId>("tasks");
  const [planOpen, setPlanOpen] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [showInvite, setShowInvite] = useState(false);
  const [showMembers, setShowMembers] = useState(false);
  const [connectLocalAgentOpen, setConnectLocalAgentOpen] = useState(false);
  const [chatsDrawerOpen, setChatsDrawerOpen] = useState(false);
  const [selectedTaskAgentIds, setSelectedTaskAgentIds] = useState<string[]>(
    [],
  );
  const teamId = teamConfig?.id;
  const participantId = useMemo(
    () => readTeamParticipantIdForTeam(teamConfig),
    [teamConfig],
  );
  const currentParticipant = useMemo(
    () =>
      teamConfig?.participants?.find(
        (participant) => participant.id === participantId,
      ) ?? null,
    [participantId, teamConfig?.participants],
  );
  const participantRole = currentParticipant?.role ?? "member";
  const currentParticipantRemoved = currentParticipant?.status === "removed";
  const isCoworkMode = teamMode === "cowork";
  const canRunTeamTask =
    !currentParticipantRemoved &&
    (participantRole === "owner" || participantRole === "member");
  const canCreateTeamTask = isCoworkMode && canRunTeamTask;
  const canInvite =
    !currentParticipantRemoved &&
    (participantRole === "owner" || participantRole === "member");
  const canManageMembers =
    !currentParticipantRemoved && participantRole === "owner";
  const participantDisplayName = currentParticipant?.display_name ?? "You";
  const selectedTaskAgents = useMemo(() => {
    const selected = new Set(selectedTaskAgentIds);
    return (teamConfig?.members ?? []).filter((member) =>
      selected.has(member.name),
    );
  }, [selectedTaskAgentIds, teamConfig?.members]);
  const createTeamTask = useCreateTeamTask();
  const removalHandledRef = useRef(false);

  useEffect(() => {
    if (!teamConfig?.members) {
      setSelectedTaskAgentIds([]);
      return;
    }
    const available = new Set(teamConfig.members.map((member) => member.name));
    setSelectedTaskAgentIds((prev) => {
      const next = prev.filter((agentId) => available.has(agentId));
      if (next.length === prev.length) return prev;
      return next;
    });
  }, [teamConfig?.members]);

  const applyTeam = useCallback((team: Team | null) => {
    setTeamConfig(team);
    writePreferredTeam(team);
    dispatchTeamUpdated(team);
  }, []);

  const leaveRemovedTeam = useCallback(
    (removedTeamId?: string) => {
      if (removalHandledRef.current) return;
      removalHandledRef.current = true;
      const remaining = filterRemovedTeamsForLocalUser(
        teams.filter((team) => team.id !== removedTeamId),
      );
      setTeams(remaining);
      applyTeam(remaining[0] ?? null);
      setShowInvite(false);
      setShowMembers(false);
      toast.warning("你已被移出该 Team");
      navigate("/workspace/team/new", { replace: true });
      window.setTimeout(() => {
        removalHandledRef.current = false;
      }, 1500);
    },
    [applyTeam, navigate, teams],
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const remote = filterRemovedTeamsForLocalUser(
          await migrateLegacyTeamsIfNeeded(await fetchTeams()),
        );
        if (cancelled) return;
        setTeams(remote);
        const preferred = readPreferredTeamId();
        const next =
          (preferred ? remote.find((team) => team.id === preferred) : null) ??
          remote[0] ??
          null;
        applyTeam(next);
      } catch (error) {
        console.warn("[team] failed to load team rooms", error);
      }
    };
    void load();
    const refresh = () => void load();
    window.addEventListener("octopus:teams-refresh", refresh);
    return () => {
      cancelled = true;
      window.removeEventListener("octopus:teams-refresh", refresh);
    };
  }, [applyTeam]);

  useEffect(() => {
    if (!teamConfig && teams.length > 0) {
      applyTeam(teams[0] ?? null);
    }
  }, [applyTeam, teamConfig, teams]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !workDir || !isAbsolutePath(workDir))
      return;
    try {
      if (threadId) {
        window.localStorage.setItem(`team:workdir:${threadId}`, workDir);
      }
      window.localStorage.setItem("team:workdir:lastUsed", workDir);
    } catch (e) {
      swallow(e);
    }
  }, [threadId, workDir]);

  useEffect(() => {
    const handler = (event: Event) => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path;
      if (path && isAbsolutePath(path)) {
        setWorkDir(path);
      }
    };
    window.addEventListener("octopus:workdir-selected", handler);
    return () =>
      window.removeEventListener("octopus:workdir-selected", handler);
  }, []);

  useEffect(() => {
    const handler = () => setShowCreateTeam(true);
    window.addEventListener("octopus:create-team", handler);
    return () => window.removeEventListener("octopus:create-team", handler);
  }, []);

  useEffect(() => {
    const handler = (e: CustomEvent<Team>) => {
      const team = e.detail;
      applyTeam(team);
    };
    window.addEventListener("octopus:select-team", handler as EventListener);
    return () =>
      window.removeEventListener(
        "octopus:select-team",
        handler as EventListener,
      );
  }, [applyTeam]);

  useEffect(() => {
    const handler = (e: CustomEvent<Team>) => {
      const team = e.detail;
      if (
        team.id === teamConfig?.id &&
        isParticipantRemoved(team, participantId)
      ) {
        leaveRemovedTeam(team.id);
        return;
      }
      setTeams((prev) =>
        prev.map((item) => (item.id === team.id ? team : item)),
      );
      if (team.id === teamConfig?.id) {
        applyTeam(team);
      }
    };
    window.addEventListener(
      "octopus:team-room-updated",
      handler as EventListener,
    );
    return () =>
      window.removeEventListener(
        "octopus:team-room-updated",
        handler as EventListener,
      );
  }, [applyTeam, leaveRemovedTeam, participantId, teamConfig?.id]);

  useEffect(() => {
    const handler = (
      event: CustomEvent<{
        teamId?: string;
        participantId?: string;
        reason?: string;
      }>,
    ) => {
      const detail = event.detail;
      if (detail?.teamId && detail.teamId !== teamConfig?.id) return;
      if (detail?.participantId && detail.participantId !== participantId)
        return;
      leaveRemovedTeam(detail?.teamId ?? teamConfig?.id);
    };
    window.addEventListener("octopus:team-removed", handler as EventListener);
    return () =>
      window.removeEventListener(
        "octopus:team-removed",
        handler as EventListener,
      );
  }, [leaveRemovedTeam, participantId, teamConfig?.id]);

  const [thread, sendMessage, , liveToolEvents, lastTurnToolEvents] =
    useThreadStream({
      threadId: isNewThread ? undefined : threadId,
      context: {
        ...settings.context,
        mode: "team",
        // Route the turn to the team leader's backend agent preset.
        // Team mode uses the same agent as chat mode (e.g. "coder" is
        // the same person whether in chat or team — they're just
        // "pulled into the group").
        agent_name: teamConfig?.leaderId ?? "general",
        subagent_enabled: isCoworkMode,
        is_plan_mode: isCoworkMode,
        // Chat keeps the roster in context but routes through the
        // single-LLM TL path; cowork enters the heavy swarm/cowork
        // executor. Backend only branches on this field.
        team_mode: isCoworkMode ? "cowork" : "chat",
        // Send the full roster (agent_id + display_name + role) so the
        // backend's `_resolve_agent_roster` can drive routing/swarm/vote.
        // ``Agent.name`` is the registered backend agent_id (coder /
        // general / vibe_selling …) — the same key used by the agent
        // registry. Without these objects the backend fell back to the
        // legacy `team_members: string[]` path, which couldn't tag the TL
        // and silently degraded into a single-agent turn.
        agent_roster:
          teamConfig?.members.map((m) => ({
            agent_id: m.name,
            display_name: m.display_name ?? m.name,
            avatar_url: m.avatar_url ?? undefined,
            role: m.name === teamConfig.leaderId ? "tl" : "member",
          })) ?? [],
        // Keep legacy fields for any consumer that still reads them.
        team_members:
          teamConfig?.members.map((m) => m.display_name ?? m.name) ?? [],
        team_leader:
          teamConfig?.members.find((m) => m.name === teamConfig.leaderId)
            ?.display_name ?? null,
        team_id: teamId,
        team_name: teamConfig?.name ?? undefined,
        project: teamConfig?.name ? `Team · ${teamConfig.name}` : "Team",
        workspace_path: workDir,
        task_agent_refs: selectedTaskAgents.map((agent) => agent.name),
        task_agent_names: selectedTaskAgents.map(
          (agent) => agent.display_name ?? agent.name,
        ),
      },
      onStart: (startedThreadId) => {
        setIsNewThread(false);
        const targetPath = `/workspace/team/${startedThreadId}`;
        if (
          typeof window === "undefined" ||
          window.location.pathname !== targetPath
        ) {
          navigate(targetPath, { replace: true });
        }
      },
    });
  const hasActiveTeamToolEvent = useMemo(
    () =>
      [...liveToolEvents, ...lastTurnToolEvents].some(
        (event) =>
          event.status === "running" || event.status === "waiting_approval",
      ),
    [lastTurnToolEvents, liveToolEvents],
  );
  const teamInputStatus =
    thread.error
      ? "error"
      : thread.isLoading && (thread.streamingMessage || hasActiveTeamToolEvent)
        ? "streaming"
        : "ready";

  // See chats/[thread_id]/page.tsx for the rationale — if the first
  // stream fails before onStart fires, isNewThread can stay stuck at
  // true while messages already rendered, producing a Welcome overlay
  // on top of the live conversation. Watching messages.length gives a
  // defensive second source of truth.
  useEffect(() => {
    if (isNewThread && thread.messages.length > 0) {
      setIsNewThread(false);
      const targetPath = `/workspace/team/${threadId}`;
      if (
        typeof window === "undefined" ||
        window.location.pathname !== targetPath
      ) {
        navigate(targetPath, { replace: true });
      }
    }
  }, [isNewThread, navigate, thread.messages.length, setIsNewThread, threadId]);

  useRegenerateHandler(thread, sendMessage, threadId);
  usePlanActionHandler(sendMessage, threadId);

  const previewBlocks = useMemo(() => {
    for (let i = thread.messages.length - 1; i >= 0; i--) {
      const msg = thread.messages[i];
      if (!msg || !isAIMessage(msg)) continue;
      const text =
        typeof msg.content === "string"
          ? msg.content
          : msg.content
              .filter(
                (c): c is { type: "text"; text: string } => c.type === "text",
              )
              .map((c) => c.text)
              .join("\n");
      const blocks = extractCodeBlocks(text);
      if (hasPreviewableBlocks(blocks)) return blocks;
    }
    return null;
  }, [thread.messages]);

  useEffect(() => {
    if (previewBlocks && !showPreview) setShowPreview(true);
  }, [previewBlocks]);

  const createTaskFromSubmit = useCallback(
    async (text: string) => {
      if (!teamId || !canCreateTeamTask) return;
      const assignees: TaskAssignee[] = selectedTaskAgents.map((agent) => ({
        kind: "agent",
        ref: agent.name,
      }));
      try {
        await createTeamTask.mutateAsync({
          room_id: teamId,
          title: teamTaskTitleFromText(text),
          description: text,
          assignees,
          metadata: {
            source: "team_input",
            thread_id: isNewThread ? undefined : threadId,
            team_mode: teamMode,
          },
        });
        setShowTeamWorkbench(true);
        setTeamWorkbenchTab("tasks");
      } catch (error) {
        toast.error(
          error instanceof Error ? error.message : "创建团队待办失败",
        );
      }
    },
    [
      canCreateTeamTask,
      createTeamTask,
      isNewThread,
      selectedTaskAgents,
      teamId,
      teamMode,
      threadId,
    ],
  );

  const handleSubmit = useCallback(
    (message: { text: string }) => {
      const taskAgentNames = selectedTaskAgents.map(
        (agent) => agent.display_name ?? agent.name,
      );
      const text =
        taskAgentNames.length > 0
          ? `本次任务优先交给：${taskAgentNames.join("、")}。\n\n${message.text}`
          : message.text;
      void createTaskFromSubmit(message.text);
      void sendMessage(threadId, { text, files: [] });
    },
    [createTaskFromSubmit, selectedTaskAgents, sendMessage, threadId],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  const handleCreateTeam = useCallback(
    async (config: TeamConfig) => {
      const newTeam = await createTeam({
        name: config.name,
        members: config.members,
        leaderId: config.leaderId,
      });
      setTeams((prev) => [
        newTeam,
        ...prev.filter((team) => team.id !== newTeam.id),
      ]);
      applyTeam(newTeam);
      if (!isNewThread) {
        navigate("/workspace/team/new");
      }
    },
    [applyTeam, isNewThread, navigate],
  );

  const handleStartCodingProject = useCallback(() => {
    setTeamMode("cowork");
    if (typeof window !== "undefined") {
      window.dispatchEvent(
        new CustomEvent("octopus:edit-message", {
          detail: { text: "新建一个编程项目：" },
        }),
      );
    }
  }, []);

  const planSteps = useMemo(
    () =>
      computePlanSteps(thread.messages, thread.values.todos, {
        completed: t.planPanel.completed,
        inProgress: t.planPanel.inProgress,
        pending: t.planPanel.pending,
      }),
    [thread.messages, thread.values.todos, t],
  );
  const completedPlanSteps = useMemo(
    () => planSteps.filter((s) => s.status === "completed").length,
    [planSteps],
  );

  return (
    <ArtifactsProvider threadId={threadId}>
      <SubtasksProvider>
        <ThreadProviders thread={thread} isMock={false}>
          <CollabProvider
            teamId={teamId}
            threadId={threadId}
            participantId={participantId}
            displayName={participantDisplayName}
            autoConnect={Boolean(teamId)}
          >
            <TeamThreadUpdateBridge
              refresh={thread.refresh}
              isLoading={thread.isLoading}
            />
            <ChatBox threadId={threadId}>
              <ChatPageLayout
                isNewThread={isNewThread}
                headerClassName="pl-3"
                header={
                  <>
                    <ChatHeaderMenuButton
                      onClick={() => setChatsDrawerOpen(true)}
                    />
                    <div className="flex min-w-0 items-center gap-2">
                      <WorkDirSelector
                        workDir={workDir}
                        onWorkDirChange={setWorkDir}
                        className="min-w-0 max-w-[min(46vw,24rem)]"
                      />
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 shrink-0 rounded-lg border border-transparent text-muted-foreground transition-all hover:border-border/50 hover:bg-muted/50 hover:text-foreground"
                            title="新建 / 接入"
                          >
                            <PlusIcon className="size-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="w-48">
                          <DropdownMenuItem
                            onSelect={() => setShowCreateTeam(true)}
                          >
                            <FolderPlusIcon className="size-4" />
                            新建项目
                          </DropdownMenuItem>
                          <DropdownMenuItem onSelect={handleStartCodingProject}>
                            <Code2Icon className="size-4" />
                            新建编程项目
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => setConnectLocalAgentOpen(true)}
                          >
                            <BotIcon className="size-4" />
                            接入本地伙伴
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    <div className="ml-auto flex items-center gap-2">
                      {teamId && (
                        <>
                          <PresenceAvatars className="hidden md:flex" />
                          {canInvite && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8 rounded-lg border border-transparent text-muted-foreground transition-all hover:border-border/50 hover:bg-muted/50 hover:text-foreground"
                              onClick={() => setShowInvite(true)}
                              title={t.collab.inviteCollaborators}
                            >
                              <UserPlusIcon className="size-4" />
                            </Button>
                          )}
                          {canManageMembers && (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="size-8 rounded-lg border border-transparent text-muted-foreground transition-all hover:border-border/50 hover:bg-muted/50 hover:text-foreground"
                              onClick={() => setShowMembers(true)}
                              title="成员管理"
                            >
                              <UserCogIcon className="size-4" />
                            </Button>
                          )}
                        </>
                      )}
                      {planSteps.length > 0 && (
                        <div className="relative">
                          {planOpen && (
                            <div className="absolute top-full right-0 z-20 mt-2 animate-in slide-in-from-top-2 fade-in duration-200">
                              <PlanPanel
                                messages={thread.messages}
                                todos={thread.values.todos}
                                open={planOpen}
                                onClose={() => setPlanOpen(false)}
                              />
                            </div>
                          )}
                          <PlanButton
                            onClick={() => setPlanOpen((v) => !v)}
                            stepCount={planSteps.length}
                            completedCount={completedPlanSteps}
                            isActive={planOpen}
                          />
                        </div>
                      )}
                      <TokenUsageIndicator messages={thread.messages} />
                      {previewBlocks && (
                        <button
                          onClick={() => setShowPreview((v) => !v)}
                          className={cn(
                            "flex size-8 items-center justify-center rounded-lg border border-transparent transition-all duration-200 hover:border-border/50 hover:bg-muted/50",
                            showPreview &&
                              "bg-primary/10 text-primary border-primary/20",
                            !showPreview && "text-muted-foreground",
                          )}
                          title={
                            showPreview
                              ? t.livePreview.hidePanel
                              : t.livePreview.showPanel
                          }
                        >
                          <MonitorIcon className="size-4" />
                        </button>
                      )}
                      <Button
                        data-testid="team-workbench-toggle"
                        variant="ghost"
                        size="icon"
                        className={cn(
                          "size-8 rounded-lg border transition-all",
                          showTeamWorkbench
                            ? "border-primary/20 bg-primary/10 text-primary"
                            : "border-transparent hover:border-border/50 hover:bg-muted/50",
                        )}
                        onClick={() => {
                          setShowTeamWorkbench((open) => !open);
                          if (!showTeamWorkbench) setTeamWorkbenchTab("tasks");
                        }}
                        title={
                          showTeamWorkbench
                            ? "关闭 Team 工作台"
                            : "打开 Team 工作台"
                        }
                      >
                        <PanelRightIcon className="size-4" />
                      </Button>
                    </div>
                  </>
                }
                messageList={
                  <MessageList
                    className="size-full"
                    threadId={threadId}
                    thread={thread}
                    paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                    mode={isCoworkMode ? "team" : "chat"}
                    liveToolEvents={liveToolEvents}
                    lastTurnToolEvents={lastTurnToolEvents}
                    footer={
                      <>
                        <TeamTaskProgressFeed
                          onOpenTasks={() => {
                            setShowTeamWorkbench(true);
                            setTeamWorkbenchTab("tasks");
                          }}
                        />
                        <ChatStreamingFooter
                          thread={thread}
                          liveToolEvents={liveToolEvents}
                          threadId={threadId}
                          mode={isCoworkMode ? "team" : "chat"}
                        />
                      </>
                    }
                  />
                }
                inputArea={
                  <div
                    className={cn(
                      "relative w-full transition-all duration-300",
                      isNewThread && "-translate-y-[calc(50vh-96px)]",
                      isNewThread
                        ? "max-w-(--container-width-sm)"
                        : showTeamWorkbench
                          ? "max-w-(--container-width-md)"
                          : "max-w-(--container-width-lg)",
                    )}
                  >
                    <div className="absolute -top-4 right-0 left-0 z-0">
                      <div className="absolute right-0 bottom-0 left-0">
                        <TodoList
                          className="shadow-sm"
                          todos={thread.values.todos ?? []}
                          hidden={
                            !thread.values.todos ||
                            thread.values.todos.length === 0
                          }
                        />
                      </div>
                    </div>
                    {mounted ? (
                      <div className="flex flex-col gap-2">
                        {isNewThread && (
                          <Welcome mode={settings.context.mode} />
                        )}
                        <TeamRoomMessageStrip />
                        <TeamInputBox
                          status={teamInputStatus}
                          workDir={workDir}
                          showWorkDirSelector={false}
                          modelName={settings.context.model_name}
                          teamMode={teamMode}
                          teamMembers={teamConfig?.members ?? []}
                          selectedAgentIds={selectedTaskAgentIds}
                          onSelectedAgentIdsChange={setSelectedTaskAgentIds}
                          submitBehavior={
                            canRunTeamTask ? "run" : "message"
                          }
                          onWorkDirChange={setWorkDir}
                          onTeamModeChange={setTeamMode}
                          onModelChange={(modelName) =>
                            setSettings("context", {
                              ...settings.context,
                              model_name: modelName,
                            })
                          }
                          onSubmit={handleSubmit}
                          onStop={handleStop}
                        />
                      </div>
                    ) : (
                      <div
                        aria-hidden="true"
                        className="workspace-panel h-32 w-full rounded-lg"
                      />
                    )}
                  </div>
                }
                secondaryPanel={
                  showPreview && previewBlocks ? (
                    <div className="ml-3 hidden min-h-0 w-[min(420px,40vw)] shrink-0 flex-col overflow-hidden animate-in slide-in-from-right-2 fade-in duration-200 lg:flex workspace-panel-subtle">
                      <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
                        <div className="flex items-center gap-2">
                          <MonitorIcon className="size-4 text-primary" />
                          <span className="text-sm font-medium">
                            {t.livePreview.title}
                          </span>
                        </div>
                        <button
                          onClick={() => setShowPreview(false)}
                          className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                        >
                          <XIcon className="size-3.5" />
                        </button>
                      </div>
                      <Suspense
                        fallback={
                          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                            {t.livePreview.loading}
                          </div>
                        }
                      >
                        <LivePreviewPanel
                          htmlContent={previewBlocks.html}
                          cssContent={previewBlocks.css}
                          jsContent={previewBlocks.js}
                        />
                      </Suspense>
                    </div>
                  ) : undefined
                }
                sidebar={
                  <TeamWorkbenchPanel
                    activeTab={teamWorkbenchTab}
                    onSelectTab={setTeamWorkbenchTab}
                    onClose={() => setShowTeamWorkbench(false)}
                    roomId={teamId}
                    team={teamConfig}
                    workDir={workDir}
                    onWorkDirChange={setWorkDir}
                    currentParticipantId={participantId}
                    canManageTasks={canRunTeamTask}
                  />
                }
                showSidebar={showTeamWorkbench}
                sidebarWidth="min(600px, 42vw)"
              />
            </ChatBox>

            <CreateTeamDialog
              open={showCreateTeam}
              onOpenChange={setShowCreateTeam}
              onCreateTeam={handleCreateTeam}
            />
            <InviteDialog
              open={showInvite}
              onOpenChange={setShowInvite}
              roomId={teamId ?? ""}
              threadId={threadId}
              team={teamConfig}
              onTeamChange={(team) => {
                setTeams((prev) =>
                  prev.map((item) => (item.id === team.id ? team : item)),
                );
                applyTeam(team);
              }}
            />
            <TeamMembersDialog
              open={showMembers}
              onOpenChange={setShowMembers}
              team={teamConfig}
              currentParticipantId={participantId}
              onTeamChange={(team) => {
                setTeams((prev) =>
                  prev.map((item) => (item.id === team.id ? team : item)),
                );
                applyTeam(team);
              }}
            />
            <LocalAgentConnectDialog
              open={connectLocalAgentOpen}
              onOpenChange={setConnectLocalAgentOpen}
            />
            <ChatsDrawer
              open={chatsDrawerOpen}
              onOpenChange={setChatsDrawerOpen}
            />
          </CollabProvider>
        </ThreadProviders>
      </SubtasksProvider>
    </ArtifactsProvider>
  );
}
