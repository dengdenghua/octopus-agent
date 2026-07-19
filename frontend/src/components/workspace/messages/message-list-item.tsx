import type { Message } from "@/core/api/types";
import "katex/dist/katex.min.css";
import {
  FileIcon,
  Loader2Icon,
  PanelRightOpenIcon,
  PencilIcon,
  RefreshCwIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
} from "lucide-react";
import { useParams } from "react-router-dom";
import {
  memo,
  useCallback,
  useMemo,
  type ComponentProps,
  type ImgHTMLAttributes,
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
import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  extractTextFromMessage,
  parseUploadedFiles,
  stripUploadedFilesTag,
  type FileInMessage,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { useHumanMessagePlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

import { CopyButton } from "../copy-button";
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
import { ClarificationChoiceCard } from "./clarification-choice-card";
import { GroundingChip } from "./grounding-chip";
import { extractClarificationQuestionnaire } from "../clarification-questionnaire";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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

function getPublicReasoningSummary(message: Message): string | null {
  const additional = isRecord(message.additional_kwargs)
    ? message.additional_kwargs
    : null;
  const octopus = isRecord(additional?.octopus) ? additional.octopus : null;
  for (const source of [additional, octopus]) {
    if (!source) continue;
    for (const key of [
      "public_reasoning_summary",
      "reasoning_summary",
      "thinking_summary",
      "thought_summary",
    ]) {
      const value = source[key];
      if (typeof value === "string" && value.trim()) {
        const cleaned = value.trim();
        if (!looksLikeBoilerplateThinking(cleaned)) return cleaned;
      }
    }
  }
  return null;
}

const INTERNAL_PROGRESS_THINKING_PATTERNS = [
  /connected to the model gateway/i,
  /waiting for (?:the )?first (?:response )?chunk/i,
  /model gateway status/i,
  /waiting_for_first_chunk/i,
  /request intake/i,
  /task framing/i,
  /tool routing/i,
  /model dispatch/i,
  /concise judgment path/i,
  /structured timeline of thoughts and tool calls/i,
  /\u6a21\u578b\u7f51\u5173/,
  /\u7b49\u5f85[\s\S]*\u54cd\u5e94/,
  /\u9762\u5411\u6700\u7ec8\u56de\u590d\u7684\u7b80\u660e\u5224\u65ad\u8def\u5f84/,
  /\u601d\u8003\u4e0e\u5de5\u5177\u8c03\u7528\u7684\u7ed3\u6784\u5316\u65f6\u95f4\u7ebf/,
];

const BOILERPLATE_THINKING_PATTERNS = [
  /frame the ask/i,
  /restate the objective/i,
  /gather context/i,
  /reason across options/i,
  /check for stale facts/i,
  /give the user the result/i,
  /avoid exposing hidden chain-of-thought/i,
  /keep any helper roles virtual/i,
  /this turn is in structured thinking mode/i,
  /use the plan below only as private execution guidance/i,
  /when you surface progress, write task-specific public checkpoints/i,
  /request intake/i,
  /task framing/i,
  /tool routing/i,
  /model dispatch/i,
  /我会先调用必要工具/,
  /边拿结果边整理答案/,
  /开始直接生成回复/,
  /开始规划/,
  /规划完成/,
  /还在执行中/,
  /正在执行工具/,
  /工具完成/,
  /明确(?:你|用户)?的问题目标/,
  /结合当前上下文组织回答路径/,
  /检查是否需要补充信息/,
];

function looksLikeBoilerplateThinking(text?: string | null): boolean {
  if (!text?.trim()) return false;
  if (
    INTERNAL_PROGRESS_THINKING_PATTERNS.some((pattern) => pattern.test(text))
  ) {
    return true;
  }
  const hits = BOILERPLATE_THINKING_PATTERNS.filter((pattern) =>
    pattern.test(text),
  ).length;
  const hasConcreteSignals =
    /\b(?:Thought|Action|Observation|read_file|web_search|fetch_url|list_cwd|exec_shell)\b/i.test(
      text,
    ) || /[\w.-]+\.(?:tsx?|jsx?|py|ya?ml|json|md|toml|css|html)\b/.test(text);
  return hits >= 2 && !hasConcreteSignals;
}

function buildPublicThinkingSummary(message: Message): string | null {
  // Raw reasoning_content can contain private chain-of-thought. Only render
  // summaries that the backend explicitly marks as public.
  return getPublicReasoningSummary(message);
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
      className="group/thinking-row mb-1 flex w-full min-w-0 items-center gap-1.5 py-0.5 text-left text-[11px] leading-4 text-muted-foreground/55 transition-colors hover:text-muted-foreground"
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
      <PanelRightOpenIcon className="size-3 shrink-0 opacity-0 transition-opacity group-hover/thinking-row:opacity-50" />
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
}: {
  className?: string;
  message: Message;
  isLoading?: boolean;
  chatFontSize?: "small" | "medium" | "large";
  suppressReasoningPanel?: boolean;
  enableClarificationActions?: boolean;
}) {
  const { t } = useI18n();
  const isHuman = message.type === "human";
  const params = useParams();
  const threadIdForFeedback = params.threadId ?? params.thread_id ?? null;
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

        if (sentiment === "liked") {
          import("canvas-confetti").then(({ default: confetti }) => {
            confetti({
              particleCount: 100,
              spread: 70,
              origin: { y: 0.6 },
              colors: ["#10b981", "#3b82f6", "#f59e0b", "#eab308"],
            });
          });
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
        // Implementation note.
        // onto one-character-per-line because the flex item min-width
        // hit 0 and couldn't break in the middle of a 2-char string.
        // Using `max-w-[85%]` instead keeps the right-aligned cap but
        // gives the flex child room to stay on a single horizontal line.
        className={isHuman ? "max-w-[85%] items-end" : "w-full"}
        message={message}
        isLoading={isLoading}
        chatFontSize={chatFontSize}
        suppressReasoningPanel={suppressReasoningPanel}
        enableClarificationActions={enableClarificationActions}
      />
      {!isLoading && (
        <div
          className={cn(
            "flex items-center gap-1.5 text-muted-foreground",
            isHuman
              ? "pointer-events-none absolute top-full right-0 z-20 mt-0.5 w-auto justify-end rounded-lg bg-background/90 px-1 py-0.5 opacity-0 shadow-[var(--shadow-xs)] backdrop-blur-sm transition-opacity group-hover/conversation-message:pointer-events-auto group-hover/conversation-message:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100"
              : "mt-2 w-full",
          )}
        >
          {message.type === "ai" && (
            <>
              <button
                onClick={() => {
                  void submitFeedback("liked");
                }}
                className="inline-flex size-6 items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-200 hover:bg-emerald-500/10 hover:text-emerald-600 dark:hover:text-emerald-400"
                title={t.conversation.goodResponse}
                aria-label={t.conversation.goodResponse}
              >
                <ThumbsUpIcon className="size-3.5" />
              </button>
              <button
                onClick={() => {
                  void submitFeedback("disliked");
                }}
                className="inline-flex size-6 items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-200 hover:bg-rose-500/10 hover:text-rose-600 dark:hover:text-rose-400"
                title={t.conversation.badResponse}
                aria-label={t.conversation.badResponse}
              >
                <ThumbsDownIcon className="size-3.5" />
              </button>
            </>
          )}
          <CopyButton
            clipboardData={
              extractContentFromMessage(message) ??
              extractReasoningContentFromMessage(message) ??
              ""
            }
            size="icon-sm"
            className="size-6 rounded-lg border-0 bg-transparent p-0 text-muted-foreground/70 shadow-none transition-all duration-200 hover:bg-muted/60 hover:text-foreground focus-visible:ring-0 active:scale-95"
          />
          {message.type === "ai" ? (
            <button
              onClick={() => {
                window.dispatchEvent(
                  new CustomEvent("octopus:regenerate", {
                    detail: { threadId: threadIdForFeedback },
                  }),
                );
              }}
              className="inline-flex size-6 items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-200 hover:bg-muted/60 hover:text-foreground"
              title={t.conversation.regenerateResponse}
              aria-label={t.conversation.regenerateResponse}
            >
              <RefreshCwIcon className="size-3.5" />
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
              className="inline-flex size-6 items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-200 hover:bg-muted/60 hover:text-foreground"
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
    return splitInlineThinkingDetails(
      stripLegacySubagentBudgetPlaceholder(
        stripInternalTraceDetails(rawContent ?? ""),
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
  const messageHasToolCalls =
    !isHuman &&
    Array.isArray((message as { tool_calls?: unknown[] }).tool_calls) &&
    ((message as { tool_calls?: unknown[] }).tool_calls?.length ?? 0) > 0;
  const publicThinkingSummary = useMemo(() => {
    if (isHuman) return null;
    return buildPublicThinkingSummary(message);
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
  const showInterruptedReceipt =
    responseState === "interrupted" ||
    (legacyRunStatus === "streaming" && hasVisibleBody);
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
            content={visibleContentToDisplay}
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
        <div className="mt-2 text-[11px] leading-5 text-muted-foreground/70">
          {t.conversation.interruptedMessage}
        </div>
      )}
      {/* Strategy badge · reveals which reply path produced this
          bubble (reflex / ReAct / direct_llm / plan). Helps users
          and devs spot when a long query accidentally hit the cache
          or the planner path for a conversational turn. */}
      {(() => {
        const octopus = (
          message.additional_kwargs as
            | {
                octopus?: {
                  strategy?: string;
                  success?: boolean;
                  reflex_rule?: string;
                  input_tokens?: number;
                  output_tokens?: number;
                  duration_ms?: number;
                  rounds?: number;
                };
              }
            | undefined
        )?.octopus;
        const strategy = octopus?.strategy;
        if (!strategy && octopus?.duration_ms == null) return null;
        const strategyFailed = octopus?.success === false;
        const hiddenStrategies = new Set(["llm_unavailable"]);
        const label: Record<string, string> = {
          reflex: t.conversation.strategyReflex,
          reflex_hit: t.conversation.strategyReflex,
          react_loop: t.conversation.strategyReact,
          chat_fallback_react: t.conversation.strategyReact,
          react_direct_llm: t.conversation.strategyReact,
          thinking_direct_llm: t.conversation.strategyReact,
          direct_llm: t.conversation.strategyDirectLlm,
          direct_llm_fallback: t.conversation.strategyDirectLlm,
          flash_direct_llm: t.conversation.strategyDirectLlm,
          team_direct_llm: t.conversation.strategyDirectLlm,
          team_vote: t.conversation.strategyVote,
        };
        const strategyText = strategy
          ? strategyFailed || hiddenStrategies.has(strategy)
            ? null
            : (label[strategy] ??
              (strategy.startsWith("tier:")
                ? t.conversation.strategyCache
                : strategy))
          : null;
        // Compact stats string · only shown when backend forwarded
        // tokens / duration via the agentic-loop stats event.
        // Format: "1.2k in / 480 out · 8.3s · 3 rounds".
        const statsBits: string[] = [];
        const fmtTok = (n: number): string =>
          n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
        if (
          typeof octopus?.input_tokens === "number" ||
          typeof octopus?.output_tokens === "number"
        ) {
          const inT = octopus.input_tokens ?? 0;
          const outT = octopus.output_tokens ?? 0;
          statsBits.push(`${fmtTok(inT)} in / ${fmtTok(outT)} out`);
        }
        if (typeof octopus?.duration_ms === "number") {
          const ms = octopus.duration_ms;
          statsBits.push(ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);
        }
        if (typeof octopus?.rounds === "number" && octopus.rounds > 1) {
          statsBits.push(`${octopus.rounds} rounds`);
        }
        const statsText = statsBits.join(" · ");
        if (!strategyText && !statsText) return null;
        return (
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {strategyText && (
              <div
                className="inline-flex items-center gap-1 rounded-full bg-muted/40 px-2 py-0.5 text-[10px] text-muted-foreground/80"
                title={
                  octopus?.reflex_rule
                    ? `strategy=${strategy} · rule=${octopus.reflex_rule}`
                    : `strategy=${strategy}`
                }
              >
                {strategyText}
              </div>
            )}
            {statsText && (
              <div
                className="inline-flex items-center gap-1 rounded-full bg-muted/40 px-2 py-0.5 text-[10px] tabular-nums text-muted-foreground/80"
                title={[
                  octopus?.input_tokens != null
                    ? `input_tokens=${octopus.input_tokens}`
                    : null,
                  octopus?.output_tokens != null
                    ? `output_tokens=${octopus.output_tokens}`
                    : null,
                  octopus?.duration_ms != null
                    ? `duration_ms=${octopus.duration_ms}`
                    : null,
                  octopus?.rounds != null ? `rounds=${octopus.rounds}` : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}
              >
                {statsText}
              </div>
            )}
          </div>
        );
      })()}
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
            className="rounded px-1.5 py-0.5 text-[10px] font-normal"
          >
            {getFileTypeLabel(file.filename, t.messageGrouping.fileFallback)}
          </Badge>
          <span className="text-muted-foreground text-[10px]">
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
        className="group border-border-subtle relative block overflow-hidden rounded-lg border"
      >
        <img
          src={fileUrl}
          alt={file.filename}
          className="h-32 w-auto max-w-60 object-cover transition-transform group-hover:scale-105"
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
          className="rounded px-1.5 py-0.5 text-[10px] font-normal"
        >
          {getFileTypeLabel(file.filename, t.messageGrouping.fileFallback)}
        </Badge>
        <span className="text-muted-foreground text-[10px]">
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
