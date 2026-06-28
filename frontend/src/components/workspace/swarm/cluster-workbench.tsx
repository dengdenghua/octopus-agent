import { useMemo } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertCircleIcon,
  BookOpenIcon,
  BrainIcon,
  CheckCircle2Icon,
  CoinsIcon,
  FilePenIcon,
  Loader2Icon,
  MonitorIcon,
  SearchIcon,
  StarIcon,
  WrenchIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import { WorkstationSeat } from "../workstation-seat";
import {
  STATUS_LABELS,
  type AgentStatus,
  type SwarmAgent,
  type SwarmSession,
  type TraceEntry,
} from "./types";

/**
 * ClusterWorkbench — a Kimi-"Agent 集群"-style two-pane workbench for octopus's
 * multi-agent swarm, built entirely on octopus's existing data model
 * (``SwarmSession`` / ``SwarmAgent`` / ``TraceEntry``) and atoms
 * (``WorkstationSeat``).
 *
 * Left pane  = the cluster overview: a segmented phase-progress bar + one
 *              humanized card per parallel agent (avatar · name · role · task ·
 *              live progress · status).
 * Right pane = "octopus's Computer": an agent tab strip + the selected agent's
 *              live work timeline (typed step icons + URLs) + its result.
 *
 * Deliberately presentation-only (driven by props), so it unit-tests against
 * mock sessions and later drops onto the realtime swarm-context unchanged.
 *
 * Improvements over Kimi's version (the "better than his" bits):
 *  - a real *segmented* progress bar (Kimi only shows an "N/M" counter);
 *  - denser agent cards (token usage / rating / equipped skills);
 *  - per-agent hue theming straight from ``SwarmAgent.hue``;
 *  - proper a11y: the agent strip is a real ``tablist`` with arrow-key/Enter
 *    selection and ``aria-selected`` state.
 */

const STATUS_DOT: Record<AgentStatus, string> = {
  pending: "bg-muted-foreground/40",
  reasoning: "bg-sky-500 animate-pulse",
  iterating: "bg-sky-500 animate-pulse",
  generating: "bg-violet-500 animate-pulse",
  analyzing: "bg-amber-500 animate-pulse",
  summarizing: "bg-amber-500 animate-pulse",
  done: "bg-emerald-500",
  failed: "bg-destructive",
  cancelled: "bg-muted-foreground/40",
  timed_out: "bg-destructive",
};

const TRACE_ICON: Record<TraceEntry["kind"], LucideIcon> = {
  search: SearchIcon,
  read: BookOpenIcon,
  think: BrainIcon,
  write: FilePenIcon,
  tool: WrenchIcon,
};

const RUNNING_STATES: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "reasoning",
  "iterating",
  "generating",
  "analyzing",
  "summarizing",
]);

const TERMINAL_OK: ReadonlySet<AgentStatus> = new Set<AgentStatus>(["done"]);
const TERMINAL_BAD: ReadonlySet<AgentStatus> = new Set<AgentStatus>([
  "failed",
  "timed_out",
  "cancelled",
]);

function isRunning(status: AgentStatus): boolean {
  return RUNNING_STATES.has(status);
}

function statusDotClass(status: AgentStatus): string {
  return STATUS_DOT[status] ?? "bg-muted-foreground/40";
}

function agentSegmentClass(status: AgentStatus): string {
  if (TERMINAL_OK.has(status)) return "bg-emerald-500";
  if (TERMINAL_BAD.has(status)) return "bg-destructive";
  if (isRunning(status)) return "bg-sky-500";
  return "bg-muted-foreground/20";
}

export interface ClusterProgress {
  done: number;
  running: number;
  total: number;
}

export function clusterProgress(agents: SwarmAgent[]): ClusterProgress {
  let done = 0;
  let running = 0;
  for (const a of agents) {
    if (TERMINAL_OK.has(a.status) || TERMINAL_BAD.has(a.status)) done += 1;
    else if (isRunning(a.status)) running += 1;
  }
  return { done, running, total: agents.length };
}

/** Segmented progress bar — one segment per agent, colored by its status. */
function ClusterProgressBar({ agents }: { agents: SwarmAgent[] }) {
  const { done, total } = clusterProgress(agents);
  return (
    <div className="flex items-center gap-2">
      <div
        className="flex h-1.5 flex-1 gap-0.5 overflow-hidden rounded-full"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={`已完成 ${done} / ${total} 个 agent`}
      >
        {agents.map((a) => (
          <span
            key={a.id}
            className={cn("h-full flex-1 rounded-full", agentSegmentClass(a.status))}
          />
        ))}
      </div>
      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
        {done}/{total}
      </span>
    </div>
  );
}

function AgentClusterCard({
  agent,
  selected,
  onSelect,
}: {
  agent: SwarmAgent;
  selected: boolean;
  onSelect: () => void;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, agent.progress)) * 100);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      style={{ borderColor: selected ? `hsl(${agent.hue} 70% 55%)` : undefined }}
      className={cn(
        "group w-full rounded-xl border bg-background/80 p-2.5 text-left transition-colors",
        selected
          ? "ring-1 ring-[hsl(var(--agent-hue,220)_70%_55%)]"
          : "border-border/60 hover:bg-muted/40",
      )}
    >
      <div className="flex items-center gap-2">
        <span
          className="grid size-7 shrink-0 place-items-center rounded-lg text-[15px] leading-none"
          style={{ backgroundColor: `hsl(${agent.hue} 70% 95%)` }}
          aria-hidden="true"
        >
          {agent.avatarEmoji}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-semibold">{agent.name}</span>
            <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
              #{String(agent.index + 1).padStart(2, "0")}
            </span>
          </div>
          <div className="truncate text-[11px] text-muted-foreground">{agent.role}</div>
        </div>
        <span
          className={cn("size-1.5 shrink-0 rounded-full", statusDotClass(agent.status))}
          aria-label={STATUS_LABELS[agent.status]}
          title={STATUS_LABELS[agent.status]}
        />
      </div>

      <div className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-muted-foreground/90">
        {agent.task}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-full rounded-full transition-[width]",
              TERMINAL_BAD.has(agent.status) ? "bg-destructive" : "bg-foreground/70",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
          {STATUS_LABELS[agent.status]}
        </span>
      </div>

      {(agent.tokenUsed != null || agent.stats?.rating != null) && (
        <div className="mt-1.5 flex items-center gap-3 text-[10px] text-muted-foreground/80">
          {agent.tokenUsed != null && (
            <span className="inline-flex items-center gap-1">
              <CoinsIcon className="size-3" />
              {agent.tokenUsed.toLocaleString()}
              {agent.tokenBudget ? `/${agent.tokenBudget.toLocaleString()}` : ""}
            </span>
          )}
          {agent.stats?.rating != null && (
            <span className="inline-flex items-center gap-1">
              <StarIcon className="size-3" />
              {agent.stats.rating.toFixed(1)}
            </span>
          )}
        </div>
      )}
    </button>
  );
}

function AgentTraceTimeline({ trace }: { trace: TraceEntry[] }) {
  if (trace.length === 0) {
    return (
      <div className="px-1 py-6 text-center text-xs text-muted-foreground">
        暂无执行步骤
      </div>
    );
  }
  return (
    <ol className="relative ml-1 space-y-2 border-l border-border/60 pl-3.5">
      {trace.map((entry) => {
        const Icon = TRACE_ICON[entry.kind] ?? WrenchIcon;
        const failed = entry.status === "error" || entry.status === "failed";
        return (
          <li key={entry.id} className="relative">
            <span className="absolute -left-[1.32rem] grid size-4 place-items-center rounded-full bg-background">
              <Icon
                className={cn("size-3", failed ? "text-destructive" : "text-muted-foreground")}
                aria-hidden="true"
              />
            </span>
            <div className="text-[12px] font-medium leading-snug">{entry.title}</div>
            {entry.url && (
              <div className="truncate text-[11px] text-muted-foreground">
                {entry.faviconEmoji ? `${entry.faviconEmoji} ` : ""}
                {entry.url}
              </div>
            )}
            {entry.detail && !entry.url && (
              <div className="line-clamp-2 text-[11px] text-muted-foreground/90">
                {entry.detail}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function AgentDetailPanel({
  agent,
  trace,
}: {
  agent: SwarmAgent;
  trace: TraceEntry[];
}) {
  const StatusIcon = TERMINAL_OK.has(agent.status)
    ? CheckCircle2Icon
    : TERMINAL_BAD.has(agent.status)
      ? AlertCircleIcon
      : Loader2Icon;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-start gap-2.5 border-b border-border/60 px-3 py-2.5">
        <span
          className="grid size-9 shrink-0 place-items-center rounded-xl text-[18px] leading-none"
          style={{ backgroundColor: `hsl(${agent.hue} 70% 95%)` }}
          aria-hidden="true"
        >
          {agent.avatarEmoji}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-semibold">{agent.name}</span>
            <span className="truncate text-xs text-muted-foreground">· {agent.role}</span>
          </div>
          {agent.motto && (
            <div className="truncate text-[11px] italic text-muted-foreground/80">
              “{agent.motto}”
            </div>
          )}
        </div>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 text-[11px]",
            TERMINAL_BAD.has(agent.status) ? "text-destructive" : "text-muted-foreground",
          )}
        >
          <StatusIcon
            className={cn("size-3.5", isRunning(agent.status) && "animate-spin")}
          />
          {STATUS_LABELS[agent.status]}
        </span>
      </div>

      {agent.skills.length > 0 && (
        <div className="flex flex-wrap gap-1 px-3 pt-2">
          {agent.skills.map((s) => (
            <span
              key={s}
              className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              {s}
            </span>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <AgentTraceTimeline trace={trace} />
        {agent.result && (
          <div className="mt-3 rounded-lg border border-border/60 bg-muted/30 p-2.5 text-[12px] leading-relaxed whitespace-pre-wrap">
            {agent.result}
          </div>
        )}
        {agent.error && (
          <div className="mt-3 rounded-lg border border-destructive/40 bg-destructive/10 p-2.5 text-[12px] text-destructive">
            {agent.error}
          </div>
        )}
      </div>
    </div>
  );
}

export interface ClusterWorkbenchProps {
  session: SwarmSession;
  /** Currently focused agent id (uncontrolled-friendly: falls back to first). */
  selectedAgentId?: string;
  onSelectAgent?: (agentId: string) => void;
  className?: string;
}

export function ClusterWorkbench({
  session,
  selectedAgentId,
  onSelectAgent,
  className,
}: ClusterWorkbenchProps) {
  const agents = session.agents;
  const selected =
    agents.find((a) => a.id === selectedAgentId) ?? agents[0] ?? null;
  const selectedTrace = useMemo(
    () =>
      selected
        ? session.trace.filter((t) => t.agentId === selected.id)
        : [],
    [session.trace, selected],
  );

  if (agents.length === 0) {
    return (
      <div
        className={cn(
          "grid min-h-40 place-items-center rounded-xl border border-border/60 text-sm text-muted-foreground",
          className,
        )}
      >
        集群尚未分配 agent
      </div>
    );
  }

  const select = (id: string) => onSelectAgent?.(id);

  return (
    <div
      className={cn(
        "grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]",
        className,
      )}
    >
      {/* ── Left: cluster overview ── */}
      <section
        aria-label="Agent 集群"
        className="flex min-h-0 flex-col gap-2.5 rounded-2xl border border-border/60 bg-background/50 p-3"
      >
        <header className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-semibold">
            Agent 集群 · {agents.length} 个并行
          </span>
        </header>
        <ClusterProgressBar agents={agents} />
        <div className="flex flex-col gap-2 overflow-y-auto">
          {agents.map((a) => (
            <AgentClusterCard
              key={a.id}
              agent={a}
              selected={selected?.id === a.id}
              onSelect={() => select(a.id)}
            />
          ))}
        </div>
      </section>

      {/* ── Right: "octopus's Computer" ── */}
      <section
        aria-label="octopus's Computer"
        className="flex min-h-0 flex-col rounded-2xl border border-border/60 bg-background/50"
      >
        <header className="flex items-center gap-2 border-b border-border/60 px-3 py-2">
          <MonitorIcon className="size-4 text-muted-foreground" aria-hidden="true" />
          <span className="text-[13px] font-semibold">octopus&apos;s Computer</span>
          {session.status !== "done" && (
            <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
              <span className="size-1.5 animate-pulse rounded-full bg-emerald-500" />
              执行任务中…
            </span>
          )}
        </header>

        {/* agent tab strip */}
        <div
          role="tablist"
          aria-label="选择 agent"
          className="flex gap-2 overflow-x-auto border-b border-border/60 px-2.5 py-2"
        >
          {agents.map((a) => (
            <WorkstationSeat
              key={a.id}
              name={a.name}
              avatar={a.avatarEmoji}
              compactName
              selected={selected?.id === a.id}
              dotClassName={statusDotClass(a.status)}
              dotLabel={STATUS_LABELS[a.status]}
              onClick={() => select(a.id)}
              ariaLabel={`${a.name}（${a.role}）`}
            />
          ))}
        </div>

        {selected && <AgentDetailPanel agent={selected} trace={selectedTrace} />}
      </section>
    </div>
  );
}
