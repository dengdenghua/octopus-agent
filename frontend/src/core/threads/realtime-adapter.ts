/**
 * Conversation -> AgentThreadState adapter.
 *
 * The realtime gateway delivers state as ``Conversation``: a flat list of turns, each turn a list of typed Items keyed by stable ``id``.
 *
 * Workspace pages consume the ``AgentThreadState`` view via ``useThreadStream``.
 *
 * Semantically pure (output depends only on input); internally memoized
 * per Turn/Item identity so unchanged turns map to reference-equal
 * ``Message`` objects across calls — treat the output as immutable.
 */

import type {
  AIMessage,
  HumanMessage,
  Message,
  ToolCall,
} from "@/core/api/types";
import type { Todo } from "@/core/todos";
import { isPrivateAgentGroundingSource } from "@/core/realtime/items";
import { itemStreamText } from "@/core/realtime/reducer";

import type {
  AgentMessageItem,
  ApprovalItem,
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  ErrorItem,
  FileChangeItem,
  GroundingSource,
  Item,
  McpToolCallItem,
  PlanItem,
  ReasoningItem,
  SteeringUserMessageItem,
  SubagentItem,
  TodoListItem,
  Turn,
  UserMessageItem,
  VerificationItem,
} from "@/core/realtime/items";

import type { AgentThreadState } from "./types";
import {
  mentionsCompletion,
  mentionsDelivered,
  segmentLLMTrace,
  hasLLMTraceMarkers,
} from "@/core/i18n/llmMarkers";
import {
  commandExecutionInput,
  commandExecutionToolName,
} from "./realtime-tool-compat";

const ROLE_NO_OUTPUT_PLACEHOLDER_RE =
  /^\s*\[[^\]\n]{1,80}\]\s*\((?:no output|no visible output|empty output)\)\s*$/i;
const TEAM_ROLE_START_RE =
  /^\s*\[(?:planner|researcher|critic|arbiter|synthesizer|writer|reviewer|analyst|coder|designer|executor|tester)\]\s*starting\s*(?:[·•-]|\u00b7)\s*agent=[^\n]*\n*/i;
const TEAM_ROLE_PREFIX_RE =
  /^\s*\[(?:planner|researcher|critic|arbiter|synthesizer|writer|reviewer|analyst|coder|designer|executor|tester)\]\s*/i;
const NULLISH_PLACEHOLDER_RE = /^\s*(?:null|undefined|none|n\/a)\s*$/i;
const REPEATED_NULL_PLACEHOLDER_RE = /^\s*(?:null\s*)+$/i;

/**
 * Convert a realtime ``Conversation`` into the ``AgentThreadState``
 * shape that the legacy thread hooks (``useThreadStream``) expose.
 *
 * Mapping:
 *   - Each turn's items are walked in the server-authored causal order.
 *     Legacy items without timeline coordinates keep their stored positions.
 *   - User messages -> ``HumanMessage`` records.
 *   - Reasoning + agentMessage items in the SAME turn collapse into
 *     ONE ``AIMessage``: reasoning attaches to
 *     ``additional_kwargs.reasoning_content`` of the AI reply that
 *     immediately follows it.
 *   - commandExecution / mcpToolCall items become tool_calls on the
 *     trailing AIMessage of the same turn (or on a fresh AIMessage
 *     if there's no agentMessage yet).
 *   - fileChange items are surfaced through ``thread.artifacts``.
 *   - ``todo-list`` items are mapped to ``thread.todos``.
 *   - ``plan`` items are surfaced via ``additional_kwargs.thinking_plan``
 *     on the active AI reply.
 *   - ``error`` items become a final synthetic AIMessage with
 *     ``additional_kwargs.error``.
 *
 * The top-level state object and ``messages`` array are fresh on every
 * call, but ``Message`` objects are reused by reference while the
 * underlying ``Turn``/``Item`` objects are unchanged (the realtime
 * reducer rebuilds only what a delta touched). Downstream React.memo
 * layers rely on that identity to skip unchanged content during
 * streaming, so treat the returned messages as immutable.
 */
export function conversationToAgentThreadState(
  conv: Conversation,
  base?: Partial<AgentThreadState>,
): AgentThreadState {
  const messages: Message[] = [];
  const artifacts: string[] = base?.artifacts ? [...base.artifacts] : [];
  let todos: Todo[] | undefined = base?.todos ? [...base.todos] : undefined;

  for (const turn of conv.turns) {
    const turnArtifacts = turnArtifactsFrom(turn);
    if (turnArtifacts.length > 0) artifacts.push(...turnArtifacts);

    const turnTodos = turnTodosFrom(turn);
    if (turnTodos !== null) todos = turnTodos;

    const turnMessages = turnToMessagesStable(turn);
    messages.push(...turnMessages);
  }

  return {
    title: base?.title ?? "",
    messages,
    artifacts,
    ...(todos !== undefined ? { todos } : {}),
    ...(base?.agent_roster !== undefined
      ? { agent_roster: base.agent_roster }
      : {}),
    ...(base?.current_speaker !== undefined
      ? { current_speaker: base.current_speaker }
      : {}),
    ...(base?.execution_metrics !== undefined
      ? { execution_metrics: base.execution_metrics }
      : {}),
    ...(base?.execution_plan !== undefined
      ? { execution_plan: base.execution_plan }
      : {}),
  };
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Per-turn helpers
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

function turnArtifactsFrom(turn: Turn): string[] {
  const out: string[] = [];
  for (const item of turn.items) {
    if (item.type === "fileChange") {
      const fc = item as FileChangeItem;
      for (const change of fc.changes) {
        out.push(change.path);
      }
    } else if (item.type === "artifact") {
      out.push((item as ArtifactItem).path);
    }
  }
  return out;
}

/**
 * Returns the latest todo-list snapshot in the turn, or ``null`` if
 * none. (A turn can emit multiple todo-list updates; the last one
 * wins, matching how the live panel re-renders on each update.)
 */
function turnTodosFrom(turn: Turn): Todo[] | null {
  let latest: TodoListItem | null = null;
  for (const item of turn.items) {
    if (item.type === "todo-list") latest = item as TodoListItem;
  }
  if (latest === null) return null;
  return latest.plan.map((entry) => ({
    content: entry.title,
    status: entry.status,
  }));
}

// Identity caches. The realtime reducer keeps object identity stable for
// turns/items a delta didn't touch (replaceAt/replaceTurnItem rebuild only
// the changed one), so an unchanged ``Turn`` reference can reuse its whole
// mapping, and inside a changed turn an unchanged ``Item`` can reuse the
// ``Message`` it anchored last time. WeakMaps: entries die together with
// the reducer state that owns the keys.
const turnMessagesCache = new WeakMap<Turn, Message[]>();
const itemMessageCache = new WeakMap<Item, Message>();

function turnToMessagesStable(turn: Turn): Message[] {
  const cached = turnMessagesCache.get(turn);
  if (cached) return cached;

  const fresh = turnToMessages(turn);

  // Reconcile per-message identity: a message anchored to an item id
  // (user/steering/error messages, and AI messages carrying their
  // agentMessage item id) is swapped for last call's object when its
  // content is unchanged, keeping the reference strictly equal for
  // React.memo consumers. Synthetic flush messages have no id → always
  // fresh (they only exist on interrupted/streaming tails).
  const itemsById = new Map<string, Item>();
  for (const item of turn.items) itemsById.set(item.id, item);
  for (let index = 0; index < fresh.length; index += 1) {
    const message = fresh[index];
    if (!message?.id) continue;
    const anchor = itemsById.get(message.id);
    if (!anchor) continue;
    const previous = itemMessageCache.get(anchor);
    if (previous && stableDeepEqual(previous, message)) {
      fresh[index] = previous;
    } else {
      itemMessageCache.set(anchor, message);
    }
  }

  turnMessagesCache.set(turn, fresh);
  return fresh;
}

// Structural equality with a reference fast path. Messages rebuilt from
// unchanged items carry reference-equal leaves (strings/arrays lifted off
// the item), so the walk touches object shells without re-comparing large
// payloads byte by byte.
function stableDeepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (
    typeof a !== "object" ||
    typeof b !== "object" ||
    a === null ||
    b === null
  ) {
    return false;
  }
  const aIsArray = Array.isArray(a);
  if (aIsArray !== Array.isArray(b)) return false;
  if (aIsArray) {
    const left = a as unknown[];
    const right = b as unknown[];
    if (left.length !== right.length) return false;
    for (let index = 0; index < left.length; index += 1) {
      if (!stableDeepEqual(left[index], right[index])) return false;
    }
    return true;
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  if (keys.length !== Object.keys(right).length) return false;
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(right, key)) return false;
    if (!stableDeepEqual(left[key], right[key])) return false;
  }
  return true;
}

function turnToMessages(turn: Turn): Message[] {
  const out: Message[] = [];

  // A cancelled turn may contain a final agentMessage snapshot whose bytes
  // were flushed just before the interruption. It is a recoverable draft,
  // not an authoritative response. Target only the last prose item; earlier
  // public checkpoints and completed tool evidence stay visible.
  let interruptedMessageId: string | null = null;
  if (turn.status === "interrupted") {
    for (let index = turn.items.length - 1; index >= 0; index -= 1) {
      const item = turn.items[index];
      if (item?.type === "agentMessage") {
        interruptedMessageId = item.id;
        break;
      }
    }
  }

  // We accumulate reasoning + plan + tool calls into the AIMessage that
  // FOLLOWS them. ``pending`` holds the so-far-collected metadata that
  // the next agentMessage (or end-of-turn synthetic AI) will absorb.
  type PendingAi = {
    reasoning: string[];
    plan: string | null;
    toolCalls: ToolCall[];
    // Sum of reasoning item durationMs contributing to this AI message.
    // Null when no reasoning item carried a duration (legacy data).
    reasoningDurationMs: number | null;
    // ISO timestamp of the earliest reasoning item's createdAt — used by
    // the UI to start the live thinking timer at the true first-token
    // arrival time instead of the React render frame.
    reasoningStartedAt: string | null;
  };
  const newPending = (): PendingAi => ({
    reasoning: [],
    plan: null,
    toolCalls: [],
    reasoningDurationMs: null,
    reasoningStartedAt: null,
  });
  let pending: PendingAi = newPending();

  const pushAiMessage = (ai: AIMessage): void => {
    const duplicateIndex = findDuplicateAiMessageIndex(out, ai);
    if (duplicateIndex >= 0) {
      out[duplicateIndex] = mergeDuplicateAiMessages(
        out[duplicateIndex] as AIMessage,
        ai,
      );
      return;
    }
    out.push(ai);
  };

  const flushPendingAsTrailingAi = (): void => {
    // End-of-turn flush: if there's leftover reasoning/plan/tool_calls
    // but no agentMessage came through (e.g. interrupted mid-turn),
    // surface them as a synthetic AI record so the UI doesn't lose
    // the work-in-progress display.
    if (
      pending.reasoning.length === 0 &&
      pending.plan === null &&
      pending.toolCalls.length === 0
    ) {
      return;
    }
    if (
      turn.status === "completed" &&
      mergePendingIntoLastAiAnswer(out, pending)
    ) {
      pending = newPending();
      return;
    }
    const ai: AIMessage = {
      type: "ai",
      content: "",
      additional_kwargs: buildAiAdditionalKwargs(pending),
      ...(pending.toolCalls.length > 0
        ? { tool_calls: pending.toolCalls }
        : {}),
    };
    pushAiMessage(ai);
    pending = newPending();
  };

  for (const item of turn.items) {
    switch (item.type) {
      case "userMessage": {
        // Flush any preceding agent state before we move to a new
        // turn boundary represented by a user message inside the
        // turn (rare; usually one user message per turn).
        flushPendingAsTrailingAi();
        out.push(userMessageToHuman(item as UserMessageItem));
        break;
      }
      case "steeringUserMessage": {
        flushPendingAsTrailingAi();
        const steering = item as SteeringUserMessageItem;
        out.push({
          type: "human",
          id: steering.id,
          content: steering.text,
          additional_kwargs: {
            steering: true,
            target_turn_id: steering.targetTurnId,
          },
        });
        break;
      }
      case "reasoning": {
        const r = item as ReasoningItem;
        const content = itemStreamText(r);
        if (content) pending.reasoning.push(content);
        else if (r.summary.length > 0) {
          pending.reasoning.push(r.summary.join("\n"));
        }
        // Accumulate wall-clock thinking time across consecutive reasoning
        // items. Null durations (legacy data) are skipped; if every item is
        // null the total stays null so the UI shows nothing on replay.
        if (typeof r.durationMs === "number" && r.durationMs >= 0) {
          pending.reasoningDurationMs =
            (pending.reasoningDurationMs ?? 0) + r.durationMs;
        }
        // Keep the earliest reasoning item's createdAt so the UI can start
        // the live timer at the true first-token arrival time.
        if (
          r.createdAt &&
          (pending.reasoningStartedAt === null ||
            r.createdAt < pending.reasoningStartedAt)
        ) {
          pending.reasoningStartedAt = r.createdAt;
        }
        break;
      }
      case "plan": {
        pending.plan = itemStreamText(item as PlanItem);
        break;
      }
      case "commandExecution": {
        const ce = item as CommandExecutionItem;
        pending.toolCalls.push({
          id: ce.id,
          name: commandExecutionToolName(ce),
          args: {
            ...commandExecutionInput(ce),
            output: itemStreamText(ce),
            exit_code: ce.exitCode,
          },
          type: "tool_call",
          effectReceipt: ce.effectReceipt ?? undefined,
          ...toolCallTimelineCoordinates(ce),
        });
        break;
      }
      case "mcpToolCall": {
        const mcp = item as McpToolCallItem;
        pending.toolCalls.push({
          id: mcp.id,
          name: `${mcp.server}.${mcp.tool}`,
          args: mcp.arguments,
          type: "tool_call",
          ...toolCallTimelineCoordinates(mcp),
        });
        break;
      }
      case "subagent": {
        const subagent = item as SubagentItem;
        pending.toolCalls.push({
          id: subagent.id,
          name: "subagent",
          args: {
            subagent_id: subagent.subagentId,
            role: subagent.role,
            name: subagent.name,
            codename: subagent.codename,
            status: subagent.status,
            summary: subagent.summary,
            error: subagent.error,
            files_touched: subagent.filesTouched,
          },
          type: "tool_call",
          ...toolCallTimelineCoordinates(subagent),
        });
        break;
      }
      case "agentMessage": {
        const am = item as AgentMessageItem;
        const isInterruptedMessage = am.id === interruptedMessageId;
        const isFailedMessage = am.status === "failed";
        const split = splitReactTrace(itemStreamText(am));
        const messageKind =
          am.messageKind ??
          (split.publicUpdate && !split.finalAnswer ? "commentary" : "answer");
        // The backend's ReAct loop streams the LLM's raw trajectory:
        // "Thought: ...\nAction: tool(...)\nFinal Answer: ..." into
        // a single ``agentMessage`` item. Rendering that verbatim dumps
        // ReAct scaffolding into the chat bubble. Peel it apart here so
        // the main bubble shows only the polished Final Answer while
        // the thought process falls through to ``reasoning_content``
        // (collapsible) and the Action line is dropped (the tool call
        // is already surfaced as a separate commandExecution item).
        const kwargs = buildAiAdditionalKwargs(pending);
        // Merge any Thought text extracted from the agentMessage into
        // whatever reasoning the earlier ``reasoning`` items already
        // accumulated.
        if (split.thought) {
          const existing =
            typeof kwargs.reasoning_content === "string"
              ? (kwargs.reasoning_content as string)
              : "";
          kwargs.reasoning_content = existing
            ? `${existing}\n\n${split.thought}`
            : split.thought;
        }
        if (isPostFinalStatusOnlyMessage(split.finalAnswer, pending, out)) {
          pending = newPending();
          break;
        }
        // Per-speaker identity (group/team rooms) → additional_kwargs the
        // message-list reads to render the real author's avatar + name.
        if (am.agentDisplayName) {
          kwargs.agent_display_name = am.agentDisplayName;
        }
        if (am.agentAvatarUrl) {
          kwargs.agent_avatar_url = am.agentAvatarUrl;
        }
        if (am.agentIcon) {
          kwargs.agent_icon = am.agentIcon;
        }
        if (am.phaseId) {
          kwargs.phase_id = am.phaseId;
        }
        if (am.parentItemId) {
          kwargs.parent_item_id = am.parentItemId;
        }
        if (typeof am.progressSequence === "number") {
          kwargs.progress_sequence = am.progressSequence;
        }
        if (typeof am.timelineSequence === "number") {
          kwargs.timeline_sequence = am.timelineSequence;
        }
        // Current realtime messages carry an explicit protocol lane. Expose
        // it to the grouping layer so the very first answer token renders in
        // the answer lane instead of being reclassified later by text length
        // or Markdown shape. The fallback above keeps old logs compatible.
        kwargs.message_kind = messageKind;
        if (isInterruptedMessage) {
          kwargs.response_state = "interrupted";
          if (turn.interruptReason) {
            kwargs.interrupt_reason = turn.interruptReason;
          }
          if (split.finalAnswer?.trim()) {
            // Keep the draft available to the workbench/replay layer without
            // presenting it as the assistant's settled answer in chat.
            kwargs.interrupted_draft = split.finalAnswer;
          }
        }
        if (isFailedMessage) {
          const failureDetail = split.finalAnswer?.trim() || "turn failed";
          kwargs.response_state = "failed";
          kwargs.error = {
            message: failureDetail,
            will_retry: false,
            info: { code: "agent_response_failed" },
          };
        }
        if (messageKind === "commentary" && !isInterruptedMessage) {
          kwargs.public_progress = true;
        }
        const ai: AIMessage = {
          type: "ai",
          id: am.id,
          content:
            isInterruptedMessage || isFailedMessage
              ? ""
              : (split.finalAnswer || split.publicUpdate || ""),
          additional_kwargs: kwargs,
          ...(pending.toolCalls.length > 0
            ? { tool_calls: pending.toolCalls }
            : {}),
        };
        pushAiMessage(ai);
        pending = newPending();
        break;
      }
      case "fileChange": {
        // FileChanges are surfaced as AIMessage tool_calls so the
        // LiveToolTimeline sees them; the artifact list separately
        // collects the paths (see ``turnArtifactsFrom``).
        const fc = item as FileChangeItem;
        pending.toolCalls.push({
          id: fc.id,
          name: "file_change",
          args: {
            changes: fc.changes,
            grant_root: fc.grantRoot,
          },
          type: "tool_call",
          ...toolCallTimelineCoordinates(fc),
        });
        break;
      }
      case "todo-list": {
        // Already surfaced via ``turnTodosFrom`` at the thread level;
        // no-op here.
        break;
      }
      case "approval": {
        const approval = item as ApprovalItem;
        pending.toolCalls.push({
          id: approval.id,
          name: "approval",
          args: {
            method: approval.method,
            decision: approval.decision,
            target_item_id: approval.targetItemId,
            params: approval.params,
          },
          type: "tool_call",
          ...toolCallTimelineCoordinates(approval),
        });
        break;
      }
      case "verification": {
        const verification = item as VerificationItem;
        pending.toolCalls.push({
          id: verification.id,
          name: "verification",
          args: {
            command: verification.command,
            kind: verification.kind,
            exit_code: verification.exitCode,
            summary: verification.summary,
            related_files: verification.relatedFiles,
            related_change_item_ids: verification.relatedChangeItemIds,
          },
          type: "tool_call",
          ...toolCallTimelineCoordinates(verification),
        });
        break;
      }
      case "artifact": {
        const artifact = item as ArtifactItem;
        pending.toolCalls.push({
          id: artifact.id,
          name: "artifact",
          args: {
            artifact_id: artifact.artifactId,
            kind: artifact.kind,
            path: artifact.path,
            title: artifact.title,
            render_status: artifact.renderStatus,
            validation_status: artifact.validationStatus,
          },
          type: "tool_call",
          ...toolCallTimelineCoordinates(artifact),
        });
        break;
      }
      case "error": {
        flushPendingAsTrailingAi();
        pushAiMessage(errorToAi(item as ErrorItem));
        break;
      }
      default: {
        // Unknown item types: skip silently. The reducer is stricter,
        // but this adapter prefers forward-compatibility (a future
        // item type shouldn't break legacy pages).
        const _exhaustive: never = item;
        void _exhaustive;
      }
    }
  }

  flushPendingAsTrailingAi();
  appendFailedTurnReceipt(out, turn);
  attachGroundingToNarrativeAnchor(out, turn.grounding);
  return out;
}

function appendFailedTurnReceipt(out: Message[], turn: Turn): void {
  if (turn.status !== "failed") return;
  if (
    out.some(
      (message) =>
        message.type === "ai" &&
        typeof message.additional_kwargs?.error === "object" &&
        message.additional_kwargs.error !== null,
    )
  ) {
    return;
  }

  const verificationMessage = failedVerificationMessage(turn);
  const turnError =
    turn.error && typeof turn.error === "object"
      ? (turn.error as Record<string, unknown>)
      : null;
  const turnErrorMessage =
    typeof turnError?.message === "string" ? turnError.message.trim() : "";
  const turnErrorCode =
    typeof turnError?.code === "string" ? turnError.code.trim() : "";
  const message = verificationMessage || turnErrorMessage || "turn failed";
  const verificationRequired = turn.items.some(
    (item) =>
      item.type === "verification" &&
      item.status === "failed" &&
      /verification required/i.test((item as VerificationItem).command),
  );
  const code = verificationMessage
    ? verificationRequired
      ? "verification_required"
      : "verification_failed"
    : turnErrorCode || "turn_failed";

  out.push({
    id: `${turn.id}:failure-receipt`,
    type: "ai",
    content: "",
    additional_kwargs: {
      response_state: "failed",
      error: {
        message,
        will_retry: false,
        info: { code },
      },
    },
  });
}

function toolCallTimelineCoordinates(
  item: Item,
): Pick<ToolCall, "timelineSequence" | "parentItemId" | "phaseId"> {
  return {
    timelineSequence: item.timelineSequence ?? null,
    parentItemId: item.parentItemId ?? null,
    phaseId: item.phaseId ?? null,
  };
}

// Fold the turn's codebase grounding (project docs/chunks it was grounded on)
// onto the first public checkpoint, which is the earliest conversational beat
// that can truthfully acknowledge those sources. This is structural: it does
// not classify prose into a hard-coded orient/investigate/synthesize ladder.
// Turns without public progress keep the legacy final-answer fallback.
function attachGroundingToNarrativeAnchor(
  messages: Message[],
  grounding: GroundingSource[] | undefined,
): void {
  const safeGrounding = grounding?.filter(
    (source) => !isPrivateAgentGroundingSource(source),
  );
  if (!safeGrounding || safeGrounding.length === 0) return;
  let fallbackIndex = -1;
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message || message.type !== "ai") continue;
    fallbackIndex = index;
    if (message.additional_kwargs?.public_progress === true) {
      fallbackIndex = index;
      break;
    }
  }
  if (fallbackIndex < 0) return;
  const anchor = messages[fallbackIndex];
  if (!anchor || anchor.type !== "ai") return;
  // Copy-on-write: the message object may be an identity-cached one shared
  // with a previous mapping; mutating it would hide the change from React.memo.
  messages[fallbackIndex] = {
    ...anchor,
    additional_kwargs: {
      ...(anchor.additional_kwargs ?? {}),
      grounding: safeGrounding,
    },
  };
}

function mergePendingIntoLastAiAnswer(
  messages: Message[],
  pending: {
    reasoning: string[];
    plan: string | null;
    toolCalls: ToolCall[];
  },
): boolean {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || message.type === "human") break;
    if (message.type !== "ai") continue;
    // Commentary is a process checkpoint, never the delivered answer. A
    // completed turn can still have trailing private reasoning (providers
    // sometimes finish the reasoning item after the answer item); attaching
    // that tail to commentary makes the adapter treat the checkpoint as if it
    // were the terminal response and can hide the real answer downstream.
    if (message.additional_kwargs?.public_progress === true) continue;
    if (!normalizeMessageTextForDedupe(message.content)) continue;

    const existing = message as AIMessage;
    const incoming: AIMessage = {
      type: "ai",
      content: "",
      additional_kwargs: buildAiAdditionalKwargs(pending),
      ...(pending.toolCalls.length > 0
        ? { tool_calls: pending.toolCalls }
        : {}),
    };
    messages[index] = mergeAiTraceMetadata(existing, incoming);
    return true;
  }
  return false;
}

function isPostFinalStatusOnlyMessage(
  content: string,
  pending: { reasoning: string[]; toolCalls: ToolCall[] },
  out: Message[],
): boolean {
  if (
    !out.some(
      (message) =>
        message.type === "ai" &&
        message.additional_kwargs?.public_progress !== true &&
        normalizeMessageTextForDedupe(message.content).length >= 24,
    )
  ) {
    return false;
  }
  const hasOnlyTodoTools =
    pending.toolCalls.length === 0 ||
    pending.toolCalls.every((toolCall) =>
      ["todo_write", "write_todos"].includes(toolCall.name),
    );
  if (!hasOnlyTodoTools) return false;

  const text = normalizeStatusOnlyText(
    [content, ...pending.reasoning].join("\n"),
  );
  if (!text) return false;
  return mentionsDelivered(text) && mentionsCompletion(text);
}

function normalizeStatusOnlyText(value: string): string {
  return value
    .replace(/[`*_~>#-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function normalizeMessageTextForDedupe(value: unknown): string {
  if (typeof value !== "string") return "";
  const split = splitReactTrace(value);
  const text = split.finalAnswer || value;
  const stripped = text
    .replace(TEAM_ROLE_START_RE, "")
    .replace(TEAM_ROLE_PREFIX_RE, "")
    .trim();
  if (
    NULLISH_PLACEHOLDER_RE.test(stripped) ||
    REPEATED_NULL_PLACEHOLDER_RE.test(stripped)
  ) {
    return "";
  }
  return stripped
    .replace(/<details\b[\s\S]*?<\/details>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/[`*_~>#-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function findDuplicateAiMessageIndex(
  messages: Message[],
  candidate: AIMessage,
): number {
  const candidateText = normalizeMessageTextForDedupe(candidate.content);
  if (candidateText.length < 24) return -1;
  const candidateIsProgress =
    candidate.additional_kwargs?.public_progress === true;

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || message.type === "human") break;
    if (message.type !== "ai") continue;
    if (
      (message.additional_kwargs?.public_progress === true) !==
      candidateIsProgress
    ) {
      continue;
    }
    const existingText = normalizeMessageTextForDedupe(message.content);
    if (!existingText) continue;
    if (existingText === candidateText) return index;
  }
  return -1;
}

function mergeDuplicateAiMessages(
  existing: AIMessage,
  duplicate: AIMessage,
): AIMessage {
  return mergeAiTraceMetadata(existing, duplicate);
}

function mergeAiTraceMetadata(
  existing: AIMessage,
  duplicate: AIMessage,
): AIMessage {
  const additional = mergeAdditionalKwargs(
    existing.additional_kwargs,
    duplicate.additional_kwargs,
  );
  const toolCalls = [
    ...(existing.tool_calls ?? []),
    ...(duplicate.tool_calls ?? []),
  ];
  return {
    ...existing,
    id: existing.id ?? duplicate.id,
    additional_kwargs: additional,
    ...(toolCalls.length > 0 ? { tool_calls: dedupeToolCalls(toolCalls) } : {}),
  };
}

function mergeAdditionalKwargs(
  existing?: Record<string, unknown>,
  incoming?: Record<string, unknown>,
): Record<string, unknown> | undefined {
  if (!existing && !incoming) return undefined;
  const merged: Record<string, unknown> = {
    ...(existing ?? {}),
    ...(incoming ?? {}),
  };
  const reasoning = mergeTextBlocks(
    existing?.reasoning_content,
    incoming?.reasoning_content,
  );
  if (reasoning) merged.reasoning_content = reasoning;
  // Sum thinking durations when trailing reasoning is merged into an
  // already-emitted AI message (e.g. reasoning finishes after the answer).
  const mergedDuration = mergeReasoningDurationMs(
    existing?.reasoning_duration_ms,
    incoming?.reasoning_duration_ms,
  );
  if (mergedDuration !== null) {
    merged.reasoning_duration_ms = mergedDuration;
  } else {
    delete merged.reasoning_duration_ms;
  }
  return merged;
}

function mergeReasoningDurationMs(
  a: unknown,
  b: unknown,
): number | null {
  const aNum = typeof a === "number" && Number.isFinite(a) ? a : null;
  const bNum = typeof b === "number" && Number.isFinite(b) ? b : null;
  if (aNum === null && bNum === null) return null;
  return (aNum ?? 0) + (bNum ?? 0);
}

function mergeTextBlocks(a: unknown, b: unknown): string | undefined {
  const blocks = [a, b]
    .filter(
      (value): value is string =>
        typeof value === "string" && value.trim().length > 0,
    )
    .map((value) => value.trim());
  if (blocks.length === 0) return undefined;
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const block of blocks) {
    const normalized = normalizeMessageTextForDedupe(block);
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    unique.push(block);
  }
  return unique.join("\n\n");
}

function dedupeToolCalls(toolCalls: ToolCall[]): ToolCall[] {
  const seen = new Set<string>();
  const unique: ToolCall[] = [];
  for (const toolCall of toolCalls) {
    const key = toolCall.id
      ? `id:${toolCall.id}`
      : `${toolCall.name}:${JSON.stringify(toolCall.args)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(toolCall);
  }
  return unique;
}

function userMessageToHuman(item: UserMessageItem): HumanMessage {
  return {
    type: "human",
    id: item.id,
    content: item.text,
    ...(item.attachments && item.attachments.length > 0
      ? { additional_kwargs: { attachments: item.attachments } }
      : {}),
  };
}

function errorToAi(item: ErrorItem): AIMessage {
  const message = item.message || "turn failed";
  return {
    type: "ai",
    id: item.id,
    // Error details belong to the terminal receipt rendered after the turn's
    // chronological work lane. Keeping this synthetic message body empty
    // prevents a failure sentence from appearing before tool events merely
    // because an agentMessage item was opened earlier in the stream.
    content: "",
    additional_kwargs: {
      error: {
        message,
        will_retry: item.willRetry,
        info: item.errorInfo,
      },
    },
  };
}

function buildAiAdditionalKwargs(pending: {
  reasoning: string[];
  plan: string | null;
  reasoningDurationMs?: number | null;
  reasoningStartedAt?: string | null;
}): Record<string, unknown> {
  const kwargs: Record<string, unknown> = {};
  if (pending.reasoning.length > 0) {
    kwargs.reasoning_content = pending.reasoning.join("\n\n");
  }
  if (pending.plan !== null) {
    kwargs.thinking_plan = pending.plan;
  }
  if (typeof pending.reasoningDurationMs === "number") {
    kwargs.reasoning_duration_ms = pending.reasoningDurationMs;
  }
  if (pending.reasoningStartedAt) {
    kwargs.reasoning_started_at = pending.reasoningStartedAt;
  }
  return kwargs;
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// Convenience: derive ``isLoading`` / ``error`` from Conversation
// for callers that need just those flags without full state mapping.
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

export function conversationIsLoading(conv: Conversation): boolean {
  if (conv.turns.length === 0) return false;
  const last = conv.turns[conv.turns.length - 1];
  return last !== undefined && last.status === "inProgress";
}

export function conversationStreamingMessage(
  conv: Conversation,
): Message | null {
  if (!conversationIsLoading(conv)) return null;
  const last = conv.turns[conv.turns.length - 1];
  if (!last) return null;
  // Shares the identity cache with conversationToAgentThreadState so the
  // streaming message keeps the same reference as its list counterpart.
  const messages = turnToMessagesStable(last);
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message?.type === "ai") return message;
  }
  return null;
}

export function conversationLastError(conv: Conversation): Error | undefined {
  // Return only when the most-recent turn ended in a hard failure.
  if (conv.turns.length === 0) return undefined;
  const last = conv.turns[conv.turns.length - 1];
  if (last === undefined) return undefined;
  if (last.status !== "failed") return undefined;
  if (last.error && typeof last.error === "object") {
    const m = (last.error as { message?: unknown }).message;
    const message = typeof m === "string" ? m : "turn failed";
    if (!/^turn failed$/i.test(message.trim())) {
      return new Error(message);
    }
  }
  // Look for a trailing ErrorItem.
  for (let i = last.items.length - 1; i >= 0; i--) {
    const item = last.items[i];
    if (item !== undefined && item.type === "error") {
      return new Error((item as ErrorItem).message);
    }
  }
  for (let i = last.items.length - 1; i >= 0; i--) {
    const item = last.items[i];
    if (
      item?.type === "agentMessage" &&
      item.status === "failed" &&
      itemStreamText(item as AgentMessageItem).trim()
    ) {
      return new Error(itemStreamText(item as AgentMessageItem).trim());
    }
  }
  const verificationMessage = failedVerificationMessage(last);
  if (verificationMessage) return new Error(verificationMessage);
  if (isNoOutputPlannerFailure(last)) return undefined;
  return new Error("turn failed");
}

function failedVerificationMessage(turn: Turn): string | undefined {
  for (let i = turn.items.length - 1; i >= 0; i--) {
    const item = turn.items[i];
    if (item?.type !== "verification" || item.status !== "failed") continue;
    const verification = item as VerificationItem;
    return (
      verification.summary?.trim() ||
      verification.stderrTail?.trim() ||
      verification.stdoutTail?.trim() ||
      "verification failed"
    );
  }
  return undefined;
}

function isNoOutputPlannerFailure(turn: Turn): boolean {
  let sawNoOutputAgentMessage = false;
  for (const item of turn.items) {
    if (item.type === "userMessage") continue;
    if (
      item.type === "agentMessage" &&
      ROLE_NO_OUTPUT_PLACEHOLDER_RE.test(itemStreamText(item))
    ) {
      sawNoOutputAgentMessage = true;
      continue;
    }
    return false;
  }
  return sawNoOutputAgentMessage;
}

// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// ReAct trace splitter
// â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

/**
 * Split a ReAct-formatted LLM trajectory into the three semantic
 * pieces the UI needs separately:
 *
 *   - ``thought``:      everything inside ``Thought:`` blocks. Shown
 *                       as collapsible reasoning, not main content.
 *   - ``finalAnswer``:  body after the LAST ``Final Answer:`` marker.
 *                       Rendered as the agent's visible message.
 *
 * ``Action: tool(...)`` and ``Observation: ...`` lines are dropped:
 * the action is already represented by a separate
 * ``commandExecution`` / ``mcpToolCall`` item, and the observation is
 * that tool's ``aggregatedOutput`` / ``result``. Rendering them again
 * inside the message bubble is noise.
 *
 * If no ReAct markers are present at all, the whole text is returned
 * as ``finalAnswer`` unchanged, so non-ReAct agents (e.g. a plain
 * chat reply) stay pristine.
 *
 * Exported for direct unit tests.
 */
export function splitReactTrace(text: string): {
  thought: string;
  publicUpdate: string;
  finalAnswer: string;
} {
  if (!text) return { thought: "", publicUpdate: "", finalAnswer: "" };
  // Markers are recognised across all supported locales (en / zh /
  // ja / ko). The union regex lives in `@/core/i18n/llmMarkers` so
  // the spelling stays in one place — keep this function free of
  // hardcoded bilingual alternations.
  if (!hasLLMTraceMarkers(text)) {
    return { thought: "", publicUpdate: "", finalAnswer: text };
  }
  const segs = segmentLLMTrace(text);

  const thoughts: string[] = [];
  const updates: string[] = [];
  let finalAnswer = "";
  for (const seg of segs) {
    const clean = seg.text.trim();
    if (!clean) continue;
    if (seg.kind === "thought") thoughts.push(clean);
    else if (seg.kind === "update") updates.push(clean);
    else if (seg.kind === "finalAnswer") finalAnswer = clean; // last one wins
    // action + observation + prelude are intentionally dropped
  }
  // If the LLM never emitted a Final Answer (e.g. turn interrupted,
  // or still streaming an intermediate step) show the most recent
  // thought as the placeholder bubble text so the message isn't
  // empty. Otherwise the Final Answer wins outright.
  if (!finalAnswer && thoughts.length > 0) {
    return {
      thought: thoughts.slice(0, -1).join("\n\n"),
      publicUpdate: updates.at(-1) ?? "",
      finalAnswer: "",
    };
  }
  return {
    thought: thoughts.join("\n\n"),
    publicUpdate: updates.at(-1) ?? "",
    finalAnswer,
  };
}
