import {
  AlertCircleIcon,
  CheckCircle2Icon,
  CircleIcon,
  Loader2Icon,
} from "lucide-react";
import { useMemo } from "react";

import { deriveAgentPhases, progressForPhases } from "./agent-phases";
import type { LiveToolEvent } from "./live-tool-timeline";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function hasExplicitTaskPlan(events: LiveToolEvent[]): boolean {
  return events.some((event) => {
    if (event.name !== "todo_write") return false;
    const items = event.input?.items ?? event.input?.todos;
    return Array.isArray(items) && items.length >= 2;
  });
}

export function ComposerStepProgress({
  events,
  hasAnswer,
  isLoading,
  runSettled,
  runFailed,
  paused,
  onOpenDetails,
  className,
}: {
  events: LiveToolEvent[];
  hasAnswer?: boolean;
  isLoading?: boolean;
  runSettled?: boolean;
  runFailed?: boolean;
  paused?: boolean;
  onOpenDetails: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  const hasPlan = useMemo(() => hasExplicitTaskPlan(events), [events]);
  const { phases, currentPhase } = useMemo(
    () =>
      deriveAgentPhases(events, {
        hasAnswer,
        runSettled,
        runFailed,
        paused,
      }),
    [events, hasAnswer, paused, runFailed, runSettled],
  );

  // This indicator describes a real model-authored task plan only. Generic
  // tool activity stays in the transcript rather than being presented as an
  // invented numbered plan.
  if (
    !hasPlan ||
    !currentPhase ||
    phases.length < 2 ||
    (runSettled && hasAnswer && !paused) ||
    (!isLoading && currentPhase.status === "done")
  ) {
    return null;
  }

  const progress = progressForPhases(phases, currentPhase);
  const label = t.agentWorkbench.stepProgress(progress.current, progress.total);

  return (
    <div className={cn("flex w-full justify-center pb-1", className)}>
      <button
        type="button"
        onClick={onOpenDetails}
        aria-label={`${label} · ${currentPhase.title}`}
        title={currentPhase.title}
        className="group inline-flex h-10 max-w-full items-center gap-2 rounded-full border border-border-default bg-background/95 px-4 text-sm font-semibold text-muted-foreground shadow-[0_8px_24px_-16px_rgba(15,23,42,0.45)] backdrop-blur-xl transition-[border-color,background-color,color,transform] hover:-translate-y-0.5 hover:border-primary/30 hover:bg-background hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:translate-y-0"
      >
        {currentPhase.status === "running" ? (
          <Loader2Icon
            aria-hidden="true"
            className="size-4 shrink-0 animate-spin text-info dark:text-info"
          />
        ) : currentPhase.status === "waiting_approval" ? (
          <CircleIcon
            aria-hidden="true"
            className="size-4 shrink-0 text-warning"
          />
        ) : currentPhase.status === "error" ? (
          <AlertCircleIcon
            aria-hidden="true"
            className="size-4 shrink-0 text-destructive"
          />
        ) : currentPhase.status === "done" ? (
          <CheckCircle2Icon
            aria-hidden="true"
            className="size-4 shrink-0 text-success"
          />
        ) : (
          <CircleIcon
            aria-hidden="true"
            className="size-4 shrink-0 text-info dark:text-info"
          />
        )}
        <span className="truncate tabular-nums">{label}</span>
      </button>
    </div>
  );
}
