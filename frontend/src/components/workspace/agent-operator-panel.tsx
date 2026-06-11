import {
  ArchiveIcon,
  CheckCircle2Icon,
  Clock3Icon,
  GitBranchIcon,
  ListChecksIcon,
  RefreshCwIcon,
  XCircleIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  applyAgentTraceReviewQueuePromotions,
  decideAgentTraceReviewQueueItem,
  fetchAgentTraceProcessTimeline,
  fetchAgentTraceReviewQueue,
  fetchAgentTraceReviewQueueSummary,
  fetchAgentTraceTaskRuns,
  queueAgentTraceTaskRunReview,
  type AgentTraceProcessTimeline,
  type AgentTraceReviewQueueItem,
  type AgentTraceReviewQueueSummary,
  type AgentTraceTaskRun,
} from "@/core/agent-trace/api";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

const EMPTY_SUMMARY: AgentTraceReviewQueueSummary = {
  schema: "octopus.review_queue.v1",
  total: 0,
  pending_count: 0,
  by_status: {},
  by_priority: {},
  by_target_bucket: {},
  next_actions: [],
};

export function AgentOperatorPanel() {
  const [taskRuns, setTaskRuns] = useState<AgentTraceTaskRun[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<AgentTraceProcessTimeline | null>(null);
  const [queueItems, setQueueItems] = useState<AgentTraceReviewQueueItem[]>([]);
  const [queueSummary, setQueueSummary] =
    useState<AgentTraceReviewQueueSummary>(EMPTY_SUMMARY);
  const [loading, setLoading] = useState(true);
  const [lastApplyResult, setLastApplyResult] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refreshQueue = useCallback(async () => {
    const [items, summary] = await Promise.all([
      fetchAgentTraceReviewQueue(12, 0, { status: "pending" }),
      fetchAgentTraceReviewQueueSummary(),
    ]);
    setQueueItems(items);
    setQueueSummary(summary);
  }, []);

  const refreshTaskRuns = useCallback(async () => {
    const rows = await fetchAgentTraceTaskRuns(8);
    setTaskRuns(rows);
    setSelectedTaskId((current) => current ?? rows[0]?.task_id ?? null);
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([refreshTaskRuns(), refreshQueue()]);
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [refreshQueue, refreshTaskRuns]);

  useEffect(() => {
    void refreshAll();
    const timer = window.setInterval(refreshAll, 8000);
    return () => window.clearInterval(timer);
  }, [refreshAll]);

  useEffect(() => {
    if (!selectedTaskId) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    fetchAgentTraceProcessTimeline(selectedTaskId)
      .then((next) => {
        if (!cancelled) setTimeline(next);
      })
      .catch((err) => {
        swallow(err);
        if (!cancelled) setTimeline(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTaskId]);

  const selectedTask = useMemo(
    () => taskRuns.find((run) => run.task_id === selectedTaskId) ?? null,
    [selectedTaskId, taskRuns],
  );

  const onQueueSelectedReview = async () => {
    if (!selectedTaskId) return;
    setBusyId(`queue:${selectedTaskId}`);
    try {
      await queueAgentTraceTaskRunReview(selectedTaskId);
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onDecide = async (
    item: AgentTraceReviewQueueItem,
    action: "promoted" | "rejected" | "archived",
  ) => {
    setBusyId(item.id);
    try {
      await decideAgentTraceReviewQueueItem(item.id, {
        action,
        promotedTo: action === "promoted" ? item.target_bucket : undefined,
        reason: action === "promoted" ? "Accepted from operator panel." : "",
      });
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onApplyPromoted = async () => {
    setBusyId("apply-promoted");
    try {
      const result = await applyAgentTraceReviewQueuePromotions({ limit: 50 });
      setLastApplyResult(
        `Applied ${result.applied}, skipped ${result.skipped}, failed ${result.failed}`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="workspace-panel rounded-[1.5rem] px-5 py-4">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Operator loop
          </div>
          <h2 className="mt-1 text-base font-semibold">Agent evolution queue</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Task runs become review candidates first, then you decide what is
            promoted into memory, backlog, rules, or archive.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => void onApplyPromoted()}
            disabled={
              busyId === "apply-promoted" ||
              (queueSummary.by_status.promoted ?? 0) === 0
            }
          >
            <CheckCircle2Icon className="mr-1.5 size-3.5" />
            Apply promoted
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => void refreshAll()}
            disabled={loading}
          >
            <RefreshCwIcon className={cn("mr-1.5 size-3.5", loading && "animate-spin")} />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      {lastApplyResult && (
        <div className="mb-3 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          {lastApplyResult}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <Metric label="Pending" value={queueSummary.pending_count} tone="amber" />
        <Metric label="Promoted" value={queueSummary.by_status.promoted ?? 0} tone="emerald" />
        <Metric label="Rejected" value={queueSummary.by_status.rejected ?? 0} tone="rose" />
        <Metric label="Total" value={queueSummary.total} tone="blue" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="space-y-3">
          <PanelTitle
            icon={<GitBranchIcon className="size-4" />}
            title="Recent task runs"
            meta={`${taskRuns.length} loaded`}
          />
          <div className="overflow-hidden rounded-lg border border-border/60">
            {taskRuns.length === 0 ? (
              <EmptyPanel title="No task runs yet" />
            ) : (
              taskRuns.map((run) => (
                <button
                  key={run.task_id}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border/50 px-3 py-2 text-left last:border-b-0 hover:bg-muted/40",
                    selectedTaskId === run.task_id && "bg-primary/10",
                  )}
                  onClick={() => setSelectedTaskId(run.task_id)}
                >
                  <StatusDot status={run.status} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {run.title || run.summary || run.task_id}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{shortId(run.task_id)}</span>
                      <span>{run.tool_calls_started ?? 0} tools</span>
                      {(run.tool_errors ?? 0) > 0 && (
                        <span className="text-destructive">
                          {run.tool_errors} errors
                        </span>
                      )}
                    </div>
                  </div>
                  <Badge variant="outline" className="text-[10px]">
                    {run.status ?? "unknown"}
                  </Badge>
                </button>
              ))
            )}
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/15 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">
                  {selectedTask?.title || selectedTask?.summary || "No task selected"}
                </div>
                {selectedTaskId && (
                  <div className="font-mono text-[11px] text-muted-foreground">
                    {selectedTaskId}
                  </div>
                )}
              </div>
              <Button
                size="sm"
                className="h-8 shrink-0"
                disabled={!selectedTaskId || busyId === `queue:${selectedTaskId}`}
                onClick={() => void onQueueSelectedReview()}
              >
                <ListChecksIcon className="mr-1.5 size-3.5" />
                Queue review
              </Button>
            </div>
            <TimelinePreview timeline={timeline} />
          </div>
        </div>

        <div className="space-y-3">
          <PanelTitle
            icon={<ListChecksIcon className="size-4" />}
            title="Pending review queue"
            meta={`${queueSummary.pending_count} pending`}
          />
          <div className="space-y-2">
            {queueItems.length === 0 ? (
              <EmptyPanel title="No pending review items" />
            ) : (
              queueItems.map((item) => (
                <ReviewQueueRow
                  key={item.id}
                  item={item}
                  busy={busyId === item.id}
                  onPromote={() => void onDecide(item, "promoted")}
                  onReject={() => void onDecide(item, "rejected")}
                  onArchive={() => void onDecide(item, "archived")}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function TimelinePreview({
  timeline,
}: {
  timeline: AgentTraceProcessTimeline | null;
}) {
  if (!timeline) return <EmptyPanel title="No process timeline available" />;
  const nodes = timeline.timeline.slice(0, 8);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline" className="text-[10px]">
          score {formatScore(timeline.overview.score)}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          approvals {timeline.overview.approval_count ?? 0}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          lessons {timeline.overview.experience_record_count ?? 0}
        </Badge>
      </div>
      <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
        {nodes.map((node, index) => (
          <div
            key={`${node.lane}-${node.kind}-${node.ts ?? index}`}
            className="grid grid-cols-[5.5rem_1fr] gap-2 rounded-md bg-background/55 px-2 py-1.5 text-[11px]"
          >
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Clock3Icon className="size-3" />
              <span className="truncate">{node.lane}</span>
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium">
                {node.title || node.kind}
              </div>
              {(node.text || node.tool || node.status) && (
                <div className="truncate text-muted-foreground">
                  {node.text || node.tool || node.status}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewQueueRow({
  item,
  busy,
  onPromote,
  onReject,
  onArchive,
}: {
  item: AgentTraceReviewQueueItem;
  busy: boolean;
  onPromote: () => void;
  onReject: () => void;
  onArchive: () => void;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/65 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("text-[10px]", priorityClass(item.priority))}>
              {item.priority}
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {item.target_bucket}
            </Badge>
            <span className="text-[11px] text-muted-foreground">
              x{item.occurrences}
            </span>
          </div>
          <div className="mt-2 text-sm font-medium">{item.title}</div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {item.text}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span>{item.candidate_kind}</span>
            {(item.source_task_ids ?? []).slice(0, 2).map((taskId) => (
              <span key={taskId} className="font-mono">
                {shortId(taskId)}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <IconButton
            label="Promote"
            disabled={busy}
            onClick={onPromote}
            icon={<CheckCircle2Icon className="size-3.5" />}
          />
          <IconButton
            label="Reject"
            disabled={busy}
            onClick={onReject}
            icon={<XCircleIcon className="size-3.5" />}
          />
          <IconButton
            label="Archive"
            disabled={busy}
            onClick={onArchive}
            icon={<ArchiveIcon className="size-3.5" />}
          />
        </div>
      </div>
    </div>
  );
}

function IconButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
    </Button>
  );
}

function PanelTitle({
  icon,
  title,
  meta,
}: {
  icon: ReactNode;
  title: string;
  meta: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      <span className="text-[11px] text-muted-foreground">{meta}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "amber" | "emerald" | "rose" | "blue";
}) {
  const tones = {
    amber: "border-amber-500/25 bg-amber-500/10",
    emerald: "border-emerald-500/25 bg-emerald-500/10",
    rose: "border-rose-500/25 bg-rose-500/10",
    blue: "border-blue-500/25 bg-blue-500/10",
  };
  return (
    <div className={cn("rounded-lg border px-3 py-2", tones[tone])}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
    </div>
  );
}

function EmptyPanel({ title }: { title: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border/70 px-3 py-8 text-center text-sm text-muted-foreground">
      {title}
    </div>
  );
}

function StatusDot({ status }: { status?: string | null }) {
  const cls =
    status === "completed"
      ? "bg-emerald-500"
      : status === "failed"
        ? "bg-destructive"
        : status === "running"
          ? "bg-blue-500"
          : "bg-muted-foreground/40";
  return <span className={cn("size-2 shrink-0 rounded-full", cls)} />;
}

function priorityClass(priority: string) {
  if (priority === "P0") return "bg-destructive text-destructive-foreground";
  if (priority === "P1") return "bg-amber-500 text-white";
  return "bg-muted text-muted-foreground";
}

function shortId(id: string) {
  return id.length > 16 ? `${id.slice(0, 16)}...` : id;
}

function formatScore(score: unknown) {
  return typeof score === "number" ? score.toFixed(2) : "--";
}
