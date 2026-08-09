/**
 * BackgroundTasksPanel -- 7x24 persistent background agent execution panel.
 *
 * Displays a list of background tasks with real-time status, output streaming
 * via reconnectable SSE, and pause/resume/cancel controls.
 */

import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ChevronLeftIcon,
  ClockIcon,
  Loader2Icon,
  PauseIcon,
  PlayIcon,
  PlusIcon,
  RefreshCwIcon,
  SquareIcon,
  Trash2Icon,
  XIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  useBackgroundTaskOutput,
  useBackgroundTasks,
} from "@/core/background/hooks";
import type {
  BackgroundTask,
  BackgroundTaskOutput,
  BackgroundTaskStatus,
} from "@/core/background/types";
import { swallow } from "@/core/utils/log";
import { isActiveStatus, isTerminalStatus } from "@/core/background/types";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  BackgroundTaskStatus,
  { color: string; icon: React.ReactNode }
> = {
  queued: {
    color: "bg-muted-foreground/15 text-muted-foreground",
    icon: <ClockIcon className="size-3" />,
  },
  running: {
    color: "bg-info/15 text-info dark:text-info",
    icon: <Loader2Icon className="size-3 animate-spin" />,
  },
  paused: {
    color: "bg-warning/15 text-warning",
    icon: <PauseIcon className="size-3" />,
  },
  completed: {
    color: "bg-success/15 text-success",
    icon: <CheckCircle2Icon className="size-3" />,
  },
  failed: {
    color: "bg-destructive/15 text-destructive",
    icon: <AlertCircleIcon className="size-3" />,
  },
  cancelled: {
    color: "bg-muted-foreground/15 text-muted-foreground",
    icon: <XIcon className="size-3" />,
  },
  interrupted: {
    color: "bg-chart-7/15 text-chart-7 dark:text-chart-7",
    icon: <AlertCircleIcon className="size-3" />,
  },
};

function StatusBadge({ status }: { status: BackgroundTaskStatus }) {
  const { t } = useI18n();
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.queued;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-medium",
        cfg.color,
      )}
    >
      {cfg.icon}
      {statusLabel(status, t.backgroundTasks)}
    </span>
  );
}

function formatRelativeTime(
  isoString: string,
  copy: Translations["backgroundTasks"],
): string {
  const now = Date.now();
  const ts = new Date(isoString).getTime();
  const diff = now - ts;
  if (diff < 60_000) return copy.justNow;
  if (diff < 3_600_000) return copy.minutesAgo(Math.floor(diff / 60_000));
  if (diff < 86_400_000) return copy.hoursAgo(Math.floor(diff / 3_600_000));
  return copy.daysAgo(Math.floor(diff / 86_400_000));
}

function statusLabel(
  status: string,
  copy: Translations["backgroundTasks"],
): string {
  switch (status) {
    case "queued":
      return copy.queued;
    case "running":
      return copy.running;
    case "paused":
      return copy.paused;
    case "completed":
      return copy.completed;
    case "failed":
      return copy.failed;
    case "cancelled":
      return copy.cancelled;
    case "interrupted":
      return copy.interrupted;
    default:
      return status;
  }
}

function formatDuration(startIso: string, endIso?: string | null): string {
  const start = new Date(startIso).getTime();
  const end = endIso ? new Date(endIso).getTime() : Date.now();
  const diff = end - start;
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s`;
  if (diff < 3_600_000)
    return `${Math.floor(diff / 60_000)}m ${Math.floor((diff % 60_000) / 1000)}s`;
  return `${Math.floor(diff / 3_600_000)}h ${Math.floor((diff % 3_600_000) / 60_000)}m`;
}

// ---------------------------------------------------------------------------
// Task list item
// ---------------------------------------------------------------------------

function TaskListItem({
  task,
  isSelected,
  onSelect,
  onPause,
  onResume,
  onCancel,
  onDelete,
}: {
  task: BackgroundTask;
  isSelected: boolean;
  onSelect: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const { t } = useI18n();
  const taskLabel =
    task.name || task.prompt.slice(0, 50) || t.backgroundTasks.unnamedTask;

  return (
    <div
      className={cn(
        "group rounded-lg border p-3 transition-colors hover:bg-accent/50",
        isSelected && "border-primary/30 bg-accent/30",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          className="min-w-0 flex-1 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          onClick={onSelect}
        >
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium">{taskLabel}</span>
          </div>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {task.prompt.length > 80
              ? task.prompt.slice(0, 80) + "..."
              : task.prompt}
          </p>
          <div className="mt-1.5 flex items-center gap-2">
            <StatusBadge status={task.status} />
            <span className="text-xs text-muted-foreground">
              {formatRelativeTime(task.updated_at, t.backgroundTasks)}
            </span>
            {task.started_at && (
              <span className="text-xs text-muted-foreground">
                {formatDuration(task.started_at, task.finished_at)}
              </span>
            )}
          </div>
        </button>

        {/* Action buttons */}
        <div className="flex shrink-0 items-center gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity">
          {task.status === "running" && (
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              onClick={onPause}
              aria-label={t.backgroundTasks.pause}
              title={t.backgroundTasks.pause}
            >
              <PauseIcon className="size-3.5" />
            </Button>
          )}
          {(task.status === "paused" || task.status === "interrupted") && (
            <Button
              variant="ghost"
              size="icon"
              className="size-7"
              onClick={onResume}
              aria-label={t.backgroundTasks.resume}
              title={t.backgroundTasks.resume}
            >
              <PlayIcon className="size-3.5" />
            </Button>
          )}
          {isActiveStatus(task.status) && (
            <Button
              variant="ghost"
              size="icon"
              className="size-7 text-destructive hover:text-destructive"
              onClick={onCancel}
              aria-label={t.backgroundTasks.cancel}
              title={t.backgroundTasks.cancel}
            >
              <SquareIcon className="size-3.5" />
            </Button>
          )}
          {isTerminalStatus(task.status) && (
            <Button
              variant="ghost"
              size="icon"
              className="size-7 text-destructive hover:text-destructive"
              onClick={onDelete}
              aria-label={t.backgroundTasks.delete}
              title={t.backgroundTasks.delete}
            >
              <Trash2Icon className="size-3.5" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Task detail view with output
// ---------------------------------------------------------------------------

function TaskDetailView({
  task,
  onBack,
  onPause,
  onResume,
  onCancel,
}: {
  task: BackgroundTask;
  onBack: () => void;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const { messages, done, doneStatus } = useBackgroundTaskOutput(task.task_id);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-3">
        <Button
          variant="ghost"
          size="icon"
          className="size-7"
          onClick={onBack}
          aria-label={t.backgroundTasks.back}
          title={t.backgroundTasks.back}
        >
          <ChevronLeftIcon className="size-4" />
        </Button>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-medium">
            {task.name || t.backgroundTasks.title}
          </h3>
          <div className="flex items-center gap-2 mt-0.5">
            <StatusBadge status={task.status} />
            <span className="text-xs text-muted-foreground font-mono">
              {task.task_id}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {task.status === "running" && (
            <Button variant="outline" size="sm" onClick={onPause}>
              <PauseIcon className="size-3.5 mr-1" />
              {t.backgroundTasks.pause}
            </Button>
          )}
          {(task.status === "paused" || task.status === "interrupted") && (
            <Button variant="outline" size="sm" onClick={onResume}>
              <PlayIcon className="size-3.5 mr-1" />
              {t.backgroundTasks.resume}
            </Button>
          )}
          {isActiveStatus(task.status) && (
            <Button
              variant="outline"
              size="sm"
              className="text-destructive border-destructive/30 hover:bg-destructive/10"
              onClick={onCancel}
            >
              <SquareIcon className="size-3.5 mr-1" />
              {t.backgroundTasks.cancel}
            </Button>
          )}
        </div>
      </div>

      {/* Task info */}
      <div className="border-b px-4 py-2 text-xs">
        <div className="flex items-center gap-4 text-muted-foreground">
          <span>
            {t.backgroundTasks.agentLabel}:{" "}
            <span className="text-foreground">{task.assistant_id}</span>
          </span>
          {task.thread_id && (
            <span>
              {t.backgroundTasks.threadLabel}:{" "}
              <span className="font-mono text-foreground">
                {task.thread_id.slice(0, 8)}
              </span>
            </span>
          )}
          {task.started_at && (
            <span>
              {t.backgroundTasks.durationLabel}:{" "}
              <span className="text-foreground">
                {formatDuration(task.started_at, task.finished_at)}
              </span>
            </span>
          )}
        </div>
        {task.error && (
          <div className="mt-1 rounded bg-destructive/10 px-2 py-1 text-destructive text-xs">
            {task.error}
          </div>
        )}
      </div>

      {/* Output stream */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
            {isActiveStatus(task.status) ? (
              <>
                <Loader2Icon className="size-6 animate-spin mb-2" />
                <span className="text-sm">
                  {t.backgroundTasks.waitingOutput}
                </span>
              </>
            ) : (
              <span className="text-sm">{t.backgroundTasks.noOutput}</span>
            )}
          </div>
        ) : (
          messages.map((msg) => (
            <OutputMessageItem key={msg.seq} message={msg} />
          ))
        )}
        {done && doneStatus && (
          <div className="flex items-center gap-2 rounded-lg border px-3 py-2 text-xs">
            {doneStatus === "completed" ? (
              <CheckCircle2Icon className="size-4 text-success" />
            ) : (
              <AlertCircleIcon className="size-4 text-destructive" />
            )}
            <span>
              {t.backgroundTasks.taskFinished(
                statusLabel(doneStatus, t.backgroundTasks),
              )}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function OutputMessageItem({ message }: { message: BackgroundTaskOutput }) {
  const { t } = useI18n();
  const isStatus = message.role === "status";
  const isError = message.role === "error";

  return (
    <div
      className={cn(
        "rounded-lg px-3 py-2 text-sm",
        isStatus && "bg-muted/50 text-muted-foreground text-xs italic",
        isError && "bg-destructive/10 text-destructive text-xs",
        !isStatus && !isError && "bg-accent/30",
      )}
    >
      {!isStatus && !isError && (
        <div className="mb-0.5 text-xs font-medium text-muted-foreground uppercase">
          {message.role}
        </div>
      )}
      <div className="whitespace-pre-wrap break-words leading-relaxed">
        {message.content}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {formatRelativeTime(message.timestamp, t.backgroundTasks)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// New task form
// ---------------------------------------------------------------------------

function NewTaskForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (prompt: string, name: string) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [prompt, setPrompt] = useState("");
  const [name, setName] = useState("");
  const nameId = useId();
  const promptId = useId();

  return (
    <div className="space-y-3 p-4">
      <div>
        <label
          htmlFor={nameId}
          className="text-xs font-medium text-muted-foreground"
        >
          {t.backgroundTasks.taskName}
        </label>
        <Input
          id={nameId}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t.backgroundTasks.taskNamePlaceholder}
          className="mt-1"
        />
      </div>
      <div>
        <label
          htmlFor={promptId}
          className="text-xs font-medium text-muted-foreground"
        >
          {t.backgroundTasks.promptLabel}
        </label>
        <textarea
          id={promptId}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={t.backgroundTasks.promptPlaceholder}
          rows={5}
          className="mt-1 w-full rounded-lg border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
        />
      </div>
      <div className="flex items-center gap-2 justify-end">
        <Button variant="outline" size="sm" onClick={onCancel}>
          {t.backgroundTasks.cancel}
        </Button>
        <Button
          size="sm"
          disabled={!prompt.trim()}
          onClick={() => onSubmit(prompt.trim(), name.trim())}
        >
          <ZapIcon className="size-3.5 mr-1" />
          {t.backgroundTasks.runInBackground}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel (rendered inside Sheet)
// ---------------------------------------------------------------------------

function BackgroundTasksPanelContent() {
  const { t } = useI18n();
  const {
    tasks,
    loading,
    error,
    refresh,
    submit,
    pause,
    resume,
    cancel,
    remove,
  } = useBackgroundTasks();
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [showNewForm, setShowNewForm] = useState(false);
  const { confirm, confirmDialog } = useConfirmDialog();

  const selectedTask = tasks.find((t) => t.task_id === selectedTaskId) ?? null;

  const handleSubmit = useCallback(
    async (prompt: string, name: string) => {
      try {
        const task = await submit({ prompt, name });
        setShowNewForm(false);
        setSelectedTaskId(task.task_id);
      } catch (e) {
        swallow(e);
      }
    },
    [submit],
  );

  const confirmCancel = useCallback(
    async (task: BackgroundTask) => {
      const taskLabel =
        task.name || task.prompt.slice(0, 50) || t.backgroundTasks.unnamedTask;
      const ok = await confirm({
        title: t.backgroundTasks.cancel,
        description: t.backgroundTasks.cancelConfirm(taskLabel),
        confirmLabel: t.backgroundTasks.cancel,
      });
      if (ok) cancel(task.task_id);
    },
    [confirm, cancel, t],
  );

  const confirmDelete = useCallback(
    async (task: BackgroundTask) => {
      const taskLabel =
        task.name || task.prompt.slice(0, 50) || t.backgroundTasks.unnamedTask;
      const ok = await confirm({
        title: t.backgroundTasks.delete,
        description: t.backgroundTasks.deleteConfirm(taskLabel),
      });
      if (ok) {
        if (selectedTaskId === task.task_id) setSelectedTaskId(null);
        remove(task.task_id);
      }
    },
    [confirm, remove, selectedTaskId, t],
  );

  // Show task detail
  if (selectedTask) {
    return (
      <>
        <TaskDetailView
          task={selectedTask}
          onBack={() => setSelectedTaskId(null)}
          onPause={() => pause(selectedTask.task_id)}
          onResume={() => resume(selectedTask.task_id)}
          onCancel={() => void confirmCancel(selectedTask)}
        />
        {confirmDialog}
      </>
    );
  }

  // Show new task form
  if (showNewForm) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => setShowNewForm(false)}
            aria-label={t.backgroundTasks.back}
            title={t.backgroundTasks.back}
          >
            <ChevronLeftIcon className="size-4" />
          </Button>
          <h3 className="text-sm font-medium">{t.backgroundTasks.newTask}</h3>
        </div>
        <NewTaskForm
          onSubmit={handleSubmit}
          onCancel={() => setShowNewForm(false)}
        />
      </div>
    );
  }

  // Task list
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-medium">{t.backgroundTasks.title}</h3>
          {tasks.filter((t) => isActiveStatus(t.status)).length > 0 && (
            <Badge variant="secondary" className="text-xs px-1.5 py-0">
              {t.backgroundTasks.activeCount(
                tasks.filter((task) => isActiveStatus(task.status)).length,
              )}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={refresh}
            aria-label={t.backgroundTasks.refresh}
            title={t.backgroundTasks.refresh}
          >
            <RefreshCwIcon className="size-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            onClick={() => setShowNewForm(true)}
            aria-label={t.backgroundTasks.newTask}
            title={t.backgroundTasks.newTask}
          >
            <PlusIcon className="size-3.5" />
          </Button>
        </div>
      </div>

      {/* Content */}
      {loading && tasks.length === 0 ? (
        <div className="flex items-center justify-center py-12">
          <Loader2Icon className="size-5 animate-spin text-muted-foreground" />
          <span className="sr-only">{t.backgroundTasks.loading}</span>
        </div>
      ) : error ? (
        <div
          role="alert"
          className="flex flex-col items-center justify-center gap-3 px-4 py-12 text-center"
        >
          <AlertCircleIcon className="size-7 text-destructive/70" />
          <p className="text-sm text-destructive">
            {t.backgroundTasks.loadFailed}
          </p>
          <Button variant="outline" size="sm" onClick={refresh}>
            <RefreshCwIcon className="mr-1 size-3.5" />
            {t.backgroundTasks.retry}
          </Button>
        </div>
      ) : tasks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
          <ZapIcon className="size-8 text-muted-foreground/40 mb-3" />
          <p className="text-sm font-medium text-muted-foreground">
            {t.backgroundTasks.noTasks}
          </p>
          <p className="mt-1 text-xs text-muted-foreground/70">
            {t.backgroundTasks.noTasksDescription}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-4"
            onClick={() => setShowNewForm(true)}
          >
            <PlusIcon className="size-3.5 mr-1" />
            {t.backgroundTasks.newTask}
          </Button>
        </div>
      ) : (
        <ScrollArea className="flex-1">
          <div className="space-y-2 p-3">
            {tasks.map((task) => (
              <TaskListItem
                key={task.task_id}
                task={task}
                isSelected={task.task_id === selectedTaskId}
                onSelect={() => setSelectedTaskId(task.task_id)}
                onPause={() => pause(task.task_id)}
                onResume={() => resume(task.task_id)}
                onCancel={() => void confirmCancel(task)}
                onDelete={() => void confirmDelete(task)}
              />
            ))}
          </div>
        </ScrollArea>
      )}
      {confirmDialog}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exported sheet trigger + panel
// ---------------------------------------------------------------------------

export function BackgroundTasksPanel({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[var(--dialog-lg)] sm:w-[var(--dialog-lg)] p-0">
        <SheetHeader className="sr-only">
          <SheetTitle>{t.backgroundTasks.title}</SheetTitle>
        </SheetHeader>
        <BackgroundTasksPanelContent />
      </SheetContent>
    </Sheet>
  );
}

/**
 * Standalone trigger button that opens the background tasks panel.
 * Shows a badge with the active task count.
 */
export function BackgroundTasksTrigger({ className }: { className?: string }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className={cn("relative size-8", className)}
        onClick={() => setOpen(true)}
        aria-label={t.backgroundTasks.title}
        title={t.backgroundTasks.title}
      >
        <ZapIcon className="size-4" />
      </Button>
      <BackgroundTasksPanel open={open} onOpenChange={setOpen} />
    </>
  );
}
