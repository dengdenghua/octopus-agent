import {
  CheckIcon,
  CircleDashedIcon,
  FileTextIcon,
  GitForkIcon,
  LoaderCircleIcon,
  ListChecksIcon,
  MonitorIcon,
  PauseIcon,
  PlusIcon,
  ActivityIcon,
  PlayIcon,
  SparklesIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AgentStatusPills } from "./agent-status-pills";
import { DispatchComposer } from "./dispatch-composer";
import { TraceFeed } from "./trace-feed";
import type { SwarmSession, TraceEntry } from "./types";

type View = "tasks" | "computer" | "report";
type SessionMode = NonNullable<SwarmSession["mode"]>;

interface Props {
  session: SwarmSession;
  selectedAgentId: string;
  onSelectAgent: (id: string) => void;
  onClose?: () => void;
}

/**
 * Right-side workbench that visualises a swarm session. Mirrors Kimi's
 * "Computer" panel: header with live status, a view switcher, a scrollable
 * content area, and an agent pill row at the bottom.
 */
export function AgentWorkbenchPanel({
  session,
  selectedAgentId,
  onSelectAgent,
  onClose,
}: Props) {
  const { t } = useI18n();
  const [view, setView] = useState<View>("tasks");
  const [mode, setMode] = useState<SessionMode>(session.mode ?? "live");
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayPlaying, setReplayPlaying] = useState(false);
  const [replaySpeed, setReplaySpeed] = useState(1);
  const hasAgents = session.agents.length > 0;
  const isThreadTimeline = session.id.startsWith("thread-");
  // Composer is only for the standalone/manual workbench. Thread-mirrored
  // sessions are rendered as the agent's live timeline, not as a template.
  const [composerOpen, setComposerOpen] = useState(!hasAgents && !isThreadTimeline);
  const selected = session.agents.find((a) => a.id === selectedAgentId) ?? session.agents[0];
  const isArchived = session.status === "done";
  const effectiveMode = composerOpen ? "clone" : mode;
  const orderedTrace = useMemo(
    () =>
      [...session.trace].sort(
        (a, b) =>
          (a.sequence ?? Number.MAX_SAFE_INTEGER) -
            (b.sequence ?? Number.MAX_SAFE_INTEGER) ||
          a.timestamp - b.timestamp,
      ),
    [session.trace],
  );
  const timelineEntries = useMemo(
    () =>
      effectiveMode === "result"
        ? []
        : effectiveMode === "replay"
          ? orderedTrace.slice(0, replayIndex)
          : orderedTrace,
    [orderedTrace, replayIndex, effectiveMode],
  );
  const selectedEntries = useMemo(
    () => (selected && effectiveMode !== "result" ? timelineEntries.filter((t) => t.agentId === selected.id) : []),
    [timelineEntries, selected, effectiveMode],
  );

  useEffect(() => {
    setMode(session.mode ?? "live");
    setReplayIndex(0);
    setReplayPlaying(false);
  }, [session.id, session.mode]);

  useEffect(() => {
    if (effectiveMode !== "replay") {
      setReplayPlaying(false);
      return;
    }
    if (!replayPlaying) return;
    if (replayIndex >= orderedTrace.length) {
      setReplayPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => {
      setReplayIndex((value) => Math.min(value + 1, orderedTrace.length));
    }, Math.max(80, 450 / replaySpeed));
    return () => window.clearTimeout(timer);
  }, [effectiveMode, orderedTrace.length, replayIndex, replayPlaying, replaySpeed]);

  return (
    <div className="flex h-full flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-muted text-lg">
          🖥️
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold">
            Octopus Workbench
          </div>
          <div className="flex items-center gap-1.5 text-[11px]">
            <span
              className={cn(
                "size-1.5 rounded-lg",
                hasAgents
                  ? isArchived
                    ? "bg-emerald-500"
                    : "bg-emerald-500 animate-pulse"
                  : "bg-muted-foreground/40",
              )}
            />
            <span className="text-muted-foreground">
              {!hasAgents
                ? t.agentWorkbench.idle
                : isArchived
                  ? t.agentWorkbench.finished
                  : t.agentWorkbench.running}
            </span>
          </div>
        </div>
        {!isThreadTimeline && (
          <button
            type="button"
            className={cn(
              "rounded-lg p-1.5 transition-colors",
              composerOpen
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted",
            )}
            onClick={() => setComposerOpen((v) => !v)}
            title={t.agentWorkbench.newTaskTitle}
          >
            <SparklesIcon className="size-4" />
          </button>
        )}
        <button
          type="button"
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted"
          onClick={onClose}
          title={t.agentWorkbench.closeTitle}
        >
          <PlusIcon className="size-4 rotate-45" />
        </button>
      </div>

      {/* Composer overlay — always accessible for starting a new batch */}
      {!isThreadTimeline && composerOpen && (
        <div className="border-b border-border/60 bg-muted/20 p-3">
          <DispatchComposer
            initialPrompt={effectiveMode === "clone" ? session.sourcePrompt : undefined}
            onLaunched={() => setComposerOpen(false)}
          />
        </div>
      )}

      {/* Empty idle state */}
      {!hasAgents && !composerOpen && (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 text-center">
          <SparklesIcon className="size-8 text-muted-foreground/40" />
          <p className="text-muted-foreground text-sm">
            {t.agentWorkbench.emptyNoAgents}
          </p>
          <button
            type="button"
            onClick={() => setComposerOpen(true)}
            hidden={isThreadTimeline}
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-sm"
          >
            {t.agentWorkbench.startNewTaskButton}
          </button>
        </div>
      )}

      {!hasAgents && composerOpen && (
        <div className="flex flex-1 items-center justify-center px-6 text-center">
          <p className="text-muted-foreground text-xs">
            {t.agentWorkbench.composerHint}
          </p>
        </div>
      )}

      {/* Agent-scoped UI only when a session is running */}
      {selected && (
        <>
          {/* Timeline header */}
          <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2">
            <div
              className="flex size-6 shrink-0 items-center justify-center rounded-lg text-sm"
              style={{ background: `hsl(${selected.hue} 70% 92%)` }}
            >
              {selected.avatarEmoji}
            </div>
            <span className="text-sm font-medium">
              {effectiveMode === "replay"
                ? "Replay"
                : effectiveMode === "result"
                  ? "Result"
                  : effectiveMode === "clone"
                    ? "Clone"
                    : t.agentWorkbench.liveEventStream}
            </span>
            <span className="text-muted-foreground text-xs">
              · {t.agentWorkbench.eventsCount(session.trace.length)}
            </span>
            <div className="flex-1" />
            {hasAgents && !isThreadTimeline && (
              <ModeSwitch
                mode={effectiveMode}
                onReplay={() => {
                  setMode("replay");
                  setComposerOpen(false);
                  setView("tasks");
                  setReplayIndex(0);
                  setReplayPlaying(true);
                }}
                onResult={() => {
                  setMode("result");
                  setComposerOpen(false);
                  setReplayPlaying(false);
                  setView("report");
                }}
                onClone={() => {
                  setMode("clone");
                  setReplayPlaying(false);
                  setComposerOpen(true);
                }}
              />
            )}
            {!isThreadTimeline && <ViewSwitch view={view} onChange={setView} />}
          </div>
          {effectiveMode === "replay" && (
            <ReplayControls
              current={replayIndex}
              total={orderedTrace.length}
              playing={replayPlaying}
              speed={replaySpeed}
              onToggle={() => {
                if (replayIndex >= orderedTrace.length) {
                  setReplayIndex(0);
                  setReplayPlaying(true);
                } else {
                  setReplayPlaying((value) => !value);
                }
              }}
              onSeek={(value) => {
                setReplayIndex(value);
                setReplayPlaying(false);
              }}
              onSpeed={() => {
                setReplaySpeed((value) => value === 1 ? 2 : value === 2 ? 4 : 1);
              }}
            />
          )}

          {/* Body */}
          <div className="min-h-0 flex-1 overflow-hidden">
            {isThreadTimeline ? (
              <div className="flex h-full flex-col">
                {session.plan && (
                  <PlanSummary
                    plan={session.plan}
                    reports={session.phaseReports}
                    workflow={session.workflow}
                  />
                )}
                <HandoffSummary session={session} />
                <TraceFeed entries={timelineEntries} emptyHint={t.agentWorkbench.traceFeedEmpty} />
              </div>
            ) : (
              <>
                {view === "tasks" && (
                  <div className="flex h-full flex-col">
                    {session.plan && (
                      <PlanSummary
                        plan={session.plan}
                        reports={session.phaseReports}
                        workflow={session.workflow}
                      />
                    )}
                    <HandoffSummary session={session} />
                    <TraceFeed entries={timelineEntries} emptyHint={t.agentWorkbench.traceFeedEmpty} />
                  </div>
                )}
                {view === "computer" && (
                  <ComputerView selected={selected} entries={selectedEntries} />
                )}
                {view === "report" && (
                  <ReportView session={session} agentId={selected.id} />
                )}
              </>
            )}
          </div>

          {/* Bottom pill row */}
          <div className="border-t border-border/60">
            <AgentStatusPills
              agents={session.agents}
              selectedId={selectedAgentId}
              onSelect={onSelectAgent}
            />
          </div>
        </>
      )}
    </div>
  );
}

function PlanSummary({
  plan,
  reports = [],
  workflow,
}: {
  plan: NonNullable<SwarmSession["plan"]>;
  reports?: NonNullable<SwarmSession["phaseReports"]>;
  workflow?: SwarmSession["workflow"];
}) {
  const reportByPhase = new Map(
    reports.map((report) => [report.phaseIndex, report]),
  );
  const workflowProgress =
    workflow?.progress != null
      ? Math.round(Math.max(0, Math.min(1, workflow.progress)) * 100)
      : null;
  return (
    <div className="border-b border-border/60 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
        <ActivityIcon className="size-3.5 text-muted-foreground" />
        <span>Swarm Plan</span>
        <span className="text-muted-foreground">
          {plan.strategy} · {plan.maxConcurrency} workers
        </span>
      </div>
      {workflow && (
        <div className="mb-2 rounded-lg border border-border/60 bg-background px-3 py-2 text-[11px]">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-medium">
              {workflow.stage ?? "workflow"}
            </span>
            <span className="shrink-0 text-muted-foreground">
              {workflow.status ?? "running"}
              {workflowProgress != null ? ` / ${workflowProgress}%` : ""}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-4 gap-1 text-[10px] text-muted-foreground">
            <Metric label="total" value={workflow.totalTasks} />
            <Metric label="done" value={workflow.completedTasks} />
            <Metric label="fail" value={workflow.failedTasks} />
            <Metric label="cancel" value={workflow.cancelledTasks} />
          </div>
        </div>
      )}
      <div className="space-y-2">
        {plan.phases.map((phase) => {
          const report = reportByPhase.get(phase.phaseIndex);
          const phaseVisual = getPhaseVisual(report?.status);
          return (
          <div key={phase.phaseIndex} className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-[11px]">
            <div className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 font-medium">
                <phaseVisual.Icon className={cn("size-3.5 shrink-0", phaseVisual.className)} />
                <span className="truncate">Phase {phase.phaseIndex + 1}</span>
              </span>
              <span className="text-muted-foreground">
                {phase.parallel ? "parallel" : "serial"}
                {report ? ` · ${report.status}` : ""}
              </span>
            </div>
            <div className="mt-1 text-muted-foreground">
              {phase.taskIds.join(" · ")}
            </div>
            {report && (
              <div className="mt-2 grid grid-cols-4 gap-1 text-[10px] text-muted-foreground">
                <Metric label="ok" value={report.succeeded} />
                <Metric label="fail" value={report.failed} />
                <Metric label="handoff" value={report.handoffCount} />
                <Metric label="ms" value={Math.round(report.wallMs)} />
              </div>
            )}
          </div>
          );
        })}
      </div>
    </div>
  );
}

function ReplayControls({
  current,
  total,
  playing,
  speed,
  onToggle,
  onSeek,
  onSpeed,
}: {
  current: number;
  total: number;
  playing: boolean;
  speed: number;
  onToggle: () => void;
  onSeek: (value: number) => void;
  onSpeed: () => void;
}) {
  const Icon = playing ? PauseIcon : PlayIcon;
  return (
    <div className="flex items-center gap-2 border-b border-border/60 px-4 py-2 text-xs">
      <button
        type="button"
        onClick={onToggle}
        className="rounded-lg border border-border/60 bg-background p-1.5 text-foreground hover:bg-muted"
        title={playing ? "Pause replay" : "Play replay"}
      >
        <Icon className="size-3.5" />
      </button>
      <input
        aria-label="Replay position"
        type="range"
        min={0}
        max={Math.max(total, 0)}
        value={Math.min(current, total)}
        onChange={(event) => onSeek(Number(event.currentTarget.value))}
        className="h-2 min-w-0 flex-1"
      />
      <span className="w-16 text-right text-muted-foreground">
        {Math.min(current, total)} / {total}
      </span>
      <button
        type="button"
        onClick={onSpeed}
        className="rounded-lg border border-border/60 bg-background px-2 py-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        title="Replay speed"
      >
        {speed}x
      </button>
    </div>
  );
}

function getPhaseVisual(
  status?: NonNullable<SwarmSession["phaseReports"]>[number]["status"],
) {
  switch (status) {
    case "success":
      return {
        label: "done",
        Icon: CheckIcon,
        className: "text-emerald-500",
      };
    case "partial":
      return {
        label: "active",
        Icon: LoaderCircleIcon,
        className: "text-blue-500",
      };
    case "failed":
      return {
        label: "failed",
        Icon: TriangleAlertIcon,
        className: "text-red-500",
      };
    default:
      return {
        label: "queued",
        Icon: CircleDashedIcon,
        className: "text-muted-foreground",
      };
  }
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-background/70 px-2 py-1">
      <div className="font-medium text-foreground">{value}</div>
      <div>{label}</div>
    </div>
  );
}

function HandoffSummary({ session }: { session: SwarmSession }) {
  const handoffs = session.handoffs ?? [];
  if (handoffs.length === 0) return null;

  return (
    <div className="border-b border-border/60 px-4 py-3">
      <div className="mb-2 flex items-center gap-2 text-xs font-medium">
        <ListChecksIcon className="size-3.5 text-muted-foreground" />
        <span>Agent Handoffs</span>
        <span className="text-muted-foreground">{handoffs.length} reports</span>
      </div>
      <div className="space-y-2">
        {handoffs.slice(0, 6).map((handoff) => (
          <div
            key={`${handoff.agentId}-${handoff.taskId}-${handoff.phaseIndex}`}
            className="rounded-lg border border-border/60 bg-background px-3 py-2 text-[11px]"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-medium">{handoff.agentId}</span>
              <span className="shrink-0 text-muted-foreground">
                P{handoff.phaseIndex + 1} · {handoff.status}
              </span>
            </div>
            {handoff.summary && (
              <div className="mt-1 line-clamp-2 text-muted-foreground">
                {handoff.summary}
              </div>
            )}
            {(handoff.nodeIds.length > 0 || handoff.artifacts.length > 0) && (
              <div className="mt-2 flex flex-wrap gap-1">
                {handoff.nodeIds.map((nodeId) => (
                  <span key={nodeId} className="rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {nodeId}
                  </span>
                ))}
                {handoff.artifacts.slice(0, 3).map((artifact) => (
                  <span key={artifact} className="max-w-44 truncate rounded-md bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {artifact}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ViewSwitch({
  view,
  onChange,
}: {
  view: View;
  onChange: (v: View) => void;
}) {
  const { t } = useI18n();
  const items: { id: View; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { id: "tasks", label: t.agentWorkbench.taskListView, icon: ListChecksIcon },
    { id: "computer", label: t.agentWorkbench.computerView, icon: MonitorIcon },
    { id: "report", label: t.agentWorkbench.reportView, icon: FileTextIcon },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-border/60 bg-muted/30 p-0.5 text-xs">
      {items.map((it) => {
        const Icon = it.icon;
        const active = view === it.id;
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => onChange(it.id)}
            className={cn(
              "flex items-center gap-1 rounded-lg px-2 py-1 transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3" />
            <span>{it.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function ModeSwitch({
  mode,
  onReplay,
  onResult,
  onClone,
}: {
  mode: SessionMode;
  onReplay: () => void;
  onResult: () => void;
  onClone: () => void;
}) {
  const items = [
    { id: "replay" as const, label: "Replay", icon: PlayIcon, action: onReplay },
    { id: "result" as const, label: "Result", icon: FileTextIcon, action: onResult },
    { id: "clone" as const, label: "Clone", icon: GitForkIcon, action: onClone },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-lg border border-border/60 bg-muted/30 p-0.5 text-xs">
      {items.map((it) => {
        const Icon = it.icon;
        const active = mode === it.id;
        return (
          <button
            key={it.id}
            type="button"
            onClick={it.action}
            className={cn(
              "flex items-center gap-1 rounded-lg px-2 py-1 transition-colors",
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3" />
            <span>{it.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function ComputerView({
  selected,
  entries,
}: {
  selected: { hue: number; avatarEmoji: string };
  entries: TraceEntry[];
}) {
  const { t } = useI18n();
  const computerEntries = entries.filter((e) => e.kind === "read" || e.kind === "tool");
  if (computerEntries.length === 0) {
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-xs">
        {t.agentWorkbench.computerViewEmpty}
      </div>
    );
  }
  return (
    <div className="h-full space-y-3 overflow-auto p-4">
      {computerEntries.map((e: TraceEntry) => (
        <div
          key={e.id}
          className="block rounded-lg border border-border bg-card p-3"
        >
          <div className="flex items-center gap-2">
            <span className="text-base">{e.faviconEmoji ?? "🌐"}</span>
            <span className="text-muted-foreground truncate text-xs">
              {e.url ? new URL(e.url).host : ""}
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-foreground">
            {e.title}
          </div>
          {e.detail && (
            <p className="text-muted-foreground mt-1 line-clamp-3 text-xs leading-relaxed">
              {e.detail}
            </p>
          )}
          {e.kind === "tool" && (e.inputPreview || e.outputPreview) && (
            <div className="mt-2 space-y-1 rounded-lg bg-muted/40 px-2 py-1.5 font-mono text-[10px] text-muted-foreground">
              {e.inputPreview && (
                <div className="line-clamp-3">
                  <span className="text-foreground/70">input </span>
                  {e.inputPreview}
                </div>
              )}
              {e.outputPreview && (
                <div className="line-clamp-3">
                  <span className="text-foreground/70">output </span>
                  {e.outputPreview}
                </div>
              )}
              {e.artifactPaths?.slice(0, 3).map((path) => (
                <div key={path} className="truncate text-foreground/70">
                  artifact {path}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      <div className="text-muted-foreground/50 pb-2 text-center text-[10px]">
        {t.agentWorkbench.browsingTrail(selected.avatarEmoji)}
      </div>
    </div>
  );
}

function ReportView({
  session,
  agentId,
}: {
  session: SwarmSession;
  agentId: string;
}) {
  const { t } = useI18n();
  const agent = session.agents.find((a) => a.id === agentId);
  const file = session.deliverables.find((d) =>
    d.ownerAgentIds.includes(agentId),
  );
  const hasResult = agent?.result && agent.result.trim().length > 0;
  const hasError = !!agent?.error;

  if (!hasResult && !hasError && !file) {
    return (
      <div className="text-muted-foreground flex h-full items-center justify-center text-xs">
        {agent?.status === "done" ? t.agentWorkbench.reportPending : t.agentWorkbench.agentRunning}
      </div>
    );
  }

  return (
    <div className="h-full space-y-3 overflow-auto p-4 text-sm">
      {file && (
        <>
          <div className="flex items-center gap-2">
            <FileTextIcon className="size-4 text-muted-foreground" />
            <span className="font-medium">{file.name}</span>
          </div>
          <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 font-mono text-[11px] break-all text-muted-foreground">
            {file.path}
          </div>
        </>
      )}
      {hasError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
          {agent?.error}
        </div>
      )}
      {hasResult && (
        <div className="whitespace-pre-wrap rounded-lg border border-border bg-background px-3 py-2 text-xs leading-relaxed">
          {agent?.result}
        </div>
      )}
      {agent?.durationSeconds != null && (
        <div className="text-muted-foreground text-[10px]">
          {t.agentWorkbench.durationSeconds(agent.durationSeconds.toFixed(1))}
        </div>
      )}
    </div>
  );
}
