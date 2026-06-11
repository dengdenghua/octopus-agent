/**
 * Realtime-backed implementation of `useThreadStream`.
 *
 * It opens the realtime WebSocket, maps `Conversation` to the
 * `AgentThreadState` shape consumed by workspace pages, and exposes
 * live tool events derived from realtime items.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  conversationIsLoading,
  conversationLastError,
  conversationStreamingMessage,
  conversationToAgentThreadState,
} from "@/core/threads/realtime-adapter";
import { swallow } from "@/core/utils/log";
import { useRealtimeThread } from "@/core/realtime";
import type {
  AgentPhaseSnapshot,
  ApprovalItem,
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  FileChangeItem,
  Item,
  McpToolCallItem,
  SubagentItem,
  PendingApproval,
  TodoListItem,
  Turn,
  VerificationItem,
} from "@/core/realtime/items";

import type { Message } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { LiveToolEvent } from "@/components/workspace/live-tool-timeline";
import type { AgentThreadState, ReasoningEffort } from "@/core/threads/types";
import type { ToolEndEvent } from "@/core/threads/hooks";
import {
  permissionRuntimeConfig,
  type ApprovalPolicy,
  type SandboxPolicy,
} from "@/core/permissions";
import {
  promptInputFilePartToFile,
  uploadFiles,
  type UploadedFileInfo,
} from "@/core/uploads";
import {
  commandExecutionInput,
  commandExecutionToolName,
} from "./realtime-tool-compat";

/** File payload accepted by `sendMessage`. */
export interface FileInMessage {
  file_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
}

/** Full BaseStream shape consumed by workspace pages. */
type ExposedRealtimeThread = BaseStream<AgentThreadState>;

type SendMessageFn = (
  threadId: string,
  message: PromptInputMessage,
  ...args: unknown[]
) => void;

export type UseThreadStreamRealtimeResult = readonly [
  ExposedRealtimeThread,
  SendMessageFn,
  boolean,
  LiveToolEvent[],
  LiveToolEvent[],
  {
    pendingApprovals: PendingApproval[];
    resolveApproval: (requestId: string | number, accept: boolean) => void;
  },
];

export interface UseThreadStreamRealtimeOptions {
  threadId: string;
  /** Persisted "remember this model" picked by the page header. */
  model?: string;
  /** Default approval policy for new turns. Code page is permissive. */
  approvalPolicy?: ApprovalPolicy;
  /** Sandbox policy paired with the permission preset. */
  sandboxPolicy?: SandboxPolicy;
  /** Lifecycle callbacks derived from realtime conversation transitions. */
  onStart?: (threadId: string) => void;
  onFinish?: (state: AgentThreadState) => void;
  onToolEnd?: (event: ToolEndEvent) => void;
  /** Opaque settings bag surfaced to the server as turn context. */
  context?: unknown;
}

function reasoningEffortValue(value: unknown): ReasoningEffort | undefined {
  if (
    value === "minimal" ||
    value === "low" ||
    value === "medium" ||
    value === "high" ||
    value === "xhigh"
  ) {
    return value;
  }
  return undefined;
}

function toMillis(value: string | null | undefined): number {
  return toOptionalMillis(value) ?? Date.now();
}

function toOptionalMillis(
  value: string | null | undefined,
): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function liveStatus(status: Item["status"]): LiveToolEvent["status"] {
  if (status === "inProgress") return "running";
  if (status === "completed") return "done";
  return "error";
}

function finishFields(
  status: LiveToolEvent["status"],
  startedAt: number,
  turn: Turn,
  durationMs?: number | null,
): Pick<LiveToolEvent, "finishedAt" | "durationMs"> {
  if (status === "running" || status === "waiting_approval") return {};
  const finishedAt =
    durationMs != null && durationMs >= 0
      ? startedAt + durationMs
      : (toOptionalMillis(turn.completedAt) ?? startedAt);
  return {
    finishedAt,
    durationMs:
      durationMs != null && durationMs >= 0
        ? durationMs
        : Math.max(0, finishedAt - startedAt),
  };
}

function commandItemToLiveEvent(
  item: CommandExecutionItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: commandExecutionToolName(item),
    status,
    startedAt,
    iteration,
    input: commandExecutionInput(item),
    output: item.aggregatedOutput || undefined,
    ...finishFields(status, startedAt, turn),
  };
}

function mcpItemToLiveEvent(
  item: McpToolCallItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  // Sub-agent lifecycle markers: the bridge writes synthesised
  // ``mcpToolCall`` items whose ``tool`` field is one of the magic
  // marker strings (mirrors ``runtime.protocol.items.ItemMarker``).
  // Translate them into ``lifecycle`` events so the AgentWorkbench
  // panel can render a tile from the spawn moment instead of waiting
  // for the first ``sub_tool_*`` event.
  if (item.tool === "__subagent_spawned__") {
    const args = (item.arguments ?? {}) as Record<string, unknown>;
    const codename =
      typeof args.codename === "string" ? args.codename : undefined;
    const avatar = typeof args.avatar === "string" ? args.avatar : undefined;
    const role = typeof args.role === "string" ? args.role : undefined;
    const agentId =
      typeof args.agent_id === "string" ? args.agent_id : undefined;
    const parentToolUseId =
      typeof args.parent_tool_use_id === "string"
        ? args.parent_tool_use_id
        : typeof args.parentToolUseId === "string"
          ? args.parentToolUseId
          : undefined;
    return {
      id: item.id,
      name: "subagent",
      status: "running",
      lifecycle: "spawned",
      startedAt,
      iteration,
      agentId,
      subAgentRole: role,
      subagentCodename: codename,
      subagentAvatar: avatar,
      parentToolUseId,
      input: { ...args },
    };
  }
  if (item.tool === "__subagent_finished__") {
    const args = (item.arguments ?? {}) as Record<string, unknown>;
    const result = (item.result ?? {}) as Record<string, unknown>;
    const codename =
      typeof result.codename === "string" ? result.codename : undefined;
    const avatar =
      typeof result.avatar === "string" ? result.avatar : undefined;
    const role = typeof result.role === "string" ? result.role : undefined;
    const agentId =
      typeof result.agent_id === "string" ? result.agent_id : undefined;
    const parentToolUseId =
      typeof result.parent_tool_use_id === "string"
        ? result.parent_tool_use_id
        : typeof result.parentToolUseId === "string"
          ? result.parentToolUseId
          : typeof args.parent_tool_use_id === "string"
            ? args.parent_tool_use_id
            : typeof args.parentToolUseId === "string"
              ? args.parentToolUseId
              : undefined;
    const ok = result.ok !== false;
    const iterationCount =
      typeof result.iteration_count === "number"
        ? result.iteration_count
        : undefined;
    const filesTouched = Array.isArray(result.files_touched)
      ? result.files_touched.filter((p): p is string => typeof p === "string")
      : undefined;
    const durationS =
      typeof result.duration_s === "number" ? result.duration_s : undefined;
    const durationMs =
      durationS !== undefined
        ? Math.max(0, Math.round(durationS * 1000))
        : undefined;
    const finishedAt =
      durationMs !== undefined ? startedAt + durationMs : startedAt;
    return {
      id: item.id,
      name: "subagent",
      status: ok ? "done" : "error",
      lifecycle: "finished",
      startedAt,
      finishedAt,
      durationMs,
      iteration,
      agentId,
      subAgentRole: role,
      subagentCodename: codename,
      subagentAvatar: avatar,
      parentToolUseId,
      iterationCount,
      filesTouched,
      input: { ...result },
      output: result,
    };
  }
  return {
    id: item.id,
    name: item.tool ? `mcp:${item.tool}` : "mcp",
    status,
    startedAt,
    iteration,
    input: {
      server: item.server,
      tool: item.tool,
      arguments: item.arguments,
      progress: item.progress ?? null,
    },
    output: item.error
      ? item.progress
        ? { error: item.error, progress: item.progress }
        : { error: item.error }
      : item.progress
        ? { result: item.result, progress: item.progress }
        : item.result,
    ...finishFields(status, startedAt, turn, item.durationMs),
  };
}

function fileChangeItemToLiveEvent(
  item: FileChangeItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: "file_change",
    status,
    startedAt,
    iteration,
    input: {
      changes: item.changes,
      grantRoot: item.grantRoot,
    },
    output: item.changes,
    ...finishFields(status, startedAt, turn),
  };
}

function todoItemToLiveEvent(
  item: TodoListItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: "todo_write",
    status,
    startedAt,
    iteration,
    input: {
      items: item.plan.map((entry) => ({
        content: entry.title,
        status: entry.status,
      })),
      explanation: item.explanation,
    },
    output: item.plan,
    ...finishFields(status, startedAt, turn),
  };
}

function phaseStatusToTodoStatus(status: AgentPhaseSnapshot["status"]): string {
  if (status === "done") return "completed";
  if (status === "running" || status === "waiting_approval") {
    return "in_progress";
  }
  if (status === "error") return "error";
  return "pending";
}

function phaseSnapshotEventStatus(turn: Turn): LiveToolEvent["status"] {
  const phases = turn.phases ?? [];
  if (phases.some((phase) => phase.status === "error")) return "error";
  if (phases.some((phase) => phase.status === "waiting_approval")) {
    return "waiting_approval";
  }
  if (phases.some((phase) => phase.status === "running")) return "running";
  if (phases.length > 0 && phases.every((phase) => phase.status === "done")) {
    return "done";
  }
  return turn.status === "inProgress" ? "running" : "done";
}

function phaseSnapshotsToLiveEvent(
  turn: Turn,
  iteration: number,
): LiveToolEvent | null {
  const phases = turn.phases ?? [];
  if (phases.length === 0) return null;
  const startedAt = toMillis(turn.startedAt);
  const status = phaseSnapshotEventStatus(turn);
  return {
    id: `server-phases:${turn.id}`,
    name: "todo_write",
    status,
    startedAt,
    iteration,
    input: {
      items: phases.map((phase) => ({
        content: phase.title,
        activeForm: phase.title,
        status: phaseStatusToTodoStatus(phase.status),
        phaseId: phase.id,
        index: phase.index,
        total: phase.total,
        activeItemId: phase.activeItemId,
      })),
      workspaceFocus: turn.workspaceFocus,
      workbenchSnapshot: turn.workbenchSnapshot ?? null,
      source: "turn.phases",
    },
    output: phases,
    ...finishFields(status, startedAt, turn),
  };
}

function subagentItemToLiveEvent(
  item: SubagentItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: "subagent",
    status,
    startedAt,
    iteration,
    agentId: item.subagentId,
    subAgentRole: item.role ?? undefined,
    subagentCodename: item.codename ?? undefined,
    subagentAvatar: item.avatar ?? undefined,
    parentToolUseId: item.parentItemId ?? undefined,
    input: {
      subagentId: item.subagentId,
      role: item.role,
      name: item.name,
      parentItemId: item.parentItemId,
    },
    output: item.error ? { error: item.error } : item.summary,
    iterationCount: item.iterationCount ?? undefined,
    filesTouched: item.filesTouched,
    ...finishFields(status, startedAt, turn),
  };
}

function approvalItemToLiveEvent(
  item: ApprovalItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status: LiveToolEvent["status"] =
    item.decision === "pending" ? "waiting_approval" : liveStatus(item.status);
  return {
    id: item.targetItemId ?? item.id,
    name: item.method || "approval",
    status,
    startedAt,
    iteration,
    input: {
      requestId: item.requestId,
      method: item.method,
      params: item.params,
      decision: item.decision,
    },
    ...finishFields(status, startedAt, turn),
  };
}

function verificationItemToLiveEvent(
  item: VerificationItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: `verification:${item.kind}`,
    status,
    startedAt,
    iteration,
    input: {
      command: item.command,
      relatedFiles: item.relatedFiles,
      relatedChangeItemIds: item.relatedChangeItemIds,
    },
    output: {
      exitCode: item.exitCode,
      summary: item.summary,
      stdoutTail: item.stdoutTail,
      stderrTail: item.stderrTail,
    },
    ...finishFields(status, startedAt, turn),
  };
}

function artifactItemToLiveEvent(
  item: ArtifactItem,
  turn: Turn,
  iteration: number,
): LiveToolEvent {
  const startedAt = toMillis(item.createdAt);
  const status = liveStatus(item.status);
  return {
    id: item.id,
    name: "artifact",
    status,
    startedAt,
    iteration,
    input: {
      artifactId: item.artifactId,
      kind: item.kind,
      path: item.path,
      title: item.title,
      workspaceFocus: {
        itemId: item.id,
        view: item.kind === "image" ? "image" : "artifact",
        title: item.title ?? item.path,
        subtitle: item.path,
        previewUrl: item.previewUrl,
      },
    },
    output: {
      previewUrl: item.previewUrl,
      renderStatus: item.renderStatus,
      validationStatus: item.validationStatus,
    },
    ...finishFields(status, startedAt, turn),
  };
}

function itemToLiveEvent(
  item: Item,
  turn: Turn,
  iteration: number,
): LiveToolEvent | null {
  if (item.type === "commandExecution") {
    return commandItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "mcpToolCall") {
    return mcpItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "fileChange") {
    return fileChangeItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "todo-list") {
    return todoItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "subagent") {
    return subagentItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "approval") {
    return approvalItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "verification") {
    return verificationItemToLiveEvent(item, turn, iteration);
  }
  if (item.type === "artifact") {
    return artifactItemToLiveEvent(item, turn, iteration);
  }
  return null;
}

export function liveToolEventsFromConversation(
  conv: Conversation,
): LiveToolEvent[] {
  const itemEvents = conv.turns.flatMap((turn, turnIndex) => {
    const events = turn.items
      .map((item, itemIndex) =>
        itemToLiveEvent(item, turn, turnIndex + itemIndex + 1),
      )
      .filter((event): event is LiveToolEvent => event !== null);
    const phaseEvent = phaseSnapshotsToLiveEvent(
      turn,
      turnIndex + turn.items.length + 1,
    );
    return phaseEvent ? [...events, phaseEvent] : events;
  });
  return [
    ...itemEvents,
    ...conv.pendingApprovals.map((approval, index) =>
      approvalToLiveEvent(approval, conv.turns.length + index + 1),
    ),
  ];
}

export function liveToolEventsFromLastTurn(
  conv: Conversation,
): LiveToolEvent[] {
  const last = conv.turns[conv.turns.length - 1];
  const itemEvents = last
    ? last.items
        .map((item, index) => itemToLiveEvent(item, last, index + 1))
        .filter((event): event is LiveToolEvent => event !== null)
    : [];
  const phaseEvent = last
    ? phaseSnapshotsToLiveEvent(last, itemEvents.length + 1)
    : null;
  const events = phaseEvent ? [...itemEvents, phaseEvent] : itemEvents;
  return [
    ...events,
    ...conv.pendingApprovals.map((approval, index) =>
      approvalToLiveEvent(approval, events.length + index + 1),
    ),
  ];
}

function approvalToLiveEvent(
  approval: PendingApproval,
  iteration: number,
): LiveToolEvent {
  const params = approval.params as {
    itemId?: unknown;
    tool?: unknown;
    argsPreview?: unknown;
    detail?: unknown;
  };
  const tool =
    typeof params.tool === "string" && params.tool
      ? params.tool
      : "tool_approval";
  return {
    id: String(params.itemId || approval.requestId),
    name: tool,
    status: "waiting_approval",
    startedAt: toMillis(approval.createdAt),
    iteration,
    input: {
      tool,
      argsPreview: params.argsPreview,
      detail: params.detail,
      requestId: approval.requestId,
    },
  };
}

export function useThreadStreamRealtime(
  opts: UseThreadStreamRealtimeOptions,
): UseThreadStreamRealtimeResult {
  const {
    threadId,
    model,
    approvalPolicy,
    sandboxPolicy,
    onStart,
    onFinish,
    onToolEnd,
    context,
  } = opts;

  const realtime = useRealtimeThread({ threadId });
  const { state, startTurn, interrupt, resume, compact, resolveApproval } =
    realtime;
  const [isUploading, setIsUploading] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const permissionRuntime = useMemo(
    () =>
      permissionRuntimeConfig(
        (context as { permission_mode?: unknown } | null | undefined)
          ?.permission_mode,
      ),
    [context],
  );
  const effectiveApprovalPolicy =
    approvalPolicy ?? permissionRuntime.approvalPolicy;
  const effectiveSandboxPolicy =
    sandboxPolicy ?? permissionRuntime.sandboxPolicy;

  // Mapped conversation view. Re-derives only when
  // the underlying `state` object identity changes; the realtime
  // reducer already short-circuits when nothing changed, so this is
  // cheap.
  const mapped = useMemo<AgentThreadState>(
    () => conversationToAgentThreadState(state),
    [state],
  );
  const liveToolEvents = useMemo(
    () => liveToolEventsFromConversation(state),
    [state],
  );
  const lastTurnToolEvents = useMemo(
    () => liveToolEventsFromLastTurn(state),
    [state],
  );
  const approvalControls = useMemo(
    () => ({
      pendingApprovals: state.pendingApprovals,
      resolveApproval,
    }),
    [state.pendingApprovals, resolveApproval],
  );

  const isLoading = useMemo(() => conversationIsLoading(state), [state]);
  const realtimeError = useMemo(() => conversationLastError(state), [state]);
  const error = sendError ?? realtimeError;
  const streamingMessage = useMemo(
    () => conversationStreamingMessage(state),
    [state],
  );

  // Lifecycle callbacks (onStart / onFinish / onToolEnd).
  const wasLoadingRef = useRef(false);
  const seenToolIdsRef = useRef<Set<string>>(new Set());
  const callbacksRef = useRef({ onStart, onFinish, onToolEnd });
  useEffect(() => {
    callbacksRef.current = { onStart, onFinish, onToolEnd };
  }, [onStart, onFinish, onToolEnd]);

  useEffect(() => {
    // Edge: idle -> busy -> call onStart with the active thread id.
    if (!wasLoadingRef.current && isLoading) {
      try {
        callbacksRef.current.onStart?.(threadId || "");
      } catch (e) {
        swallow(e);
      }
    }
    // Edge: busy -> idle -> call onFinish with the final state.
    if (wasLoadingRef.current && !isLoading) {
      try {
        callbacksRef.current.onFinish?.(mapped);
      } catch (e) {
        swallow(e);
      }
    }
    wasLoadingRef.current = isLoading;
  }, [isLoading, threadId, mapped]);

  useEffect(() => {
    // Walk all items; when we see a just-completed tool we haven't
    // surfaced yet, fire onToolEnd. Cheap because the reducer keeps
    // object identity stable for items that didn't change.
    const cb = callbacksRef.current.onToolEnd;
    if (!cb) return;
    for (const turn of state.turns) {
      for (const item of turn.items) {
        if (
          (item.type === "commandExecution" || item.type === "mcpToolCall") &&
          item.status !== "inProgress" &&
          !seenToolIdsRef.current.has(item.id)
        ) {
          seenToolIdsRef.current.add(item.id);
          try {
            cb({
              name:
                item.type === "commandExecution"
                  ? commandExecutionToolName(item)
                  : "mcp",
              data: item,
            });
          } catch (e) {
            swallow(e);
          }
        }
      }
    }
  }, [state]);

  // Stable `stop` ref so callers can `useRef(thread.stop)` without
  // tearing on every render (the code page does this around L1195).
  const stopRef = useRef(() => {
    void interrupt();
  });
  stopRef.current = () => {
    void interrupt();
  };
  const stop = useCallback(() => stopRef.current(), []);

  const refresh = useCallback(() => resume(), [resume]);

  const exposedThread = useMemo(
    () =>
      ({
        messages: mapped.messages,
        streamingMessage,
        subgraphStreams: {},
        values: mapped,
        isLoading,
        isThreadLoading: false,
        error,
        stop,
        refresh,
        submit: () => {
          // ``submit`` is only called by the stream consumer's
          // internal plumbing; the realtime path routes through
          // ``sendMessage`` -> ``startTurn`` instead. Providing a no-op
          // keeps the BaseStream contract satisfied for the few places
          // that might introspect the shape.
        },
        threadId: threadId || null,
        compact,
      }) as ExposedRealtimeThread & { compact: typeof compact },
    [
      mapped,
      streamingMessage,
      isLoading,
      error,
      stop,
      refresh,
      threadId,
      compact,
    ],
  );

  const sendMessage = useCallback<SendMessageFn>(
    (_threadId, message) => {
      const text = (message?.text ?? "").trim();
      if (!text) return;
      void (async () => {
        setSendError(null);
        const effectiveThreadId =
          _threadId && _threadId !== "new" ? _threadId : threadId;
        const files = message.files ?? [];
        setIsUploading(files.length > 0);
        try {
          const attachments =
            effectiveThreadId && effectiveThreadId !== "new"
              ? await uploadPromptInputFiles(effectiveThreadId, files)
              : await fallbackFileAttachmentsAsync(files);
          const rawContext =
            context && typeof context === "object"
              ? (context as Record<string, unknown>)
              : {};
          const selectedMode =
            typeof rawContext.mode === "string" && rawContext.mode.trim()
              ? rawContext.mode
              : "code";
          const runtimeContext = {
            ...rawContext,
            mode: selectedMode,
            capability_mode:
              typeof rawContext.capability_mode === "string" &&
              rawContext.capability_mode.trim()
                ? rawContext.capability_mode
                : "code",
            code_mode:
              typeof rawContext.code_mode === "string" &&
              rawContext.code_mode.trim()
                ? rawContext.code_mode
                : "solo",
            permission_mode: permissionRuntime.mode,
            sandbox_mode: permissionRuntime.sandbox_mode,
            execution_environment: permissionRuntime.execution_environment,
          };
          const reasoningEffort = reasoningEffortValue(
            rawContext["reasoning_effort"],
          );
          const metadataContext = reasoningEffort
            ? { ...runtimeContext, reasoning_effort: reasoningEffort }
            : runtimeContext;
          setIsUploading(false);
          await startTurn({
            input: text,
            attachments,
            approvalPolicy: effectiveApprovalPolicy,
            sandboxPolicy: effectiveSandboxPolicy,
            ...(permissionRuntime.planningMode ? { planningMode: true } : {}),
            ...(model ? { model } : {}),
            ...(reasoningEffort ? { effort: reasoningEffort } : {}),
            metadata: {
              context: metadataContext,
            } as Record<string, unknown>,
          });
        } finally {
          setIsUploading(false);
        }
      })().catch((err) => {
        setSendError(
          err instanceof Error ? err.message : "Failed to send message",
        );
      });
    },
    [
      startTurn,
      effectiveApprovalPolicy,
      effectiveSandboxPolicy,
      model,
      context,
      permissionRuntime.mode,
      permissionRuntime.execution_environment,
      threadId,
    ],
  );

  return [
    exposedThread,
    sendMessage,
    isUploading,
    liveToolEvents,
    lastTurnToolEvents,
    approvalControls,
  ] as const;
}

async function uploadPromptInputFiles(
  threadId: string,
  fileParts: PromptInputMessage["files"],
): Promise<Record<string, unknown>[]> {
  if (fileParts.length === 0) return [];
  const files = (
    await Promise.all(fileParts.map((part) => promptInputFilePartToFile(part)))
  ).filter((file): file is File => file instanceof File);
  if (files.length === 0) return fallbackFileAttachments(fileParts);
  const result = await uploadFiles(threadId, files);

  // Hosted upload gives us a server-side path/URL. For image-typed
  // attachments we ALSO embed a base64 data URL so the backend can
  // build OpenAI image_url content blocks for vision models without
  // having to re-fetch the artifact.
  const fileByName = new Map<string, File>();
  for (const file of files) fileByName.set(file.name, file);
  const enriched = await Promise.all(
    result.files.map(async (uploaded) => {
      const base = uploadedFileToAttachment(uploaded);
      const file = fileByName.get(uploaded.filename);
      if (!file || !isImageMime(file.type)) return base;
      const dataUrl = await readFileAsDataUrl(file).catch(() => null);
      return dataUrl
        ? { ...base, mediaType: file.type, data_url: dataUrl }
        : base;
    }),
  );
  return enriched;
}

function uploadedFileToAttachment(
  file: UploadedFileInfo,
): Record<string, unknown> {
  return {
    filename: file.filename,
    size: file.size,
    path: file.path,
    virtual_path: file.virtual_path,
    artifact_url: file.artifact_url,
    extension: file.extension,
    modified: file.modified,
  };
}

function fallbackFileAttachments(
  fileParts: PromptInputMessage["files"],
): Record<string, unknown>[] {
  return fileParts.map((part) => ({
    filename: part.filename,
    mediaType: part.mediaType,
    url: part.url,
  }));
}

/**
 * Variant of fallbackFileAttachments used when the runtime hasn't
 * created the thread yet. We can't upload to the artifact store, but
 * we CAN base64-encode any image attachments inline so the model sees
 * them on the very first turn.
 */
async function fallbackFileAttachmentsAsync(
  fileParts: PromptInputMessage["files"],
): Promise<Record<string, unknown>[]> {
  return Promise.all(
    fileParts.map(async (part) => {
      const base: Record<string, unknown> = {
        filename: part.filename,
        mediaType: part.mediaType,
        url: part.url,
      };
      if (!isImageMime(part.mediaType)) return base;
      const file = await promptInputFilePartToFile(part);
      if (!(file instanceof File)) return base;
      const dataUrl = await readFileAsDataUrl(file).catch(() => null);
      return dataUrl ? { ...base, data_url: dataUrl } : base;
    }),
  );
}

function isImageMime(mediaType: string | undefined | null): boolean {
  return typeof mediaType === "string" && mediaType.toLowerCase().startsWith("image/");
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      if (typeof result === "string") resolve(result);
      else reject(new Error("FileReader returned non-string"));
    };
    reader.onerror = () =>
      reject(reader.error ?? new Error("FileReader failed"));
    reader.readAsDataURL(file);
  });
}
