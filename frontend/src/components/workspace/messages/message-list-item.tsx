import type { Message } from "@/core/api/types";
import type { CoworkRoomMessage } from "@/core/cowork";
import {
  FileIcon,
  GitForkIcon,
  Loader2Icon,
  PencilIcon,
  RefreshCwIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import {
  memo,
  useCallback,
  useMemo,
  type ComponentProps,
  type ImgHTMLAttributes,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { Loader } from "@/components/ai-elements/loader";
import {
  Message as AIElementMessage,
  MessageContent as AIElementMessageContent,
  MessageResponse as AIElementMessageResponse,
} from "@/components/ai-elements/message";
import { Task, TaskTrigger } from "@/components/ai-elements/task";
import { Badge } from "@/components/ui/badge";
import { resolveArtifactURL } from "@/core/artifacts/utils";
import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useForkThread } from "@/core/threads/hooks";
import {
  extractContentFromMessage,
  extractTextFromMessage,
  parseUploadedFiles,
  stripInternalToolProtocol,
  stripLeakedRendererMarkup,
  stripUploadedFilesTag,
  type FileInMessage,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { useHumanMessagePlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";
import {
  CoworkRoomMessageActions,
  type CoworkRoomMessageActionsProps,
} from "../collab";
import { emitOpenAgentWorkbench } from "../agent-workbench-events";
import {
  ExecutionPlanReview,
  isExecutionPlanMessage,
  getExecutionPlanFromMessage,
} from "../execution-plan-review";
import {
  TaskProgressChecklist,
  isTaskChecklistMessage,
  getChecklistPlanFromMessage,
} from "../task-progress-checklist";
import { normalizeExecutionPlan } from "../execution-plan-utils";

import { MarkdownContent } from "./markdown-content";
import { useThreadStreaming, useThreadValues } from "./context";
import { useStreamingTextBuffer } from "@/hooks/use-streaming-text-buffer";
import { ClarificationChoiceCard } from "./clarification-choice-card";
import { GroundingChip } from "./grounding-chip";
import { useConversationDetailLevel } from "./use-conversation-detail-level";
import { extractClarificationQuestionnaire } from "../clarification-questionnaire";

export interface MessageListProjectActions extends Omit<
  CoworkRoomMessageActionsProps,
  "message"
> {
  /** Metadata from the hidden room mirror, keyed by source_message_id. */
  messageMetadataBySourceId?: Record<string, CoworkRoomMessage["metadata"]>;
}

/** Build the hidden Team Room copy that gives a canonical thread message a
 * stable Project OS action anchor without rendering the text twice. */
export function threadMessageToCoworkRoomMessage(
  message: Message,
  threadId: string | null,
  messageIndex: number | undefined,
  metadataBySourceId: MessageListProjectActions["messageMetadataBySourceId"],
): CoworkRoomMessage {
  const stableMessageId = message.id
    ? String(message.id)
    : `${threadId ?? "thread"}:${messageIndex ?? "message"}`;
  const sourceMessageId = `thread:${stableMessageId}`;
  return {
    seq: -1,
    participant_id: "human",
    display_name: "我",
    text: extractTextFromMessage(message),
    metadata: metadataBySourceId?.[sourceMessageId] ?? {
      source_message_id: sourceMessageId,
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Format an ISO timestamp as local HH:mm, returning "" when unparseable. */
function formatMessageTime(createdAt: string): string {
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Small muted HH:mm label shown under a message bubble. Visible on hover of
 * the message, or always when the conversation detail level is "high".
 */
export function MessageTimestamp({
  createdAt,
  alwaysVisible,
  align = "start",
}: {
  createdAt?: string;
  alwaysVisible?: boolean;
  align?: "start" | "end";
}) {
  if (!createdAt) return null;
  const formatted = formatMessageTime(createdAt);
  if (!formatted) return null;
  return (
    <span
      className={cn(
        "text-micro text-muted-foreground/60 select-none",
        align === "end" ? "self-end" : "self-start",
        alwaysVisible
          ? "opacity-100"
          : "opacity-0 transition-opacity group-hover/conversation-message:opacity-100",
      )}
    >
      {formatted}
    </span>
  );
}

const INTERNAL_TRACE_DETAILS_RE =
  /^\s*<details\b[^>]*>\s*<summary\b[^>]*>\s*[^<]*(?:ReAct|\u8f68\u8ff9)[^<]*<\/summary>[\s\S]*?<\/details>\s*/i;

const INLINE_THINKING_DETAILS_CAPTURE_RE =
  /^\s*<details\b[^>]*>\s*<summary\b[^>]*>\s*[^<]*(?:\u601d\u8003\u8fc7\u7a0b|Thinking)[^<]*<\/summary>([\s\S]*?)<\/details>\s*/i;

const LEGACY_SUBAGENT_BUDGET_PLACEHOLDER_RE =
  /^\s*(?:\[[^\]\n]+\]\s*)?\(sub-agent exceeded token budget \d+\/\d+\)\s*$/i;

function stripInternalTraceDetails(content: string): string {
  let next = content;
  for (let i = 0; i < 4; i += 1) {
    const stripped = next.replace(INTERNAL_TRACE_DETAILS_RE, "");
    if (stripped === next) break;
    next = stripped.trimStart();
  }
  return next;
}

function stripLegacySubagentBudgetPlaceholder(content: string): string {
  return LEGACY_SUBAGENT_BUDGET_PLACEHOLDER_RE.test(content) ? "" : content;
}

function splitInlineThinkingDetails(content: string) {
  const match = content.match(INLINE_THINKING_DETAILS_CAPTURE_RE);
  if (!match) {
    return { content, hadInlineThinking: false, thinkingContent: null };
  }
  const fullMatch = match[0] ?? "";
  const thinkingContent = (match[1] ?? "").trim();
  return {
    content: content.slice(fullMatch.length).trimStart(),
    hadInlineThinking: true,
    thinkingContent: thinkingContent || null,
  };
}

/**
 * Cheap pre-filter for the streaming hot path.
 *
 * The full protocol-cleaning chain (stripInternalToolProtocol →
 * stripInternalTraceDetails → splitInlineThinkingDetails → …) is a dozen
 * whole-string regex passes — fine per settled message, wasteful when it
 * re-runs on every streamed token. Every pattern in that chain requires at
 * least one of the characters below (protocol XML/fence markers, ReAct
 * field headers, guard boilerplate, and the ASCII opening paren of the
 * legacy ``(sub-agent exceeded token budget N/N)`` placeholder — its
 * optional ``[...]`` prefix already matches via ``[``). A reply containing
 * none of them is guaranteed to pass through every stage unchanged, so we
 * can skip the entire chain. First-mark test is O(n) with zero allocation.
 */
const PROTOCOL_FIRST_MARK_RE = /[<`TAFONS质量（({[]/;

export function containsProtocolMarkers(content: string): boolean {
  return PROTOCOL_FIRST_MARK_RE.test(content);
}

function getReasoningSummary(message: Message): string | null {
  const additional = isRecord(message.additional_kwargs)
    ? message.additional_kwargs
    : null;
  const octopus = isRecord(additional?.octopus) ? additional.octopus : null;
  for (const source of [additional, octopus]) {
    if (!source) continue;
    const value = source.public_reasoning_summary;
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return null;
}

function buildReasoningSummary(message: Message): string | null {
  // Legacy snapshots used this explicit field for readable reasoning
  // summaries. It remains a reasoning disclosure and is never promoted to
  // normal commentary. Provider aliases are intentionally not guessed here.
  return getReasoningSummary(message);
}

function cleanClipboardText(value: string): string {
  return stripLeakedRendererMarkup(stripInternalToolProtocol(value), {
    trim: true,
  });
}

export function messageClipboardText(message: Message): string {
  const rawContent = extractContentFromMessage(message) ?? "";
  if (message.type === "human") {
    return stripUploadedFilesTag(rawContent).trim();
  }

  const displayContent = splitInlineThinkingDetails(
    stripLegacySubagentBudgetPlaceholder(stripInternalTraceDetails(rawContent)),
  ).content;
  const visibleContent =
    extractClarificationQuestionnaire(displayContent)?.visibleContent ??
    displayContent;
  const cleanedVisible = cleanClipboardText(visibleContent);
  if (cleanedVisible) return cleanedVisible;

  // Preserve the legacy explicit summary in clipboard output without ever
  // falling back to raw provider reasoning or guessed alias fields.
  return cleanClipboardText(getReasoningSummary(message) ?? "");
}

type MarkdownRenderProps = Pick<
  ComponentProps<typeof MarkdownContent>,
  "components" | "rehypePlugins" | "chatFontSize"
>;

function SegmentedReasoningPanel({
  publicThinkingSummary,
  isLoading,
  messageId,
}: MarkdownRenderProps & {
  publicThinkingSummary?: string | null;
  isLoading: boolean;
  messageId?: string;
}) {
  const replyThinking = publicThinkingSummary?.trim() || null;
  if (!replyThinking) return null;
  const summary = replyThinking.replace(/\s+/g, " ").trim();

  return (
    <button
      type="button"
      onClick={() =>
        emitOpenAgentWorkbench({
          tab: "agent",
          eventId: messageId,
          eventKind: "thinking",
          view: "summary",
          processEvent: {
            kind: "thinking",
            summary,
            detail: replyThinking,
            status: isLoading ? "running" : "done",
            count: 1,
          },
        })
      }
      className="group/thinking-row mb-1 flex w-full min-w-0 items-center gap-1.5 rounded-full border border-border/50 bg-muted/40 px-2.5 py-1 text-left text-xs leading-4 text-muted-foreground/70 transition-colors hover:text-muted-foreground hover:border-border"
      data-process-event-id={messageId}
      data-process-event-kind="thinking"
      data-testid="assistant-thinking-event"
      aria-label={summary}
    >
      <span
        className={cn(
          "inline-flex size-1.5 shrink-0 rounded-full bg-muted-foreground/35",
          isLoading && "animate-pulse bg-primary/55",
        )}
      />
      <span className="min-w-0 flex-1 truncate">{summary}</span>
    </button>
  );
}

// Wrapped in React.memo with chatFontSize as an explicit prop.
// Previously, MarkdownContent called useLocalSettings() internally to
// pick up the active chat font size. memo() here blocked prop-change-less
// re-renders, which meant settings changes (driven only by useState inside
// the hook) never reached the memoized subtree. Now we pass chatFontSize
// as a prop through to MarkdownContent, so memo's shallow comparison
// correctly detects font-size changes and re-renders only when needed.
export const MessageListItem = memo(function MessageListItem({
  className,
  message,
  isLoading,
  chatFontSize,
  suppressReasoningPanel = false,
  enableClarificationActions = false,
  isLastMessage = true,
  messageIndex,
  afterContent,
  projectMessageActions,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  chatFontSize?: "small" | "medium" | "large";
  suppressReasoningPanel?: boolean;
  enableClarificationActions?: boolean;
  isLastMessage?: boolean;
  messageIndex?: number;
  afterContent?: ReactNode;
  /** Project actions exposed on human bubbles in a bound project group. */
  projectMessageActions?: MessageListProjectActions;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const forkThread = useForkThread();
  const isHuman = message.type === "human";
  const messageMetadata =
    message.type === "ai"
      ? (message.additional_kwargs as Record<string, unknown> | undefined)
      : undefined;
  const assistantIsSettledAnswer =
    message.type === "ai" &&
    messageMetadata?.message_kind !== "commentary" &&
    messageMetadata?.public_progress !== true &&
    messageMetadata?.response_state !== "interrupted" &&
    messageMetadata?.response_state !== "failed" &&
    messageMetadata?.run_status !== "streaming";
  const clipboardText = useMemo(() => messageClipboardText(message), [message]);
  const showMessageActions =
    !isLoading &&
    (isHuman ||
      (assistantIsSettledAnswer && clipboardText.length > 0 && isLastMessage));
  const params = useParams();
  const threadIdForFeedback = params.threadId ?? params.thread_id ?? null;
  const { messageMetadataBySourceId, ...coworkProjectMessageActions } =
    projectMessageActions ?? {};
  const roomMessageForProjectActions = useMemo<CoworkRoomMessage | null>(() => {
    if (!isHuman || !projectMessageActions) return null;
    return threadMessageToCoworkRoomMessage(
      message,
      threadIdForFeedback,
      messageIndex,
      messageMetadataBySourceId,
    );
  }, [
    isHuman,
    message,
    messageIndex,
    messageMetadataBySourceId,
    projectMessageActions,
    threadIdForFeedback,
  ]);
  const { level } = useConversationDetailLevel();
  const createdAt = (
    message.additional_kwargs as { created_at?: string } | undefined
  )?.created_at;
  const submitFeedback = useCallback(
    async (sentiment: "liked" | "disliked") => {
      const content =
        typeof message.content === "string" ? message.content : "";
      try {
        const res = await fetch(`${getBackendBaseURL()}/api/feedback`, {
          method: "POST",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({
            sentiment,
            message_id: message.id ?? null,
            thread_id: threadIdForFeedback,
            content_preview: content.slice(0, 400),
          }),
        });
        if (!res.ok) {
          throw new Error(`feedback http ${res.status}`);
        }

        toast.success(
          sentiment === "liked"
            ? t.conversation.feedbackThanks
            : t.conversation.feedbackRecorded,
        );
      } catch {
        toast.error(t.conversation.feedbackFailed);
      }
    },
    [message.content, message.id, threadIdForFeedback, t.conversation],
  );

  return (
    <AIElementMessage
      className={cn("group/conversation-message relative w-full", className)}
      from={isHuman ? "user" : "assistant"}
    >
      <MessageContent
        // Human bubbles used to pass `w-fit` here. Combined with the inner
        // AIElementMessageContent's own `w-fit max-w-full min-w-0`, the
        // outer `w-fit` could collapse the flex item's min-width to 0 and
        // push text onto one-character-per-line because the flex item
        // couldn't break in the middle of a 2-char string.
        // Using `max-w-[85%]` instead keeps the right-aligned cap but
        // gives the flex child room to stay on a single horizontal line.
        className={isHuman ? "max-w-[85%] items-end" : "w-full"}
        message={message}
        isLoading={isLoading}
        chatFontSize={chatFontSize}
        suppressReasoningPanel={suppressReasoningPanel}
        enableClarificationActions={enableClarificationActions}
      />
      <MessageTimestamp
        createdAt={createdAt}
        alwaysVisible={level === "high"}
        align={isHuman ? "end" : "start"}
      />
      {afterContent}
      {showMessageActions && (
        <div
          className={cn(
            "flex items-center gap-1.5 text-foreground/60",
            isHuman
              ? "pointer-events-none absolute top-full right-0 z-20 mt-0.5 w-auto justify-end rounded-lg bg-background/90 px-1 py-0.5 opacity-0 shadow-[var(--shadow-xs)] transition-opacity group-hover/conversation-message:pointer-events-auto group-hover/conversation-message:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100"
              : "mt-2 w-full",
          )}
        >
          {message.type === "ai" && (
            <>
              <button
                onClick={() => {
                  void submitFeedback("liked");
                }}
                className="inline-flex size-7 items-center justify-center rounded-lg text-foreground/60 transition-all duration-base hover:bg-success/10 hover:text-success focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 dark:hover:text-success"
                title={t.conversation.goodResponse}
                aria-label={t.conversation.goodResponse}
              >
                <ThumbsUpIcon className="size-4" />
              </button>
              <button
                onClick={() => {
                  void submitFeedback("disliked");
                }}
                className="inline-flex size-7 items-center justify-center rounded-lg text-foreground/60 transition-all duration-base hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45 dark:hover:text-destructive"
                title={t.conversation.badResponse}
                aria-label={t.conversation.badResponse}
              >
                <ThumbsDownIcon className="size-4" />
              </button>
            </>
          )}
          <CopyButton
            clipboardData={clipboardText}
            size="icon-sm"
            className="size-7 rounded-lg border-0 bg-transparent p-0 text-foreground/60 shadow-none transition-colors duration-base hover:bg-muted/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/45"
          />
          {roomMessageForProjectActions && projectMessageActions ? (
            <CoworkRoomMessageActions
              {...coworkProjectMessageActions}
              message={roomMessageForProjectActions}
              className={cn("min-h-0", projectMessageActions.className)}
            />
          ) : null}
          {threadIdForFeedback != null && messageIndex != null ? (
            <button
              onClick={() => {
                forkThread.mutate(
                  {
                    threadId: threadIdForFeedback,
                    atMessageIndex: messageIndex,
                  },
                  {
                    onSuccess: (result) => {
                      toast.success(t.conversation.forkedThread);
                      navigate(`/workspace/realtime/${result.thread_id}`);
                    },
                    onError: () => {
                      toast.error(t.conversation.forkFailed);
                    },
                  },
                );
              }}
              className="inline-flex size-7 items-center justify-center rounded-lg text-foreground/60 transition-all duration-base hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45"
              title={t.conversation.forkFromHere}
              aria-label={t.conversation.forkFromHere}
            >
              <GitForkIcon className="size-4" />
            </button>
          ) : null}
          {message.type === "ai" ? (
            <button
              onClick={() => {
                window.dispatchEvent(
                  new CustomEvent("octopus:regenerate", {
                    detail: { threadId: threadIdForFeedback },
                  }),
                );
              }}
              className="inline-flex size-7 items-center justify-center rounded-lg text-foreground/60 transition-all duration-base hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/45"
              title={t.conversation.regenerateResponse}
              aria-label={t.conversation.regenerateResponse}
            >
              <RefreshCwIcon className="size-4" />
            </button>
          ) : (
            <button
              onClick={() => {
                const text = extractTextFromMessage(message);
                window.dispatchEvent(
                  new CustomEvent("octopus:edit-message", {
                    detail: { text, threadId: threadIdForFeedback },
                  }),
                );
              }}
              className="inline-flex size-6 items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-base hover:bg-muted/60 hover:text-foreground"
              title={t.conversation.editResend}
              aria-label={t.conversation.editResend}
            >
              <PencilIcon className="size-3.5" />
            </button>
          )}
        </div>
      )}
    </AIElementMessage>
  );
});

/**
 * Custom image component that handles artifact URLs
 */
function MessageImage({
  src,
  alt,
  threadId,
  maxWidth: _maxWidth = "90%",
  ...props
}: React.ImgHTMLAttributes<HTMLImageElement> & {
  threadId: string;
  maxWidth?: string;
}) {
  if (!src) return null;

  const imgClassName = "overflow-hidden rounded-lg max-w-[90%]";

  if (typeof src !== "string") {
    return <img className={imgClassName} src={src} alt={alt} {...props} />;
  }

  const url = src.startsWith("/mnt/") ? resolveArtifactURL(src, threadId) : src;

  return (
    <a href={url} target="_blank" rel="noopener noreferrer">
      <img className={imgClassName} src={url} alt={alt} {...props} />
    </a>
  );
}

function MessageContent_({
  className,
  message,
  isLoading = false,
  chatFontSize,
  suppressReasoningPanel = false,
  enableClarificationActions = false,
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  chatFontSize?: "small" | "medium" | "large";
  suppressReasoningPanel?: boolean;
  enableClarificationActions?: boolean;
}) {
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const humanMessagePlugins = useHumanMessagePlugins();
  const { t } = useI18n();
  const isHuman = message.type === "human";
  const params = useParams();
  const thread_id = params.threadId ?? params.thread_id;
  const { streamingMessage } = useThreadStreaming();
  const { values } = useThreadValues();

  // useRehypeSplitWordsIntoSpans now returns the full plugin stack including
  // rehypeRaw and rehypeKatex, so we don't need to add them again.
  const allRehypePlugins = rehypePlugins;

  // The typing cursor belongs only to the message actively receiving text,
  // never to older messages that share the thread-level loading state.
  const isCurrentlyStreaming = isLoading && message.id === streamingMessage?.id;

  const components = useMemo(
    () => ({
      img: (props: ImgHTMLAttributes<HTMLImageElement>) => (
        <MessageImage {...props} threadId={thread_id ?? ""} maxWidth="90%" />
      ),
    }),
    [thread_id],
  );

  const rawContent = extractContentFromMessage(message);
  const files = useMemo(() => {
    const files = message.additional_kwargs?.files;
    if (!Array.isArray(files) || files.length === 0) {
      if (rawContent.includes("<uploaded_files>")) {
        // If the content contains the <uploaded_files> tag, we return the parsed files from the content for backward compatibility.
        return parseUploadedFiles(rawContent);
      }
      return null;
    }
    return files as FileInMessage[];
  }, [message.additional_kwargs?.files, rawContent]);

  // User messages can carry attachments in additional_kwargs.attachments
  // (research files used to go through .files, but images now ride this
  // separate channel so we can fold them into multimodal content arrays).
  const attachments = useMemo(() => {
    const raw = message.additional_kwargs?.attachments;
    if (!Array.isArray(raw) || raw.length === 0) return null;
    return raw as Array<{
      filename?: string;
      mediaType?: string;
      data_url?: string;
      url?: string;
      artifact_url?: string;
    }>;
  }, [message.additional_kwargs?.attachments]);

  const displayContentState = useMemo(() => {
    if (isHuman) {
      return {
        content: rawContent ? stripUploadedFilesTag(rawContent) : "",
        hadInlineThinking: false,
        thinkingContent: null,
      };
    }
    const source = rawContent ?? "";
    // Streaming fast path: skip the whole protocol-cleaning regex chain for
    // content that contains none of the protocol first-marks (see
    // containsProtocolMarkers). The chain is idempotent, so settled
    // messages and marked streaming content still get the full treatment.
    if (!containsProtocolMarkers(source)) {
      return {
        content: source,
        hadInlineThinking: false,
        thinkingContent: null,
      };
    }
    return splitInlineThinkingDetails(
      stripInternalToolProtocol(
        stripLegacySubagentBudgetPlaceholder(stripInternalTraceDetails(source)),
      ),
    );
  }, [rawContent, isHuman]);
  const contentToDisplay = displayContentState.content;
  const structuredClarification = useMemo(
    () =>
      isHuman ? null : extractClarificationQuestionnaire(contentToDisplay),
    [contentToDisplay, isHuman],
  );
  const visibleContentToDisplay =
    structuredClarification?.visibleContent ?? contentToDisplay;
  // Body typewriter (WorkBuddy-style buffer playback): while this message is
  // actively receiving streamed tokens, play the content back at a smooth
  // tick rate instead of re-rendering markdown on every delta. When the
  // stream ends (`enabled` flips off), the short remaining tail is drained
  // with a bounded delay before the complete source is shown. Guard against
  // the target text
  // shrinking mid-stream (e.g. a draft being replaced): if the buffer ever
  // exceeds the target, fall back to the source text directly.
  const bufferedBody = useStreamingTextBuffer({
    targetText: visibleContentToDisplay,
    enabled: isCurrentlyStreaming,
    resetKey: message.id,
  });
  const renderedBody =
    bufferedBody.length <= visibleContentToDisplay.length
      ? bufferedBody
      : visibleContentToDisplay;
  const messageHasToolCalls =
    !isHuman &&
    Array.isArray((message as { tool_calls?: unknown[] }).tool_calls) &&
    ((message as { tool_calls?: unknown[] }).tool_calls?.length ?? 0) > 0;
  const publicThinkingSummary = useMemo(() => {
    if (isHuman) return null;
    return buildReasoningSummary(message);
  }, [isHuman, message]);
  const hasVisibleBody = Boolean(
    visibleContentToDisplay.trim() ||
    structuredClarification ||
    publicThinkingSummary ||
    (files?.length ?? 0) > 0,
  );
  const responseState = (
    message.additional_kwargs as { response_state?: unknown } | undefined
  )?.response_state;
  const legacyRunStatus = (
    message.additional_kwargs as { run_status?: unknown } | undefined
  )?.run_status;
  const interruptReason = (
    message.additional_kwargs as { interrupt_reason?: unknown } | undefined
  )?.interrupt_reason;
  const showInterruptedReceipt =
    responseState === "interrupted" ||
    (legacyRunStatus === "streaming" && hasVisibleBody);
  const showPausedReceipt = responseState === "paused";
  const showCancelledReceipt = responseState === "cancelled";
  const filesList =
    files && files.length > 0 && thread_id ? (
      <RichFilesList files={files} threadId={thread_id} />
    ) : null;

  const attachmentsList = useMemo(() => {
    if (!attachments) return null;
    const images = attachments.filter((att) => {
      const mt = (att.mediaType ?? "").toLowerCase();
      const url = att.data_url ?? att.url ?? att.artifact_url ?? "";
      return mt.startsWith("image/") || url.startsWith("data:image/");
    });
    if (images.length === 0) return null;
    return (
      <div className="mb-2 flex flex-wrap justify-end gap-2">
        {images.map((att, idx) => {
          const src = att.data_url || att.url || att.artifact_url || "";
          if (!src) return null;
          return (
            <a
              key={`att-${idx}-${att.filename ?? idx}`}
              href={src}
              target="_blank"
              rel="noopener noreferrer"
              className="block overflow-hidden rounded-lg border border-border-subtle"
            >
              <img
                src={src}
                alt={att.filename ?? t.message.attachmentFallback}
                className="h-32 w-auto max-w-60 object-cover"
              />
            </a>
          );
        })}
      </div>
    );
  }, [attachments, t.message.attachmentFallback]);

  // Uploading state: mock AI message shown while files upload
  if (message.additional_kwargs?.element === "task") {
    return (
      <AIElementMessageContent className={className}>
        <Task defaultOpen={false}>
          <TaskTrigger title="">
            <div className="text-muted-foreground flex w-full cursor-default items-center gap-2 text-sm select-none">
              <Loader className="size-4" />
              <span>{visibleContentToDisplay}</span>
            </div>
          </TaskTrigger>
        </Task>
      </AIElementMessageContent>
    );
  }

  // Lightweight task checklist "" auto-mode plan (no approval needed)
  if (isTaskChecklistMessage(message)) {
    const planFromMessage = getChecklistPlanFromMessage(message);
    const livePlan = normalizeExecutionPlan(values?.execution_plan);
    const plan =
      livePlan &&
      planFromMessage &&
      livePlan.plan_id === planFromMessage.plan_id
        ? livePlan
        : planFromMessage;

    if (plan) {
      return (
        <AIElementMessageContent className={className}>
          <TaskProgressChecklist plan={plan} />
        </AIElementMessageContent>
      );
    }
  }

  // Execution plan review card "" shown inline when the middleware generates a plan
  if (isExecutionPlanMessage(message) && thread_id) {
    const planFromMessage = getExecutionPlanFromMessage(message);
    // Prefer the live plan from thread state (updated in real-time) over the
    // static plan snapshot embedded in the message.
    const livePlan = normalizeExecutionPlan(values?.execution_plan);
    const plan =
      livePlan &&
      planFromMessage &&
      livePlan.plan_id === planFromMessage.plan_id
        ? livePlan
        : planFromMessage;

    if (plan) {
      return (
        <AIElementMessageContent className={className}>
          <ExecutionPlanReview plan={plan} threadId={thread_id} />
        </AIElementMessageContent>
      );
    }
  }

  // Reasoning-only AI message (no main response content yet) "" just show
  // the collapsible thinking panel on its own.
  if (
    !suppressReasoningPanel &&
    !isHuman &&
    publicThinkingSummary &&
    !rawContent
  ) {
    return (
      <AIElementMessageContent className={className}>
        <SegmentedReasoningPanel
          publicThinkingSummary={publicThinkingSummary}
          isLoading={isLoading}
          messageId={message.id}
          rehypePlugins={allRehypePlugins}
          components={components}
          chatFontSize={chatFontSize}
        />
      </AIElementMessageContent>
    );
  }

  // AI message with BOTH reasoning and a final response "" render the
  // thinking panel above the response so users can still drill into the
  // model's chain of thought after the answer arrives. Defaults to
  // collapsed so the thinking trace doesn't dominate the visible
  // response; users click the trigger to expand and review.
  // Thinking: open while streaming, auto-collapse when done
  const segmentedReasoningPanel =
    !suppressReasoningPanel &&
    !isHuman &&
    !messageHasToolCalls &&
    publicThinkingSummary ? (
      <SegmentedReasoningPanel
        publicThinkingSummary={publicThinkingSummary}
        isLoading={isLoading}
        messageId={message.id}
        rehypePlugins={allRehypePlugins}
        components={components}
        chatFontSize={chatFontSize}
      />
    ) : null;
  if (isHuman) {
    const messageResponse = visibleContentToDisplay ? (
      <AIElementMessageResponse
        remarkPlugins={humanMessagePlugins.remarkPlugins}
        rehypePlugins={humanMessagePlugins.rehypePlugins}
        components={components}
      >
        {visibleContentToDisplay}
      </AIElementMessageResponse>
    ) : null;
    return (
      // items-end right-aligns the inner bubble; flex-col keeps files
      // stacked above the message body. Removing the explicit `w-fit` on
      // AIElementMessageContent lets it inherit its own default width
      // behaviour (`w-fit max-w-[85%]` via the .is-user group selector)
      // without compounding with an outer `w-fit` on the wrapper.
      <div className={cn("ml-auto flex flex-col items-end gap-2", className)}>
        {filesList}
        {attachmentsList}
        {messageResponse && (
          <AIElementMessageContent>{messageResponse}</AIElementMessageContent>
        )}
      </div>
    );
  }

  return (
    <AIElementMessageContent className={className}>
      {filesList}
      {attachmentsList}
      <GroundingChip message={message} />
      {segmentedReasoningPanel}
      {visibleContentToDisplay.trim() && (
        <div className="relative">
          <MarkdownContent
            content={renderedBody}
            isLoading={isLoading}
            rehypePlugins={allRehypePlugins}
            className={cn(
              "my-3",
              isCurrentlyStreaming && "kimi-streaming-tail",
            )}
            components={components}
            chatFontSize={chatFontSize}
          />
        </div>
      )}
      <ClarificationChoiceCard
        content={contentToDisplay}
        active={enableClarificationActions && !isCurrentlyStreaming}
        messageId={message.id}
      />
      {/* Terminal receipt for an interrupted answer. The incomplete draft is
          intentionally absent from the transcript; tools and checkpoints
          remain available through the process workbench. Legacy persisted
          `run_status=streaming` messages retain the same honest receipt. */}
      {!isCurrentlyStreaming && showInterruptedReceipt && (
        <div className="mt-2 text-xs leading-5 text-muted-foreground/70">
          {typeof interruptReason === "string" && interruptReason.trim()
            ? `${t.conversation.interruptedMessage}（原因：${interruptReason}）`
            : t.conversation.interruptedMessage}
        </div>
      )}
      {!isCurrentlyStreaming && showPausedReceipt && (
        <div className="mt-2 rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {typeof interruptReason === "string" && interruptReason.trim()
            ? `${t.conversation.pausedMessage}（${interruptReason}）`
            : t.conversation.pausedMessage}
        </div>
      )}
      {!isCurrentlyStreaming && showCancelledReceipt && (
        <div className="mt-2 text-xs leading-5 text-muted-foreground/70">
          {t.conversation.cancelledMessage}
        </div>
      )}
    </AIElementMessageContent>
  );
}

/**
 * Get file extension and check helpers
 */
const getFileExt = (filename: string) =>
  filename.split(".").pop()?.toLowerCase() ?? "";

const FILE_TYPE_MAP: Record<string, string> = {
  json: "JSON",
  csv: "CSV",
  txt: "TXT",
  md: "Markdown",
  py: "Python",
  js: "JavaScript",
  ts: "TypeScript",
  tsx: "TSX",
  jsx: "JSX",
  html: "HTML",
  css: "CSS",
  xml: "XML",
  yaml: "YAML",
  yml: "YAML",
  pdf: "PDF",
  png: "PNG",
  jpg: "JPG",
  jpeg: "JPEG",
  gif: "GIF",
  svg: "SVG",
  zip: "ZIP",
  tar: "TAR",
  gz: "GZ",
};

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "svg", "bmp"];

function getFileTypeLabel(filename: string, fileFallback: string): string {
  const ext = getFileExt(filename);
  return FILE_TYPE_MAP[ext] ?? (ext.toUpperCase() || fileFallback);
}

function isImageFile(filename: string): boolean {
  return IMAGE_EXTENSIONS.includes(getFileExt(filename));
}

/**
 * Format bytes to human-readable size string
 */
function formatBytes(
  bytes: number,
  units: { b: string; kb: string; mb: string },
): string {
  if (bytes === 0) return `0 ${units.b}`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} ${units.kb}`;
  return `${(kb / 1024).toFixed(1)} ${units.mb}`;
}

/**
 * List of files from additional_kwargs.files (with optional upload status)
 */
function RichFilesList({
  files,
  threadId,
}: {
  files: FileInMessage[];
  threadId: string;
}) {
  if (files.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap justify-end gap-2">
      {files.map((file, index) => (
        <RichFileCard
          key={`${file.filename}-${index}`}
          file={file}
          threadId={threadId}
        />
      ))}
    </div>
  );
}

/**
 * Single file card that handles FileInMessage (supports uploading state)
 */
function RichFileCard({
  file,
  threadId,
}: {
  file: FileInMessage;
  threadId: string;
}) {
  const { t } = useI18n();
  const isUploading = file.status === "uploading";
  const isImage = isImageFile(file.filename);

  if (isUploading) {
    return (
      <div className="bg-background border-border-subtle flex max-w-50 min-w-30 flex-col gap-1 rounded-lg border p-3 opacity-60 shadow-[var(--shadow-xs)]">
        <div className="flex items-start gap-2">
          <Loader2Icon className="text-muted-foreground mt-0.5 size-4 shrink-0 animate-spin" />
          <span
            className="text-foreground truncate text-sm font-medium"
            title={file.filename}
          >
            {file.filename}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <Badge
            variant="secondary"
            className="rounded px-1.5 py-0.5 text-xs font-normal"
          >
            {getFileTypeLabel(file.filename, t.messageGrouping.fileFallback)}
          </Badge>
          <span className="text-muted-foreground text-xs">
            {t.uploads.uploading}
          </span>
        </div>
      </div>
    );
  }

  if (!file.path) return null;

  const fileUrl = resolveArtifactURL(file.path, threadId);

  if (isImage) {
    return (
      <a
        href={fileUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="border-border-subtle relative block overflow-hidden rounded-lg border"
      >
        <img
          src={fileUrl}
          alt={file.filename}
          className="h-32 w-auto max-w-60 object-cover"
        />
      </a>
    );
  }

  return (
    <div className="bg-background border-border-subtle flex max-w-50 min-w-30 flex-col gap-1 rounded-lg border p-3 shadow-[var(--shadow-xs)]">
      <div className="flex items-start gap-2">
        <FileIcon className="text-muted-foreground mt-0.5 size-4 shrink-0" />
        <span
          className="text-foreground truncate text-sm font-medium"
          title={file.filename}
        >
          {file.filename}
        </span>
      </div>
      <div className="flex items-center justify-between gap-2">
        <Badge
          variant="secondary"
          className="rounded px-1.5 py-0.5 text-xs font-normal"
        >
          {getFileTypeLabel(file.filename, t.messageGrouping.fileFallback)}
        </Badge>
        <span className="text-muted-foreground text-xs">
          {formatBytes(file.size, {
            b: t.common.fileSizeB,
            kb: t.common.fileSizeKB,
            mb: t.common.fileSizeMB,
          })}
        </span>
      </div>
    </div>
  );
}

const MessageContent = memo(MessageContent_);
