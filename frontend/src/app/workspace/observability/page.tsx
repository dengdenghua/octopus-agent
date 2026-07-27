/* Implementation note. */

import {
  ActivityIcon,
  BrainCircuitIcon,
  CoinsIcon,
  DatabaseIcon,
  GaugeIcon,
  NetworkIcon,
  RefreshCwIcon,
  RotateCcwIcon,
  ShieldAlertIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { authHeaders, authedEventSource } from "@/core/auth/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Progress } from "@/components/ui/progress";
import { ErrorState, LoadingState } from "@/components/ui/state";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { AgentOperatorPanel } from "@/components/workspace/agent-operator-panel";
import { RunReviewPanel } from "@/components/workspace/run-review-panel";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import {
  authorizeToolEffectRetry,
  type ToolEffectReceipt,
  type ToolEffectsSnapshot,
} from "@/core/observability/api";
import { DiagnosticsContent } from "../diagnostics/page";

// ─── Shared polling helper ───────────────────────────────────
// Every heartbeat-driven panel follows the same shape: fetch JSON
// on an interval, track loading / error, expose a manual-refresh
// button. Abstracting it keeps each panel's render code tight.
function useHeartbeat<T>(
  url: string,
  intervalMs: number,
  initial: T,
): {
  data: T;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  lastFetchedAt: number | null;
} {
  const [data, setData] = useState<T>(initial);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastFetchedAt, setLastFetchedAt] = useState<number | null>(null);
  const tickRef = useRef(0);

  const fetchOnce = useCallback(async () => {
    const my = ++tickRef.current;
    try {
      const r = await fetch(url, { headers: authHeaders() });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = (await r.json()) as T;
      // Drop stale responses if a newer request was started.
      if (tickRef.current !== my) return;
      setData(j);
      setError(null);
      setLastFetchedAt(Date.now());
    } catch (e) {
      swallow(e);
      if (tickRef.current !== my) return;
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (tickRef.current === my) setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    void fetchOnce();
    const t = window.setInterval(fetchOnce, intervalMs);
    return () => window.clearInterval(t);
  }, [fetchOnce, intervalMs]);

  return { data, loading, error, refresh: fetchOnce, lastFetchedAt };
}

// ═══════════════════════════════════════════════════════════
// PAGE SHELL
// ═══════════════════════════════════════════════════════════

export default function ObservabilityPage({
  initialTab = "runs",
}: {
  initialTab?: string;
}) {
  const { t } = useI18n();
  const tab = normalizeObservabilityTab(initialTab);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="px-4 pb-4">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
          <section className="workspace-panel px-6 py-5">
            <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex size-11 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <ActivityIcon className="size-5" />
                </div>
                <div className="flex-1">
                  <h1 className="text-2xl font-bold tracking-tight">
                    {t.observabilityPage.pageTitle}
                  </h1>
                  <p className="text-sm text-muted-foreground">
                    {t.observabilityPage.subtitle}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 gap-2">
                <Button asChild className="h-9 rounded-full px-4">
                  <Link to="/workspace/realtime/new">开始一次任务</Link>
                </Button>
              </div>
            </div>

            <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <ObservabilitySignalCard
                icon={<ActivityIcon className="size-4" />}
                title="运行复盘"
                description="先看任务是否顺畅，哪里报错，哪里值得回看。"
              />
              <ObservabilitySignalCard
                icon={<NetworkIcon className="size-4" />}
                title="实时事件"
                description="并行协作、黑板和日志流合并成一个事件视图。"
              />
              <ObservabilitySignalCard
                icon={<GaugeIcon className="size-4" />}
                title="资源与成本"
                description="上下文预算、令牌消耗和成本汇总放在一起看。"
              />
              <ObservabilitySignalCard
                icon={<BrainCircuitIcon className="size-4" />}
                title="系统状态"
                description="自进化、诊断和后台状态统一收口。"
              />
            </div>
          </section>

          <Tabs defaultValue={tab} className="w-full">
            <TabsList className="grid h-auto w-full grid-cols-2 gap-1 p-1 md:grid-cols-4">
              <TabsTrigger value="overview" className="py-2">
                <ActivityIcon className="mr-1.5 size-3.5" />
                总览
              </TabsTrigger>
              <TabsTrigger value="events" className="py-2">
                <NetworkIcon className="mr-1.5 size-3.5" />
                事件流
              </TabsTrigger>
              <TabsTrigger value="resources" className="py-2">
                <GaugeIcon className="mr-1.5 size-3.5" />
                资源与成本
              </TabsTrigger>
              <TabsTrigger value="system" className="py-2">
                <BrainCircuitIcon className="mr-1.5 size-3.5" />
                系统
              </TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="mt-4">
              <div className="space-y-4">
                <section className="workspace-panel px-5 py-4">
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <div>
                      <h2 className="text-base font-semibold">先从总览开始</h2>
                      <p className="text-sm text-muted-foreground">
                        把当前后台的健康、事件、资源和系统状态分成四个视角，扫一眼就知道该去哪里。
                      </p>
                    </div>
                    <Button
                      asChild
                      variant="outline"
                      className="h-9 rounded-full px-4"
                    >
                      <Link to="/workspace/realtime/new">打开一次新任务</Link>
                    </Button>
                  </div>
                </section>
                <AgentOperatorPanel />
              </div>
            </TabsContent>

            <TabsContent value="events" className="mt-4 space-y-4">
              <PanelGroup
                eyebrow="事件流"
                title="运行、协作和日志放到一起看"
                description="这部分保留了原有的运行复盘、协作、黑板和日志，但不再把它们拆成一长排标签。"
              >
                <RunReviewPanel />
                <SwarmPanel />
                <BlackboardPanel />
                <JournalPanel />
              </PanelGroup>
            </TabsContent>

            <TabsContent value="resources" className="mt-4 space-y-4">
              <PanelGroup
                eyebrow="资源与成本"
                title="先看预算，再看账单"
                description="把上下文预算和花费放在同一个层级里，减少来回切换。"
              >
                <HemolymphPanel />
                <CostPanel />
              </PanelGroup>
            </TabsContent>

            <TabsContent value="system" className="mt-4 space-y-4">
              <PanelGroup
                eyebrow="系统"
                title="把后台状态和自进化收口"
                description="诊断不再单独占一个孤岛标签，而是和自进化一起作为系统视图。"
              >
                <ToolEffectsPanel />
                <RegenerationPanel />
                <DiagnosticsContent />
              </PanelGroup>
            </TabsContent>
          </Tabs>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 1 · SWARM SESSION
// Groups sub-agent tool events under their parent call_agent_parallel
// tool_use row · uses /api/progress to find running delegations and
// /api/stream (SSE) to observe live sub-agent tool_starts. Because
// this page isn't bound to a thread, we watch the GLOBAL event
// stream and surface whichever parent tool_use blocks are active.
// ═══════════════════════════════════════════════════════════

interface SubToolRecord {
  id: string;
  name: string;
  sub_agent_role?: string;
  parent_tool_use_id?: string;
  input_preview?: Record<string, unknown>;
  status: "running" | "success" | "error";
  started_at: number;
  finished_at?: number;
}

function SwarmPanel() {
  const { t } = useI18n();
  const [events, setEvents] = useState<SubToolRecord[]>([]);
  const [connected, setConnected] = useState(false);

  // Consume the global journal SSE feed. Now that
  // ``ephemeral_runner._emit_sub_tool_event`` mirrors to the journal,
  // the parent ``sub_tool_start`` / ``sub_tool_end`` frames flow on
  // ``/api/stream`` as first-class events. We index by tool_call_id
  // so a start/end pair updates a single row in place.
  useEffect(() => {
    const base = getBackendBaseURL();
    const es = authedEventSource(`${base}/api/stream`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (msg) => {
      try {
        const p = JSON.parse(msg.data) as {
          event_type?: string;
          ts?: string;
          task_id?: string;
          tool_call_id?: string;
          tool_name?: string;
          role_id?: string;
          parent_tool_use_id?: string | null;
          is_error?: boolean;
          duration_ms?: number;
          args_preview?: string;
          step?: { sucker_id?: string; node_id?: string };
        };

        // sub_tool_start / sub_tool_end · the new direct-from-journal
        // path (preferred — carries role_id, tool_name, error status).
        if (
          p.event_type === "sub_tool_start" ||
          p.event_type === "sub_tool_end"
        ) {
          const callId = p.tool_call_id;
          if (!callId) return;
          setEvents((prev) => {
            const idx = prev.findIndex((r) => r.id === callId);
            if (p.event_type === "sub_tool_start") {
              if (idx >= 0) return prev; // dedupe
              const startRec: SubToolRecord = {
                id: callId,
                name: p.tool_name ?? "?",
                sub_agent_role: p.role_id,
                parent_tool_use_id:
                  p.parent_tool_use_id ?? p.task_id ?? undefined,
                status: "running",
                started_at: Date.now(),
              };
              return [...prev, startRec].slice(-40);
            }
            // sub_tool_end · update existing record (or append closed)
            const endStatus: "error" | "success" = p.is_error
              ? "error"
              : "success";
            if (idx < 0) {
              const closedRec: SubToolRecord = {
                id: callId,
                name: p.tool_name ?? "?",
                sub_agent_role: p.role_id,
                parent_tool_use_id:
                  p.parent_tool_use_id ?? p.task_id ?? undefined,
                status: endStatus,
                started_at: Date.now(),
                finished_at: Date.now(),
              };
              return [...prev, closedRec].slice(-40);
            }
            const existing = prev[idx];
            if (!existing) return prev;
            const updated = [...prev];
            const merged: SubToolRecord = {
              ...existing,
              status: endStatus,
              finished_at: Date.now(),
            };
            updated[idx] = merged;
            return updated;
          });
          return;
        }

        // Legacy `step` fallback for plain skill calls (kept so the
        // panel still shows non-subagent activity).
        if (p.event_type !== "step") return;
        const sid = p.step?.sucker_id;
        if (!sid) return;
        setEvents((prev) => {
          const next: SubToolRecord[] = [
            ...prev,
            {
              id: `${p.task_id ?? "?"}-${p.step?.node_id ?? "?"}-${prev.length}`,
              name: sid,
              parent_tool_use_id: p.task_id,
              status: "success",
              started_at: Date.now(),
              finished_at: Date.now(),
            },
          ];
          return next.slice(-40);
        });
      } catch (e) {
        swallow(e);
      }
    };
    return () => es.close();
  }, []);

  // Group by parent_tool_use_id (== task_id here) so each active
  // task renders as a row with its sub-events nested underneath.
  const grouped = useMemo(() => {
    const map = new Map<string, SubToolRecord[]>();
    for (const e of events) {
      const k = e.parent_tool_use_id ?? "(unbound)";
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(e);
    }
    return Array.from(map.entries()).slice(-8);
  }, [events]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">
            {t.observabilityPage.swarmCardTitle}
          </CardTitle>
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "size-2 rounded-full",
                connected ? "bg-emerald-500 animate-pulse" : "bg-muted",
              )}
            />
            <span className="text-xs text-muted-foreground uppercase tracking-wide">
              {connected
                ? t.observabilityPage.connected
                : t.observabilityPage.idle}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {grouped.length === 0 && (
          <Empty className="border-0 bg-transparent shadow-none">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <NetworkIcon />
              </EmptyMedia>
              <EmptyTitle>{t.observabilityPage.noConcurrentTasks}</EmptyTitle>
              <EmptyDescription>
                {t.observabilityPage.noConcurrentTasksHint}
                <br />
                <span className="text-xs">
                  {t.observabilityPage.nestedSseNote}
                </span>
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {grouped.map(([taskId, sub]) => (
          <div
            key={taskId}
            className="rounded-lg border border-border-default bg-muted/20 p-3"
          >
            <div className="mb-2 flex items-center justify-between">
              <div className="text-xs font-mono text-muted-foreground">
                {t.observabilityPage.taskPrefix}:{taskId.slice(0, 16)}
              </div>
              <Badge variant="outline" className="text-xs">
                {t.observabilityPage.stepsCount(sub.length)}
              </Badge>
            </div>
            <div className="space-y-1">
              {sub.slice(-6).map((s) => (
                <div
                  key={s.id}
                  className="flex items-center gap-2 rounded-md bg-background/50 px-2 py-1 text-xs"
                >
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      s.status === "running"
                        ? "bg-amber-500 animate-pulse"
                        : s.status === "error"
                          ? "bg-destructive"
                          : "bg-emerald-500",
                    )}
                  />
                  {s.sub_agent_role && (
                    <Badge variant="outline" className="text-xs font-mono">
                      {s.sub_agent_role}
                    </Badge>
                  )}
                  <span className="font-mono">{s.name}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 2 · BLACKBOARD VIEWER
// ═══════════════════════════════════════════════════════════

interface BlackboardListResp {
  turns: Array<{ turn_id: string; key_count: number; age_seconds: number }>;
}

interface BlackboardSnapResp {
  turn_id: string;
  key_count: number;
  entries: Record<string, unknown>;
}

function BlackboardPanel() {
  const { t } = useI18n();
  const base = getBackendBaseURL();
  const list = useHeartbeat<BlackboardListResp>(
    `${base}/api/blackboard`,
    3000,
    { turns: [] },
  );
  const [selected, setSelected] = useState<string | null>(null);

  // Auto-pick the most recently active turn if none selected.
  useEffect(() => {
    const first = list.data.turns[0];
    if (!selected && first) {
      setSelected(first.turn_id);
    }
  }, [list.data.turns, selected]);

  const snap = useHeartbeat<BlackboardSnapResp | null>(
    selected ? `${base}/api/blackboard?turn_id=${selected}` : "",
    2000,
    null,
  );

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-[260px_1fr]">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">
            {t.observabilityPage.activeTurns}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {list.data.turns.length === 0 && (
            <div className="text-xs text-muted-foreground">
              {t.observabilityPage.noActiveBlackboard}
            </div>
          )}
          {list.data.turns.map((tr) => (
            <Button
              key={tr.turn_id}
              variant="ghost"
              onClick={() => setSelected(tr.turn_id)}
              aria-pressed={selected === tr.turn_id}
              aria-label={`黑板回合 ${tr.turn_id.slice(0, 18)}`}
              className={cn(
                "h-auto w-full justify-start rounded-md border px-2 py-1.5 text-left text-xs transition-colors hover:text-foreground",
                selected === tr.turn_id
                  ? "border-primary/40 bg-primary/10 hover:bg-primary/10"
                  : "border-transparent bg-muted/30 hover:bg-muted/60",
              )}
            >
              <div className="w-full">
                <div className="font-mono text-xs truncate">
                  {tr.turn_id.slice(0, 18)}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span>
                    {tr.key_count} {t.observabilityPage.keyCount}
                  </span>
                  <span>·</span>
                  <span>{formatAge(tr.age_seconds)}</span>
                </div>
              </div>
            </Button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">
              {t.observabilityPage.snapshot}
              {selected && (
                <span className="ml-2 font-mono text-xs text-muted-foreground">
                  {selected.slice(0, 16)}
                </span>
              )}
            </CardTitle>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                list.refresh();
                snap.refresh();
              }}
            >
              <RefreshCwIcon className="size-3" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {!selected && (
            <Empty className="border-0 bg-transparent shadow-none">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <DatabaseIcon />
                </EmptyMedia>
                <EmptyTitle>{t.observabilityPage.selectTurnHint}</EmptyTitle>
                <EmptyDescription>
                  {t.observabilityPage.selectTurnHintDesc}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {selected &&
            snap.data &&
            Object.keys(snap.data.entries).length === 0 && (
              <div className="py-6 text-center text-xs text-muted-foreground">
                {t.observabilityPage.emptyBlackboard}
              </div>
            )}
          {selected && snap.data && (
            <div className="space-y-2">
              {Object.entries(snap.data.entries).map(([k, v]) => (
                <div key={k} className="rounded-md bg-muted/30 p-2 text-xs">
                  <div className="mb-1 font-mono font-semibold text-primary">
                    {k}
                  </div>
                  <pre className="whitespace-pre-wrap break-words text-xs text-muted-foreground">
                    {formatValue(v)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 3 · JOURNAL STREAM
// ═══════════════════════════════════════════════════════════

interface JournalEvent {
  event_type: string;
  ts: string;
  task_id?: string;
  arm_id?: string;
  path?: string;
  action?: string;
  // SubTool fields
  role_id?: string;
  tool_call_id?: string;
  tool_name?: string;
  iteration?: number;
  args_preview?: string;
  output_preview?: string;
  is_error?: boolean;
  duration_ms?: number;
  parent_tool_use_id?: string | null;
  // BrowserArtifact fields
  kind?: string;
  url?: string;
  filename?: string;
  caption?: string;
  mime_type?: string;
  width?: number | null;
  height?: number | null;
  thread_id?: string;
  [key: string]: unknown;
}

function JournalPanel() {
  const { t } = useI18n();
  const { confirm, confirmDialog } = useConfirmDialog();
  const [events, setEvents] = useState<JournalEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  const handleClear = useCallback(async () => {
    if (events.length === 0) return;
    if (
      !(await confirm({
        title: t.observabilityPage.clearConfirmTitle,
        description: t.observabilityPage.clearConfirmDescription,
        confirmLabel: t.observabilityPage.clear,
      }))
    )
      return;
    setEvents([]);
  }, [confirm, events.length, t.observabilityPage.clearConfirmTitle, t.observabilityPage.clearConfirmDescription, t.observabilityPage.clear]);

  useEffect(() => {
    const base = getBackendBaseURL();
    const es = authedEventSource(`${base}/api/stream`);
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (msg) => {
      if (pausedRef.current) return;
      try {
        const p = JSON.parse(msg.data) as JournalEvent;
        setEvents((prev) => {
          const next = [...prev, p];
          return next.slice(-200);
        });
      } catch (e) {
        swallow(e);
      }
    };
    return () => es.close();
  }, []);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of events) c[e.event_type] = (c[e.event_type] ?? 0) + 1;
    return c;
  }, [events]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold">
            {t.observabilityPage.journalEventStream}
          </CardTitle>
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "size-2 rounded-full",
                connected ? "bg-emerald-500 animate-pulse" : "bg-muted",
              )}
            />
            <Button
              size="sm"
              variant="ghost"
              aria-pressed={paused}
              onClick={() => setPaused((p) => !p)}
            >
              {paused ? t.observabilityPage.resume : t.observabilityPage.pause}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={handleClear}
              disabled={events.length === 0}
            >
              {t.observabilityPage.clear}
            </Button>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {Object.entries(counts).map(([kind, n]) => (
            <Badge
              key={kind}
              variant="outline"
              className="text-xs font-mono"
            >
              {kind} · {n}
            </Badge>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        {events.length === 0 && (
          <Empty className="border-0 bg-transparent shadow-none">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <ActivityIcon />
              </EmptyMedia>
              <EmptyTitle>{t.observabilityPage.noEvents}</EmptyTitle>
              <EmptyDescription>
                {t.observabilityPage.noEventsHint}
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        <div className="max-h-[60vh] overflow-auto font-mono text-xs">
          {events
            .slice()
            .reverse()
            .map((e, i) => (
              <div
                key={i}
                className={cn(
                  "border-b border-border-subtle px-2 py-1.5",
                  eventRowColor(e.event_type),
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground shrink-0">
                    {shortTs(e.ts)}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {e.event_type}
                  </Badge>
                  {e.task_id && (
                    <span className="text-xs text-muted-foreground truncate">
                      {t.observabilityPage.taskPrefix}:{e.task_id.slice(0, 12)}
                    </span>
                  )}
                  {e.path && (
                    <span className="text-xs text-primary truncate">
                      {e.action ?? t.observabilityPage.eventActionFile}:{" "}
                      {e.path}
                    </span>
                  )}
                  {/* SubTool events — role + tool + status */}
                  {(e.event_type === "sub_tool_start" ||
                    e.event_type === "sub_tool_end") && (
                    <span className="text-xs truncate flex items-center gap-1.5">
                      {e.role_id && (
                        <Badge
                          variant="outline"
                          className="text-xs font-mono"
                        >
                          {e.role_id}
                        </Badge>
                      )}
                      <span className="text-primary font-mono">
                        {e.tool_name ?? "?"}
                      </span>
                      {e.event_type === "sub_tool_end" && (
                        <span
                          className={cn(
                            "text-xs",
                            e.is_error ? "text-destructive" : "text-emerald-500",
                          )}
                        >
                          {e.is_error
                            ? t.observabilityPage.eventFailure
                            : t.observabilityPage.eventSuccess}
                          {e.duration_ms !== undefined &&
                            t.observabilityPage.eventDurationSuffix(
                              e.duration_ms,
                            )}
                        </span>
                      )}
                    </span>
                  )}
                  {/* BrowserArtifact — inline thumbnail + caption */}
                  {e.event_type === "browser_artifact" && e.url && (
                    <span className="text-xs truncate flex items-center gap-1.5">
                      <Badge variant="outline" className="text-xs">
                        {e.kind ?? t.observabilityPage.eventArtifactScreenshot}
                      </Badge>
                      <a
                        href={`${getBackendBaseURL()}${e.url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary underline-offset-2 hover:underline truncate max-w-[12rem] sm:max-w-[18rem]"
                        title={e.caption || e.filename}
                      >
                        {e.filename ?? t.observabilityPage.eventArtifact}
                      </a>
                      {e.width && e.height && (
                        <span className="text-muted-foreground">
                          {e.width}×{e.height}
                        </span>
                      )}
                    </span>
                  )}
                </div>
                {/* Inline thumbnail for screenshots */}
                {e.event_type === "browser_artifact" &&
                  e.url &&
                  e.mime_type?.startsWith("image/") && (
                    <div className="mt-1.5 pl-4">
                      <a
                        href={`${getBackendBaseURL()}${e.url}`}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <img
                          src={`${getBackendBaseURL()}${e.url}`}
                          alt={
                            e.caption ||
                            e.filename ||
                            t.observabilityPage.eventArtifactScreenshot
                          }
                          className="max-h-32 max-w-[12rem] sm:max-w-[20rem] rounded-md border border-border-subtle object-contain"
                          loading="lazy"
                        />
                      </a>
                      {e.caption && (
                        <div className="mt-1 text-xs text-muted-foreground italic truncate max-w-[12rem] sm:max-w-[20rem]">
                          {e.caption}
                        </div>
                      )}
                    </div>
                  )}
                {/* Args / output preview for SubTool events */}
                {e.event_type === "sub_tool_start" && e.args_preview && (
                  <div className="mt-1 pl-4 text-xs text-muted-foreground truncate">
                    → {e.args_preview}
                  </div>
                )}
                {e.event_type === "sub_tool_end" && e.output_preview && (
                  <div className="mt-1 pl-4 text-xs text-muted-foreground truncate">
                    ← {e.output_preview}
                  </div>
                )}
              </div>
            ))}
        </div>
      </CardContent>
      {confirmDialog}
    </Card>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 4 · FENCED TOOL EFFECTS
// ═══════════════════════════════════════════════════════════

const EMPTY_TOOL_EFFECTS: ToolEffectsSnapshot = {
  backend: "disabled",
  shared_across_hosts: false,
  can_authorize_retry: false,
  count: 0,
  state_counts: {},
  receipts: [],
};

export function ToolEffectsPanel() {
  const base = getBackendBaseURL();
  const { data, loading, error, refresh } = useHeartbeat<ToolEffectsSnapshot>(
    `${base}/api/tool-effects?limit=100`,
    3000,
    EMPTY_TOOL_EFFECTS,
  );
  const [selected, setSelected] = useState<ToolEffectReceipt | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const indeterminate = data.state_counts.indeterminate ?? 0;
  const visibleReceipts = useMemo(
    () =>
      data.receipts.filter(
        (receipt, index) => receipt.state !== "committed" || index < 6,
      ),
    [data.receipts],
  );
  const hasCollapsedReceipts = visibleReceipts.length < data.receipts.length;

  const authorize = useCallback(async () => {
    if (!selected || reason.trim().length < 8) return;
    setSubmitting(true);
    try {
      await authorizeToolEffectRetry(selected, reason.trim());
      toast.success("已允许一次受 fencing token 保护的重试");
      setSelected(null);
      setReason("");
      refresh();
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : "放行失败");
    } finally {
      setSubmitting(false);
    }
  }, [reason, refresh, selected]);

  return (
    <>
      <Card className="border-border-default/80 shadow-none">
        <CardHeader className="flex-row items-start justify-between gap-4 space-y-0 pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <ShieldAlertIcon className="size-4 text-amber-500" />
              外部动作回执
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              识别重复执行、节点接管和必须人工核对的外部副作用。
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={indeterminate > 0 ? "destructive" : "secondary"}>
              {indeterminate > 0 ? `${indeterminate} 项待核对` : "无待核对项"}
            </Badge>
            <Button
              size="icon"
              variant="ghost"
              className="size-8"
              onClick={refresh}
              aria-label="刷新外部动作回执"
            >
              <RefreshCwIcon
                className={cn("size-3.5", loading && "animate-spin")}
              />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span className="rounded-full bg-muted px-2.5 py-1">
              后端 · {data.backend}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-1">
              {data.shared_across_hosts ? "跨节点共享" : "本机协调"}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-1">
              已提交 · {data.state_counts.committed ?? 0}
            </span>
            <span className="rounded-full bg-muted px-2.5 py-1">
              执行中 ·{" "}
              {(data.state_counts.claimed ?? 0) +
                (data.state_counts.started ?? 0)}
            </span>
          </div>

          {error ? (
            <div className="rounded-lg bg-destructive/8 px-3 py-3 text-xs text-destructive">
              回执状态读取失败：{error}
            </div>
          ) : data.receipts.length === 0 ? (
            <div className="rounded-lg bg-muted/30 px-3 py-5 text-center text-xs text-muted-foreground">
              暂无外部动作回执；工具执行后会自动出现在这里。
            </div>
          ) : (
            <div className="divide-y divide-border-default/70 rounded-lg border border-border-default/70">
              {visibleReceipts.map((receipt) => (
                <div
                  key={receipt.effect_key}
                  className="flex flex-col gap-2 px-3 py-3 sm:flex-row sm:items-center"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-xs font-medium">
                        {receipt.sucker_id || "未知工具"}
                      </span>
                      <EffectStateBadge state={receipt.state} />
                    </div>
                    <div className="mt-1 truncate text-xs text-muted-foreground">
                      任务 {receipt.task_id.slice(0, 12) || "—"} · 步骤{" "}
                      {receipt.step_id} · token {receipt.fencing_token}
                    </div>
                    {receipt.reason && (
                      <p className="mt-1 line-clamp-2 text-xs text-amber-700 dark:text-amber-300">
                        {receipt.reason}
                      </p>
                    )}
                  </div>
                  {receipt.state === "indeterminate" &&
                    data.can_authorize_retry && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 shrink-0 rounded-full text-xs"
                        onClick={() => {
                          setSelected(receipt);
                          setReason("");
                        }}
                      >
                        <RotateCcwIcon className="mr-1.5 size-3" />
                        核对后重试
                      </Button>
                    )}
                </div>
              ))}
              {hasCollapsedReceipts && (
                <div className="px-3 py-2 text-center text-xs text-muted-foreground">
                  已收起历史提交记录，仅保留需关注项与最近 6 条
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open && !submitting) setSelected(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认外部动作没有发生</DialogTitle>
            <DialogDescription>
              只有在外部系统、文件或远程服务中确认该动作没有成功后才能放行。系统会核对
              fencing token，页面过期时不会误操作新回执。
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
            {selected?.sucker_id} · token {selected?.fencing_token}
          </div>
          <Textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="填写核对依据，例如：支付平台确认没有生成订单。"
            className="min-h-24"
          />
          <DialogFooter>
            <Button
              variant="ghost"
              onClick={() => setSelected(null)}
              disabled={submitting}
            >
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => void authorize()}
              disabled={submitting || reason.trim().length < 8}
            >
              {submitting ? "正在核对状态…" : "确认未发生并允许重试"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function EffectStateBadge({ state }: { state: ToolEffectReceipt["state"] }) {
  const labels: Record<ToolEffectReceipt["state"], string> = {
    claimed: "已占用",
    started: "执行中",
    committed: "已提交",
    indeterminate: "需核对",
    retry_authorized: "已放行一次",
  };
  return (
    <Badge
      variant={state === "indeterminate" ? "destructive" : "secondary"}
      className="h-5 px-1.5 text-xs"
    >
      {labels[state]}
    </Badge>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 4 · REGENERATION SUMMARY
// ═══════════════════════════════════════════════════════════

interface RegenSummary {
  skill_forge: { status: string; forged_count: number };
  rule_extractor: {
    status: string;
    rules_count: number;
    failure_trajectories: number;
  };
  memory_consolidator: {
    status: string;
    memories_count: number;
    trajectories_scanned: number;
  };
  kg_updater: { status: string; triple_count: number };
  workflow_rewriter: { status: string; trajectories_scanned: number };
  recipe_evaluator: { status: string; recipes_tracked: number };
  trajectories: {
    total: number;
    failures: number;
    by_strategy: Record<string, number>;
  };
}

function RegenerationPanel() {
  const { t } = useI18n();
  const base = getBackendBaseURL();
  const { data, loading, error, refresh } = useHeartbeat<RegenSummary | null>(
    `${base}/api/regeneration/summary`,
    5000,
    null,
  );

  if (loading && !data) {
    return <LoadingState title={t.observabilityPage.loading} />;
  }
  if (error) {
    return (
      <ErrorState
        title={t.observabilityPage.errorPrefix}
        detail={error}
      />
    );
  }
  if (!data) return null;

  const producers = [
    {
      key: "skill_forge",
      label: t.observabilityPage.regenProducers.skillForge,
      metric: t.observabilityPage.runReviewMetricForged(
        data.skill_forge.forged_count,
      ),
      status: data.skill_forge.status,
      hint: t.observabilityPage.regenProducers.skillForgeHint,
    },
    {
      key: "rule_extractor",
      label: t.observabilityPage.regenProducers.ruleExtractor,
      metric: t.observabilityPage.runReviewMetricRules(
        data.rule_extractor.rules_count,
      ),
      status: data.rule_extractor.status,
      hint: t.observabilityPage.regenProducers.ruleExtractorHint(
        data.rule_extractor.failure_trajectories,
      ),
    },
    {
      key: "memory_consolidator",
      label: t.observabilityPage.regenProducers.memoryConsolidator,
      metric: t.observabilityPage.runReviewMetricMems(
        data.memory_consolidator.memories_count,
      ),
      status: data.memory_consolidator.status,
      hint: t.observabilityPage.regenProducers.memoryConsolidatorHint(
        data.memory_consolidator.trajectories_scanned,
      ),
    },
    {
      key: "kg_updater",
      label: t.observabilityPage.regenProducers.kgUpdater,
      metric: t.observabilityPage.runReviewMetricTriples(
        data.kg_updater.triple_count,
      ),
      status: data.kg_updater.status,
      hint: t.observabilityPage.regenProducers.kgUpdaterHint,
    },
    {
      key: "workflow_rewriter",
      label: t.observabilityPage.regenProducers.workflowRewriter,
      metric: t.observabilityPage.runReviewMetricTraj(
        data.workflow_rewriter.trajectories_scanned,
      ),
      status: data.workflow_rewriter.status,
      hint: t.observabilityPage.regenProducers.workflowRewriterHint,
    },
    {
      key: "recipe_evaluator",
      label: t.observabilityPage.regenProducers.recipeEvaluator,
      metric: t.observabilityPage.runReviewMetricRecipes(
        data.recipe_evaluator.recipes_tracked,
      ),
      status: data.recipe_evaluator.status,
      hint: t.observabilityPage.regenProducers.recipeEvaluatorHint,
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-xs">
          {t.observabilityPage.trajectoryTotal} · {data.trajectories.total}
        </Badge>
        <Badge variant="outline" className="text-xs">
          {t.observabilityPage.failureCount} · {data.trajectories.failures}
        </Badge>
        {Object.entries(data.trajectories.by_strategy).map(([k, n]) => (
          <Badge key={k} variant="outline" className="text-xs font-mono">
            {k}:{n}
          </Badge>
        ))}
        <Button size="sm" variant="ghost" className="ml-auto" onClick={refresh}>
          <RefreshCwIcon className="size-3" />
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
        {producers.map((p) => (
          <Card key={p.key}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-xs font-semibold">
                  {p.label}
                </CardTitle>
                <StatusDot status={p.status} />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-lg font-bold">{p.metric}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {p.hint}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 5 · HEMOLYMPH 4-BUCKET METER
// ═══════════════════════════════════════════════════════════

interface HemolymphResp {
  count: number;
  max_tracked: number;
  snapshots: Array<{
    ts: number;
    budget_tokens: number;
    tokens_used: number;
    utilization: number;
    segment_count: number;
    by_bucket: Record<string, { used: number; alloc: number }>;
    recipe_id: string | null;
    task_type: string | null;
  }>;
}

function HemolymphPanel() {
  const { t } = useI18n();
  const base = getBackendBaseURL();
  const { data } = useHeartbeat<HemolymphResp>(
    `${base}/api/hemolymph/recent?limit=20`,
    3000,
    { count: 0, max_tracked: 50, snapshots: [] },
  );

  const latest = data.snapshots[data.snapshots.length - 1];
  const buckets = ["system", "suckers", "memory", "history"] as const;
  const bucketColors: Record<string, string> = {
    system: "bg-sky-500",
    suckers: "bg-emerald-500",
    memory: "bg-amber-500",
    history: "bg-violet-500",
  };
  const bucketLabels: Record<string, string> = {
    system: t.observabilityPage.hemolymphBuckets.system,
    suckers: t.observabilityPage.hemolymphBuckets.suckers,
    memory: t.observabilityPage.hemolymphBuckets.memory,
    history: t.observabilityPage.hemolymphBuckets.history,
  };

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">
            {t.observabilityPage.latestCompose}
            {latest && (
              <span className="ml-2 text-xs text-muted-foreground">
                · {t.observabilityPage.utilizationLabel}{" "}
                {(latest.utilization * 100).toFixed(1)}%
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {!latest && (
            <Empty className="border-0 bg-transparent shadow-none">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <GaugeIcon />
                </EmptyMedia>
                <EmptyTitle>{t.observabilityPage.noComposeRecords}</EmptyTitle>
                <EmptyDescription>
                  {t.observabilityPage.noComposeRecordsHint}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {latest && (
            <div className="space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">
                  {t.observabilityPage.total}
                </span>
                <span className="font-mono">
                  {latest.tokens_used} / {latest.budget_tokens}{" "}
                  {t.observabilityPage.snapshotTokensUnit}
                </span>
              </div>
              <Progress value={latest.utilization * 100} />
              <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                {buckets.map((b) => {
                  const info = latest.by_bucket[b] ?? { used: 0, alloc: 1 };
                  const pct =
                    info.alloc > 0 ? (info.used / info.alloc) * 100 : 0;
                  return (
                    <div key={b} className="rounded-md bg-muted/30 p-2">
                      <div className="flex items-center gap-1.5 text-xs uppercase tracking-wide">
                        <span
                          className={cn(
                            "size-1.5 rounded-full",
                            bucketColors[b],
                          )}
                        />
                        {bucketLabels[b]}
                      </div>
                      <div className="mt-1 text-sm font-mono">
                        {info.used}
                        <span className="text-muted-foreground">
                          /{info.alloc}
                        </span>
                      </div>
                      <div className="mt-1 h-1 overflow-hidden rounded-full bg-background">
                        <div
                          className={cn(
                            "h-full transition-all",
                            bucketColors[b],
                          )}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold">
            {t.observabilityPage.historyPrefix} {data.snapshots.length}{" "}
            {t.observabilityPage.tabJournal}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-[50vh] overflow-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border text-left text-muted-foreground">
                  <th className="py-1">
                    {t.observabilityPage.hemolymphTable.ts}
                  </th>
                  <th className="py-1">
                    {t.observabilityPage.hemolymphTable.usedBudget}
                  </th>
                  <th className="py-1">
                    {t.observabilityPage.hemolymphTable.util}
                  </th>
                  <th className="py-1">
                    {t.observabilityPage.hemolymphTable.recipe}
                  </th>
                </tr>
              </thead>
              <tbody className="font-mono">
                {data.snapshots
                  .slice()
                  .reverse()
                  .map((s, i) => (
                    <tr key={i} className="border-b border-border-subtle">
                      <td className="py-1 text-muted-foreground">
                        {new Date(s.ts * 1000).toLocaleTimeString()}
                      </td>
                      <td className="py-1">
                        {s.tokens_used} / {s.budget_tokens}
                      </td>
                      <td className="py-1">
                        {(s.utilization * 100).toFixed(1)}%
                      </td>
                      <td className="py-1 text-muted-foreground">
                        {s.recipe_id ?? "—"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// PANEL 6 · COST SUMMARY
// ═══════════════════════════════════════════════════════════

interface CostSummary {
  total_tokens: number;
  total_usd: number;
  commit_count: number;
  task_count: number;
  tasks: Array<{
    task_id: string;
    tokens: number;
    usd: number;
    commit_count: number;
    last_ts: string | null;
  }>;
}

function CostPanel() {
  const { t } = useI18n();
  const base = getBackendBaseURL();
  const { data, refresh } = useHeartbeat<CostSummary>(
    `${base}/api/budget/summary?limit=30`,
    3000,
    {
      total_tokens: 0,
      total_usd: 0,
      commit_count: 0,
      task_count: 0,
      tasks: [],
    },
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        <StatTile
          label={t.observabilityPage.cumulativeTokens}
          value={data.total_tokens.toLocaleString()}
        />
        <StatTile
          label={t.observabilityPage.cumulativeUsd}
          value={`$${data.total_usd.toFixed(4)}`}
        />
        <StatTile
          label={t.observabilityPage.commitCount}
          value={data.commit_count.toLocaleString()}
        />
        <StatTile
          label={t.observabilityPage.taskCount}
          value={data.task_count.toLocaleString()}
        />
      </div>
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-semibold">
              {t.observabilityPage.taskGroupingPrefix} {data.tasks.length}
            </CardTitle>
            <Button size="sm" variant="ghost" onClick={refresh}>
              <RefreshCwIcon className="size-3" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {data.tasks.length === 0 && (
            <Empty className="border-0 bg-transparent shadow-none">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <CoinsIcon />
                </EmptyMedia>
                <EmptyTitle>{t.observabilityPage.noBudgetCommits}</EmptyTitle>
                <EmptyDescription>
                  {t.observabilityPage.noBudgetCommitsHint}
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          )}
          {data.tasks.length > 0 && (
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="py-1">
                      {t.observabilityPage.costTable.task}
                    </th>
                    <th className="py-1">
                      {t.observabilityPage.costTable.tokens}
                    </th>
                    <th className="py-1">
                      {t.observabilityPage.costTable.usd}
                    </th>
                    <th className="py-1">
                      {t.observabilityPage.costTable.commits}
                    </th>
                    <th className="py-1">
                      {t.observabilityPage.costTable.last}
                    </th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {data.tasks.map((tk) => (
                    <tr
                      key={tk.task_id}
                      className="border-b border-border-subtle"
                    >
                      <td
                        className="py-1 max-w-[12rem] truncate"
                        title={tk.task_id}
                      >
                        {tk.task_id.slice(0, 18)}
                      </td>
                      <td className="py-1">{tk.tokens.toLocaleString()}</td>
                      <td className="py-1">${tk.usd.toFixed(5)}</td>
                      <td className="py-1">{tk.commit_count}</td>
                      <td className="py-1 text-muted-foreground">
                        {tk.last_ts ? shortTs(tk.last_ts) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// Shared UI helpers
// ═══════════════════════════════════════════════════════════

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border-default bg-muted/20 p-3">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-xl font-bold font-mono">{value}</div>
    </div>
  );
}

function StatusDot({ status }: { status: string }) {
  const { t } = useI18n();
  const cls =
    status === "ready"
      ? "bg-emerald-500"
      : status === "warming"
        ? "bg-amber-500"
        : "bg-muted";
  const label =
    status === "ready"
      ? t.observabilityPage.statusReady
      : status === "warming"
        ? t.observabilityPage.statusWarming
        : t.observabilityPage.statusIdle;
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn("size-1.5 rounded-full", cls)} />
      <span className="text-xs text-muted-foreground uppercase">
        {label}
      </span>
    </div>
  );
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return String(v);
  if (typeof v === "string") return v;
  try {
    return JSON.stringify(v, null, 2);
  } catch (e) {
    swallow(e);
    return String(v);
  }
}

function shortTs(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleTimeString();
  } catch (e) {
    swallow(e);
    return ts;
  }
}

function eventRowColor(kind: string): string {
  if (kind === "immune" || kind === "immune_reject") return "bg-destructive/5";
  if (kind.startsWith("budget")) return "bg-amber-500/5";
  if (kind === "file_op") return "bg-primary/5";
  if (kind === "browser_artifact") return "bg-violet-500/5";
  if (kind === "sub_tool_start" || kind === "sub_tool_end")
    return "bg-cyan-500/5";
  return "";
}

type ObservabilityTab = "overview" | "events" | "resources" | "system";

function normalizeObservabilityTab(tab: string): ObservabilityTab {
  switch (tab) {
    case "overview":
      return "overview";
    case "events":
    case "runs":
    case "swarm":
    case "blackboard":
    case "journal":
      return "events";
    case "resources":
    case "hemolymph":
    case "cost":
      return "resources";
    case "system":
    case "regeneration":
    case "diagnostics":
      return "system";
    default:
      return "overview";
  }
}

function PanelGroup({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="workspace-panel px-5 py-4">
      <div className="mb-4 space-y-1.5">
        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          {eyebrow}
        </div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function ObservabilitySignalCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-border-default bg-background/70 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
