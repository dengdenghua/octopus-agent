import {
  ChevronDownIcon,
  CircleIcon,
  DownloadIcon,
  FileTextIcon,
  Loader2Icon,
  MessageCircleIcon,
  MonitorIcon,
  SquareActivityIcon,
  SquareIcon,
  UsersIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

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

export interface PersistentRunFooterProps extends ChatStreamingFooterProps {
  hasResult?: boolean;
  onOpenWorkbench?: () => void;
  onOpenResult?: () => void;
  onExportReplay?: () => void;
  onStop?: () => void;
  className?: string;
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
        "my-2 flex flex-col items-start gap-2 transition-all duration-200",
        shouldShow ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0",
      )}
    >
      {hasLiveSignals && (
        <div className="w-full overflow-hidden rounded-2xl border border-border/60 bg-background/85 p-2.5 shadow-sm shadow-black/[0.03] backdrop-blur">
          <div className="mb-2 flex min-w-0 items-center justify-between gap-2 px-1 text-[11px] text-muted-foreground">
            <div className="flex min-w-0 items-center gap-2">
              <span className="relative flex size-2.5 shrink-0 items-center justify-center">
                <span className="absolute inline-flex size-2.5 animate-ping rounded-full bg-emerald-500/25" />
                <span className="relative inline-flex size-1.5 rounded-full bg-emerald-500" />
              </span>
              <span className="truncate font-medium text-foreground">
                {isTeamMode
                  ? t.chatStreamingFooter.collaborating
                  : normalizedMode === "code"
                    ? t.chatStreamingFooter.coding
                    : isDeepMode
                      ? t.chatStreamingFooter.researching
                      : t.chatStreamingFooter.processing}
              </span>
            </div>
            <div className="hidden shrink-0 items-center gap-1.5 sm:flex">
              <span className="inline-flex items-center gap-1 rounded-full bg-muted/55 px-2 py-0.5">
                <SquareActivityIcon className="size-3" />
                {t.agentWorkbench.activityTrace}
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-muted/55 px-2 py-0.5">
                <MonitorIcon className="size-3" />
                {t.agentWorkbench.computerViewLabel}
              </span>
            </div>
          </div>
          <ProcessHeader
            mode={normalizedMode}
            events={semanticWorkEvents}
            expanded={detailsOpen}
            onToggle={() => setDetailsOpen((value) => !value)}
            embedded
          />
          <LiveWorkbenchStrip
            mode={normalizedMode}
            events={semanticWorkEvents}
          />
          {detailsOpen && (
            <div className="mt-2 border-l border-border/55 pl-4">
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

export function PersistentRunFooter({
  thread,
  liveToolEvents,
  mode = "chat",
  hasResult = false,
  onOpenWorkbench,
  onOpenResult,
  onExportReplay,
  onStop,
  className,
}: PersistentRunFooterProps) {
  const { t } = useI18n();
  const normalizedMode =
    mode === "thinking" || mode === "flash" ? "chat" : mode;
  const displayEvents = useMemo(() => liveToolEvents ?? [], [liveToolEvents]);
  const semanticWorkEvents = useMemo(
    () => getProcessTraceEvents(displayEvents),
    [displayEvents],
  );
  const visibleEvents = semanticHeaderEvents(semanticWorkEvents);
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
  const total = visibleEvents.length;
  const participants = realAgentParticipants(visibleEvents);
  const isActive = thread.isLoading || running > 0 || waiting > 0;
  const shouldShow = isActive || total > 0 || hasResult;
  const [isMounted, setIsMounted] = useState(shouldShow);

  useEffect(() => {
    if (shouldShow) {
      setIsMounted(true);
      return;
    }
    const timer = window.setTimeout(() => setIsMounted(false), 180);
    return () => window.clearTimeout(timer);
  }, [shouldShow]);

  if (!isMounted) return null;

  const runState: AgentRunState =
    thread.error || error > 0
      ? "error"
      : waiting > 0
        ? "waiting"
        : isActive
          ? "running"
          : total > 0 || hasResult
            ? "done"
            : "pending";
  const phase =
    total > 0
      ? currentPhase(visibleEvents, normalizedMode, t)
      : {
          title: thread.isLoading
            ? t.chatStreamingFooter.thinking
            : hasResult
              ? t.chatStreamingFooter.completed
              : t.chatStreamingFooter.readyToExecute,
          subtitle:
            normalizedMode === "team"
              ? t.chatStreamingFooter.readyForAgentCollaboration
              : normalizedMode === "code"
                ? t.chatStreamingFooter.readyToHandleCodeTask
                : t.chatStreamingFooter.readyToExecuteTask,
        };
  const statusLabel =
    runState === "error"
      ? t.chatStreamingFooter.error
      : runState === "waiting"
        ? t.chatStreamingFooter.awaitingConfirmation
        : runState === "done"
          ? t.chatStreamingFooter.completed
          : runState === "running"
            ? t.chatStreamingFooter.running
            : t.chatStreamingFooter.processing;
  const completedCount = Math.min(total, done + error);

  return (
    <div
      className={cn(
        "shrink-0 border-t border-border/60 bg-background/92 px-2 py-2 shadow-[0_-12px_28px_-24px_rgba(0,0,0,0.45)] backdrop-blur-xl transition-all duration-200",
        shouldShow ? "translate-y-0 opacity-100" : "translate-y-2 opacity-0",
        className,
      )}
    >
      <div className="mx-auto flex min-h-12 w-full max-w-[min(1040px,calc(100vw-1rem))] items-center gap-2">
        <div
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg border",
            agentRunPanelClass(runState),
          )}
        >
          {runState === "running" ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : runState === "waiting" ? (
            <CircleIcon className="size-4" />
          ) : runState === "done" ? (
            <SquareActivityIcon className="size-4" />
          ) : runState === "error" ? (
            <SquareIcon className="size-4" />
          ) : (
            <MonitorIcon className="size-4" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 text-xs font-semibold text-foreground">
              {statusLabel}
            </span>
            <span className="min-w-0 truncate text-xs text-muted-foreground">
              {phase.title}
            </span>
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">{phase.subtitle}</span>
            {total > 0 && (
              <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 font-mono text-[10px]">
                {completedCount}/{total}
              </span>
            )}
            {participants.length > 0 && (
              <span className="hidden shrink-0 rounded-full bg-violet-500/10 px-1.5 py-0.5 text-[10px] text-violet-700 sm:inline dark:text-violet-300">
                {participants.length} {t.chatStreamingFooter.agentCollaboration}
              </span>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {onOpenWorkbench && (
            <FooterActionButton
              label={t.chatStreamingFooter.viewMachine}
              onClick={onOpenWorkbench}
            >
              <MonitorIcon className="size-3.5" />
              <span className="hidden sm:inline">
                {t.chatStreamingFooter.viewMachine}
              </span>
            </FooterActionButton>
          )}
          {hasResult && onOpenResult && (
            <FooterActionButton
              label={t.chatStreamingFooter.viewResult}
              onClick={onOpenResult}
            >
              <FileTextIcon className="size-3.5" />
              <span className="hidden sm:inline">
                {t.chatStreamingFooter.viewResult}
              </span>
            </FooterActionButton>
          )}
          {onExportReplay && (
            <FooterActionButton
              label={t.share.exportReplay}
              onClick={onExportReplay}
            >
              <DownloadIcon className="size-3.5" />
              <span className="hidden md:inline">{t.share.exportReplay}</span>
            </FooterActionButton>
          )}
          {isActive && onStop && (
            <FooterActionButton
              label={t.common.stop}
              onClick={onStop}
              className="text-destructive hover:border-destructive/30 hover:bg-destructive/10"
            >
              <SquareIcon className="size-3.5" />
              <span className="hidden sm:inline">{t.common.stop}</span>
            </FooterActionButton>
          )}
        </div>
      </div>
    </div>
  );
}

function FooterActionButton({
  children,
  label,
  onClick,
  className,
}: {
  children: ReactNode;
  label: string;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      title={label}
      className={cn(
        "inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-border/55 bg-background/70 px-2.5 text-xs font-medium text-foreground shadow-sm transition-colors hover:border-primary/25 hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35",
        className,
      )}
    >
      {children}
    </button>
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
        "my-2 flex items-center gap-2 text-sm text-muted-foreground transition-all duration-200",
        isLoading ? "translate-y-0 opacity-100" : "-translate-y-1 opacity-0",
      )}
    >
      <div className="flex min-w-0 items-center gap-2 rounded-xl border border-border/55 bg-background/85 px-3 py-2 shadow-sm shadow-black/[0.025] backdrop-blur">
        <span className="relative flex size-3 shrink-0 items-center justify-center">
          <span className="absolute inline-flex size-3 animate-ping rounded-full bg-primary/20" />
          <span className="relative inline-flex size-1.5 rounded-full bg-primary" />
        </span>
        <span className="shrink-0 font-medium text-foreground">
          {t.chatStreamingFooter.thinking}
        </span>
        <span className="flex shrink-0 items-center gap-0.5" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <span
              key={index}
              className="size-1 animate-pulse rounded-full bg-primary/55"
              style={{ animationDelay: `${index * 140}ms` }}
            />
          ))}
        </span>
        <span className="hidden min-w-0 items-center gap-1 text-[11px] text-muted-foreground sm:flex">
          <SquareActivityIcon className="size-3" />
          {t.agentWorkbench.activityTrace}
        </span>
      </div>
    </div>
  );
}

function ProcessHeader({
  mode,
  events,
  expanded,
  onToggle,
  embedded = false,
}: {
  mode: ReasoningMode | "code" | "team";
  events: LiveToolEvent[];
  expanded: boolean;
  onToggle: () => void;
  embedded?: boolean;
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

  return (
    <button
      type="button"
      className={cn(
        "group flex w-full items-center justify-between gap-3 rounded-xl text-left text-xs text-muted-foreground transition-colors hover:bg-muted/25",
        embedded
          ? "px-1.5 py-1.5"
          : "border border-border/50 bg-background/70 px-2.5 py-2 shadow-sm shadow-black/[0.025] backdrop-blur",
      )}
      onClick={onToggle}
      aria-expanded={expanded}
    >
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            "flex size-6 items-center justify-center rounded-lg border",
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
          <div className="font-medium text-foreground">{phase.title}</div>
          <div className="truncate text-[10px] leading-4">{phase.subtitle}</div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 text-[10px]">
        {participants.length > 0 && (
          <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-violet-700 dark:text-violet-300">
            {participants.length} Agent
          </span>
        )}
        {running > 0 && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              agentRunBadgeClass("running"),
            )}
          >
            {running} {t.chatStreamingFooter.running}
          </span>
        )}
        {waiting > 0 && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              agentRunBadgeClass("waiting"),
            )}
          >
            {waiting} {t.chatStreamingFooter.awaitingConfirmation}
          </span>
        )}
        {done > 0 && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              agentRunBadgeClass("done"),
            )}
          >
            {done} {t.chatStreamingFooter.done}
          </span>
        )}
        {error > 0 && (
          <span
            className={cn(
              "rounded-full px-2 py-0.5",
              agentRunBadgeClass("error"),
            )}
          >
            {error} {t.chatStreamingFooter.error}
          </span>
        )}
        {total > 0 && (
          <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">
            {done + error}/{total}
          </span>
        )}
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

function LiveWorkbenchStrip({
  mode,
  events,
}: {
  mode: ReasoningMode | "code" | "team";
  events: LiveToolEvent[];
}) {
  const { t } = useI18n();
  const participants = participantSummaries(events);
  const current =
    [...events]
      .reverse()
      .find(
        (event) =>
          event.status === "running" || event.status === "waiting_approval",
      ) ?? events[events.length - 1];
  const computerLabel = current
    ? `${workbenchKindLabel(current, t)} · ${eventSummary(current)}`
    : t.agentWorkbench.computerViewHint;
  const activityLabel =
    participants.length > 0
      ? `${participants.length} ${t.chatStreamingFooter.agentCollaboration}`
      : t.agentWorkbench.eventsCount(events.length);

  return (
    <div className="mt-2 grid gap-1.5 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.9fr)]">
      <div className="flex min-w-0 items-center gap-2 rounded-xl bg-muted/35 px-2.5 py-2">
        <SquareActivityIcon className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-foreground">
            {mode === "team"
              ? t.message.agentCluster
              : t.agentWorkbench.activityTrace}
          </div>
          <div className="truncate text-[11px] text-muted-foreground">
            {activityLabel}
          </div>
        </div>
        <LivePulseDots />
      </div>
      <div className="flex min-w-0 items-center gap-2 rounded-xl bg-muted/35 px-2.5 py-2">
        <MonitorIcon className="size-4 shrink-0 text-sky-600 dark:text-sky-400" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-foreground">
            {t.agentWorkbench.computerViewLabel}
          </div>
          <div className="truncate text-[11px] text-muted-foreground">
            {computerLabel}
          </div>
        </div>
      </div>
      {participants.length > 0 && (
        <div className="flex min-w-0 flex-wrap gap-1.5 sm:col-span-2">
          {participants.slice(0, 4).map((participant, index) => (
            <span
              key={participant.name}
              title={participant.name}
              className={cn(
                "inline-flex min-w-0 items-center gap-1.5 rounded-full px-2 py-1 text-[11px]",
                agentRunBadgeClass(participant.status),
              )}
            >
              <span className="font-mono text-[10px]" aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span className="truncate">
                {t.message.agent} {String(index + 1).padStart(2, "0")}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function LivePulseDots() {
  return (
    <span className="flex shrink-0 items-center gap-0.5" aria-hidden="true">
      {[0, 1, 2].map((index) => (
        <span
          key={index}
          className="size-1.5 animate-pulse rounded-full bg-emerald-500/65"
          style={{ animationDelay: `${index * 140}ms` }}
        />
      ))}
    </span>
  );
}

function participantSummaries(
  events: LiveToolEvent[],
): { name: string; status: AgentRunState }[] {
  const byName = new Map<string, AgentRunState>();
  for (const event of events) {
    const name = event.agentName ?? event.subAgentRole ?? event.agentId;
    if (!name) continue;
    const current = byName.get(name);
    const next =
      event.status === "error"
        ? "error"
        : event.status === "waiting_approval"
          ? "waiting"
          : event.status === "running"
            ? "running"
            : event.status === "done"
              ? "done"
              : "pending";
    if (next === "error") {
      byName.set(name, next);
      continue;
    }
    if (current === "running" || current === "waiting") continue;
    byName.set(name, next);
  }
  return Array.from(byName.entries()).map(([name, status]) => ({
    name,
    status,
  }));
}

function workbenchKindLabel(
  event: LiveToolEvent,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (/shell|bash|terminal|exec|test|verify/i.test(event.name)) {
    return t.agentWorkbench.kindTerminal;
  }
  if (/browser|browse|fetch|url/i.test(event.name)) {
    return t.agentWorkbench.kindBrowser;
  }
  if (/search/i.test(event.name)) return t.agentWorkbench.kindSearch;
  if (/read|grep|glob|list/i.test(event.name)) return t.agentWorkbench.kindRead;
  if (/(write|edit|replace|create|patch)/i.test(event.name)) {
    return t.agentWorkbench.kindFile;
  }
  if (/todo|plan/i.test(event.name)) return t.agentWorkbench.kindTodos;
  if (/agent|swarm|delegate|spawn|team/i.test(event.name)) {
    return t.agentWorkbench.kindAgent;
  }
  return t.agentWorkbench.executingTask;
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
