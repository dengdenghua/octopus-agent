import {
  Code2Icon,
  FileTextIcon,
  ListChecksIcon,
  PanelRightIcon,
  SearchIcon,
  XIcon,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  ArtifactsProvider,
  useArtifacts,
} from "@/components/workspace/artifacts";
import { AgentProgressPill } from "@/components/workspace/agent-progress-pill";
import {
  AgentWorkbenchPanel,
  hasAgentWorkbenchContent,
  type AgentWorkbenchTabId,
  workspaceFocusTabFromEvents,
} from "@/components/workspace/agent-workbench-panel";
import {
  AGENT_WORKBENCH_FOCUS_EVENT,
  type AgentWorkbenchFocusDetail,
} from "@/components/workspace/agent-workbench-events";
import { ChatBox, useThreadChat } from "@/components/workspace/chats";
import { ChatsDrawer } from "@/components/workspace/chats-drawer";
import { ChatHeaderMenuButton } from "@/components/workspace/chat-header-menu-button";
import {
  ChatInputBox,
  type DeepResearchComposerOptions,
} from "@/components/workspace/chat-input-box";
import type { ReasoningMode } from "@/components/workspace/reasoning-mode";
import type { PromptInputFilePart } from "@/core/uploads";
import { ChatPageLayout } from "@/components/workspace/chat-page-layout";
import { ChatStreamingFooter } from "@/components/workspace/chat-streaming-footer";
import { AgentWelcome } from "@/components/workspace/agent-welcome";
import { RealtimeApprovalToasts } from "@/components/workspace/realtime-approval-toasts";
import { DeepResearchHistoryPanel } from "@/components/workspace/deep-research-history-panel";
import { DeepResearchPanel } from "@/components/workspace/deep-research-panel";
import {
  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  MessageList,
} from "@/components/workspace/messages";
import { LoadOlderTurnsBanner } from "@/components/workspace/messages/load-older-turns-banner";
import { ThreadProviders } from "@/components/workspace/messages/context";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { ShareMenu } from "@/components/workspace/share-menu";
import { TodoPanel } from "@/components/workspace/todo-panel";
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
import { useThreadSettings } from "@/core/settings";
import { useThreadStream } from "@/core/threads/hooks";
import {
  normalizePermissionMode,
  permissionRuntimeConfig,
} from "@/core/permissions";
import { startDeepResearch, type ResearchJob } from "@/core/research/api";
import { ACTIVE_AGENT_EVENT, ACTIVE_AGENT_KEY } from "@/core/agents/active";
import { useAgent } from "@/core/agents/hooks";
import { useEvent } from "@/core/events";
import { usePauseTask, useTasks } from "@/core/tasks/hooks";
import { isAIMessage, type Message } from "@/core/api/types";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractTextFromMessage,
} from "@/core/messages/utils";
import { useModels } from "@/core/models/hooks";
import { resolveModelContextWindow } from "@/core/models/context-window";
import {
  extractCodeBlocks,
  hasPreviewableBlocks,
} from "@/lib/extract-code-blocks";
import { isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";

const BOOKMARKLET_AGENT_IDS = new Set([
  "general",
  "coder",
  "desktop_operator",
  "vibe_selling",
  "ecommerce_mind",
]);

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

const NEW_CHAT_STARTERS: Array<{
  label: string;
  prompt: string;
  icon: LucideIcon;
  tone: string;
}> = [
  {
    label: "调研一个方向",
    prompt:
      "调研一个值得进入的细分赛道，输出机会点、竞品格局、风险和下一步行动。",
    icon: SearchIcon,
    tone: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  },
  {
    label: "规划一项工作",
    prompt:
      "把这个目标拆成可执行计划，按优先级列出里程碑、风险和今天要做的第一步。",
    icon: ListChecksIcon,
    tone: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  },
  {
    label: "写一份文档",
    prompt:
      "帮我写一份清晰的项目说明，包含背景、目标、方案、时间线和验收标准。",
    icon: FileTextIcon,
    tone: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  },
  {
    label: "检查一段代码",
    prompt:
      "帮我审查这段代码，找出潜在 bug、边界情况、性能问题和可以直接修改的地方。",
    icon: Code2Icon,
    tone: "bg-rose-500/10 text-rose-700 dark:text-rose-300",
  },
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

  return (
    <button
      type="button"
      aria-label={activePage ? "关闭右侧窗口" : "打开右侧窗口"}
      title={activePage ? "关闭右侧窗口" : "打开右侧窗口"}
      onClick={handleTogglePanel}
      className={cn(
        "flex size-8 items-center justify-center rounded-md border transition-colors shadow-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        activePage
          ? "border-border/55 bg-muted/45 text-foreground"
          : "border-transparent bg-transparent hover:border-border/45 hover:bg-muted/45 hover:text-foreground",
      )}
    >
      <PanelRightIcon className="size-4" />
    </button>
  );
}

function recordFromUnknown(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
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
export default function ChatsPage() {
  const chatState = useThreadChat();

  return (
    <ArtifactsProvider threadId={chatState.threadId}>
      <ChatsPageContent chatState={chatState} />
    </ArtifactsProvider>
  );
}

function ChatsPageContent({
  chatState,
}: {
  chatState: ReturnType<typeof useThreadChat>;
}) {
  const { t } = useI18n();
  const { threadId, isNewThread, setIsNewThread } = chatState;
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
  const settledWorkbenchAutoDismissedRef = useRef<string | null>(null);
  const [discussionOnly, setDiscussionOnly] = useState(false);
  const [chatsDrawerOpen, setChatsDrawerOpen] = useState(false);
  // Work directory for code/research-flavored conversations. Empty by
  // default — pure chat doesn't need a folder; the selector pill only
  // appears for react/deep modes (see showWorkDirSelector below).
  const [workDir, setWorkDir] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    try {
      return window.localStorage.getItem("chat:workdir:lastUsed") ?? "";
    } catch {
      return "";
    }
  });
  const handleWorkDirChange = useCallback((dir: string) => {
    setWorkDir(dir);
    try {
      if (dir) window.localStorage.setItem("chat:workdir:lastUsed", dir);
    } catch (e) {
      swallow(e);
    }
  }, []);

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

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    setFocusedWorkbenchAgentId(null);
    setAgentWorkbenchManuallyOpened(false);
  }, [threadId]);

  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams<{ agentName?: string }>();
  const qc = useQueryClient();
  const searchParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search],
  );
  const requestedAgent = searchParams.get("agent") ?? "";
  const bookmarkletAgent = BOOKMARKLET_AGENT_IDS.has(requestedAgent)
    ? requestedAgent
    : "";
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
  const memoryMode = searchParams.get("memory") ?? "";

  // Route-scoped agent identity.
  // Plain chats use the general model-chat persona; agent identity is
  // route-scoped to `/workspace/agents/:agent/chats/...`.
  const activeAgentId = routeAgentName || bookmarkletAgent || "general";
  const { agent: activeAgent } = useAgent(activeAgentId);
  const routeMode = settings.context.mode;
  const effectiveMode: ReasoningMode =
    isAgentRoute && routeMode === "deep"
      ? routeMode
      : isAgentRoute
        ? "react"
        : discussionOnly
          ? "chat"
          : "react";
  const threadRouteBase = isAgentRoute
    ? `/workspace/agents/${encodeURIComponent(activeAgentId)}/chats`
    : location.pathname.startsWith("/workspace/chats")
      ? "/workspace/chats"
      : "/workspace/realtime";
  const threadRouteFor = useCallback(
    (id: string) => `${threadRouteBase}/${id}`,
    [threadRouteBase],
  );
  const newThreadRouteForMode = useCallback(
    (mode: string, prompt?: string) => {
      const query = prompt?.trim()
        ? `?prompt=${encodeURIComponent(prompt.trim())}`
        : "";
      if (mode === "react" || mode === "deep") {
        return `/workspace/agents/${encodeURIComponent(activeAgentId)}/chats/new${query}`;
      }
      return location.pathname.startsWith("/workspace/chats")
        ? `/workspace/chats/new${query}`
        : `/workspace/realtime/new${query}`;
    },
    [activeAgentId, location.pathname],
  );

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
  const initialPrompt = useMemo(() => {
    return searchParams.get("prompt") ?? "";
  }, [searchParams]);
  const [composerSeed, setComposerSeed] = useState(initialPrompt);
  const prevAgentRef = useRef<string | null>(null);
  const pendingRouteSyncRef = useRef<string | null>(null);
  useEffect(() => {
    if (initialPrompt) setComposerSeed(initialPrompt);
  }, [initialPrompt]);
  useEffect(() => {
    const selectedAgent = routeAgentName || bookmarkletAgent || "general";
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
  }, [bookmarkletAgent, routeAgentName]);
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
  }, [memoryMode, setSettings, settings.context]);
  useEffect(() => {
    const prev = prevAgentRef.current;
    prevAgentRef.current = activeAgentId;
    if (prev === null || prev === activeAgentId) return;
    // Agent actually changed mid-session → flush both views.
    qc.invalidateQueries({ queryKey: ["threads", "search"] });
    // route — hitting it falls through the `*` catch-all in router.tsx
    // which redirects to `/` (landing page). Use `/chats/new` so we
    // land on a fresh chat for the new agent instead of bouncing out
    // of the workspace entirely.
  }, [activeAgentId, qc]);

  useEvent(
    "agent:changed",
    ({ name }) => {
      if (!name || name === activeAgentId) return;
      qc.invalidateQueries({ queryKey: ["threads", "search"] });
      navigate(`/workspace/agents/${encodeURIComponent(name)}/chats/new`, {
        replace: false,
      });
    },
    [activeAgentId, navigate, qc],
  );

  const [thread, sendMessage, , liveToolEvents, lastTurnToolEvents, realtimeApprovals] =
    useThreadStream({
      threadId,
      // Spread settings.context FIRST so our agent_name wins. Otherwise any
      // stale `agent_name` in the shared settings store (shared across
      // threads) clobbers the current page's pick — which is how turn 2+
      // started sending the wrong id before this fix.
      context: {
        ...settings.context,
        mode: effectiveMode,
        agent_name: activeAgentId,
        interaction_mode:
          effectiveMode === "react" || effectiveMode === "deep"
            ? "office"
            : undefined,
      },
      onStart: (startedThreadId) => {
        setIsNewThread(false);
        const targetPath = threadRouteFor(startedThreadId);
        const currentPath =
          typeof window === "undefined"
            ? ""
            : window.location.hash.replace(/^#/, "") ||
              window.location.pathname;
        if (currentPath !== targetPath && typeof window !== "undefined") {
          // Avoid React Router remounting the page while the SSE stream is
          // active. A remount aborts the stream and looks like a full reload.
          window.history.replaceState(
            window.history.state,
            "",
            `#${targetPath}`,
          );
          pendingRouteSyncRef.current = targetPath;
        }
      },
      onFinish: () => {
        const targetPath = pendingRouteSyncRef.current;
        pendingRouteSyncRef.current = null;
        if (targetPath) {
          navigate(targetPath, { replace: true });
        }
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
      if (
        typeof window !== "undefined" &&
        (window.location.hash.replace(/^#/, "") || window.location.pathname) !==
          targetPath
      ) {
        window.history.replaceState(window.history.state, "", `#${targetPath}`);
        pendingRouteSyncRef.current = targetPath;
      }
    }
  }, [
    isNewThread,
    navigate,
    thread.messages.length,
    setIsNewThread,
    threadId,
    threadRouteFor,
  ]);

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
  const latestArtifactFocusPath = useMemo(
    () => latestArtifactFocusPathFromEvents(agentDisplayEvents),
    [agentDisplayEvents],
  );
  const isAgentWorkflowMode =
    effectiveMode === "deep" || effectiveMode === "react";
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
  const requiresReportDeliverable = agentDisplayEvents.some((event) =>
    /deep-research|report|docx|pptx|pdf|research|swarm/i.test(
      [
        event.name,
        JSON.stringify(event.input ?? {}),
        JSON.stringify(event.output ?? {}),
      ].join(" "),
    ),
  );
  const hasReportArtifact = thread.messages.some(
    (message) =>
      isAIMessage(message) &&
      /report|docx|pptx|pdf|xlsx|html|报告|调研|总结|交付|文档|方案/i.test(
        extractTextFromMessage(message) || extractContentFromMessage(message),
      ),
  );
  const hasAgentAnswer = thread.messages.some((message) => {
    if (!isAIMessage(message)) return false;
    const text =
      extractTextFromMessage(message) || extractContentFromMessage(message);
    return text.trim().length >= 80;
  });
  const canSettleStaleLiveEvents =
    !thread.isLoading &&
    !thread.error &&
    hasAgentAnswer &&
    (!requiresReportDeliverable || hasReportArtifact);
  const agentRunSettled =
    !thread.isLoading &&
    (!hasRunningAgentEvents || canSettleStaleLiveEvents) &&
    !hasActiveBackgroundTask &&
    !hasPausedOrPendingBackgroundTask;
  const hasCompletedAgentOutput =
    !thread.error &&
    agentRunSettled &&
    (!requiresReportDeliverable || hasReportArtifact);
  const agentRunFailed =
    agentRunSettled &&
    !hasCompletedAgentOutput &&
    !hasPausedOrPendingBackgroundTask;
  const shouldHideSettledProcessChrome =
    agentRunSettled && hasCompletedAgentOutput;
  const currentTodoEvents = shouldHideSettledProcessChrome
    ? []
    : agentDisplayEvents;
  const hasCurrentTodos = currentTodoEvents.some(
    (event) => event.name === "todo_write" && event.input,
  );
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
  const showAgentProgressPill =
    hasRenderableAgentWorkbench &&
    hasCurrentTodos &&
    !shouldHideSettledProcessChrome;
  const canOpenAgentWorkbench =
    !isNewThread || hasRenderableAgentWorkbench || !!previewBlocks;
  const showAgentWorkbench =
    canOpenAgentWorkbench &&
    (agentWorkbenchManuallyOpened ||
      (hasRenderableAgentWorkbench &&
        (!agentWorkbenchDismissed || artifactsOpen || showAgentPlan))) &&
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
      setAgentWorkbenchDismissed(false);
      setAgentWorkbenchTabTouched(false);
    }
  }, [canOpenAgentWorkbench, hasRenderableAgentWorkbench]);

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
    const handleAgentFocus = (event: Event) => {
      const detail = (event as CustomEvent<AgentWorkbenchFocusDetail>).detail;
      const agentId =
        typeof detail?.agentId === "string" ? detail.agentId.trim() : "";
      if (!agentId) return;
      setFocusedWorkbenchAgentId(agentId);
      setArtifactsOpen(false);
      setShowAgentPlan(false);
      setAgentWorkbenchDismissed(false);
      setShowResearchHistory(false);
      setShowResearch(false);
      setShowPreview(false);
      setAgentWorkbenchTab("agent");
      setAgentWorkbenchTabTouched(true);
    };
    window.addEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handleAgentFocus);
    return () =>
      window.removeEventListener(AGENT_WORKBENCH_FOCUS_EVENT, handleAgentFocus);
  }, [setArtifactsOpen]);

  const handleSubmit = useCallback(
    (message: { text: string; images?: File[] }) => {
      const images = message.images ?? [];
      if (images.length === 0) {
        void sendMessage(threadId, { text: message.text, files: [] });
        return;
      }
      // Read each image into a data URL so PromptInputFilePart has the
      // `url` field FileUIPart requires; the original File is also
      // attached so the upload path can re-use the bytes without
      // re-decoding.
      void Promise.all(
        images.map(
          (file) =>
            new Promise<PromptInputFilePart>((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => {
                const url =
                  typeof reader.result === "string" ? reader.result : "";
                resolve({
                  type: "file",
                  mediaType: file.type || "image/png",
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
      location.pathname,
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
          lead_agent_name: activeAgentId,
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
    [activeAgentId, researchLoading, threadId],
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
  }, [thread, threadId, tasks.data, pauseTask]);

  const hasResearchPanel = showResearch && (!!researchJob || !!researchError);
  const activeRightPanel: RightPanelPage | null = showAgentWorkbench
    ? "agent"
    : artifactsOpen
      ? "artifacts"
      : showAgentPlan
        ? "plan"
        : showResearchHistory
          ? "history"
          : hasResearchPanel
            ? "research"
            : null;

  const openAgentPanel = useCallback(() => {
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
        <RealtimeApprovalToasts
          approvals={realtimeApprovals.pendingApprovals}
          resolveApproval={realtimeApprovals.resolveApproval}
        />
        <ChatBox artifactPanelMode="external" threadId={threadId}>
          <ChatPageLayout
            isNewThread={isNewThread}
            header={
              <>
                <ChatHeaderMenuButton
                  onClick={() => setChatsDrawerOpen(true)}
                />
                <div className="min-w-0 flex-1">
                  <ThreadTitle
                    threadId={threadId}
                    thread={thread}
                    className="border-0 bg-transparent px-0 py-0 text-sm"
                  />
                </div>
                <div className="ml-auto flex shrink-0 items-center gap-1">
                  {(thread?.values?.title || initialPrompt) && (
                    <ShareMenu
                      iconOnly
                      title={thread?.values?.title || initialPrompt || "Octopus"}
                      prompt={initialPrompt || undefined}
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
                paddingBottom={
                  MESSAGE_LIST_DEFAULT_PADDING_BOTTOM +
                  (hasCurrentTodos ? 96 : 0)
                }
                mode={effectiveMode}
                liveToolEvents={lastTurnToolEvents}
                lastTurnToolEvents={lastTurnToolEvents}
                currentAgent={{
                  name: activeAgentId,
                  display_name: activeAgent?.display_name || activeAgentId,
                  avatar_url: activeAgent?.avatar_url || null,
                  icon: activeAgent?.icon || null,
                }}
                footer={
                  <ChatStreamingFooter
                    thread={thread}
                    liveToolEvents={lastTurnToolEvents}
                    threadId={threadId}
                    mode={effectiveMode}
                  />
                }
              />
            }
            inputArea={
              <div
                className={cn(
                  "relative w-full transition-all duration-300",
                  isNewThread && "md:-translate-y-[calc(50vh-168px)]",
                  isNewThread ? "max-w-3xl" : "max-w-(--container-width-md)",
                )}
              >
                {mounted ? (
                  <div
                    className={cn(
                      "flex flex-col",
                      showAgentProgressPill ? "gap-0" : "gap-2",
                    )}
                  >
                    {isNewThread &&
                      (isAgentRoute ? (
                        <AgentWelcome
                          agent={activeAgent}
                          agentName={activeAgentId}
                        />
                      ) : (
                        <Welcome mode={effectiveMode} />
                      ))}
                    {showAgentProgressPill ? (
                      <AgentProgressPill
                        events={agentDisplayEvents}
                        hasAnswer={hasCompletedAgentOutput}
                        runSettled={agentRunSettled}
                        runFailed={agentRunFailed}
                        paused={hasPausedOrPendingBackgroundTask}
                        progressScopeKey={`${threadId}:agent-progress-plan`}
                      />
                    ) : (
                      <TodoPanel
                        liveToolEvents={currentTodoEvents}
                        className="relative z-10"
                      />
                    )}
                    <ChatInputBox
                      key={composerSeed || "empty-composer"}
                      status={
                        thread.error
                          ? "error"
                          : thread.isLoading
                            ? "streaming"
                            : "ready"
                      }
                      modelName={settings.context.model_name}
                      mode={effectiveMode}
                      reasoningEffort={settings.context.reasoning_effort}
                      threadId={threadId}
                      disabled={researchLoading}
                      workDir={workDir}
                      showWorkDirSelector={
                        effectiveMode === "react" || effectiveMode === "deep"
                      }
                      onWorkDirChange={handleWorkDirChange}
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
                          reasoning_effort: reasoningEffort,
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
                        isNewThread
                          ? "描述任务、贴链接，或输入 / 选择命令..."
                          : undefined
                      }
                      className={cn(
                        isNewThread &&
                          "border-border/70 bg-card/95 shadow-[0_18px_56px_-34px_rgba(15,23,42,0.45)]",
                        showAgentProgressPill && "rounded-t-none border-t-0",
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
                  <div className="flex items-center justify-between border-b border-border/50 px-3 py-2">
                    <span className="text-sm font-medium">Agent</span>
                    <button
                      onClick={() => setShowResearch(false)}
                      className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                    >
                      <XIcon className="size-3.5" />
                    </button>
                  </div>
                  <div className="p-3 text-xs text-destructive">
                    {researchError}
                  </div>
                </div>
              ) : showAgentWorkbench ? (
                <AgentWorkbenchPanel
                  activeTab={agentWorkbenchTab}
                  events={agentDisplayEvents}
                  focusedAgentId={focusedWorkbenchAgentId}
                  hasAnswer={hasCompletedAgentOutput}
                  runSettled={agentRunSettled}
                  runFailed={agentRunFailed}
                  paused={hasPausedOrPendingBackgroundTask}
                  threadId={threadId}
                  workDir={workDir}
                  browserPreviewBlocks={previewBlocks}
                  onClose={closeAgentWorkbenchPanel}
                  onSelectTab={selectAgentWorkbenchTab}
                />
              ) : undefined
            }
            showSidebar={
              artifactsOpen ||
              showResearchHistory ||
              (showResearch && (!!researchJob || !!researchError)) ||
              showAgentWorkbench
            }
            sidebarWidth={
              showAgentWorkbench ? "min(600px, 42vw)" : "min(420px, 40vw)"
            }
          />
        </ChatBox>
        <ChatsDrawer
          open={chatsDrawerOpen}
          onOpenChange={setChatsDrawerOpen}
        />
      </ThreadProviders>
    </SubtasksProvider>
  );
}

function NewChatStarterGrid({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center justify-between gap-3 px-1">
        <div className="text-[12px] font-medium text-muted-foreground">
          常用任务
        </div>
        <div className="hidden text-[11px] text-muted-foreground/70 sm:block">
          精选场景
        </div>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {NEW_CHAT_STARTERS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.label}
              type="button"
              onClick={() => onPick(item.prompt)}
              className={cn(
                "group flex min-h-[76px] items-start gap-3 rounded-lg border border-border/60 bg-background/78 px-3 py-3 text-left shadow-sm",
                "transition-[border-color,background-color,box-shadow,transform] duration-150 hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card hover:shadow-md",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 active:translate-y-0",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md transition-transform group-hover:scale-[1.03]",
                  item.tone,
                )}
              >
                <Icon className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-medium text-foreground">
                  {item.label}
                </span>
                <span className="mt-1 line-clamp-2 block text-[11.5px] leading-4 text-muted-foreground">
                  {item.prompt}
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
