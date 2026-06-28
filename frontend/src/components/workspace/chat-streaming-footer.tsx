import {
  ChevronDownIcon,
  CircleIcon,
  EyeIcon,
  Loader2Icon,
  MessageCircleIcon,
  PlayCircleIcon,
  UsersIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { BaseStream } from "@/core/api/use-stream-types";
import { useI18n } from "@/core/i18n/hooks";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { LiveToolTimeline, type LiveToolEvent } from "./live-tool-timeline";
import { getProcessTraceEvents } from "./process-trace-events";
import type { ReasoningMode } from "./reasoning-mode";
import {
  type AgentRunState,
  agentRunBadgeClass,
  agentRunPanelClass,
} from "./agent-run-status";

export interface ChatStreamingFooterProps {
  thread: BaseStream<AgentThreadState>;
  liveToolEvents?: LiveToolEvent[];
  threadId?: string | null;
  mode?: ReasoningMode | "code" | "team";
}

export function ChatStreamingFooter({
  thread,
  liveToolEvents,
  mode = "chat",
}: ChatStreamingFooterProps) {
  const { t } = useI18n();
  const normalizedMode =
    mode === "thinking" || mode === "flash" ? "chat" : mode;
  const isDeepMode = normalizedMode === "deep";
  const isTeamMode = normalizedMode === "team";
  const isWorkflowMode =
    normalizedMode === "react" ||
    normalizedMode === "deep" ||
    normalizedMode === "team" ||
    normalizedMode === "code";
  const displayEvents = useMemo(() => liveToolEvents ?? [], [liveToolEvents]);
  const semanticWorkEvents = useMemo(
    () => getProcessTraceEvents(displayEvents),
    [displayEvents],
  );
  const hasAgentCluster = useMemo(
    () => realAgentParticipants(semanticWorkEvents).length > 0,
    [semanticWorkEvents],
  );
  const isWaitingForAssistantMessage =
    thread.isLoading && !thread.streamingMessage;
  const hasLiveSignals =
    isWaitingForAssistantMessage &&
    isWorkflowMode &&
    semanticWorkEvents.length > 0;
  const shouldShow = isWaitingForAssistantMessage || hasLiveSignals;
  const [isMounted, setIsMounted] = useState(shouldShow);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const autoOpenedForRunRef = useRef(false);

  useEffect(() => {
    if (shouldShow) {
      setIsMounted(true);
      return;
    }

    const timer = window.setTimeout(() => {
      setIsMounted(false);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [shouldShow]);

  useEffect(() => {
    if (!hasLiveSignals) {
      autoOpenedForRunRef.current = false;
      return;
    }

    if (
      !autoOpenedForRunRef.current &&
      (isDeepMode || isTeamMode || normalizedMode === "code")
    ) {
      setDetailsOpen(true);
      autoOpenedForRunRef.current = true;
    }
  }, [hasLiveSignals, isDeepMode, isTeamMode, normalizedMode]);

  if (!isMounted) return null;

  if (!isWorkflowMode || !hasLiveSignals) {
    return (
      <SimpleThinkingFooter
        isVisible={shouldShow}
        isLoading={thread.isLoading}
      />
    );
  }

  return (
    <div
      className={cn(
        "my-2 flex flex-col items-start gap-1.5 transition-all duration-200",
        shouldShow ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0",
      )}
    >
      {hasLiveSignals && (
        <div className="w-full">
          <ProcessHeader
            mode={normalizedMode}
            events={semanticWorkEvents}
            expanded={detailsOpen}
            onToggle={() => setDetailsOpen((value) => !value)}
          />
          {detailsOpen && (
            <div className="mt-1.5 border-l border-border/55 pl-4">
              <LiveToolTimeline
                events={displayEvents}
                className="py-0"
                showAll={isDeepMode}
                groupByAgent={hasAgentCluster}
              />
              {thread.isLoading && (
                <div className="mt-1 flex items-center gap-2 pl-2 text-xs text-muted-foreground">
                  <Loader2Icon className="size-3 animate-spin text-primary" />
                  {isDeepMode
                    ? t.chatStreamingFooter.researching
                    : isTeamMode
                      ? t.chatStreamingFooter.collaborating
                      : t.chatStreamingFooter.processing}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SimpleThinkingFooter({
  isVisible,
  isLoading,
}: {
  isVisible: boolean;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  if (!isVisible) return null;
  return (
    <div
      className={cn(
        "my-2 flex items-center gap-2 border-l border-border/60 pl-3 text-sm text-muted-foreground transition-all duration-200",
        isLoading ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0",
      )}
    >
      <Loader2Icon className="size-4 animate-spin text-primary" />
      <span>{t.chatStreamingFooter.thinking}</span>
    </div>
  );
}

function ProcessHeader({
  mode,
  events,
  expanded,
  onToggle,
}: {
  mode: ReasoningMode | "code" | "team";
  events: LiveToolEvent[];
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useI18n();
  const visibleEvents = semanticHeaderEvents(events);
  const running = visibleEvents.filter(
    (event) => event.status === "running",
  ).length;
  const waiting = visibleEvents.filter(
    (event) => event.status === "waiting_approval",
  ).length;
  const done = visibleEvents.filter((event) => event.status === "done").length;
  const error = visibleEvents.filter(
    (event) => event.status === "error",
  ).length;
  const isDeep = mode === "deep";
  const isTeam = mode === "team";
  const Icon = isDeep ? UsersIcon : isTeam ? UsersIcon : MessageCircleIcon;
  const phase = currentPhase(visibleEvents, mode, t);
  const participants = realAgentParticipants(visibleEvents);
  const total = visibleEvents.length;
  const headerState: AgentRunState =
    error > 0
      ? "error"
      : waiting > 0
        ? "waiting"
        : running > 0
          ? "running"
          : done > 0
            ? "done"
          : "pending";
  const progressLabel =
    total > 0
      ? t.chatStreamingFooter.currentProgress(done + error, total)
      : t.chatStreamingFooter.executing;

  return (
    <button
      type="button"
      data-testid="chat-execution-strip"
      className="group flex w-full items-center justify-between gap-3 rounded-xl border border-border/55 bg-background/90 px-3 py-2.5 text-left text-xs text-muted-foreground shadow-sm backdrop-blur transition-all duration-200 hover:border-border hover:bg-muted/20 hover:shadow-md"
      onClick={onToggle}
      aria-expanded={expanded}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            "flex size-6 items-center justify-center border",
            agentRunPanelClass(headerState),
          )}
        >
          {waiting > 0 ? (
            <CircleIcon className="size-3.5" />
          ) : running > 0 ? (
            <Loader2Icon className="size-3.5 animate-spin" />
          ) : (
            <Icon className="size-3.5" />
          )}
        </span>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2 font-medium text-foreground">
            <span className="shrink-0">{t.chatStreamingFooter.agentExecuting}</span>
            <span className="h-3 w-px shrink-0 bg-border/75" />
            <span className="min-w-0 truncate">{phase.title}</span>
          </div>
          <div className="truncate text-[10px] leading-4">{phase.subtitle}</div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 text-[10px]">
        <span className="hidden rounded bg-muted/60 px-1.5 py-0.5 text-muted-foreground sm:inline">
          {progressLabel}
        </span>
        {participants.length > 0 && (
          <span className="rounded bg-violet-500/10 px-1.5 py-0.5 text-violet-700 dark:text-violet-300">
            {participants.length} Agent
          </span>
        )}
        {running > 0 && (
          <span
            className={cn("rounded px-1.5 py-0.5", agentRunBadgeClass("running"))}
          >
            {running} {t.chatStreamingFooter.running}
          </span>
        )}
        {waiting > 0 && (
          <span
            className={cn("rounded px-1.5 py-0.5", agentRunBadgeClass("waiting"))}
          >
            {waiting} {t.chatStreamingFooter.awaitingConfirmation}
          </span>
        )}
        {done > 0 && (
          <span
            className={cn("rounded px-1.5 py-0.5", agentRunBadgeClass("done"))}
          >
            {done} {t.chatStreamingFooter.done}
          </span>
        )}
        {error > 0 && (
          <span
            className={cn("rounded px-1.5 py-0.5", agentRunBadgeClass("error"))}
          >
            {error} {t.chatStreamingFooter.error}
          </span>
        )}
        <span className="hidden items-center gap-1 rounded bg-muted/50 px-1.5 py-0.5 text-muted-foreground md:inline-flex">
          <EyeIcon className="size-3" />
          {t.chatStreamingFooter.viewResult}
        </span>
        <span className="hidden items-center gap-1 rounded bg-foreground px-1.5 py-0.5 text-background md:inline-flex">
          <PlayCircleIcon className="size-3" />
          {t.chatStreamingFooter.replay}
        </span>
        <ChevronDownIcon
          className={cn(
            "size-3.5 transition-transform group-hover:text-foreground",
            expanded && "rotate-180",
          )}
        />
      </div>
    </button>
  );
}

function semanticHeaderEvents(events: LiveToolEvent[]) {
  return getProcessTraceEvents(events);
}

function realAgentParticipants(events: LiveToolEvent[]): string[] {
  const names = new Set<string>();
  for (const event of events) {
    const name = event.agentName ?? event.subAgentRole ?? event.agentId;
    if (name) names.add(name);
  }
  return Array.from(names);
}

function currentPhase(
  events: LiveToolEvent[],
  mode: ReasoningMode | "code" | "team",
  t: ReturnType<typeof useI18n>["t"],
): { title: string; subtitle: string } {
  const current =
    [...events]
      .reverse()
      .find(
        (event) =>
          event.status === "running" || event.status === "waiting_approval",
      ) ?? events[events.length - 1];
  const participants = realAgentParticipants(events);
  const done = events.filter((event) => event.status === "done").length;
  const total = events.length;
  const suffix =
    total > 0
      ? `${t.chatStreamingFooter.completed} ${done}/${total}${participants.length > 0 ? ` · ${participants.length} ${t.chatStreamingFooter.agentCollaboration}` : ""}`
      : mode === "deep"
        ? t.chatStreamingFooter.readyToBreakdownAndGather
        : t.chatStreamingFooter.readyToExecuteTask;

  if (!current) {
    return {
      title:
        mode === "team"
          ? t.chatStreamingFooter.readyForAgentCollaboration
          : mode === "deep"
            ? t.chatStreamingFooter.readyForDeepTask
            : t.chatStreamingFooter.readyToExecute,
      subtitle: suffix,
    };
  }
  if (current.status === "waiting_approval") {
    return {
      title: t.chatStreamingFooter.awaitingConfirmation,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (current.status === "error") {
    return {
      title: t.chatStreamingFooter.executionError,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (current.name === "todo_write" || /plan|planning/i.test(current.name)) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.updatingPlan
          : t.chatStreamingFooter.planUpdated,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (/web_search|fetch_url|browse|browser|search/i.test(current.name)) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.collectingData
          : t.chatStreamingFooter.dataCollected,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (/read|grep|glob|list/i.test(current.name)) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.readingContext
          : t.chatStreamingFooter.contextRead,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (/(write|edit|replace|create|patch)/i.test(current.name)) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.modifyingArtifacts
          : t.chatStreamingFooter.artifactsModified,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (/shell|bash|exec|test|verify/i.test(current.name)) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.runningVerification
          : t.chatStreamingFooter.verificationDone,
      subtitle: eventSummary(current) || suffix,
    };
  }
  if (
    /agent|swarm|delegate|spawn|team/i.test(current.name) ||
    participants.length > 1
  ) {
    return {
      title:
        current.status === "running"
          ? t.chatStreamingFooter.coordinatingAgents
          : t.chatStreamingFooter.agentsCoordinated,
      subtitle: eventSummary(current) || suffix,
    };
  }
  return {
    title:
      current.status === "running"
        ? t.chatStreamingFooter.processingTask
        : t.chatStreamingFooter.organizingResults,
    subtitle: eventSummary(current) || suffix,
  };
}

function eventSummary(event: LiveToolEvent): string {
  const input = event.input;
  const value =
    firstStringValue(input, [
      "task",
      "description",
      "query",
      "pattern",
      "path",
      "file_path",
      "url",
      "command",
      "cmd",
    ]) ||
    event.agentName ||
    event.subAgentRole ||
    "";
  return compactSummary(value || event.name.replace(/[_-]+/g, " "), 96);
}

function firstStringValue(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

function compactSummary(value: string, max: number): string {
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1)}…`;
}
