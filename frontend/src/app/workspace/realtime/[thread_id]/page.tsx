import {
  CheckIcon,
  CircleDotIcon,
  Code2Icon,
  CopyIcon,
  FileTextIcon,
  ListChecksIcon,
  PanelRightIcon,
  SearchIcon,
  UserPlusIcon,
  UsersRoundIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  ArtifactPanel,
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts";
import {
  AgentWorkbenchPanel,
  hasAgentWorkbenchContent,
  type AgentWorkbenchTabId,
  type WorkbenchRosterSeat,
  workspaceFocusTabFromEvents,
} from "@/components/workspace/agent-workbench-panel";
import {
  AGENT_WORKBENCH_FOCUS_EVENT,
  AGENT_WORKBENCH_OPEN_EVENT,
  type AgentWorkbenchEventView,
  type AgentWorkbenchFocusDetail,
  type AgentWorkbenchFocusView,
  type AgentWorkbenchOpenDetail,
  type AgentWorkbenchProcessEventKind,
  type AgentWorkbenchProcessEventSnapshot,
} from "@/components/workspace/agent-workbench-events";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import { ChatsDrawer } from "@/components/workspace/chats-drawer";
import { ChatHeaderMenuButton } from "@/components/workspace/chat-header-menu-button";
import {
  ChatInputBox,
  type DeepResearchComposerOptions,
} from "@/components/workspace/chat-input-box";
import type {
  AgentModeName,
  AuditIntensity,
  DetectResponse,
  DetectionSignals,
} from "@/components/workspace/mode-selector";
import type { ReasoningMode } from "@/components/workspace/reasoning-mode";
import type { PersonalMode } from "@/components/workspace/personal-mode-selector";
import { RecRecorderOverlay } from "@/components/workspace/rec-recorder-overlay";
import type { PromptInputFilePart } from "@/core/uploads";
import { ChatPageLayout } from "@/components/workspace/chat-page-layout";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { RealtimeApprovalToasts } from "@/components/workspace/realtime-approval-toasts";
import { DeepResearchHistoryPanel } from "@/components/workspace/deep-research-history-panel";
import { DeepResearchPanel } from "@/components/workspace/deep-research-panel";
import {
  FINAL_DELIVERABLE_PATTERN,
  finalOutputArtifactEntries,
  type DiffEntry,
} from "@/components/workspace/agent-workbench-utils";
import {
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  MessageList,
} from "@/components/workspace/messages";
import { extractResultUrl } from "@/components/workspace/messages/message-output-summary";
import { LoadOlderTurnsBanner } from "@/components/workspace/messages/load-older-turns-banner";
import { ThreadProviders } from "@/components/workspace/messages/context";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { ShareMenu } from "@/components/workspace/share-menu";
import { AgentAvatar } from "@/components/workspace/sidebar-footer";
import {
  useTeamModeMeta,
  TEAM_MODES,
  serveMeshForMode,
  type TeamMode,
} from "@/components/workspace/team-mode-picker";
import { toWorkBlocks } from "@/components/workspace/work-blocks";
import { screenBlocksForAgent } from "@/components/workspace/agent-workbench-snapshot";
import { buildReplayFromBlocks } from "@/components/workspace/replay-from-blocks";
import { buildReplayHtml } from "@/core/sharing/replay-html";
import { downloadTextFile, shareSlug } from "@/core/sharing/download";
import {
  modePresetForAgentMode,
  workflowPresetForMode,
} from "@/core/agent-modes/presets";
import { PlanPanel } from "@/components/workspace/plan-panel";
import { Welcome } from "@/components/workspace/welcome";
import {
  latestPersistedTodoEventsFromMessages,
  restoredTodoEventsForDisplay,
} from "@/components/workspace/persisted-tool-events";
import {
  usePlanActionHandler,
  useRegenerateHandler,
} from "@/components/workspace/use-thread-page";
import { swallow } from "@/core/utils/log";
import { SubtasksProvider } from "@/core/tasks/context";
import { getAPIClient } from "@/core/api";
import { copyTextToClipboard } from "@/core/clipboard";
import { threadCollaborationLink } from "@/core/collaboration/thread-collaboration-link";
import { toHashRouterShellUrl } from "@/core/router/hash-shell-url";
import { taskWorkspaceRoute } from "@/core/router/task-workspace-route";
import { useDeferredRouteCommit } from "@/core/router/use-deferred-route-commit";
import { useThreadSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import { useIsMobile } from "@/hooks/use-mobile";
import type { ReasoningEffort } from "@/core/threads";
import {
  normalizePermissionMode,
  permissionRuntimeConfig,
} from "@/core/permissions";
import { startDeepResearch, type ResearchJob } from "@/core/research/api";
import { getRecordingStatus } from "@/core/teach-repeat/api";
import type { RecordingStatus } from "@/core/teach-repeat/types";
import { ACTIVE_AGENT_EVENT, ACTIVE_AGENT_KEY } from "@/core/agents/active";
import {
  dedupeAgentsByName,
  dedupePersonaAgentsByDisplayName,
  useAgent,
  useAgents,
  useLocalCliAgents,
  useMobileDevices,
  type Agent,
} from "@/core/agents";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { emitAgentChanged, eventBus, useEvent } from "@/core/events";
import {
  consumeTaskCollaboratorPreset,
  TASK_COLLABORATOR_PRESET_EVENT,
  type TaskCollaboratorPreset,
} from "@/core/collaboration/task-collaborator-preset";
import { collaborationRosterFromThread } from "@/core/collaboration/thread-collaboration";
import {
  buildCoworkSelectionSyncPlan,
  coworkGroupToCollaborationRoster,
  coworkSessionToCollaborationRoster,
  useCollabSession,
  useCoworkGroup,
  useEnsureCollabRoom,
  useInviteCoworkMember,
  useRemoveCoworkMember,
  useSetCoworkMode,
} from "@/core/cowork";
import { usePauseTask, useTasks } from "@/core/tasks/hooks";
import { isAIMessage, isHumanMessage, type Message } from "@/core/api/types";
import { useI18n } from "@/core/i18n/hooks";
import { ToolEffectsProvider } from "@/core/observability/tool-effects-context";
import {
  extractContentFromMessage,
  extractTextFromMessage,
} from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { resolveModelContextWindow } from "@/core/models/context-window";
import { getBackendBaseURL } from "@/core/config";
import {
  extractCodeBlocks,
  hasPreviewableBlocks,
} from "@/lib/extract-code-blocks";
import { isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function normalizeReasoningEffortForUi(
  effort: ReasoningEffort | undefined,
): ReasoningEffort | undefined {
  return effort === "max" ? "xhigh" : effort;
}

const CHAT_WORKDIR_KEY = "chat:workdir:lastUsed";
const CODE_WORKDIR_KEY = "code:workdir:lastUsed";
const RECENT_WORKDIRS_KEY = "octopus:recentWorkdirs";
const MAX_RECENT_WORKDIRS = 6;

type ThreadRouteState = {
  threadOwnerAgentId?: string;
  workspacePath?: string;
};

function normalizeWorkDirKey(path: string): string {
  return path.trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
}

function rememberChatWorkDir(dir: string) {
  if (typeof window === "undefined") return;
  try {
    if (!dir || !isAbsolutePath(dir)) {
      window.localStorage.removeItem(CHAT_WORKDIR_KEY);
      return;
    }
    window.localStorage.setItem(CHAT_WORKDIR_KEY, dir);
    window.localStorage.setItem(CODE_WORKDIR_KEY, dir);

    const raw = window.localStorage.getItem(RECENT_WORKDIRS_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    const current = Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === "string")
      : [];
    const next = [
      dir,
      ...current.filter(
        (item) => normalizeWorkDirKey(item) !== normalizeWorkDirKey(dir),
      ),
    ].slice(0, MAX_RECENT_WORKDIRS);
    window.localStorage.setItem(RECENT_WORKDIRS_KEY, JSON.stringify(next));
  } catch (e) {
    swallow(e, "storage");
  }
}

type CompactResult = {
  compacted: boolean;
  reason?: string;
  turnCount?: number;
  keepRecent?: number;
};

type CompactableThread = {
  compact?: () => Promise<CompactResult>;
};

const URL_PATTERN = /https?:\/\/[^\s，,]+/gi;

// Tool names / payloads that imply the run must end with a report-style
// deliverable before it can be considered settled.
const REPORT_DELIVERABLE_PATTERN =
  /deep-research|report|docx|pptx|pdf|research|swarm/i;

const CHAT_STARTER_ICONS: LucideIcon[] = [
  SearchIcon,
  ListChecksIcon,
  FileTextIcon,
  Code2Icon,
];

function extractResearchUrls(text: string): { topic: string; urls: string[] } {
  const urls = Array.from(new Set(text.match(URL_PATTERN) ?? []));
  const topic = text.replace(URL_PATTERN, " ").replace(/\s+/g, " ").trim();
  return { topic: topic || text.trim(), urls };
}

function latestModelContextTokens(messages: Message[]): number | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (!message || !isAIMessage(message)) continue;
    const usage = message.usage_metadata;
    if (!usage) continue;
    const input = Number.isFinite(usage.input_tokens) ? usage.input_tokens : 0;
    const output = Number.isFinite(usage.output_tokens)
      ? usage.output_tokens
      : 0;
    const total = Number.isFinite(usage.total_tokens)
      ? usage.total_tokens
      : input + output;
    return Math.max(0, total);
  }
  return null;
}

function estimateRetainedContextTokens(messages: Message[]): number {
  const chars = messages.reduce(
    (total, message) => total + extractTextFromMessage(message).length,
    0,
  );
  return Math.ceil(chars / 4);
}

function estimateCurrentContextTokens(messages: Message[]): number {
  const latestUsage = latestModelContextTokens(messages);
  const retainedEstimate = estimateRetainedContextTokens(messages);
  return Math.max(latestUsage ?? 0, retainedEstimate);
}

type RightPanelPage =
  | "agent"
  | "artifacts"
  | "plan"
  | "preview"
  | "research"
  | "history";

type ChatCollaborationRosterEntry = {
  agent_id: string;
  name: string;
  display_name: string;
  avatar_url?: string | null;
  icon?: string | null;
  role: "tl" | "member";
};

function RightPanelMenu({
  activePage,
  onClosePanel,
  onOpenAgent,
  onOpenArtifacts,
  onOpenPlan,
  onOpenPreview,
  onOpenResearch,
  onOpenResearchHistory,
  hasAgentWorkbench,
  hasPlan,
  hasPreview,
  hasResearch,
  hasResearchHistory,
  artifactCount,
}: {
  activePage: RightPanelPage | null;
  artifactCount: number;
  hasAgentWorkbench: boolean;
  hasPlan: boolean;
  hasPreview: boolean;
  hasResearch: boolean;
  hasResearchHistory: boolean;
  onClosePanel: () => void;
  onOpenAgent: () => void;
  onOpenArtifacts: () => void;
  onOpenPlan: () => void;
  onOpenPreview: () => void;
  onOpenResearch: () => void;
  onOpenResearchHistory: () => void;
}) {
  const { t } = useI18n();
  const hasAnyPanel =
    hasAgentWorkbench ||
    hasPlan ||
    artifactCount > 0 ||
    hasPreview ||
    hasResearch ||
    hasResearchHistory;

  if (!hasAnyPanel) return null;

  const openDefaultPanel = () => {
    if (hasAgentWorkbench) {
      onOpenAgent();
    } else if (artifactCount > 0) {
      onOpenArtifacts();
    } else if (hasPlan) {
      onOpenPlan();
    } else if (hasPreview) {
      onOpenPreview();
    } else if (hasResearch) {
      onOpenResearch();
    } else if (hasResearchHistory) {
      onOpenResearchHistory();
    }
  };
  const handleTogglePanel = () => {
    if (activePage) {
      onClosePanel();
      return;
    }
    openDefaultPanel();
  };

  const panelToggleLabel = activePage
    ? t.realtime.panelToggle.close
    : t.realtime.panelToggle.open;

  return (
    <Button
      type="button"
      aria-label={panelToggleLabel}
      title={panelToggleLabel}
      onClick={handleTogglePanel}
      className={cn(
        "flex size-[42px] items-center justify-center rounded-lg border shadow-none transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 sm:size-8",
        activePage
          ? "border-transparent bg-transparent text-foreground/82 hover:border-border-default hover:bg-muted/55 hover:text-foreground"
          : "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground",
      )}
    >
      <PanelRightIcon className="size-4" />
    </Button>
  );
}

function FinalArtifactCompletionNotice({
  entries,
  onOpen,
}: {
  entries: DiffEntry[];
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const first = entries[0];
  if (!first) return null;
  const extraCount = Math.max(0, entries.length - 1);
  return (
    <button
      type="button"
      onClick={onOpen}
      className="my-2 ml-11 flex max-w-full items-center gap-2 rounded-md border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-left text-xs text-emerald-800 transition-colors hover:bg-emerald-500/15 dark:text-emerald-200"
    >
      <FileTextIcon className="size-4 shrink-0" />
      <span className="min-w-0 flex-1">
        <span className="font-medium">
          {t.realtime.finalArtifact.generated}
        </span>
        <span className="ml-2 font-mono text-[11px] text-emerald-700/80 dark:text-emerald-200/80">
          {first.path || first.title}
        </span>
        {extraCount > 0 && (
          <span className="ml-2 text-emerald-700/80 dark:text-emerald-200/80">
            +{extraCount}
          </span>
        )}
      </span>
      <span className="shrink-0 text-[11px] text-emerald-700/75 dark:text-emerald-200/75">
        {t.realtime.finalArtifact.view}
      </span>
    </button>
  );
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function threadOwnerAgentFromMetadata(
  metadata?: Record<string, unknown> | null,
  values?: Record<string, unknown> | null,
): string {
  return firstString(
    metadata?.agent,
    metadata?.agent_name,
    metadata?.agent_id,
    metadata?.lead_agent_name,
    metadata?.current_agent,
    values?.current_speaker,
    values?.agent_name,
  );
}

function ChatHeaderAgentBadge({
  agent,
  agentId,
}: {
  agent: ReturnType<typeof useAgent>["agent"];
  agentId: string;
}) {
  const label = agent?.display_name?.trim() || agent?.name?.trim() || agentId;
  const icon = agent?.icon?.trim() || "";
  const initial = label.trim().charAt(0).toUpperCase() || "A";
  const avatarUrl = agent?.avatar_url
    ? withAgentAvatarVersion(
        agent.avatar_url.startsWith("http://") ||
          agent.avatar_url.startsWith("https://")
          ? agent.avatar_url
          : `${getBackendBaseURL()}${agent.avatar_url}`,
      )
    : "";
  if (!label || label === "general") return null;
  return (
    <div
      className="inline-flex h-8 max-w-[180px] shrink-0 items-center gap-1.5 px-1.5 text-[12px] text-foreground/88 transition-colors hover:bg-muted/45"
      title={label}
    >
      <span className="flex size-5 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-[10px] font-semibold text-muted-foreground">
        {avatarUrl ? (
          <img src={avatarUrl} alt={label} className="size-full object-cover" />
        ) : icon ? (
          icon
        ) : (
          initial
        )}
      </span>
      <span className="truncate">{label}</span>
    </div>
  );
}

function ChatHeaderRecButton({
  threadId,
  onOpen,
  isRecording,
}: {
  threadId: string;
  onOpen: () => void;
  isRecording: boolean;
}) {
  const { t } = useI18n();
  const [status, setStatus] = useState<RecordingStatus>({
    recording: false,
    step_count: 0,
    name: "",
  });

  const refresh = useCallback(async () => {
    if (!threadId || threadId === "new") return;
    try {
      setStatus(await getRecordingStatus(threadId));
    } catch (error) {
      swallow(error, "teach-repeat-status");
    }
  }, [threadId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // The floating RecRecorderOverlay owns start/stop now; this chip only opens it
  // and mirrors live state. ``isRecording`` (from the overlay) flips instantly;
  // the poll keeps the step counter fresh and recovers state on reload.
  const recording = isRecording || status.recording;
  useEffect(() => {
    if (!recording) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh, recording]);

  const recordingTitle = recording
    ? t.realtime.recording.recording(status.step_count)
    : t.realtime.recording.idle;

  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!threadId || threadId === "new"}
      title={recordingTitle}
      aria-label={recordingTitle}
      className={cn(
        "inline-flex h-[42px] shrink-0 items-center gap-1.5 rounded-lg border px-3 text-[11px] font-semibold shadow-none transition-all duration-200 sm:h-8 sm:px-2.5",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        recording
          ? "border-red-500/25 bg-red-500/10 text-red-600 hover:bg-red-500/16 dark:text-red-400"
          : "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground",
      )}
    >
      <CircleDotIcon className={cn("size-3.5", recording && "animate-pulse")} />
      <span>REC</span>
      {recording && status.step_count > 0 && (
        <span className="font-mono text-[10px] opacity-70">
          {status.step_count}
        </span>
      )}
    </button>
  );
}

function formatCollaboratorCount(count: number, unit: string): string {
  return unit.length <= 1 ? `${count}${unit}` : `${count} ${unit}`;
}

function TaskCollaboratorControl({
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
  const ActiveIcon = activeMeta?.icon ?? UserPlusIcon;
  const displayRoster = roster.slice(0, 5);
  const extraRosterCount = Math.max(0, roster.length - displayRoster.length);
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
            "group inline-flex h-[42px] max-w-[11rem] items-center gap-1.5 rounded-lg border px-2.5 text-[12px] font-medium shadow-none transition-all duration-200 sm:h-8 sm:px-2",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35",
            isTeamDraft
              ? "border-primary/30 bg-primary/10 text-primary hover:bg-primary/15"
              : "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/50 hover:text-foreground",
          )}
          title={t.chatInputBox.collaborators}
        >
          {displayRoster.length > 0 ? (
            <span className="grid grid-flow-col auto-cols-[1.25rem] gap-0.5">
              {displayRoster.map((agent) => (
                <span
                  key={agent.agent_id}
                  className={cn(
                    "grid size-5 place-items-center overflow-hidden rounded-md border text-[10px] font-semibold transition-all duration-200",
                    isTeamDraft
                      ? "border-primary-foreground/40 bg-primary-foreground/20 text-primary-foreground"
                      : "border-border-default bg-muted text-muted-foreground",
                  )}
                  title={agent.display_name}
                >
                  {agent.avatar_url ? (
                    <img
                      src={agent.avatar_url}
                      alt={agent.display_name}
                      className="size-full object-cover"
                    />
                  ) : agent.icon?.trim() ? (
                    <span className="text-[12px] leading-none">
                      {agent.icon}
                    </span>
                  ) : (
                    agent.display_name.charAt(0).toUpperCase()
                  )}
                </span>
              ))}
              {extraRosterCount > 0 && (
                <span
                  className={cn(
                    "grid size-5 place-items-center rounded-md border text-[9px] font-semibold transition-all duration-200",
                    isTeamDraft
                      ? "border-primary/20 bg-primary-foreground/90 text-primary"
                      : "border-border-default bg-muted text-muted-foreground",
                  )}
                >
                  +{extraRosterCount}
                </span>
              )}
            </span>
          ) : (
            <ActiveIcon className="size-4 shrink-0" />
          )}
          <span className="hidden min-w-0 truncate sm:inline">
            {activeMeta?.label ?? t.chatInputBox.collaboratorsSingle}
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1 shrink-0 rounded-md px-1.5 py-0.5 mr-1 text-[10px] transition-all duration-200",
              isTeamDraft
                ? "bg-primary-foreground/80 text-primary font-semibold"
                : hasOnlineMembers
                  ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "bg-transparent text-muted-foreground group-hover:bg-background/75 group-hover:text-foreground",
            )}
          >
            {hasOnlineMembers && (
              <span className="size-1.5 rounded-full bg-emerald-500" />
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
            <div className="flex min-w-0 items-center gap-2 text-[12px] font-medium">
              <UsersRoundIcon className="size-4 text-primary" />
              <span className="truncate">{t.chatInputBox.collaborators}</span>
            </div>
            <button
              type="button"
              onClick={() => onSelectedAgentIdsChange([])}
              className="rounded-lg px-2 py-1 text-[11px] text-muted-foreground transition-all duration-200 hover:bg-muted/70 hover:text-foreground"
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
                    "inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] font-medium transition-all duration-200",
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
                    <span className="grid size-6 shrink-0 place-items-center overflow-hidden rounded-md bg-background text-[10px] font-semibold text-muted-foreground">
                      {entry.avatar_url ? (
                        <img
                          src={entry.avatar_url}
                          alt={entry.display_name}
                          className="size-full object-cover"
                        />
                      ) : entry.icon?.trim() ? (
                        <span className="text-[13px] leading-none">
                          {entry.icon}
                        </span>
                      ) : (
                        entry.display_name.charAt(0).toUpperCase()
                      )}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[11px] font-medium">
                      {entry.display_name}
                    </span>
                    {isLeader ? (
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {t.agentWorkbenchPanel.mainController}
                      </span>
                    ) : (
                      <span className="shrink-0 rounded p-0.5 text-muted-foreground opacity-60 transition-all duration-200 group-hover:opacity-100">
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
                    className="group flex min-w-0 w-full items-center gap-2 rounded-lg bg-muted/35 px-2 py-1.5 text-left transition-all duration-200 hover:bg-destructive/10 hover:text-destructive"
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
          <label className="flex h-9 items-center gap-2 rounded-lg border border-border-default bg-background/45 px-2.5 transition-all duration-200 hover:border-border-strong hover:bg-background/60 focus-within:border-ring focus-within:bg-background focus-within:ring-2 focus-within:ring-ring/20">
            <SearchIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={t.chatInputBox.collaboratorsSearchPlaceholder}
              aria-label={t.chatInputBox.collaboratorsSearchPlaceholder}
              className="h-auto min-w-0 flex-1 border-0 bg-transparent p-0 text-[12px] shadow-none outline-none placeholder:text-muted-foreground/45 focus-visible:ring-0 focus-visible:ring-offset-0"
            />
          </label>
          {selectedAgents.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {selectedAgents.map((agent) => (
                <button
                  key={agent.name}
                  type="button"
                  onClick={() => toggleAgent(agent)}
                  className="group inline-flex max-w-full items-center gap-1 rounded-lg border border-primary/20 bg-primary/8 px-1.5 py-0.5 text-[11px] text-primary transition-all duration-200 hover:bg-destructive/10 hover:border-destructive/30 hover:text-destructive"
                >
                  <AgentAvatar
                    agent={agent}
                    className="size-4 rounded text-[9px]"
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
                      "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-all duration-200",
                      selected ? "bg-primary/8" : "hover:bg-muted/55",
                    )}
                  >
                    <AgentAvatar
                      agent={agent}
                      className="size-7 rounded-md text-[11px]"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] font-medium">
                        {label}
                      </span>
                      <span className="block truncate text-[11px] text-muted-foreground">
                        {agent.description || agent.name}
                      </span>
                    </span>
                    <span
                      className={cn(
                        "grid size-5 shrink-0 place-items-center rounded-md border transition-all duration-200",
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
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-lg px-2.5 text-[12px] font-medium text-muted-foreground transition-all duration-200 hover:bg-muted/60 hover:text-foreground"
          >
            <CopyIcon className="size-3.5" />
            {t.collab.copyLink}
          </button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function latestArtifactFocusPathFromEvents(
  events: Array<{ input?: unknown }>,
): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const input = recordFromUnknown(events[index]?.input);
    const focus = recordFromUnknown(input?.workspaceFocus);
    const view = focus?.view;
    if (view !== "artifact" && view !== "image") continue;
    const path = input?.path;
    if (typeof path === "string" && path.trim().length > 0) return path;
  }
  return null;
}

/**
 * Plain chat workspace. Mirrors the team / code page architecture
 * (`ThreadProviders → ChatBox → ChatPageLayout`) so headers, message
 * list, composer, and Welcome state all share the same Octopus-style
 * design. No file tree, no team-mode picker — just the conversation.
 */
export default function RealtimePage() {
  const chatState = useThreadChat();

  return (
    <ArtifactsProvider threadId={chatState.threadId}>
      <RealtimePageContent chatState={chatState} />
    </ArtifactsProvider>
  );
}

function RealtimePageContent({
  chatState,
}: {
  chatState: ReturnType<typeof useThreadChat>;
}) {
  const { t } = useI18n();
  const { threadId, isNewThread, setIsNewThread } = chatState;
  const isMobile = useIsMobile();
  const {
    artifacts,
    open: artifactsOpen,
    select: selectArtifact,
    setOpen: setArtifactsOpen,
  } = useArtifacts();
  const [settings, setSettings] = useThreadSettings(threadId);
  const [mounted, setMounted] = useState(false);
  const [, setShowPreview] = useState(false);
  const [researchJob, setResearchJob] = useState<ResearchJob | null>(null);
  const [researchLoading, setResearchLoading] = useState(false);
  const [researchError, setResearchError] = useState<string | null>(null);
  const [showResearch, setShowResearch] = useState(false);
  const [showResearchHistory, setShowResearchHistory] = useState(false);
  const [showAgentPlan, setShowAgentPlan] = useState(false);
  const [agentWorkbenchTab, setAgentWorkbenchTab] =
    useState<AgentWorkbenchTabId>("agent");
  const [agentWorkbenchTabTouched, setAgentWorkbenchTabTouched] =
    useState(false);
  const [agentWorkbenchDismissed, setAgentWorkbenchDismissed] = useState(false);
  const [agentWorkbenchManuallyOpened, setAgentWorkbenchManuallyOpened] =
    useState(false);
  const [focusedWorkbenchAgentId, setFocusedWorkbenchAgentId] = useState<
    string | null
  >(null);
  // Which sub-view the focus event asked for; lives and dies with
  // focusedWorkbenchAgentId (set together, cleared together).
  const [focusedWorkbenchAgentView, setFocusedWorkbenchAgentView] =
    useState<AgentWorkbenchFocusView | null>(null);
  // Bumped on every focus emission so the panel treats a repeat focus of the
  // same agent (e.g. a view switch) as a fresh intent.
  const [focusedWorkbenchAgentNonce, setFocusedWorkbenchAgentNonce] =
    useState(0);
  const [focusedWorkbenchEventId, setFocusedWorkbenchEventId] = useState<
    string | null
  >(null);
  const [focusedWorkbenchEventKind, setFocusedWorkbenchEventKind] =
    useState<AgentWorkbenchProcessEventKind | null>(null);
  const [focusedWorkbenchEventView, setFocusedWorkbenchEventView] =
    useState<AgentWorkbenchEventView | null>(null);
  const [focusedWorkbenchEventNonce, setFocusedWorkbenchEventNonce] =
    useState(0);
  const [focusedWorkbenchProcessEvent, setFocusedWorkbenchProcessEvent] =
    useState<AgentWorkbenchProcessEventSnapshot | null>(null);
  const [focusedWorkbenchEffectKey, setFocusedWorkbenchEffectKey] = useState<
    string | null
  >(null);
  const settledWorkbenchAutoDismissedRef = useRef<string | null>(null);
  const [discussionOnly, setDiscussionOnly] = useState(false);
  const [chatsDrawerOpen, setChatsDrawerOpen] = useState(false);
  const [projectAgentMode, setProjectAgentMode] =
    useState<AgentModeName>("develop");
  const [auditIntensity, setAuditIntensity] =
    useState<AuditIntensity>("standard");
  const [projectDetection, setProjectDetection] =
    useState<DetectResponse | null>(null);
  // Personal-space work mode (general/build/research) — only meaningful when no
  // project dir is bound; threaded into the turn context as personal_mode. It no
  // longer downgrades capability: personal space still runs against an isolated
  // coding workspace, while a selected folder binds a user project workspace.
  const [personalMode, setPersonalMode] = useState<PersonalMode>("general");
  // REC floating recorder overlay (replaces the old confirm() start/stop flow).
  const [recOverlayOpen, setRecOverlayOpen] = useState(false);
  const [recIsRecording, setRecIsRecording] = useState(false);
  // Work directory for Agent project/code state. Empty means the thread uses its
  // isolated personal coding workspace; selecting a local folder binds a user
  // project directory without mixing it with the separate Team workspace.
  const [workDir, setWorkDir] = useState<string>(() => "");
  const localStartedThreadIdRef = useRef<string | null>(null);
  const handleWorkDirChange = useCallback((dir: string) => {
    setWorkDir(dir);
    rememberChatWorkDir(dir);
  }, []);
  const threadWorkspaceQuery = useQuery({
    queryKey: ["thread", "workspace-path", threadId],
    enabled:
      !isNewThread &&
      Boolean(threadId) &&
      localStartedThreadIdRef.current !== threadId,
    queryFn: async () => {
      const state = await getAPIClient().threads.getState(threadId);
      const workspacePath = state.metadata?.["workspace_path"];
      return typeof workspacePath === "string" && isAbsolutePath(workspacePath)
        ? workspacePath
        : "";
    },
    refetchOnWindowFocus: false,
  });
  const threadIdentityQuery = useQuery({
    queryKey: ["thread", "identity", threadId],
    enabled:
      !isNewThread &&
      Boolean(threadId) &&
      localStartedThreadIdRef.current !== threadId,
    queryFn: async () => getAPIClient().threads.get(threadId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  const coworkGroupQuery = useCoworkGroup(isNewThread ? null : threadId);
  const collabSessionQuery = useCollabSession(isNewThread ? null : threadId);
  const inviteCoworkMemberMutation = useInviteCoworkMember();
  const removeCoworkMemberMutation = useRemoveCoworkMember();
  const setCoworkModeMutation = useSetCoworkMode();
  const ensureCollabRoomMutation = useEnsureCollabRoom();
  const persistedThreadWorkspacePath = threadWorkspaceQuery.data ?? "";

  useEffect(() => {
    if (
      isNewThread ||
      threadWorkspaceQuery.isPending ||
      localStartedThreadIdRef.current === threadId
    ) {
      return;
    }
    if (!persistedThreadWorkspacePath) {
      setWorkDir("");
      rememberChatWorkDir("");
      return;
    }
    setWorkDir((current) => {
      if (
        normalizeWorkDirKey(current) ===
        normalizeWorkDirKey(persistedThreadWorkspacePath)
      ) {
        return current;
      }
      rememberChatWorkDir(persistedThreadWorkspacePath);
      return persistedThreadWorkspacePath;
    });
  }, [
    isNewThread,
    persistedThreadWorkspacePath,
    threadId,
    threadWorkspaceQuery.isPending,
  ]);

  useEffect(() => {
    const handler = (event: Event) => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path;
      if (path && isAbsolutePath(path)) {
        handleWorkDirChange(path);
      }
    };
    window.addEventListener("octopus:workdir-selected", handler);
    return () =>
      window.removeEventListener("octopus:workdir-selected", handler);
  }, [handleWorkDirChange]);
  const { models } = useModels();
  const { agents: builtinAgents } = useAgents();
  const { cliAgents } = useLocalCliAgents();
  const { mobileAgents } = useMobileDevices();
  const allTaskCollaboratorAgents = useMemo(
    () =>
      dedupePersonaAgentsByDisplayName(
        dedupeAgentsByName([...mobileAgents, ...cliAgents, ...builtinAgents]),
      ),
    [builtinAgents, cliAgents, mobileAgents],
  );
  const [selectedCollaboratorIds, setSelectedCollaboratorIds] = useState<
    string[]
  >([]);
  const [teamModeIntent, setTeamModeIntent] = useState<TeamMode>("cluster");
  const [collaboratorPickerOpen, setCollaboratorPickerOpen] = useState(false);
  const collaboratorSelectionTouchedRef = useRef(false);
  const lastCoworkSyncSignatureRef = useRef<string | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    collaboratorSelectionTouchedRef.current = false;
    lastCoworkSyncSignatureRef.current = null;
    setSelectedCollaboratorIds([]);
    setTeamModeIntent("cluster");
  }, [threadId]);

  useEffect(() => {
    setFocusedWorkbenchAgentId(null);
    setFocusedWorkbenchAgentView(null);
    setFocusedWorkbenchEventId(null);
    setFocusedWorkbenchEventKind(null);
    setFocusedWorkbenchEventView(null);
    setFocusedWorkbenchEffectKey(null);
    setAgentWorkbenchManuallyOpened(false);
  }, [threadId]);

  const navigate = useNavigate();
  const location = useLocation();
  const routeState = (location.state as ThreadRouteState | null) ?? null;
  const params = useParams<{ agentName?: string }>();
  const qc = useQueryClient();
  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const initialPrompt = useMemo(() => {
    return searchParams.get("prompt") ?? "";
  }, [searchParams]);
  const queryAgentName = (searchParams.get("agent") ?? "").trim();
  const routeAgentName = useMemo(() => {
    const raw = params.agentName?.trim();
    if (!raw) return "";
    try {
      return decodeURIComponent(raw);
    } catch (e) {
      swallow(e);
      return raw;
    }
  }, [params.agentName]);
  const isAgentRoute = !!routeAgentName;
  const isRealtimeRoute = location.pathname.startsWith("/workspace/realtime");
  const memoryMode = searchParams.get("memory") ?? "";
  const queryWorkspacePath = searchParams.get("workspace_path") ?? "";

  // Unified task routes carry the selected persona in ?agent= while every chat
  // thread stays on the /workspace/realtime/* surface.
  const activeAgentId = routeAgentName || queryAgentName || "general";
  const { agent: activeAgent } = useAgent(activeAgentId);
  const hintedThreadOwnerAgentId = routeState?.threadOwnerAgentId?.trim() || "";
  const hintedWorkspacePath =
    typeof routeState?.workspacePath === "string" &&
    isAbsolutePath(routeState.workspacePath)
      ? routeState.workspacePath
      : isAbsolutePath(queryWorkspacePath)
        ? queryWorkspacePath
        : "";
  const threadOwnerAgentId = useMemo(
    () =>
      threadOwnerAgentFromMetadata(
        threadIdentityQuery.data?.metadata,
        threadIdentityQuery.data?.values,
      ),
    [threadIdentityQuery.data],
  );
  const resolvedThreadOwnerAgentId =
    threadOwnerAgentId || hintedThreadOwnerAgentId;
  const effectiveAgentId = resolvedThreadOwnerAgentId || activeAgentId;
  const { agent: threadOwnerAgent } = useAgent(
    resolvedThreadOwnerAgentId && resolvedThreadOwnerAgentId !== activeAgentId
      ? resolvedThreadOwnerAgentId
      : null,
  );
  const displayAgent =
    resolvedThreadOwnerAgentId && resolvedThreadOwnerAgentId !== activeAgentId
      ? threadOwnerAgent
      : activeAgent;
  const currentTaskAgentName = displayAgent?.name ?? effectiveAgentId;
  const composerDisplayAgent = useMemo(
    () =>
      displayAgent ?? {
        name: effectiveAgentId,
        display_name: effectiveAgentId,
        avatar_url: null,
        icon: null,
      },
    [displayAgent, effectiveAgentId],
  );
  const selectedCollaborators = useMemo(() => {
    const selected = new Set(selectedCollaboratorIds);
    return allTaskCollaboratorAgents.filter((agent) =>
      selected.has(agent.name),
    );
  }, [allTaskCollaboratorAgents, selectedCollaboratorIds]);
  const persistedCollaborationRoster = useMemo(
    () =>
      collaborationRosterFromThread(
        threadIdentityQuery.data?.metadata,
        threadIdentityQuery.data?.values,
        currentTaskAgentName,
      ),
    [
      currentTaskAgentName,
      threadIdentityQuery.data?.metadata,
      threadIdentityQuery.data?.values,
    ],
  );
  const coworkCollaborationProfiles = useMemo(
    () => [composerDisplayAgent, ...allTaskCollaboratorAgents],
    [allTaskCollaboratorAgents, composerDisplayAgent],
  );
  const coworkCollaborationRoster = useMemo(() => {
    const sessionRoster = coworkSessionToCollaborationRoster(
      collabSessionQuery.data,
      currentTaskAgentName,
      coworkCollaborationProfiles,
    );
    const groupRoster = coworkGroupToCollaborationRoster(
      coworkGroupQuery.data,
      currentTaskAgentName,
      coworkCollaborationProfiles,
    );
    if (sessionRoster.length === 0) return groupRoster;
    if (groupRoster.length === 0) return sessionRoster;
    const seen = new Map<string, ChatCollaborationRosterEntry>();
    for (const entry of sessionRoster) seen.set(entry.agent_id, entry);
    for (const entry of groupRoster) {
      if (!seen.has(entry.agent_id)) seen.set(entry.agent_id, entry);
    }
    return Array.from(seen.values());
  }, [
    collabSessionQuery.data,
    coworkCollaborationProfiles,
    coworkGroupQuery.data,
    currentTaskAgentName,
  ]);
  const savedCollaborationRoster = useMemo(() => {
    if (coworkCollaborationRoster.length > 0) return coworkCollaborationRoster;
    return persistedCollaborationRoster;
  }, [coworkCollaborationRoster, persistedCollaborationRoster]);
  const persistedCollaboratorIds = useMemo(
    () =>
      savedCollaborationRoster
        .filter(
          (agent) =>
            agent.role !== "tl" && agent.agent_id !== currentTaskAgentName,
        )
        .map((agent) => agent.agent_id),
    [currentTaskAgentName, savedCollaborationRoster],
  );
  const persistedCollaboratorKey = persistedCollaboratorIds.join("\u0000");
  const savedCollaborationMode =
    collabSessionQuery.data?.mode ?? coworkGroupQuery.data?.state.mode;
  const applyTaskCollaboratorPreset = useCallback(
    (preset: TaskCollaboratorPreset) => {
      const nextIds = Array.from(
        new Set(
          (preset.collaboratorIds ?? [])
            .map((id) => id.trim())
            .filter((id) => id && id !== currentTaskAgentName),
        ),
      );
      collaboratorSelectionTouchedRef.current = true;
      setSelectedCollaboratorIds(nextIds);
      setTeamModeIntent(
        nextIds.length > 0 ? (preset.mode ?? "cluster") : "cluster",
      );
      if (preset.openPicker) {
        setCollaboratorPickerOpen(true);
      }
    },
    [currentTaskAgentName],
  );
  useEffect(() => {
    const storedPreset = consumeTaskCollaboratorPreset();
    if (storedPreset) {
      applyTaskCollaboratorPreset(storedPreset);
    }
    const handler = (event: Event) => {
      const preset = (event as CustomEvent<TaskCollaboratorPreset>).detail;
      if (preset) {
        applyTaskCollaboratorPreset(preset);
      }
    };
    window.addEventListener(TASK_COLLABORATOR_PRESET_EVENT, handler);
    return () =>
      window.removeEventListener(TASK_COLLABORATOR_PRESET_EVENT, handler);
  }, [applyTaskCollaboratorPreset]);
  useEffect(() => {
    if (
      isNewThread ||
      threadIdentityQuery.isPending ||
      localStartedThreadIdRef.current === threadId
    ) {
      return;
    }
    if (collaboratorSelectionTouchedRef.current) {
      return;
    }
    setSelectedCollaboratorIds((current) =>
      current.join("\u0000") === persistedCollaboratorKey
        ? current
        : persistedCollaboratorIds,
    );
    if (persistedCollaboratorIds.length > 0) {
      setTeamModeIntent(savedCollaborationMode ?? "cluster");
    }
  }, [
    isNewThread,
    persistedCollaboratorKey,
    persistedCollaboratorIds,
    savedCollaborationMode,
    threadId,
    threadIdentityQuery.isPending,
  ]);
  const selectedCollaboratorKey = selectedCollaboratorIds.join("\u0000");
  useEffect(() => {
    if (isNewThread || !threadId || threadId === "new") return;

    const startedLocally = localStartedThreadIdRef.current === threadId;
    const userTouched = collaboratorSelectionTouchedRef.current;
    const matchesSavedRoster =
      selectedCollaboratorKey === persistedCollaboratorKey;
    if (!startedLocally && !userTouched && !matchesSavedRoster) return;
    const sessionState = collabSessionQuery.data
      ? {
          roster: collabSessionQuery.data.roster,
          mode: collabSessionQuery.data.mode,
          event_count: coworkGroupQuery.data?.state.event_count ?? 0,
          is_one_to_one:
            collabSessionQuery.data.roster.filter(
              (member) => member.kind === "agent",
            ).length <= 1 &&
            collabSessionQuery.data.roster.filter(
              (member) => member.kind === "human",
            ).length <= 1,
          room_id: collabSessionQuery.data.room_id,
        }
      : null;
    const currentCoworkState =
      sessionState ?? coworkGroupQuery.data?.state ?? null;
    if (
      currentCoworkState === null &&
      (collabSessionQuery.isPending || coworkGroupQuery.isPending)
    ) {
      return;
    }

    const plan = buildCoworkSelectionSyncPlan({
      leaderId: currentTaskAgentName,
      collaboratorIds: selectedCollaboratorIds,
      mode: teamModeIntent,
      current: currentCoworkState,
    });
    if (!plan.hasWork) return;

    const signature = `${threadId}|${plan.signature}`;
    if (lastCoworkSyncSignatureRef.current === signature) return;
    lastCoworkSyncSignatureRef.current = signature;
    const resetOnError = () => {
      if (lastCoworkSyncSignatureRef.current === signature) {
        lastCoworkSyncSignatureRef.current = null;
      }
    };

    for (const id of plan.inviteAgentIds) {
      inviteCoworkMemberMutation.mutate(
        {
          threadId,
          input: {
            target_id: id,
            kind: "agent",
            role: "participant",
            grant: { scope: "all" },
          },
        },
        { onError: resetOnError },
      );
    }
    for (const id of plan.removeAgentIds) {
      removeCoworkMemberMutation.mutate(
        { threadId, memberId: id },
        { onError: resetOnError },
      );
    }
    if (plan.shouldSetMode) {
      setCoworkModeMutation.mutate(
        { threadId, mode: plan.mode },
        { onError: resetOnError },
      );
    }
  }, [
    collabSessionQuery.data,
    collabSessionQuery.isPending,
    coworkGroupQuery.data?.state,
    coworkGroupQuery.data,
    coworkGroupQuery.isPending,
    currentTaskAgentName,
    inviteCoworkMemberMutation,
    isNewThread,
    persistedCollaboratorKey,
    removeCoworkMemberMutation,
    selectedCollaboratorIds,
    selectedCollaboratorKey,
    setCoworkModeMutation,
    teamModeIntent,
    threadId,
  ]);
  const handleSelectedCollaboratorIdsChange = useCallback(
    (ids: string[]) => {
      const leader = currentTaskAgentName.trim();
      const nextIds = Array.from(
        new Set(ids.map((id) => id.trim()).filter((id) => id && id !== leader)),
      );
      collaboratorSelectionTouchedRef.current = true;
      setSelectedCollaboratorIds(nextIds);
      if (nextIds.length === 0) {
        setTeamModeIntent("chat");
      }
    },
    [currentTaskAgentName],
  );
  const handleTeamModeIntentChange = useCallback((mode: TeamMode) => {
    collaboratorSelectionTouchedRef.current = true;
    setTeamModeIntent(mode);
  }, []);
  const collaborationRoster = useMemo<ChatCollaborationRosterEntry[]>(() => {
    const leaderName = composerDisplayAgent.name?.trim() || effectiveAgentId;
    const roster: ChatCollaborationRosterEntry[] = [
      {
        agent_id: leaderName,
        name: leaderName,
        display_name:
          composerDisplayAgent.display_name?.trim() ||
          composerDisplayAgent.name?.trim() ||
          leaderName,
        avatar_url: composerDisplayAgent.avatar_url ?? null,
        icon: composerDisplayAgent.icon ?? null,
        role: "tl",
      },
    ];
    for (const agent of selectedCollaborators) {
      if (!agent.name || agent.name === leaderName) continue;
      roster.push({
        agent_id: agent.name,
        name: agent.name,
        display_name: agent.display_name?.trim() || agent.name,
        avatar_url: agent.avatar_url ?? null,
        icon: agent.icon ?? null,
        role: "member",
      });
    }
    return roster;
  }, [composerDisplayAgent, effectiveAgentId, selectedCollaborators]);
  const collaborationEnabled = selectedCollaborators.length > 0;
  const visibleCollaborationRoster = useMemo(() => {
    const primary =
      collaborationEnabled || savedCollaborationRoster.length === 0
        ? collaborationRoster
        : savedCollaborationRoster;
    const secondary =
      primary === collaborationRoster
        ? savedCollaborationRoster
        : collaborationRoster;
    if (secondary.length === 0) return primary;
    const seen = new Map<string, ChatCollaborationRosterEntry>();
    for (const entry of primary) seen.set(entry.agent_id, entry);
    for (const entry of secondary) {
      if (!seen.has(entry.agent_id)) seen.set(entry.agent_id, entry);
    }
    return Array.from(seen.values());
  }, [collaborationEnabled, collaborationRoster, savedCollaborationRoster]);
  const visibleCollaborationEnabled = visibleCollaborationRoster.length > 1;
  const collaborationRosterSeats = useMemo<WorkbenchRosterSeat[]>(
    () =>
      visibleCollaborationRoster.map((agent) => ({
        id: agent.agent_id,
        name: agent.display_name,
        avatarUrl: agent.avatar_url ?? null,
        icon: agent.icon ?? null,
        role: agent.role,
      })),
    [visibleCollaborationRoster],
  );
  const collaborationTeamName =
    firstString(threadIdentityQuery.data?.values?.title, initialPrompt) ||
    t.collab.defaultTeamName;
  const collaborationContext = useMemo(() => {
    if (!collaborationEnabled) return {};
    const isCoworkMode = teamModeIntent !== "chat";
    return {
      agent_name: effectiveAgentId,
      subagent_enabled: isCoworkMode,
      is_plan_mode: isCoworkMode,
      team_mode: isCoworkMode ? "cowork" : "chat",
      serve_mesh: serveMeshForMode(teamModeIntent),
      topology_id: teamModeIntent === "cluster" ? "cowork" : undefined,
      agent_roster: collaborationRoster,
      team_members: collaborationRoster.map((agent) => agent.display_name),
      team_leader: collaborationRoster[0]?.display_name ?? effectiveAgentId,
      team_id: `thread:${threadId}`,
      team_name: collaborationTeamName,
      project: t.collab.projectPrefix(collaborationTeamName),
      task_agent_refs: selectedCollaborators.map((agent) => agent.name),
      task_agent_names: selectedCollaborators.map(
        (agent) => agent.display_name ?? agent.name,
      ),
    };
  }, [
    collaborationEnabled,
    collaborationRoster,
    collaborationTeamName,
    effectiveAgentId,
    selectedCollaborators,
    t,
    teamModeIntent,
    threadId,
  ]);
  const collaborationRoomMemberPayload = useMemo(
    () =>
      visibleCollaborationRoster.map((agent) => ({
        name: agent.agent_id,
        display_name: agent.display_name,
        description:
          agent.role === "tl"
            ? t.collab.common.leader
            : t.collab.common.aiMember,
        avatar_url: agent.avatar_url ?? undefined,
        icon: agent.icon ?? undefined,
      })),
    [t, visibleCollaborationRoster],
  );
  const collaborationRoomSignature = useMemo(
    () =>
      [
        threadId,
        collaborationTeamName,
        teamModeIntent,
        ...collaborationRoomMemberPayload.map((member) => member.name),
      ].join("\u0000"),
    [
      collaborationRoomMemberPayload,
      collaborationTeamName,
      teamModeIntent,
      threadId,
    ],
  );
  const lastEnsuredCollabRoomRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      isNewThread ||
      !threadId ||
      threadId === "new" ||
      !visibleCollaborationEnabled ||
      collabSessionQuery.isPending ||
      collabSessionQuery.data?.room_id ||
      ensureCollabRoomMutation.isPending
    ) {
      return;
    }
    if (lastEnsuredCollabRoomRef.current === collaborationRoomSignature) {
      return;
    }
    lastEnsuredCollabRoomRef.current = collaborationRoomSignature;
    ensureCollabRoomMutation.mutate(
      {
        threadId,
        input: {
          id: `collab-${threadId}`,
          name: collaborationTeamName,
          members: collaborationRoomMemberPayload,
          leaderId: collaborationRoomMemberPayload[0]?.name ?? effectiveAgentId,
          mode: teamModeIntent,
        },
      },
      {
        onError: () => {
          if (lastEnsuredCollabRoomRef.current === collaborationRoomSignature) {
            lastEnsuredCollabRoomRef.current = null;
          }
        },
      },
    );
  }, [
    collabSessionQuery.data?.room_id,
    collabSessionQuery.isPending,
    collaborationRoomMemberPayload,
    collaborationRoomSignature,
    collaborationTeamName,
    effectiveAgentId,
    ensureCollabRoomMutation,
    isNewThread,
    teamModeIntent,
    threadId,
    visibleCollaborationEnabled,
  ]);
  useEffect(() => {
    setSelectedCollaboratorIds((current) =>
      current.filter((id) => id !== currentTaskAgentName),
    );
  }, [currentTaskAgentName]);
  const effectiveReasoningEffort = normalizeReasoningEffortForUi(
    settings.context.reasoning_effort,
  );
  const routeMode = settings.context.mode;
  const effectiveWorkDir =
    !isNewThread &&
    threadWorkspaceQuery.isPending &&
    localStartedThreadIdRef.current !== threadId &&
    hintedWorkspacePath
      ? hintedWorkspacePath
      : workDir;
  const projectWorkspacePath = effectiveWorkDir.trim();
  const isProjectCodeMode = !!projectWorkspacePath;
  const isExplicitConversationMode =
    routeMode === "chat" || routeMode === "flash" || discussionOnly;
  const isCodingWorkspaceMode =
    isProjectCodeMode ||
    ((isAgentRoute || isRealtimeRoute) && !isExplicitConversationMode);
  // Code mode is available to every agent by default · per-agent unlock
  // flag removed. Tool/permission scoping lives in the skills &
  // permissions system, not a global gate.
  const codeModeUnlocked = true;
  // Local CLI partner (Codex / Claude Code): driven by spawning its own CLI, so
  // its model comes from the CLI's config, not the Octopus model picker.
  const partnerCaps = activeAgent?.capabilities as
    | { local_partner?: boolean; local_partner_id?: string }
    | undefined;
  const isLocalPartner =
    activeAgentId.startsWith("local_") || Boolean(partnerCaps?.local_partner);
  const partnerId = isLocalPartner
    ? String(partnerCaps?.local_partner_id ?? "")
    : "";
  const [partnerModel, setPartnerModel] = useState("");
  // Reset the override when switching to a different agent.
  useEffect(() => {
    setPartnerModel("");
  }, [activeAgentId]);
  const projectSignals = useMemo(() => {
    if (!isProjectCodeMode || !projectDetection) return undefined;
    const signals = projectDetection.signals;
    const compact: DetectionSignals = {
      workspace_path: projectWorkspacePath,
      exists: signals.exists,
      file_count: signals.file_count,
      manifests: signals.manifests?.slice(0, 8),
      structure_dirs: signals.structure_dirs?.slice(0, 12),
      git_commits: signals.git_commits,
      has_readme: signals.has_readme,
      lock_files: signals.lock_files?.slice(0, 8),
      commands: signals.commands?.slice(0, 8),
    };
    return {
      recommended_mode: projectDetection.recommended_mode,
      confidence: projectDetection.confidence,
      reason: projectDetection.reason,
      signals: compact,
    };
  }, [isProjectCodeMode, projectDetection, projectWorkspacePath]);
  const projectModePreset = useMemo(
    () => modePresetForAgentMode(projectAgentMode),
    [projectAgentMode],
  );
  const effectiveMode: ReasoningMode = isCodingWorkspaceMode
    ? "code"
    : isAgentRoute && routeMode === "deep"
      ? routeMode
      : isAgentRoute
        ? "react"
        : discussionOnly
          ? "chat"
          : "react";
  const streamMode: ReasoningMode | "team" = collaborationEnabled
    ? "team"
    : effectiveMode;
  const threadRouteFor = useCallback(
    (id: string) => `/workspace/realtime/${encodeURIComponent(id)}`,
    [],
  );
  const newThreadRouteForMode = useCallback(
    (mode: string, prompt?: string) => {
      const agentId =
        mode === "react" || mode === "deep" ? activeAgentId : "general";
      return taskWorkspaceRoute({ agentId, prompt });
    },
    [activeAgentId],
  );
  const openWorkDirInNewTask = useCallback(
    (dir: string) => {
      const next = dir.trim();
      if (!isAbsolutePath(next)) return;
      const route = taskWorkspaceRoute({
        agentId: effectiveAgentId,
        workspacePath: next,
      });
      const opened = window.open(
        new URL(toHashRouterShellUrl(route), window.location.origin).toString(),
        "_blank",
        "noopener,noreferrer",
      );
      if (opened) opened.opener = null;
    },
    [effectiveAgentId],
  );
  const routeWorkspaceHintKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!isNewThread || !hintedWorkspacePath) return;
    const key = normalizeWorkDirKey(hintedWorkspacePath);
    if (routeWorkspaceHintKeyRef.current === key) return;
    routeWorkspaceHintKeyRef.current = key;
    handleWorkDirChange(hintedWorkspacePath);
  }, [handleWorkDirChange, hintedWorkspacePath, isNewThread]);

  // ── Agent-switch refresh ───────────────────────────────────
  // When the user picks a different agent in the footer dropdown while
  // looking at an existing thread, we need to:
  //   1. Leave the stale conversation window (it belonged to the old
  //      agent · showing its messages while the new agent answers the
  //      next turn is confusing and mixes personas).
  //   2. Invalidate the thread-list query so the sidebar re-fetches the
  //      new agent's threads (metadata.agent filter changed).
  // Skip the navigate+invalidate on the FIRST observed value (page
  // mount) — only react to actual changes.
  const [composerSeed, setComposerSeed] = useState(initialPrompt);
  const prevAgentRef = useRef<string | null>(null);
  const { stageRoute: stageThreadRoute, commitRoute: commitThreadRoute } =
    useDeferredRouteCommit();
  useEffect(() => {
    if (initialPrompt) setComposerSeed(initialPrompt);
  }, [initialPrompt]);
  useEffect(() => {
    const selectedAgent = routeAgentName || queryAgentName || "general";
    try {
      window.localStorage.setItem(ACTIVE_AGENT_KEY, selectedAgent);
      window.dispatchEvent(
        new CustomEvent(ACTIVE_AGENT_EVENT, {
          detail: { name: selectedAgent },
        }),
      );
    } catch (e) {
      swallow(e, "storage");
    }
  }, [queryAgentName, routeAgentName]);
  useEffect(() => {
    if (
      !resolvedThreadOwnerAgentId ||
      resolvedThreadOwnerAgentId === activeAgentId
    ) {
      return;
    }
    try {
      window.dispatchEvent(
        new CustomEvent(ACTIVE_AGENT_EVENT, {
          detail: { name: resolvedThreadOwnerAgentId, source: "thread" },
        }),
      );
    } catch (e) {
      swallow(e, "event");
    }
    emitAgentChanged(resolvedThreadOwnerAgentId, "thread");
  }, [activeAgentId, resolvedThreadOwnerAgentId]);
  useEffect(() => {
    const context = settings.context as typeof settings.context & {
      page_agent_memory_mode?: string;
    };
    if (!memoryMode || context.page_agent_memory_mode === memoryMode) {
      return;
    }
    setSettings("context", {
      ...settings.context,
      page_agent_memory_mode: memoryMode,
    } as Partial<typeof settings.context>);
  }, [memoryMode, setSettings, settings, settings.context]);
  useEffect(() => {
    const prev = prevAgentRef.current;
    prevAgentRef.current = activeAgentId;
    if (prev === null || prev === activeAgentId) return;
    // Agent actually changed mid-session → flush both views.
    qc.invalidateQueries({ queryKey: ["threads", "search"] });
    // The visible route stays on the unified realtime surface; the selected
    // agent is carried by ?agent= for fresh tasks and by thread metadata for
    // history.
  }, [activeAgentId, qc]);

  useEvent(
    "agent:changed",
    ({ name, source }) => {
      if (source === "thread") return;
      if (!name || name === activeAgentId) return;
      qc.invalidateQueries({ queryKey: ["threads", "search"] });
      navigate(taskWorkspaceRoute({ agentId: name }), { replace: false });
    },
    [activeAgentId, navigate, qc],
  );

  const [
    thread,
    sendMessage,
    ,
    liveToolEvents,
    lastTurnToolEvents,
    realtimeApprovals,
  ] = useThreadStream({
    threadId,
    // Spread settings.context FIRST so our agent_name wins. Otherwise any
    // stale `agent_name` in the shared settings store (shared across
    // threads) clobbers the current page's pick — which is how turn 2+
    // started sending the wrong id before this fix.
    context: {
      ...settings.context,
      reasoning_effort: effectiveReasoningEffort,
      mode: streamMode,
      workspace_path: isProjectCodeMode ? projectWorkspacePath : undefined,
      workspace_scope: isProjectCodeMode
        ? "project"
        : isCodingWorkspaceMode
          ? "personal"
          : undefined,
      personal_workspace_enabled:
        !isProjectCodeMode && isCodingWorkspaceMode ? true : undefined,
      capability_mode: isCodingWorkspaceMode ? "code" : undefined,
      code_mode: isCodingWorkspaceMode ? "solo" : undefined,
      agent_mode: isCodingWorkspaceMode ? projectAgentMode : undefined,
      mode_preset: isCodingWorkspaceMode ? projectModePreset.id : undefined,
      workflow_preset: isCodingWorkspaceMode
        ? workflowPresetForMode(projectAgentMode, auditIntensity)
        : undefined,
      // Personal-space work mode. Backend keeps this as scope steering while the
      // same code capability/tool chain remains available in personal workspace.
      personal_mode: !isProjectCodeMode ? personalMode : undefined,
      skill_pack_profile: isCodingWorkspaceMode
        ? projectModePreset.skillPackProfile
        : undefined,
      verification_policy: isCodingWorkspaceMode
        ? projectModePreset.verificationPolicy
        : undefined,
      default_skill_packs: isCodingWorkspaceMode
        ? projectModePreset.defaultSkillPacks
        : undefined,
      default_plugins: isCodingWorkspaceMode
        ? projectModePreset.defaultPlugins
        : undefined,
      mode_contract: isCodingWorkspaceMode
        ? projectModePreset.promptContract
        : undefined,
      project_signals: projectSignals,
      agent_name: effectiveAgentId,
      // Local CLI partner model override → passed to the CLI via -m. Empty/absent
      // ⇒ the CLI keeps its own configured default. Kept separate from
      // model_name (octopus's namespace) on purpose.
      partner_model: partnerId ? partnerModel : undefined,
      interaction_mode:
        effectiveMode === "react" ||
        effectiveMode === "deep" ||
        effectiveMode === "code"
          ? "office"
          : undefined,
      ...collaborationContext,
    },
    onStart: (startedThreadId) => {
      localStartedThreadIdRef.current = startedThreadId;
      setIsNewThread(false);
      const targetPath = threadRouteFor(startedThreadId);
      // The live page deliberately stays mounted until the turn settles, so
      // React Router cannot own this transition yet. Keep sidebar selection
      // and its thread list in sync with the server-issued id immediately.
      eventBus.emit("thread:route-sync", {
        href: targetPath,
        threadId: startedThreadId,
      });
      void qc.invalidateQueries({ queryKey: ["threads", "search"] });
      // Keep the /new route mounted for the lifetime of the first turn.
      // Changing the hash here still notifies the desktop HashRouter and
      // tears down its WebSocket, even when history.replaceState is used.
      // The sidebar already follows thread:route-sync; commit the actual URL
      // once onFinish confirms that the server-owned turn is terminal.
      stageThreadRoute(targetPath);
    },
    onFinish: () => {
      void qc.invalidateQueries({ queryKey: ["threads", "search"] });
      commitThreadRoute();
    },
  });
  const [isCompressingContext, setIsCompressingContext] = useState(false);
  const selectedModel = useMemo(() => {
    const modelName = settings.context.model_name;
    return (
      models.find(
        (model) =>
          model.name === modelName ||
          model.id === modelName ||
          model.model === modelName,
      ) ?? models[0]
    );
  }, [models, settings.context.model_name]);
  const maxContextTokens = useMemo(
    () => resolveModelContextWindow(selectedModel),
    [selectedModel],
  );
  const contextTokens = useMemo(
    () => estimateCurrentContextTokens(thread.messages),
    [thread.messages],
  );
  const compactThread = (thread as typeof thread & CompactableThread).compact;
  const handleCompressContext = useCallback(async () => {
    if (!compactThread || isCompressingContext) {
      if (!compactThread) {
        toast.error("Context compression is not available for this thread");
      }
      return;
    }
    setIsCompressingContext(true);
    try {
      const result = await compactThread();
      if (result.compacted) {
        toast.success(
          t.contextCompressor?.autoCompressed ?? "Context compressed",
        );
        return;
      }
      const kept =
        result.keepRecent != null && result.turnCount != null
          ? `Only ${result.turnCount} turns; keeping the latest ${result.keepRecent}.`
          : "Nothing to compress yet.";
      toast.message(
        t.contextCompressor?.compressContext ?? "Compress context",
        {
          description:
            result.reason === "below_keep_recent"
              ? kept
              : (result.reason ?? kept),
        },
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to compress context",
      );
    } finally {
      setIsCompressingContext(false);
    }
  }, [compactThread, isCompressingContext, t.contextCompressor]);

  // If the first stream fails before onStart fires, isNewThread stays
  // true while messages already rendered, producing a Welcome overlay
  // on top of the live conversation. Second source of truth: once any
  // messages arrive, treat the thread as established.
  useEffect(() => {
    if (isNewThread && thread.messages.length > 0) {
      setIsNewThread(false);
      const targetPath = threadRouteFor(threadId);
      // Same deferred route commit as onStart. This fallback can run before
      // the loading-edge callback on a fast first item; mutating the hash here
      // used to remount the page and interrupt the turn before any answer.
      stageThreadRoute(targetPath);
      eventBus.emit("thread:route-sync", {
        href: targetPath,
        threadId,
      });
    }
  }, [
    isNewThread,
    thread.messages.length,
    setIsNewThread,
    stageThreadRoute,
    threadId,
    threadRouteFor,
  ]);

  useRegenerateHandler(thread, sendMessage, threadId);
  usePlanActionHandler(sendMessage, threadId);

  const previewBlocks = useMemo(() => {
    for (let i = thread.messages.length - 1; i >= 0; i--) {
      const msg = thread.messages[i];
      // Current turn only: an inline-preview block from an earlier turn
      // must not hijack every later completion (same scoping as
      // resultPreviewUrl below).
      if (msg && isHumanMessage(msg)) break;
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

  // Deployed preview URL (vercel/netlify/localhost/etc.) — when present and
  // no inline html blocks exist, we still treat the task as a "frontend
  // task" and auto-switch the workbench to the browser preview tab on
  // completion. The URL is also forwarded to LivePreviewPanel so it can
  // render the deployed site instead of falling back to srcDoc.
  // Only the current turn is scanned (messages after the last human message):
  // a deploy URL from an earlier turn must not hijack every later completion.
  const resultPreviewUrl = useMemo(() => {
    let turnStart = 0;
    for (let i = thread.messages.length - 1; i >= 0; i--) {
      const message = thread.messages[i];
      if (message && isHumanMessage(message)) {
        turnStart = i + 1;
        break;
      }
    }
    return extractResultUrl(thread.messages.slice(turnStart));
  }, [thread.messages]);

  const latestPersistedTodoEvents = useMemo(
    () => latestPersistedTodoEventsFromMessages(thread.messages),
    [thread.messages],
  );
  const restoredTodoEvents = useMemo(
    () =>
      restoredTodoEventsForDisplay({
        isLoading: thread.isLoading,
        lastTurnToolEvents,
        latestPersistedTodoEvents,
      }),
    [lastTurnToolEvents, latestPersistedTodoEvents, thread.isLoading],
  );
  const agentDisplayEvents = useMemo(
    () => [
      ...(lastTurnToolEvents.length > 0 ? lastTurnToolEvents : liveToolEvents),
      ...restoredTodoEvents,
    ],
    [lastTurnToolEvents, liveToolEvents, restoredTodoEvents],
  );
  const latestWorkspaceFocusTab = useMemo(
    () => workspaceFocusTabFromEvents(agentDisplayEvents),
    [agentDisplayEvents],
  );
  // Self-contained replay export, surfaced from the unified share menu.
  const replayBlocks = useMemo(
    () => screenBlocksForAgent(toWorkBlocks(agentDisplayEvents), null),
    [agentDisplayEvents],
  );
  const handleExportReplay = useCallback(() => {
    if (replayBlocks.length === 0) return;
    const title =
      thread?.values?.title || initialPrompt || t.realtime.replay.titleDefault;
    const html = buildReplayHtml(
      buildReplayFromBlocks(replayBlocks, {
        title,
        brand: "Octopus Agent",
        footer: `${new Date().toLocaleDateString()} · ${t.realtime.replay.footer}`,
      }),
    );
    downloadTextFile(html, `octopus-replay-${shareSlug(title)}.html`);
  }, [replayBlocks, thread, initialPrompt, t]);
  const latestArtifactFocusPath = useMemo(
    () => latestArtifactFocusPathFromEvents(agentDisplayEvents),
    [agentDisplayEvents],
  );
  const isAgentWorkflowMode =
    effectiveMode === "deep" ||
    effectiveMode === "react" ||
    effectiveMode === "code";
  const tasks = useTasks("all");
  const hasRunningAgentEvents = lastTurnToolEvents.some(
    (event) =>
      event.status === "running" || event.status === "waiting_approval",
  );
  const hasActiveBackgroundTask = (tasks.data?.active ?? []).some(
    (task) => task.thread_id === threadId,
  );
  const hasPausedBackgroundTask = (tasks.data?.paused ?? []).some(
    (task) => task.thread_id === threadId,
  );
  const hasPendingBackgroundTask = (tasks.data?.pending ?? []).some(
    (task) => task.thread_id === threadId,
  );
  const hasPausedOrPendingBackgroundTask =
    hasPausedBackgroundTask || hasPendingBackgroundTask;
  const requiresReportDeliverable = useMemo(
    () =>
      agentDisplayEvents.some((event) => {
        // The stream mapping layer precomputes this flag once per event —
        // consuming it avoids re-stringifying payloads on every render.
        // undefined means the event bypassed that layer (e.g. restored
        // todo events), so fall back to matching here.
        if (event.isReportLike !== undefined) return event.isReportLike;
        // Structured name check first — serializing payloads is the expensive
        // fallback (command outputs accumulate without bound while streaming).
        if (REPORT_DELIVERABLE_PATTERN.test(event.name)) return true;
        if (
          event.input != null &&
          REPORT_DELIVERABLE_PATTERN.test(JSON.stringify(event.input))
        ) {
          return true;
        }
        return (
          event.output != null &&
          REPORT_DELIVERABLE_PATTERN.test(JSON.stringify(event.output))
        );
      }),
    [agentDisplayEvents],
  );
  const hasReportArtifact = useMemo(
    () =>
      thread.messages.some(
        (message) =>
          isAIMessage(message) &&
          FINAL_DELIVERABLE_PATTERN.test(
            extractTextFromMessage(message) ||
              extractContentFromMessage(message),
          ),
      ),
    [thread.messages],
  );
  const finalArtifactEntries = useMemo(
    () => finalOutputArtifactEntries(agentDisplayEvents),
    [agentDisplayEvents],
  );
  const hasFinalArtifact = finalArtifactEntries.length > 0;
  const hasAgentAnswer = useMemo(
    () =>
      thread.messages.some((message) => {
        if (hasFinalArtifact) return true;
        if (!isAIMessage(message)) return false;
        const text =
          extractTextFromMessage(message) || extractContentFromMessage(message);
        return text.trim().length >= 80;
      }),
    [hasFinalArtifact, thread.messages],
  );
  const canSettleStaleLiveEvents =
    !thread.isLoading &&
    (!thread.error || hasFinalArtifact) &&
    hasAgentAnswer &&
    (!requiresReportDeliverable || hasReportArtifact || hasFinalArtifact);
  const agentRunSettled =
    !thread.isLoading &&
    (!hasRunningAgentEvents || canSettleStaleLiveEvents) &&
    !hasActiveBackgroundTask &&
    !hasPausedOrPendingBackgroundTask;
  const hasCompletedAgentOutput =
    (!thread.error || hasFinalArtifact) &&
    agentRunSettled &&
    (!requiresReportDeliverable || hasReportArtifact || hasFinalArtifact);
  const agentRunFailed =
    agentRunSettled &&
    !hasCompletedAgentOutput &&
    !hasPausedOrPendingBackgroundTask;
  const sidebarRunState = useMemo<
    "running" | "waiting" | "error" | null
  >(() => {
    if (hasPausedOrPendingBackgroundTask) return "waiting";
    if (agentRunFailed || (thread.error && !thread.isLoading)) return "error";
    if (agentRunSettled) return null;
    if (agentDisplayEvents.some((event) => event.status === "error")) {
      return "error";
    }
    if (
      agentDisplayEvents.some((event) => event.status === "waiting_approval")
    ) {
      return "waiting";
    }
    if (
      hasActiveBackgroundTask ||
      thread.isLoading ||
      Boolean(thread.streamingMessage) ||
      agentDisplayEvents.some((event) => event.status === "running")
    ) {
      return "running";
    }
    return null;
  }, [
    agentDisplayEvents,
    agentRunFailed,
    agentRunSettled,
    hasActiveBackgroundTask,
    hasPausedOrPendingBackgroundTask,
    thread.error,
    thread.isLoading,
    thread.streamingMessage,
  ]);
  const sidebarThreadId =
    thread.threadId ?? localStartedThreadIdRef.current ?? threadId;
  useEffect(() => {
    const href = threadRouteFor(sidebarThreadId);
    eventBus.emit("thread:run-status", {
      href,
      state: sidebarRunState,
      threadId: sidebarThreadId,
    });
    return () => {
      eventBus.emit("thread:run-status", {
        href,
        state: null,
        threadId: sidebarThreadId,
      });
    };
  }, [sidebarRunState, sidebarThreadId, threadRouteFor]);
  const shouldHideSettledProcessChrome =
    agentRunSettled && hasCompletedAgentOutput;
  const hasRenderableAgentWorkbench = useMemo(
    () =>
      isAgentWorkflowMode &&
      hasAgentWorkbenchContent(agentDisplayEvents, {
        hasAnswer: hasCompletedAgentOutput,
        runSettled: agentRunSettled,
        runFailed: agentRunFailed,
        paused: hasPausedOrPendingBackgroundTask,
      }),
    [
      agentDisplayEvents,
      agentRunFailed,
      agentRunSettled,
      hasCompletedAgentOutput,
      hasPausedOrPendingBackgroundTask,
      isAgentWorkflowMode,
    ],
  );
  const canOpenAgentWorkbench =
    !isNewThread ||
    collaborationEnabled ||
    hasRenderableAgentWorkbench ||
    !!previewBlocks ||
    // Realtime keeps the right workbench available from the first turn. The
    // actual file tree still lives in the left project pane; this panel is the
    // live agent workstation and replay surface.
    isCodingWorkspaceMode ||
    isRealtimeRoute;
  const showAgentWorkbench =
    canOpenAgentWorkbench &&
    (agentWorkbenchManuallyOpened ||
      (collaborationEnabled && !agentWorkbenchDismissed) ||
      (hasRenderableAgentWorkbench && (artifactsOpen || showAgentPlan))) &&
    !showResearchHistory &&
    !(showResearch && (!!researchJob || !!researchError));
  const artifactCount = artifacts?.length ?? 0;
  const settledWorkbenchTurnKey = useMemo(() => {
    const latestMessage = thread.messages[thread.messages.length - 1];
    return `${threadId}:${latestMessage?.id ?? thread.messages.length}`;
  }, [thread.messages, threadId]);

  useEffect(() => {
    if (!canOpenAgentWorkbench) {
      setAgentWorkbenchManuallyOpened(false);
    }
    if (!hasRenderableAgentWorkbench) {
      if (!isNewThread) {
        setAgentWorkbenchDismissed(false);
      }
      setAgentWorkbenchTabTouched(false);
    }
  }, [canOpenAgentWorkbench, hasRenderableAgentWorkbench, isNewThread]);

  useEffect(() => {
    if (
      !hasRenderableAgentWorkbench ||
      !shouldHideSettledProcessChrome ||
      artifactsOpen ||
      showAgentPlan
    ) {
      return;
    }
    if (settledWorkbenchAutoDismissedRef.current === settledWorkbenchTurnKey) {
      return;
    }
    settledWorkbenchAutoDismissedRef.current = settledWorkbenchTurnKey;
    setAgentWorkbenchDismissed(true);
    setAgentWorkbenchTabTouched(false);
  }, [
    artifactsOpen,
    hasRenderableAgentWorkbench,
    settledWorkbenchTurnKey,
    shouldHideSettledProcessChrome,
    showAgentPlan,
  ]);

  useEffect(() => {
    if (thread.isLoading) {
      setAgentWorkbenchTabTouched(false);
    }
  }, [thread.isLoading]);

  useEffect(() => {
    if (
      !showAgentWorkbench ||
      !thread.isLoading ||
      agentWorkbenchTabTouched ||
      !latestWorkspaceFocusTab
    ) {
      return;
    }
    if (latestWorkspaceFocusTab === "artifacts") {
      if (artifactCount <= 0) return;
      if (
        latestArtifactFocusPath &&
        artifacts.includes(latestArtifactFocusPath)
      ) {
        selectArtifact(latestArtifactFocusPath, true);
      }
      setArtifactsOpen(true);
      setShowAgentPlan(false);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
    }
    setAgentWorkbenchTab(latestWorkspaceFocusTab);
  }, [
    agentWorkbenchTabTouched,
    artifactCount,
    artifacts,
    latestArtifactFocusPath,
    latestWorkspaceFocusTab,
    selectArtifact,
    setArtifactsOpen,
    showAgentWorkbench,
    thread.isLoading,
  ]);

  useEffect(() => {
    if (
      // Mirrors the isNewThread auto-expand path: on mobile the panel takes
      // over the whole chat column, so never auto-open it there.
      isMobile ||
      (!previewBlocks && !resultPreviewUrl) ||
      agentWorkbenchTabTouched ||
      thread.isLoading ||
      !hasCompletedAgentOutput
    ) {
      return;
    }
    setAgentWorkbenchTab("browser");
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(true);
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
  }, [
    isMobile,
    previewBlocks,
    resultPreviewUrl,
    agentWorkbenchTabTouched,
    thread.isLoading,
    hasCompletedAgentOutput,
    setArtifactsOpen,
  ]);

  useEffect(() => {
    const handleAgentFocus = (event: Event) => {
      const detail = (event as CustomEvent<AgentWorkbenchFocusDetail>).detail;
      const agentId =
        typeof detail?.agentId === "string" ? detail.agentId.trim() : "";
      if (!agentId) return;
      setFocusedWorkbenchAgentId(agentId);
      setFocusedWorkbenchAgentView(detail?.view ?? null);
      setFocusedWorkbenchAgentNonce((n) => n + 1);
      setFocusedWorkbenchEventId(null);
      setFocusedWorkbenchEventKind(null);
      setFocusedWorkbenchEventView(null);
      setFocusedWorkbenchProcessEvent(null);
      setFocusedWorkbenchEffectKey(null);
      setArtifactsOpen(false);
      setShowAgentPlan(false);
      setAgentWorkbenchDismissed(false);
      setAgentWorkbenchManuallyOpened(true);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
      setAgentWorkbenchTab(detail?.tab ?? "agent");
      setAgentWorkbenchTabTouched(true);
    };
    window.addEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handleAgentFocus);
    return () =>
      window.removeEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handleAgentFocus);
  }, [setArtifactsOpen]);

  useEffect(() => {
    const handleOpenWorkbench = (event: Event) => {
      const detail = (event as CustomEvent<AgentWorkbenchOpenDetail>).detail;
      setFocusedWorkbenchAgentId(null);
      setFocusedWorkbenchAgentView(null);
      setFocusedWorkbenchEventId(detail?.eventId?.trim() || null);
      setFocusedWorkbenchEventKind(detail?.eventKind ?? null);
      setFocusedWorkbenchEventView(detail?.view ?? null);
      setFocusedWorkbenchProcessEvent(detail?.processEvent ?? null);
      setFocusedWorkbenchEffectKey(detail?.effectKey?.trim() || null);
      setFocusedWorkbenchEventNonce((n) => n + 1);
      setArtifactsOpen(false);
      setShowAgentPlan(false);
      setAgentWorkbenchDismissed(false);
      setAgentWorkbenchManuallyOpened(true);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
      if (detail?.tab) {
        setAgentWorkbenchTab(detail.tab);
      }
      setAgentWorkbenchTabTouched(true);
    };
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpenWorkbench);
    return () =>
      window.removeEventListener(
        AGENT_WORKBENCH_OPEN_EVENT,
        handleOpenWorkbench,
      );
  }, [setArtifactsOpen]);

  const handleSubmit = useCallback(
    (message: { text: string; images?: File[]; files?: File[] }) => {
      const images = message.images ?? [];
      const attachedFiles = message.files ?? [];
      const browserFiles = [...attachedFiles, ...images];
      if (browserFiles.length === 0) {
        void sendMessage(threadId, { text: message.text, files: [] });
        return;
      }
      // Read each image into a data URL so PromptInputFilePart has the
      // `url` field FileUIPart requires; the original File is also
      // attached so the upload path can re-use the bytes without
      // re-decoding.
      void Promise.all(
        browserFiles.map(
          (file) =>
            new Promise<PromptInputFilePart>((resolve, reject) => {
              const mediaType = file.type || "application/octet-stream";
              if (!mediaType.toLowerCase().startsWith("image/")) {
                resolve({
                  type: "file",
                  mediaType,
                  filename: file.name,
                  url: "",
                  file,
                });
                return;
              }
              const reader = new FileReader();
              reader.onload = () => {
                const url =
                  typeof reader.result === "string" ? reader.result : "";
                resolve({
                  type: "file",
                  mediaType,
                  filename: file.name,
                  url,
                  file,
                });
              };
              reader.onerror = () =>
                reject(reader.error ?? new Error("FileReader failed"));
              reader.readAsDataURL(file);
            }),
        ),
      ).then((files) => {
        void sendMessage(threadId, { text: message.text, files });
      });
    },
    [sendMessage, threadId],
  );
  useEffect(() => {
    const handleQuickReply = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: unknown }>).detail;
      const text = typeof detail?.text === "string" ? detail.text.trim() : "";
      if (!text || thread.isLoading) return;
      void sendMessage(threadId, { text, files: [] });
    };
    window.addEventListener("octopus:quick-reply", handleQuickReply);
    return () => {
      window.removeEventListener("octopus:quick-reply", handleQuickReply);
    };
  }, [sendMessage, thread.isLoading, threadId]);
  const handleModeChange = useCallback(
    (mode: ReasoningMode, draft?: string) => {
      if (mode === effectiveMode) return;
      if (mode === "code" && !isCodingWorkspaceMode) return;
      if (!isAgentRoute) {
        setDiscussionOnly(mode === "chat");
        return;
      }
      setSettings("context", {
        ...settings.context,
        mode,
      });
      if (
        mode === "react" ||
        mode === "deep" ||
        (isAgentRoute && mode === "chat")
      ) {
        navigate(newThreadRouteForMode(mode, draft), { replace: false });
      }
    },
    [
      effectiveMode,
      isAgentRoute,
      isCodingWorkspaceMode,
      navigate,
      newThreadRouteForMode,
      setSettings,
      settings.context,
    ],
  );

  const handleDeepResearch = useCallback(
    async (topic: string, options?: DeepResearchComposerOptions) => {
      const extracted = extractResearchUrls(topic);
      const clean = extracted.topic.trim();
      if (!clean || researchLoading) return false;
      const urls = Array.from(
        new Set([
          ...extracted.urls,
          ...(options?.urls ?? []),
          ...(options?.materials ?? [])
            .map((material) => material.url)
            .filter((url): url is string => !!url),
        ]),
      );
      setResearchLoading(true);
      setResearchError(null);
      setShowAgentPlan(false);
      setShowResearch(true);
      setShowResearchHistory(false);
      setShowPreview(false);
      try {
        const job = await startDeepResearch({
          topic: clean,
          thread_id: threadId,
          lead_agent_name: effectiveAgentId,
          depth: "deep",
          max_subagents: options?.maxSubagents,
          max_searches: options?.maxSearches ?? 274,
          include_thread_uploads: true,
          prefetch_sources: true,
          materials: options?.materials ?? [],
          urls,
          roles: options?.roles,
          source_kinds: options?.sourceKinds ?? [
            "web",
            "news",
            "academic",
            "company_site",
            "ecommerce",
            "social",
            "forum",
            "provided_url",
            "uploaded_file",
          ],
        });
        setResearchJob(job);
        return true;
      } catch (err) {
        swallow(err);
        setResearchError(
          err instanceof Error ? err.message : "Failed to start agent run",
        );
        return false;
      } finally {
        setResearchLoading(false);
      }
    },
    [effectiveAgentId, researchLoading, threadId],
  );

  // Implementation note.
  // Implementation note.
  // Implementation note.
  // Implementation note.
  const pauseTask = usePauseTask();
  const handleStop = useCallback(async () => {
    const activeForThread = (tasks.data?.active ?? []).find(
      (t) => t.thread_id === threadId,
    );
    await thread.stop();
    if (activeForThread) {
      try {
        await pauseTask.mutateAsync({
          taskId: activeForThread.task_id,
          reason: "user_request",
          note: t.chatPage.stopNote,
        });
      } catch (e) {
        swallow(e);
      }
    }
  }, [thread, threadId, tasks.data, pauseTask, t.chatPage.stopNote]);

  const hasResearchPanel = showResearch && (!!researchJob || !!researchError);
  const activeRightPanel: RightPanelPage | null = showResearchHistory
    ? "history"
    : hasResearchPanel
      ? "research"
      : artifactsOpen
        ? "artifacts"
        : showAgentPlan
          ? "plan"
          : showAgentWorkbench
            ? "agent"
            : null;

  const openAgentPanel = useCallback(() => {
    setFocusedWorkbenchEffectKey(null);
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(true);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchTab("agent");
    setAgentWorkbenchTabTouched(true);
  }, [setArtifactsOpen]);

  const openArtifactsPanel = useCallback(() => {
    setArtifactsOpen(true);
    setShowAgentPlan(false);
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(false);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchTab("artifacts");
    setAgentWorkbenchTabTouched(true);
  }, [setArtifactsOpen]);

  const openWorkbenchArtifact = useCallback(
    (path: string) => {
      // Same guard as the workspace-focus auto-follow effect: only select
      // paths the artifacts context actually knows about.
      if (path && artifacts.includes(path)) {
        selectArtifact(path, true);
      }
      // Open the artifacts side panel without retargeting the workbench
      // tab: "artifacts" has no embedded workbench page, so switching
      // would strand an open workbench on the legacy fallback view.
      setArtifactsOpen(true);
      setShowAgentPlan(false);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
      setAgentWorkbenchTabTouched(true);
    },
    [artifacts, selectArtifact, setArtifactsOpen],
  );

  const openFinalArtifactPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(true);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchTab("agent");
    setAgentWorkbenchTabTouched(true);
  }, [setArtifactsOpen]);

  const openAgentPlanPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(true);
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(false);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchTab("plan");
    setAgentWorkbenchTabTouched(true);
  }, [setArtifactsOpen]);

  const openPreviewPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchDismissed(false);
    setAgentWorkbenchManuallyOpened(true);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchTab("browser");
    setAgentWorkbenchTabTouched(true);
  }, [setArtifactsOpen]);

  const openResearchPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchManuallyOpened(false);
    setShowResearchHistory(false);
    setShowResearch(true);
    setShowPreview(false);
  }, [setArtifactsOpen]);

  const openResearchHistoryPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchManuallyOpened(false);
    setShowResearchHistory(true);
    setShowResearch(false);
    setShowPreview(false);
  }, [setArtifactsOpen]);

  const closeAgentWorkbenchPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchManuallyOpened(false);
    setAgentWorkbenchDismissed(true);
  }, [setArtifactsOpen]);

  const closeRightPanel = useCallback(() => {
    setArtifactsOpen(false);
    setShowAgentPlan(false);
    setAgentWorkbenchManuallyOpened(false);
    setShowResearchHistory(false);
    setShowResearch(false);
    setShowPreview(false);
    setAgentWorkbenchDismissed(true);
  }, [setArtifactsOpen]);
  const selectAgentWorkbenchTab = useCallback(
    (tab: AgentWorkbenchTabId) => {
      if (tab === "artifacts") {
        openArtifactsPanel();
        return;
      }
      if (tab === "plan") {
        openAgentPlanPanel();
        return;
      }
      setArtifactsOpen(false);
      setShowAgentPlan(false);
      setAgentWorkbenchDismissed(false);
      setAgentWorkbenchManuallyOpened(true);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
      setAgentWorkbenchTab(tab);
      setAgentWorkbenchTabTouched(true);
    },
    [openAgentPlanPanel, openArtifactsPanel, setArtifactsOpen],
  );
  return (
    <SubtasksProvider>
      <ThreadProviders thread={thread} isMock={false}>
        <ToolEffectsProvider enabled={!isNewThread} active={thread.isLoading}>
          <RealtimeApprovalToasts
            approvals={realtimeApprovals.pendingApprovals}
            resolveApproval={realtimeApprovals.resolveApproval}
          />
          <ChatBox artifactPanelMode="external" threadId={threadId}>
            <ChatPageLayout
              isNewThread={isNewThread}
              pageTitle={
                thread?.values?.title ||
                initialPrompt ||
                (isNewThread ? t.sidebar.actionNewTask : "Octopus")
              }
              header={
                <>
                  <ChatHeaderMenuButton
                    onClick={() => setChatsDrawerOpen(true)}
                    className="absolute left-3 top-1/2 -translate-y-1/2"
                  />
                  <ChatHeaderAgentBadge
                    agent={displayAgent}
                    agentId={effectiveAgentId}
                  />
                  <div className="min-w-0 flex-1">
                    <ThreadTitle
                      threadId={threadId}
                      thread={thread}
                      className="border-0 bg-transparent px-0 py-0 text-sm"
                    />
                  </div>
                  <div className="ml-auto flex shrink-0 items-center gap-1">
                    <TaskCollaboratorControl
                      agents={allTaskCollaboratorAgents}
                      selectedAgents={selectedCollaborators}
                      selectedAgentIds={selectedCollaboratorIds}
                      currentAgentName={currentTaskAgentName}
                      teamMode={teamModeIntent}
                      open={collaboratorPickerOpen}
                      onOpenChange={setCollaboratorPickerOpen}
                      onSelectedAgentIdsChange={
                        handleSelectedCollaboratorIdsChange
                      }
                      onTeamModeChange={handleTeamModeIntentChange}
                      roster={visibleCollaborationRoster}
                      threadId={threadId}
                      isNewThread={isNewThread}
                    />
                    <ChatHeaderRecButton
                      threadId={threadId}
                      onOpen={() => setRecOverlayOpen(true)}
                      isRecording={recIsRecording}
                    />
                    {(thread?.values?.title || initialPrompt) && (
                      <ShareMenu
                        iconOnly
                        title={
                          thread?.values?.title || initialPrompt || "Octopus"
                        }
                        prompt={initialPrompt || undefined}
                        onExportReplay={
                          replayBlocks.length > 0
                            ? handleExportReplay
                            : undefined
                        }
                      />
                    )}
                    <RightPanelMenu
                      activePage={activeRightPanel}
                      artifactCount={artifactCount}
                      hasAgentWorkbench={canOpenAgentWorkbench}
                      hasPlan={hasRenderableAgentWorkbench}
                      hasPreview={!!previewBlocks}
                      hasResearch={!!researchJob || !!researchError}
                      hasResearchHistory={!!researchJob || !!researchError}
                      onClosePanel={closeRightPanel}
                      onOpenAgent={openAgentPanel}
                      onOpenArtifacts={openArtifactsPanel}
                      onOpenPlan={openAgentPlanPanel}
                      onOpenPreview={openPreviewPanel}
                      onOpenResearch={openResearchPanel}
                      onOpenResearchHistory={openResearchHistoryPanel}
                    />
                  </div>
                </>
              }
              messageList={
                <MessageList
                  className="size-full"
                  threadId={threadId}
                  thread={thread}
                  header={
                    realtimeApprovals.hasMoreTurns ? (
                      <LoadOlderTurnsBanner
                        onLoad={realtimeApprovals.loadOlderTurns}
                      />
                    ) : null
                  }
                  paddingBottom={MESSAGE_LIST_DEFAULT_PADDING_BOTTOM}
                  mode={effectiveMode}
                  liveToolEvents={lastTurnToolEvents}
                  lastTurnToolEvents={lastTurnToolEvents}
                  completedAgentOutput={hasCompletedAgentOutput}
                  currentAgent={{
                    name: effectiveAgentId,
                    display_name:
                      displayAgent?.display_name || effectiveAgentId,
                    avatar_url:
                      displayAgent?.avatar_url ||
                      (threadOwnerAgentId
                        ? `/api/agents/${encodeURIComponent(threadOwnerAgentId)}/avatar`
                        : null),
                    icon: displayAgent?.icon || null,
                  }}
                  agentRoster={
                    visibleCollaborationEnabled
                      ? visibleCollaborationRoster
                      : undefined
                  }
                  footer={
                    hasCompletedAgentOutput &&
                    hasFinalArtifact &&
                    !hasReportArtifact ? (
                      <FinalArtifactCompletionNotice
                        entries={finalArtifactEntries}
                        onOpen={openFinalArtifactPanel}
                      />
                    ) : null
                  }
                />
              }
              inputArea={
                <div
                  className={cn(
                    "relative w-full transition-[max-width,transform] duration-300",
                    isNewThread && "md:-translate-y-[calc(50vh-168px)]",
                    isNewThread ? "max-w-3xl" : "max-w-(--container-width-md)",
                  )}
                >
                  {mounted ? (
                    <div className="flex flex-col gap-2">
                      {isNewThread &&
                        (isAgentRoute ? (
                          <AgentWelcome
                            agent={activeAgent}
                            agentName={effectiveAgentId}
                          />
                        ) : (
                          <Welcome mode={effectiveMode} />
                        ))}
                      <ChatInputBox
                        key={composerSeed || "empty-composer"}
                        status={
                          thread.error && !hasCompletedAgentOutput
                            ? "error"
                            : thread.isLoading
                              ? "streaming"
                              : "ready"
                        }
                        modelName={settings.context.model_name}
                        partnerId={partnerId}
                        partnerModel={partnerModel}
                        onPartnerModelChange={setPartnerModel}
                        mode={effectiveMode}
                        reasoningEffort={effectiveReasoningEffort}
                        threadId={threadId}
                        disabled={researchLoading}
                        workDir={effectiveWorkDir}
                        displayAgent={composerDisplayAgent}
                        showWorkDirSelector
                        onWorkDirChange={handleWorkDirChange}
                        lockWorkDirToThread={!isNewThread && isProjectCodeMode}
                        onOpenWorkDirInNewTask={openWorkDirInNewTask}
                        codeModeUnlocked={codeModeUnlocked}
                        projectAgentMode={projectAgentMode}
                        auditIntensity={auditIntensity}
                        personalMode={personalMode}
                        projectDetection={projectDetection}
                        onProjectAgentModeChange={setProjectAgentMode}
                        onAuditIntensityChange={setAuditIntensity}
                        onPersonalModeChange={setPersonalMode}
                        onProjectDetectionChange={setProjectDetection}
                        contextTokens={contextTokens}
                        maxContextTokens={maxContextTokens}
                        isCompressingContext={isCompressingContext}
                        onCompressContext={handleCompressContext}
                        onModelChange={(modelName) =>
                          setSettings("context", {
                            ...settings.context,
                            model_name: modelName,
                          })
                        }
                        onReasoningEffortChange={(reasoningEffort) =>
                          setSettings("context", {
                            ...settings.context,
                            reasoning_effort:
                              normalizeReasoningEffortForUi(reasoningEffort),
                          })
                        }
                        onModeChange={handleModeChange}
                        permissionMode={normalizePermissionMode(
                          settings.context.permission_mode,
                        )}
                        onPermissionModeChange={(permissionMode) => {
                          const permissionRuntime =
                            permissionRuntimeConfig(permissionMode);
                          setSettings("context", {
                            ...settings.context,
                            permission_mode: permissionRuntime.mode,
                            execution_environment:
                              permissionRuntime.execution_environment,
                          });
                        }}
                        onSubmit={handleSubmit}
                        onDeepResearch={handleDeepResearch}
                        showInspirationToggle
                        allowAgentModes
                        onStop={handleStop}
                        autoFocus={isNewThread}
                        defaultValue={composerSeed}
                        placeholder={
                          isProjectCodeMode
                            ? t.realtime.composer.placeholderCode
                            : isNewThread
                              ? t.realtime.composer.placeholderNew
                              : undefined
                        }
                        className={cn(
                          isNewThread &&
                            "border-border-default bg-card/95 shadow-[0_18px_56px_-34px_rgba(15,23,42,0.45)]",
                        )}
                      />
                      {isNewThread && !isAgentRoute && !composerSeed && (
                        <NewChatStarterGrid
                          onPick={(prompt) => {
                            setComposerSeed(prompt);
                          }}
                        />
                      )}
                    </div>
                  ) : (
                    <div
                      aria-hidden="true"
                      className="workspace-panel h-32 w-full rounded-lg"
                    />
                  )}
                </div>
              }
              sidebar={
                showResearchHistory ? (
                  <DeepResearchHistoryPanel
                    activeJobId={researchJob?.job_id}
                    onSelect={(job) => {
                      setResearchJob(job);
                      setResearchError(null);
                      setShowResearch(true);
                      setShowResearchHistory(false);
                      setShowPreview(false);
                    }}
                    onClose={() => setShowResearchHistory(false)}
                  />
                ) : showResearch && researchJob ? (
                  <DeepResearchPanel
                    job={researchJob}
                    loading={researchLoading}
                    error={researchError}
                    onClose={() => setShowResearch(false)}
                  />
                ) : showResearch && researchError ? (
                  <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <div className="flex items-center justify-between border-b border-border-default px-3 py-2">
                      <span className="text-sm font-medium">Agent</span>
                      <button
                        type="button"
                        onClick={() => setShowResearch(false)}
                        className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                        aria-label={t.common.close}
                      >
                        <XIcon className="size-3.5" />
                      </button>
                    </div>
                    <div className="p-3 text-xs text-destructive">
                      {researchError}
                    </div>
                  </div>
                ) : artifactsOpen ? (
                  <ArtifactPanel className="size-full" threadId={threadId} />
                ) : showAgentPlan ? (
                  <PlanPanel
                    className="size-full rounded-none border-0 shadow-none"
                    messages={thread.messages}
                    open
                    onClose={() => setShowAgentPlan(false)}
                  />
                ) : undefined
              }
              secondaryPanel={
                showAgentWorkbench ? (
                  <AgentWorkbenchPanel
                    activeTab={agentWorkbenchTab}
                    events={agentDisplayEvents}
                    focusedAgentId={focusedWorkbenchAgentId}
                    focusedAgentView={focusedWorkbenchAgentView}
                    focusedAgentNonce={focusedWorkbenchAgentNonce}
                    focusedEventId={focusedWorkbenchEventId}
                    focusedEventKind={focusedWorkbenchEventKind}
                    focusedEventView={focusedWorkbenchEventView}
                    focusedEventNonce={focusedWorkbenchEventNonce}
                    focusedProcessEvent={focusedWorkbenchProcessEvent}
                    focusedEffectKey={focusedWorkbenchEffectKey}
                    hasAnswer={hasCompletedAgentOutput}
                    isLoading={thread.isLoading}
                    runSettled={agentRunSettled}
                    runFailed={agentRunFailed}
                    paused={hasPausedOrPendingBackgroundTask}
                    threadId={threadId}
                    workDir={workDir}
                    browserPreviewBlocks={previewBlocks}
                    resultPreviewUrl={resultPreviewUrl}
                    rosterSeats={collaborationRosterSeats}
                    onSelectTab={selectAgentWorkbenchTab}
                    onOpenArtifact={openWorkbenchArtifact}
                  />
                ) : undefined
              }
              onSecondaryClose={closeAgentWorkbenchPanel}
              showSidebar={
                artifactsOpen ||
                showAgentPlan ||
                showResearchHistory ||
                (showResearch && (!!researchJob || !!researchError))
              }
              sidebarWidth="min(420px, 40vw)"
              secondaryPanelWidth="min(600px, 42vw)"
            />
          </ChatBox>
          <ChatsDrawer
            open={chatsDrawerOpen}
            onOpenChange={setChatsDrawerOpen}
          />
          <RecRecorderOverlay
            open={recOverlayOpen}
            threadId={threadId}
            defaultName={
              thread?.values?.title ||
              initialPrompt ||
              t.realtime.recorder.defaultName
            }
            initiallyRecording={recIsRecording}
            onClose={() => setRecOverlayOpen(false)}
            onRecordingChange={setRecIsRecording}
          />
        </ToolEffectsProvider>
      </ThreadProviders>
    </SubtasksProvider>
  );
}

function NewChatStarterGrid({ onPick }: { onPick: (prompt: string) => void }) {
  const { t } = useI18n();
  const starters = t.realtime.chatStarters;
  return (
    <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
      {starters.map((item, index) => {
        const Icon = CHAT_STARTER_ICONS[index] ?? SearchIcon;
        return (
          <button
            key={item.label}
            type="button"
            onClick={() => onPick(item.prompt)}
            title={item.prompt}
            className={cn(
              "group inline-flex items-center gap-2 rounded-xl border border-transparent bg-transparent px-3.5 py-2 text-[13px] font-medium text-muted-foreground/80",
              "transition-all duration-200 ease-out hover:-translate-y-0.5 hover:border-border-default hover:bg-card hover:text-foreground hover:shadow-[var(--shadow-sm)]",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 active:translate-y-0 active:duration-75",
            )}
          >
            <Icon className="size-4 text-muted-foreground/70 transition-all duration-200 group-hover:scale-110 group-hover:text-primary" />
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
