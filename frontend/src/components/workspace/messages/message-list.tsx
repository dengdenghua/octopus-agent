import type { AIMessage, Message, ToolMessage } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { ReactNode } from "react";
import {
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { getBackendBaseURL } from "@/core/config";
import { useLocalSettings } from "@/core/settings";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  groupMessages,
  hasContent,
  hasPresentFiles,
  hasReasoning,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import type { LiveToolEvent } from "../live-tool-timeline";

import { AgentAvatar } from "./agent-message-header";
import { ClarificationChoiceCard } from "./clarification-choice-card";
import { MarkdownContent } from "./markdown-content";
import { extractClarificationQuestionnaire } from "../clarification-questionnaire";
import {
  hasVisibleMessageGroupContent,
  MessageGroup,
} from "./message-group";
import { MessageListItem } from "./message-list-item";
import {
  hasMessageOutputSummary,
  MessageOutputSummary,
} from "./message-output-summary";
import { MessageListSkeleton } from "./skeleton";
import { ParallelSubtasksGrid } from "./parallel-subtasks-grid";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 160;
export const MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM = 80;
export const MESSAGE_LIST_TIMEOUT_WARNING_MS = 300_000;
type SubtaskUpdate = Partial<Subtask> & { id: string };
interface TurnMarker {
  agentAvatar?: string;
  agentIcon?: string | null;
  agentName?: string;
  key: string;
  kind: "dot" | "phase";
  label: string;
  number: number;
}
type TurnLocatorRunState = "done" | "error" | "pending" | "running";

const TURN_LOCATOR_VISIBLE_LIMIT = 17;
const TURN_SCROLL_VIEWPORT_CLASS = "message-list-scroll-viewport";

export function nearestTurnKeyByViewportCenter(
  markers: TurnMarker[],
  rects: Record<string, Pick<DOMRect, "bottom" | "top"> | undefined>,
  viewportTop: number,
  viewportHeight: number,
): string | null {
  if (markers.length === 0) return null;
  const viewportCenter = viewportTop + viewportHeight * 0.36;
  let best: { distance: number; key: string } | null = null;
  for (const marker of markers) {
    const rect = rects[marker.key];
    if (!rect) continue;
    const top = rect.top;
    const bottom = Math.max(rect.bottom, top);
    const center = top <= viewportCenter && bottom >= viewportCenter
      ? viewportCenter
      : (top + bottom) / 2;
    const distance = Math.abs(center - viewportCenter);
    if (!best || distance < best.distance) {
      best = { distance, key: marker.key };
    }
  }
  return best?.key ?? markers.at(-1)?.key ?? null;
}

export function visibleTurnMarkerWindow(
  markers: TurnMarker[],
  activeKey: string | null,
  limit = TURN_LOCATOR_VISIBLE_LIMIT,
): TurnMarker[] {
  if (limit <= 0 || markers.length <= limit) return markers;
  const activeIndex = activeKey
    ? markers.findIndex((marker) => marker.key === activeKey)
    : -1;
  const focusIndex = activeIndex >= 0 ? activeIndex : markers.length - 1;
  const maxStart = Math.max(0, markers.length - limit);
  const activeOffset = Math.floor(limit * 0.68);
  const start = Math.min(maxStart, Math.max(0, focusIndex - activeOffset));
  return markers.slice(start, start + limit);
}

function getTurnScrollViewport(node: Element | null): HTMLElement | Window {
  if (typeof window === "undefined" || !node) return window;

  const explicit = node.closest(`.${TURN_SCROLL_VIEWPORT_CLASS}`);
  if (explicit instanceof HTMLElement) return explicit;

  let current = node.parentElement;
  while (current) {
    const style = window.getComputedStyle(current);
    if (
      /(auto|scroll|overlay)/.test(style.overflowY) &&
      current.scrollHeight > current.clientHeight
    ) {
      return current;
    }
    current = current.parentElement;
  }

  return window;
}

const PHASE_TOOL_RE = /todo|plan|phase|task|subagent|workflow|milestone/i;

const PHASE_TURN_RE =
  /\bphase\s*\d+\b|\bphase\s*[:：-]|todo-phase|第\s*[一二三四五六七八九十0-9]+\s*阶段|阶段\s*[0-9一二三四五六七八九十]+|分阶段/i;

export function turnMarkerKindFromMessages(
  messages: Message[],
): "dot" | "phase" {
  const searchText = messages.map(extractTurnMarkerSearchText).join("\n");
  if (PHASE_TURN_RE.test(searchText)) return "phase";

  let executionSignals = 0;
  for (const message of messages) {
    if (message.type === "tool") {
      executionSignals += 1;
      continue;
    }
    if (message.type !== "ai") continue;
    const aiMessage = message as AIMessage;
    if (aiMessage.additional_kwargs?.thinking_plan) return "phase";
    if (aiMessage.additional_kwargs?.workbenchSnapshot) return "phase";
    if (aiMessage.additional_kwargs?.phases) return "phase";
    for (const toolCall of aiMessage.tool_calls ?? []) {
      executionSignals += 1;
      if (PHASE_TOOL_RE.test(toolCall.name)) return "phase";
      if (PHASE_TURN_RE.test(stringifyTurnMarkerValue(toolCall.args))) {
        return "phase";
      }
    }
  }

  return executionSignals >= 4 || messages.length >= 6 ? "phase" : "dot";
}

/**
 * Unified chat message list.
 *
 * Previous versions virtualized rows via ``@tanstack/react-virtual`` to
 * save render cost on long conversations. The approach interacted badly
 * with streaming: each token chunk grows the currently-streaming group by
 * a few lines, and the virtualizer's ResizeObserver measures async, so
 * rows below sat at stale ``translateY`` offsets for a frame or two:
 * visually, text would overlap and the scroll bar would jitter.
 *
 * We now follow the upstream deer-flow layout: a plain flex-col rendered
 * inside ``<Conversation>/<ConversationContent>``, which wraps
 * ``use-stick-to-bottom`` and handles auto-scroll semantics natively.
 * No ResizeObserver in the critical path, no translateY recomputation.
 * The one known trade-off is memory on very long conversations (hundreds
 * of messages). We accept that; virtualization can be reintroduced as a
 * separate feature later if it actually shows up in profiles.
 */

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  footer,
  compact = false,
  lastTurnToolEvents,
  liveToolEvents,
  mode = "react",
  currentAgent,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  compact?: boolean;
  footer?: ReactNode;
  lastTurnToolEvents?: LiveToolEvent[];
  liveToolEvents?: LiveToolEvent[];
  mode?: "chat" | "flash" | "thinking" | "react" | "deep" | "team" | "code";
  currentAgent?: {
    name: string;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
  } | null;
}) {
  const { t } = useI18n();
  const [settings] = useLocalSettings();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const loadingProgressAtRef = useRef<number | null>(null);
  const [loadingAgeMs, setLoadingAgeMs] = useState(0);
  const agentRoster = thread.values?.agent_roster;
  // Kept for compatibility. Other code branches used to gate behavior
  // on this. The per-message header now renders unconditionally when
  // the AI message carries agent metadata, so this flag is informational
  // only.
  const _isGroupChat = agentRoster && agentRoster.length > 0;
  void _isGroupChat;

  // O(1) lookup by agent display_name.
  const agentRosterMap = useMemo(() => {
    if (!agentRoster) return new Map();
    return new Map(agentRoster.map((a) => [a.display_name, a]));
  }, [agentRoster]);

  const messages = thread.messages;
  const progressFingerprint = useMemo(() => {
    const streamText = thread.streamingMessage
      ? extractTextFromMessage(thread.streamingMessage).trim()
      : "";
    const liveEvents = [
      ...(liveToolEvents ?? []),
      ...(lastTurnToolEvents ?? []),
    ]
      .map((event) =>
        [
          event.id,
          event.name,
          event.status,
          event.startedAt,
          event.finishedAt ?? "",
          event.iteration,
          event.agentId ?? "",
          event.subAgentRole ?? "",
          event.parentToolUseId ?? "",
        ].join(":"),
      )
      .join("|");
    return [
      thread.isLoading ? "loading" : "idle",
      thread.streamingMessage?.id ?? "",
      streamText.slice(-240),
      messages.length,
      liveEvents,
    ].join("::");
  }, [
    lastTurnToolEvents,
    liveToolEvents,
    messages.length,
    thread.isLoading,
    thread.streamingMessage,
  ]);
  useEffect(() => {
    if (!thread.isLoading) {
      loadingProgressAtRef.current = null;
      setLoadingAgeMs(0);
      return;
    }
    loadingProgressAtRef.current = Date.now();
    setLoadingAgeMs(0);
    const timer = window.setInterval(() => {
      const progressAt = loadingProgressAtRef.current ?? Date.now();
      setLoadingAgeMs(Date.now() - progressAt);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [thread.isLoading, progressFingerprint]);

  // Suppress the warning when at least one tool call is still in-progress
  // (e.g. the agent is writing a large file and producing no streaming text;
  // the tool event stays "in_progress" until completion, which is visible
  // in the live-tool timeline even if the text stream is silent).
  const hasActiveTool = (liveToolEvents ?? []).some(
    (e) => e.status === "running" || e.status === "waiting_approval",
  );
  const turnLocatorRunState = useMemo<TurnLocatorRunState>(() => {
    const events = [...(liveToolEvents ?? []), ...(lastTurnToolEvents ?? [])];
    if (thread.error && !thread.isLoading) return "error";
    if (events.some((event) => event.status === "waiting_approval")) {
      return "pending";
    }
    if (
      thread.isLoading ||
      thread.streamingMessage ||
      events.some((event) => event.status === "running")
    ) {
      return "running";
    }
    if (events.some((event) => event.status === "error")) return "error";
    return "done";
  }, [
    lastTurnToolEvents,
    liveToolEvents,
    thread.error,
    thread.isLoading,
    thread.streamingMessage,
  ]);
  const showTimeoutWarning =
    thread.isLoading &&
    loadingAgeMs >= MESSAGE_LIST_TIMEOUT_WARNING_MS &&
    !hasActiveTool;
  const threadErrorMessage = thread.error?.message ?? "";
  const isNetworkError = /network|fetch|abort|timeout|ECONNREFUSED/i.test(
    threadErrorMessage,
  );
  const isVerificationRequiredError =
    /verification required|no verification step|Code changes were produced/i.test(
      threadErrorMessage,
    );
  const errorBannerText =
    thread.error && !thread.isLoading
      ? isNetworkError
        ? t.streaming.networkLost ||
          "Network connection was interrupted. Send a message to resume from the checkpoint."
        : isVerificationRequiredError
          ? t.streaming.verificationRequired
          : /^turn failed$/i.test(threadErrorMessage)
            ? t.streaming.turnFailed
            : threadErrorMessage ||
              t.streaming.connectionLost ||
              "This reply was interrupted. Continue the chat or retry."
      : null;
  const verificationAuditNotice =
    isVerificationRequiredError && errorBannerText ? errorBannerText : null;

  // Aggregation layer (fold continuous tool-call runs into collapsible
  // bubbles) is currently disabled because it was eating streaming AI messages
  // in Code mode. Restore direct group rendering so every AI response
  // shows. Re-enable by wrapping `groupMessages` with `groupActivities`
  // once the streaming-message edge case is handled.
  const groupedMessages = useMemo(
    () => groupMessages(messages, (group) => group),
    [messages],
  );
  const auditNoticeGroupKey = useMemo(() => {
    if (!verificationAuditNotice) return null;
    for (let index = groupedMessages.length - 1; index >= 0; index -= 1) {
      const group = groupedMessages[index]!;
      if (group.type === "assistant" && hasMessageOutputSummary(group.messages)) {
        return `${group.type}:${group.id ?? `idx-${index}`}`;
      }
      if (group.type === "human") break;
    }
    return null;
  }, [groupedMessages, verificationAuditNotice]);
  const latestHumanGroupIndex = useMemo(() => {
    for (let index = groupedMessages.length - 1; index >= 0; index -= 1) {
      if (groupedMessages[index]?.type === "human") return index;
    }
    return -1;
  }, [groupedMessages]);
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const turnMarkers = useMemo<TurnMarker[]>(() => {
    const markers: TurnMarker[] = [];
    for (let index = 0; index < groupedMessages.length; index += 1) {
      const group = groupedMessages[index]!;
      if (group.type !== "human") continue;
      const nextHumanIndex = groupedMessages.findIndex(
        (candidate, candidateIndex) =>
          candidateIndex > index && candidate.type === "human",
      );
      const endIndex =
        nextHumanIndex === -1 ? groupedMessages.length : nextHumanIndex;
      const turnMessages = groupedMessages
        .slice(index, endIndex)
        .flatMap((candidate) => candidate.messages);
      const firstMessage = group.messages[0];
      const turnAiMessage = turnMessages.find(
        (message): message is AIMessage => message.type === "ai",
      );
      const agentName =
        (turnAiMessage?.additional_kwargs?.agent_display_name as
          | string
          | undefined) ||
        currentAgent?.display_name ||
        currentAgent?.name ||
        "Assistant";
      const agentAvatar =
        (turnAiMessage?.additional_kwargs?.agent_avatar_url as
          | string
          | undefined) ||
        currentAgent?.avatar_url ||
        undefined;
      const agentIcon =
        (turnAiMessage?.additional_kwargs?.agent_icon as string | undefined) ||
        currentAgent?.icon ||
        undefined;
      const rawLabel = firstMessage
        ? extractTextFromMessage(firstMessage).replace(/\s+/g, " ").trim()
        : "";
      markers.push({
        agentAvatar,
        agentIcon,
        agentName,
        key: `${group.type}:${group.id ?? `idx-${index}`}`,
        kind: turnMarkerKindFromMessages(turnMessages),
        label: rawLabel || `第 ${markers.length + 1} 轮对话`,
        number: markers.length + 1,
      });
    }
    return markers;
  }, [currentAgent, groupedMessages]);
  const [activeTurnKey, setActiveTurnKey] = useState<string | null>(null);

  useEffect(() => {
    setActiveTurnKey((current) =>
      current && turnMarkers.some((marker) => marker.key === current)
        ? current
        : (turnMarkers.at(-1)?.key ?? null),
    );
  }, [turnMarkers]);

  useEffect(() => {
    if (turnMarkers.length === 0 || typeof window === "undefined") {
      return;
    }
    const firstNode = groupRefs.current[turnMarkers[0]!.key] ?? null;
    const scrollElement = getTurnScrollViewport(firstNode);
    let frame = 0;

    const updateActiveTurn = () => {
      frame = 0;
      const rootRect =
        scrollElement instanceof Window
          ? { top: 0, height: window.innerHeight }
          : scrollElement.getBoundingClientRect();
      const rects: Record<
        string,
        Pick<DOMRect, "bottom" | "top"> | undefined
      > = {};
      for (const marker of turnMarkers) {
        rects[marker.key] = groupRefs.current[marker.key]
          ?.getBoundingClientRect();
      }
      const nextKey = nearestTurnKeyByViewportCenter(
        turnMarkers,
        rects,
        rootRect.top,
        rootRect.height,
      );
      if (nextKey) {
        setActiveTurnKey((current) => (current === nextKey ? current : nextKey));
      }
    };

    const scheduleUpdate = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(updateActiveTurn);
    };

    scheduleUpdate();
    scrollElement.addEventListener("scroll", scheduleUpdate, { passive: true });
    if (scrollElement !== window) {
      window.addEventListener("scroll", scheduleUpdate, { passive: true });
    }
    window.addEventListener("resize", scheduleUpdate);
    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(scheduleUpdate);
    if (resizeObserver) {
      if (scrollElement instanceof HTMLElement) {
        resizeObserver.observe(scrollElement);
      }
      for (const marker of turnMarkers) {
        const node = groupRefs.current[marker.key];
        if (node) resizeObserver.observe(node);
      }
    }
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      scrollElement.removeEventListener("scroll", scheduleUpdate);
      if (scrollElement !== window) {
        window.removeEventListener("scroll", scheduleUpdate);
      }
      window.removeEventListener("resize", scheduleUpdate);
      resizeObserver?.disconnect();
    };
  }, [progressFingerprint, turnMarkers]);

  const scrollToTurn = (key: string) => {
    setActiveTurnKey(key);
    groupRefs.current[key]?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };
  const subtaskUpdates = useMemo<SubtaskUpdate[]>(() => {
    const updates: SubtaskUpdate[] = [];
    for (const group of groupedMessages) {
      if (group.type !== "assistant:subagent") {
        continue;
      }
      for (const message of group.messages) {
        if (message.type === "ai") {
          const aiMsg = message as AIMessage;
          for (const toolCall of aiMsg.tool_calls ?? []) {
            if (toolCall.name !== "task" || !toolCall.id) {
              continue;
            }
            updates.push({
              id: toolCall.id,
              subagent_type: toolCall.args.subagent_type as string,
              description: toolCall.args.description as string,
              prompt: toolCall.args.prompt as string,
              status: "in_progress",
              progress: 0,
            });
          }
          continue;
        }
        if (message.type !== "tool") {
          continue;
        }
        const taskId = (message as ToolMessage).tool_call_id;
        if (!taskId) {
          continue;
        }
        const result = extractTextFromMessage(message);
        if (result.startsWith("Task Succeeded. Result:")) {
          updates.push({
            id: taskId,
            status: "completed",
            progress: 1,
            result: result.split("Task Succeeded. Result:")[1]?.trim(),
          });
        } else if (result.startsWith("Task failed.")) {
          updates.push({
            id: taskId,
            status: "failed",
            progress: 1,
            error: result.split("Task failed.")[1]?.trim(),
          });
        } else if (result.startsWith("Task timed out")) {
          updates.push({
            id: taskId,
            status: "timed_out",
            progress: 1,
            error: result,
          });
        } else {
          updates.push({ id: taskId, status: "in_progress" });
        }
      }
    }
    return updates;
  }, [groupedMessages]);

  useEffect(() => {
    for (const update of subtaskUpdates) {
      updateSubtask(update);
    }
  }, [subtaskUpdates, updateSubtask]);

  const getAgentIdentity = (msg?: (typeof messages)[number]) => {
    const aiMsg = msg?.type === "ai" ? (msg as AIMessage) : undefined;
    const name =
      (aiMsg?.additional_kwargs?.agent_display_name as string | undefined) ||
      currentAgent?.display_name ||
      currentAgent?.name;
    const avatar =
      (aiMsg?.additional_kwargs?.agent_avatar_url as string | undefined) ||
      currentAgent?.avatar_url ||
      undefined;
    const icon =
      (aiMsg?.additional_kwargs?.agent_icon as string | undefined) ||
      currentAgent?.icon ||
      undefined;
    const role = name ? agentRosterMap.get(name)?.role : undefined;
    return { name, avatar, icon, role };
  };

  const renderAssistantFrame = ({
    key,
    agentName,
    agentAvatar,
    agentIcon,
    children,
  }: {
    key: string;
    agentName?: string;
    agentAvatar?: string;
    agentIcon?: string | null;
    children: ReactNode;
  }) => {
    const displayName = agentName || "Assistant";
    return (
      <div key={key} className="flex w-full items-start gap-3">
        <AgentAvatar
          agentDisplayName={displayName}
          avatarUrl={agentAvatar}
          icon={agentIcon}
          className="mt-1 size-8 rounded-md"
        />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    );
  };

  const renderMessageWithHeader = (
    msg: (typeof messages)[number],
    keyPrefix: string | undefined,
    beforeContent?: ReactNode,
  ) => {
    const key = `${keyPrefix}/${msg.id}`;
    const content = (
      <>
        {beforeContent}
        <MessageListItem
          message={msg}
          isLoading={thread.isLoading && msg.id === thread.streamingMessage?.id}
          chatFontSize={settings.display.chat_font_size}
          suppressReasoningPanel={Boolean(beforeContent)}
          enableClarificationActions={
            !thread.isLoading && messages[messages.length - 1] === msg
          }
        />
      </>
    );
    if (msg.type !== "ai") {
      return <div key={key}>{content}</div>;
    }
    const { name, avatar, icon } = getAgentIdentity(msg);
    return renderAssistantFrame({
      key,
      agentName: name,
      agentAvatar: avatar,
      agentIcon: icon,
      children: content,
    });
  };

  const renderGroupHeader = (
    group: (typeof groupedMessages)[number],
    enableClarificationActions = false,
    keepOpen = false,
  ) => {
    if (!hasVisibleMessageGroupContent(group.messages)) return null;
    const aiMessage = group.messages.find(
      (message): message is AIMessage => message.type === "ai",
    );
    const {
      name: agentName,
      avatar: agentAvatar,
      icon: agentIcon,
    } = getAgentIdentity(aiMessage);
    const content = (
      <MessageGroup
        enableClarificationActions={enableClarificationActions}
        messages={group.messages}
        keepOpen={keepOpen}
        isLoading={
          thread.isLoading &&
          group.messages.some(
            (message) => message.id === thread.streamingMessage?.id,
          )
        }
      />
    );
    if (!agentName) return content;
    return renderAssistantFrame({
      key: `agent-frame/${group.id ?? agentName}`,
      agentName,
      agentAvatar,
      agentIcon,
      children: content,
    });
  };

  const renderGroupContent = (
    group: (typeof groupedMessages)[number],
    beforeAssistantContent?: ReactNode,
    enableClarificationActions = false,
    keepOpen = false,
    deferOutputs = false,
    auditNotice: string | null = null,
  ) => {
    if (group.type === "human" || group.type === "assistant") {
      let injectedBeforeContent = false;
      return (
        <>
          {group.messages.map((msg) => {
            const beforeContent =
              beforeAssistantContent &&
              msg.type === "ai" &&
              !injectedBeforeContent
                ? beforeAssistantContent
                : undefined;
            if (beforeContent) injectedBeforeContent = true;
            return renderMessageWithHeader(msg, group.id, beforeContent);
          })}
          {group.type === "assistant" && !deferOutputs && (
            <MessageOutputSummary
              auditNotice={auditNotice}
              messages={group.messages}
              threadId={threadId}
              className="ml-11 w-auto"
            />
          )}
        </>
      );
    }
    if (group.type === "assistant:clarification") {
      const message = group.messages[0];
      if (message && hasContent(message)) {
        const content = extractContentFromMessage(message);
        const questionnaire = extractClarificationQuestionnaire(content);
        const visibleContent = questionnaire?.visibleContent ?? content;
        return (
          <div className="w-full">
            {visibleContent.trim() && (
              <MarkdownContent
                content={visibleContent}
                isLoading={thread.isLoading}
                rehypePlugins={rehypePlugins}
              />
            )}
            <ClarificationChoiceCard
              content={content}
              active={!thread.isLoading}
              messageId={message.id}
            />
          </div>
        );
      }
      return null;
    }
    if (group.type === "assistant:present-files") {
      const files: string[] = [];
      for (const message of group.messages) {
        if (hasPresentFiles(message)) {
          files.push(...extractPresentFilesFromMessage(message));
        }
      }
      return (
        <div className="ml-11 w-auto">
          {group.messages[0] && hasContent(group.messages[0]) && (
            <MarkdownContent
              content={extractContentFromMessage(group.messages[0])}
              isLoading={thread.isLoading}
              rehypePlugins={rehypePlugins}
              className="mb-4"
            />
          )}
          {!deferOutputs && (
            <ArtifactFileList files={files} threadId={threadId} />
          )}
        </div>
      );
    }
    if (group.type === "assistant:subagent") {
      const taskIds = new Set<string>();
      for (const message of group.messages) {
        if (message.type !== "ai") continue;
        for (const toolCall of (message as AIMessage).tool_calls ?? []) {
          if (toolCall.name === "task" && toolCall.id) {
            taskIds.add(toolCall.id);
          }
        }
      }
      const results: React.ReactNode[] = [];
      for (const message of group.messages.filter((m) => m.type === "ai")) {
        if (hasReasoning(message)) {
          results.push(
            <MessageGroup
              key={"thinking-group-" + message.id}
              messages={[message]}
              keepOpen={keepOpen}
              isLoading={
                thread.isLoading && message.id === thread.streamingMessage?.id
              }
            />,
          );
        }
        results.push(
          <div
            key={"subtask-count-" + message.id}
            className="text-muted-foreground font-normal pt-2 text-sm"
          >
            {t.subagents.executing(taskIds.size)}
          </div>,
        );
        const validTaskIds = ((message as AIMessage).tool_calls ?? []).reduce<
          string[]
        >((ids, toolCall) => {
          if (toolCall.name === "task" && toolCall.id) ids.push(toolCall.id);
          return ids;
        }, []);
        if (validTaskIds.length > 1) {
          results.push(
            <ParallelSubtasksGrid
              key={"parallel-grid-" + message.id}
              taskIds={validTaskIds}
              isLoading={
                thread.isLoading && message.id === thread.streamingMessage?.id
              }
            />,
          );
        } else {
          for (const taskId of validTaskIds) {
            results.push(
              <SubtaskCard
                key={"task-group-" + taskId}
                taskId={taskId}
                isLoading={
                  thread.isLoading && message.id === thread.streamingMessage?.id
                }
              />,
            );
          }
        }
      }
      return <div className="relative z-1 flex flex-col gap-2">{results}</div>;
    }
    // Default: assistant:processing renders as MessageGroup.
    return renderGroupHeader(group, enableClarificationActions, keepOpen);
  };

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }

  return (
    <Conversation
      className={cn(
        "relative flex size-full flex-col select-text overflow-x-hidden",
        "[&_p]:select-text [&_li]:select-text [&_span]:select-text [&_pre]:select-text [&_code]:select-text",
        className,
      )}
      data-message-scroll-root="true"
      role="log"
    >
      <ConversationContent
        scrollClassName={TURN_SCROLL_VIEWPORT_CLASS}
        className={cn(
          "mx-auto w-full pt-2 gap-4",
          compact ? "max-w-none px-2" : "max-w-(--container-width-md) px-4",
        )}
      >
        {groupedMessages.map((group, index) => {
          const groupKey = `${group.type}:${group.id ?? `idx-${index}`}`;
          const isLatestGroup = index === groupedMessages.length - 1;
          const groupHasStreamingMessage =
            thread.streamingMessage != null &&
            group.messages.some(
              (message) => message.id === thread.streamingMessage?.id,
            );
          const keepGroupOpen =
            groupHasStreamingMessage || (thread.isLoading && isLatestGroup);

          const enableGroupClarificationActions =
            !thread.isLoading && isLatestGroup;
          const deferGroupOutputs =
            thread.isLoading &&
            latestHumanGroupIndex >= 0 &&
            index > latestHumanGroupIndex;
          const groupAuditNotice =
            groupKey === auditNoticeGroupKey ? verificationAuditNotice : null;

          return (
            <div
              key={groupKey}
              ref={(node) => {
                if (group.type !== "human") return;
                if (node) {
                  groupRefs.current[groupKey] = node;
                } else {
                  delete groupRefs.current[groupKey];
                }
              }}
              data-turn-key={group.type === "human" ? groupKey : undefined}
              className={cn(
                index === 0 ? "pt-1" : undefined,
                group.type === "human" ? "scroll-mt-6" : undefined,
              )}
            >
              {renderGroupContent(
                group,
                undefined,
                enableGroupClarificationActions,
                keepGroupOpen,
                deferGroupOutputs,
                groupAuditNotice,
              )}
            </div>
          );
        })}

        {footer}

        {errorBannerText && !(verificationAuditNotice && auditNoticeGroupKey) && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-amber-200/70 bg-amber-50/90 px-4 py-3 text-sm text-amber-900 shadow-sm dark:border-amber-800/50 dark:bg-amber-950/75 dark:text-amber-100"
          >
            <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-300" />
            <span className="min-w-0 leading-6">{errorBannerText}</span>
          </div>
        )}

        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>

      <TurnLocatorRail
        activeKey={activeTurnKey}
        markers={turnMarkers}
        onSelect={scrollToTurn}
        runState={turnLocatorRunState}
      />

      <ConversationScrollButton
        aria-label="回到最新消息"
        title="回到最新"
        style={{ bottom: `${Math.max(12, paddingBottom + 12)}px` }}
      >
        最新
      </ConversationScrollButton>

      {showTimeoutWarning && !thread.error && (
        <div className="absolute top-4 left-[50%] z-10 -translate-x-1/2 flex items-center gap-3 rounded-lg border border-amber-300/70 bg-amber-50/95 px-4 py-2 text-xs text-amber-900 shadow-sm backdrop-blur-sm dark:border-amber-700/50 dark:bg-amber-950/90 dark:text-amber-200">
          <AlertTriangleIcon className="size-4 shrink-0 text-amber-600" />
          <span>
            {`已 ${Math.floor(loadingAgeMs / 1000)} 秒没有新进展，可能卡住了`}
          </span>
          <button
            type="button"
            onClick={() => void thread.stop()}
            className="rounded-md border border-amber-300/80 px-2 py-1 text-[11px] font-medium text-amber-900 transition-colors hover:bg-amber-100 dark:border-amber-700/60 dark:text-amber-200 dark:hover:bg-amber-900/70"
          >
            停止
          </button>
        </div>
      )}
    </Conversation>
  );
}

function TurnLocatorRail({
  activeKey,
  markers,
  onSelect,
  runState,
}: {
  activeKey: string | null;
  markers: TurnMarker[];
  onSelect: (key: string) => void;
  runState: TurnLocatorRunState;
}) {
  if (markers.length <= 1) return null;
  const visibleMarkers = visibleTurnMarkerWindow(markers, activeKey);
  const firstMarker = markers[0]!;
  const lastMarker = markers[markers.length - 1]!;

  return (
    <nav
      aria-label={"\u5bf9\u8bdd\u5b9a\u4f4d"}
      className="absolute top-1/2 left-0 z-20 block -translate-y-1/2"
    >
      <div className="relative flex max-h-[82vh] flex-col items-center gap-1 overflow-hidden px-1 py-1.5">
        <TurnLocatorLimitButton
          active={visibleMarkers[0]?.key === firstMarker.key}
          direction="up"
          label={"\u8df3\u5230\u7b2c\u4e00\u8f6e\u5bf9\u8bdd"}
          onClick={() => onSelect(firstMarker.key)}
        />
        {visibleMarkers.map((marker) => {
          const active = marker.key === activeKey;
          const label = `\u7b2c ${marker.number} \u8f6e${
            marker.kind === "phase"
              ? "\uff08\u9636\u6bb5\u4efb\u52a1\uff09"
              : ""
          }\uff1a${marker.label}`;
          return (
            <button
              key={marker.key}
              aria-current={active ? "step" : undefined}
              aria-label={label}
              data-turn-marker-kind={marker.kind}
              className={cn(
                "group relative flex w-6 items-center justify-center rounded-full transition-all duration-150",
                "focus-visible:ring-ring/50 outline-none focus-visible:ring-2",
                "opacity-70 hover:bg-muted/45 hover:opacity-100",
                marker.kind === "phase" ? "h-8" : "h-2.5",
              )}
              onClick={() => onSelect(marker.key)}
              title={label}
              type="button"
            >
              <span
                aria-hidden="true"
                className={cn(
                  "rounded-full transition-all duration-150",
                  marker.kind === "phase"
                    ? "h-8 w-2 bg-muted-foreground/25 group-hover:bg-muted-foreground/40"
                    : "size-2.5 bg-muted-foreground/30 group-hover:bg-muted-foreground/45",
                )}
              />
              {active && (
                <TurnMarkerAvatar
                  marker={marker}
                  runState={marker.key === lastMarker.key ? runState : "done"}
                />
              )}
            </button>
          );
        })}
        <TurnLocatorLimitButton
          active={visibleMarkers[visibleMarkers.length - 1]?.key === lastMarker.key}
          direction="down"
          label={"\u8df3\u5230\u6700\u540e\u4e00\u8f6e\u5bf9\u8bdd"}
          onClick={() => onSelect(lastMarker.key)}
        />
      </div>
    </nav>
  );
}

function TurnMarkerAvatar({
  marker,
  runState,
}: {
  marker: TurnMarker;
  runState: TurnLocatorRunState;
}) {
  const backendBase = getBackendBaseURL();
  const avatarUrl = marker.agentAvatar
    ? marker.agentAvatar.startsWith("http")
      ? marker.agentAvatar
      : `${backendBase}${marker.agentAvatar}`
    : null;
  const agentName = marker.agentName ?? "Assistant";
  const icon = marker.agentIcon?.trim();
  const initial = agentName.trim().charAt(0).toUpperCase() || "?";
  const knockOutWhite = /octopus|\u7ae0\u9c7c/i.test(
    `${agentName} ${marker.agentAvatar ?? ""}`,
  );

  return (
    <div
      aria-hidden="true"
      data-turn-marker-avatar="true"
      className={cn(
        "pointer-events-none absolute flex size-5 items-center justify-center rounded-full bg-transparent drop-shadow-[0_1px_1px_rgba(0,0,0,0.18)]",
        runState === "running" &&
          "animate-[breathing_2s_ease-in-out_infinite]",
        runState === "pending" && "animate-pulse",
      )}
    >
      {avatarUrl ? (
        <TransparentTurnAvatarImage
          src={avatarUrl}
          transparentizeWhite={knockOutWhite}
        />
      ) : icon ? (
        <span className="bg-transparent text-sm leading-none">{icon}</span>
      ) : (
        <span className="bg-transparent text-[10px] font-semibold leading-none text-muted-foreground">
          {initial}
        </span>
      )}
      {runState !== "done" && <TurnMarkerStatusLight runState={runState} />}
    </div>
  );
}

function TurnMarkerStatusLight({
  runState,
}: {
  runState: Exclude<TurnLocatorRunState, "done">;
}) {
  const live = runState === "running" || runState === "pending";
  const color =
    runState === "running"
      ? "bg-emerald-500"
      : runState === "pending"
        ? "bg-amber-500"
        : "bg-red-500";
  return (
    <span
      aria-hidden="true"
      className={cn(
        "absolute -right-0.5 -bottom-0.5 size-1.5 rounded-full border border-background",
        color,
      )}
      data-turn-marker-status={runState}
    >
      {live && (
        <span
          className={cn(
            "absolute inset-0 rounded-full opacity-70",
            color,
            runState === "running" ? "animate-ping" : "animate-pulse",
          )}
        />
      )}
    </span>
  );
}

function TransparentTurnAvatarImage({
  src,
  transparentizeWhite,
}: {
  src: string;
  transparentizeWhite: boolean;
}) {
  const [renderedSrc, setRenderedSrc] = useState(src);
  const [processed, setProcessed] = useState(false);

  useEffect(() => {
    setRenderedSrc(src);
    setProcessed(false);
    if (!transparentizeWhite || typeof window === "undefined") return;

    let cancelled = false;
    const image = new window.Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      try {
        const width = image.naturalWidth || image.width;
        const height = image.naturalHeight || image.height;
        if (!width || !height) return;

        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) return;

        context.drawImage(image, 0, 0);
        const imageData = context.getImageData(0, 0, width, height);
        const { data } = imageData;
        for (let index = 0; index < data.length; index += 4) {
          const red = data[index] ?? 0;
          const green = data[index + 1] ?? 0;
          const blue = data[index + 2] ?? 0;
          const alpha = data[index + 3] ?? 0;
          const maxChannel = Math.max(red, green, blue);
          const minChannel = Math.min(red, green, blue);
          if (alpha > 0 && minChannel > 238 && maxChannel - minChannel < 18) {
            data[index + 3] = 0;
          }
        }
        context.putImageData(imageData, 0, 0);
        if (!cancelled) {
          setRenderedSrc(canvas.toDataURL("image/png"));
          setProcessed(true);
        }
      } catch {
        if (!cancelled) setProcessed(false);
      }
    };
    image.onerror = () => {
      if (!cancelled) setProcessed(false);
    };
    image.src = src;

    return () => {
      cancelled = true;
    };
  }, [src, transparentizeWhite]);

  return (
    <img
      alt=""
      className={cn(
        "size-5 bg-transparent object-contain",
        transparentizeWhite && !processed && "mix-blend-multiply",
      )}
      src={renderedSrc}
    />
  );
}

function TurnLocatorLimitButton({
  active,
  direction,
  label,
  onClick,
}: {
  active: boolean;
  direction: "down" | "up";
  label: string;
  onClick: () => void;
}) {
  const Icon = direction === "up" ? ChevronUpIcon : ChevronDownIcon;
  return (
    <button
      aria-label={label}
      className={cn(
        "relative z-1 flex size-7 items-center justify-center rounded-full bg-background/80 outline-none transition-all",
        "focus-visible:ring-ring/50 focus-visible:ring-2",
        active
          ? "text-muted-foreground/40 opacity-60"
          : "text-muted-foreground/70 opacity-85 hover:bg-muted/55 hover:text-muted-foreground hover:opacity-100",
      )}
      onClick={onClick}
      title={label}
      type="button"
    >
      <Icon
        aria-hidden="true"
        className="size-4"
      />
    </button>
  );
}

function extractTurnMarkerSearchText(message: Message) {
  const parts = [extractTextFromMessage(message)];
  if (message.type === "ai") {
    const aiMessage = message as AIMessage;
    for (const toolCall of aiMessage.tool_calls ?? []) {
      parts.push(toolCall.name);
      parts.push(stringifyTurnMarkerValue(toolCall.args));
    }
  }
  const reasoningContent = message.additional_kwargs?.reasoning_content;
  if (typeof reasoningContent === "string") {
    parts.push(reasoningContent);
  }
  const phases = message.additional_kwargs?.phases;
  if (phases) {
    parts.push(stringifyTurnMarkerValue(phases));
  }
  return parts.join("\n");
}

function stringifyTurnMarkerValue(value: unknown) {
  try {
    return JSON.stringify(value)?.slice(0, 4000) ?? "";
  } catch {
    return "";
  }
}
