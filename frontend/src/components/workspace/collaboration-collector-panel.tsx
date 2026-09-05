"use client";

import {
  ArchiveIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleIcon,
  Loader2Icon,
  RotateCcwIcon,
  SquareIcon,
  XCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import type { LiveToolEvent } from "./live-tool-timeline";

type CollectorChildStatus = "success" | "failed" | "cancelled";
type CollectorStatus = "collecting" | "completed" | "failed" | "cancelled";

interface CollectorAttempt {
  attempt: number;
  child_id: string;
  completed_at: string;
  result?: Record<string, unknown>;
  status: CollectorChildStatus;
}

interface CollectorSnapshot {
  active_retry_child_ids: string[];
  archived?: boolean;
  archived_at?: string | null;
  attempt_count: number;
  completed_count: number;
  expected_child_ids: string[];
  expected_count: number;
  failure_count: number;
  generation: number;
  remaining_child_ids: string[];
  results: Array<CollectorAttempt & { pending_retry?: boolean }>;
  revision: number;
  status: CollectorStatus;
  success_count: number;
}

interface CollectorResponse {
  collector?: CollectorSnapshot;
}

interface AttemptsResponse {
  attempts?: CollectorAttempt[];
}

interface CollectorOperationsResponse {
  collectors?: Array<{
    collector?: { status?: CollectorStatus };
    retryable_child_ids?: string[];
    run_id?: string;
  }>;
}

interface CollaborationCoordinate {
  contextPlan: {
    deepRecall: boolean;
    fullTokens: number;
    reductionPercent: number;
    selectedTokens: number;
  } | null;
  displayNames: Map<string, string>;
  runId: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function runIdFromRecord(value: unknown): string | undefined {
  if (!isRecord(value)) return undefined;
  return (
    stringValue(value.collaboration_run_id) ??
    (isRecord(value.result)
      ? stringValue(value.result.collaboration_run_id)
      : undefined)
  );
}

function finiteNonNegative(value: unknown): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.max(0, numeric) : 0;
}

function contextPlanFromRecord(
  value: unknown,
): CollaborationCoordinate["contextPlan"] {
  if (!isRecord(value)) return null;
  if (!isRecord(value.context_plan)) {
    return isRecord(value.result) ? contextPlanFromRecord(value.result) : null;
  }
  const plan = value.context_plan;
  const selectedTokens = finiteNonNegative(plan.selected_estimated_tokens);
  const fullTokens = finiteNonNegative(plan.full_context_estimated_tokens);
  const reportedReduction = Number(plan.estimated_reduction_ratio);
  const reductionRatio = Number.isFinite(reportedReduction)
    ? Math.min(1, Math.max(0, reportedReduction))
    : fullTokens > 0
      ? Math.max(0, Math.min(1, (fullTokens - selectedTokens) / fullTokens))
      : 0;
  return {
    deepRecall: plan.deep_recall_escalated === true,
    fullTokens,
    reductionPercent: Math.round(reductionRatio * 1000) / 10,
    selectedTokens,
  };
}

export function latestCollaborationCoordinate(
  events: LiveToolEvent[],
): CollaborationCoordinate | null {
  for (const event of [...events].reverse()) {
    if (event.name.replace(/^mcp:/, "") !== "team_swarm") continue;
    const args = isRecord(event.input?.arguments)
      ? event.input.arguments
      : event.input;
    const runId = runIdFromRecord(args) ?? runIdFromRecord(event.output);
    if (!runId) continue;
    const displayNames = new Map<string, string>();
    const specs = args?.specs;
    if (Array.isArray(specs)) {
      for (const spec of specs) {
        if (!isRecord(spec)) continue;
        const id = stringValue(spec.agent_id);
        if (!id) continue;
        displayNames.set(id, stringValue(spec.display_name) ?? id);
      }
    }
    return {
      contextPlan:
        contextPlanFromRecord(event.output) ?? contextPlanFromRecord(args),
      displayNames,
      runId,
    };
  }
  return null;
}

function attemptReason(attempt: CollectorAttempt | undefined): string {
  if (!attempt || !isRecord(attempt.result)) return "";
  return (
    stringValue(attempt.result.error) ??
    stringValue(attempt.result.message) ??
    stringValue(attempt.result.detail) ??
    ""
  );
}

function attemptContextDelivery(
  attempt: CollectorAttempt | undefined,
): { avoided: number; mode: string; sent: number } | null {
  if (!attempt || !isRecord(attempt.result)) return null;
  const delivery = attempt.result.context_delivery;
  if (!isRecord(delivery)) return null;
  const mode = stringValue(delivery.mode);
  if (!mode || mode === "unavailable") return null;
  const sent = Number(delivery.sent_estimated_tokens);
  const avoided = Number(delivery.avoided_estimated_tokens);
  return {
    avoided: Number.isFinite(avoided) ? Math.max(0, avoided) : 0,
    mode,
    sent: Number.isFinite(sent) ? Math.max(0, sent) : 0,
  };
}

function attemptSessionCompaction(
  attempt: CollectorAttempt | undefined,
): { rawTurns: number; throughTurn: number } | null {
  if (!attempt || !isRecord(attempt.result)) return null;
  const compaction = attempt.result.session_compaction;
  if (!isRecord(compaction) || compaction.checkpoint_valid !== true)
    return null;
  const throughTurn = Number(compaction.checkpoint_through_turn);
  const rawTurns = Number(compaction.raw_turns_retained);
  if (!Number.isFinite(throughTurn) || throughTurn <= 0) return null;
  return {
    rawTurns: Number.isFinite(rawTurns)
      ? Math.max(throughTurn, rawTurns)
      : throughTurn,
    throughTurn,
  };
}

export function CollaborationCollectorPanel({
  events,
  threadId,
}: {
  events: LiveToolEvent[];
  threadId?: string;
}) {
  const { t } = useI18n();
  const coordinate = useMemo(
    () => latestCollaborationCoordinate(events),
    [events],
  );
  const [collector, setCollector] = useState<CollectorSnapshot | null>(null);
  const [attempts, setAttempts] = useState<CollectorAttempt[]>([]);
  const [expandedChildren, setExpandedChildren] = useState<Set<string>>(
    () => new Set(),
  );
  const [busy, setBusy] = useState(false);
  const [steeringChildId, setSteeringChildId] = useState<string | null>(null);
  const [steeringText, setSteeringText] = useState("");
  const [steeringBusyChildId, setSteeringBusyChildId] = useState<string | null>(
    null,
  );
  const [stoppingChildId, setStoppingChildId] = useState<string | null>(null);
  const [error, setError] = useState<
    "cancel" | "load" | "memberCancel" | "queue" | "retry" | "steer" | null
  >(null);
  const [monitorGeneration, setMonitorGeneration] = useState(0);
  const [retryableRunIds, setRetryableRunIds] = useState<string[]>([]);
  const [activeRunIds, setActiveRunIds] = useState<string[]>([]);

  const loadAttempts = useCallback(
    async (signal?: AbortSignal) => {
      if (!threadId || !coordinate) return;
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(coordinate.runId)}/collector/attempts`,
        { headers: authHeaders(), signal },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AttemptsResponse;
      setAttempts(Array.isArray(payload.attempts) ? payload.attempts : []);
    },
    [coordinate, threadId],
  );

  const loadOperations = useCallback(
    async (signal?: AbortSignal) => {
      if (!threadId) return;
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/collectors?limit=100`,
        { headers: authHeaders(), signal },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as CollectorOperationsResponse;
      const items = payload.collectors ?? [];
      setRetryableRunIds(
        items
          .map((item) => stringValue(item.run_id))
          .filter((runId, index): runId is string =>
            Boolean(
              runId && (items[index]?.retryable_child_ids?.length ?? 0) > 0,
            ),
          ),
      );
      setActiveRunIds(
        items
          .map((item) => stringValue(item.run_id))
          .filter((runId, index): runId is string =>
            Boolean(runId && items[index]?.collector?.status === "collecting"),
          ),
      );
    },
    [threadId],
  );

  useEffect(() => {
    if (!threadId || !coordinate) {
      setCollector(null);
      setAttempts([]);
      setRetryableRunIds([]);
      setActiveRunIds([]);
      return;
    }
    const controller = new AbortController();
    let active = true;

    const monitor = async () => {
      let revision = 0;
      let waitMs = 0;
      try {
        while (active) {
          const params = new URLSearchParams({
            after_revision: String(revision),
            wait_ms: String(waitMs),
          });
          const response = await fetch(
            `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(coordinate.runId)}/collector?${params}`,
            { headers: authHeaders(), signal: controller.signal },
          );
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const payload = (await response.json()) as CollectorResponse;
          if (!payload.collector) throw new Error("collector missing");
          setCollector(payload.collector);
          setError(null);
          revision = payload.collector.revision;
          await loadAttempts(controller.signal);
          await loadOperations(controller.signal).catch(() => undefined);
          if (payload.collector.status !== "collecting") break;
          waitMs = 25_000;
        }
      } catch (cause) {
        if (
          active &&
          !(cause instanceof DOMException && cause.name === "AbortError")
        ) {
          setError("load");
        }
      }
    };

    void monitor();
    return () => {
      active = false;
      controller.abort();
    };
  }, [coordinate, loadAttempts, loadOperations, monitorGeneration, threadId]);

  const attemptsByChild = useMemo(() => {
    const grouped = new Map<string, CollectorAttempt[]>();
    for (const attempt of attempts) {
      const list = grouped.get(attempt.child_id) ?? [];
      list.push(attempt);
      grouped.set(attempt.child_id, list);
    }
    return grouped;
  }, [attempts]);

  const retryableIds = useMemo(() => {
    if (!collector || collector.archived) return [];
    const ids = collector.results
      .filter(
        (result) => result.status === "failed" || result.status === "cancelled",
      )
      .map((result) => result.child_id);
    return [...new Set(ids)];
  }, [collector]);

  const retryFailed = useCallback(async () => {
    if (!threadId || !coordinate || retryableIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(coordinate.runId)}/collector/retry`,
        {
          body: JSON.stringify({ child_ids: retryableIds }),
          headers: jsonAuthHeaders(),
          method: "POST",
        },
      );
      if (response.status === 429) {
        setError("queue");
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as CollectorResponse;
      if (payload.collector) setCollector(payload.collector);
      await loadAttempts();
      await loadOperations().catch(() => undefined);
      setMonitorGeneration((value) => value + 1);
    } catch {
      setError("retry");
    } finally {
      setBusy(false);
    }
  }, [coordinate, loadAttempts, loadOperations, retryableIds, threadId]);

  const retryFailedRuns = useCallback(async () => {
    if (!threadId || retryableRunIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/collectors/retry`,
        {
          body: JSON.stringify({ run_ids: retryableRunIds }),
          headers: jsonAuthHeaders(),
          method: "POST",
        },
      );
      if (response.status === 429) {
        setError("queue");
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as {
        collectors?: CollectorSnapshot[];
      };
      const currentIndex = retryableRunIds.indexOf(coordinate?.runId ?? "");
      if (currentIndex >= 0 && payload.collectors?.[currentIndex]) {
        setCollector(payload.collectors[currentIndex]);
      }
      await loadAttempts();
      await loadOperations().catch(() => undefined);
      setMonitorGeneration((value) => value + 1);
    } catch {
      setError("retry");
    } finally {
      setBusy(false);
    }
  }, [coordinate, loadAttempts, loadOperations, retryableRunIds, threadId]);

  const stopActiveRuns = useCallback(async () => {
    if (!threadId || activeRunIds.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/collectors/cancel`,
        {
          body: JSON.stringify({ run_ids: activeRunIds }),
          headers: jsonAuthHeaders(),
          method: "POST",
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as {
        collectors?: Array<{
          collector?: CollectorSnapshot;
          run_id?: string;
        }>;
      };
      const current = payload.collectors?.find(
        (item) => item.run_id === coordinate?.runId,
      );
      if (current?.collector) setCollector(current.collector);
      await loadAttempts();
      await loadOperations().catch(() => undefined);
      setMonitorGeneration((value) => value + 1);
    } catch {
      setError("cancel");
    } finally {
      setBusy(false);
    }
  }, [activeRunIds, coordinate, loadAttempts, loadOperations, threadId]);

  const steerMember = useCallback(
    async (childId: string) => {
      const text = steeringText.trim();
      if (!threadId || !coordinate || !text) return;
      setSteeringBusyChildId(childId);
      setError(null);
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(coordinate.runId)}/collector/${encodeURIComponent(childId)}/steer`,
          {
            body: JSON.stringify({ text }),
            headers: jsonAuthHeaders(),
            method: "POST",
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as CollectorResponse;
        if (payload.collector) setCollector(payload.collector);
        setSteeringChildId(null);
        setSteeringText("");
        setMonitorGeneration((value) => value + 1);
      } catch {
        setError("steer");
      } finally {
        setSteeringBusyChildId(null);
      }
    },
    [coordinate, steeringText, threadId],
  );

  const stopMember = useCallback(
    async (childId: string) => {
      if (!threadId || !coordinate) return;
      setStoppingChildId(childId);
      setError(null);
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(coordinate.runId)}/collector/${encodeURIComponent(childId)}/cancel`,
          {
            body: JSON.stringify({}),
            headers: jsonAuthHeaders(),
            method: "POST",
          },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as CollectorResponse;
        if (payload.collector) setCollector(payload.collector);
        if (steeringChildId === childId) {
          setSteeringChildId(null);
          setSteeringText("");
        }
        setMonitorGeneration((value) => value + 1);
      } catch {
        setError("memberCancel");
      } finally {
        setStoppingChildId(null);
      }
    },
    [coordinate, steeringChildId, threadId],
  );

  if (!threadId || !coordinate || (!collector && error !== "load")) return null;

  if (!collector) {
    return (
      <section
        className="border-b border-border-subtle py-4"
        data-testid="collaboration-collector-panel"
      >
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <XCircleIcon className="size-3.5 text-warning" />
          <span>{t.coworkCollab.collectorMonitorUnavailable}</span>
        </div>
      </section>
    );
  }

  const showBatchRetry =
    retryableRunIds.length > 1 ||
    (retryableRunIds.length > 0 && !retryableRunIds.includes(coordinate.runId));
  const showCurrentRetry =
    !showBatchRetry &&
    retryableIds.length > 0 &&
    collector.status !== "collecting";
  const showStop = activeRunIds.length > 0;

  return (
    <section
      className="border-b border-border-subtle py-4"
      data-testid="collaboration-collector-panel"
    >
      <div className="flex min-w-0 items-center gap-2">
        <h3 className="text-xs font-medium text-foreground">
          {t.coworkCollab.collectorTitle}
        </h3>
        <span className="text-xs tabular-nums text-muted-foreground">
          {t.coworkCollab.collectorProgress(
            collector.completed_count,
            collector.expected_count,
          )}
        </span>
        {collector.archived ? (
          <span className="inline-flex items-center gap-1 text-mini text-muted-foreground">
            <ArchiveIcon className="size-3" />
            {t.coworkCollab.collectorArchived}
          </span>
        ) : null}
        {showStop || showBatchRetry || showCurrentRetry ? (
          <div className="ml-auto flex items-center">
            {showStop ? (
              <button
                type="button"
                disabled={busy}
                className="inline-flex h-7 items-center gap-1.5 px-1 text-xs font-medium text-destructive hover:text-destructive/75 disabled:opacity-50"
                onClick={() => void stopActiveRuns()}
              >
                {busy ? (
                  <Loader2Icon className="size-3.5 animate-spin" />
                ) : (
                  <SquareIcon className="size-3.5" />
                )}
                {activeRunIds.length > 1
                  ? t.coworkCollab.collectorStopRuns(activeRunIds.length)
                  : t.coworkCollab.collectorStop}
              </button>
            ) : showCurrentRetry ? (
              <button
                type="button"
                disabled={busy}
                className="inline-flex h-7 items-center gap-1.5 px-1 text-xs font-medium text-primary hover:text-primary/75 disabled:opacity-50"
                onClick={() => void retryFailed()}
              >
                <RotateCcwIcon
                  className={cn("size-3.5", busy && "animate-spin")}
                />
                {t.coworkCollab.collectorRetryFailedOnly}
              </button>
            ) : null}
            {!showStop && showBatchRetry ? (
              <button
                type="button"
                disabled={busy}
                className="inline-flex h-7 items-center gap-1.5 px-1 text-xs font-medium text-primary hover:text-primary/75 disabled:opacity-50"
                onClick={() => void retryFailedRuns()}
              >
                <RotateCcwIcon
                  className={cn("size-3.5", busy && "animate-spin")}
                />
                {t.coworkCollab.collectorRetryFailedRuns(
                  retryableRunIds.length,
                )}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {coordinate.contextPlan ? (
        <p
          className="mt-2 text-mini tabular-nums text-muted-foreground"
          data-testid="collaboration-context-plan"
        >
          {t.coworkCollab.collectorContextPlan(
            coordinate.contextPlan.deepRecall ? "recall" : "selective",
            coordinate.contextPlan.selectedTokens,
            coordinate.contextPlan.fullTokens,
            coordinate.contextPlan.reductionPercent,
          )}
        </p>
      ) : null}

      {error === "retry" ||
      error === "queue" ||
      error === "cancel" ||
      error === "memberCancel" ||
      error === "steer" ? (
        <p className="mt-2 text-xs text-destructive">
          {error === "queue"
            ? t.coworkCollab.collectorQueueFull
            : error === "cancel"
              ? t.coworkCollab.collectorStopFailed
              : error === "memberCancel"
                ? t.coworkCollab.collectorStopMemberFailed
                : error === "steer"
                  ? t.coworkCollab.collectorSteerFailed
                  : t.coworkCollab.collectorRetryFailed}
        </p>
      ) : null}

      <ul className="mt-2 divide-y divide-border-subtle">
        {collector.expected_child_ids.map((childId) => {
          const result = collector.results.find(
            (item) => item.child_id === childId,
          );
          const childAttempts = attemptsByChild.get(childId) ?? [];
          const retrying = collector.active_retry_child_ids.includes(childId);
          const remaining = collector.remaining_child_ids.includes(childId);
          const expanded = expandedChildren.has(childId);
          const status = retrying
            ? "retrying"
            : (result?.status ?? (remaining ? "waiting" : "waiting"));
          const reason = attemptReason(result);
          const contextDelivery = attemptContextDelivery(result);
          const sessionCompaction = attemptSessionCompaction(result);
          const displayName = coordinate.displayNames.get(childId) ?? childId;
          const steerable =
            collector.status === "collecting" &&
            !collector.archived &&
            remaining;
          const steering = steeringChildId === childId;
          const StatusIcon =
            status === "success"
              ? CheckCircle2Icon
              : status === "failed" || status === "cancelled"
                ? XCircleIcon
                : status === "retrying"
                  ? Loader2Icon
                  : CircleIcon;
          const statusLabel =
            status === "success"
              ? t.coworkCollab.collectorSuccess
              : status === "failed"
                ? t.coworkCollab.collectorFailed
                : status === "cancelled"
                  ? t.coworkCollab.collectorCancelled
                  : status === "retrying"
                    ? t.coworkCollab.collectorRetrying
                    : t.coworkCollab.collectorWaiting;

          return (
            <li key={childId} className="py-2">
              <div className="flex min-w-0 items-start gap-2">
                <StatusIcon
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    status === "success" && "text-success",
                    (status === "failed" || status === "cancelled") &&
                      "text-destructive",
                    status === "retrying" && "animate-spin text-primary",
                    status === "waiting" && "text-muted-foreground/45",
                  )}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate text-xs font-medium text-foreground">
                      {displayName}
                    </span>
                    <span className="shrink-0 text-mini text-muted-foreground">
                      {statusLabel}
                    </span>
                  </div>
                  {reason ? (
                    <p className="mt-0.5 line-clamp-2 text-mini leading-4 text-muted-foreground">
                      {reason}
                    </p>
                  ) : null}
                  {contextDelivery || sessionCompaction ? (
                    <p className="mt-0.5 text-mini tabular-nums text-muted-foreground/75">
                      {contextDelivery
                        ? t.coworkCollab.collectorContextDelivery(
                            contextDelivery.mode,
                            contextDelivery.sent,
                            contextDelivery.avoided,
                          )
                        : null}
                      {contextDelivery && sessionCompaction ? " · " : null}
                      {sessionCompaction
                        ? t.coworkCollab.collectorMemoryCheckpoint(
                            sessionCompaction.throughTurn,
                            sessionCompaction.rawTurns,
                          )
                        : null}
                    </p>
                  ) : null}
                </div>
                {childAttempts.length > 1 ? (
                  <button
                    type="button"
                    aria-expanded={expanded}
                    className="inline-flex shrink-0 items-center gap-1 text-mini text-muted-foreground hover:text-foreground"
                    onClick={() =>
                      setExpandedChildren((previous) => {
                        const next = new Set(previous);
                        if (next.has(childId)) next.delete(childId);
                        else next.add(childId);
                        return next;
                      })
                    }
                  >
                    {t.coworkCollab.collectorAttempts(childAttempts.length)}
                    {expanded ? (
                      <ChevronDownIcon className="size-3" />
                    ) : (
                      <ChevronRightIcon className="size-3" />
                    )}
                  </button>
                ) : null}
                {steerable ? (
                  <div className="flex shrink-0 items-center gap-3">
                    <button
                      type="button"
                      aria-label={t.coworkCollab.collectorSteerMemberLabel(
                        displayName,
                      )}
                      className="text-mini font-medium text-primary hover:text-primary/75"
                      disabled={
                        busy ||
                        stoppingChildId === childId ||
                        steeringBusyChildId === childId
                      }
                      onClick={() => {
                        setError(null);
                        setSteeringChildId(childId);
                        setSteeringText("");
                      }}
                    >
                      {t.coworkCollab.collectorSteer}
                    </button>
                    <button
                      type="button"
                      aria-label={t.coworkCollab.collectorStopMemberLabel(
                        displayName,
                      )}
                      className="text-mini text-muted-foreground hover:text-destructive disabled:opacity-50"
                      disabled={
                        busy ||
                        stoppingChildId === childId ||
                        steeringBusyChildId === childId
                      }
                      onClick={() => void stopMember(childId)}
                    >
                      {stoppingChildId === childId
                        ? `${t.coworkCollab.collectorStopMember}…`
                        : t.coworkCollab.collectorStopMember}
                    </button>
                  </div>
                ) : null}
              </div>
              {steering ? (
                <div className="ml-5 mt-2 border-l border-border-subtle pl-3">
                  <textarea
                    autoFocus
                    aria-label={t.coworkCollab.collectorSteerPlaceholder(
                      displayName,
                    )}
                    className="min-h-16 w-full resize-y bg-transparent text-xs leading-5 text-foreground outline-none placeholder:text-muted-foreground/65"
                    disabled={steeringBusyChildId === childId}
                    maxLength={20_000}
                    placeholder={t.coworkCollab.collectorSteerPlaceholder(
                      displayName,
                    )}
                    value={steeringText}
                    onChange={(event) => setSteeringText(event.target.value)}
                  />
                  <div className="mt-1 flex items-center gap-3">
                    <button
                      type="button"
                      className="text-mini font-medium text-primary hover:text-primary/75 disabled:opacity-50"
                      disabled={
                        steeringBusyChildId === childId || !steeringText.trim()
                      }
                      onClick={() => void steerMember(childId)}
                    >
                      {steeringBusyChildId === childId
                        ? `${t.coworkCollab.collectorSteerSubmit}…`
                        : t.coworkCollab.collectorSteerSubmit}
                    </button>
                    <button
                      type="button"
                      className="text-mini text-muted-foreground hover:text-foreground disabled:opacity-50"
                      disabled={steeringBusyChildId === childId}
                      onClick={() => {
                        setSteeringChildId(null);
                        setSteeringText("");
                      }}
                    >
                      {t.coworkCollab.collectorSteerCancel}
                    </button>
                  </div>
                </div>
              ) : null}
              {expanded ? (
                <ol className="ml-5 mt-1 border-l border-border-subtle pl-2">
                  {childAttempts.map((attempt) => (
                    <li
                      key={`${childId}:${attempt.attempt}`}
                      className="py-1 text-mini text-muted-foreground"
                    >
                      <span className="font-medium text-foreground/80">
                        {t.coworkCollab.collectorAttempt(attempt.attempt)}
                      </span>
                      <span className="mx-1">·</span>
                      <span>
                        {attempt.status === "success"
                          ? t.coworkCollab.collectorSuccess
                          : attempt.status === "failed"
                            ? t.coworkCollab.collectorFailed
                            : t.coworkCollab.collectorCancelled}
                      </span>
                      {attemptReason(attempt) ? (
                        <span> · {attemptReason(attempt)}</span>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
