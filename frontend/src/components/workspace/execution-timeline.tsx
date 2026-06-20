/* Implementation note. */
import {
  BrainCircuitIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleDotIcon,
  ClockIcon,
  CpuIcon,
  SearchIcon,
  WrenchIcon,
  ZapIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

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
      color: "bg-gray-500",
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

  const load = useCallback(async () => {
    try {
      const r = await fetch(
        `${getBackendBaseURL()}/api/journal/timeline?limit=30`,
        {
          headers: authHeaders(),
        },
      );
      if (r.ok) setData(await r.json());
    } catch (e) {
      swallow(e);
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
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        {t.executionTimeline.loading}
      </div>
    );
  }
  if (!data || taskIds.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        {t.executionTimeline.empty}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <SearchIcon className="size-4 text-muted-foreground" />
        <input
          className="h-8 flex-1 rounded-lg border border-border/60 bg-background/60 px-3 text-xs outline-none placeholder:text-muted-foreground focus:border-primary/50"
          placeholder={t.executionTimeline.searchPlaceholder}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button
          onClick={() => {
            setLoading(true);
            void load();
          }}
          className="rounded-lg border border-border/60 px-3 py-1.5 text-xs hover:bg-muted"
        >
          {t.executionTimeline.refresh}
        </button>
      </div>

      {taskIds.map((tid) => {
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
            className="rounded-xl border border-border/60 bg-background/60 overflow-hidden"
          >
            <button
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-muted/30"
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
                    <span className="rounded-md bg-violet-500/15 px-1.5 py-0.5 text-[10px] text-violet-400">
                      {strategy}
                    </span>
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
              <div className="border-t border-border/40 px-4 py-3">
                <div className="relative ml-3 border-l-2 border-border/40 pl-6 space-y-4">
                  {events.map((ev, i) => {
                    const style = eventStyle(ev.event_type);
                    return (
                      <div key={i} className="relative">
                        <div
                          className={`absolute -left-[31px] top-0.5 flex size-5 items-center justify-center rounded-full text-white ${style.color}`}
                        >
                          {style.icon}
                        </div>
                        <div className="text-xs">
                          <div className="flex items-center gap-2">
                            <span className="font-medium">{ev.event_type}</span>
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
                            <div className="mt-1 rounded-lg bg-muted/40 px-2.5 py-1.5 text-[11px] text-muted-foreground">
                              {stripTraceLabelPrefixes(ev.thought).slice(
                                0,
                                200,
                              )}
                            </div>
                          )}
                          {ev.action && (
                            <div className="mt-1 rounded-lg bg-blue-500/10 px-2.5 py-1.5 text-[11px] font-mono text-blue-300">
                              {stripTraceLabelPrefixes(ev.action).slice(0, 150)}
                            </div>
                          )}
                          {ev.observation && (
                            <div className="mt-1 max-h-24 overflow-y-auto rounded-lg bg-muted/30 px-2.5 py-1.5 text-[11px] text-muted-foreground">
                              {stripTraceLabelPrefixes(ev.observation).slice(
                                0,
                                300,
                              )}
                            </div>
                          )}
                          {ev.final_answer && (
                            <div className="mt-1 rounded-lg bg-emerald-500/10 px-2.5 py-1.5 text-[11px] text-emerald-400">
                              {stripTraceLabelPrefixes(ev.final_answer).slice(
                                0,
                                200,
                              )}
                            </div>
                          )}
                          {ev.error && (
                            <div className="mt-1 rounded-lg bg-rose-500/10 px-2.5 py-1.5 text-[11px] text-rose-400">
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
      })}
    </div>
  );
}
