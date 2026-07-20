import { LoaderIcon, PauseIcon } from "lucide-react";
import { memo } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { usePauseTask, useTasks } from "@/core/tasks/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface Props {
  threadId: string;
  className?: string;
}

/* Implementation note. */
export const ReactProgressPill = memo(function ReactProgressPill({
  threadId,
  className,
}: Props) {
  const { t } = useI18n();
  const b = t.pausedTasksBanner;
  const tasks = useTasks("active");
  const pause = usePauseTask();

  const active = (tasks.data?.active ?? []).find(
    (a) => a.thread_id === threadId,
  );
  if (!active) return null;

  async function handlePause() {
    if (!active) return;
    try {
      await pause.mutateAsync({
        taskId: active.task_id,
        reason: "user_request",
      });
      toast.success(
        `${b.pauseRequestedPrefix} ${active.task_id.slice(0, 8)}…`,
        {
          description: b.pauseRequestedDesc,
        },
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const tokenPct =
    active.max_tokens > 0 ? (active.tokens_spent / active.max_tokens) * 100 : 0;
  const iterPct =
    active.max_iterations > 0
      ? (active.current_iteration / active.max_iterations) * 100
      : 0;
  const hot = tokenPct >= 70 || iterPct >= 70;

  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full border border-border-default bg-card/50 px-2 py-0.5 text-xs",
        hot
          ? "border-amber-300/60 bg-amber-50/60 dark:border-amber-700/40 dark:bg-amber-950/30"
          : "border-blue-300/60 bg-blue-50/60 dark:border-blue-700/40 dark:bg-blue-950/30",
        className,
      )}
    >
      <LoaderIcon
        className={cn(
          "h-3 w-3 animate-spin",
          hot ? "text-amber-600" : "text-blue-600",
        )}
      />
      {active.max_iterations > 0 && (
        <span className="font-mono text-muted-foreground">
          iter {active.current_iteration}/{active.max_iterations}
        </span>
      )}
      {active.max_tokens > 0 && (
        <span className="font-mono text-muted-foreground">
          · {(active.tokens_spent / 1000).toFixed(1)}k/
          {(active.max_tokens / 1000).toFixed(0)}k
        </span>
      )}
      <Button
        size="sm"
        variant="ghost"
        className="ml-0.5 h-5 gap-0.5 rounded-full px-1.5 text-xs hover:bg-background/60"
        onClick={handlePause}
        disabled={pause.isPending}
        title={b.pauseBtn}
      >
        <PauseIcon className="h-3 w-3" />
        {b.pauseBtn}
      </Button>
    </div>
  );
});
