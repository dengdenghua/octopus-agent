import { useEffect, useMemo, useState } from "react";
import {
  BotIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleIcon,
  FileTextIcon,
  GlobeIcon,
  Loader2Icon,
  MonitorIcon,
  NetworkIcon,
  PencilLineIcon,
  SquareActivityIcon,
  TerminalIcon,
  XCircleIcon,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { DotProgress } from "@/components/workspace/swarm/dot-progress";

import { deriveAgentPhases, progressForPhases } from "../agent-phases";
import { emitAgentWorkbenchFocus } from "../agent-workbench-events";
import {
  type AgentRunState,
  agentRunAvatarAnimationClass,
  agentRunBadgeClass,
  agentRunHue,
  agentRunIconClass,
  agentRunPanelClass,
  agentRunProgressBarClass,
} from "../agent-run-status";
import { LiveToolTimeline, type LiveToolEvent } from "../live-tool-timeline";
import { getProcessTraceEvents } from "../process-trace-events";

import {
  type ProcessTraceMode,
  shouldOpenProcessTraceByDefault,
} from "./process-trace-visibility";

type MessageAgentRow = {
  id: string;
  name: string;
  label: string;
  status: AgentRunState;
  task: string;
  prompt?: string;
  role?: string;
  avatar?: string;
  currentTool?: string;
  eventCount: number;
};

type TraceSectionKind = "thinking" | "action" | "verification";

type TraceSection = {
  kind: TraceSectionKind;
  title: string;
  summary: string;
  events: LiveToolEvent[];
  openByDefault: boolean;
};

export function ProcessTrace({
  events,
  hasAnswer,
  mode,
  live = false,
}: {
  events: LiveToolEvent[];
  hasAnswer?: boolean;
  mode: ProcessTraceMode;
  live?: boolean;
}) {
  const { t } = useI18n();
  const visibleEvents = useMemo(() => getProcessTraceEvents(events), [events]);
  const phaseState = useMemo(
    () => deriveAgentPhases(events, { hasAnswer }),
    [events, hasAnswer],
  );
  const parallelAgents = useMemo(
    () => deriveMessageAgentRows(events),
    [events],
  );
  const sections = useMemo(
    () =>
      buildTraceSections(
        mergeSectionEvents(visibleEvents, events),
        phaseState.currentPhase?.title ?? "",
        t,
      ),
    [events, visibleEvents, phaseState.currentPhase?.title, t],
  );
  const [open, setOpen] = useState(
    live || shouldOpenProcessTraceByDefault(visibleEvents, hasAnswer, mode),
  );
  const [rawDetailsOpen, setRawDetailsOpen] = useState(false);
  const shouldOpen =
    live || shouldOpenProcessTraceByDefault(visibleEvents, hasAnswer, mode);
  const doneCount = useMemo(
    () => visibleEvents.filter((e) => e.status === "done").length,
    [visibleEvents],
  );
  const totalCount = visibleEvents.length;
  const progress = phaseState.currentPhase
    ? progressForPhases(phaseState.phases, phaseState.currentPhase)
    : null;
  const showAgents = parallelAgents.length > 0;
  const showProcessBody = live || open;
  const hasSectionCards = sections.length > 0;

  useEffect(() => {
    setOpen(shouldOpen);
  }, [shouldOpen]);

  useEffect(() => {
    if (!open) setRawDetailsOpen(false);
  }, [open]);

  return (
    <div
      className={cn(
        "border-l px-3 py-1.5",
        live
          ? "mb-3 border-primary/35"
          : "mb-2 border-border/55 text-muted-foreground",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 py-1 text-left transition-colors hover:text-foreground"
      >
        {showAgents ? (
          <NetworkIcon className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <CircleIcon className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="min-w-0 flex-1 text-sm font-medium text-foreground">
          {showAgents ? t.message.agentCluster : t.message.thinkingProcess}
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {showAgents
            ? t.dispatchCard.parallelTasks(parallelAgents.length)
            : progress
              ? `${progress.current}/${progress.total}`
              : `${doneCount}/${totalCount}`}
        </span>
        <ChevronDownIcon
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open ? "rotate-180" : "rotate-0",
          )}
        />
      </button>
      {showProcessBody && (
        <div className="mt-2 space-y-3">
          {showAgents ? (
            <AgentClusterCard
              agents={parallelAgents.slice(0, open ? 12 : 4)}
              statusLabels={{
                running: t.message.statusViewing,
                waiting: t.message.statusWaiting,
                done: t.message.statusCompleted,
                error: t.message.statusError,
                pending: t.message.statusWaiting,
              }}
            />
          ) : hasSectionCards ? (
            sections.map((section) => (
              <TraceSectionCard key={section.kind} section={section} />
            ))
          ) : (
            phaseState.phases.slice(0, open ? 7 : 3).map((phase) => (
              <div
                key={phase.id}
                className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm"
              >
                {phase.status === "running" ? (
                  <Loader2Icon className="size-3.5 shrink-0 animate-spin text-emerald-600 dark:text-emerald-400" />
                ) : phase.status === "waiting_approval" ? (
                  <CircleIcon className="size-3.5 shrink-0 text-amber-500" />
                ) : phase.status === "done" ? (
                  <CheckCircle2Icon className="size-3.5 shrink-0 text-emerald-500" />
                ) : (
                  <CircleIcon className="size-3.5 shrink-0 text-muted-foreground/45" />
                )}
                <span
                  className={cn(
                    "min-w-0 flex-1 truncate",
                    phase.status === "pending"
                      ? "text-muted-foreground"
                      : "text-foreground",
                  )}
                >
                  {phase.title}
                </span>
              </div>
            ))
          )}
        </div>
      )}
      {open && visibleEvents.length > 0 && (
        <div className="mt-2 border-t border-border/35 pt-2">
          <button
            type="button"
            onClick={() => setRawDetailsOpen((value) => !value)}
            className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted/35 hover:text-foreground"
            aria-expanded={rawDetailsOpen}
          >
            <ChevronDownIcon
              className={cn(
                "size-3.5 shrink-0 transition-transform",
                rawDetailsOpen ? "rotate-180" : "-rotate-90",
              )}
            />
            <span className="font-medium">{t.message.processDetails}</span>
            <span className="ml-auto tabular-nums">
              {t.message.processRecords(visibleEvents.length)}
            </span>
          </button>
          {rawDetailsOpen && (
            <div className="pt-2">
              <LiveToolTimeline events={visibleEvents} showAll />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AgentClusterCard({
  agents,
  statusLabels,
}: {
  agents: MessageAgentRow[];
  statusLabels: Record<MessageAgentRow["status"], string>;
}) {
  const { t } = useI18n();
  return (
    <div className="rounded-xl border border-border/55 bg-background/85 px-3 py-2.5 shadow-sm">
      <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
        <NetworkIcon className="size-4 shrink-0 text-sky-500" />
        <span className="font-medium text-foreground">
          {t.message.agentCluster}
        </span>
        <span className="ml-auto tabular-nums">
          {t.dispatchCard.parallelTasks(agents.length)}
        </span>
      </div>
      <div className="space-y-2">
        {agents.map((agent) => (
          <AgentClusterRow
            key={agent.id}
            agent={agent}
            statusLabel={statusLabels[agent.status]}
          />
        ))}
      </div>
    </div>
  );
}

function AgentClusterRow({
  agent,
  statusLabel,
}: {
  agent: MessageAgentRow;
  statusLabel: string;
}) {
  const progress = agentProgress(agent);
  const progressHue = agentRunHue(agent.status);
  return (
    <div className="group/agent-row relative">
      <button
        type="button"
        onClick={() => emitAgentWorkbenchFocus({ agentId: agent.id })}
        className="flex w-full items-center gap-2 rounded-lg bg-muted/35 px-2.5 py-2 text-left text-sm transition-colors hover:bg-muted/60"
      >
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md border bg-background",
            agentRunPanelClass(agent.status),
          )}
        >
          {agent.avatar ? (
            <span className="text-base leading-none" aria-hidden="true">
              {agent.avatar}
            </span>
          ) : (
            <BotIcon
              className={cn(
                "size-4",
                agentRunIconClass(agent.status),
              )}
            />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-medium text-foreground">
              {agent.name}
            </span>
            {agent.role && (
              <span className="hidden truncate text-xs text-muted-foreground sm:inline">
                {agent.role}
              </span>
            )}
            <span
              className={cn(
                "ml-auto rounded-full px-2 py-0.5 text-[10px]",
                agentRunBadgeClass(agent.status),
              )}
            >
              {statusLabel}
            </span>
          </div>
          <div className="mt-1 flex items-end gap-2">
            <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
              {agent.task}
            </span>
            <div className="flex shrink-0 flex-col items-end gap-1">
              <span className="font-mono text-xs leading-none text-foreground">
                {agent.label}
              </span>
              <DotProgress
                progress={progress}
                hue={progressHue}
                cols={16}
                rows={3}
                className={cn(agentRunAvatarAnimationClass(agent.status))}
              />
            </div>
          </div>
        </div>
        {agent.status === "running" ? (
          <Loader2Icon className="size-3.5 shrink-0 animate-spin text-emerald-600 dark:text-emerald-400" />
        ) : agent.status === "waiting" ? (
          <CircleIcon className="size-3.5 shrink-0 text-amber-500" />
        ) : agent.status === "done" ? (
          <CheckCircle2Icon className="size-3.5 shrink-0 text-emerald-500" />
        ) : agent.status === "error" ? (
          <XCircleIcon className="size-3.5 shrink-0 text-destructive" />
        ) : (
          <CircleIcon className="size-3.5 shrink-0 text-muted-foreground/45" />
        )}
      </button>
      <AgentHoverPreview agent={agent} statusLabel={statusLabel} />
    </div>
  );
}

function AgentHoverPreview({
  agent,
  statusLabel,
}: {
  agent: MessageAgentRow;
  statusLabel: string;
}) {
  const { t } = useI18n();
  const body = agent.prompt || agent.task || t.message.noTaskDescription;
  return (
    <div
      className="pointer-events-none absolute left-8 top-[calc(100%+0.5rem)] z-40 hidden w-[min(42rem,calc(100vw-5rem))] rounded-xl border border-border/60 bg-background/95 p-4 text-left shadow-2xl shadow-black/15 backdrop-blur-xl group-hover/agent-row:block"
      role="tooltip"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-14 shrink-0 items-center justify-center rounded-full border border-border/55 bg-muted/35 text-2xl">
          {agent.avatar || <BotIcon className="size-7 text-muted-foreground" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-lg font-semibold text-foreground">
                {agent.name}
              </div>
              <div className="truncate text-sm text-muted-foreground">
                {agent.role || t.message.assistant}
              </div>
            </div>
            <span className="font-mono text-sm text-foreground">
              {agent.label}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>{statusLabel}</span>
            <span>·</span>
            <span>{t.message.processRecords(agent.eventCount)}</span>
            {agent.currentTool && (
              <>
                <span>·</span>
                <span className="truncate">
                  {t.message.latestTool}: {agent.currentTool}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="mt-4 max-h-80 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-muted/35 p-3 text-sm leading-6 text-foreground">
        {body}
      </div>
    </div>
  );
}

function agentProgress(agent: MessageAgentRow): number {
  if (agent.status === "done" || agent.status === "error") return 1;
  if (agent.status === "pending") return 0.08;
  return Math.max(0.18, Math.min(0.92, 0.28 + agent.eventCount * 0.08));
}

function TraceSectionCard({ section }: { section: TraceSection }) {
  const [open, setOpen] = useState(section.openByDefault);
  const Icon =
    section.kind === "thinking"
      ? PencilLineIcon
      : section.kind === "action"
        ? NetworkIcon
        : SquareActivityIcon;
  const status = section.events.some(
    (event) => event.status === "error",
  )
    ? "error"
    : section.events.some((event) => event.status === "waiting_approval")
      ? "waiting"
      : section.events.some((event) => event.status === "running")
        ? "running"
        : "done";

  return (
    <div className="rounded-xl border border-border/55 bg-background/85 px-3 py-2 shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 text-left"
      >
        {status === "running" ? (
          <Loader2Icon className="size-4 shrink-0 animate-spin text-emerald-600 dark:text-emerald-400" />
        ) : status === "waiting" ? (
          <CircleIcon className="size-4 shrink-0 text-amber-500" />
        ) : status === "error" ? (
          <XCircleIcon className="size-4 shrink-0 text-destructive" />
        ) : (
          <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />
        )}
        <Icon className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-foreground">
              {section.title}
            </span>
            <span className="ml-auto text-[11px] text-muted-foreground">
              {section.summary}
            </span>
          </div>
          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
            <div
              className={cn(
                "h-full transition-all",
                agentRunProgressBarClass(status),
              )}
              style={{ width: `${section.events.length > 0 ? 100 : 0}%` }}
            />
          </div>
        </div>
        <ChevronDownIcon
          className={cn(
            "size-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <div className="mt-3 space-y-1.5 border-l border-border/45 pl-3">
          {section.events.map((event) => (
            <TraceEventLine key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}

function TraceEventLine({ event }: { event: LiveToolEvent }) {
  const Icon =
    event.name === "read_file"
      ? FileTextIcon
      : event.name === "shell_command" || event.name === "exec_shell"
        ? TerminalIcon
        : event.name === "web_search"
          ? GlobeIcon
          : MonitorIcon;
  const target = firstString(event.input, [
    "path",
    "file_path",
    "filepath",
    "filename",
    "command",
    "query",
    "url",
    "target",
  ]);
  const label =
    typeof event.thought === "string" && event.thought.trim()
      ? event.thought.trim()
      : typeof event.observation === "string" && event.observation.trim()
        ? event.observation.trim()
        : target
          ? `${event.name.replace(/[_-]+/g, " ")} ${target}`
          : event.name.replace(/[_-]+/g, " ");
  return (
    <div className="flex items-start gap-2 text-[12px] text-muted-foreground">
      {event.status === "running" ? (
        <Loader2Icon className="mt-0.5 size-3.5 shrink-0 animate-spin text-emerald-600 dark:text-emerald-400" />
      ) : event.status === "waiting_approval" ? (
        <CircleIcon className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
      ) : event.status === "error" ? (
        <XCircleIcon className="mt-0.5 size-3.5 shrink-0 text-destructive" />
      ) : (
        <CheckCircle2Icon className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
      )}
      <Icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-foreground">{label}</div>
        <div className="truncate text-[11px] text-muted-foreground">
          {event.name.replace(/[_-]+/g, " ")}
        </div>
      </div>
    </div>
  );
}

function mergeSectionEvents(
  visibleEvents: LiveToolEvent[],
  rawEvents: LiveToolEvent[],
): LiveToolEvent[] {
  const byId = new Map(visibleEvents.map((event) => [event.id, event]));
  for (const event of rawEvents) {
    const hasPublicThinking =
      event.name === "model_reasoning" ||
      Boolean(event.thought?.trim()) ||
      Boolean(event.observation?.trim());
    if (hasPublicThinking && !byId.has(event.id)) {
      byId.set(event.id, event);
    }
  }
  return Array.from(byId.values()).sort((a, b) => a.startedAt - b.startedAt);
}

function buildTraceSections(
  events: LiveToolEvent[],
  phaseTitle: string,
  t: ReturnType<typeof useI18n>["t"],
): TraceSection[] {
  const thinking = events.filter(
    (event) =>
      Boolean(event.thought?.trim()) ||
      Boolean(event.observation?.trim()) ||
      event.name === "model_reasoning",
  );
  const action = events.filter((event) =>
    /read|write|edit|shell|exec|search|fetch|browse|web_search|call_agent|todo_write/i.test(
      event.name,
    ),
  );
  const verification = events.filter((event) =>
    /verify|check|test|validate|review|approval/i.test(event.name),
  );
  const remainder = events.filter(
    (event) =>
      !thinking.includes(event) &&
      !action.includes(event) &&
      !verification.includes(event),
  );

  const sections: TraceSection[] = [];
  if (thinking.length > 0) {
    sections.push({
      kind: "thinking",
      title: t.message.thinkingProcess,
      summary: phaseTitle || t.message.thinking,
      events: thinking,
      openByDefault: true,
    });
  }
  if (action.length > 0) {
    sections.push({
      kind: "action",
      title: t.message.execution,
      summary: t.message.actionCount(action.length),
      events: action,
      openByDefault: true,
    });
  }
  if (verification.length > 0) {
    sections.push({
      kind: "verification",
      title: t.message.verification,
      summary: t.message.checkCount(verification.length),
      events: verification,
      openByDefault: false,
    });
  }
  if (sections.length === 0 && remainder.length > 0) {
    sections.push({
      kind: "action",
      title: t.message.process,
      summary: t.message.processRecords(remainder.length),
      events: remainder,
      openByDefault: true,
    });
  }
  return sections;
}

function deriveMessageAgentRows(events: LiveToolEvent[]): MessageAgentRow[] {
  const byId = new Map<string, MessageAgentRow>();
  for (const event of events) {
    const id =
      event.agentId ??
      (event.parentToolUseId && event.subAgentRole
        ? `${event.parentToolUseId}:${event.subAgentRole}`
        : undefined) ??
      event.subAgentRole ??
      event.agentName;
    if (!id || id === "__main__") continue;
    const existing = byId.get(id);
    const status =
      event.status === "error"
        ? "error"
        : event.status === "done"
          ? "done"
          : event.status === "waiting_approval"
            ? "waiting"
            : event.status === "running"
              ? "running"
              : "pending";
    const prompt =
      firstString(event.input, ["prompt", "task", "description", "query"]) ||
      event.thought ||
      existing?.prompt ||
      "";
    byId.set(id, {
      id,
      name:
        event.subagentCodename ??
        event.agentName ??
        existing?.name ??
        event.subAgentRole ??
        id,
      label: existing?.label ?? String(byId.size + 1).padStart(2, "0"),
      status:
        existing?.status === "running" || existing?.status === "waiting"
          ? existing.status
          : status,
      task: existing?.task || prompt || event.name.replace(/[_-]+/g, " "),
      prompt: prompt || existing?.prompt,
      role: event.subAgentRole ?? existing?.role,
      avatar: event.subagentAvatar ?? existing?.avatar,
      currentTool: event.name.replace(/[_-]+/g, " "),
      eventCount: (existing?.eventCount ?? 0) + 1,
    });
  }
  if (byId.size > 0) return Array.from(byId.values()).slice(0, 12);

  // No real sub-agent events — don't fabricate. See parallel comment
  // in agent-workbench-panel.tsx for the rationale (was creating fake
  // swarm tiles in single-agent runs).
  return [];
}

function firstString(
  input: Record<string, unknown> | undefined,
  keys: string[],
) {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}
