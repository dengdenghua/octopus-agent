import { swallow } from "@/core/utils/log";
import type { LiveToolEvent } from "./live-tool-timeline";

export type WorkBlockKind =
  | "agent"
  | "browser"
  | "file"
  | "read"
  | "search"
  | "skill"
  | "swarm"
  | "terminal"
  | "todo";

export interface WorkBlock {
  id: string;
  event: LiveToolEvent;
  kind: WorkBlockKind;
  actionLabel: string;
  target: string;
  title: string;
  subtitle: string;
  status: WorkBlockStatus;
  startedAt: number;
  inputText: string;
  outputText: string;
}

export type WorkBlockStatus = LiveToolEvent["status"] | "warning";

export type WorkBlockStatusLabels = Partial<
  Record<WorkBlockStatus, string>
>;

export interface SettledRunDisplayOptions {
  hasAnswer?: boolean;
  runSettled?: boolean;
  runFailed?: boolean;
  paused?: boolean;
}

const LOW_LEVEL_EVENTS = new Set([
  "turn_request",
  "stream_connection",
  "response_stream",
  "model_gateway",
  "model_reasoning",
]);

export function toWorkBlocks(events: LiveToolEvent[]): WorkBlock[] {
  return coalesceWorkEvents(events)
    .filter(isVisibleWorkEvent)
    .sort((a, b) => a.startedAt - b.startedAt)
    .map(toWorkBlock);
}

function coalesceWorkEvents(events: LiveToolEvent[]): LiveToolEvent[] {
  const byId = new Map<string, LiveToolEvent>();
  for (const event of events) {
    const previous = byId.get(event.id);
    if (!previous) {
      byId.set(event.id, event);
      continue;
    }
    byId.set(event.id, {
      ...previous,
      ...event,
      input: event.input ?? previous.input,
      output: event.output ?? previous.output,
      startedAt: Math.min(previous.startedAt, event.startedAt),
      finishedAt: event.finishedAt ?? previous.finishedAt,
      durationMs: event.durationMs ?? previous.durationMs,
    });
  }
  return [...byId.values()];
}

export function normalizeEventsForSettledDisplay(
  events: LiveToolEvent[],
  options: SettledRunDisplayOptions = {},
): LiveToolEvent[] {
  if (
    !options.runSettled ||
    options.runFailed ||
    options.paused ||
    !options.hasAnswer
  ) {
    return events;
  }
  return events.map((event) => {
    if (event.status !== "running" && event.status !== "waiting_approval") {
      return event;
    }
    return {
      ...event,
      status: "done",
      finishedAt: event.finishedAt ?? event.startedAt,
      durationMs: event.durationMs ?? 0,
    };
  });
}

export function pickCurrentWorkBlock(blocks: WorkBlock[]): WorkBlock | null {
  return (
    [...blocks]
      .reverse()
      .find(
        (block) =>
          block.status === "running" || block.status === "waiting_approval",
      ) ??
    blocks[blocks.length - 1] ??
    null
  );
}

export function progressForWorkBlocks(blocks: WorkBlock[], current: WorkBlock) {
  const selectedIndex = Math.max(
    0,
    blocks.findIndex((block) => block.id === current.id),
  );
  const terminal = blocks.filter(
    (block) =>
      block.status === "done" ||
      block.status === "warning" ||
      block.status === "error",
  ).length;
  const currentIndex = Math.max(
    1,
    Math.min(blocks.length, Math.max(terminal, selectedIndex + 1)),
  );
  return { current: currentIndex, total: blocks.length };
}

export function isWorkRunning(blocks: WorkBlock[]): boolean {
  return blocks.some(
    (block) =>
      block.status === "running" || block.status === "waiting_approval",
  );
}

export function statusText(
  status: WorkBlockStatus,
  labels?: WorkBlockStatusLabels,
): string {
  const fallback: Record<WorkBlockStatus, string> = {
    running: "正在执行",
    waiting_approval: "等待确认",
    warning: "已恢复",
    error: "执行失败",
    done: "已完成",
  };
  return labels?.[status] || fallback[status];
}

function toWorkBlock(event: LiveToolEvent): WorkBlock {
  const kind = workKind(event.name);
  const status = workBlockStatus(event);
  const actionLabel = workActionLabel(event, kind, status);
  const target = workTarget(event, kind);
  const title = workTitle(event, kind, actionLabel, target);
  const subtitle = workSubtitle(event, target);
  return {
    id: event.id,
    event,
    kind,
    actionLabel,
    target,
    title,
    subtitle,
    status,
    startedAt: event.startedAt,
    inputText: detailText(event.input),
    outputText: detailText(event.output),
  };
}

function workBlockStatus(event: LiveToolEvent): WorkBlockStatus {
  if (event.status === "error" && isManualVerificationRequiredEvent(event)) {
    return "waiting_approval";
  }
  if (event.status === "error" && isRecoverableToolFailureEvent(event)) {
    return "warning";
  }
  return event.status;
}

function isVisibleWorkEvent(event: LiveToolEvent): boolean {
  if (
    event.parentToolUseId &&
    !event.agentId &&
    !event.agentName &&
    !event.subAgentRole &&
    !event.lifecycle
  ) {
    return false;
  }
  if (LOW_LEVEL_EVENTS.has(event.name)) return false;
  return true;
}

function workKind(name: string): WorkBlockKind {
  if (name === "call_agent_parallel") return "swarm";
  if (name === "todo_write") return "todo";
  if (
    /skill|deep-research|report-writing|docx|pptx-swarm|webapp-building-swarm/i.test(
      name,
    )
  )
    return "skill";
  if (/shell|bash|terminal|cmd|exec|python/i.test(name)) return "terminal";
  if (/fetch|browser|url|web/i.test(name)) return "browser";
  if (/search|grep|glob|list/i.test(name)) return "search";
  if (/read/i.test(name)) return "read";
  if (/(write|edit|replace|create|artifact)/i.test(name)) return "file";
  return "agent";
}

function workTitle(
  event: LiveToolEvent,
  kind: WorkBlockKind,
  actionLabel: string,
  target: string,
): string {
  if (isManualVerificationRequiredEvent(event)) {
    return "等待验证";
  }
  if (event.lifecycle === "spawned" || /subagent_spawned/i.test(event.name)) {
    return `创建助手 ${agentDisplayName(event)}`;
  }
  if (event.lifecycle === "finished" || /subagent_finished/i.test(event.name)) {
    return `助手完成 ${agentDisplayName(event)}`;
  }
  if (event.name === "todo_write") {
    return actionLabel;
  }
  if (event.name === "call_agent_parallel") {
    const count = specCount(event.input);
    return count > 0 ? `并行分派 ${count} 个子任务` : "并行分派子任务";
  }
  if (kind === "skill") {
    return skillTitle(event);
  }
  const progressLabel = progressLabelText(event);
  if (event.name.startsWith("mcp:") && progressLabel) {
    return compact(progressLabel, 64);
  }
  if (target) return `${actionLabel} ${compact(target, 48)}`;
  if (event.name === "model_gateway") return "连接模型";
  return actionLabel || event.name.replace(/[_-]+/g, " ");
}

function workSubtitle(event: LiveToolEvent, fallbackTarget: string): string {
  if (isManualVerificationRequiredEvent(event)) {
    return statusText(workBlockStatus(event));
  }
  const progress = progressSubtitleText(event);
  if (progress) return compact(progress, 88);
  if (event.name === "todo_write") {
    return todoTitle(event.input) || statusText(workBlockStatus(event));
  }
  const inputTarget = firstString(event.input, [
    "path",
    "file_path",
    "filepath",
    "url",
    "query",
    "pattern",
    "cwd",
  ]);
  if (inputTarget) return compact(publicInputTarget(inputTarget, event), 88);
  if (fallbackTarget) return compact(fallbackTarget, 88);
  if (event.agentName) return event.agentName;
  return statusText(workBlockStatus(event));
}

function workActionLabel(
  event: LiveToolEvent,
  kind: WorkBlockKind,
  status: WorkBlockStatus,
): string {
  if (isManualVerificationRequiredEvent(event)) return "等待验证";
  if (event.lifecycle === "spawned" || /subagent_spawned/i.test(event.name)) {
    return "创建助手";
  }
  if (event.lifecycle === "finished" || /subagent_finished/i.test(event.name)) {
    return "助手完成";
  }
  if (event.name === "todo_write") return "编写待办清单";
  if (event.name === "call_agent_parallel") return "并行分派";
  if (kind === "skill") return "加载技能";
  if (kind === "terminal") {
    if (status === "error") return "终端运行失败";
    if (status === "warning") return "终端已恢复";
    return "运行终端";
  }
  if (kind === "read") return "阅读";
  if (kind === "file") return fileActionLabel(event);
  if (kind === "browser") return "浏览";
  if (kind === "search") return "搜索";
  if (kind === "swarm") return "并行分派";
  return "执行";
}

function fileActionLabel(event: LiveToolEvent): string {
  const op =
    firstString(event.input, ["op", "operation", "action"]) ||
    firstChangeString(event.input, ["op", "operation", "action"]);
  if (/add|create|new|generate|write/i.test(op)) return "创建文件";
  if (/delete|remove/i.test(op)) return "删除文件";
  return "编辑";
}

function workTarget(event: LiveToolEvent, kind: WorkBlockKind): string {
  if (event.lifecycle === "spawned" || /subagent_spawned/i.test(event.name)) {
    return agentDisplayName(event);
  }
  if (event.lifecycle === "finished" || /subagent_finished/i.test(event.name)) {
    return agentDisplayName(event);
  }
  if (event.name === "todo_write") return "";
  if (event.name === "call_agent_parallel") {
    const count = specCount(event.input);
    return count > 0 ? `${count} 个子任务` : "子任务";
  }
  if (kind === "skill") {
    return firstString(event.input, ["skill", "skill_name", "name"]);
  }
  const path =
    firstChangeString(event.input, ["path", "file_path", "filepath"]) ||
    firstString(event.input, ["path", "file_path", "filepath", "filename"]);
  const url = firstString(event.input, ["url"]);
  const query = firstString(event.input, ["query", "pattern"]);
  const commandSummary = firstString(event.input, [
    "description",
    "label",
    "title",
  ]);
  if ((kind === "read" || kind === "file") && path) return basename(path);
  if (kind === "browser" && url) return hostOf(url);
  if (kind === "search" && query) return compact(query, 48);
  if (kind === "terminal" && commandSummary) return compact(commandSummary, 48);
  return "";
}

function publicInputTarget(value: string, event: LiveToolEvent): string {
  const kind = workKind(event.name);
  if (kind === "browser") return hostOf(value);
  if (kind === "read" || kind === "file") return basename(value);
  if (kind === "terminal" && /[\\/]/.test(value)) return basename(value);
  return value;
}

function isManualVerificationRequiredEvent(event: LiveToolEvent): boolean {
  const normalizedName = event.name.trim().toLowerCase();
  if (
    !(
      normalizedName === "verification:manual" ||
      normalizedName.endsWith(":verification:manual")
    )
  ) {
    return false;
  }
  const command = firstString(event.input, ["command"]);
  const output = detailText(event.output);
  return /verification required|no verification step|Code changes were produced/i.test(
    `${command}\n${output}`,
  );
}

function isRecoverableToolFailureEvent(event: LiveToolEvent): boolean {
  const haystack = `${event.name}\n${detailText(event.input)}\n${detailText(
    event.output,
  )}`;
  return /工具失败|status=failed\s+error=TypeError|换一种方式重试|tool failed|tool_error|No such tool|不存在的工具/i.test(
    haystack,
  );
}

function agentDisplayName(event: LiveToolEvent): string {
  return (
    event.subagentCodename ||
    event.agentName ||
    event.subAgentRole ||
    event.agentId ||
    "子智能体"
  );
}

function progressRecord(event: LiveToolEvent): Record<string, unknown> | null {
  const progress = event.input?.progress;
  if (!progress || typeof progress !== "object" || Array.isArray(progress)) {
    return null;
  }
  return progress as Record<string, unknown>;
}

function progressLabelText(event: LiveToolEvent): string {
  return firstString(progressRecord(event) ?? undefined, ["label"]);
}

function progressSubtitleText(event: LiveToolEvent): string {
  const progress = progressRecord(event);
  if (!progress) return "";
  const label = progressLabelText(event);
  const metric = progressMetricText(progress);
  if (event.name.startsWith("mcp:") && label) return metric || label;
  if (label && metric) return `${label} · ${metric}`;
  return label || metric;
}

function progressMetricText(progress: Record<string, unknown>): string {
  const percent = numberValue(progress.percent);
  if (percent !== null) {
    const normalized = percent > 0 && percent <= 1 ? percent * 100 : percent;
    return `${Math.round(normalized)}%`;
  }
  const current = numberValue(progress.current);
  const total = numberValue(progress.total);
  if (current !== null && total !== null) return `${current}/${total}`;
  if (current !== null) return String(current);
  return "";
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function specCount(input: Record<string, unknown> | undefined): number {
  const specs = input?.specs;
  return Array.isArray(specs) ? specs.length : 0;
}

function skillTitle(event: LiveToolEvent): string {
  const skill =
    firstString(event.input, ["skill", "skill_name", "name"]) || event.name;
  if (skill === "deep-research-swarm" || event.name === "deep-research-swarm") {
    return "加载深度调研集群技能";
  }
  if (skill === "report-writing" || event.name === "report-writing") {
    return "加载报告写作技能";
  }
  if (skill === "docx" || event.name === "docx") {
    return "组装 DOCX 交付物";
  }
  return `加载技能 ${compact(skill, 48)}`;
}

function todoTitle(input: Record<string, unknown> | undefined) {
  const raw = input?.items ?? input?.todos;
  const items = Array.isArray(raw) ? raw : [];
  const current =
    items.find(
      (item) =>
        typeof item === "object" &&
        item !== null &&
        (item as Record<string, unknown>).status === "in_progress",
    ) ??
    [...items]
      .reverse()
      .find((item) => typeof item === "object" && item !== null);
  if (!current || typeof current !== "object") return "";
  const record = current as Record<string, unknown>;
  const value =
    firstString(record, ["activeForm", "active_form"]) ||
    firstString(record, ["content", "text", "title", "task"]);
  return value ? compact(value, 64) : "";
}

function firstString(
  input: Record<string, unknown> | undefined,
  keys: string[],
) {
  if (!input) return "";
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
  }
  return "";
}

function firstChangeString(
  input: Record<string, unknown> | undefined,
  keys: string[],
) {
  const changes = input?.changes;
  if (!Array.isArray(changes)) return "";
  for (const change of changes) {
    if (!change || typeof change !== "object" || Array.isArray(change)) {
      continue;
    }
    const value = firstString(change as Record<string, unknown>, keys);
    if (value) return value;
  }
  return "";
}

function basename(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

function hostOf(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (e) {
    swallow(e);
    return compact(url, 42);
  }
}

function compact(value: string, max: number) {
  const clean = value.replace(/\s+/g, " ").trim();
  return clean.length <= max ? clean : `${clean.slice(0, max - 1)}...`;
}

function detailText(value: unknown): string {
  if (value === undefined || value === null) return "";
  const text =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return text.length > 16000 ? `${text.slice(0, 16000)}\n...` : text;
}
