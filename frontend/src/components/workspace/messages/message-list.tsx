import type { AIMessage, Message, ToolMessage } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { ReactNode } from "react";
import {
  AlertTriangleIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  XCircleIcon,
  UsersIcon,
} from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
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
  hasToolCalls,
  isSettledAssistantAnswer,
  type MessageGroup as CoreMessageGroup,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { StreamVitals } from "@/core/realtime/stream-vitals";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask, useSubtaskContext } from "@/core/tasks/context";
import { isSubtaskActive } from "@/core/tasks/types";
import type { AgentThreadState } from "@/core/threads";
import {
  findTimelineItemElement,
  getTimelineLinkageState,
  subscribeTimelineLinkage,
  TIMELINE_ITEM_HIGHLIGHT_CLASS,
} from "@/core/threads/timeline-linkage";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import {
  AGENT_WORKBENCH_LOCATE_EVENT,
  type AgentWorkbenchLocateDetail,
} from "../agent-workbench-events";
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
import { FollowUpSuggestions } from "./follow-up-suggestions";

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

function cssEscape(value: string): string {
  const escape = globalThis.CSS?.escape;
  if (typeof escape === "function") return escape(value);
  return value.replace(/["\\]/g, "\\$&");
}

export interface MessageTurnSlice {
  /** Indexes into the grouped-message array, kept contiguous and ordered. */
  groupIndexes: number[];
  /** Human group key when present; leading system content uses a prelude key. */
  key: string;
}

/** Per-group render inputs derived once per turn instead of per group. */
interface GroupTurnRenderInfo {
  /** Deduped message slice of the whole turn (matches turnMessagesForGroup). */
  turnMessages: Message[];
  /** True when this is the terminal plain assistant group for the turn. */
  isLastAssistantOfTurn: boolean;
  /** assistantFrameIdentity of this group (null for non-assistant types). */
  assistantIdentity: string | null;
  /** Assistant-ish groups (assistant / assistant:processing) before this one. */
  previousAssistantGroupCount: number;
  /** Nearest previous assistant-ish group's non-null identity, if any. */
  previousAssistantIdentity: string | undefined;
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

export function turnMarkerKindFromMessages(
  messages: Message[],
): "dot" | "phase" {
  for (const message of messages) {
    if (message.type !== "ai") continue;
    const aiMessage = message as AIMessage;
    const additional = aiMessage.additional_kwargs;
    if (
      typeof additional?.phase_id === "string" &&
      additional.phase_id.trim()
    ) {
      return "phase";
    }
    if (additional?.thinking_plan) return "phase";
    if (Array.isArray(additional?.phases) && additional.phases.length > 0) {
      return "phase";
    }
    const workbenchSnapshot = additional?.workbenchSnapshot;
    if (
      workbenchSnapshot &&
      typeof workbenchSnapshot === "object" &&
      Array.isArray((workbenchSnapshot as { phases?: unknown }).phases) &&
      ((workbenchSnapshot as { phases: unknown[] }).phases.length ?? 0) > 0
    ) {
      return "phase";
    }
    for (const toolCall of aiMessage.tool_calls ?? []) {
      if (typeof toolCall.phaseId === "string" && toolCall.phaseId.trim()) {
        return "phase";
      }
    }
  }
  return "dot";
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

// A turn can contain several plain assistant groups, with more processing
// appended after an intermediate answer/checkpoint. Only an assistant group
// with no later assistant or processing activity may host the final receipt.
// This keeps in-progress file writes on the execution timeline and prevents a
// completed-change card from appearing in the middle of a still-running turn.
function isLastAssistantGroupOfTurn(
  groupedMessages: CoreMessageGroup[],
  group: CoreMessageGroup,
): boolean {
  const index = groupedMessages.indexOf(group);
  if (index === -1) return true;
  for (let i = index + 1; i < groupedMessages.length; i++) {
    const later = groupedMessages[i]!;
    if (later.type === "human") break;
    if (
      later.type === "assistant" ||
      later.type === "assistant:processing" ||
      later.type === "assistant:clarification" ||
      later.type === "assistant:subagent"
    ) {
      return false;
    }
  }
  return true;
}

function hasLaterProcessActivity(
  turnMessages: Message[],
  group: CoreMessageGroup,
): boolean {
  const hostMessage = [...group.messages]
    .reverse()
    .find((message) => message.type === "ai");
  if (!hostMessage) return false;
  const hostIndex = turnMessages.indexOf(hostMessage);
  if (hostIndex < 0) return false;
  return turnMessages
    .slice(hostIndex + 1)
    .some(
      (message) =>
        message.type === "ai" &&
        (message.additional_kwargs?.public_progress === true ||
          hasToolCalls(message) ||
          hasReasoning(message)),
    );
}

// A clarification card should only auto-answer (its 20s countdown) while it
// is the newest group in the conversation. Once the user moves on, stale
// cards must stay inert — otherwise every idle moment re-arms every old
// card and fires its default choice as a spurious user turn.
export function isLatestMessageGroup(
  groupedMessages: CoreMessageGroup[],
  group: CoreMessageGroup,
): boolean {
  return groupedMessages[groupedMessages.length - 1] === group;
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
  /** Backend turn disposition: "failed" | "blocked_on_user" (see react_terminal). */
  disposition?: string;
  /** Backend failure classification kind: "environment" | "git_hook" | "". */
  failure_kind?: string;
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
    const disposition =
      typeof info?.disposition === "string" && info.disposition.trim()
        ? info.disposition.trim()
        : "";
    const failureKind =
      typeof info?.failure_kind === "string" && info.failure_kind.trim()
        ? info.failure_kind.trim()
        : "";
    return {
      detail,
      eventId: message.id,
      ...(typeof info?.code === "string" && info.code.trim()
        ? { code: info.code.trim() }
        : {}),
      ...(disposition ? { disposition } : {}),
      ...(failureKind ? { failure_kind: failureKind } : {}),
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

export function failureKind(
  detail: string,
  code?: string,
  disposition?: string,
  failureKindHint?: string,
): FailurePresentation["kind"] {
  const signal = `${code ?? ""}\n${detail}`;
  const normalized = signal.toLowerCase();
  // A genuine "needs your input" hand-off is never a failure — amber/waiting.
  if (disposition === "blocked_on_user") {
    return "blocked";
  }
  // Backend environment classification wins over the heuristic below so the
  // frontend never re-labels a structured environment block as a network loss.
  if (failureKindHint === "environment") {
    return "environment";
  }
  const isClientClose =
    /client closed/.test(normalized) ||
    /websocket closed \(1000/.test(normalized);
  const isAbort =
    /aborterror/.test(normalized) || /^abort$/i.test(detail.trim());
  if (isClientClose || isAbort) {
    return "error";
  }
  if (
    /network error|fetch failed|econnrefused|timeout|websocket closed \(1006|transport error|connection (refused|reset|lost)/i.test(
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
  if (/guard_impasse|todo-protocol guard|completeness guard/i.test(signal)) {
    return "guard";
  }
  if (
    /missing_terminal_state|unknown_turn_status|runtime returned without a terminal/i.test(
      signal,
    )
  ) {
    return "lifecycle";
  }
  // Unstructured / legacy environment blocks (codes or raw stderr).
  if (
    /pnpm.*no.?tty|aborted removal of modules|permission denied|eacces|command not found|not found:|sandbox.*(?:blocked|denied)/i.test(
      signal,
    )
  ) {
    return "environment";
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
 * Enhanced cluster header section for subagent groups.
 * Shows overall progress, statistics, and controls.
 */
function SubagentClusterSection({
  subagentEvents,
  groupId,
  isLoading,
}: {
  subagentEvents: Array<{ id: string }>;
  groupId: string | undefined;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  const [allCollapsed, setAllCollapsed] = useState(false);
  const { tasks } = useSubtaskContext();

  // Calculate statistics
  const stats = useMemo(() => {
    const result = {
      total: subagentEvents.length,
      completed: 0,
      running: 0,
      pending: 0,
      failed: 0,
    };

    for (const event of subagentEvents) {
      const task = tasks[event.id];
      if (!task) {
        result.pending += 1;
        continue;
      }

      if (task.status === "completed") {
        result.completed += 1;
      } else if (
        task.status === "failed" ||
        task.status === "timed_out" ||
        task.status === "cancelled"
      ) {
        result.failed += 1;
      } else if (isSubtaskActive(task.status)) {
        result.running += 1;
      } else {
        result.pending += 1;
      }
    }

    return result;
  }, [subagentEvents, tasks]);

  const progressPercent =
    stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0;

  return (
    <div className="mt-4 ml-11">
      {/* Enhanced cluster header */}
      <div className="mb-3 flex items-center justify-between rounded-lg border border-border-default bg-muted/20 px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
            <UsersIcon className="size-4 text-primary" />
          </div>
          <div>
            <div className="text-sm font-semibold">
              {t.subagents.parallelExecution}
            </div>
            <div className="text-xs text-muted-foreground">
              {stats.completed}/{stats.total} {t.subagents.completed}
              {stats.running > 0 &&
                ` · ${stats.running} ${t.subagents.running}`}
              {stats.failed > 0 && ` · ${stats.failed} ${t.subagents.failed}`}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Overall progress bar */}
          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted/60">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                stats.running > 0
                  ? "bg-success animate-pulse"
                  : stats.failed > 0 && stats.completed === 0
                    ? "bg-destructive"
                    : "bg-success",
              )}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {progressPercent}%
          </span>
        </div>
      </div>

      {/* Subagent grid or cards */}
      {subagentEvents.length > 1 ? (
        <ParallelSubtasksGrid
          key={"parallel-grid-live-" + (groupId ?? "unknown")}
          taskIds={subagentEvents.map((e) => e.id)}
          isLoading={isLoading}
        />
      ) : (
        subagentEvents.map((event) => (
          <SubtaskCard
            key={"task-live-" + event.id}
            taskId={event.id}
            isLoading={isLoading}
          />
        ))
      )}
    </div>
  );
}

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
  onOpenArtifact,
  lastTurnToolEvents,
  liveToolEvents,
  allToolEvents,
  currentAgent,
  agentRoster = EMPTY_AGENT_ROSTER,
  completedAgentOutput = false,
  showSenderName = false,
  mode,
  project,
  onSendFollowUp,
  onAuthorizeNetwork,
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
  onOpenArtifact?: (path: string) => void;
  lastTurnToolEvents?: LiveToolEvent[];
  liveToolEvents?: LiveToolEvent[];
  allToolEvents?: LiveToolEvent[];
  completedAgentOutput?: boolean;
  currentAgent?: {
    name: string;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
  } | null;
  agentRoster?: MessageListAgentRosterEntry[];
  /** Project path for ambient suggestions */
  project?: string | null;
  /** Callback when user selects a follow-up suggestion */
  onSendFollowUp?: (prompt: string) => void;
  /** Callback when the user authorizes network access from the
   *  environment-blocked banner ("common domains" or "full"). */
  onAuthorizeNetwork?: (tier: "common" | "full") => void;
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

  // 侧边栏 → 对话区联动：共享 linkage store 出现高亮条目时，滚动定位到同一
  // 时间线项并短暂高亮（≤2s）。高亮 class 随 store 的 2s 定时器清除
  // （highlightedTimelineItemId 归零触发本 effect 的清理函数），组件卸载时
  // 也会兜底移除；样式全程仅 CSS transition，无循环动画。两侧共用同一 id，
  // 因此查找时以 "chat" lane 限定只命中对话区行。
  const timelineLinkage = useSyncExternalStore(
    subscribeTimelineLinkage,
    getTimelineLinkageState,
    getTimelineLinkageState,
  );
  useEffect(() => {
    const itemId = timelineLinkage.highlightedTimelineItemId;
    if (!itemId) return;
    let row: HTMLElement | null = null;
    let frame = 0;
    let disposed = false;
    const locate = (): boolean => {
      row = findTimelineItemElement(itemId, "chat");
      if (!row) return false;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add(TIMELINE_ITEM_HIGHLIGHT_CLASS);
      return true;
    };
    // 命中聚合组子项时，MessageGroup 需先在本轮状态更新后渲染子项，首帧
    // 可能定位不到，按帧重试（上限 3 帧 ≈ 50ms，高亮总时长 2s 不受影响）。
    let attempts = 0;
    const retry = () => {
      if (disposed) return;
      if (locate()) return;
      attempts += 1;
      if (attempts < 3) frame = window.requestAnimationFrame(retry);
    };
    if (!locate()) frame = window.requestAnimationFrame(retry);
    return () => {
      disposed = true;
      if (frame) window.cancelAnimationFrame(frame);
      row?.classList.remove(TIMELINE_ITEM_HIGHLIGHT_CLASS);
    };
  }, [timelineLinkage.highlightedTimelineItemId, timelineLinkage.nonce]);

  useEffect(() => {
    const handleLocate = (event: Event) => {
      const detail = (event as CustomEvent<AgentWorkbenchLocateDetail>).detail;
      const eventId =
        typeof detail?.eventId === "string" ? detail.eventId.trim() : "";
      if (!eventId) return;
      const row = document.querySelector<HTMLElement>(
        `[data-process-event-id="${cssEscape(eventId)}"]`,
      );
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.animate(
        [
          { backgroundColor: "transparent", boxShadow: "none" },
          {
            backgroundColor:
              "color-mix(in oklch, var(--primary) 12%, transparent)",
            boxShadow:
              "inset 2px 0 0 color-mix(in oklch, var(--primary) 70%, transparent)",
          },
          { backgroundColor: "transparent", boxShadow: "none" },
        ],
        { duration: 1100, easing: "ease-out" },
      );
    };
    window.addEventListener(AGENT_WORKBENCH_LOCATE_EVENT, handleLocate);
    return () =>
      window.removeEventListener(AGENT_WORKBENCH_LOCATE_EVENT, handleLocate);
  }, []);

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
  const latestTurnHasSettledAnswer = useMemo(
    () =>
      latestTurnMessages(messages).some((message) =>
        isSettledAssistantAnswer(message),
      ),
    [messages],
  );
  const presentFailure = useCallback(
    (failure: StructuredFailure): FailurePresentation => {
      const kind = failureKind(
        failure.detail,
        failure.code,
        failure.disposition,
        failure.failure_kind,
      );
      const requiresWorkspaceWrite =
        /Code mode cannot finish this implementation task yet:\s*no successful file write\/edit execution is recorded/i.test(
          failure.detail,
        );
      const hasStructuredReadableDetail =
        Boolean(failure.code) &&
        failure.detail !== "turn failed" &&
        !/^[a-z][a-z0-9_.-]{1,80}$/i.test(failure.detail);
      // Environment / blocked hand-offs surface the readable reason from the
      // backend (``turn.error.message``) verbatim; the i18n strings are only
      // the fallback when no detail came through.
      const message =
        kind === "blocked"
          ? failure.detail !== "turn failed"
            ? failure.detail
            : t.streaming.blockedOnUser
          : kind === "environment"
            ? failure.detail !== "turn failed"
              ? failure.detail
              : t.streaming.environmentBlocked
            : kind === "network"
              ? t.streaming.networkLost
              : kind === "verification"
                ? t.streaming.verificationRequired
                : kind === "guard"
                  ? hasStructuredReadableDetail
                    ? failure.detail
                    : t.streaming.guardBlocked
                  : kind === "lifecycle"
                    ? t.streaming.lifecycleFailed
                    : requiresWorkspaceWrite
                      ? t.streaming.workspaceWriteRequired
                      : hasStructuredReadableDetail
                        ? failure.detail
                        : t.streaming.turnFailed;
      return { ...failure, kind, message };
    },
    [
      t.streaming.blockedOnUser,
      t.streaming.environmentBlocked,
      t.streaming.networkLost,
      t.streaming.guardBlocked,
      t.streaming.lifecycleFailed,
      t.streaming.turnFailed,
      t.streaming.verificationRequired,
      t.streaming.workspaceWriteRequired,
    ],
  );
  const failureReceipt = useMemo<FailurePresentation | null>(() => {
    if (!thread.error || thread.isLoading) return null;
    // A provider can finish the visible answer and still close its transport
    // with a late/stale error. Do not contradict an already settled answer
    // with a generic "turn failed" banner. Explicit structured failures keep
    // their receipt because they are authoritative protocol state.
    if (
      latestTurnHasSettledAnswer &&
      !latestStructuredFailure &&
      failureKind(threadErrorMessage) === "error"
    ) {
      return null;
    }
    return presentFailure(
      latestStructuredFailure ?? {
        detail: threadErrorMessage.trim() || "turn failed",
      },
    );
  }, [
    latestStructuredFailure,
    latestTurnHasSettledAnswer,
    presentFailure,
    thread.error,
    thread.isLoading,
    threadErrorMessage,
  ]);
  const isNetworkError = failureReceipt?.kind === "network";
  // Environment blocks and "needs your input" hand-offs are not agent
  // failures — render them amber, not destructive red.
  const isWarningFailure =
    isNetworkError ||
    failureReceipt?.kind === "environment" ||
    failureReceipt?.kind === "blocked";
  const failureHeaderText =
    failureReceipt?.kind === "blocked"
      ? t.streaming.blockedOnUser
      : failureReceipt?.kind === "environment"
        ? t.streaming.environmentBlocked
        : isNetworkError
          ? t.streaming.networkLost
          : t.message.taskFailed;
  const isVerificationRequiredError = failureReceipt?.kind === "verification";
  const errorBannerText = failureReceipt?.message ?? null;
  const verificationAuditNotice =
    isVerificationRequiredError && errorBannerText ? errorBannerText : null;

  // Tool-run folding into collapsible bubbles lives in the group/timeline
  // layer (message-group.tsx): `aggregateSimilarToolCalls` merges consecutive
  // same-kind tool calls, and the component keeps a tool-carrying AI
  // message's streamed answer in the conversation lane instead of burying it
  // inside the process replay. That guard is what the old message-level
  // `groupActivities` folding in message-grouping.ts lacked, so it ate
  // streaming AI messages and was removed as a redundant, regression-prone
  // path. groupMessages stays a straight group mapper here.
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
  // Holds the ResizeObserver created in the turn-locator effect so the
  // activity-observer effect below can switch which marker node it watches
  // without tearing down the scroll/resize listeners.
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const observedMarkerRef = useRef<string | null>(null);
  const resolveAgentIdentity = useCallback(
    (msg?: (typeof messages)[number]): AgentIdentity => {
      const aiMsg = msg?.type === "ai" ? (msg as AIMessage) : undefined;
      if (threadId === "octopus-assistant" && currentAgent) {
        return {
          avatar:
            cleanIdentityText(currentAgent.avatar_url) ??
            fallbackAgentAvatarUrl(currentAgent.name),
          icon: cleanIdentityText(currentAgent.icon),
          id: currentAgent.name,
          name: currentAgent.display_name ?? currentAgent.name,
          role: undefined,
        };
      }
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
    [agentRosterMap, currentAgent, soleRosterEntry, thread.values, threadId],
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
    resizeObserverRef.current = resizeObserver;
    observedMarkerRef.current = null;
    // Only observe the scroll container here. Historical turns run under
    // `content-visibility:auto` (`.message-turn-history`), so they are skipped
    // from layout while off-screen and essentially never resize; observing all
    // of them made the observer list grow linearly with turn count on long
    // conversations. The only node that actually grows during streaming is the
    // active turn's marker, which the activity-observer effect below subscribes
    // to (and switches) based on activeTurnKey.
    if (resizeObserver && scrollElement instanceof HTMLElement) {
      resizeObserver.observe(scrollElement);
    }
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      scrollElement.removeEventListener("scroll", scheduleUpdate);
      if (scrollElement !== window) {
        window.removeEventListener("scroll", scheduleUpdate);
      }
      window.removeEventListener("resize", scheduleUpdate);
      resizeObserver?.disconnect();
      resizeObserverRef.current = null;
      observedMarkerRef.current = null;
    };
  }, [structuralFingerprint, turnMarkers]);

  // Switch which marker node the shared ResizeObserver watches as the active
  // turn changes. Keeps the observer count bounded (scroll container + 1
  // active marker) regardless of how many historical turns exist.
  useEffect(() => {
    const observer = resizeObserverRef.current;
    if (!observer) return;
    const prevKey = observedMarkerRef.current;
    if (prevKey) {
      const prevNode = groupRefs.current[prevKey];
      if (prevNode) observer.unobserve(prevNode);
    }
    observedMarkerRef.current = null;
    if (!activeTurnKey) return;
    const node = groupRefs.current[activeTurnKey];
    if (node) {
      observer.observe(node);
      observedMarkerRef.current = activeTurnKey;
    }
  }, [activeTurnKey, structuralFingerprint]);

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
        // REMOVED: Dead subtask status contract (lines 1444-1476).
        // Backend never sends "Task Succeeded. Result:" / "Task failed." /
        // "Task timed out" prefixes. Subtask status must flow through proper
        // SSE events (item/subtask/status), not text parsing.
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
                <span className="rounded-md border border-success/50 bg-success/10 px-1.5 py-0 text-xs leading-4 font-medium text-success">
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
    suppressReasoningPanel = false,
    afterContent?: ReactNode,
  ) => {
    const key = `${keyPrefix}/${msg.id}`;
    return (
      <div key={key}>
        {beforeContent}
        <MessageListItem
          message={msg}
          isLoading={thread.isLoading && msg.id === thread.streamingMessage?.id}
          chatFontSize={settings.display.chat_font_size}
          suppressReasoningPanel={
            Boolean(beforeContent) || suppressReasoningPanel
          }
          enableClarificationActions={
            !thread.isLoading && messages[messages.length - 1] === msg
          }
          isLastMessage={messages[messages.length - 1] === msg}
          messageIndex={messages.indexOf(msg)}
          afterContent={afterContent}
        />
      </div>
    );
  };

  const renderMessageWithHeader = (
    msg: (typeof messages)[number],
    keyPrefix: string | undefined,
    beforeContent?: ReactNode,
    suppressReasoningPanel = false,
    afterContent?: ReactNode,
  ) => {
    const key = `${keyPrefix}/${msg.id}`;
    const content = (
      <>
        {beforeContent}
        <MessageListItem
          message={msg}
          isLoading={thread.isLoading && msg.id === thread.streamingMessage?.id}
          chatFontSize={settings.display.chat_font_size}
          suppressReasoningPanel={
            Boolean(beforeContent) || suppressReasoningPanel
          }
          enableClarificationActions={
            !thread.isLoading && messages[messages.length - 1] === msg
          }
          isLastMessage={messages[messages.length - 1] === msg}
          messageIndex={messages.indexOf(msg)}
          afterContent={afterContent}
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
      const groupIndex = groupedMessages.indexOf(group);
      const turnHasProcessingLane = (() => {
        if (groupIndex < 0) return false;
        for (let index = groupIndex - 1; index >= 0; index -= 1) {
          const previous = groupedMessages[index]!;
          if (previous.type === "human") break;
          if (previous.type === "assistant:processing") return true;
        }
        for (
          let index = groupIndex + 1;
          index < groupedMessages.length;
          index += 1
        ) {
          const next = groupedMessages[index]!;
          if (next.type === "human") break;
          if (next.type === "assistant:processing") return true;
        }
        return false;
      })();
      const isTerminalAssistantGroup =
        group.type === "assistant" &&
        isLastAssistantGroupOfTurn(groupedMessages, group) &&
        !hasLaterProcessActivity(
          turnMessagesForGroup(groupedMessages, group),
          group,
        );
      const isProcessChangeGroup =
        group.type === "assistant" &&
        !isTerminalAssistantGroup &&
        hasMessageOutputSummary(group.messages);
      const outputSummary =
        isTerminalAssistantGroup && !deferOutputs ? (
          <MessageOutputSummary
            auditNotice={auditNotice}
            messages={group.messages}
            turnMessages={turnMessagesForGroup(groupedMessages, group)}
            threadId={threadId}
            onOpenArtifact={onOpenArtifact}
            failure={failure}
          />
        ) : isProcessChangeGroup ? (
          <MessageOutputSummary
            messages={group.messages}
            threadId={threadId}
            onOpenArtifact={onOpenArtifact}
            presentation="process"
          />
        ) : null;
      const outputHostMessage = outputSummary
        ? [...group.messages].reverse().find((message) => message.type === "ai")
        : undefined;
      let injectedBeforeContent = false;
      const renderedMessages = group.messages.map((msg) => {
        const beforeContent =
          beforeAssistantContent && msg.type === "ai" && !injectedBeforeContent
            ? beforeAssistantContent
            : undefined;
        if (beforeContent) injectedBeforeContent = true;
        return showAssistantAvatar || msg.type !== "ai"
          ? renderMessageWithHeader(
              msg,
              group.id,
              beforeContent,
              turnHasProcessingLane,
              msg === outputHostMessage ? outputSummary : undefined,
            )
          : renderMessageContent(
              msg,
              group.id,
              beforeContent,
              turnHasProcessingLane,
              msg === outputHostMessage ? outputSummary : undefined,
            );
      });
      // Check for subagents spawned via run_orchestration in the current turn.
      // These appear as LiveToolEvents with name="subagent" but don't create
      // tool_calls in the message, so hasSubagent() misses them.
      const subagentEventsInTurn = (() => {
        // Try liveToolEvents first (for current streaming turn), then fall back
        // to allToolEvents filtered by iteration (for historical turns).
        const eventsToSearch =
          liveToolEvents && liveToolEvents.length > 0
            ? liveToolEvents
            : (allToolEvents ?? []);

        if (eventsToSearch.length === 0) return [];

        const isLive = eventsToSearch === liveToolEvents;

        // For historical turns, we need to determine which iteration (turn index)
        // this group belongs to.
        const currentIteration = (() => {
          if (isLive) return -1; // Not needed for live events

          // Find which turn this group belongs to
          const turns = partitionMessageGroupsIntoTurns(groupedMessages);
          const groupIndex = groupedMessages.indexOf(group);

          for (let i = 0; i < turns.length; i++) {
            if (turns[i]!.groupIndexes.includes(groupIndex)) {
              return i;
            }
          }
          return -1;
        })();

        return eventsToSearch.filter((event) => {
          if (event.name !== "subagent") return false;
          if (!event.lifecycle || event.lifecycle !== "spawned") return false;

          // For live events, include all subagents.
          // For historical events, only include those matching this turn's iteration.
          return isLive || event.iteration === currentIteration;
        });
      })();

      const hasSubagentsInTurn = subagentEventsInTurn.length > 0;

      return (
        <>
          {group.type === "assistant" && !showAssistantAvatar ? (
            <div className="ml-11 w-auto">{renderedMessages}</div>
          ) : (
            renderedMessages
          )}
          {outputSummary && !outputHostMessage && outputSummary}
          {hasSubagentsInTurn && group.type === "assistant" && (
            <SubagentClusterSection
              subagentEvents={subagentEventsInTurn}
              groupId={group.id ?? group.messages[0]?.id ?? "assistant"}
              isLoading={
                thread.isLoading &&
                group.messages.some((m) => m.id === thread.streamingMessage?.id)
              }
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
              active={
                !thread.isLoading &&
                isLatestMessageGroup(groupedMessages, group)
              }
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

  const assistantFrameIdentity = useCallback(
    (group: (typeof groupedMessages)[number]): string | null => {
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
      const presentationIdentity = [
        identityKey(identity.avatar),
        identityKey(identity.icon),
      ]
        .filter((value): value is string => Boolean(value))
        .join("|");
      return presentationIdentity || null;
    },
    [resolveAgentIdentity],
  );

  // Budget the turn-wide scans once per groupedMessages change: the render
  // loop below used to re-derive turn message slices, last-assistant
  // positions and previous-speaker identities per group (slice + reverse +
  // map + filter each time), which is O(groups) per group and O(groups^2)
  // per frame. One walk per turn keeps it O(groups) per frame; the render
  // loop then does O(1) map lookups.
  const groupTurnRenderInfo = useMemo(() => {
    const info = new Map<number, GroupTurnRenderInfo>();
    for (const turn of messageTurns) {
      const start = turn.groupIndexes[0]!;
      const end = turn.groupIndexes[turn.groupIndexes.length - 1]!;
      // Same span and identity dedupe as turnMessagesForGroup: a turn starts
      // at its human group (or index 0 for the prelude) and runs to the last
      // group before the next human one.
      const seen = new Set<Message>();
      const turnMessages: Message[] = [];
      let lastAssistantActivityIndex = -1;
      for (let index = start; index <= end; index += 1) {
        const group = groupedMessages[index]!;
        if (
          group.type === "assistant" ||
          group.type === "assistant:processing" ||
          group.type === "assistant:clarification" ||
          group.type === "assistant:subagent"
        ) {
          lastAssistantActivityIndex = index;
        }
        for (const message of group.messages) {
          if (seen.has(message)) continue;
          seen.add(message);
          turnMessages.push(message);
        }
      }
      let previousAssistantGroupCount = 0;
      let previousAssistantIdentity: string | undefined;
      for (const index of turn.groupIndexes) {
        const group = groupedMessages[index]!;
        const assistantIdentity = assistantFrameIdentity(group);
        info.set(index, {
          turnMessages,
          isLastAssistantOfTurn:
            group.type === "assistant" &&
            index === lastAssistantActivityIndex &&
            !hasLaterProcessActivity(turnMessages, group),
          assistantIdentity,
          previousAssistantGroupCount,
          previousAssistantIdentity,
        });
        if (
          group.type === "assistant" ||
          group.type === "assistant:processing"
        ) {
          previousAssistantGroupCount += 1;
          if (
            assistantIdentity !== null &&
            previousAssistantIdentity === undefined
          ) {
            previousAssistantIdentity = assistantIdentity;
          }
        }
      }
    }
    return info;
  }, [messageTurns, groupedMessages, assistantFrameIdentity]);

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }

  // A terminal/send error and an active pulse must never be visible at the
  // same time. If the transport still reports loading while an error is
  // already authoritative, prefer the recoverable error receipt.
  const showConversationActivity = thread.isLoading && !thread.error;
  const showEmptyPendingAssistantFrame =
    messageTurns.length === 0 &&
    showConversationActivity &&
    !hasStreamingAnswer;
  const emptyPendingAssistantIdentity = showEmptyPendingAssistantFrame
    ? resolveAgentIdentity()
    : null;

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
        {showEmptyPendingAssistantFrame &&
          renderAssistantFrame({
            key: "pending-agent-frame/empty-turn",
            agentName: emptyPendingAssistantIdentity?.name,
            agentAvatar: emptyPendingAssistantIdentity?.avatar,
            agentIcon: emptyPendingAssistantIdentity?.icon,
            agentRole: emptyPendingAssistantIdentity?.role,
            children: (
              <PublicThinkingStatus
                isLoading={showConversationActivity}
                liveToolEvents={liveToolEvents ?? []}
                hasStreamingMessage={hasStreamingAnswer}
                vitals={streamVitals}
                className="ml-0"
              />
            ),
          })}
        {messageTurns.map((turn, turnIndex) => {
          const isLatestTurn = turnIndex === messageTurns.length - 1;
          const markerKey = turn.key.startsWith("human:") ? turn.key : null;
          // A submitted turn can spend several seconds waiting for its first
          // model event. During that gap there is no assistant message group
          // to own the avatar, which made the activity line look detached
          // from the agent. Reserve the same assistant frame immediately;
          // it disappears as soon as a visible assistant group arrives.
          const latestTurnHasVisibleAssistantGroup = turn.groupIndexes.some(
            (groupIndex) => {
              const group = groupedMessages[groupIndex];
              if (!group) return false;
              return (
                (group.type === "assistant" ||
                  group.type === "assistant:processing") &&
                hasVisibleMessageGroupContent(group.messages, t)
              );
            },
          );
          const showPendingAssistantFrame =
            isLatestTurn &&
            showConversationActivity &&
            !hasStreamingAnswer &&
            !latestTurnHasVisibleAssistantGroup;
          const pendingAssistantIdentity = showPendingAssistantFrame
            ? resolveAgentIdentity()
            : null;

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
                // ChatGPT-style entrance: animate new turns appearing, skip history
                isLatestTurn &&
                  "animate-[message-entrance_220ms_cubic-bezier(0.33,1,0.68,1)]",
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
                const groupInfo = groupTurnRenderInfo.get(index)!;
                const groupTurnMessages =
                  group.type === "assistant"
                    ? groupInfo.turnMessages
                    : group.messages;
                const structuredGroupFailure =
                  group.type === "assistant" && groupInfo.isLastAssistantOfTurn
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

                const assistantIdentity = groupInfo.assistantIdentity;
                const previousAssistantIdentity =
                  groupInfo.previousAssistantIdentity;
                const showAssistantAvatar =
                  groupInfo.previousAssistantGroupCount === 0 ||
                  (assistantIdentity !== null &&
                    previousAssistantIdentity !== undefined &&
                    previousAssistantIdentity !== assistantIdentity);

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
              {isLatestTurn &&
                (showPendingAssistantFrame ? (
                  renderAssistantFrame({
                    key: `pending-agent-frame/${turn.key}`,
                    agentName: pendingAssistantIdentity?.name,
                    agentAvatar: pendingAssistantIdentity?.avatar,
                    agentIcon: pendingAssistantIdentity?.icon,
                    agentRole: pendingAssistantIdentity?.role,
                    children: (
                      <PublicThinkingStatus
                        isLoading={showConversationActivity}
                        liveToolEvents={liveToolEvents ?? []}
                        hasStreamingMessage={hasStreamingAnswer}
                        vitals={streamVitals}
                        className="ml-0"
                      />
                    ),
                  })
                ) : (
                  <div
                    className="ml-11"
                    data-testid="assistant-continuation-activity"
                  >
                    <PublicThinkingStatus
                      isLoading={showConversationActivity}
                      liveToolEvents={liveToolEvents ?? []}
                      hasStreamingMessage={hasStreamingAnswer}
                      vitals={streamVitals}
                      className="ml-0"
                    />
                  </div>
                ))}
            </div>
          );
        })}

        {/* Follow-up suggestions: show after the last turn when conversation is idle */}
        {onSendFollowUp &&
          project &&
          messageTurns.length > 0 &&
          !thread.isLoading && (
            <FollowUpSuggestions
              project={project}
              agentId={threadId}
              conversationVersion={messageTurns.length}
              isLoading={thread.isLoading}
              onSelect={onSendFollowUp}
              className="ml-11 mt-4"
            />
          )}

        {footer}

        {errorBannerText &&
          !failureReceiptAttachedToGroup &&
          !failureAlreadyVisibleInAssistantText &&
          !(verificationAuditNotice && auditNoticeGroupKey) && (
            <div
              role="alert"
              className={cn(
                "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-[var(--shadow-xs)]",
                isWarningFailure
                  ? "border-warning/30/70 bg-warning/5 text-warning dark:border-warning/50"
                  : "border-destructive/25 bg-destructive/8 text-destructive dark:border-destructive/35 dark:bg-destructive/12",
              )}
            >
              {isWarningFailure ? (
                <AlertTriangleIcon className="mt-0.5 size-4 shrink-0 text-warning" />
              ) : (
                <XCircleIcon className="mt-0.5 size-4 shrink-0" />
              )}
              <div className="min-w-0 flex-1 leading-6">
                <div className="mb-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-medium">
                  <span>{failureHeaderText}</span>
                  {!isNetworkError && failedCompletedFileCount > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-0.5 text-xs font-normal text-foreground/70">
                      {t.message.completedChanges} · {failedCompletedFileCount}
                    </span>
                  )}
                </div>
                {!isNetworkError && (
                  <div className="text-sm opacity-80">{errorBannerText}</div>
                )}
                {failureReceipt?.kind === "environment" &&
                  onAuthorizeNetwork && (
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => onAuthorizeNetwork("common")}
                        className="rounded-md border border-warning/80 bg-warning/10 px-2.5 py-1 text-xs font-medium text-warning transition-colors hover:bg-warning/20 dark:border-warning/60 dark:hover:bg-warning/70"
                      >
                        {t.streaming.environmentBlockedAuthorizeCommon}
                      </button>
                      <button
                        type="button"
                        onClick={() => onAuthorizeNetwork("full")}
                        className="rounded-md border border-warning/40 px-2.5 py-1 text-xs font-medium text-warning/90 transition-colors hover:bg-warning/10 dark:border-warning/50"
                      >
                        {t.streaming.environmentBlockedAuthorizeFull}
                      </button>
                    </div>
                  )}
              </div>
            </div>
          )}

        <div
          data-testid="conversation-bottom-safe-area"
          style={{
            // The composer is an overlay. Reserve its measured height plus a
            // small reading-safe zone so an expanded reasoning block can be
            // scrolled completely above both the composer and the floating
            // "latest" affordance.
            height: `calc(max(${paddingBottom}px, var(--chat-input-overlay-height, ${paddingBottom}px)) + 56px)`,
          }}
        />
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
        style={{
          // Keep the affordance in the reading surface, not on top of the
          // absolutely-positioned composer. The layout publishes its measured
          // height, including expanded todos, approvals and multiline input.
          bottom: "calc(var(--chat-input-overlay-height, 160px) + 12px)",
        }}
      >
        {t.message.latest}
      </ConversationScrollButton>

      {showTimeoutWarning && !thread.error && (
        <div className="absolute top-4 left-[50%] z-10 -translate-x-1/2 flex items-center gap-3 rounded-lg border border-warning/70 bg-warning/5 px-4 py-2 text-xs text-warning shadow-[var(--shadow-xs)] dark:border-warning/50">
          <AlertTriangleIcon className="size-4 shrink-0 text-warning" />
          <span>
            {t.message.timeoutWarning(Math.floor(loadingAgeMs / 1000))}
          </span>
          <button
            type="button"
            onClick={() => void thread.stop()}
            className="rounded-md border border-warning/80 px-2 py-1 text-xs font-medium text-warning transition-colors hover:bg-warning/10 dark:border-warning/60 dark:hover:bg-warning/70"
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
          const label = t.message.turnNumberLabel(marker.number, marker.label);
          return (
            <button
              key={marker.key}
              aria-current={active ? "step" : undefined}
              aria-label={label}
              data-turn-marker-active={active ? "true" : undefined}
              data-turn-marker-kind={marker.kind}
              className={cn(
                "group relative flex w-6 items-center justify-center rounded-full transition-all duration-fast",
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
                  "rounded-full transition-all duration-fast",
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
