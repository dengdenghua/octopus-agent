/* Implementation note. */
import {
  BrainCircuitIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleDotIcon,
  ClockIcon,
  CpuIcon,
  SearchIcon,
  RefreshCwIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState, StatusBadge } from "@/components/ui/state";
import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { stripTraceLabelPrefixes } from "./messages/trace-labels";

/* ── types ─────────────────────────────────────────── */

interface TimelineEvent {
  event_type: string;
  ts: string;
  task_id: string;
  arm_id?: string | null;
  skill_name?: string;
  strategy?: string;
  thought?: string;
  action?: string;
  observation?: string;
  iteration?: number;
  final_answer?: string;
  error?: string;
  tokens_in?: number;
  tokens_out?: number;
  usd?: number;
  latency_ms?: number;
  model?: string;
  provider?: string;
}

interface TimelineResponse {
  task_ids: string[];
  timelines: Record<string, TimelineEvent[]>;
}

/* ── event icon/color mapping ──────────────────────── */

const EVENT_STYLE: Record<string, { icon: React.ReactNode; color: string }> = {
  step: { icon: <WrenchIcon className="size-3.5" />, color: "bg-blue-500" },
  trajectory: {
    icon: <BrainCircuitIcon className="size-3.5" />,
    color: "bg-violet-500",
  },
  react_checkpoint: {
    icon: <CpuIcon className="size-3.5" />,
    color: "bg-amber-500",
  },
  immune: { icon: <ZapIcon className="size-3.5" />, color: "bg-rose-500" },
  budget_squirt: {
    icon: <ClockIcon className="size-3.5" />,
    color: "bg-orange-500",
  },
  reflex_hit: {
    icon: <ZapIcon className="size-3.5" />,
    color: "bg-emerald-500",
  },
};

function eventStyle(type: string) {
  return (
    EVENT_STYLE[type] ?? {
      icon: <CircleDotIcon className="size-3.5" />,
      color: "bg-muted-foreground",
    }
  );
}

/* ── main component ────────────────────────────────── */

export function ExecutionTimeline() {
  const { t } = useI18n();
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch(
        `${getBackendBaseURL()}/api/journal/timeline?limit=30`,
        {
          headers: authHeaders(),
        },
      );
      if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
      setData(await r.json());
    } catch (e) {
      swallow(e);
      setError(e instanceof Error ? e.message : String(e));
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (tid: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(tid)) {
        next.delete(tid);
      } else {
        next.add(tid);
      }
      return next;
    });
  };

  const taskIds = (data?.task_ids ?? []).filter(
    (tid) => !filter || tid.toLowerCase().includes(filter.toLowerCase()),
  );

  if (loading) {
    return <LoadingState title={t.executionTimeline.loading} />;
  }
  if (error) {
    return (
      <ErrorState
        title={t.executionTimeline.loadFailed}
        detail={error}
        actionLabel={t.executionTimeline.refresh}
        onAction={() => void load()}
      />
    );
  }
  if (!data) {
    return (
      <Empty className="min-h-[220px]">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <ClockIcon />
          </EmptyMedia>
          <EmptyTitle>{t.executionTimeline.empty}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-8 rounded-lg pl-8 text-xs"
            placeholder={t.executionTimeline.searchPlaceholder}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            void load();
          }}
        >
          <RefreshCwIcon className="size-3.5" />
          {t.executionTimeline.refresh}
        </Button>
      </div>

      {taskIds.length === 0 ? (
        <Empty className="min-h-[220px]">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SearchIcon />
            </EmptyMedia>
            <EmptyTitle>
              {filter
                ? t.executionTimeline.noMatches
                : t.executionTimeline.empty}
            </EmptyTitle>
            {filter ? (
              <EmptyDescription>
                {t.executionTimeline.noMatchesDescription}
              </EmptyDescription>
            ) : null}
          </EmptyHeader>
        </Empty>
      ) : (
        taskIds.map((tid) => {
          const events = data.timelines[tid] ?? [];
          const isOpen = expanded.has(tid);
          const first = events[0];
          const last = events[events.length - 1];
          const strategy = events.find((e) => e.strategy)?.strategy;
          const totalTokens = events.reduce(
            (s, e) => s + (e.tokens_in ?? 0) + (e.tokens_out ?? 0),
            0,
          );
          const totalUsd = events.reduce((s, e) => s + (e.usd ?? 0), 0);

          return (
            <div
              key={tid}
              className="overflow-hidden rounded-xl border border-border/60 bg-background/60 transition-all duration-200 hover:border-border hover:shadow-md"
            >
              <button
                className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40"
                onClick={() => toggle(tid)}
              >
                {isOpen ? (
                  <ChevronDownIcon className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronRightIcon className="size-4 text-muted-foreground" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium font-mono">
                      {tid === "_no_task"
                        ? t.executionTimeline.noTask
                        : tid.slice(0, 12)}
                    </span>
                    {strategy && (
                      <StatusBadge tone="paused" className="h-5 text-[10px]">
                        {strategy}
                      </StatusBadge>
                    )}
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {events.length} {t.executionTimeline.events}
                    {totalTokens > 0 &&
                      ` · ${totalTokens.toLocaleString()} tokens`}
                    {totalUsd > 0 && ` · $${totalUsd.toFixed(4)}`}
                    {first && ` · ${new Date(first.ts).toLocaleTimeString()}`}
                    {last &&
                      first &&
                      last.ts !== first.ts &&
                      ` → ${new Date(last.ts).toLocaleTimeString()}`}
                  </div>
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-border/40 px-4 py-3 transition-all duration-200">
                  <div className="relative ml-3 space-y-4 border-l-2 border-border/40 pl-6">
                    {events.map((ev, i) => {
                      const style = eventStyle(ev.event_type);
                      return (
                        <div key={i} className="relative transition-all duration-200 hover:translate-x-0.5">
                          <div
                            className={`absolute -left-[31px] top-0.5 flex size-5 items-center justify-center rounded-full text-white shadow-sm transition-transform duration-200 ${style.color}`}
                          >
                            {style.icon}
                          </div>
                          <div className="text-xs">
                            <div className="flex items-center gap-2">
                              <span className="font-medium">
                                {ev.event_type}
                              </span>
                              {ev.skill_name && (
                                <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-[10px] text-blue-400">
                                  {ev.skill_name}
                                </span>
                              )}
                              {ev.iteration != null && (
                                <span className="text-[10px] text-muted-foreground">
                                  iter {ev.iteration}
                                </span>
                              )}
                              <span className="ml-auto text-[10px] text-muted-foreground">
                                {new Date(ev.ts).toLocaleTimeString()}
                              </span>
                            </div>
                            {ev.thought && (
                              <div className="mt-1 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px] text-muted-foreground transition-all duration-150 hover:bg-muted/60">
                                {stripTraceLabelPrefixes(ev.thought).slice(
                                  0,
                                  200,
                                )}
                              </div>
                            )}
                            {ev.action && (
                              <div className="mt-1 rounded-lg bg-primary/10 px-2.5 py-1.5 text-[11px] font-mono text-primary transition-all duration-150 hover:bg-primary/15">
                                {stripTraceLabelPrefixes(ev.action).slice(
                                  0,
                                  150,
                                )}
                              </div>
                            )}
                            {ev.observation && (
                              <div className="mt-1 max-h-24 overflow-y-auto rounded-lg bg-muted/30 px-2.5 py-1.5 text-[11px] text-muted-foreground transition-all duration-150 hover:bg-muted/50">
                                {stripTraceLabelPrefixes(ev.observation).slice(
                                  0,
                                  300,
                                )}
                              </div>
                            )}
                            {ev.final_answer && (
                              <div className="mt-1 rounded-lg bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-600 transition-all duration-150 hover:bg-emerald-500/15 dark:text-emerald-400">
                                {stripTraceLabelPrefixes(ev.final_answer).slice(
                                  0,
                                  200,
                                )}
                              </div>
                            )}
                            {ev.error && (
                              <div className="mt-1 rounded-lg bg-destructive/10 px-2.5 py-1.5 text-[11px] text-destructive transition-all duration-150 hover:bg-destructive/15">
                                {ev.error.slice(0, 200)}
                              </div>
                            )}
                            {(ev.tokens_in || ev.tokens_out || ev.model) && (
                              <div className="mt-1 flex gap-3 text-[10px] text-muted-foreground">
                                {ev.model && (
                                  <span>
                                    {ev.provider}/{ev.model}
                                  </span>
                                )}
                                {ev.tokens_in != null && (
                                  <span>{ev.tokens_in} in</span>
                                )}
                                {ev.tokens_out != null && (
                                  <span>{ev.tokens_out} out</span>
                                )}
                                {ev.latency_ms != null && (
                                  <span>{ev.latency_ms.toFixed(0)}ms</span>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
