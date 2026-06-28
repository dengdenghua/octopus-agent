"use client";

import {
  CheckCircle2Icon,
  ChevronDownIcon,
  XCircleIcon,
  Loader2Icon,
  TerminalIcon,
  FileEditIcon,
  SearchIcon,
  GlobeIcon,
  EyeIcon,
  GitBranchIcon,
  BrainCircuitIcon,
  ShieldAlertIcon,
  RefreshCwIcon,
  ListChecksIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { cn } from "@/lib/utils";

import { emitAgentWorkbenchFocus } from "./agent-workbench-events";
import {
  agentRunBadgeClass,
  agentRunStatusLightPulseClass,
} from "./agent-run-status";
import { stripToolEnvelope } from "./messages/trace-labels";
import { getProcessTraceEvents } from "./process-trace-events";
import { isSkillToolName } from "./tool-action-kind";

type TimelineT = Pick<Translations, "liveTools" | "liveToolTimeline">;

const TOOL_ICONS: Record<string, { icon: React.ElementType; color: string }> = {
  bash: { icon: TerminalIcon, color: "text-green-500" },
  exec_shell: { icon: TerminalIcon, color: "text-green-500" },
  shell_command: { icon: TerminalIcon, color: "text-green-500" },
  write_file: { icon: FileEditIcon, color: "text-blue-500" },
  write_text_file: { icon: FileEditIcon, color: "text-blue-500" },
  create_file: { icon: FileEditIcon, color: "text-blue-500" },
  edit_code: { icon: FileEditIcon, color: "text-blue-500" },
  edit_text_file: { icon: FileEditIcon, color: "text-blue-500" },
  str_replace: { icon: FileEditIcon, color: "text-blue-500" },
  read_file: { icon: EyeIcon, color: "text-cyan-500" },
  read_text_file: { icon: EyeIcon, color: "text-cyan-500" },
  fetch_url: { icon: GlobeIcon, color: "text-orange-500" },
  list_cwd: { icon: SearchIcon, color: "text-purple-500" },
  glob: { icon: SearchIcon, color: "text-purple-500" },
  grep: { icon: SearchIcon, color: "text-purple-500" },
  todo_write: { icon: ListChecksIcon, color: "text-violet-500" },
  call_agent: { icon: BrainCircuitIcon, color: "text-sky-500" },
  call_agent_parallel: { icon: BrainCircuitIcon, color: "text-sky-500" },
  bb_read: { icon: BrainCircuitIcon, color: "text-sky-500" },
  bb_write: { icon: BrainCircuitIcon, color: "text-sky-500" },
  bb_keys: { icon: BrainCircuitIcon, color: "text-sky-500" },
  "deep-research-swarm": { icon: BrainCircuitIcon, color: "text-violet-500" },
  "report-writing": { icon: FileEditIcon, color: "text-blue-500" },
  docx: { icon: FileEditIcon, color: "text-blue-500" },
  web_search: { icon: GlobeIcon, color: "text-orange-500" },
  apply_skill: { icon: BrainCircuitIcon, color: "text-violet-500" },
  list_learned_skills: { icon: BrainCircuitIcon, color: "text-violet-500" },
  learn_skill_from_text: { icon: BrainCircuitIcon, color: "text-violet-500" },
  planning: { icon: BrainCircuitIcon, color: "text-sky-500" },
  agent_thought: { icon: BrainCircuitIcon, color: "text-violet-500" },
  team_swarm: { icon: BrainCircuitIcon, color: "text-sky-500" },
  team_routing: { icon: BrainCircuitIcon, color: "text-sky-500" },
  git_status: { icon: GitBranchIcon, color: "text-amber-500" },
  git_commit: { icon: GitBranchIcon, color: "text-amber-500" },
  git_diff: { icon: GitBranchIcon, color: "text-amber-500" },
  stream_recovery: { icon: RefreshCwIcon, color: "text-sky-500" },
  model_gateway: { icon: BrainCircuitIcon, color: "text-sky-500" },
  model_reasoning: { icon: BrainCircuitIcon, color: "text-violet-500" },
};

function getToolLabels(t: TimelineT): Record<string, string> {
  return {
    bash: t.liveTools.terminal ?? "Terminal",
    exec_shell: t.liveTools.terminal ?? "Terminal",
    shell_command: t.liveTools.terminal ?? "Terminal",
    write_file: t.liveTools.writeFile ?? "Write File",
    write_text_file: t.liveTools.writeFile ?? "Write File",
    create_file: t.liveTools.writeFile ?? "Create File",
    edit_code: t.liveTools.editFile ?? "Edit File",
    edit_text_file: t.liveTools.editFile ?? "Edit File",
    str_replace: t.liveTools.editFile ?? "Edit File",
    read_file: t.liveTools.readFile ?? "Read File",
    read_text_file: t.liveTools.readFile ?? "Read File",
    fetch_url: "Browse Page",
    list_cwd: t.liveTools.searchFiles ?? "List Files",
    glob: t.liveTools.searchFiles ?? "Search Files",
    grep: t.liveTools.searchContent ?? "Search Content",
    todo_write: "Todos",
    call_agent: "Subagent",
    call_agent_parallel: "Agent swarm",
    bb_read: "Blackboard",
    bb_write: "Blackboard",
    bb_keys: "Blackboard",
    "deep-research-swarm": "Research swarm",
    "report-writing": "Report writing",
    docx: "DOCX",
    web_search: t.liveTools.webSearch ?? "Web Search",
    apply_skill: "Apply skill",
    list_learned_skills: "List skills",
    learn_skill_from_text: "Learn skill",
    planning: "Planning",
    agent_thought: "Agent thought",
    team_swarm: "Team swarm",
    team_routing: "Team routing",
    git_status: t.liveTools.gitStatus ?? "Git Status",
    git_commit: t.liveTools.gitCommit ?? "Git Commit",
    git_diff: t.liveTools.gitDiff ?? "Git Diff",
    stream_recovery: t.liveTools.streamRecovery ?? "Stream recovery",
    model_gateway: "Model gateway",
    model_reasoning: "Model reasoning",
  };
}

export interface LiveToolEvent {
  id: string;
  name: string;
  status: "running" | "done" | "error" | "waiting_approval";
  startedAt: number;
  durationMs?: number;
  finishedAt?: number;
  iteration: number;
  agentId?: string;
  agentName?: string;
  input?: Record<string, unknown>;
  output?: unknown;
  parentToolUseId?: string;
  subAgentRole?: string;
  /** Cute codename assigned at spawn time (e.g. "Spark-3a4"). Set on
   * sub-agent-attributable events so the workbench can group them
   * under one tile. */
  subagentCodename?: string;
  /** Emoji avatar derived from role. Falls back to 🐙 for unknown
   * roles. */
  subagentAvatar?: string;
  /** Lifecycle marker. Synthesised events carry these instead of a
   * tool name, so panels can render the spawn moment + finish stats
   * without waiting for the first real tool call. */
  lifecycle?: "spawned" | "finished";
  /** Set on lifecycle="finished" events. */
  iterationCount?: number;
  /** Set on lifecycle="finished" events. */
  filesTouched?: string[];
  thought?: string;
  observation?: string;
}

function workflowEvents(events: LiveToolEvent[]): LiveToolEvent[] {
  return getProcessTraceEvents(events);
}

function getVisibleEvents(events: LiveToolEvent[]): LiveToolEvent[] {
  const topLevel = workflowEvents(events).filter((e) => !e.parentToolUseId);
  const runningEvents = topLevel
    .filter(
      (event) =>
        event.status === "running" || event.status === "waiting_approval",
    )
    .sort((a, b) => a.startedAt - b.startedAt);
  const recentFinishedEvents = topLevel
    .filter((event) => event.status !== "running")
    .sort(
      (a, b) => (b.finishedAt ?? b.startedAt) - (a.finishedAt ?? a.startedAt),
    )
    .slice(0, runningEvents.length > 0 ? 2 : 4);

  return [...runningEvents, ...recentFinishedEvents];
}

function getAllVisibleEvents(events: LiveToolEvent[]): LiveToolEvent[] {
  return workflowEvents(events)
    .filter((event) => !event.parentToolUseId)
    .sort((a, b) => a.startedAt - b.startedAt);
}

function getRunningEvents(events: LiveToolEvent[]): LiveToolEvent[] {
  return workflowEvents(events)
    .filter((event) => !event.parentToolUseId && event.status === "running")
    .sort((a, b) => a.startedAt - b.startedAt);
}

function getChildren(
  events: LiveToolEvent[],
  parentId: string,
): LiveToolEvent[] {
  return events
    .filter((e) => e.parentToolUseId === parentId)
    .sort((a, b) => a.startedAt - b.startedAt);
}

export function LiveToolTimeline({
  events,
  className,
  groupByAgent,
  runningOnly = false,
  showAll = false,
}: {
  events: LiveToolEvent[];
  className?: string;
  groupByAgent?: boolean;
  runningOnly?: boolean;
  showAll?: boolean;
}) {
  const { t } = useI18n();
  const toolLabels = useMemo(() => getToolLabels(t), [t]);
  const visibleEvents = useMemo(
    () =>
      showAll
        ? getAllVisibleEvents(events)
        : runningOnly
          ? getRunningEvents(events)
          : getVisibleEvents(events),
    [events, runningOnly, showAll],
  );

  if (visibleEvents.length === 0) return null;

  if (groupByAgent) {
    return (
      <GroupedTimeline
        events={visibleEvents}
        allEvents={events}
        toolLabels={toolLabels}
        t={t}
        className={className}
      />
    );
  }

  return (
    <div className={cn("space-y-1 py-1.5", className)}>
      {visibleEvents.map((event, index) => (
        <ParentWithChildren
          key={`${event.id}:${index}`}
          event={event}
          allEvents={events}
          toolLabels={toolLabels}
          t={t}
        />
      ))}
    </div>
  );
}

function ParentWithChildren({
  event,
  allEvents,
  toolLabels,
  t,
  showAgent,
}: {
  event: LiveToolEvent;
  allEvents: LiveToolEvent[];
  toolLabels: Record<string, string>;
  t: TimelineT;
  showAgent?: boolean;
}) {
  const children = useMemo(
    () => getChildren(allEvents, event.id),
    [allEvents, event.id],
  );
  if (children.length === 0) {
    return (
      <ToolEventRow
        event={event}
        toolLabels={toolLabels}
        t={t}
        showAgent={showAgent}
      />
    );
  }
  return (
    <div className="space-y-1">
      <ToolEventRow
        event={event}
        toolLabels={toolLabels}
        t={t}
        showAgent={showAgent}
      />
      <div className="ml-6 space-y-1 border-l border-primary/20 pl-2">
        {children.map((child, index) => (
          <ToolEventRow
            key={`${event.id}:${child.id}:${index}`}
            event={child}
            toolLabels={toolLabels}
            t={t}
            showAgent
            nested
          />
        ))}
      </div>
    </div>
  );
}

function formatInputSummary(
  input?: Record<string, unknown>,
): string | undefined {
  if (!input) return undefined;
  const priority = [
    "command",
    "path",
    "file_path",
    "cwd",
    "pattern",
    "url",
    "query",
    "task",
    "prompt",
    "description",
  ] as const;
  for (const key of priority) {
    const v = input[key];
    if (v !== undefined && v !== null && `${v}`.trim() !== "") {
      const text = typeof v === "string" ? v : JSON.stringify(v);
      const normalized = text.replace(/\s+/g, " ").trim();
      return normalized.length > 120
        ? `${normalized.slice(0, 120)}…`
        : normalized;
    }
  }
  const entries = Object.entries(input).filter(
    ([, v]) => v !== undefined && v !== null,
  );
  if (entries.length === 0) return undefined;
  return entries
    .slice(0, 2)
    .map(([k, v]) => {
      const text = typeof v === "string" ? v : JSON.stringify(v);
      return `${k}: ${text.length > 60 ? text.slice(0, 60) + "…" : text}`;
    })
    .join(" · ");
}

function formatOutputSummary(output: unknown): string | undefined {
  if (output === undefined || output === null) return undefined;
  if (typeof output === "string") {
    const normalized = stripToolEnvelope(output).replace(/\s+/g, " ").trim();
    if (!normalized) return undefined;
    return normalized.length > 140
      ? `${normalized.slice(0, 140)}…`
      : normalized;
  }
  if (typeof output === "object" && !Array.isArray(output)) {
    const record = output as Record<string, unknown>;
    for (const key of [
      "error",
      "stderr",
      "stdout",
      "result",
      "message",
      "path",
      "content",
    ]) {
      const v = record[key];
      if (v !== undefined && v !== null && `${v}`.trim() !== "") {
        const text = typeof v === "string" ? v : JSON.stringify(v);
        const normalized = text.replace(/\s+/g, " ").trim();
        return `${key}: ${normalized.length > 120 ? normalized.slice(0, 120) + "…" : normalized}`;
      }
    }
  }
  const text = JSON.stringify(output);
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
}

function formatDetailBlock(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const normalized = text.trim();
  if (!normalized) return undefined;
  return normalized.length > 4000
    ? `${normalized.slice(0, 4000)}\n...`
    : normalized;
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith("{") && !trimmed.startsWith("["))) {
    return value;
  }
  try {
    return JSON.parse(trimmed);
  } catch (e) {
    swallow(e);
    return value;
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  const parsed = parseMaybeJson(value);
  if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
    return parsed as Record<string, unknown>;
  }
  return null;
}

function countItems(value: unknown, keys: string[]): number | null {
  const parsed = parseMaybeJson(value);
  if (Array.isArray(parsed)) return parsed.length;
  const record = asRecord(parsed);
  if (!record) return null;
  for (const key of keys) {
    const item = record[key];
    if (Array.isArray(item)) return item.length;
    const nested = asRecord(item);
    if (nested) {
      const nestedCount = countItems(nested, keys);
      if (nestedCount !== null) return nestedCount;
    }
  }
  return null;
}

interface SearchResultItem {
  title: string;
  url?: string;
}

function extractSearchResults(value: unknown, max = 8): SearchResultItem[] {
  const parsed = parseMaybeJson(value);
  const list = Array.isArray(parsed)
    ? parsed
    : (() => {
        const record = asRecord(parsed);
        if (!record) return [];
        for (const key of ["results", "items", "sources", "urls", "pages"]) {
          const candidate = record[key];
          if (Array.isArray(candidate)) return candidate;
        }
        return [record];
      })();
  const results: SearchResultItem[] = [];
  const seen = new Set<string>();
  for (const item of list) {
    const record = asRecord(item);
    if (!record) continue;
    const title =
      typeof record.title === "string" && record.title.trim()
        ? record.title.trim()
        : typeof record.name === "string" && record.name.trim()
          ? record.name.trim()
          : typeof record.text === "string" && record.text.trim()
            ? record.text.trim()
            : "";
    const url =
      typeof record.url === "string" && record.url.trim()
        ? record.url.trim()
        : typeof record.link === "string" && record.link.trim()
          ? record.link.trim()
          : "";
    const label = title || url;
    if (!label) continue;
    const key = url || label;
    if (seen.has(key)) continue;
    seen.add(key);
    results.push({ title: compactMiddle(label, 96), url: url || undefined });
    if (results.length >= max) break;
  }
  return results;
}

function extractSourceLabels(value: unknown, max = 4): string[] {
  const parsed = parseMaybeJson(value);
  const out: string[] = [];
  const visit = (item: unknown) => {
    if (out.length >= max) return;
    const record = asRecord(item);
    if (!record) return;
    const title = typeof record.title === "string" ? record.title.trim() : "";
    const url =
      typeof record.url === "string"
        ? record.url.trim()
        : typeof record.link === "string"
          ? record.link.trim()
          : "";
    if (url) {
      try {
        out.push(new URL(url).hostname.replace(/^www\./, ""));
        return;
      } catch (e) {
        swallow(e);
        out.push(url.slice(0, 32));
        return;
      }
    }
    if (title) out.push(title.slice(0, 32));
  };
  if (Array.isArray(parsed)) {
    parsed.forEach(visit);
    return out;
  }
  const record = asRecord(parsed);
  if (!record) return out;
  for (const key of ["results", "items", "sources", "urls", "pages"]) {
    const list = record[key];
    if (Array.isArray(list)) {
      list.forEach(visit);
      if (out.length > 0) return out;
    }
  }
  visit(record);
  return out;
}

function researchLogText(
  event: LiveToolEvent,
  t: TimelineT,
): {
  label: string;
  detail?: string;
  sources?: string[];
} | null {
  if (event.name === "web_search") {
    const query =
      typeof event.input?.query === "string" ? event.input.query.trim() : "";
    const count =
      countItems(event.output, ["results", "items", "sources"]) ??
      (typeof event.input?.max_results === "number"
        ? event.input.max_results
        : null);
    if (event.status === "running") {
      return {
        label: t.liveToolTimeline.searchingWeb,
        detail: query ? t.liveToolTimeline.searchingQuery(query) : undefined,
      };
    }
    return {
      label: t.liveToolTimeline.searchedPages(count ?? undefined),
      detail: query
        ? t.liveToolTimeline.searchResultCovering(query)
        : t.liveToolTimeline.searchResultInContext,
      sources: extractSourceLabels(event.output),
    };
  }

  if (event.name === "fetch_url") {
    const url =
      typeof event.input?.url === "string" ? event.input.url.trim() : "";
    const source = url
      ? (() => {
          try {
            return new URL(url).hostname.replace(/^www\./, "");
          } catch (e) {
            swallow(e);
            return url;
          }
        })()
      : undefined;
    return {
      label:
        event.status === "running"
          ? t.liveToolTimeline.browsingPage
          : t.liveToolTimeline.browsedOnePage,
      detail: source
        ? t.liveToolTimeline.sourceFrom(source)
        : t.liveToolTimeline.pageOpenedAndExtracted,
      sources: source ? [source] : extractSourceLabels(event.output, 1),
    };
  }

  return null;
}

function stringInput(
  input: Record<string, unknown> | undefined,
  keys: string[],
): string {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

function compactMiddle(text: string, max = 96): string {
  const clean = text.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  const head = Math.floor((max - 1) * 0.62);
  const tail = max - 1 - head;
  return `${clean.slice(0, head)}…${clean.slice(-tail)}`;
}

function actionStatusLabel(
  event: LiveToolEvent,
  verb: (running: boolean) => string,
  target?: string,
): string {
  const label = verb(event.status === "running");
  return target ? `${label} ${target}` : label;
}

function elapsedInputMs(input?: Record<string, unknown>): number | undefined {
  const value = input?.elapsed_ms ?? input?.elapsedMs;
  if (typeof value === "number" && Number.isFinite(value))
    return Math.max(0, value);
  if (
    typeof value === "string" &&
    value.trim() &&
    !Number.isNaN(Number(value))
  ) {
    return Math.max(0, Number(value));
  }
  return undefined;
}

function elapsedSeconds(input?: Record<string, unknown>): number {
  return Math.max(0, Math.floor((elapsedInputMs(input) ?? 0) / 1000));
}

function swarmLogText(
  event: LiveToolEvent,
  t: TimelineT,
): {
  label: string;
  detail?: string;
} | null {
  if (event.name === "call_agent_parallel") {
    const specs = Array.isArray(event.input?.specs) ? event.input.specs : [];
    const roles = specs
      .map((spec) => asRecord(spec))
      .map((spec) => {
        const role = spec?.agent_id ?? spec?.role ?? spec?.name;
        return typeof role === "string" ? role : "";
      })
      .filter(Boolean)
      .slice(0, 5);
    const count = specs.length;
    return {
      label:
        event.status === "running"
          ? t.liveToolTimeline.parallelDispatching(count || undefined)
          : t.liveToolTimeline.parallelTasksReturned(count || undefined),
      detail:
        roles.length > 0
          ? t.liveToolTimeline.rolesWithNextStep(roles.join(" / "))
          : t.liveToolTimeline.subtaskAggregation,
    };
  }

  if (event.name === "call_agent") {
    const role = stringInput(event.input, ["agent_id", "role", "name"]);
    return {
      label: role
        ? t.liveToolTimeline.callSubAgent(role)
        : t.liveToolTimeline.callSubAgentShort,
      detail: t.liveToolTimeline.focusedDelegation,
    };
  }

  if (event.name === "bb_write") {
    const key = stringInput(event.input, ["key"]);
    return {
      label: key
        ? t.liveToolTimeline.writeBlackboard(compactMiddle(key, 60))
        : t.liveToolTimeline.writeBlackboardShort,
      detail: t.liveToolTimeline.saveBlackboardFinding,
    };
  }

  if (event.name === "bb_read" || event.name === "bb_keys") {
    const key = stringInput(event.input, ["key"]);
    return {
      label:
        event.name === "bb_keys"
          ? t.liveToolTimeline.readBlackboardDirectory
          : key
            ? t.liveToolTimeline.readBlackboard(compactMiddle(key, 60))
            : t.liveToolTimeline.readBlackboardShort,
      detail: t.liveToolTimeline.pullParallelResults,
    };
  }

  return null;
}

function codeLogText(
  event: LiveToolEvent,
  t: TimelineT,
): {
  label: string;
  detail?: string;
} | null {
  if (event.name === "agent_thought") {
    return {
      label: t.liveToolTimeline.thoughtDetailLabel(
        event.iteration || undefined,
      ),
      detail: event.thought ?? t.liveToolTimeline.modelPublicReasoningFragment,
    };
  }

  if (event.name === "model_reasoning") {
    const outputRecord = asRecord(event.output);
    const content =
      typeof outputRecord?.content === "string"
        ? outputRecord.content
        : typeof event.output === "string"
          ? event.output
          : "";
    return {
      label: t.liveToolTimeline.modelPublicReasoningStream,
      detail: content
        ? compactMiddle(content, 220)
        : t.liveToolTimeline.modelOutputtingReasoning,
    };
  }

  if (isSkillToolName(event.name)) {
    const skillName =
      stringInput(event.input, ["skill", "skill_name", "name"]) || event.name;
    const request = stringInput(event.input, [
      "user_request",
      "request",
      "query",
      "task",
      "prompt",
    ]);
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.applyingSkill,
        compactMiddle(skillName, 80),
      ),
      detail: request
        ? compactMiddle(request, 180)
        : t.liveToolTimeline.invokeSkillProcess,
    };
  }

  if (event.name === "planning") {
    const request = stringInput(event.input, [
      "task",
      "prompt",
      "description",
      "summary",
    ]);
    return {
      label: actionStatusLabel(event, t.liveToolTimeline.planningNextStep),
      detail: request
        ? compactMiddle(request, 180)
        : t.liveToolTimeline.modelOrganizingNextStep,
    };
  }

  if (event.name === "turn_request") {
    return {
      label: t.liveToolTimeline.understandTask,
      detail: t.liveToolTimeline.readingUserRequirements,
    };
  }

  if (event.name === "stream_connection") {
    return {
      label: t.liveToolTimeline.connectRuntime,
      detail: t.liveToolTimeline.establishingCallbackChannel,
    };
  }

  if (event.name === "response_stream") {
    return {
      label: t.liveToolTimeline.renderingModelOutput,
      detail: t.liveToolTimeline.incrementalTextReceived,
    };
  }

  if (event.name === "model_gateway") {
    const seconds = elapsedSeconds(event.input);
    if (event.status === "running") {
      return {
        label: actionStatusLabel(event, t.liveToolTimeline.planningNextStep),
        detail:
          seconds > 0
            ? t.liveToolTimeline.modelOrganizingNextStepWithWait(seconds)
            : t.liveToolTimeline.modelOrganizingNextStep,
      };
    }
    if (event.status === "error") {
      return {
        label: t.liveToolTimeline.modelOutputIncomplete,
        detail: t.liveToolTimeline.providerRejected,
      };
    }
    return {
      label: t.liveToolTimeline.modelOutputReceived,
      detail: t.liveToolTimeline.modelStartedReturning,
    };
  }

  const path = stringInput(event.input, [
    "path",
    "file_path",
    "target_path",
    "cwd",
  ]);
  const command = stringInput(event.input, ["command", "cmd", "script"]);
  const pattern = stringInput(event.input, ["pattern", "query"]);
  const description = stringInput(event.input, ["description", "summary"]);
  const lineStart = stringInput(event.input, [
    "line_start",
    "start_line",
    "start",
  ]);
  const lineEnd = stringInput(event.input, ["line_end", "end_line", "end"]);
  const lineSuffix =
    lineStart && lineEnd
      ? ` (lines ${lineStart}-${lineEnd})`
      : lineStart
        ? ` (line ${lineStart})`
        : "";

  if (event.name === "read_file" || event.name === "read_text_file") {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.readingFile,
        `${compactMiddle(path || "file")}${lineSuffix}`,
      ),
      detail: path ? undefined : t.liveToolTimeline.readFileToUnderstand,
    };
  }

  if (event.name === "list_cwd") {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.browsingDirectory,
        compactMiddle(path || "."),
      ),
      detail: t.liveToolTimeline.viewDirectoryStructure,
    };
  }

  if (event.name === "glob") {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.searchingFiles,
        compactMiddle(pattern || path || "*"),
      ),
      detail: path ? t.liveToolTimeline.scopePath(path) : undefined,
    };
  }

  if (event.name === "grep") {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.searchingText,
        compactMiddle(pattern || "pattern"),
      ),
      detail: path ? t.liveToolTimeline.scopePath(path) : undefined,
    };
  }

  if (
    event.name === "bash" ||
    event.name === "exec_shell" ||
    event.name === "shell_command"
  ) {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.runningCommand,
        compactMiddle(description || command || "command"),
      ),
      detail: command && description ? command : undefined,
    };
  }

  if (
    event.name === "write_file" ||
    event.name === "write_text_file" ||
    event.name === "create_file"
  ) {
    const creating = event.name === "create_file";
    return {
      label: actionStatusLabel(
        event,
        creating
          ? t.liveToolTimeline.creatingFile
          : t.liveToolTimeline.writingFile,
        compactMiddle(path || "file"),
      ),
      detail: t.liveToolTimeline.writeFileContent,
    };
  }

  if (
    event.name === "edit_code" ||
    event.name === "edit_text_file" ||
    event.name === "str_replace"
  ) {
    return {
      label: actionStatusLabel(
        event,
        t.liveToolTimeline.editingFile,
        compactMiddle(path || "file"),
      ),
      detail: pattern
        ? t.liveToolTimeline.matchPattern(compactMiddle(pattern))
        : undefined,
    };
  }

  if (event.name === "git_status") {
    return {
      label: actionStatusLabel(event, t.liveToolTimeline.readingGitStatus),
    };
  }
  if (event.name === "git_diff") {
    return {
      label: actionStatusLabel(event, t.liveToolTimeline.readingGitDiff),
    };
  }
  if (event.name === "git_commit") {
    return {
      label: actionStatusLabel(event, t.liveToolTimeline.committingGit),
    };
  }

  return null;
}

const CONTENT_PREVIEW_KEYS = [
  "content",
  "text",
  "code",
  "body",
  "patch",
  "diff",
] as const;

function normalizePreviewText(value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  const lines = trimmed.split(/\r?\n/);
  const preview = lines.slice(0, 8).join("\n");
  const tooLong = lines.length > 8 || preview.length > 900;
  return `${preview.slice(0, 900)}${tooLong ? "\n..." : ""}`;
}

function getContentPreviewFromRecord(
  record?: Record<string, unknown>,
): string | undefined {
  if (!record) return undefined;
  for (const key of CONTENT_PREVIEW_KEYS) {
    const preview = normalizePreviewText(record[key]);
    if (preview) return preview;
  }
  return undefined;
}

function getContentPreview(event: LiveToolEvent): string | undefined {
  const inputPreview = getContentPreviewFromRecord(event.input);
  if (inputPreview) return inputPreview;
  if (
    typeof event.output === "object" &&
    event.output !== null &&
    !Array.isArray(event.output)
  ) {
    return getContentPreviewFromRecord(event.output as Record<string, unknown>);
  }
  return undefined;
}

function researchAdjustmentSummary(
  event: LiveToolEvent,
  t: TimelineT,
): string | undefined {
  if (event.name !== "web_search") return undefined;
  if (event.status === "running") {
    return t.liveToolTimeline.collectingEvidence;
  }
  if (event.status === "error") {
    return t.liveToolTimeline.searchRoundFailed;
  }
  const query = typeof event.input?.query === "string" ? event.input.query : "";
  if (/规模|增[长長]|CAGR|market size|forecast/i.test(query)) {
    return t.liveToolTimeline.marketSizeLeads;
  }
  if (
    /品牌|竞争|格局|company|companies|Oura|Eight Sleep|床垫|床墊/i.test(query)
  ) {
    return t.liveToolTimeline.competitionLeads;
  }
  if (/技术|technology|AI|sensor|wearable|产品|product/i.test(query)) {
    return t.liveToolTimeline.technologyLeads;
  }
  if (/消费|需求|痛点|睡眠经济|consumer|demand|pain/i.test(query)) {
    return t.liveToolTimeline.demandLeads;
  }
  return t.liveToolTimeline.roundResultsRead;
}

function statusText(event: LiveToolEvent, t: TimelineT): string {
  switch (event.status) {
    case "running":
      return t.liveToolTimeline.statusRunning;
    case "done":
      return t.liveToolTimeline.statusDone;
    case "error":
      return t.liveToolTimeline.statusFailed;
    case "waiting_approval":
      return t.liveToolTimeline.statusWaitingApproval;
    default:
      return "";
  }
}

function statusClassName(status: LiveToolEvent["status"]): string {
  return agentRunBadgeClass(status);
}

function detailTitle(
  t: TimelineT,
  key:
    | "input"
    | "thought"
    | "publicReasoning"
    | "result"
    | "observation"
    | "preview",
): string {
  return t.liveToolTimeline.detailTitles[key];
}

function InlineSummaryRow({
  label,
  value,
  tone = "muted",
}: {
  label: string;
  value: string;
  tone?: "muted" | "result";
}) {
  return (
    <div
      className={cn(
        "mt-1 ml-5 flex min-w-0 items-start gap-2 border-l pl-2 text-[10px] leading-4",
        tone === "result"
          ? "border-emerald-500/25 text-emerald-700/85 dark:text-emerald-400/85"
          : "border-border/50 text-muted-foreground/85",
      )}
    >
      <span className="shrink-0 rounded-sm bg-muted/60 px-1.5 py-0.5 font-medium text-muted-foreground">
        {label}
      </span>
      <span className="min-w-0 break-words line-clamp-2">{value}</span>
    </div>
  );
}

function ToolEventRow({
  event,
  toolLabels,
  t,
  showAgent,
  nested,
}: {
  event: LiveToolEvent;
  toolLabels: Record<string, string>;
  t: TimelineT;
  showAgent?: boolean;
  nested?: boolean;
}) {
  // Tool names carry suffixes the icon map doesn't (grep_text→grep,
  // glob_files→glob) — fall back to the normalized base before the generic
  // icon so search/file/shell steps stay visually distinct.
  const iconCfg = TOOL_ICONS[event.name] ??
    TOOL_ICONS[event.name.toLowerCase().replace(/_text/g, "")] ??
    TOOL_ICONS[event.name.toLowerCase().replace(/_files?$/, "")] ?? {
      icon: TerminalIcon,
      color: "text-muted-foreground",
    };
  const label = toolLabels[event.name] ?? event.name;
  const Icon = iconCfg.icon;
  const modelReasoningOutput = (() => {
    if (event.name !== "model_reasoning") return undefined;
    const outputRecord = asRecord(event.output);
    if (typeof outputRecord?.content === "string") return outputRecord.content;
    return typeof event.output === "string" ? event.output : undefined;
  })();
  const isSystemWorkLogEvent =
    event.name === "turn_request" ||
    event.name === "stream_connection" ||
    event.name === "response_stream" ||
    event.name === "model_gateway" ||
    event.name === "model_reasoning";
  const inputSummary = formatInputSummary(event.input);
  const outputSummary = formatOutputSummary(event.output);
  const inputDetail = isSystemWorkLogEvent
    ? undefined
    : formatDetailBlock(event.input);
  const outputDetail =
    event.name === "model_reasoning"
      ? modelReasoningOutput
      : isSystemWorkLogEvent
        ? undefined
        : formatDetailBlock(event.output);
  const thoughtDetail = formatDetailBlock(event.thought);
  const observationDetail = formatDetailBlock(event.observation);
  const contentPreview = isSystemWorkLogEvent
    ? undefined
    : getContentPreview(event);
  const researchSummary = researchAdjustmentSummary(event, t);
  const researchLog = researchLogText(event, t);
  const searchResults =
    event.name === "web_search" && event.status !== "running"
      ? extractSearchResults(event.output)
      : [];
  const swarmLog = researchLog ? null : swarmLogText(event, t);
  const codeLog = researchLog || swarmLog ? null : codeLogText(event, t);
  const [open, setOpen] = useState(
    event.status === "running" || event.status === "error",
  );
  const inlineInputSummary =
    inputSummary &&
    !researchLog &&
    !isSystemWorkLogEvent &&
    inputSummary !== codeLog?.detail
      ? inputSummary
      : undefined;
  const inlineOutputSummary =
    outputSummary &&
    !researchLog &&
    !isSystemWorkLogEvent &&
    event.status !== "running"
      ? outputSummary
      : undefined;
  const hasDetails = Boolean(
    inputDetail ||
    outputDetail ||
    thoughtDetail ||
    observationDetail ||
    contentPreview,
  );

  return (
    <div
      className={cn(
        "group relative rounded-md px-2 py-1 transition-all duration-200 hover:bg-accent/40",
        nested ? "text-[11px]" : "text-xs",
        event.status === "error"
          ? "text-muted-foreground"
          : "text-muted-foreground",
      )}
    >
      <div className="flex items-center gap-2">
        {event.status === "running" ? (
          <span className="relative shrink-0">
            <Loader2Icon className="size-3.5 animate-spin text-emerald-600 dark:text-emerald-400" />
            <span className="absolute -inset-1 animate-ping rounded-full bg-emerald-500/20" />
          </span>
        ) : event.status === "waiting_approval" ? (
          <span className="relative shrink-0">
            <ShieldAlertIcon className="size-3.5 text-amber-500" />
            <span className="absolute -inset-1 animate-pulse rounded-full bg-amber-500/20" />
          </span>
        ) : event.status === "error" ? (
          <XCircleIcon className="size-3.5 shrink-0 text-destructive" />
        ) : (
          <CheckCircle2Icon className="size-3.5 text-emerald-500 shrink-0" />
        )}

        <Icon className={cn("size-3.5 shrink-0", iconCfg.color)} />
        <span className="min-w-0 truncate text-sm font-medium text-foreground">
          {researchLog?.label ?? swarmLog?.label ?? codeLog?.label ?? label}
        </span>

        {showAgent && event.agentName && (
          <span className="text-muted-foreground text-[10px]">
            · {event.agentName}
          </span>
        )}

        {researchLog?.sources && researchLog.sources.length > 0 && (
          <span className="flex min-w-0 items-center gap-1">
            {researchLog.sources.slice(0, 3).map((source) => (
              <span
                key={source}
                className="max-w-20 truncate rounded-full border border-border/60 bg-background/80 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                title={source}
              >
                {source}
              </span>
            ))}
          </span>
        )}

        <span className="ml-auto flex items-center gap-1">
          <span
            className={cn(
              "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
              agentRunStatusLightPulseClass(event.status) ?? "",
              statusClassName(event.status),
            )}
          >
            {statusText(event, t)}
          </span>

          {event.status === "done" && event.durationMs != null && event.durationMs >= 1 && (
            <span className="text-muted-foreground text-[10px]">
              {event.durationMs < 1000
                ? `${event.durationMs}ms`
                : `${(event.durationMs / 1000).toFixed(1)}s`}
            </span>
          )}

          {hasDetails && (
            <button
              type="button"
              className="flex size-5 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
              onClick={() => setOpen((value) => !value)}
              aria-label={
                open
                  ? t.liveToolTimeline.collapseToolDetails
                  : t.liveToolTimeline.expandToolDetails
              }
              title={
                open
                  ? t.liveToolTimeline.collapseToolDetails
                  : t.liveToolTimeline.expandToolDetails
              }
            >
              <ChevronDownIcon
                className={cn(
                  "size-3.5 transition-transform",
                  open ? "rotate-180" : "rotate-0",
                )}
              />
            </button>
          )}
        </span>
      </div>

      {researchLog?.detail && (
        <div className="mt-2 ml-5 border-l border-border/60 pl-3 text-sm leading-6 text-foreground/80">
          {researchLog.detail}
        </div>
      )}

      {searchResults.length > 0 && (
        <SearchResultsInline results={searchResults} t={t} />
      )}

      {swarmLog?.detail && (
        <div className="mt-2 ml-5 border-l border-primary/25 pl-3 text-sm leading-6 text-foreground/80 transition-all duration-200">
          {swarmLog.detail}
        </div>
      )}

      {codeLog?.detail && (
        <div className="mt-1 ml-5 break-words border-l border-border/60 pl-3 text-sm leading-6 text-foreground/75">
          {codeLog.detail}
        </div>
      )}

      {thoughtDetail && event.name !== "agent_thought" && (
        <div className="mt-1 ml-5 border-l border-violet-500/25 pl-2 text-[11px] leading-5 text-violet-700 dark:text-violet-300">
          <span className="font-medium">{detailTitle(t, "thought")}: </span>
          {compactMiddle(thoughtDetail, 260)}
        </div>
      )}

      {observationDetail && (
        <div className="mt-1 ml-5 border-l border-emerald-500/25 pl-2 text-[11px] leading-5 text-emerald-700 dark:text-emerald-300">
          <span className="font-medium">{detailTitle(t, "observation")}: </span>
          {compactMiddle(observationDetail, 260)}
        </div>
      )}

      {inlineInputSummary && (
        <InlineSummaryRow
          label={t.liveToolTimeline.detailTitles.input}
          value={inlineInputSummary}
        />
      )}

      {inlineOutputSummary && (
        <InlineSummaryRow
          label={t.liveToolTimeline.detailTitles.result}
          value={inlineOutputSummary}
          tone="result"
        />
      )}

      {researchSummary && !researchLog && (
        <div className="mt-1 ml-5 border-l border-sky-500/25 pl-2 text-[10px] leading-4 text-sky-700 dark:text-sky-300">
          {researchSummary}
        </div>
      )}

      {open && inputDetail && (
        <div className="mt-2 ml-5 overflow-hidden border-l border-border/55 pl-2">
          <div className="pb-1 text-[10px] font-medium text-muted-foreground">
            {detailTitle(t, "input")}
          </div>
          <pre className="max-h-44 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/35 px-2 py-1.5 font-mono text-[10px] leading-4 text-foreground/80">
            {inputDetail}
          </pre>
        </div>
      )}

      {open && thoughtDetail && (
        <div className="mt-2 ml-5 overflow-hidden border-l border-violet-500/25 pl-2">
          <div className="pb-1 text-[10px] font-medium text-muted-foreground">
            {detailTitle(t, "thought")}
          </div>
          <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-md bg-violet-500/5 px-2 py-1.5 font-mono text-[10px] leading-4 text-foreground/80">
            {thoughtDetail}
          </pre>
        </div>
      )}

      {open &&
        outputDetail &&
        (event.status !== "running" || event.name === "model_reasoning") && (
          <div className="mt-2 ml-5 overflow-hidden border-l border-emerald-500/25 pl-2">
            <div className="pb-1 text-[10px] font-medium text-muted-foreground">
              {event.name === "model_reasoning"
                ? detailTitle(t, "publicReasoning")
                : detailTitle(t, "result")}
            </div>
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-md bg-emerald-500/5 px-2 py-1.5 font-mono text-[10px] leading-4 text-foreground/80">
              {outputDetail}
            </pre>
          </div>
        )}

      {open && observationDetail && (
        <div className="mt-2 ml-5 overflow-hidden border-l border-emerald-500/25 pl-2">
          <div className="pb-1 text-[10px] font-medium text-muted-foreground">
            {detailTitle(t, "observation")}
          </div>
          <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words rounded-md bg-emerald-500/5 px-2 py-1.5 font-mono text-[10px] leading-4 text-foreground/80">
            {observationDetail}
          </pre>
        </div>
      )}

      {open && contentPreview && (
        <div className="mt-2 ml-5 overflow-hidden border-l border-border/55 pl-2">
          <div className="pb-1 text-[10px] font-medium text-muted-foreground">
            {detailTitle(t, "preview")}
          </div>
          <pre className="max-h-36 overflow-hidden whitespace-pre-wrap break-words py-1 font-mono text-[10px] leading-4 text-foreground/80">
            {contentPreview}
          </pre>
        </div>
      )}
    </div>
  );
}

function SearchResultsInline({
  results,
  t,
}: {
  results: SearchResultItem[];
  t: TimelineT;
}) {
  const [expanded, setExpanded] = useState(false);
  const collapsedCount = 5;
  const visibleResults = expanded ? results : results.slice(0, collapsedCount);
  const hiddenCount = Math.max(0, results.length - visibleResults.length);
  return (
    <div className="mt-2 ml-5 space-y-1 border-l border-border/60 pl-3">
      {visibleResults.map((result, index) => (
        <div
          key={`${result.url ?? result.title}-${index}`}
          className="flex min-w-0 items-start gap-2 text-xs leading-5 text-muted-foreground"
        >
          <span className="w-4 shrink-0 text-right font-mono text-[10px] text-muted-foreground/70">
            {index + 1}
          </span>
          {result.url ? (
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer"
              className="min-w-0 truncate text-foreground/75 underline-offset-2 hover:text-foreground hover:underline"
              title={result.title}
            >
              {result.title}
            </a>
          ) : (
            <span
              className="min-w-0 truncate text-foreground/75"
              title={result.title}
            >
              {result.title}
            </span>
          )}
        </div>
      ))}
      {hiddenCount > 0 && (
        <button
          type="button"
          className="mt-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
          onClick={() => setExpanded(true)}
        >
          <ChevronDownIcon className="size-3" />
          {t.liveToolTimeline.showMoreResults(hiddenCount)}
        </button>
      )}
      {expanded && results.length > collapsedCount && (
        <button
          type="button"
          className="mt-1 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
          onClick={() => setExpanded(false)}
        >
          <ChevronDownIcon className="size-3 rotate-180" />
          {t.liveToolTimeline.collapseResults}
        </button>
      )}
    </div>
  );
}

function GroupedTimeline({
  events,
  allEvents,
  toolLabels,
  t,
  className,
}: {
  events: LiveToolEvent[];
  allEvents: LiveToolEvent[];
  toolLabels: Record<string, string>;
  t: TimelineT;
  className?: string;
}) {
  const grouped = useMemo(() => {
    const map = new Map<string, { name: string; events: LiveToolEvent[] }>();
    for (const e of events) {
      const key = timelineAgentGroupId(e) ?? "__main__";
      if (!map.has(key)) {
        map.set(key, {
          name: e.subagentCodename ?? e.agentName ?? e.subAgentRole ?? key,
          events: [],
        });
      }
      map.get(key)!.events.push(e);
    }
    return Array.from(map.entries());
  }, [events]);

  return (
    <div className={cn("space-y-3 py-1.5", className)}>
      {grouped.map(([agentId, group]) => (
        <div key={agentId}>
          {agentId !== "__main__" && (
            <button
              type="button"
              onClick={() => emitAgentWorkbenchFocus({ agentId })}
              className="mb-1 flex w-full items-center gap-1.5 rounded-md px-3 py-1 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground transition-colors hover:bg-muted/45 hover:text-foreground"
            >
              <span className="size-1.5 rounded-lg bg-primary animate-pulse" />
              {group.name}
            </button>
          )}
          <div className="space-y-1">
            {group.events.map((item) => (
              <ParentWithChildren
                key={item.id}
                event={item}
                allEvents={allEvents}
                toolLabels={toolLabels}
                t={t}
                showAgent={agentId === "__main__" && !!item.agentName}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function timelineAgentGroupId(event: LiveToolEvent): string | undefined {
  if (event.parentToolUseId && event.subAgentRole) {
    return `${event.parentToolUseId}:${event.subAgentRole}`;
  }
  return (
    event.agentId ??
    event.subagentCodename ??
    event.subAgentRole ??
    event.agentName
  );
}
