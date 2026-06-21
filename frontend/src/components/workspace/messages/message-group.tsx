import { swallow } from "@/core/utils/log";
import type { AIMessage, Message } from "@/core/api/types";
import {
  BookOpenTextIcon,
  ChevronDownIcon,
  ChevronUp,
  FolderOpenIcon,
  GlobeIcon,
  ListTodoIcon,
  MessageCircleQuestionMarkIcon,
  NotebookPenIcon,
  SearchIcon,
  ShieldAlertIcon,
  SquareTerminalIcon,
  UsersIcon,
  WrenchIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";

import type { BundledLanguage } from "shiki";

import {
  ChainOfThought,
  ChainOfThoughtContent,
  ChainOfThoughtSearchResult,
  ChainOfThoughtSearchResults,
  ChainOfThoughtStep,
} from "@/components/ai-elements/chain-of-thought";
import { CodeBlock } from "@/components/ai-elements/code-block";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";
import {
  isApprovalRequest,
  ToolApprovalCard,
} from "@/components/workspace/tool-approval-card";
import {
  TAORBadge,
  IterationDivider,
} from "@/components/workspace/taor-indicator";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractReasoningContentFromMessage,
  findToolCallResult,
  isLikelyFinalAnswerContent,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { extractTitleFromMarkdown } from "@/core/utils/markdown";
import { cn } from "@/lib/utils";

import { useArtifacts } from "../artifacts";
import { FlipDisplay } from "../flip-display";
import { isAutoVerificationToolName } from "../process-trace-events";
import { Tooltip } from "../tooltip";

import { ClarificationChoiceCard } from "./clarification-choice-card";
import { MarkdownContent } from "./markdown-content";
import { stripTraceLabelPrefixes } from "./trace-labels";
import {
  actionStateLabel,
  inferToolActionKind,
  inferToolActionKindFromText,
  reasoningStateLabel,
} from "../tool-action-kind";

const INTERNAL_PROGRESS_PATTERNS = [
  /我会先调用必要工具/,
  /边拿结果边整理答案/,
  /开始直接生成回复/,
  /开始规划/,
  /规划完成/,
  /还在执行中/,
  /正在执行工具/,
  /工具完成/,
  /frame the ask/i,
  /gather context/i,
  /reason across options/i,
  /avoid exposing hidden chain-of-thought/i,
  /use the plan below only as private execution guidance/i,
];

function isInternalProgressText(text?: string | null): boolean {
  if (!text?.trim()) return false;
  return INTERNAL_PROGRESS_PATTERNS.some((pattern) => pattern.test(text));
}

function isActionCallbackText(text?: string | null): boolean {
  const value = text
    ?.replace(/^\s*>\s?/gm, "")
    .replace(/<\/?(?:tool|tool_call|function)[^>]*>/gi, "")
    .trim();
  if (!value) return false;
  const normalized = stripTraceLabelPrefixes(value);
  const chineseActionPrefixes = [
    "\u4f7f\u7528",
    "\u6267\u884c",
    "\u641c\u7d22",
    "\u8bfb\u53d6",
    "\u5199\u5165",
    "\u8c03\u7528",
    "\u6253\u5f00",
    "\u66f4\u65b0",
  ];
  const actionIntent =
    /^(?:now\s+)?(?:let me|i(?:'ll| will| need to| should| can)|we(?:'ll| will| need to| should))\s+(?:search|look up|query|check|read|open|fetch|browse|run|write|compile|synthesize|summarize|try|use)\b/i;
  const observationIntent =
    /^(?:the\s+)?(?:search\s+results?|results?|observation)\b.*\b(?:empty|found|show|shows|coming back|returned|suggest|indicate)\b/i;
  const toolProtocol =
    /<tool_call\b|<\/?function=|"\s*command\s*"\s*:\s*"|(?:^|\b)(?:web_search|image_search|web_fetch|fetch_url|read_file|write_file|apply_patch|shell_command|exec_shell|list_cwd)\b/i;
  return (
    /^Action:\s*/.test(value) ||
    /^Observation:\s*/i.test(value) ||
    toolProtocol.test(text ?? "") ||
    actionIntent.test(normalized) ||
    observationIntent.test(normalized) ||
    /^(search|read|write|call|open|update|run|use)\b/i.test(value) ||
    /^[A-Za-z_][A-Za-z0-9_-]*\s*\(/.test(normalized) ||
    chineseActionPrefixes.some((prefix) => normalized.startsWith(prefix))
  );
}

const HIDDEN_TIMELINE_TOOL_NAMES = new Set([
  "task",
  "todo_write",
  "write_todos",
  "bb_keys",
  "query_skill",
  "skill_search",
  "apply_skill",
  "deep-research",
  "deep_research",
  "deep-research-swarm",
  "recall",
]);

const PUBLIC_TRACE_TOOL_RE =
  /\b(web_search|image_search|fetch_url|web_fetch|read_file|read_file_range|write_file|str_replace|edit_code|ls|list_cwd|glob_files|call_agent_parallel|call_agent|bb_keys|query_skill|skill_search|apply_skill|deep-research|deep_research|deep-research-swarm|recall|todo_write|write_todos)\b/i;

function isHiddenTimelineToolName(name: string): boolean {
  const normalized = name.toLowerCase();
  return (
    HIDDEN_TIMELINE_TOOL_NAMES.has(normalized) ||
    isAutoVerificationToolName(normalized)
  );
}

function isTeamCallToolName(name: string): boolean {
  const normalized = name.toLowerCase();
  return (
    normalized === "call_agent_parallel" ||
    normalized === "call_agent" ||
    normalized === "delegate_agent" ||
    normalized === "spawn_agent"
  );
}

function extractTraceToolName(text: string): string | null {
  const functionMatch = text.match(/function=([A-Za-z0-9_-]+)/i);
  if (functionMatch?.[1]) return functionMatch[1];
  const directMatch = text.match(PUBLIC_TRACE_TOOL_RE);
  if (directMatch?.[1]) return directMatch[1];
  const callMatch = text.match(/\b([A-Za-z_][A-Za-z0-9_-]*)\s*\(/);
  return callMatch?.[1] ?? null;
}

function extractTraceTarget(text: string, name: string): string | undefined {
  const targetKey = /search|glob/i.test(name)
    ? "query"
    : /fetch|url|web/i.test(name)
      ? "url"
      : /read|write|edit|list|ls|path|file/i.test(name)
        ? "path"
        : "target";
  const xmlMatch = text.match(
    new RegExp(`<parameter=${targetKey}>([\\s\\S]*?)<\\/parameter>`, "i"),
  );
  if (xmlMatch?.[1]?.trim()) return xmlMatch[1].trim();
  const jsonMatch =
    text.match(new RegExp(`"${targetKey}"\\s*:\\s*"([^"]+)"`, "i")) ??
    text.match(/"query"\s*:\s*"([^"]+)"/i) ??
    text.match(/"url"\s*:\s*"([^"]+)"/i) ??
    text.match(/"path"\s*:\s*"([^"]+)"/i) ??
    text.match(/"name"\s*:\s*"([^"]+)"/i) ??
    text.match(/"role"\s*:\s*"([^"]+)"/i);
  if (jsonMatch?.[1]?.trim()) return jsonMatch[1].trim();
  const knownAgentMatch = text.match(
    /(Market Researcher|Coder|Vibe Selling|Ecommerce Mind)/i,
  );
  return knownAgentMatch?.[1];
}

function publicActionTextFromTraceTool(
  name: string,
  target: string | undefined,
  t: ReturnType<typeof useI18n>["t"] | undefined,
): string | null {
  if (!t || isHiddenTimelineToolName(name)) return null;
  const normalized = name.toLowerCase();
  const withTarget = (label: string) =>
    target ? `${label}: ${target}` : label;
  if (isTeamCallToolName(normalized)) {
    return withTarget(t.messageGrouping.callTeammate);
  }
  if (normalized.includes("search") || normalized.includes("glob")) {
    return withTarget(t.messageGrouping.searchSources);
  }
  if (normalized.includes("fetch") || normalized.includes("web_fetch")) {
    return withTarget(t.messageGrouping.readWebpage);
  }
  if (
    normalized.includes("read") ||
    normalized === "ls" ||
    normalized === "list_cwd"
  ) {
    return withTarget(t.messageGrouping.readFile);
  }
  if (
    normalized.includes("write") ||
    normalized.includes("edit") ||
    normalized.includes("replace")
  ) {
    return withTarget(t.messageGrouping.updateFile);
  }
  return withTarget(t.messageGrouping.runAction);
}

function publicStatusFromPrivateReasoning(
  text: string,
  t: ReturnType<typeof useI18n>["t"] | undefined,
): string | null {
  if (!t) return null;
  if (
    /SOUL\.md|hard system rule|system prompt|hidden chain-of-thought/i.test(
      text,
    )
  ) {
    return null;
  }
  if (
    /sub-?agent.*(?:round cap|timeout|exceeded)|round cap|timeout/i.test(text)
  ) {
    return t.messageGrouping.teammateTimeout;
  }
  if (/\u5b50\s*agent.*\u8d85\u65f6|\u8d85\u65f6.*\u63a5\u7ba1/.test(text)) {
    return t.messageGrouping.teammateTimeout;
  }
  if (/\b(?:the user|user asks|request|objective)\b/i.test(text)) {
    return t.messageGrouping.clarifyTaskDirection;
  }
  if (
    /\b(?:write|draft|synthesize|compile|report)\b/i.test(text) ||
    /\u62a5\u544a|\u64b0\u5199|\u6574\u7406/.test(text)
  ) {
    return t.messageGrouping.synthesizeFindings;
  }
  if (
    /\b(?:search|query|look up|fetch|source)\b/i.test(text) ||
    /\u641c\u7d22|\u8d44\u6599|\u7f51\u9875/.test(text)
  ) {
    return t.messageGrouping.searchSources;
  }
  if (
    /\b(?:plan|todo|next step)\b/i.test(text) ||
    /\u8ba1\u5212|\u4e0b\u4e00\u6b65|\u89c4\u5212/.test(text)
  ) {
    return t.messageGrouping.planNextStep;
  }
  if (
    /\b(?:call_agent|teammate|colleague|Market Researcher)\b/i.test(text) ||
    /\u53ec\u5524|\u56e2\u961f|\u540c\u4e8b/.test(text)
  ) {
    return t.messageGrouping.callTeammate;
  }
  return null;
}

function looksLikePrivateReasoningText(text: string): boolean {
  return (
    /\b(?:let me|i(?:'ll| will| need to| should| can)|actually|looking at|since the user|my memory|blackboard|ddg|backend|todo|skill|tool|web_search|fetch_url|query_skill|bb_keys|call_agent_parallel)\b/i.test(
      text,
    ) ||
    /\u8ba9\u6211|\u6211\u9700\u8981|\u6211\u5e94\u8be5|\u5b9e\u9645\u4e0a|\u9ed1\u677f|\u641c\u7d22\u540e\u7aef|\u5de5\u5177|\u6280\u80fd|todo/.test(
      text,
    )
  );
}

function normalizePublicTimelineChunk(
  chunk: string,
  t: ReturnType<typeof useI18n>["t"] | undefined,
  options: { allowPlainThoughts: boolean },
): string | null {
  if (!t) return null;
  const stripped = stripTraceLabelPrefixes(
    chunk
      .replace(/<\/?(?:tool|tool_call|function|thought|thinking)[^>]*>/gi, " ")
      .replace(/\s+/g, " ")
      .trim(),
  );
  if (!stripped) return null;
  if (FIRST_PHASE_RE.test(stripped)) {
    return compactReasoningSummary(stripped, 120);
  }
  const toolName = extractTraceToolName(chunk);
  if (toolName) {
    const actionText = publicActionTextFromTraceTool(
      toolName,
      extractTraceTarget(chunk, toolName),
      t,
    );
    return actionText ? t.message.actionLabel(actionText) : null;
  }
  if (!options.allowPlainThoughts) {
    const publicStatus = publicStatusFromPrivateReasoning(stripped, t);
    if (publicStatus) return publicStatus;
  }
  if (
    /^\s*Observation\s*:/i.test(chunk) ||
    /\(real tool execution/i.test(chunk)
  ) {
    return null;
  }
  if (!options.allowPlainThoughts && looksLikePrivateReasoningText(stripped)) {
    return null;
  }
  if (options.allowPlainThoughts) return stripped;
  return null;
}

function dedupeTimelineChunks(chunks: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const chunk of chunks) {
    const normalized = stripTraceLabelPrefixes(chunk)
      .replace(/\s+/g, " ")
      .trim()
      .toLowerCase();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(chunk);
  }
  return result;
}

export function MessageGroup({
  className,
  enableClarificationActions = false,
  messages,
  isLoading = false,
  keepOpen = false,
}: {
  className?: string;
  enableClarificationActions?: boolean;
  messages: Message[];
  isLoading?: boolean;
  keepOpen?: boolean;
}) {
  const { t } = useI18n();
  // Keep the live turn focused on the current frame. Older steps move behind
  // a replay disclosure so streaming never becomes a long historical pile.
  const isLiveTimeline = isLoading || keepOpen;
  const [showSteps, setShowSteps] = useState(false);
  const [openReasoningGroups, setOpenReasoningGroups] = useState<
    Record<string, boolean>
  >({});
  const [openActionGroups, setOpenActionGroups] = useState<
    Record<string, boolean>
  >({});
  const steps = useMemo(
    () => convertToSteps(messages, t),
    [messages, t],
  );
  const clarificationContent = useMemo(
    () =>
      steps
        .map((step) =>
          step.type === "reasoning"
            ? step.reasoning
            : step.type === "actionCallback"
              ? step.actionText
              : null,
        )
        .filter((value): value is string => Boolean(value?.trim()))
        .join("\n\n"),
    [steps],
  );
  const stepsFingerprint = useMemo(
    () => messages.map((message) => message.id).join("|"),
    [messages],
  );
  const timelineItems = useMemo(
    () => groupConsecutiveReasoningSteps(steps),
    [steps],
  );
  const { currentStep, replaySteps } = useMemo(() => {
    if (!isLiveTimeline) return { currentStep: null, replaySteps: steps };
    return {
      currentStep: steps[steps.length - 1] ?? null,
      replaySteps: steps.slice(0, -1),
    };
  }, [isLiveTimeline, steps]);
  const leadInSteps = useMemo(
    () =>
      isLiveTimeline
        ? leadInStepsBeforeFirstPhase(replaySteps, currentStep)
        : [],
    [currentStep, isLiveTimeline, replaySteps],
  );
  const replayOnlySteps = useMemo(
    () =>
      isLiveTimeline && leadInSteps.length > 0
        ? replaySteps.slice(leadInSteps.length)
        : replaySteps,
    [isLiveTimeline, leadInSteps.length, replaySteps],
  );
  const currentTimelineItem = useMemo(
    () => (currentStep ? timelineItemFromStep(currentStep, "current") : null),
    [currentStep],
  );
  const leadInTimelineItems = useMemo(
    () => groupConsecutiveReasoningSteps(leadInSteps),
    [leadInSteps],
  );
  const replayTimelineItems = useMemo(
    () =>
      isLiveTimeline
        ? groupConsecutiveReasoningSteps(replayOnlySteps)
        : timelineItems,
    [isLiveTimeline, replayOnlySteps, timelineItems],
  );
  const totalIterations = useMemo(() => {
    const last = steps[steps.length - 1];
    return last?.iteration ?? 1;
  }, [steps]);
  const rehypePlugins = useRehypeSplitWordsIntoSpans(isLoading);
  const replayStepCount = isLiveTimeline
    ? replayOnlySteps.length
    : steps.length;
  const showTimelineToggle = replayStepCount > 0;
  const useCompactToggleLabel = replayStepCount > 12;
  const timelineToggleLabel = isLiveTimeline
    ? showSteps
      ? t.messageGrouping.hideProcessReplay
      : useCompactToggleLabel
        ? t.messageGrouping.processReplay
        : t.messageGrouping.replayNSteps(replayStepCount)
    : showSteps
      ? t.messageGrouping.hideSavedSteps
      : useCompactToggleLabel
        ? t.messageGrouping.viewProcessSummary
        : t.messageGrouping.viewNSavedSteps(steps.length);

  useEffect(() => {
    setShowSteps(false);
    setOpenReasoningGroups({});
    setOpenActionGroups({});
  }, [isLiveTimeline, stepsFingerprint]);

  if (steps.length === 0) {
    return null;
  }

  // Helper: render an iteration divider when the iteration number changes
  // between consecutive steps.
  function renderIterationDivider(
    prevStep: CoTStep | undefined,
    currentStep: CoTStep,
  ) {
    if (
      prevStep &&
      currentStep.iteration != null &&
      prevStep.iteration != null &&
      currentStep.iteration > prevStep.iteration
    ) {
      return (
        <IterationDivider
          key={`iter-${currentStep.iteration}`}
          iteration={currentStep.iteration}
          maxIterations={totalIterations > 1 ? totalIterations : undefined}
        />
      );
    }
    return null;
  }

  function renderTimelineItem(
    item: TimelineItem,
    idx: number,
    items: TimelineItem[],
    options?: { current?: boolean },
  ) {
    const isCurrentFrame = Boolean(options?.current);
    const isHistoryReplay = isLiveTimeline && !isCurrentFrame;
    const itemIsLoading = isCurrentFrame
      ? isLoading
      : !isHistoryReplay && isLoading;
    const prevItem = idx > 0 ? items[idx - 1] : undefined;
    const prevStep = prevItem ? lastTimelineStep(prevItem) : undefined;
    const isLast =
      isCurrentFrame || (!isHistoryReplay && idx === items.length - 1);
    if (item.type === "reasoningGroup") {
      const open =
        isCurrentFrame ||
        (openReasoningGroups[item.id] ?? item.steps.length <= 3);
      const isActiveGroup =
        isCurrentFrame || (itemIsLoading && isLast && item.steps.length > 0);
      const content = (
        <ReasoningStepGroup
          key={item.id}
          group={item}
          isLoading={itemIsLoading}
          open={open}
          active={isActiveGroup}
          onOpenChange={(nextOpen) =>
            setOpenReasoningGroups((current) => ({
              ...current,
              [item.id]: nextOpen,
            }))
          }
          rehypePlugins={rehypePlugins}
          renderIterationDivider={() =>
            renderIterationDivider(prevStep, item.steps[0]!)
          }
        />
      );
      return isCurrentFrame ? (
        <FlipDisplay key={item.id} uniqueKey={item.id}>
          {content}
        </FlipDisplay>
      ) : (
        content
      );
    }
    if (item.type === "actionCallbackGroup") {
      const open =
        isCurrentFrame || (openActionGroups[item.id] ?? item.steps.length <= 3);
      const isActiveGroup =
        isCurrentFrame || (itemIsLoading && isLast && item.steps.length > 0);
      const content = (
        <ActionCallbackGroup
          key={item.id}
          group={item}
          open={open}
          active={isActiveGroup}
          onOpenChange={(nextOpen) =>
            setOpenActionGroups((current) => ({
              ...current,
              [item.id]: nextOpen,
            }))
          }
          renderIterationDivider={() =>
            renderIterationDivider(prevStep, item.steps[0]!)
          }
        />
      );
      return isCurrentFrame ? (
        <FlipDisplay key={item.id} uniqueKey={item.id}>
          {content}
        </FlipDisplay>
      ) : (
        content
      );
    }
    const content = (
      <div key={item.id}>
        {renderIterationDivider(prevStep, item.step)}
        <ToolCall {...item.step} isLast={isLast} isLoading={itemIsLoading} />
      </div>
    );
    return isCurrentFrame ? (
      <FlipDisplay key={item.id} uniqueKey={item.id}>
        {content}
      </FlipDisplay>
    ) : (
      content
    );
  }

  return (
    <ChainOfThought
      defaultOpen
      className={cn("w-full gap-1 border-l border-border/60 pl-4", className)}
      open={true}
    >
      {leadInTimelineItems.length > 0 && (
        <ChainOfThoughtContent className="px-0 pb-1.5">
          {leadInTimelineItems.map((item, idx) =>
            renderTimelineItem(item, idx, leadInTimelineItems),
          )}
        </ChainOfThoughtContent>
      )}
      {showTimelineToggle && (
        <Button
          key="timeline-toggle"
          className="h-auto w-full items-start justify-start px-0 py-1.5 text-left hover:bg-transparent"
          variant="ghost"
          onClick={() => setShowSteps(!showSteps)}
        >
          <ChainOfThoughtStep
            label={<span className="opacity-60">{timelineToggleLabel}</span>}
            icon={
              <ChevronUp
                className={cn(
                  "size-4 opacity-60 transition-transform duration-200",
                  showSteps ? "rotate-180" : "",
                )}
              />
            }
          ></ChainOfThoughtStep>
        </Button>
      )}
      {showSteps && replayTimelineItems.length > 0 && (
        <ChainOfThoughtContent className="px-0 pb-1.5">
          {replayTimelineItems.map((item, idx) =>
            renderTimelineItem(item, idx, replayTimelineItems),
          )}
        </ChainOfThoughtContent>
      )}
      {currentTimelineItem && (
        <ChainOfThoughtContent className="px-0 pb-1.5">
          {renderTimelineItem(currentTimelineItem, 0, [currentTimelineItem], {
            current: true,
          })}
        </ChainOfThoughtContent>
      )}
      {clarificationContent && (
        <ClarificationChoiceCard
          active={enableClarificationActions && !isLoading}
          className="mt-4"
          content={clarificationContent}
          messageId={messages[messages.length - 1]?.id}
        />
      )}
    </ChainOfThought>
  );
}

function ReasoningStepGroup({
  group,
  isLoading,
  open,
  active,
  onOpenChange,
  rehypePlugins,
  renderIterationDivider,
}: {
  group: ReasoningStepGroupItem;
  isLoading: boolean;
  open: boolean;
  active: boolean;
  onOpenChange: (open: boolean) => void;
  rehypePlugins: ReturnType<typeof useRehypeSplitWordsIntoSpans>;
  renderIterationDivider: () => ReactNode;
}) {
  const { t } = useI18n();
  const summary = summarizeReasoningGroup(group, t);
  const countLabel =
    group.steps.length > 1 ? t.messageGrouping.countItems(group.steps.length) : "";
  const onlyStep = group.steps[0];
  if (!onlyStep) return null;
  return (
    <div key={group.id}>
      {renderIterationDivider()}
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <div className="mb-1 flex min-w-0 items-center gap-2">
          <TAORBadge
            phase="think"
            active={active}
            labelOverride={reasoningStateLabel(summary, active, t.taor.think)}
            className="shrink-0"
          />
          {group.steps.length > 1 && (
            <CollapsibleTrigger
              className={cn(
                "group flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-0.5 text-left",
                "text-sm text-foreground/85 transition-colors hover:bg-muted/40 hover:text-foreground",
              )}
            >
              <span className="text-muted-foreground/70 shrink-0 text-xs font-medium">
                {countLabel.trim()}
              </span>
              <span className="min-w-0 flex-1 truncate">{summary}</span>
              <ChevronDownIcon
                className={cn(
                  "size-3.5 shrink-0 transition-transform",
                  open ? "rotate-180" : "",
                )}
              />
            </CollapsibleTrigger>
          )}
        </div>
        {group.steps.length === 1 ? (
          <NumberedReasoningStep
            index={1}
            step={onlyStep}
            isLoading={isLoading}
            active={active}
            rehypePlugins={rehypePlugins}
            showNumber={false}
          />
        ) : (
          <CollapsibleContent className="space-y-1.5 data-[state=closed]:animate-out data-[state=open]:animate-in">
            {group.steps.map((step, index) => (
              <NumberedReasoningStep
                key={step.id ?? `${group.id}-${index}`}
                index={index + 1}
                step={step}
                isLoading={isLoading}
                active={active && index === group.steps.length - 1}
                rehypePlugins={rehypePlugins}
                showNumber
              />
            ))}
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  );
}

function ActionCallbackGroup({
  group,
  open,
  active,
  onOpenChange,
  renderIterationDivider,
}: {
  group: ActionCallbackGroupItem;
  open: boolean;
  active: boolean;
  onOpenChange: (open: boolean) => void;
  renderIterationDivider: () => ReactNode;
}) {
  const { t } = useI18n();
  const summary = summarizeActionGroup(group, t);
  const countLabel =
    group.steps.length > 1 ? t.messageGrouping.countItems(group.steps.length) : "";
  const onlyStep = group.steps[0];
  if (!onlyStep) return null;
  const labelStep = active ? group.steps[group.steps.length - 1] : onlyStep;
  const activeKind = inferToolActionKindFromText(labelStep?.actionText ?? "");
  return (
    <div key={group.id}>
      {renderIterationDivider()}
      <Collapsible open={open} onOpenChange={onOpenChange}>
        <div className="mb-1 flex min-w-0 items-center gap-2">
          <TAORBadge
            phase="act"
            active={active}
            labelOverride={actionStateLabel(activeKind, active, t.taor.think)}
            className="shrink-0"
          />
          {group.steps.length > 1 && (
            <CollapsibleTrigger
              className={cn(
                "group flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-0.5 text-left",
                "text-[11px] text-muted-foreground/70 transition-colors hover:bg-muted/40 hover:text-muted-foreground",
              )}
            >
              <span className="shrink-0 font-medium text-muted-foreground/60">
                {countLabel.trim()}
              </span>
              <span className="min-w-0 flex-1 truncate">{summary}</span>
              <ChevronDownIcon
                className={cn(
                  "size-3.5 shrink-0 transition-transform",
                  open ? "rotate-180" : "",
                )}
              />
            </CollapsibleTrigger>
          )}
        </div>
        {group.steps.length === 1 ? (
          <NumberedActionStep
            index={1}
            step={onlyStep}
            active={active}
            showNumber={false}
          />
        ) : (
          <CollapsibleContent className="space-y-1.5 data-[state=closed]:animate-out data-[state=open]:animate-in">
            {group.steps.map((step, index) => (
              <NumberedActionStep
                key={step.id ?? `${group.id}-${index}`}
                index={index + 1}
                step={step}
                active={active && index === group.steps.length - 1}
                showNumber
              />
            ))}
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  );
}

function NumberedActionStep({
  index,
  step,
  active,
  showNumber,
}: {
  index: number;
  step: CoTActionCallbackStep;
  active: boolean;
  showNumber: boolean;
}) {
  const actionText = stripTraceLabelPrefixes(step.actionText);
  const actionSummary = compactReasoningSummary(actionText, 120);
  const canExpand =
    showNumber && isExpandableStepText(actionText, actionSummary);
  return (
    <ChainOfThoughtStep
      className="items-start"
      icon={showNumber ? <StepNumber index={index} /> : undefined}
      label={
        canExpand ? (
          <NestedStepDisclosure defaultOpen={active} summary={actionSummary}>
            <ActionCallbackLabel text={actionText} expanded />
          </NestedStepDisclosure>
        ) : (
          <ActionCallbackLabel text={actionText} />
        )
      }
    />
  );
}

function ActionCallbackLabel({
  expanded,
  text,
}: {
  expanded?: boolean;
  text: string;
}) {
  const summary = expanded
    ? text
    : compactReasoningSummary(stripTraceLabelPrefixes(text), 140);
  return (
    <div className="max-w-full break-words text-[10px] leading-4 text-muted-foreground/75">
      {summary}
    </div>
  );
}

function StepNumber({ index }: { index: number }) {
  return (
    <span className="bg-muted text-muted-foreground flex size-5 items-center justify-center rounded-full font-mono text-[10px]">
      {String(index).padStart(2, "0")}
    </span>
  );
}

function NumberedReasoningStep({
  index,
  step,
  isLoading,
  active,
  rehypePlugins,
  showNumber,
}: {
  index: number;
  step: CoTReasoningStep;
  isLoading: boolean;
  active: boolean;
  rehypePlugins: ReturnType<typeof useRehypeSplitWordsIntoSpans>;
  showNumber: boolean;
}) {
  const reasoningText = stripTraceLabelPrefixes(step.reasoning);
  const reasoningSummary = compactReasoningSummary(reasoningText, 120);
  const canExpand =
    showNumber && isExpandableStepText(reasoningText, reasoningSummary);
  return (
    <ChainOfThoughtStep
      className="items-start"
      icon={showNumber ? <StepNumber index={index} /> : undefined}
      label={
        canExpand ? (
          <NestedStepDisclosure defaultOpen={active} summary={reasoningSummary}>
            <MarkdownContent
              content={reasoningText}
              isLoading={isLoading}
              rehypePlugins={rehypePlugins}
            />
          </NestedStepDisclosure>
        ) : (
          <MarkdownContent
            content={reasoningText}
            isLoading={isLoading}
            rehypePlugins={rehypePlugins}
          />
        )
      }
    ></ChainOfThoughtStep>
  );
}

function NestedStepDisclosure({
  children,
  defaultOpen,
  summary,
}: {
  children: ReactNode;
  defaultOpen?: boolean;
  summary: string;
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger
        className={cn(
          "group/nested-step flex min-w-0 items-start gap-1.5 rounded-md px-1 py-0.5 text-left",
          "text-[11px] leading-5 text-foreground/75 transition-colors hover:bg-muted/40 hover:text-foreground",
        )}
      >
        <ChevronDownIcon className="mt-1 size-3 shrink-0 -rotate-90 text-muted-foreground transition-transform group-data-[state=open]/nested-step:rotate-0" />
        <span className="min-w-0 flex-1 break-words">{summary}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 border-l border-border/60 pl-2 data-[state=closed]:animate-out data-[state=open]:animate-in">
        {children}
      </CollapsibleContent>
    </Collapsible>
  );
}

function isExpandableStepText(raw: string | null | undefined, summary: string) {
  const normalized = (raw ?? "").replace(/\s+/g, " ").trim();
  return normalized.length > summary.length || (raw ?? "").includes("\n");
}

// Single-line tool-call label: action verb on the left, target filename as
// an inline muted chip on the right. This compacts the previous two-row
// Implementation note.
// bar.csv" density seen in other IDE-style products.
function inlineActionLabel(action: React.ReactNode, detail?: React.ReactNode) {
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className="text-foreground shrink-0">{action}</span>
      {detail && (
        <span className="text-muted-foreground bg-muted/60 min-w-0 truncate rounded-md px-1.5 py-0.5 font-mono text-[11px]">
          {detail}
        </span>
      )}
    </div>
  );
}

const _PATH_KEYS = [
  "path",
  "file_path",
  "filepath",
  "filename",
  "root",
  "directory",
  "cwd",
  "command",
  "url",
  "query",
] as const;
const _DESC_KEYS = ["description", "desc", "purpose", "reason"] as const;

function extractPathFromArgs(
  args: Record<string, unknown>,
): string | undefined {
  for (const key of _PATH_KEYS) {
    const val = args[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return undefined;
}

function extractDescFromArgs(
  args: Record<string, unknown>,
): string | undefined {
  for (const key of _DESC_KEYS) {
    const val = args[key];
    if (typeof val === "string" && val.trim()) return val.trim();
  }
  return undefined;
}

function extractTeamCallTarget(
  args: Record<string, unknown>,
): string | undefined {
  for (const key of ["agent", "agent_name", "name", "role", "display_name"]) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  for (const key of ["agents", "roles", "team"]) {
    const value = args[key];
    if (!Array.isArray(value)) continue;
    const names = value
      .map((item) => {
        if (typeof item === "string") return item.trim();
        if (typeof item !== "object" || item === null) return "";
        const record = item as Record<string, unknown>;
        for (const nestedKey of ["name", "role", "agent", "display_name"]) {
          const nested = record[nestedKey];
          if (typeof nested === "string" && nested.trim()) {
            return nested.trim();
          }
        }
        return "";
      })
      .filter(Boolean);
    if (names.length > 0) return names.join(", ");
  }
  const knownAgentMatch = JSON.stringify(args).match(
    /(Market Researcher|Coder|Vibe Selling|Ecommerce Mind)/i,
  );
  return knownAgentMatch?.[1];
}

function ToolCall({
  id,
  messageId,
  name,
  args,
  result,
  isLast = false,
  isLoading = false,
}: {
  id?: string;
  messageId?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string | Record<string, unknown> | unknown[];
  isLast?: boolean;
  isLoading?: boolean;
}) {
  const { t } = useI18n();
  const { setOpen, autoOpen, autoSelect, selectedArtifact, select } =
    useArtifacts();
  const isActive = isLoading && isLast;

  if (name === "web_search") {
    let label: React.ReactNode = t.toolCalls.searchForRelatedInfo;
    if (typeof args.query === "string") {
      label = t.toolCalls.searchOnWebFor(args.query);
    }
    const results = extractSearchResults(result);
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            <span className="min-w-0 truncate">{label}</span>
          </div>
        }
        icon={SearchIcon}
      >
        <SearchResultsList results={results} />
      </ChainOfThoughtStep>
    );
  } else if (name === "image_search") {
    let label: React.ReactNode = t.toolCalls.searchForRelatedImages;
    if (typeof args.query === "string") {
      label = t.toolCalls.searchForRelatedImagesFor(args.query);
    }
    const results = (
      result as {
        results: {
          source_url: string;
          thumbnail_url: string;
          image_url: string;
          title: string;
        }[];
      }
    )?.results;
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            <span className="min-w-0 truncate">{label}</span>
          </div>
        }
        icon={SearchIcon}
      >
        {Array.isArray(results) && (
          <ChainOfThoughtSearchResults>
            {Array.isArray(results) &&
              results.map((item) => (
                <Tooltip key={item.image_url} content={item.title}>
                  <a
                    className="size-24 overflow-hidden rounded-lg object-cover"
                    href={item.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    <div className="bg-accent size-24">
                      <img
                        className="size-full object-cover"
                        src={item.thumbnail_url}
                        alt={item.title}
                        width={100}
                        height={100}
                      />
                    </div>
                  </a>
                </Tooltip>
              ))}
          </ChainOfThoughtSearchResults>
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "web_fetch") {
    const url = (args as { url: string })?.url;
    let title = url;
    if (typeof result === "string") {
      const potentialTitle = extractTitleFromMarkdown(result);
      if (potentialTitle && potentialTitle.toLowerCase() !== "untitled") {
        title = potentialTitle;
      }
    }
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            <span className="min-w-0 truncate">{t.toolCalls.viewWebPage}</span>
          </div>
        }
        icon={GlobeIcon}
      >
        <ChainOfThoughtSearchResult>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="cursor-pointer"
            >
              {title}
            </a>
          )}
        </ChainOfThoughtSearchResult>
      </ChainOfThoughtStep>
    );
  } else if (name === "ls" || name === "list_cwd") {
    const description = extractDescFromArgs(args) || t.toolCalls.listFolder;
    const path = extractPathFromArgs(args);
    const resultText = resultToText(result);
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            {inlineActionLabel(description, path)}
          </div>
        }
        icon={FolderOpenIcon}
      >
        {resultText && <ToolResultPreview content={resultText} />}
      </ChainOfThoughtStep>
    );
  } else if (name === "read_file" || name === "read_file_range") {
    const description = extractDescFromArgs(args) || t.toolCalls.readFile;
    const path = extractPathFromArgs(args);
    const resultText = resultToText(result);
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            {inlineActionLabel(description, path)}
          </div>
        }
        icon={BookOpenTextIcon}
      >
        {resultText && <ToolResultPreview content={resultText} />}
      </ChainOfThoughtStep>
    );
  } else if (
    name === "write_file" ||
    name === "str_replace" ||
    name === "edit_code"
  ) {
    const description = extractDescFromArgs(args) || t.toolCalls.writeFile;
    const path = extractPathFromArgs(args);
    const resultText = resultToText(result);
    // Show diff preview if available in result
    const diffPreview =
      typeof result === "object" && result && "diff_preview" in result
        ? String(result.diff_preview)
        : null;

    const isApproval = typeof result === "string" && isApprovalRequest(result);
    if (isApproval) {
      return (
        <ChainOfThoughtStep
          key={id}
          label={t.toolApproval.requiresApproval}
          icon={ShieldAlertIcon}
        >
          <ToolApprovalCard content={result as string} />
        </ChainOfThoughtStep>
      );
    }

    if (isLoading && isLast && autoOpen && autoSelect && path) {
      setTimeout(() => {
        const url = new URL(
          `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
        ).toString();
        if (selectedArtifact === url) {
          return;
        }
        select(url, true);
        setOpen(true);
      }, 100);
    }

    return (
      <ChainOfThoughtStep
        key={id}
        className="cursor-pointer"
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            {inlineActionLabel(description, path)}
          </div>
        }
        icon={NotebookPenIcon}
        onClick={() => {
          select(
            new URL(
              `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
            ).toString(),
          );
          setOpen(true);
        }}
      >
        {diffPreview && (
          <ToolResultPreview content={diffPreview} language="diff" />
        )}
        {resultText && !diffPreview && (
          <ToolResultPreview content={resultText} />
        )}
      </ChainOfThoughtStep>
    );
  } else if (
    name === "bash" ||
    name === "exec_shell" ||
    name === "mcp_exec_shell"
  ) {
    const description = extractDescFromArgs(args) || t.toolCalls.executeCommand;

    const isApproval = typeof result === "string" && isApprovalRequest(result);
    if (isApproval) {
      return (
        <ChainOfThoughtStep
          key={id}
          label={t.toolApproval.requiresApproval}
          icon={ShieldAlertIcon}
        >
          <ToolApprovalCard content={result as string} />
        </ChainOfThoughtStep>
      );
    }

    const command: string | undefined = (args as { command: string })?.command;
    const resultText = resultToText(result);
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            {inlineActionLabel(description, command)}
          </div>
        }
        icon={SquareTerminalIcon}
      >
        {command && (
          <CodeBlock
            className="mx-0 cursor-pointer border-none px-0"
            showLineNumbers={false}
            language="bash"
            code={command}
          />
        )}
        {resultText && !isApproval && (
          <ToolResultPreview content={resultText} language="bash" />
        )}
      </ChainOfThoughtStep>
    );
  } else if (name === "ask_clarification" || name === "ask_user_question") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            <span className="min-w-0 truncate">{t.toolCalls.needYourHelp}</span>
          </div>
        }
        icon={MessageCircleQuestionMarkIcon}
      ></ChainOfThoughtStep>
    );
  } else if (isTeamCallToolName(name)) {
    const target = extractTeamCallTarget(args);
    const description = t.messageGrouping.callTeammate;
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel("call", isActive, t.taor.think)}
              className="shrink-0"
            />
            {inlineActionLabel(description, target)}
          </div>
        }
        icon={UsersIcon}
      />
    );
  } else if (name === "write_todos" || name === "todo_write") {
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            <span className="min-w-0 truncate">{t.toolCalls.writeTodos}</span>
          </div>
        }
        icon={ListTodoIcon}
      />
    );
  } else {
    const description = extractDescFromArgs(args) ?? t.toolCalls.useTool(name);
    const path = extractPathFromArgs(args);
    const resultText = resultToText(result);
    return (
      <ChainOfThoughtStep
        key={id}
        label={
          <div className="flex min-w-0 items-center gap-2">
            <TAORBadge
              phase="act"
              active={isActive}
              labelOverride={actionStateLabel(
                inferToolActionKind(name, args),
                isActive,
                t.taor.think,
              )}
              className="shrink-0"
            />
            {inlineActionLabel(description, path)}
          </div>
        }
        icon={WrenchIcon}
      >
        {resultText && <ToolResultPreview content={resultText} />}
      </ChainOfThoughtStep>
    );
  }
}

const MAX_PREVIEW_LINES = 8;
const MAX_SEARCH_RESULTS = 8;

interface SearchResultItem {
  title: string;
  url?: string;
}

function isSearchResultItem(value: unknown): value is SearchResultItem {
  const record = asRecord(value);
  return (
    !!record &&
    (typeof record.title === "string" || typeof record.url === "string")
  );
}

function extractSearchResults(
  result: string | Record<string, unknown> | unknown[] | undefined,
): SearchResultItem[] {
  const parsed = typeof result === "string" ? parseMaybeJson(result) : result;
  const candidates = collectSearchResultCandidates(parsed);
  const results: SearchResultItem[] = [];
  const seen = new Set<string>();
  for (const item of candidates) {
    if (isSearchResultItem(item)) {
      const label = item.title || item.url;
      if (!label) continue;
      const key = item.url || label;
      if (seen.has(key)) continue;
      seen.add(key);
      results.push({
        title: compactReasoningSummary(label, 96),
        url: item.url,
      });
      if (results.length >= MAX_SEARCH_RESULTS) break;
      continue;
    }
    const record = asRecord(item);
    if (!record) continue;
    const title = firstStringValue(record, [
      "title",
      "name",
      "text",
      "snippet",
      "description",
    ]);
    const url = firstStringValue(record, [
      "url",
      "link",
      "href",
      "source_url",
      "sourceUrl",
    ]);
    const label = title || url;
    if (!label) continue;
    const key = url || label;
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ title: compactReasoningSummary(label, 96), url });
    if (results.length >= MAX_SEARCH_RESULTS) break;
  }
  return results;
}

function collectSearchResultCandidates(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  const record = asRecord(value);
  if (!record) return [];
  for (const key of [
    "results",
    "items",
    "sources",
    "pages",
    "web_results",
    "webResults",
    "search_results",
    "searchResults",
  ]) {
    const list = record[key];
    if (Array.isArray(list)) return list;
  }
  return [record];
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function firstStringValue(
  record: Record<string, unknown>,
  keys: string[],
): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return undefined;
}

function parseMaybeJson(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch (e) {
    swallow(e);
    return undefined;
  }
}

function SearchResultsList({ results }: { results: SearchResultItem[] }) {
  const { t } = useI18n();
  const [isOpen, setIsOpen] = useState(true);
  if (results.length === 0) return null;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="mt-1">
      <CollapsibleTrigger className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs transition-colors">
        <ChevronDownIcon
          className={cn(
            "size-3.5 transition-transform",
            isOpen ? "rotate-180" : "",
          )}
        />
        {t.liveToolTimeline.searchedPages(results.length)}
      </CollapsibleTrigger>
      <CollapsibleContent className="mt-1 data-[state=closed]:animate-out data-[state=open]:animate-in">
        <ChainOfThoughtSearchResults className="flex-col items-stretch gap-1 overflow-visible">
          {results.map((item, index) => (
            <ChainOfThoughtSearchResult
              key={`${item.url ?? item.title}-${index}`}
              className="w-fit max-w-full justify-start gap-2 rounded-md bg-transparent px-0 py-0 text-sm text-muted-foreground shadow-none hover:text-foreground"
            >
              <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground/70">
                {index + 1}
              </span>
              {item.url ? (
                <a
                  className="min-w-0 truncate"
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {item.title}
                </a>
              ) : (
                <span className="min-w-0 truncate">{item.title}</span>
              )}
            </ChainOfThoughtSearchResult>
          ))}
        </ChainOfThoughtSearchResults>
      </CollapsibleContent>
    </Collapsible>
  );
}

function resultToText(
  result: string | Record<string, unknown> | unknown[] | undefined,
): string | null {
  if (result == null) return null;
  if (typeof result === "string") return result;
  try {
    return JSON.stringify(result, null, 2);
  } catch (e) {
    swallow(e);
    return String(result);
  }
}

function ToolResultPreview({
  content,
  language,
}: {
  content: string;
  language?: BundledLanguage;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const lines = content.split("\n");
  const isLong = lines.length > MAX_PREVIEW_LINES;
  const displayContent = isOpen
    ? content
    : lines.slice(0, MAX_PREVIEW_LINES).join("\n");
  const { t } = useI18n();

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen} className="mt-1">
      <div className="relative">
        <CodeBlock
          className="mx-0 border-none px-0 text-xs"
          showLineNumbers={false}
          language={language ?? ("text" as BundledLanguage)}
          code={displayContent}
        />
        {isLong && !isOpen && (
          <div className="from-background/95 pointer-events-none absolute right-0 bottom-0 left-0 h-8 bg-gradient-to-t to-transparent" />
        )}
      </div>
      {isLong && (
        <CollapsibleTrigger className="text-muted-foreground hover:text-foreground mt-0.5 flex items-center gap-1 text-xs transition-colors hover:underline">
          <ChevronDownIcon
            className={cn(
              "size-3 transition-transform",
              isOpen ? "rotate-180" : "",
            )}
          />
          {isOpen ? t.toolCalls.lessSteps : t.toolCalls.clickToViewContent}
        </CollapsibleTrigger>
      )}
    </Collapsible>
  );
}

interface GenericCoTStep<T extends string = string> {
  id?: string;
  messageId?: string;
  type: T;
  iteration?: number;
}

interface CoTReasoningStep extends GenericCoTStep<"reasoning"> {
  reasoning: string | null;
}

interface CoTActionCallbackStep extends GenericCoTStep<"actionCallback"> {
  actionText: string;
}

interface CoTToolCallStep extends GenericCoTStep<"toolCall"> {
  name: string;
  args: Record<string, unknown>;
  result?: string | Record<string, unknown> | unknown[];
}

type CoTStep = CoTReasoningStep | CoTActionCallbackStep | CoTToolCallStep;

interface ReasoningStepGroupItem {
  id: string;
  type: "reasoningGroup";
  steps: CoTReasoningStep[];
}

interface ToolCallTimelineItem {
  id: string;
  type: "toolCall";
  step: CoTToolCallStep;
}

interface ActionCallbackGroupItem {
  id: string;
  type: "actionCallbackGroup";
  steps: CoTActionCallbackStep[];
}

type TimelineItem =
  | ReasoningStepGroupItem
  | ActionCallbackGroupItem
  | ToolCallTimelineItem;

export function hasVisibleMessageGroupContent(
  messages: Message[],
  t?: ReturnType<typeof useI18n>["t"],
): boolean {
  return convertToSteps(messages, t).length > 0;
}

function groupConsecutiveReasoningSteps(steps: CoTStep[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  let currentGroup: ReasoningStepGroupItem | null = null;
  let currentActionGroup: ActionCallbackGroupItem | null = null;

  const flushReasoningGroup = () => {
    if (currentGroup) items.push(currentGroup);
    currentGroup = null;
  };
  const flushActionGroup = () => {
    if (currentActionGroup) items.push(currentActionGroup);
    currentActionGroup = null;
  };

  for (const step of steps) {
    if (step.type === "reasoning") {
      flushActionGroup();
      if (!currentGroup) {
        currentGroup = {
          id: `${step.id ?? "reasoning"}-group`,
          type: "reasoningGroup",
          steps: [],
        };
      }
      currentGroup.steps.push(step);
      continue;
    }

    if (step.type === "actionCallback") {
      flushReasoningGroup();
      if (!currentActionGroup) {
        currentActionGroup = {
          id: `${step.id ?? "action"}-group`,
          type: "actionCallbackGroup",
          steps: [],
        };
      }
      currentActionGroup.steps.push(step);
      continue;
    }

    flushReasoningGroup();
    flushActionGroup();
    items.push({
      id: `${step.messageId ?? step.id ?? "tool"}-${items.length}`,
      type: "toolCall",
      step,
    });
  }

  flushReasoningGroup();
  flushActionGroup();
  return items;
}

function lastTimelineStep(item: TimelineItem): CoTStep {
  if (item.type === "toolCall") return item.step;
  return item.steps[item.steps.length - 1]!;
}

function timelineItemFromStep(step: CoTStep, suffix: string): TimelineItem {
  if (step.type === "toolCall") {
    return {
      id: `${step.messageId ?? step.id ?? "tool"}-${suffix}`,
      type: "toolCall",
      step,
    };
  }
  if (step.type === "actionCallback") {
    return {
      id: `${step.id ?? "action"}-${suffix}`,
      type: "actionCallbackGroup",
      steps: [step],
    };
  }
  return {
    id: `${step.id ?? "reasoning"}-${suffix}`,
    type: "reasoningGroup",
    steps: [step],
  };
}

function leadInStepsBeforeFirstPhase(
  replaySteps: CoTStep[],
  currentStep: CoTStep | null,
): CoTStep[] {
  if (replaySteps.length === 0) return [];
  const firstPhaseIndex = replaySteps.findIndex(isFirstPhaseStep);
  if (firstPhaseIndex > 0) return replaySteps.slice(0, firstPhaseIndex);
  if (firstPhaseIndex === 0) return [];
  return currentStep && isFirstPhaseStep(currentStep) ? replaySteps : [];
}

const FIRST_PHASE_RE =
  /(?:^|\n|\b)(?:phase\s*1\s*[:：.)-]|phase\s+one\b|第\s*(?:一|1)\s*阶段|阶段\s*(?:一|1)\b)/i;

function isFirstPhaseStep(step: CoTStep): boolean {
  return FIRST_PHASE_RE.test(stepText(step));
}

function stepText(step: CoTStep): string {
  if (step.type === "reasoning") return step.reasoning ?? "";
  if (step.type === "actionCallback") return step.actionText;
  const argsText = JSON.stringify(step.args ?? {});
  return `${step.name}\n${argsText}`;
}

function summarizeReasoningGroup(
  group: ReasoningStepGroupItem,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const text = group.steps
    .map((step) => step.reasoning ?? "")
    .find((value) => value.trim());
  return compactReasoningSummary(stripTraceLabelPrefixes(text), 120, t);
}

function summarizeActionGroup(
  group: ActionCallbackGroupItem,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const text = group.steps
    .map((step) => step.actionText)
    .find((value) => value.trim());
  return compactReasoningSummary(stripTraceLabelPrefixes(text), 96, t);
}

function compactReasoningSummary(
  value: string,
  max = 120,
  t?: ReturnType<typeof useI18n>["t"],
): string {
  const normalized = value
    .replace(/\s+/g, " ")
    .replace(/^\s*[-*•]\s+/, "")
    .trim();
  if (!normalized) return t?.messageGrouping.reasoningFallback ?? "整理思考过程";
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max).trimEnd()}...`;
}

function convertToSteps(
  messages: Message[],
  t?: ReturnType<typeof useI18n>["t"],
): CoTStep[] {
  const steps: CoTStep[] = [];
  let iteration = 1;
  let lastStepType: "reasoning" | "toolCall" | null = null;

  const pushReasoningStep = (
    message: Message,
    reasoning: string,
    idSuffix = "reasoning",
  ) => {
    if (!reasoning.trim()) return;
    if (lastStepType === "toolCall") {
      iteration++;
    }
    steps.push({
      id: `${message.id}-${idSuffix}`,
      messageId: message.id,
      type: "reasoning",
      reasoning,
      iteration,
    });
    lastStepType = "reasoning";
  };

  const toToolCallStep = (
    message: Message,
    toolCall: NonNullable<AIMessage["tool_calls"]>[number],
  ): CoTToolCallStep => {
    const step: CoTToolCallStep = {
      id: toolCall.id,
      messageId: message.id,
      type: "toolCall",
      name: toolCall.name,
      args: toolCall.args,
      iteration,
    };
    const toolCallId = toolCall.id;
    if (toolCallId) {
      const toolCallResult = findToolCallResult(toolCallId, messages);
      if (toolCallResult) {
        try {
          const json = JSON.parse(toolCallResult);
          step.result = json;
        } catch (e) {
          swallow(e);
          step.result = toolCallResult;
        }
      }
    }
    return step;
  };

  for (const message of messages) {
    if (message.type === "ai") {
      const tc = (message as AIMessage).tool_calls;
      const visibleToolCalls = (tc ?? []).filter(
        (tool_call) => !isHiddenTimelineToolName(tool_call.name),
      );
      const hasExplicitReasoningContent = Boolean(
        message.additional_kwargs &&
        "reasoning_content" in message.additional_kwargs,
      );
      const rawReasoning = extractReasoningContentFromMessage(message);
      const reasoning = isInternalProgressText(rawReasoning)
        ? null
        : rawReasoning;
      const rawPublicPreamble =
        tc &&
        tc.length > 0 &&
        !reasoning &&
        !isLikelyFinalAnswerContent(message)
          ? extractContentFromMessage(message)
          : null;
      const publicPreamble = isInternalProgressText(rawPublicPreamble)
        ? null
        : rawPublicPreamble;
      const reasoningText = reasoning ?? publicPreamble;
      const reasoningChunks = dedupeTimelineChunks(
        reasoningText
          ? splitReasoningIntoTimelineChunks(reasoningText)
              .map((chunk) =>
                normalizePublicTimelineChunk(chunk, t, {
                  allowPlainThoughts: !hasExplicitReasoningContent,
                }),
              )
              .filter((chunk): chunk is string => Boolean(chunk?.trim()))
          : [],
      );

      const maxStepCount = Math.max(
        reasoningChunks.length,
        visibleToolCalls.length,
      );
      for (let index = 0; index < maxStepCount; index += 1) {
        const reasoningChunk = reasoningChunks[index];
        if (reasoningChunk) {
          if (isActionCallbackText(reasoningChunk)) {
            steps.push({
              id: `${message.id}-action-${index}`,
              messageId: message.id,
              type: "actionCallback",
              actionText: reasoningChunk,
              iteration,
            });
            lastStepType = "toolCall";
          } else {
            pushReasoningStep(message, reasoningChunk, `reasoning-${index}`);
          }
        }
        const tool_call = visibleToolCalls[index];
        if (!tool_call) continue;
        const step = toToolCallStep(message, tool_call);
        steps.push(step);
        lastStepType = "toolCall";
      }
    }
  }
  return steps;
}

function splitReasoningIntoTimelineChunks(reasoning: string): string[] {
  const trimmed = reasoning.trim();
  if (!trimmed) return [];

  const traceChunks = splitLabeledTraceChunks(trimmed);
  if (traceChunks.length > 0) return traceChunks;

  const paragraphChunks = trimmed
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
  if (paragraphChunks.length > 1) return paragraphChunks;

  return trimmed
    .split(
      /(?<=[.!?。！？])\s+(?=(?:Now|Let me|The |This |I |We |继续|现在|接下来|然后)\b)/,
    )
    .map((chunk) => chunk.trim())
    .filter(Boolean);
}

const TRACE_LABEL_RE =
  /(^|\n)\s*(?:<\/?(?:thought|thinking)>\s*)*(Thought|Action|Observation|Final Answer|\u601d\u8003|\u60f3\u6cd5|\u884c\u52a8|\u6267\u884c|\u89c2\u5bdf|\u6700\u7ec8\u7b54\u6848)\s*[:\uff1a]?/gi;

type TraceLabelKind = "thought" | "action" | "observation" | "final";

function splitLabeledTraceChunks(reasoning: string): string[] {
  const matches = Array.from(reasoning.matchAll(TRACE_LABEL_RE));
  if (matches.length === 0) return [];

  const chunks: string[] = [];
  const firstIndex = matches[0]?.index ?? 0;
  chunks.push(...splitPlainReasoningChunks(reasoning.slice(0, firstIndex)));

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index]!;
    const label = normalizeTraceLabel(match[2] ?? "");
    const start = (match.index ?? 0) + match[0].length;
    const end = matches[index + 1]?.index ?? reasoning.length;
    const body = reasoning
      .slice(start, end)
      .replace(/<\/?(?:thought|thinking)>/gi, "")
      .trim();
    if (!body) continue;

    if (label === "final") {
      continue;
    }
    if (label === "action") {
      chunks.push(...splitActionTraceBlock(body));
      continue;
    }
    if (label === "observation") {
      const summary = compactObservationTraceBlock(body);
      if (summary) chunks.push(`Observation: ${summary}`);
      continue;
    }

    chunks.push(
      ...splitPlainReasoningChunks(body).map((chunk) => `Thought: ${chunk}`),
    );
  }

  return chunks.filter(Boolean);
}

function normalizeTraceLabel(label: string): TraceLabelKind {
  const lower = label.toLowerCase();
  if (
    lower.includes("action") ||
    label === "\u884c\u52a8" ||
    label === "\u6267\u884c"
  ) {
    return "action";
  }
  if (lower.includes("observation") || label === "\u89c2\u5bdf") {
    return "observation";
  }
  if (lower.includes("final") || label === "\u6700\u7ec8\u7b54\u6848") {
    return "final";
  }
  return "thought";
}

function splitActionTraceBlock(body: string): string[] {
  const lines = body
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !/^```/.test(line));
  const chunks: string[] = [];
  for (const line of lines.length > 0 ? lines : [body]) {
    const clean = line.replace(/^[-*+]\s+/, "").trim();
    if (!clean) continue;
    const calls = splitInlineToolCalls(clean);
    if (calls.length > 0) {
      chunks.push(...calls.map((call) => `Action: ${call}`));
      continue;
    }
    if (isActionTraceLine(clean)) {
      chunks.push(`Action: ${compactReasoningSummary(clean, 220)}`);
      continue;
    }
    chunks.push(`Thought: ${clean}`);
  }
  return chunks;
}

function isActionTraceLine(line: string): boolean {
  return (
    /^(search|read|write|call|open|update|run|use|fetch)\b/i.test(line) ||
    /^(?:\u4f7f\u7528|\u6267\u884c|\u641c\u7d22|\u8bfb\u53d6|\u5199\u5165|\u8c03\u7528|\u6253\u5f00|\u66f4\u65b0)/.test(
      line,
    )
  );
}

function splitInlineToolCalls(line: string): string[] {
  if (!/^[A-Za-z_][A-Za-z0-9_-]*\s*\(/.test(line)) return [];
  return line
    .split(/\)\s+(?=[A-Za-z_][A-Za-z0-9_-]*\s*\()/)
    .map((part, index, parts) =>
      index < parts.length - 1 && !part.endsWith(")") ? `${part})` : part,
    )
    .map((part) => part.trim())
    .filter(Boolean);
}

function compactObservationTraceBlock(body: string): string {
  const clean = body.replace(/\s+/g, " ").trim();
  if (!clean) return "";
  const lines = body
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const batchLine = lines.find((line) => /^\[\d+\/\d+\s+[^\]]+\]/.test(line));
  const executionLine = lines.find((line) =>
    /\(real tool execution (?:succeeded|failed)\)/i.test(line),
  );
  const targetMatch =
    clean.match(/"query"\s*:\s*"([^"]+)"/) ??
    clean.match(/"url"\s*:\s*"([^"]+)"/) ??
    clean.match(/"path"\s*:\s*"([^"]+)"/);
  const parts = [
    batchLine ?? lines[0] ?? "",
    executionLine ?? "",
    targetMatch?.[1] ? `target: ${targetMatch[1]}` : "",
  ].filter(Boolean);
  return compactReasoningSummary(parts.join(" "), 220);
}

function splitPlainReasoningChunks(reasoning: string): string[] {
  const trimmed = reasoning.trim();
  if (!trimmed) return [];
  return trimmed
    .split(/\n{2,}/)
    .map((chunk) => chunk.trim())
    .filter(Boolean);
}
