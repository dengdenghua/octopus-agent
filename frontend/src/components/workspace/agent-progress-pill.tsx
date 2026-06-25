import {
  CheckCircle2Icon,
  ChevronDownIcon,
  CircleIcon,
  Loader2Icon,
  Minimize2Icon,
  MonitorIcon,
  XCircleIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  deriveAgentPhases,
  progressForPhases,
  type AgentPhaseStatus,
} from "./agent-phases";
import type { LiveToolEvent } from "./live-tool-timeline";
import { normalizeEventsForSettledDisplay } from "./work-blocks";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { agentRunBeadTone } from "./agent-run-status";

const minimizedPlanByScope = new Map<string, string>();

function planFingerprintForPhases(
  phases: Array<{ id: string; title: string }>,
) {
  if (phases.length === 0) return null;
  return phases.map((phase) => `${phase.id}:${phase.title}`).join("|");
}

function rememberMinimizedPlan(
  scopeKey: string | undefined,
  fingerprint: string | null,
) {
  if (!scopeKey || !fingerprint) return;
  minimizedPlanByScope.set(scopeKey, fingerprint);
}

function forgetMinimizedPlan(scopeKey: string | undefined) {
  if (!scopeKey) return;
  minimizedPlanByScope.delete(scopeKey);
}

function StatusIcon({
  status,
}: {
  status: LiveToolEvent["status"] | "pending";
}) {
  if (status === "waiting_approval") {
    return <CircleIcon className="size-4 shrink-0 text-amber-500" />;
  }
  if (status === "running") {
    return (
      <Loader2Icon className="size-4 shrink-0 animate-spin text-primary" />
    );
  }
  if (status === "pending") {
    return <CircleIcon className="size-4 shrink-0 text-muted-foreground/45" />;
  }
  if (status === "error") {
    return <XCircleIcon className="size-4 shrink-0 text-destructive" />;
  }
  return <CheckCircle2Icon className="size-4 shrink-0 text-emerald-500" />;
}

export function AgentProgressPill({
  events,
  hasAnswer,
  runSettled,
  runFailed,
  paused,
  className,
  progressScopeKey,
}: {
  events: LiveToolEvent[];
  hasAnswer?: boolean;
  runSettled?: boolean;
  runFailed?: boolean;
  paused?: boolean;
  className?: string;
  progressScopeKey?: string;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const displayEvents = useMemo(
    () =>
      normalizeEventsForSettledDisplay(events, {
        hasAnswer,
        runSettled,
        runFailed,
        paused,
      }),
    [events, hasAnswer, runFailed, runSettled, paused],
  );
  const { blocks, phases, currentPhase } = useMemo(
    () =>
      deriveAgentPhases(displayEvents, {
        hasAnswer,
        runSettled,
        runFailed,
        paused,
      }),
    [displayEvents, hasAnswer, runSettled, runFailed, paused],
  );
  const autoMinimizedRunRef = useRef<string | null>(null);
  const displayPhase = currentPhase;
  const progress = displayPhase
    ? progressForPhases(phases, displayPhase)
    : { current: 0, total: 0 };
  const planFingerprint = useMemo(
    () => planFingerprintForPhases(phases),
    [phases],
  );
  const running = displayPhase?.status === "running";
  const waiting =
    !displayEvents.some((event) => event.status === "running") &&
    displayEvents.some((event) => event.status === "waiting_approval");
  const autoMinimizeKey = displayPhase
    ? `${displayPhase.id}:${progress.current}/${progress.total}:${events.length}`
    : null;

  useEffect(() => {
    if (!progressScopeKey || !planFingerprint) return;
    const storedFingerprint = minimizedPlanByScope.get(progressScopeKey);
    if (storedFingerprint === planFingerprint) {
      setMinimized(true);
      setExpanded(false);
      return;
    }
    if (storedFingerprint) {
      forgetMinimizedPlan(progressScopeKey);
      setMinimized(false);
      setExpanded(false);
    }
  }, [planFingerprint, progressScopeKey]);

  useEffect(() => {
    if (!autoMinimizeKey || !runSettled || runFailed || paused || running) {
      autoMinimizedRunRef.current = null;
      return;
    }
    if (autoMinimizedRunRef.current === autoMinimizeKey) return;
    autoMinimizedRunRef.current = autoMinimizeKey;
    rememberMinimizedPlan(progressScopeKey, planFingerprint);
    setMinimized(true);
    setExpanded(false);
  }, [
    autoMinimizeKey,
    paused,
    planFingerprint,
    progressScopeKey,
    runFailed,
    runSettled,
    running,
  ]);

  if (!displayPhase || phases.length === 0 || blocks.length === 0) {
    return null;
  }

  const percent = Math.round((progress.current / progress.total) * 100);
  const visiblePhases = phases.slice(
    Math.max(0, progress.current - 4),
    progress.current + 1,
  );
  const beadTone = agentRunBeadTone({
    paused,
    runFailed,
    status: displayPhase.status,
    waiting,
  });

  if (minimized) {
    return (
      <div
        className={cn(
          "relative z-30 -mb-2 ml-3 flex w-fit max-w-full items-center rounded-full bg-transparent",
          className,
        )}
      >
        <button
          type="button"
          onClick={() => {
            forgetMinimizedPlan(progressScopeKey);
            setMinimized(false);
            setExpanded(true);
          }}
          title={`${t.agentWorkbench.currentProgress} ${progress.current}/${progress.total}`}
          aria-label={t.agentWorkbench.restoreProgress}
          className={cn(
            "relative isolate size-4 rounded-full shadow-sm transition-transform hover:scale-110",
            beadTone.bead,
          )}
        >
          {beadTone.halo ? (
            <span
              aria-hidden="true"
              className={cn(
                "pointer-events-none absolute -inset-1 -z-10 rounded-full",
                beadTone.halo,
              )}
            />
          ) : null}
        </button>
      </div>
    );
  }

  return (
    <div className={cn("relative z-20 flex w-full flex-col", className)}>
      {expanded ? (
        <div className="rounded-t-xl border border-b-0 border-border/70 bg-background/95 p-2.5 shadow-lg shadow-black/5 backdrop-blur-xl">
          <div className="max-h-44 space-y-1.5 overflow-y-auto pr-1">
            {visiblePhases.map((phase) => {
              const active = phase.id === displayPhase.id;
              return (
                <div
                  key={phase.id}
                  className={cn(
                    "flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-xs",
                    active
                      ? "bg-primary/10 text-foreground"
                      : "text-muted-foreground",
                  )}
                >
                  <StatusIcon status={phase.status} />
                  <span className="min-w-0 flex-1 truncate">{phase.title}</span>
                  {active ? (
                    <span className="shrink-0 rounded-full bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary">
                      {progress.current}/{progress.total}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      <div
        className={cn(
          "group flex w-full items-center gap-1.5 border border-border/70 bg-background/95 px-3 py-1.5 text-left shadow-lg shadow-black/5 backdrop-blur-xl transition-colors hover:bg-muted/45",
          expanded ? "border-b-0" : "rounded-t-xl border-b-0",
        )}
      >
        <button
          type="button"
          onClick={() => {
            setExpanded((value) => !value);
          }}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        >
          <MonitorIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-1.5 text-[13px]">
              <span className="shrink-0 font-medium text-foreground">
                {t.agentWorkbench.currentProgress} {progress.current}/
                {progress.total}
              </span>
              <StatusIcon status={displayPhase.status} />
              <span
                className={cn(
                  "min-w-0 flex-1 truncate",
                  running ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {displayPhase.title}
              </span>
              <ChevronDownIcon
                className={cn(
                  "size-3.5 shrink-0 text-muted-foreground transition-transform",
                  expanded && "rotate-180",
                )}
              />
            </div>
            <div className="mt-1 h-0.5 overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full transition-all duration-300",
                  displayPhase.status === "error"
                    ? "bg-destructive"
                    : "bg-foreground/55",
                )}
                style={{ width: `${percent}%` }}
              />
            </div>
          </div>
        </button>
        <button
          type="button"
          onClick={() => {
            rememberMinimizedPlan(progressScopeKey, planFingerprint);
            setMinimized(true);
            setExpanded(false);
          }}
          title={t.agentWorkbench.minimizeProgress}
          aria-label={t.agentWorkbench.minimizeProgress}
          className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
        >
          <Minimize2Icon className="size-3" />
        </button>
      </div>
    </div>
  );
}
