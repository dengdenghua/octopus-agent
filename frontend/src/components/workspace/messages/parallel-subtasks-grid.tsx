import { DotProgress } from "@/components/workspace/swarm/dot-progress";
import { useOptionalSwarm } from "@/components/workspace/swarm/swarm-context";
import { useI18n } from "@/core/i18n/hooks";
import { useSubtask } from "@/core/tasks/context";
import {
  isSubtaskActive,
  type Subtask,
  type SubtaskStatus,
} from "@/core/tasks/types";
import { cn } from "@/lib/utils";
import {
  agentRunHue,
  agentRunPanelClass,
  agentRunStatusLightPulseClass,
  type AgentRunState,
} from "../agent-run-status";
import {
  CheckCircleIcon,
  Loader2Icon,
  PauseCircleIcon,
  XCircleIcon,
  ClockIcon,
  BanIcon,
} from "lucide-react";

function getStatusIcon(status: SubtaskStatus) {
  if (status === "completed")
    return <CheckCircleIcon className="size-3 text-emerald-500" />;
  if (status === "failed")
    return <XCircleIcon className="size-3 text-destructive" />;
  if (status === "cancelled")
    return <BanIcon className="size-3 text-amber-500" />;
  if (status === "timed_out")
    return <ClockIcon className="size-3 text-destructive" />;
  if (status === "pending")
    return <PauseCircleIcon className="size-3 text-amber-500" />;
  if (isSubtaskActive(status))
    return (
      <Loader2Icon className="size-3 animate-spin text-emerald-600 dark:text-emerald-400" />
    );
  return null;
}

function subtaskRunState(status: SubtaskStatus): AgentRunState {
  if (status === "completed") return "done";
  if (status === "failed" || status === "timed_out") return "error";
  if (status === "pending" || status === "cancelled") return "waiting";
  if (isSubtaskActive(status)) return "running";
  return "pending";
}

function MiniSubtaskRow({
  taskId,
  isLoading: _isLoading,
  onClick,
}: {
  taskId: string;
  isLoading: boolean;
  onClick?: () => void;
}) {
  const task = useSubtask(taskId);
  const { t } = useI18n();
  const swarm = useOptionalSwarm();
  const isActive = task ? isSubtaskActive(task.status) : false;

  if (!task) return null;

  const rawLabel = t.subagents[task.status as keyof typeof t.subagents];
  const statusLabel = typeof rawLabel === "string" ? rawLabel : task.status;
  const progress = subtaskProgress(task);
  const runState = subtaskRunState(task.status);
  const progressHue = agentRunHue(runState);

  const handleClick = () => {
    if (swarm) {
      swarm.setSelectedAgentId(task.id);
      swarm.openPanel();
    }
    onClick?.();
  };

  return (
    <div className="group/subtask-row relative">
      <button
        type="button"
        onClick={handleClick}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs transition-all",
          runState === "running"
            ? agentRunPanelClass("running")
            : "border-border bg-muted/30",
          onClick && "cursor-pointer hover:bg-muted/50",
        )}
      >
        {task.avatarEmoji && (
          <span
            className="flex size-6 shrink-0 items-center justify-center rounded-lg text-[11px]"
            style={
              task.hue != null
                ? { background: `hsl(${task.hue} 70% 92%)` }
                : undefined
            }
          >
            {task.avatarEmoji}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            {getStatusIcon(task.status)}
            <span className="truncate font-medium">
              {task.name ?? task.description}
            </span>
          </div>
          <div className="text-muted-foreground mt-0.5 truncate">
            {task.description}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span className="font-mono text-xs leading-none text-foreground">
            {task.id.slice(-2).toUpperCase()}
          </span>
          <DotProgress
            progress={progress}
            hue={progressHue}
            cols={16}
            rows={3}
            className={cn(agentRunStatusLightPulseClass(runState))}
          />
        </div>
      </button>
      <SubtaskHoverPreview task={task} statusLabel={statusLabel} />
    </div>
  );
}

function SubtaskHoverPreview({
  task,
  statusLabel,
}: {
  task: Subtask;
  statusLabel: string;
}) {
  const { t } = useI18n();
  const body =
    task.prompt ||
    task.description ||
    task.result ||
    t.message.noTaskDescription;
  return (
    <div
      className="pointer-events-none absolute left-8 top-[calc(100%+0.5rem)] z-40 hidden w-[min(42rem,calc(100vw-5rem))] rounded-xl border border-border/60 bg-background/95 p-4 text-left shadow-2xl shadow-black/15 backdrop-blur-xl group-hover/subtask-row:block"
      role="tooltip"
    >
      <div className="flex items-start gap-3">
        <span className="flex size-14 shrink-0 items-center justify-center rounded-full border border-border/55 bg-muted/35 text-2xl">
          {task.avatarEmoji ?? "🤖"}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-lg font-semibold text-foreground">
                {task.name ?? task.description}
              </div>
              <div className="truncate text-sm text-muted-foreground">
                {task.role ?? task.subagent_type ?? t.message.assistant}
              </div>
            </div>
            <span className="font-mono text-sm text-foreground">
              {task.id.slice(-2).toUpperCase()}
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-muted-foreground">
            <span>{statusLabel}</span>
            <span>·</span>
            <span>{t.message.processRecords(task.messages?.length ?? 0)}</span>
            {task.tokenUsed !== undefined && (
              <>
                <span>·</span>
                <span>{task.tokenUsed.toLocaleString()} tokens</span>
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

function subtaskProgress(task: Subtask): number {
  if (
    task.status === "completed" ||
    task.status === "failed" ||
    task.status === "cancelled" ||
    task.status === "timed_out"
  ) {
    return 1;
  }
  if (task.status === "pending") return 0.08;
  return Math.max(0.18, Math.min(0.92, task.progress || 0.45));
}

export function ParallelSubtasksGrid({
  taskIds,
  isLoading,
  onTaskClick,
}: {
  taskIds: string[];
  isLoading: boolean;
  onTaskClick?: (taskId: string) => void;
}) {
  const isGrid = taskIds.length > 1;

  if (taskIds.length === 0) return null;

  if (!isGrid) {
    return (
      <>
        {taskIds.map((taskId) => (
          <MiniSubtaskRow
            key={taskId}
            taskId={taskId}
            isLoading={isLoading}
            onClick={onTaskClick ? () => onTaskClick(taskId) : undefined}
          />
        ))}
      </>
    );
  }

  const cols = taskIds.length === 3 ? "grid-cols-3" : "grid-cols-2";

  return (
    <div className={`grid ${cols} gap-2`}>
      {taskIds.map((taskId) => (
        <MiniSubtaskRow
          key={taskId}
          taskId={taskId}
          isLoading={isLoading}
          onClick={onTaskClick ? () => onTaskClick(taskId) : undefined}
        />
      ))}
    </div>
  );
}
