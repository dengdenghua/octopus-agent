import { useMemo, useState } from "react";
import {
  CheckCircle2Icon,
  ClipboardListIcon,
  Loader2Icon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  Trash2Icon,
  XCircleIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  useDeleteTeamTask,
  useRunTeamTask,
  useTeamTasks,
  useUpdateTeamTask,
} from "@/core/team-tasks";
import type { TeamTask, TeamTaskStatus } from "@/core/team-tasks";
import type { Team } from "@/core/teams";
import { cn } from "@/lib/utils";

import {
  useOptionalCollab,
  type TeamTaskProgressEvent,
} from "./collab-provider";
import { CreateTaskDialog } from "./create-task-dialog";

interface TeamTasksPanelProps {
  roomId: string | null | undefined;
  team: Team | null;
  canManageTasks?: boolean;
}

const FILTERS: Array<{ id: "all" | TeamTaskStatus; label: string }> = [
  { id: "all", label: "全部" },
  { id: "pending", label: "待运行" },
  { id: "running", label: "运行中" },
  { id: "done", label: "已完成" },
  { id: "failed", label: "异常" },
];

const STATUS_META: Record<
  TeamTaskStatus,
  {
    label: string;
    Icon: typeof CheckCircle2Icon;
    className: string;
  }
> = {
  pending: {
    label: "待运行",
    Icon: ClipboardListIcon,
    className: "border-amber-500/25 bg-amber-500/10 text-amber-700",
  },
  running: {
    label: "运行中",
    Icon: Loader2Icon,
    className: "border-blue-500/25 bg-blue-500/10 text-blue-700",
  },
  done: {
    label: "已完成",
    Icon: CheckCircle2Icon,
    className: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700",
  },
  failed: {
    label: "异常",
    Icon: XCircleIcon,
    className: "border-destructive/30 bg-destructive/10 text-destructive",
  },
  cancelled: {
    label: "已暂停",
    Icon: PauseIcon,
    className: "border-muted-foreground/25 bg-muted text-muted-foreground",
  },
};

export function TeamTasksPanel({
  roomId,
  team,
  canManageTasks = true,
}: TeamTasksPanelProps) {
  const [filter, setFilter] = useState<"all" | TeamTaskStatus>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const tasksQuery = useTeamTasks(roomId ?? null);
  const runTask = useRunTeamTask();
  const updateTask = useUpdateTeamTask();
  const deleteTask = useDeleteTeamTask();
  const collab = useOptionalCollab();

  const tasks = useMemo(() => tasksQuery.data ?? [], [tasksQuery.data]);
  const latestEventByTask = useMemo(() => {
    const byTask = new Map<string, TeamTaskProgressEvent>();
    for (const event of collab?.taskEvents ?? []) {
      byTask.set(event.task_id, event);
    }
    return byTask;
  }, [collab?.taskEvents]);
  const visibleTasks = useMemo(
    () =>
      filter === "all" ? tasks : tasks.filter((task) => task.status === filter),
    [filter, tasks],
  );
  const runningCount = tasks.filter((task) => task.status === "running").length;
  const doneCount = tasks.filter((task) => task.status === "done").length;

  const handleRun = async (task: TeamTask) => {
    try {
      await runTask.mutateAsync({ taskId: task.id });
      toast.success("任务已开始运行");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "运行任务失败");
    }
  };

  const handleCancel = async (task: TeamTask) => {
    try {
      await updateTask.mutateAsync({
        taskId: task.id,
        input: { status: "cancelled" },
      });
      toast.success("任务已暂停");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "暂停任务失败");
    }
  };

  const handleDelete = async (task: TeamTask) => {
    try {
      await deleteTask.mutateAsync({ taskId: task.id });
      toast.success("任务已删除");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除任务失败");
    }
  };

  if (!roomId) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-5 text-center text-sm text-muted-foreground">
        选择或创建 Team 后，这里会显示团队待办。
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background/70">
      <div className="shrink-0 border-b border-border/45 px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-foreground">待办 plan</div>
            <div className="mt-0.5 text-xs text-muted-foreground">
              {tasks.length} 个任务 · {runningCount} 运行中 · {doneCount} 已完成
            </div>
          </div>
          <Button
            size="sm"
            className="h-8 gap-1.5 rounded-md"
            disabled={!canManageTasks}
            onClick={() => setCreateOpen(true)}
          >
            <PlusIcon className="size-3.5" />
            新建
          </Button>
        </div>
        <div className="mt-2 flex gap-1 overflow-x-auto pb-0.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setFilter(item.id)}
              className={cn(
                "h-7 shrink-0 rounded-md px-2 text-xs font-medium transition-colors",
                filter === item.id
                  ? "bg-foreground/10 text-foreground"
                  : "text-muted-foreground hover:bg-muted/55 hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        {tasksQuery.isLoading ? (
          <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2Icon className="size-4 animate-spin" />
            正在加载任务
          </div>
        ) : visibleTasks.length === 0 ? (
          <div className="flex min-h-48 items-center justify-center rounded-lg border border-dashed border-border/70 bg-muted/15 px-4 text-center text-sm text-muted-foreground">
            暂无匹配任务
          </div>
        ) : (
          <div className="space-y-2">
            {visibleTasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                team={team}
                taskEvent={latestEventByTask.get(task.id)}
                canManageTasks={canManageTasks}
                busy={
                  runTask.isPending ||
                  updateTask.isPending ||
                  deleteTask.isPending
                }
                onRun={() => void handleRun(task)}
                onCancel={() => void handleCancel(task)}
                onDelete={() => void handleDelete(task)}
              />
            ))}
          </div>
        )}
      </div>

      <CreateTaskDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        roomId={roomId}
        team={team}
      />
    </div>
  );
}

function TaskRow({
  task,
  team,
  taskEvent,
  canManageTasks,
  busy,
  onRun,
  onCancel,
  onDelete,
}: {
  task: TeamTask;
  team: Team | null;
  taskEvent?: TeamTaskProgressEvent;
  canManageTasks: boolean;
  busy: boolean;
  onRun: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const status = STATUS_META[task.status] ?? STATUS_META.pending;
  const StatusIcon = status.Icon;
  const progress = taskProgressValue(task, taskEvent);
  const assigneeLabels = assigneeNames(task, team);
  const artifactCount = task.produced_artifacts?.length ?? 0;
  const roleLabel = formatTeamRole(taskEvent?.role);
  const liveStatus = taskEvent
    ? formatTeamTaskEvent(taskEvent.event, roleLabel)
    : null;

  return (
    <article className="rounded-lg border border-border/60 bg-background/85 shadow-sm">
      <div className="flex items-start gap-2.5 px-3 py-2.5">
        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
          <ClipboardListIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h3 className="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">
              {task.title}
            </h3>
            <Badge
              variant="outline"
              className={cn("h-6 gap-1", status.className)}
            >
              <StatusIcon
                className={cn(
                  "size-3",
                  task.status === "running" && "animate-spin",
                )}
              />
              {status.label}
            </Badge>
          </div>
          {task.description && (
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {task.description}
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="rounded-md bg-muted/60 px-1.5 py-0.5">
              {task.sop_template || "自动匹配"}
            </span>
            {assigneeLabels.length > 0 && (
              <span className="rounded-md bg-muted/60 px-1.5 py-0.5">
                {assigneeLabels.join("、")}
              </span>
            )}
            {artifactCount > 0 && (
              <span className="rounded-md bg-emerald-500/10 px-1.5 py-0.5 text-emerald-700">
                {artifactCount} 个产物
              </span>
            )}
          </div>
        </div>
      </div>

      {liveStatus && task.status === "running" && (
        <div className="px-3 pb-2 text-[11px] text-primary">
          {liveStatus}
          {taskEvent?.completed_roles != null && taskEvent?.total_roles != null
            ? ` · ${taskEvent.completed_roles}/${taskEvent.total_roles} 角色完成`
            : ""}
        </div>
      )}

      {(task.status === "running" || task.status === "done") && (
        <div className="px-3 pb-2">
          <Progress value={progress} className="h-1.5 bg-muted" />
        </div>
      )}

      <div className="flex items-center justify-end gap-1 border-t border-border/45 px-2.5 py-1.5">
        {task.status === "running" ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 rounded-md px-2 text-xs"
            disabled={!canManageTasks || busy}
            onClick={onCancel}
          >
            <PauseIcon className="mr-1 size-3.5" />
            暂停
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 rounded-md px-2 text-xs"
            disabled={!canManageTasks || busy}
            onClick={onRun}
          >
            <PlayIcon className="mr-1 size-3.5" />
            运行
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 rounded-md px-2 text-xs text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
          disabled={!canManageTasks || busy}
          onClick={onDelete}
        >
          <Trash2Icon className="mr-1 size-3.5" />
          删除
        </Button>
      </div>
    </article>
  );
}

function assigneeNames(task: TeamTask, team: Team | null): string[] {
  const byRef = new Map(
    (team?.members ?? []).map((member) => [
      member.name,
      member.display_name ?? member.name,
    ]),
  );
  return (task.assignees ?? [])
    .map((assignee) => byRef.get(assignee.ref) ?? assignee.ref)
    .filter(Boolean)
    .slice(0, 3);
}

function taskProgressValue(
  task: TeamTask,
  event?: TeamTaskProgressEvent,
): number {
  if (task.status === "done") return 100;
  if (task.status === "failed" || task.status === "cancelled") return 100;
  if (typeof event?.progress === "number") {
    return Math.max(0, Math.min(100, Math.round(event.progress * 100)));
  }
  if (task.status === "running") return 8;
  return 0;
}

function formatTeamTaskEvent(event: string, roleLabel: string | null) {
  switch (event) {
    case "run_started":
      return "任务已启动";
    case "team_role_start":
      return roleLabel ? `${roleLabel} 开始执行` : "角色开始执行";
    case "role_completed":
    case "team_role_end":
      return roleLabel ? `${roleLabel} 已完成` : "一个角色已完成";
    case "run_done":
      return "任务完成，产物已写回";
    case "run_failed":
      return "任务运行失败";
    case "run_cancelled":
      return "任务已暂停";
    default:
      return roleLabel ? `${roleLabel} 有新进展` : "任务有新进展";
  }
}

function formatTeamRole(role?: string | null) {
  if (!role) return null;
  const normalized = role.replace(/^Role\./, "").toLowerCase();
  const labels: Record<string, string> = {
    planner: "规划者",
    researcher: "调研员",
    generator: "执行者",
    implementer: "执行者",
    critic: "评审者",
    synthesizer: "整理者",
    evaluator: "验收者",
  };
  return labels[normalized] ?? normalized;
}
