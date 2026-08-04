import {
  BotIcon,
  CheckIcon,
  UsersIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo } from "react";

import { emitAgentWorkbenchFocus } from "@/components/workspace/agent-workbench-events";
import type { LiveToolEvent } from "@/components/workspace/live-tool-timeline";
import type { AIMessage, Message, ToolMessage } from "@/core/api/types";
import { isTeammateToolName } from "@/components/workspace/messages/action-display";
import { cn } from "@/lib/utils";

type InlineSubagentStatus = "running" | "done" | "error" | "waiting";

export interface InlineSubagentInfo {
  id: string;
  name: string;
  role?: string;
  avatar?: string;
  status: InlineSubagentStatus;
  task: string;
  summary?: string;
  filesTouchedCount: number;
  iterationCount?: number;
  error?: string;
  index?: number;
  /** Progress 0-1. Undefined means "just spawned, no activity yet".
   *  Done agents always have progress=1 and are rendered as ✓ instead. */
  progress?: number;
}

function firstString(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** Extract progress (0-1) from a LiveToolEvent's input.progress or iteration info.
 *  Priority: input.progress.percent > iteration/iterationCount > null (no info). */
function extractProgressFromEvent(event: LiveToolEvent, totalIterations?: number): number | null {
  // 1. Direct percent from input.progress
  const progressObj = event.input?.progress;
  if (progressObj && typeof progressObj === "object" && !Array.isArray(progressObj)) {
    const p = (progressObj as Record<string, unknown>).percent;
    if (typeof p === "number" && Number.isFinite(p)) {
      // Normalize: 0-1 → as-is, 0-100 → divide by 100
      const normalized = p > 1 ? p / 100 : p;
      return Math.max(0, Math.min(1, normalized));
    }
    const current = (progressObj as Record<string, unknown>).current;
    const total = (progressObj as Record<string, unknown>).total;
    if (typeof current === "number" && typeof total === "number" && total > 0) {
      return Math.max(0, Math.min(1, current / total));
    }
  }
  // 2. Iteration-based: event.iteration / totalIterations
  if (typeof event.iteration === "number" && typeof totalIterations === "number" && totalIterations > 0) {
    return Math.max(0, Math.min(1, event.iteration / totalIterations));
  }
  return null;
}

/** Fallback: estimate progress from activity event count when no real progress data exists.
 *  Uses a slow saturating curve so it doesn't "fill up immediately".
 *  count=0 → 0.1 (just spawned, 1 col dim), 1→0.2, 3→0.4, 7→0.8, 9+→0.9 */
function estimateProgressFromEventCount(count: number): number {
  if (count <= 0) return 0.1;
  return Math.min(0.9, 0.1 + count * 0.1);
}

/** Compute a human-readable stable ID for an agent that matches message-derived specs.
 *  Priority: subAgentRole (matches spec role/name) → subagentCodename → agentId → agentName */
function stableAgentKey(event: LiveToolEvent): string | null {
  return (
    event.subAgentRole ??
    event.subagentCodename ??
    (event.agentId && event.agentId !== "__main__" ? event.agentId : null) ??
    event.agentName ??
    null
  );
}

function deriveInlineSubagents(events: LiveToolEvent[]): InlineSubagentInfo[] {
  // Phase 1: Build agentId → stableKey mapping from lifecycle/subagent events.
  // When a subagent is spawned, we get both its runtime agentId (UUID) and its role/codename.
  // We map the UUID to the human-readable role so later tool events (which only carry agentId)
  // get attributed to the same key as the spawn event (and match message-derived specs).
  const idMap = new Map<string, string>(); // agentId (UUID) → stableKey (e.g. "calculator")
  for (const event of events) {
    const key = stableAgentKey(event);
    if (event.agentId && event.agentId !== "__main__" && key && key !== event.agentId) {
      idMap.set(event.agentId, key);
    }
  }

  /** Resolve any event to its canonical stable key, using the id mapping. */
  const resolveKey = (e: LiveToolEvent): string | null => {
    if (e.agentId && e.agentId !== "__main__") {
      const mapped = idMap.get(e.agentId);
      if (mapped) return mapped;
    }
    return stableAgentKey(e);
  };

  const byId = new Map<string, InlineSubagentInfo>();
  const activityCount = new Map<string, number>();
  const totalIterations = new Map<string, number>();
  const realProgress = new Map<string, number>();

  // Phase 2: Single pass to accumulate counts and build agent records using resolved keys.
  for (const event of events) {
    const key = resolveKey(event);
    const isLifecycle = event.lifecycle === "spawned" || event.lifecycle === "finished";
    const isSubagentMarker = event.name === "subagent";
    const isSubagentEvent =
      isLifecycle ||
      Boolean(event.subagentCodename) ||
      (Boolean(event.parentToolUseId) && Boolean(event.subAgentRole)) ||
      (Boolean(event.agentId) && event.agentId !== "__main__" && Boolean(event.agentId && idMap.has(event.agentId)));

    if (key) {
      if (event.lifecycle === "finished" && typeof event.iterationCount === "number") {
        totalIterations.set(key, event.iterationCount);
      }
      const prog = extractProgressFromEvent(event, totalIterations.get(key));
      if (prog !== null) {
        const existing = realProgress.get(key);
        if (existing === undefined || prog > existing) realProgress.set(key, prog);
      }
      if (!isLifecycle && !isSubagentMarker && isSubagentEvent) {
        activityCount.set(key, (activityCount.get(key) ?? 0) + 1);
      }
    }

    if (!isSubagentEvent || !key || key === "__main__") continue;

    const existing = byId.get(key);
    const status: InlineSubagentStatus =
      event.lifecycle === "finished"
        ? event.status === "error" ? "error" : "done"
        : event.status === "error" ? "error"
        : event.status === "waiting_approval" ? "waiting"
        : event.status === "done" ? "done"
        : "running";

    const task =
      firstString(event.input as Record<string, unknown> | undefined, ["prompt_preview", "prompt", "task", "description", "query", "message"]) ||
      event.thought || existing?.task || "";
    const outputObj = event.output as Record<string, unknown> | undefined;
    const outputIsString = typeof event.output === "string";
    const summary =
      (event.lifecycle === "finished" || event.status === "done" || event.status === "error")
        ? (outputIsString
            ? event.output as string
            : firstString(outputObj, ["summary", "result", "output", "thought", "observation", "answer", "content"]))
            || event.thought || event.observation || existing?.summary
        : existing?.summary;
    const filesTouched = Array.isArray(outputObj?.files_touched)
      ? (outputObj!.files_touched as unknown[]).filter((p): p is string => typeof p === "string")
      : event.filesTouched ?? existing?.filesTouchedCount ?? 0;
    const inputName = firstString(event.input as Record<string, unknown> | undefined, ["name", "display_name"]);
    const errorMsg =
      status === "error"
        ? (outputIsString
            ? event.output as string
            : firstString(outputObj, ["error", "message"])) || event.thought || existing?.error
        : existing?.error;

    let progress: number;
    if (status === "done") {
      progress = 1.0;
    } else if (status === "error") {
      progress = realProgress.get(key)
        ?? (totalIterations.get(key) && typeof event.iteration === "number"
            ? Math.min(0.9, event.iteration / totalIterations.get(key)!) : null)
        ?? ((activityCount.get(key) ?? 0) > 0 ? estimateProgressFromEventCount(activityCount.get(key)!) : 0.3);
    } else {
      progress = realProgress.get(key)
        ?? (totalIterations.get(key) && typeof event.iteration === "number"
            ? Math.min(0.9, event.iteration / totalIterations.get(key)!) : null)
        ?? estimateProgressFromEventCount(activityCount.get(key) ?? 0);
    }

    byId.set(key, {
      id: key,
      name:
        inputName ||
        event.subAgentRole ||
        event.subagentCodename ||
        existing?.name ||
        event.agentName ||
        key,
      role: event.subAgentRole ?? existing?.role,
      avatar: event.subagentAvatar ?? existing?.avatar,
      status:
        existing?.status === "running" || existing?.status === "waiting"
          ? status === "done" || status === "error" ? status : existing.status
          : status,
      task: task || existing?.task || "",
      summary:
        summary ||
        event.observation?.slice(0, 200) ||
        (event.thought ? event.thought.slice(0, 200) : existing?.summary),
      filesTouchedCount: Array.isArray(filesTouched)
        ? Math.max(filesTouched.length, existing?.filesTouchedCount ?? 0)
        : typeof filesTouched === "number"
          ? Math.max(filesTouched, existing?.filesTouchedCount ?? 0)
          : existing?.filesTouchedCount ?? 0,
      iterationCount:
        event.iterationCount ??
        (typeof outputObj?.iteration_count === "number" ? outputObj.iteration_count as number : existing?.iterationCount),
      error: errorMsg,
      progress,
    });
  }
  return Array.from(byId.values());
}

function parseToolContent(msg: ToolMessage): unknown {
  const content = msg.content;
  if (typeof content !== "string") return null;
  try {
    return JSON.parse(content);
  } catch {
    return content;
  }
}

function roleEmoji(role?: string): string | undefined {
  if (!role) return undefined;
  const r = role.toLowerCase();
  if (r.includes("research") || r.includes("搜索") || r.includes("调研")) return "🔍";
  if (r.includes("code") || r.includes("coder") || r.includes("开发") || r.includes("编程")) return "💻";
  if (r.includes("write") || r.includes("writer") || r.includes("写作")) return "✍️";
  if (r.includes("review") || r.includes("审查") || r.includes("评审")) return "👀";
  if (r.includes("design") || r.includes("设计")) return "🎨";
  if (r.includes("test") || r.includes("测试")) return "🧪";
  if (r.includes("plan") || r.includes("规划")) return "📋";
  if (r.includes("analysis") || r.includes("分析")) return "📊";
  return undefined;
}

export function deriveSubagentsFromMessages(
  messages: Message[],
): InlineSubagentInfo[] {
  const results: InlineSubagentInfo[] = [];
  const toolResults = new Map<string, { data: unknown; error: boolean }>();

  for (const msg of messages) {
    if (msg.type === "tool" && msg.tool_call_id) {
      const parsed = parseToolContent(msg as ToolMessage);
      toolResults.set(msg.tool_call_id, {
        data: parsed,
        error: (msg as ToolMessage).status === "error",
      });
    }
  }

  let agentIndex = 0;
  for (const msg of messages) {
    if (msg.type !== "ai") continue;
    const aiMsg = msg as AIMessage;
    const toolCalls = aiMsg.tool_calls ?? [];

    for (const tc of toolCalls) {
      if (!isTeammateToolName(tc.name)) continue;
      // Legacy "task" tools are handled by SubtaskCard/ParallelSubtasksGrid, not here.
      if (tc.name.toLowerCase() === "task") continue;

      const args = (tc.args ?? {}) as Record<string, unknown>;
      const toolResult = tc.id ? toolResults.get(tc.id) : undefined;
      const result = toolResult?.data;
      const hasToolResult = Boolean(toolResult);
      const toolErrored = Boolean(toolResult?.error);

      const resultObj =
        result && typeof result === "object" && !Array.isArray(result)
          ? (result as Record<string, unknown>)
          : null;
      const successes = Array.isArray(resultObj?.successes)
        ? (resultObj!.successes as Array<Record<string, unknown>>)
        : [];
      const failures = Array.isArray(resultObj?.failures)
        ? (resultObj!.failures as Array<Record<string, unknown>>)
        : [];
      const resultIsString = typeof result === "string";

      const specs = Array.isArray(args.specs)
        ? (args.specs as Array<Record<string, unknown>>)
        : Array.isArray(args.agents)
          ? (args.agents as Array<Record<string, unknown>>)
          : Array.isArray(args.tasks)
            ? (args.tasks as Array<Record<string, unknown>>)
            : [];

      if (specs && specs.length > 0) {
        for (let i = 0; i < specs.length; i++) {
          const spec = specs[i];
          if (!spec) continue;
          const agentId =
            typeof spec.agent_id === "string"
              ? spec.agent_id
              : typeof spec.name === "string"
                ? spec.name
                : `spec-${i}`;
          const role = typeof spec.role === "string" ? spec.role : undefined;

          const success = successes.find(
            (s) =>
              (typeof s.agent_id === "string" && s.agent_id === agentId) ||
              (typeof s.spec_index === "number" && s.spec_index === i) ||
              (typeof s.role === "string" && role && s.role === role),
          );
          const failure = failures.find(
            (f) =>
              (typeof f.agent_id === "string" && f.agent_id === agentId) ||
              (typeof f.spec_index === "number" && f.spec_index === i) ||
              (typeof f.role === "string" && role && f.role === role),
          );

          const matched = success || failure;
          const displayName = matched
            ? firstString(matched, ["display_name", "name", "codename"])
            : undefined;
          const codename = matched
            ? typeof matched.codename === "string"
              ? matched.codename
              : undefined
            : undefined;
          const specName =
            typeof spec.name === "string"
              ? spec.name
              : typeof spec.codename === "string"
                ? spec.codename
                : undefined;
          const name = displayName || codename || specName || role || agentId;

          const task =
            firstString(spec, ["prompt_preview", "prompt", "task", "description", "query", "message"]) ||
            (matched ? firstString(matched, ["task_label", "task_preview"]) || "" : "");

          let status: InlineSubagentStatus = hasToolResult
            ? failure
              ? "error"
              : success
                ? "done"
                : toolErrored || resultObj?.ok === false
                  ? "error"
                  : hasToolResult
                    ? "done"
                    : "running"
            : "running";

          let summary = "";
          let error = "";
          let iterationCount: number | undefined;
          let filesTouched = 0;

          if (success) {
            summary =
              firstString(success, ["output", "result", "summary", "content"]) || "";
            if (typeof success.iteration_count === "number")
              iterationCount = success.iteration_count;
            if (Array.isArray(success.files_touched))
              filesTouched = success.files_touched.length;
          } else if (failure) {
            error =
              firstString(failure, ["error", "message"]) ||
              (typeof failure.error_type === "string" ? failure.error_type : "");
            summary =
              firstString(failure, ["partial_output", "output"]) || "";
            if (typeof failure.iteration_count === "number")
              iterationCount = failure.iteration_count;
            if (Array.isArray(failure.files_touched))
              filesTouched = failure.files_touched.length;
          } else if (resultIsString && hasToolResult) {
            summary = result as string;
            if (toolErrored) error = result as string;
          } else if (resultObj && hasToolResult && !success && !failure) {
            summary =
              firstString(resultObj, ["output", "result", "summary", "content"]) || "";
            error = firstString(resultObj, ["error", "message"]) || "";
            if (resultObj.ok === false || toolErrored) status = "error";
          }

          const resultAvatar = matched && typeof matched.avatar === "string"
            ? matched.avatar
            : undefined;
          const specAvatar = typeof spec.avatar === "string" ? spec.avatar : undefined;

          // Progress from message data: done/error → 1.0, running → no info (undefined → show starting state)
          const progress =
            status === "done" ? 1.0 :
            status === "error" ? 0.5 :
            undefined;

          results.push({
            id: agentId,
            name,
            role: role !== name ? role : undefined,
            avatar: resultAvatar ?? specAvatar ?? roleEmoji(role ?? name),
            status,
            task,
            summary: summary || undefined,
            filesTouchedCount: filesTouched,
            iterationCount,
            error: error || undefined,
            index: agentIndex++,
            progress,
          });
        }
      } else {
        // Single agent call (call_agent, spawn_agent, delegate_agent, or "subagent" record).
        // Also handles MCP server-prefixed names (e.g. "team.call_agent").
        const agentId =
          typeof args.agent_id === "string"
            ? (args.agent_id as string)
            : typeof args.subagent_id === "string"
              ? (args.subagent_id as string)
              : tc.id ?? `call-${Math.random().toString(36).slice(2, 10)}`;
        const role = typeof args.role === "string" ? (args.role as string) : undefined;
        const name =
          typeof args.name === "string"
            ? (args.name as string)
            : typeof args.display_name === "string"
              ? (args.display_name as string)
              : typeof args.codename === "string"
              ? (args.codename as string)
              : role ?? agentId;
        const task =
          firstString(args, [
            "prompt_preview",
            "prompt",
            "task",
            "description",
            "query",
            "message",
          ]) ||
          (typeof args.summary === "string" ? (args.summary as string).slice(0, 100) : "") ||
          "";

        let status: InlineSubagentStatus = hasToolResult ? "done" : "running";
        let summary = typeof args.summary === "string" ? (args.summary as string) : "";
        let error = typeof args.error === "string" ? (args.error as string) : "";
        let filesTouched = 0;
        let iterationCount: number | undefined;

        // Determine status from args.status (for "subagent" record items) or tool result.
        if (typeof args.status === "string") {
          const argStatus = (args.status as string).toLowerCase();
          if (argStatus === "done" || argStatus === "completed" || argStatus === "finished") {
            status = "done";
          } else if (argStatus === "error" || argStatus === "failed") {
            status = "error";
          } else if (argStatus === "running") {
            status = "running";
          } else if (argStatus === "waiting_approval" || argStatus === "waiting") {
            status = "waiting";
          }
        }

        if (resultObj) {
          if (resultObj.ok === false || toolErrored) status = "error";
          else if (hasToolResult) status = "done";
          summary = firstString(resultObj, ["output", "result", "summary", "content"]) || summary;
          error = firstString(resultObj, ["error", "message"]) || error;
          if (typeof resultObj.iteration_count === "number")
            iterationCount = resultObj.iteration_count;
          if (Array.isArray(resultObj.files_touched))
            filesTouched = resultObj.files_touched.length;
        } else if (resultIsString) {
          if (toolErrored) { status = "error"; error = result as string; }
          else status = "done";
          summary = result as string;
        } else if (toolErrored) {
          status = "error";
        }

        if (Array.isArray(args.files_touched)) {
          filesTouched = Math.max(filesTouched, (args.files_touched as unknown[]).length);
        }

        const resultAvatar = resultObj && typeof resultObj.avatar === "string"
          ? (resultObj.avatar as string)
          : undefined;
        const specAvatar = typeof args.avatar === "string" ? (args.avatar as string) : undefined;

        const progress =
          status === "done" ? 1.0 :
          status === "error" ? 0.5 :
          undefined;

        results.push({
          id: agentId,
          name,
          role: role !== name ? role : undefined,
          avatar: resultAvatar ?? specAvatar ?? roleEmoji(role ?? name),
          status,
          task,
          summary: summary || undefined,
          filesTouchedCount: filesTouched,
          iterationCount,
          error: error || undefined,
          index: agentIndex++,
          progress,
        });
      }
    }
  }
  return results;
}

/**
 * Single-row LED dot progress bar (1 row × 14 columns), matching Kimi's style.
 * Columns light up left-to-right strictly by percentage:
 *   0%  - 6%   → 0 cols lit (just started)
 *   7%  - 13%  → 1 col lit
 *   ...
 *   93%+       → 13 cols lit (running cap — full 14 is the ✓ state)
 * The rightmost lit column pulses softly to show "actively working".
 */
function LedProgress({ progress }: { progress?: number }) {
  const cols = 14;
  // progress undefined/NaN → just started (0.1 = ~1 col)
  const p = typeof progress === "number" && !isNaN(progress)
    ? Math.max(0, Math.min(1, progress))
    : 0.1;
  // Lit columns = floor(p * cols). Running agents max out at 13/14.
  const litCols = Math.min(cols - 1, Math.floor(p * cols));
  const isActive = p > 0 && p < 1;

  return (
    <span className="inline-flex shrink-0 items-center gap-[1.5px] leading-none" aria-label="running">
      {Array.from({ length: cols }).map((_, c) => {
        const isLit = c < litCols;
        const isPulsing = isLit && c === litCols - 1 && isActive;
        return (
          <span
            key={c}
            className={cn(
              "inline-block rounded-sm transition-colors duration-200",
              isLit
                ? "bg-success/90 dark:bg-success/90"
                : "bg-success/15 dark:bg-success/15",
              isPulsing && "animate-[pulse-soft_1.2s_ease-in-out_infinite]",
            )}
            style={{
              width: "3px",
              height: "3px",
            }}
          />
        );
      })}
    </span>
  );
}

function StatusIndicator({ status, progress }: { status: InlineSubagentStatus; progress?: number }) {
  if (status === "done") {
    return (
      <span className="flex size-4 items-center justify-center text-success">
        <CheckIcon className="size-3.5" />
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="flex size-4 items-center justify-center text-destructive/80">
        <XCircleIcon className="size-3.5" />
      </span>
    );
  }
  if (status === "waiting") {
    return (
      <span className="flex size-4 items-center justify-center text-warning/80">
        <Loader2Icon className="size-3.5 animate-spin" />
      </span>
    );
  }
  // running: LED dot matrix with column-by-column fill
  return <LedProgress progress={progress} />;
}

function AgentIndexBadge({ index, done }: { index: number; done?: boolean }) {
  return (
    <span className={cn(
      "font-mono text-xs",
      done ? "text-muted-foreground/60" : "text-muted-foreground/60"
    )}>
      {String(index + 1).padStart(2, "0")}
    </span>
  );
}

// Subtle L-shaped tree connector like Kimi's — small, faint, minimal
function LConnector() {
  return (
    <span className="relative mr-1.5 mt-0.5 shrink-0 self-start">
      <span className="block w-px border-l border-muted-foreground/15" style={{ height: "8px" }} />
      <span className="absolute left-0 top-[8px] block h-px w-1 border-t border-muted-foreground/15" />
    </span>
  );
}

function KimiStyleSubagentCard({
  agent,
  onFocus,
}: {
  agent: InlineSubagentInfo;
  onFocus: (id: string) => void;
}) {
  const isRunning = agent.status === "running" || agent.status === "waiting";
  const isDone = agent.status === "done";

  return (
    <button
      type="button"
      onClick={() => onFocus(agent.id)}
      className={cn(
        "group/agent-row flex w-full items-start gap-0 px-2.5 py-0.5 text-left transition-colors rounded",
        "hover:bg-background/60 dark:hover:bg-background/30",
      )}
    >
      {/* Avatar - compact, matches Kimi's small avatar style */}
      <span className="mr-1.5 mt-px flex size-4 shrink-0 items-center justify-center text-sm leading-none">
        {agent.avatar ? (
          <span aria-hidden="true" className="leading-none">{agent.avatar}</span>
        ) : (
          <BotIcon className="size-[13px] text-muted-foreground/60" />
        )}
      </span>

      {/* Content area - two rows */}
      <div className="min-w-0 flex-1">
        {/* Row 1: Name + index */}
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "truncate text-sm leading-tight",
              isRunning ? "text-foreground" : isDone ? "text-foreground/70" : "text-foreground/80",
            )}
          >
            {agent.name}
          </span>

          <span className="flex-1" />

          <AgentIndexBadge index={agent.index ?? 0} done={isDone} />
        </div>

        {/* Row 2: L-connector + task text + status indicator */}
        {agent.task && (
          <div className="mt-px flex items-center gap-0">
            <LConnector />
            <span
              className={cn(
                "min-w-0 flex-1 truncate text-xs leading-snug",
                isDone ? "text-muted-foreground/60" : "text-muted-foreground/70",
              )}
            >
              {agent.task}
            </span>
            <span className="ml-1.5 shrink-0 self-center">
              <StatusIndicator status={agent.status} progress={agent.progress} />
            </span>
          </div>
        )}

        {/* Show status inline when no task */}
        {!agent.task && (
          <span className="ml-1.5 shrink-0">
            <StatusIndicator status={agent.status} progress={agent.progress} />
          </span>
        )}

        {/* Error message - subtle */}
        {agent.error && agent.status === "error" && (
          <div className="mt-0.5 truncate pl-3 text-xs text-destructive/60">
            {agent.error.slice(0, 60)}
          </div>
        )}
      </div>
    </button>
  );
}

export function InlineSubagentCards({
  events,
  agents: preDerivedAgents,
  className,
}: {
  events?: LiveToolEvent[];
  agents?: InlineSubagentInfo[];
  className?: string;
}) {
  const eventAgents = useMemo(
    () => (events ? deriveInlineSubagents(events) : []),
    [events],
  );

  const agents = useMemo(() => {
    // Step 1: Normalize preDerivedAgents — collapse anonymous runtime duplicates into named spec entries.
    // deriveSubagentsFromMessages() may produce two groups:
    //   (a) "named" entries from the batch `specs`/`agents`/`tasks` array (e.g. calculator/translator/analyst)
    //   (b) "anonymous/runtime" entries from subsequent per-agent delegate/spawn calls, which carry the
    //       real task text but have generic names like "general"/UUID. These are duplicates of (a) that
    //       hold the task payload — they must be MERGED INTO the named entries, not rendered separately.
    const GENERIC_NAMES = new Set(["general", "agent", "subagent", "worker", "assistant"]);
    const isAnonymousRuntime = (a: InlineSubagentInfo): boolean => {
      if (!a.name) return true;
      const lower = a.name.toLowerCase();
      if (GENERIC_NAMES.has(lower)) return Boolean(a.task);
      if (a.id && a.id === a.name && /^[a-f0-9-]{8,}$/i.test(a.id)) return Boolean(a.task);
      return false;
    };

    /** Merge src fields into dst (dst wins on name/avatar/role; src wins on task/progress/summary). */
    const mergeInto = (dst: InlineSubagentInfo, src: InlineSubagentInfo): InlineSubagentInfo => {
      // Prefer terminal status from either side
      const terminal = new Set<InlineSubagentStatus>(["done", "error"]);
      const status: InlineSubagentStatus = terminal.has(dst.status)
        ? dst.status
        : terminal.has(src.status)
          ? src.status
          : dst.status || src.status;
      let progress: number | undefined;
      if (status === "done") progress = 1.0;
      else if (status === "error") progress = src.progress ?? dst.progress ?? 0.5;
      else progress = src.progress ?? dst.progress;
      return {
        ...dst,
        status,
        progress,
        task: dst.task || src.task,
        summary: dst.summary || src.summary,
        error: dst.error || src.error,
        filesTouchedCount: Math.max(dst.filesTouchedCount, src.filesTouchedCount),
        iterationCount: dst.iterationCount ?? src.iterationCount,
      };
    };

    // Build a cleaned, deduplicated base list from preDerivedAgents.
    let cleanedPres: InlineSubagentInfo[] = [];
    if (preDerivedAgents && preDerivedAgents.length > 0) {
      const namedPres: InlineSubagentInfo[] = [];
      const anonPres: InlineSubagentInfo[] = [];
      for (const a of preDerivedAgents) {
        if (isAnonymousRuntime(a)) anonPres.push(a);
        else namedPres.push(a);
      }

      // If anon count ≤ named count, fold them in by position (spawn order == spec order).
      // If anon count > named count (rare), fold as many as possible then append the rest.
      const mergedNamed = namedPres.map((n, i) =>
        anonPres[i] ? mergeInto(n, anonPres[i]) : n,
      );
      cleanedPres = [...mergedNamed, ...anonPres.slice(namedPres.length)];
    }

    // Step 2: Merge with live event agents.
    if (cleanedPres.length === 0) return eventAgents;
    if (eventAgents.length === 0) {
      // Re-index on the way out so badge numbers are 1..N.
      return cleanedPres.map((a, i) => ({ ...a, index: i }));
    }

    const preById = new Map(cleanedPres.map((a) => [a.id, a]));
    const preByName = new Map<string, InlineSubagentInfo>();
    for (const a of cleanedPres) {
      if (a.name) preByName.set(a.name.toLowerCase(), a);
      if (a.role) preByName.set(a.role.toLowerCase(), a);
    }
    const merged: InlineSubagentInfo[] = [];
    const seenPreIds = new Set<string>();

    for (let i = 0; i < eventAgents.length; i++) {
      const ea = eventAgents[i]!;
      let pre = preById.get(ea.id);
      if (!pre && ea.name) pre = preByName.get(ea.name.toLowerCase());
      if (!pre && ea.role) pre = preByName.get(ea.role.toLowerCase());
      // Positional fallback: event order mirrors spec declaration order.
      if (!pre && i < cleanedPres.length) {
        pre = cleanedPres[i];
      }

      if (pre) {
        seenPreIds.add(pre.id);
        const combined = mergeInto(pre, ea);
        // Keep pre's stable identity (id/name/avatar) but let ea's live data win for progress/status/task
        // when ea's status is more recent (done/error overrides running, but not vice-versa).
        const finalStatus: InlineSubagentStatus = combined.status;
        let finalProgress: number | undefined;
        if (finalStatus === "done") finalProgress = 1.0;
        else if (finalStatus === "error") finalProgress = ea.progress ?? pre.progress ?? 0.5;
        else finalProgress = ea.progress ?? pre.progress;

        merged.push({
          ...combined,
          id: pre.id,
          name: pre.name || ea.name,
          role: pre.role || ea.role,
          avatar: pre.avatar ?? ea.avatar,
          index: i,
          task: ea.task || pre.task,
          summary: ea.summary || pre.summary,
          status: finalStatus,
          progress: finalProgress,
        });
      } else {
        merged.push({ ...ea, index: i });
      }
    }
    for (const pa of cleanedPres) {
      if (!seenPreIds.has(pa.id)) merged.push(pa);
    }
    return merged.map((a, i) => ({ ...a, index: i }));
  }, [eventAgents, preDerivedAgents]);

  if (agents.length === 0) return null;

  const handleFocus = (agentId: string) => {
    emitAgentWorkbenchFocus({ agentId });
  };

  const runningCount = agents.filter((a) => a.status === "running" || a.status === "waiting").length;
  const errorCount = agents.filter((a) => a.status === "error").length;
  const allDone = runningCount === 0;

  return (
    <div className={cn("my-1.5", className)}>
      {/* Kimi-style container: header + agents in one light card */}
      <div className="rounded-md bg-muted/30 dark:bg-muted/15 px-1 py-1">
        {/* Header inside the card */}
        <div className="flex items-center gap-1.5 px-2 py-0.5">
          <UsersIcon className="size-[13px] text-muted-foreground/60" />
          <span className="text-xs text-muted-foreground/70">
            Agent 集群
          </span>
          <span className="text-xs text-muted-foreground/40">
            |
          </span>
          <span className="text-xs text-muted-foreground/60">
            {allDone
              ? `${agents.length} 个任务已完成`
              : runningCount > 0
                ? `${runningCount} 个执行中`
                : `${agents.length} 个并行任务`}
          </span>
          {errorCount > 0 && (
            <span className="text-xs text-destructive/60">
              · {errorCount} 失败
            </span>
          )}
        </div>

        {/* Agent rows */}
        <div className="mt-0.5">
          {agents.map((agent) => (
            <KimiStyleSubagentCard
              key={agent.id}
              agent={agent}
              onFocus={handleFocus}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
