/**
 * Conversation -> AgentThreadState adapter.
 *
 * The realtime gateway delivers state as ``Conversation``: a flat list of turns, each turn a list of typed Items keyed by stable ``id``.
 *
 * Workspace pages consume the ``AgentThreadState`` view via ``useThreadStream``.
 *
 * Pure function with no side effects; safe to memoize.
 */

import type {
  AIMessage,
  HumanMessage,
  Message,
  ToolCall,
} from "@/core/api/types";
import type { Todo } from "@/core/todos";

import type {
  AgentMessageItem,
  ApprovalItem,
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  ErrorItem,
  FileChangeItem,
  GroundingSource,
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
 *   - Each turn's items are walked in declared order (the realtime
 *     reducer preserves ``item/started`` order, which matches what
 *     the previous ``messages-tuple`` stream used to produce).
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
 * The output is fresh on every call (callers can deep-compare safely).
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

    const turnMessages = turnToMessages(turn);
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

function turnToMessages(turn: Turn): Message[] {
  const out: Message[] = [];

  // We accumulate reasoning + plan + tool calls into the AIMessage that
  // FOLLOWS them. ``pending`` holds the so-far-collected metadata that
  // the next agentMessage (or end-of-turn synthetic AI) will absorb.
  type PendingAi = {
    reasoning: string[];
    plan: string | null;
    toolCalls: ToolCall[];
  };
  const newPending = (): PendingAi => ({
    reasoning: [],
    plan: null,
    toolCalls: [],
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
        if (r.content) pending.reasoning.push(r.content);
        else if (r.summary.length > 0) {
          pending.reasoning.push(r.summary.join("\n"));
        }
        break;
      }
      case "plan": {
        pending.plan = (item as PlanItem).text;
        break;
      }
      case "commandExecution": {
        const ce = item as CommandExecutionItem;
        pending.toolCalls.push({
          id: ce.id,
          name: commandExecutionToolName(ce),
          args: {
            ...commandExecutionInput(ce),
            output: ce.aggregatedOutput,
            exit_code: ce.exitCode,
          },
          type: "tool_call",
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
        });
        break;
      }
      case "agentMessage": {
        const am = item as AgentMessageItem;
        // The backend's ReAct loop streams the LLM's raw trajectory:
        // "Thought: ...\nAction: tool(...)\nFinal Answer: ..." into
        // a single ``agentMessage`` item. Rendering that verbatim dumps
        // ReAct scaffolding into the chat bubble. Peel it apart here so
        // the main bubble shows only the polished Final Answer while
        // the thought process falls through to ``reasoning_content``
        // (collapsible) and the Action line is dropped (the tool call
        // is already surfaced as a separate commandExecution item).
        const split = splitReactTrace(am.text || "");
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
        const ai: AIMessage = {
          type: "ai",
          id: am.id,
          content: split.finalAnswer ?? "",
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
  attachGroundingToLastAi(out, turn.grounding);
  return out;
}

// Fold the turn's codebase grounding (project docs/chunks it was grounded on)
// onto the final AI reply's ``additional_kwargs.grounding`` — the one channel
// the chat actually renders — so message-list-item can show a grounding chip.
// Attached once, to the last AI message (the final answer bubble).
function attachGroundingToLastAi(
  messages: Message[],
  grounding: GroundingSource[] | undefined,
): void {
  if (!grounding || grounding.length === 0) return;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || message.type !== "ai") continue;
    message.additional_kwargs = {
      ...(message.additional_kwargs ?? {}),
      grounding,
    };
    return;
  }
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

  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || message.type === "human") break;
    if (message.type !== "ai") continue;
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
  return merged;
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
    content: `出错了：${message}`,
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
}): Record<string, unknown> {
  const kwargs: Record<string, unknown> = {};
  if (pending.reasoning.length > 0) {
    kwargs.reasoning_content = pending.reasoning.join("\n\n");
  }
  if (pending.plan !== null) {
    kwargs.thinking_plan = pending.plan;
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
  const messages = turnToMessages(last);
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
      ROLE_NO_OUTPUT_PLACEHOLDER_RE.test(item.text)
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
  finalAnswer: string;
} {
  if (!text) return { thought: "", finalAnswer: "" };
  // Markers are recognised across all supported locales (en / zh /
  // ja / ko). The union regex lives in `@/core/i18n/llmMarkers` so
  // the spelling stays in one place — keep this function free of
  // hardcoded bilingual alternations.
  if (!hasLLMTraceMarkers(text)) {
    return { thought: "", finalAnswer: text };
  }
  const segs = segmentLLMTrace(text);

  const thoughts: string[] = [];
  let finalAnswer = "";
  for (const seg of segs) {
    const clean = seg.text.trim();
    if (!clean) continue;
    if (seg.kind === "thought") thoughts.push(clean);
    else if (seg.kind === "finalAnswer") finalAnswer = clean; // last one wins
    // action + observation + prelude are intentionally dropped
  }
  // If the LLM never emitted a Final Answer (e.g. turn interrupted,
  // or still streaming an intermediate step) show the most recent
  // thought as the placeholder bubble text so the message isn't
  // empty. Otherwise the Final Answer wins outright.
  if (!finalAnswer && thoughts.length > 0) {
    return { thought: thoughts.slice(0, -1).join("\n\n"), finalAnswer: "" };
  }
  return { thought: thoughts.join("\n\n"), finalAnswer };
}
