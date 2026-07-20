import type { AIMessage, Message, ToolMessage } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { ReactNode } from "react";
import {
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  PlayCircleIcon,
  XCircleIcon,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  memo,
} from "react";

import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
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
  type MessageGroup as CoreMessageGroup,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { StreamVitals } from "@/core/realtime/stream-vitals";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { emitOpenAgentWorkbench } from "../agent-workbench-events";
import type { LiveToolEvent } from "../live-tool-timeline";
import { PublicThinkingStatus } from "../public-thinking-status";
import {
  type AgentRunState,
  agentRunStatusLightClass,
  agentRunStatusLightPulseClass,
} from "../agent-run-status";

import { withAgentAvatarVersion } from "@/core/agents/avatar";

import { AgentAvatar } from "./agent-message-header";
import { ClarificationChoiceCard } from "./clarification-choice-card";
import { MarkdownContent } from "./markdown-content";
import { extractClarificationQuestionnaire } from "../clarification-questionnaire";
import { hasVisibleMessageGroupContent, MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import {
  type FailurePresentation,
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
  key: string;
  kind: "dot" | "phase";
  label: string;
  number: number;
}
function sameTurnMarker(a: TurnMarker, b: TurnMarker): boolean {
  return (
    a.key === b.key &&
    a.kind === b.kind &&
    a.label === b.label &&
    a.number === b.number
  );
}
type TurnLocatorRunState = AgentRunState;
type MessageListAgentRole = "tl" | "member" | string;

interface MessageListAgentRosterEntry {
  agent_id?: string | null;
  avatar_url?: string | null;
  display_name?: string | null;
  icon?: string | null;
  name?: string | null;
  role?: MessageListAgentRole | null;
}

interface AgentIdentity {
  avatar?: string;
  icon?: string | null;
  id?: string;
  name?: string;
  role?: string;
}

const EMPTY_AGENT_ROSTER: MessageListAgentRosterEntry[] = [];
const TURN_LOCATOR_VISIBLE_LIMIT = 17;
const TURN_SCROLL_VIEWPORT_CLASS = "message-list-scroll-viewport";
const STREAM_PROGRESS_TAIL_LENGTH = 240;

export interface MessageTurnSlice {
  /** Indexes into the grouped-message array, kept contiguous and ordered. */
  groupIndexes: number[];
  /** Human group key when present; leading system content uses a prelude key. */
  key: string;
}

/**
 * Split the flat message-group stream into stable user turns.
 *
 * A turn starts at a human group and owns every following group until the next
 * human group. Keeping this boundary independent from streaming content lets
 * completed turns use display locking while the newest turn remains fully
 * rendered and free to grow token by token.
 */
export function partitionMessageGroupsIntoTurns(
  groups: CoreMessageGroup[],
): MessageTurnSlice[] {
  const turns: MessageTurnSlice[] = [];

  for (let index = 0; index < groups.length; index += 1) {
    const group = groups[index]!;
    if (group.type === "human" || turns.length === 0) {
      turns.push({
        groupIndexes: [index],
        key:
          group.type === "human"
            ? `${group.type}:${group.id ?? `idx-${index}`}`
            : `prelude:${group.type}:${group.id ?? `idx-${index}`}`,
      });
      continue;
    }

    turns[turns.length - 1]!.groupIndexes.push(index);
  }

  return turns;
}

export function streamingMessageProgressKey(
  message: Message | null | undefined,
): string {
  if (!message) return "";
  if (typeof message.content === "string") {
    return `${message.content.length}:${message.content.slice(-STREAM_PROGRESS_TAIL_LENGTH)}`;
  }
  return message.content
    .filter((part) => part.type === "text")
    .map(
      (part) =>
        `${part.text.length}:${part.text.slice(-STREAM_PROGRESS_TAIL_LENGTH)}`,
    )
    .join("|");
}

function cleanIdentityText(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function identityKey(value: unknown): string | undefined {
  return cleanIdentityText(value)?.toLowerCase();
}

function agentIdForRosterEntry(
  entry?: MessageListAgentRosterEntry | null,
): string | undefined {
  return cleanIdentityText(entry?.name) ?? cleanIdentityText(entry?.agent_id);
}

function displayNameForRosterEntry(
  entry?: MessageListAgentRosterEntry | null,
): string | undefined {
  return (
    cleanIdentityText(entry?.display_name) ??
    cleanIdentityText(entry?.name) ??
    cleanIdentityText(entry?.agent_id)
  );
}

function fallbackAgentAvatarUrl(agentId?: string | null): string | undefined {
  const cleanAgentId = cleanIdentityText(agentId);
  return cleanAgentId
    ? `/api/agents/${encodeURIComponent(cleanAgentId)}/avatar`
    : undefined;
}

function rosterEntryHasUsableAvatar(
  entry?: MessageListAgentRosterEntry | null,
) {
  return Boolean(
    cleanIdentityText(entry?.avatar_url) ||
    fallbackAgentAvatarUrl(agentIdForRosterEntry(entry)),
  );
}

function preferRosterEntry(
  current: MessageListAgentRosterEntry | undefined,
  next: MessageListAgentRosterEntry,
): MessageListAgentRosterEntry {
  if (!current) return next;
  if (
    !rosterEntryHasUsableAvatar(current) &&
    rosterEntryHasUsableAvatar(next)
  ) {
    return next;
  }
  if (!cleanIdentityText(current.icon) && cleanIdentityText(next.icon)) {
    return next;
  }
  if (
    !cleanIdentityText(current.display_name) &&
    cleanIdentityText(next.display_name)
  ) {
    return next;
  }
  return current;
}

function buildAgentRosterMap(entries: MessageListAgentRosterEntry[]) {
  const map = new Map<string, MessageListAgentRosterEntry>();
  for (const entry of entries) {
    for (const key of [
      identityKey(entry.name),
      identityKey(entry.agent_id),
      identityKey(entry.display_name),
    ]) {
      if (!key) continue;
      map.set(key, preferRosterEntry(map.get(key), entry));
    }
  }
  return map;
}

function findRosterEntry(
  map: Map<string, MessageListAgentRosterEntry>,
  ...keys: Array<unknown>
): MessageListAgentRosterEntry | undefined {
  for (const key of keys) {
    const normalized = identityKey(key);
    if (!normalized) continue;
    const entry = map.get(normalized);
    if (entry) return entry;
  }
  return undefined;
}

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
    const center =
      top <= viewportCenter && bottom >= viewportCenter
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
 * Group objects are rebuilt from scratch on every upstream state flush, so
 * comparing `prev.group === next.group` would never hold during streaming.
 * Compare the contained message references instead: once the adapter keeps
 * message identities stable, completed groups become deep-equal by
 * reference and stay frozen.
 */
function sameGroupContent(a: CoreMessageGroup, b: CoreMessageGroup): boolean {
  if (a === b) return true;
  if (a.type !== b.type || a.id !== b.id) return false;
  if (a.messages.length !== b.messages.length) return false;
  for (let index = 0; index < a.messages.length; index += 1) {
    if (a.messages[index] !== b.messages[index]) return false;
  }
  return true;
}

// Full message slice of the turn a group belongs to: from the nearest
// preceding human group through the last group before the next human one.
// Grouping never puts human/tool messages into a plain "assistant" group,
// so per-turn scans (verifications, original prompt, result URL) must look
// at the whole turn, not just the group's own messages. Groups can share
// message objects (a long final answer is pushed to both the processing
// and the assistant group), hence the identity dedupe.
function turnMessagesForGroup(
  groupedMessages: CoreMessageGroup[],
  group: CoreMessageGroup,
): Message[] {
  const index = groupedMessages.indexOf(group);
  if (index === -1) return group.messages;
  let start = index;
  while (start > 0 && groupedMessages[start]!.type !== "human") start -= 1;
  let end = index;
  while (
    end + 1 < groupedMessages.length &&
    groupedMessages[end + 1]!.type !== "human"
  ) {
    end += 1;
  }
  const seen = new Set<Message>();
  const slice: Message[] = [];
  for (const turnGroup of groupedMessages.slice(start, end + 1)) {
    for (const message of turnGroup.messages) {
      if (seen.has(message)) continue;
      seen.add(message);
      slice.push(message);
    }
  }
  return slice;
}

// A turn can contain several plain assistant groups (a long final answer
// is dual-mounted after a processing group, consecutive text replies,
// ...). Only the last one gets the turn-wide receipt scan — otherwise
// every group would render an identical full receipt for the same turn.
function isLastAssistantGroupOfTurn(
  groupedMessages: CoreMessageGroup[],
  group: CoreMessageGroup,
): boolean {
  const index = groupedMessages.indexOf(group);
  if (index === -1) return true;
  for (let i = index + 1; i < groupedMessages.length; i++) {
    const later = groupedMessages[i]!;
    if (later.type === "human") break;
    if (later.type === "assistant") return false;
  }
  return true;
}

function hasVisibleAssistantText(group: CoreMessageGroup): boolean {
  return group.messages.some(
    (message) =>
      message.type === "ai" &&
      extractContentFromMessage(message).trim().length > 0,
  );
}

function assistantGroupContainsFailureMessage(
  group: CoreMessageGroup,
  failureMessage: string,
): boolean {
  const normalizedFailure = failureMessage.replace(/\s+/g, " ").trim();
  if (!normalizedFailure) return false;

  return group.messages.some((message) => {
    if (message.type !== "ai") return false;
    const visibleText = extractTextFromMessage(message)
      .replace(/\s+/g, " ")
      .trim();
    if (!visibleText) return false;
    return (
      visibleText.includes(normalizedFailure) ||
      (visibleText.length >= 24 && normalizedFailure.includes(visibleText))
    );
  });
}

type StructuredFailure = {
  code?: string;
  detail: string;
  eventId?: string;
};

function asFailureRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : null;
}

export function structuredFailureFromMessages(
  messages: Message[],
): StructuredFailure | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.type !== "ai") continue;
    const error = asFailureRecord(message.additional_kwargs?.error);
    if (!error) continue;
    const info = asFailureRecord(error.info);
    const detail =
      typeof error.message === "string" && error.message.trim()
        ? error.message.trim()
        : "turn failed";
    return {
      detail,
      eventId: message.id,
      ...(typeof info?.code === "string" && info.code.trim()
        ? { code: info.code.trim() }
        : {}),
    };
  }
  return null;
}

function latestTurnMessages(messages: Message[]): Message[] {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.type === "human") return messages.slice(index);
  }
  return messages;
}

function failureKind(
  detail: string,
  code?: string,
): FailurePresentation["kind"] {
  const signal = `${code ?? ""}\n${detail}`;
  if (
    /network|fetch|abort|timeout|ECONNREFUSED|websocket|transport|connection/i.test(
      signal,
    )
  ) {
    return "network";
  }
  if (
    /verification_required|verification_failed|verification required|no verification step|Code changes were produced/i.test(
      signal,
    )
  ) {
    return "verification";
  }
  return "error";
}

/**
 * Memoized wrapper around a single message group. Only the group that
 * contains the currently-streaming message (or the latest group while
 * loading) will re-render on every token chunk; all completed groups
 * are frozen by React.memo and skip reconciliation entirely.
 */
const MemoizedGroup = memo(
  function MemoizedGroup({
    group,
    index,
    groupKey,
    isLatestGroup: _isLatestGroup,
    groupHasStreamingMessage: _groupHasStreamingMessage,
    keepGroupOpen,
    enableClarificationActions,
    deferGroupOutputs,
    groupAuditNotice,
    groupFailure,
    showAssistantAvatar,
    renderGroupContent,
  }: {
    group: CoreMessageGroup;
    index: number;
    groupKey: string;
    isLatestGroup: boolean;
    groupHasStreamingMessage: boolean;
    keepGroupOpen: boolean;
    enableClarificationActions: boolean;
    deferGroupOutputs: boolean;
    groupAuditNotice: string | null;
    groupFailure?: FailurePresentation | null;
    showAssistantAvatar: boolean;
    renderGroupContent: (
      group: CoreMessageGroup,
      beforeAssistantContent?: ReactNode,
      enableClarificationActions?: boolean,
      keepOpen?: boolean,
      deferOutputs?: boolean,
      auditNotice?: string | null,
      failure?: FailurePresentation | null,
      showAssistantAvatar?: boolean,
    ) => ReactNode;
  }) {
    return (
      <div
        data-turn-key={group.type === "human" ? groupKey : undefined}
        className={cn(
          index === 0 ? "pt-1" : undefined,
          group.type === "human" ? "scroll-mt-6" : undefined,
          !showAssistantAvatar &&
            (group.type === "assistant" ||
              group.type === "assistant:processing") &&
            "-mt-2",
        )}
      >
        {renderGroupContent(
          group,
          undefined,
          enableClarificationActions,
          keepGroupOpen,
          deferGroupOutputs,
          groupAuditNotice,
          groupFailure,
          showAssistantAvatar,
        )}
      </div>
    );
  },
  (prev, next) =>
    // Only re-render if the group content changed or it is the active
    // streaming group. For non-streaming groups, shallow-equal the stable props.
    prev.groupKey === next.groupKey &&
    sameGroupContent(prev.group, next.group) &&
    prev.isLatestGroup === next.isLatestGroup &&
    prev.groupHasStreamingMessage === next.groupHasStreamingMessage &&
    prev.keepGroupOpen === next.keepGroupOpen &&
    prev.enableClarificationActions === next.enableClarificationActions &&
    prev.deferGroupOutputs === next.deferGroupOutputs &&
    prev.groupAuditNotice === next.groupAuditNotice &&
    prev.groupFailure === next.groupFailure &&
    prev.showAssistantAvatar === next.showAssistantAvatar,
);

/**
 * Unified chat message list.
 *
 * Previous versions virtualized individual rows via ``@tanstack/react-virtual``
 * to save render cost on long conversations. The approach interacted badly
 * with streaming: each token chunk grows the currently-streaming group by a
 * few lines, and the virtualizer's ResizeObserver measures async, so rows
 * below sat at stale ``translateY`` offsets for a frame or two. Visually,
 * text would overlap and the scroll bar would jitter.
 *
 * Turns now stay in normal document flow. Stable historical turns opt into
 * CSS ``content-visibility:auto`` while the latest turn is always fully
 * rendered. This skips off-screen layout and paint without a measurement loop,
 * translated rows, or any chance of hiding the active streaming response.
 */

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  header,
  footer,
  lastTurnToolEvents,
  liveToolEvents,
  currentAgent,
  agentRoster = EMPTY_AGENT_ROSTER,
  completedAgentOutput = false,
  showSenderName = false,
  mode,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  /** Active chat mode. Used to keep the work-log (tool steps) expanded in
   *  code mode so the thread reads like an IDE, not a chat. */
  mode?: string;
  /** Label each agent message with its name (group-chat / team room). */
  showSenderName?: boolean;
  /** Rendered above the first message — e.g. a "load older turns"
   * banner when the thread resumed with a paginated window. */
  header?: ReactNode;
  footer?: ReactNode;
  lastTurnToolEvents?: LiveToolEvent[];
  liveToolEvents?: LiveToolEvent[];
  completedAgentOutput?: boolean;
  currentAgent?: {
    name: string;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
  } | null;
  agentRoster?: MessageListAgentRosterEntry[];
}) {
  const { t } = useI18n();
  const [settings] = useLocalSettings();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const loadingProgressAtRef = useRef<number | null>(null);
  const [loadingAgeMs, setLoadingAgeMs] = useState(0);
  const threadAgentRoster = Array.isArray(thread.values?.agent_roster)
    ? (thread.values.agent_roster as MessageListAgentRosterEntry[])
    : EMPTY_AGENT_ROSTER;
  // Kept for compatibility. Other code branches used to gate behavior
  // on this. The per-message header now renders unconditionally when
  // the AI message carries agent metadata, so this flag is informational
  // only.
  const _isGroupChat = threadAgentRoster.length + agentRoster.length > 0;
  void _isGroupChat;

  const combinedAgentRoster = useMemo(
    () => [...threadAgentRoster, ...agentRoster],
    [agentRoster, threadAgentRoster],
  );
  // O(1) lookup by agent id, backend name, or display name.
  const agentRosterMap = useMemo(
    () => buildAgentRosterMap(combinedAgentRoster),
    [combinedAgentRoster],
  );
  const soleRosterEntry =
    combinedAgentRoster.length === 1 ? combinedAgentRoster[0] : undefined;

  const messages = thread.messages;

  // Structural fingerprint: changes when the message list topology changes
  // (new messages, new/removed tool events). Used to gate scroll-listener
  // rebuilds — avoids re-attaching listeners on every streaming token.
  const structuralFingerprint = useMemo(() => {
    const liveEvents = [
      ...(liveToolEvents ?? []),
      ...(lastTurnToolEvents ?? []),
    ]
      .map((event) =>
        [event.id, event.name, event.status, event.finishedAt ?? ""].join(":"),
      )
      .join("|");
    return [
      thread.isLoading ? "loading" : "idle",
      thread.streamingMessage?.id ?? "",
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

  // Content fingerprint: includes the tail of the streaming text so the
  // loading-age timer resets when new content arrives.
  const contentFingerprint = useMemo(() => {
    return [
      structuralFingerprint,
      streamingMessageProgressKey(thread.streamingMessage),
    ].join("::");
  }, [structuralFingerprint, thread.streamingMessage]);
  const hasStreamingAnswer = Boolean(
    thread.streamingMessage &&
    extractContentFromMessage(thread.streamingMessage).trim(),
  );
  const streamVitals = (
    thread as BaseStream<AgentThreadState> & { vitals?: StreamVitals }
  ).vitals;

  // A content delta is progress, so move the silence watermark without
  // restarting the per-turn timer. The previous combined effect tore down
  // and recreated an interval on every token, adding avoidable effect/timer
  // churn to the hottest rendering path.
  useEffect(() => {
    if (!thread.isLoading) return;
    loadingProgressAtRef.current = Date.now();
    setLoadingAgeMs((age) => (age === 0 ? age : 0));
  }, [thread.isLoading, contentFingerprint]);

  useEffect(() => {
    if (!thread.isLoading) {
      loadingProgressAtRef.current = null;
      setLoadingAgeMs(0);
      return;
    }
    loadingProgressAtRef.current ??= Date.now();
    const timer = window.setInterval(() => {
      const progressAt = loadingProgressAtRef.current ?? Date.now();
      setLoadingAgeMs(Date.now() - progressAt);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [thread.isLoading]);

  // Suppress the warning when at least one tool call is still in-progress
  // (e.g. the agent is writing a large file and producing no streaming text;
  // the tool event stays "in_progress" until completion, which is visible
  // in the live-tool timeline even if the text stream is silent).
  const hasActiveTool = (liveToolEvents ?? []).some(
    (e) => e.status === "running" || e.status === "waiting_approval",
  );
  const turnLocatorRunState = useMemo<TurnLocatorRunState>(() => {
    const events = [...(liveToolEvents ?? []), ...(lastTurnToolEvents ?? [])];
    if (completedAgentOutput && !thread.isLoading) return "done";
    if (thread.error && !thread.isLoading) return "error";
    if (events.some((event) => event.status === "waiting_approval")) {
      return "waiting";
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
    completedAgentOutput,
    thread.error,
    thread.isLoading,
    thread.streamingMessage,
  ]);
  const showTimeoutWarning =
    thread.isLoading &&
    loadingAgeMs >= MESSAGE_LIST_TIMEOUT_WARNING_MS &&
    !hasActiveTool;
  // The realtime hook wraps send failures in Error now, but other BaseStream
  // implementations may still surface raw strings — keep accepting both
  // shapes when extracting the message text.
  const rawThreadError = thread.error as Error | string | undefined;
  const threadErrorMessage =
    typeof rawThreadError === "string"
      ? rawThreadError
      : (rawThreadError?.message ?? "");
  const latestStructuredFailure = useMemo(
    () => structuredFailureFromMessages(latestTurnMessages(messages)),
    [messages],
  );
  const presentFailure = useCallback(
    (failure: StructuredFailure): FailurePresentation => {
      const kind = failureKind(failure.detail, failure.code);
      const message =
        kind === "network"
          ? t.streaming.networkLost
          : kind === "verification"
            ? t.streaming.verificationRequired
            : t.streaming.turnFailed;
      return { ...failure, kind, message };
    },
    [
      t.streaming.networkLost,
      t.streaming.turnFailed,
      t.streaming.verificationRequired,
    ],
  );
  const failureReceipt = useMemo<FailurePresentation | null>(() => {
    if (!thread.error || thread.isLoading) return null;
    return presentFailure(
      latestStructuredFailure ?? {
        detail: threadErrorMessage.trim() || "turn failed",
      },
    );
  }, [
    latestStructuredFailure,
    presentFailure,
    thread.error,
    thread.isLoading,
    threadErrorMessage,
  ]);
  const isNetworkError = failureReceipt?.kind === "network";
  const isVerificationRequiredError = failureReceipt?.kind === "verification";
  const errorBannerText = failureReceipt?.message ?? null;
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
  const messageTurns = useMemo(
    () => partitionMessageGroupsIntoTurns(groupedMessages),
    [groupedMessages],
  );
  // Must mirror the exact mount predicate of `groupFailure` below (latest
  // group is a plain assistant group and the thread is idle). Anything looser
  // suppresses the fallback banner while the receipt has no group to mount
  // on, leaving the error text with no visible rendering at all.
  const failureReceiptAttachedToGroup = useMemo(() => {
    if (!failureReceipt || thread.isLoading) return false;
    const latestGroup = groupedMessages[groupedMessages.length - 1];
    if (!latestGroup || latestGroup.type !== "assistant") return false;
    const turnMessages = turnMessagesForGroup(groupedMessages, latestGroup);
    return (
      !hasVisibleAssistantText(latestGroup) ||
      hasMessageOutputSummary(turnMessages)
    );
  }, [failureReceipt, groupedMessages, thread.isLoading]);
  const failureAlreadyVisibleInAssistantText = useMemo(() => {
    if (!failureReceipt?.detail || thread.isLoading) return false;
    const latestGroup = groupedMessages[groupedMessages.length - 1];
    return latestGroup?.type === "assistant"
      ? assistantGroupContainsFailureMessage(latestGroup, failureReceipt.detail)
      : false;
  }, [failureReceipt, groupedMessages, thread.isLoading]);
  // Mirror the receipt mount rule: the audit actions attach to the last
  // plain assistant group of the latest turn, and receipt content is judged
  // on the whole turn slice — file changes usually live in the processing
  // group's messages, never in the plain assistant group's own.
  const auditNoticeGroupKey = useMemo(() => {
    if (!verificationAuditNotice) return null;
    for (let index = groupedMessages.length - 1; index >= 0; index -= 1) {
      const group = groupedMessages[index]!;
      if (group.type === "human") break;
      if (group.type !== "assistant") continue;
      return hasMessageOutputSummary(
        turnMessagesForGroup(groupedMessages, group),
      )
        ? `${group.type}:${group.id ?? `idx-${index}`}`
        : null;
    }
    return null;
  }, [groupedMessages, verificationAuditNotice]);
  const latestHumanGroupIndex = useMemo(() => {
    for (let index = groupedMessages.length - 1; index >= 0; index -= 1) {
      if (groupedMessages[index]?.type === "human") return index;
    }
    return -1;
  }, [groupedMessages]);
  // "Completed changes" badge on the failure banner: count only files
  // delivered in the failed turn, not the whole thread history.
  const failedCompletedFileCount = useMemo(() => {
    if (!thread.error || thread.isLoading) return 0;
    const turnGroups =
      latestHumanGroupIndex >= 0
        ? groupedMessages.slice(latestHumanGroupIndex)
        : groupedMessages;
    let count = 0;
    for (const group of turnGroups) {
      for (const msg of group.messages) {
        if (hasPresentFiles(msg)) {
          const files = extractPresentFilesFromMessage(msg);
          count += Array.isArray(files) ? files.length : 0;
        }
      }
    }
    return count;
  }, [groupedMessages, latestHumanGroupIndex, thread.error, thread.isLoading]);
  const groupRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const resolveAgentIdentity = useCallback(
    (msg?: (typeof messages)[number]): AgentIdentity => {
      const aiMsg = msg?.type === "ai" ? (msg as AIMessage) : undefined;
      const explicitDisplayName = cleanIdentityText(
        aiMsg?.additional_kwargs?.agent_display_name,
      );
      const explicitAgentId =
        cleanIdentityText(aiMsg?.additional_kwargs?.agent_id) ??
        cleanIdentityText(aiMsg?.additional_kwargs?.agent_name) ??
        cleanIdentityText(aiMsg?.additional_kwargs?.agent);
      const threadAgentId =
        cleanIdentityText(thread.values?.["agent_name"]) ??
        cleanIdentityText(thread.values?.["agent_id"]) ??
        cleanIdentityText(thread.values?.["lead_agent_name"]);
      const threadDisplayName =
        cleanIdentityText(thread.values?.["team_leader"]) ??
        cleanIdentityText(thread.values?.["lead_agent_name"]);
      const rosterMatch =
        findRosterEntry(
          agentRosterMap,
          explicitAgentId,
          explicitDisplayName,
          currentAgent?.name,
          currentAgent?.display_name,
          threadAgentId,
          threadDisplayName,
        ) ?? soleRosterEntry;
      const rosterAgentId = agentIdForRosterEntry(rosterMatch);
      const name =
        explicitDisplayName ??
        displayNameForRosterEntry(rosterMatch) ??
        currentAgent?.display_name ??
        currentAgent?.name ??
        threadDisplayName;
      const avatar =
        cleanIdentityText(aiMsg?.additional_kwargs?.agent_avatar_url) ??
        cleanIdentityText(rosterMatch?.avatar_url) ??
        cleanIdentityText(currentAgent?.avatar_url) ??
        fallbackAgentAvatarUrl(
          rosterAgentId ?? currentAgent?.name ?? explicitAgentId,
        );
      const icon =
        cleanIdentityText(aiMsg?.additional_kwargs?.agent_icon) ??
        cleanIdentityText(rosterMatch?.icon) ??
        cleanIdentityText(currentAgent?.icon);
      const role = cleanIdentityText(rosterMatch?.role);

      return {
        avatar,
        icon,
        id: rosterAgentId ?? currentAgent?.name ?? explicitAgentId,
        name,
        role,
      };
    },
    [
      agentRosterMap,
      currentAgent?.avatar_url,
      currentAgent?.display_name,
      currentAgent?.icon,
      currentAgent?.name,
      soleRosterEntry,
      thread.values,
    ],
  );
  // Recomputed on every streamed frame (groupedMessages is rebuilt each
  // flush), but the scroll-spy effect and the locator rail key off array
  // identity — return the previous array whenever the content is unchanged
  // so listeners are not torn down and re-attached per frame.
  const turnMarkersRef = useRef<TurnMarker[]>([]);
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
      const rawLabel = firstMessage
        ? extractTextFromMessage(firstMessage).replace(/\s+/g, " ").trim()
        : "";
      markers.push({
        key: `${group.type}:${group.id ?? `idx-${index}`}`,
        kind: turnMarkerKindFromMessages(turnMessages),
        label: rawLabel || t.message.turnLabel(markers.length + 1),
        number: markers.length + 1,
      });
    }
    const previous = turnMarkersRef.current;
    if (
      previous.length === markers.length &&
      markers.every((marker, index) => sameTurnMarker(previous[index]!, marker))
    ) {
      return previous;
    }
    turnMarkersRef.current = markers;
    return markers;
  }, [groupedMessages, t.message]);
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
      const rects: Record<string, Pick<DOMRect, "bottom" | "top"> | undefined> =
        {};
      for (const marker of turnMarkers) {
        rects[marker.key] =
          groupRefs.current[marker.key]?.getBoundingClientRect();
      }
      const nextKey = nearestTurnKeyByViewportCenter(
        turnMarkers,
        rects,
        rootRect.top,
        rootRect.height,
      );
      if (nextKey) {
        setActiveTurnKey((current) =>
          current === nextKey ? current : nextKey,
        );
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
  }, [structuralFingerprint, turnMarkers]);

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
            // No `progress` here: this reduction replays on every message
            // change and updateSubtask merges shallowly, so a hardcoded 0
            // would clobber any real progress written by a live source.
            updates.push({
              id: toolCall.id,
              subagent_type: toolCall.args.subagent_type as string,
              description: toolCall.args.description as string,
              prompt: toolCall.args.prompt as string,
              status: "in_progress",
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

  const renderAssistantFrame = ({
    key,
    agentName,
    agentAvatar,
    agentIcon,
    agentRole,
    children,
  }: {
    key: string;
    agentName?: string;
    agentAvatar?: string;
    agentIcon?: string | null;
    agentRole?: string;
    children: ReactNode;
  }) => {
    const displayName = agentName || t.message.assistant;
    // In a team room, label each agent's message with its name (and 队长
    // badge) so the thread reads like a group chat — you can see who's
    // speaking, not just an anonymous avatar.
    const isTeam = showSenderName;
    return (
      <div key={key} className="flex w-full items-start gap-3">
        <AgentAvatar
          agentDisplayName={displayName}
          avatarUrl={
            agentAvatar ? withAgentAvatarVersion(agentAvatar) : agentAvatar
          }
          icon={agentIcon}
          className="mt-1 size-8 rounded-md"
        />
        <div className="min-w-0 flex-1">
          {isTeam && agentName && (
            <div className="mb-0.5 flex items-center gap-1.5">
              <span className="text-sm font-semibold text-foreground">
                {displayName}
              </span>
              {agentRole === "tl" && (
                <span className="rounded-md border border-emerald-500/50 bg-emerald-500/10 px-1.5 py-0 text-[10px] leading-4 font-medium text-emerald-600 dark:text-emerald-400">
                  队长
                </span>
              )}
            </div>
          )}
          {children}
        </div>
      </div>
    );
  };

  const renderMessageContent = (
    msg: (typeof messages)[number],
    keyPrefix: string | undefined,
    beforeContent?: ReactNode,
  ) => {
    const key = `${keyPrefix}/${msg.id}`;
    return (
      <div key={key}>
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
    const { name, avatar, icon, role } = resolveAgentIdentity(msg);
    return renderAssistantFrame({
      key,
      agentName: name,
      agentAvatar: avatar,
      agentIcon: icon,
      agentRole: role,
      children: content,
    });
  };

  const renderGroupHeader = (
    group: (typeof groupedMessages)[number],
    enableClarificationActions = false,
    keepOpen = false,
    showAssistantAvatar = true,
  ) => {
    if (!hasVisibleMessageGroupContent(group.messages, t)) return null;
    const aiMessage = group.messages.find(
      (message): message is AIMessage => message.type === "ai",
    );
    const {
      name: agentName,
      avatar: agentAvatar,
      icon: agentIcon,
      role: agentRole,
    } = resolveAgentIdentity(aiMessage);
    const content = (
      <MessageGroup
        enableClarificationActions={enableClarificationActions}
        messages={group.messages}
        keepOpen={keepOpen}
        codeMode={mode === "code"}
        isLoading={
          keepOpen ||
          (thread.isLoading &&
            group.messages.some(
              (message) => message.id === thread.streamingMessage?.id,
            ))
        }
      />
    );
    if (!showAssistantAvatar) {
      return <div className="ml-11 w-auto">{content}</div>;
    }
    if (!agentName) return content;
    return renderAssistantFrame({
      key: `agent-frame/${group.id ?? agentName}`,
      agentName,
      agentAvatar,
      agentIcon,
      agentRole,
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
    failure: FailurePresentation | null = null,
    showAssistantAvatar = true,
  ) => {
    if (group.type === "human" || group.type === "assistant") {
      let injectedBeforeContent = false;
      const renderedMessages = group.messages.map((msg) => {
        const beforeContent =
          beforeAssistantContent && msg.type === "ai" && !injectedBeforeContent
            ? beforeAssistantContent
            : undefined;
        if (beforeContent) injectedBeforeContent = true;
        return showAssistantAvatar || msg.type !== "ai"
          ? renderMessageWithHeader(msg, group.id, beforeContent)
          : renderMessageContent(msg, group.id, beforeContent);
      });
      return (
        <>
          {group.type === "assistant" && !showAssistantAvatar ? (
            <div className="ml-11 w-auto">{renderedMessages}</div>
          ) : (
            renderedMessages
          )}
          {group.type === "assistant" && !deferOutputs && (
            <MessageOutputSummary
              auditNotice={auditNotice}
              messages={group.messages}
              turnMessages={
                isLastAssistantGroupOfTurn(groupedMessages, group)
                  ? turnMessagesForGroup(groupedMessages, group)
                  : undefined
              }
              threadId={threadId}
              failure={failure}
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
              codeMode={mode === "code"}
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
    return renderGroupHeader(
      group,
      enableClarificationActions,
      keepOpen,
      showAssistantAvatar,
    );
  };

  const assistantFrameIdentity = (
    group: (typeof groupedMessages)[number],
  ): string | null => {
    if (group.type !== "assistant" && group.type !== "assistant:processing") {
      return null;
    }
    const aiMessage = group.messages.find(
      (message): message is AIMessage => message.type === "ai",
    );
    const identity = resolveAgentIdentity(aiMessage);
    // Avatar URLs and icons are presentation metadata and can arrive a frame
    // later than the stable agent id/name. Including them in the speaker key
    // made one uninterrupted reply grow a second avatar during streaming.
    // Prefer semantic identity and use visual metadata only as a last resort.
    const stableId = identityKey(identity.id);
    if (stableId) return `id:${stableId}`;
    const stableName = identityKey(identity.name);
    if (stableName) return `name:${stableName}`;
    return [identityKey(identity.avatar), identityKey(identity.icon)]
      .filter((value): value is string => Boolean(value))
      .join("|");
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
        className="mx-auto w-full max-w-(--container-width-md) gap-7 px-4 pt-2"
      >
        {header}
        {messageTurns.map((turn, turnIndex) => {
          const isLatestTurn = turnIndex === messageTurns.length - 1;
          const markerKey = turn.key.startsWith("human:") ? turn.key : null;

          return (
            <div
              key={turn.key}
              ref={(node) => {
                if (!markerKey) return;
                if (node) {
                  groupRefs.current[markerKey] = node;
                } else {
                  delete groupRefs.current[markerKey];
                }
              }}
              className={cn(
                "message-turn flex flex-col gap-3",
                !isLatestTurn && "message-turn-history",
              )}
              data-message-turn={turn.key}
              data-turn-rendering={isLatestTurn ? "active" : "history"}
            >
              {turn.groupIndexes.map((index) => {
                const group = groupedMessages[index]!;
                const groupKey = `${group.type}:${group.id ?? `idx-${index}`}`;
                const isLatestGroup = index === groupedMessages.length - 1;
                const groupHasStreamingMessage =
                  thread.streamingMessage != null &&
                  group.messages.some(
                    (message) => message.id === thread.streamingMessage?.id,
                  );
                const keepGroupOpen =
                  groupHasStreamingMessage ||
                  (thread.isLoading && isLatestGroup);
                const enableGroupClarificationActions =
                  !thread.isLoading && isLatestGroup;
                const deferGroupOutputs =
                  thread.isLoading &&
                  latestHumanGroupIndex >= 0 &&
                  index > latestHumanGroupIndex;
                const groupAuditNotice =
                  groupKey === auditNoticeGroupKey
                    ? verificationAuditNotice
                    : null;
                const groupTurnMessages =
                  group.type === "assistant"
                    ? turnMessagesForGroup(groupedMessages, group)
                    : group.messages;
                const structuredGroupFailure =
                  group.type === "assistant" &&
                  isLastAssistantGroupOfTurn(groupedMessages, group)
                    ? structuredFailureFromMessages(groupTurnMessages)
                    : null;
                const historicalGroupFailure = structuredGroupFailure
                  ? presentFailure(structuredGroupFailure)
                  : null;
                const shouldShowFailureReceipt =
                  Boolean(failureReceipt) &&
                  isLatestGroup &&
                  group.type === "assistant" &&
                  !thread.isLoading &&
                  (!hasVisibleAssistantText(group) ||
                    hasMessageOutputSummary(groupTurnMessages));
                const groupFailure =
                  historicalGroupFailure ??
                  (failureReceipt && shouldShowFailureReceipt
                    ? failureReceipt
                    : null);

                const turnGroupPosition = turn.groupIndexes.indexOf(index);
                const assistantIdentity = assistantFrameIdentity(group);
                const previousAssistantIdentity = [...turn.groupIndexes]
                  .slice(0, turnGroupPosition)
                  .reverse()
                  .map((groupIndex) =>
                    assistantFrameIdentity(groupedMessages[groupIndex]!),
                  )
                  .find((identity): identity is string => identity !== null);
                const showAssistantAvatar =
                  assistantIdentity === null ||
                  previousAssistantIdentity === undefined ||
                  previousAssistantIdentity !== assistantIdentity;

                return (
                  <Fragment key={groupKey}>
                    <MemoizedGroup
                      group={group}
                      index={index}
                      groupKey={groupKey}
                      isLatestGroup={isLatestGroup}
                      groupHasStreamingMessage={groupHasStreamingMessage}
                      keepGroupOpen={keepGroupOpen}
                      enableClarificationActions={
                        enableGroupClarificationActions
                      }
                      deferGroupOutputs={deferGroupOutputs}
                      groupFailure={groupFailure}
                      groupAuditNotice={groupAuditNotice}
                      renderGroupContent={renderGroupContent}
                      showAssistantAvatar={showAssistantAvatar}
                    />
                  </Fragment>
                );
              })}
              {isLatestTurn && (
                <PublicThinkingStatus
                  isLoading={thread.isLoading}
                  liveToolEvents={liveToolEvents ?? []}
                  hasStreamingMessage={hasStreamingAnswer}
                  vitals={streamVitals}
                />
              )}
            </div>
          );
        })}

        {footer}

        {errorBannerText &&
          !failureReceiptAttachedToGroup &&
          !failureAlreadyVisibleInAssistantText &&
          !(verificationAuditNotice && auditNoticeGroupKey) && (
            <div
              role="alert"
              className={cn(
                "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-[var(--shadow-xs)]",
                isNetworkError
                  ? "border-amber-200/70 bg-amber-50/90 text-amber-900 dark:border-amber-800/50 dark:bg-amber-950/75 dark:text-amber-100"
                  : "border-destructive/25 bg-destructive/8 text-destructive dark:border-destructive/35 dark:bg-destructive/12",
              )}
            >
              {isNetworkError ? (
                <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-300" />
              ) : (
                <XCircleIcon className="mt-0.5 size-4 shrink-0" />
              )}
              <div className="min-w-0 flex-1 leading-6">
                <div className="mb-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
                  <span>
                    {isNetworkError
                      ? t.streaming.networkLost
                      : t.message.taskFailed}
                  </span>
                  {!isNetworkError && failedCompletedFileCount > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-0.5 text-[11px] font-normal text-foreground/70">
                      {t.message.completedChanges} · {failedCompletedFileCount}
                    </span>
                  )}
                </div>
                {!isNetworkError && (
                  <div className="text-[13px] opacity-80">
                    {errorBannerText}
                  </div>
                )}
                {isNetworkError && <span>{errorBannerText}</span>}
                {!isNetworkError && (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (!failureReceipt) {
                          emitOpenAgentWorkbench({ tab: "agent" });
                          return;
                        }
                        emitOpenAgentWorkbench({
                          tab: "agent",
                          eventId: failureReceipt.eventId,
                          eventKind: "execution",
                          view: "trace",
                          processEvent: {
                            kind: "execution",
                            summary: failureReceipt.message,
                            detail: failureReceipt.detail,
                            status: "error",
                            count: 1,
                          },
                        });
                      }}
                      className="inline-flex h-7 items-center gap-1 rounded-md border border-border-default bg-background/60 px-2.5 text-[11px] font-medium text-foreground/80 transition-colors hover:bg-background/90"
                    >
                      <PlayCircleIcon className="size-3" />
                      {t.message.viewProcess}
                    </button>
                  </div>
                )}
              </div>
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
        activityKey={contentFingerprint}
        activityLabel={t.message.newUpdates}
        aria-label={t.message.backToLatest}
        title={t.message.backToLatest}
        style={{ bottom: `${Math.max(12, paddingBottom + 12)}px` }}
      >
        {t.message.latest}
      </ConversationScrollButton>

      {showTimeoutWarning && !thread.error && (
        <div className="absolute top-4 left-[50%] z-10 -translate-x-1/2 flex items-center gap-3 rounded-lg border border-amber-300/70 bg-amber-50/95 px-4 py-2 text-xs text-amber-900 shadow-[var(--shadow-xs)] dark:border-amber-700/50 dark:bg-amber-950/90 dark:text-amber-200">
          <AlertTriangleIcon className="size-4 shrink-0 text-amber-600" />
          <span>
            {t.message.timeoutWarning(Math.floor(loadingAgeMs / 1000))}
          </span>
          <button
            type="button"
            onClick={() => void thread.stop()}
            className="rounded-md border border-amber-300/80 px-2 py-1 text-[11px] font-medium text-amber-900 transition-colors hover:bg-amber-100 dark:border-amber-700/60 dark:text-amber-200 dark:hover:bg-amber-900/70"
          >
            {t.common.stop}
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
  const { t } = useI18n();
  if (markers.length <= 1) return null;
  const visibleMarkers = visibleTurnMarkerWindow(markers, activeKey);
  const firstMarker = markers[0]!;
  const lastMarker = markers[markers.length - 1]!;

  return (
    <nav
      aria-label={t.message.turnLocator}
      className="group/turn-rail absolute top-1/2 left-0 z-20 hidden -translate-y-1/2 md:block"
    >
      <div className="relative flex max-h-[82vh] flex-col items-center gap-1 overflow-hidden px-1 py-1.5">
        <TurnLocatorLimitButton
          active={visibleMarkers[0]?.key === firstMarker.key}
          direction="up"
          label={t.message.jumpToFirstTurn}
          onClick={() => onSelect(firstMarker.key)}
        />
        {visibleMarkers.map((marker) => {
          const active = marker.key === activeKey;
          const phaseMarker =
            marker.kind === "phase" ? `（${t.message.phaseTask}）` : "";
          const label = t.message.turnNumberLabel(
            marker.number,
            `${phaseMarker}${marker.label}`,
          );
          return (
            <button
              key={marker.key}
              aria-current={active ? "step" : undefined}
              aria-label={label}
              data-turn-marker-active={active ? "true" : undefined}
              data-turn-marker-kind={marker.kind}
              className={cn(
                "group relative flex w-6 items-center justify-center rounded-full transition-all duration-150",
                "focus-visible:ring-ring/50 outline-none focus-visible:ring-2",
                active
                  ? "opacity-100"
                  : "opacity-0 hover:bg-muted/45 hover:opacity-100 focus-visible:opacity-100 group-hover/turn-rail:opacity-70",
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
                    ? cn(
                        "h-8 w-2",
                        active
                          ? "bg-muted-foreground/50"
                          : "bg-muted-foreground/25 group-hover:bg-muted-foreground/40",
                      )
                    : cn(
                        "size-2.5",
                        active
                          ? "bg-muted-foreground/55"
                          : "bg-muted-foreground/30 group-hover:bg-muted-foreground/45",
                      ),
                )}
              />
              {active &&
                marker.key === lastMarker.key &&
                runState !== "done" && (
                  <TurnMarkerStatusLight runState={runState} />
                )}
            </button>
          );
        })}
        <TurnLocatorLimitButton
          active={
            visibleMarkers[visibleMarkers.length - 1]?.key === lastMarker.key
          }
          direction="down"
          label={t.message.jumpToLastTurn}
          onClick={() => onSelect(lastMarker.key)}
        />
      </div>
    </nav>
  );
}

function TurnMarkerStatusLight({
  runState,
}: {
  runState: Exclude<TurnLocatorRunState, "done">;
}) {
  const pulseClassName = agentRunStatusLightPulseClass(runState);
  const color = agentRunStatusLightClass(runState);
  return (
    <span
      aria-hidden="true"
      className={cn(
        "absolute right-0 bottom-0 size-1.5 rounded-full border border-background",
        color,
      )}
      data-turn-marker-status={runState}
    >
      {pulseClassName && (
        <span
          className={cn(
            "absolute inset-0 rounded-full opacity-70",
            color,
            pulseClassName,
          )}
        />
      )}
    </span>
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
      <Icon aria-hidden="true" className="size-4" />
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
