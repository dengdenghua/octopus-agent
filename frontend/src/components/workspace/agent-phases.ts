import type { LiveToolEvent } from "./live-tool-timeline";
import { toWorkBlocks, type WorkBlock } from "./work-blocks";

export type AgentPhaseStatus = "pending" | "running" | "done" | "error";

export interface AgentPhase {
  id: string;
  title: string;
  detail?: string;
  status: AgentPhaseStatus;
  blockIds: string[];
}

type DeriveAgentPhasesOptions = {
  hasAnswer?: boolean;
  runSettled?: boolean;
  runFailed?: boolean;
  paused?: boolean;
};

export function deriveAgentPhases(
  events: LiveToolEvent[],
  options: DeriveAgentPhasesOptions = {},
): {
  blocks: WorkBlock[];
  phases: AgentPhase[];
  currentPhase: AgentPhase | null;
} {
  const blocks = toWorkBlocks(events);
  const phases =
    extractTodoPhases(events, blocks, options) ??
    buildGenericPhases(blocks, options);
  const normalizedPhases = normalizePhaseOrdering(phases);
  const currentPhase = pickCurrentPhase(normalizedPhases);
  return { blocks, phases: normalizedPhases, currentPhase };
}

export function progressForPhases(phases: AgentPhase[], current: AgentPhase) {
  const selectedIndex = Math.max(
    0,
    phases.findIndex((phase) => phase.id === current.id),
  );
  const terminal = phases.filter(
    (phase) => phase.status === "done" || phase.status === "error",
  ).length;
  const currentIndex = Math.max(
    1,
    Math.min(phases.length, Math.max(terminal, selectedIndex + 1)),
  );
  return { current: currentIndex, total: phases.length };
}

export function phaseStatusText(status: AgentPhaseStatus): string {
  if (status === "running") return "进行中";
  if (status === "error") return "异常";
  if (status === "done") return "已完成";
  return "待开始";
}

function pickCurrentPhase(phases: AgentPhase[]) {
  return (
    phases.find((phase) => phase.status === "running") ??
    phases.find((phase) => phase.status === "error") ??
    phases.find((phase) => phase.status === "pending") ??
    phases[phases.length - 1] ??
    null
  );
}

function extractTodoPhases(
  events: LiveToolEvent[],
  blocks: WorkBlock[],
  options: DeriveAgentPhasesOptions,
): AgentPhase[] | null {
  const todo = [...events]
    .reverse()
    .find((event) => event.name === "todo_write");
  const raw = todo?.input?.items ?? todo?.input?.todos;
  if (!Array.isArray(raw) || raw.length < 2) return null;

  const phases = raw
    .map((item, index): AgentPhase | null => {
      if (!item || typeof item !== "object") return null;
      const record = item as Record<string, unknown>;
      const title =
        firstString(record, ["activeForm", "active_form"]) ||
        firstString(record, ["content", "text", "title", "task"]);
      if (!title) return null;
      const status = normalizePhaseStatus(
        todoStatus(record.status),
        [],
        options,
      );
      const displayTitle =
        (options.runSettled || options.hasAnswer) && status === "done"
          ? title.replace(/^正在\s*/, "")
          : title;
      return {
        id: `todo-phase:${index}`,
        title: phaseTitle(displayTitle, index),
        status,
        blockIds:
          status === "running"
            ? blocks
                .filter((block) => block.status === "running")
                .map((block) => block.id)
            : [],
      };
    })
    .filter((phase): phase is AgentPhase => Boolean(phase));
  return markFailedTodoPhase(phases, options);
}

function buildGenericPhases(
  blocks: WorkBlock[],
  options: DeriveAgentPhasesOptions,
): AgentPhase[] {
  if (blocks.length === 0) return [];
  const buckets = [
    {
      id: "generic:prepare",
      title: "理解任务与准备上下文",
      blocks: blocks.filter((block) =>
        /read|recall|skill|agent/i.test(block.event.name),
      ),
    },
    {
      id: "generic:execute",
      title: "执行与收集证据",
      blocks: blocks.filter((block) =>
        /browser|search|web|fetch|terminal|shell|file/i.test(block.kind),
      ),
    },
    {
      id: "generic:deliver",
      title: "整理结果与交付",
      blocks: blocks.filter((block) =>
        /todo|write|report|artifact/i.test(
          `${block.event.name} ${block.kind} ${block.title}`,
        ),
      ),
    },
  ];
  return buckets
    .filter((bucket) => bucket.blocks.length > 0)
    .map((bucket, index) => ({
      id: bucket.id,
      title: phaseTitle(bucket.title, index),
      status: statusFromBlockList(bucket.blocks, options),
      blockIds: bucket.blocks.map((block) => block.id),
    }));
}

function statusFromBlockList(
  blocks: WorkBlock[],
  options: DeriveAgentPhasesOptions,
): AgentPhaseStatus {
  if (blocks.some((block) => block.status === "error")) return "error";
  if (
    options.runSettled &&
    blocks.some((block) => block.status === "waiting_approval") &&
    !blocks.some((block) => block.status === "running")
  ) {
    return "done";
  }
  if (
    blocks.some(
      (block) =>
        block.status === "running" || block.status === "waiting_approval",
    )
  ) {
    return "running";
  }
  return "done";
}

function normalizePhaseStatus(
  status: AgentPhaseStatus,
  blocks: WorkBlock[],
  options: DeriveAgentPhasesOptions,
): AgentPhaseStatus {
  if (options.paused) return status;
  if (!options.runSettled) return status;
  if (options.runFailed && status === "running") return "error";
  if (options.runFailed && status === "pending") return "pending";
  if (
    !options.runFailed &&
    options.hasAnswer &&
    (status === "running" || status === "pending")
  ) {
    return "done";
  }
  if (status === "pending") return "pending";
  if (status !== "running") return status;
  return blocks.length === 0 ||
    blocks.every((block) => block.status === "waiting_approval")
    ? "error"
    : status;
}

function markFailedTodoPhase(
  phases: AgentPhase[],
  options: DeriveAgentPhasesOptions,
): AgentPhase[] {
  if (
    options.paused ||
    !options.runSettled ||
    (options.hasAnswer && !options.runFailed)
  ) {
    return phases;
  }
  let marked = false;
  return phases.map((phase) => {
    if (phase.status === "done") return phase;
    if (!marked) {
      marked = true;
      return { ...phase, status: "error" };
    }
    return phase.status === "running" ? { ...phase, status: "pending" } : phase;
  });
}

function todoStatus(value: unknown): AgentPhaseStatus {
  if (value === "completed" || value === "done") return "done";
  if (value === "in_progress" || value === "running") return "running";
  if (value === "error" || value === "failed") return "error";
  return "pending";
}

function phaseTitle(title: string, index: number) {
  const clean = title.replace(/\s+/g, " ").trim();
  return /^phase\s+\d+/i.test(clean) ? clean : `Phase ${index + 1}: ${clean}`;
}

function normalizePhaseOrdering(phases: AgentPhase[]): AgentPhase[] {
  const currentIndex = phases.findIndex((phase) => phase.status === "running");
  if (currentIndex < 0) return phases;
  return phases.map((phase, index) =>
    index > currentIndex && phase.status === "running"
      ? { ...phase, status: "pending" }
      : phase,
  );
}

function firstString(input: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = input[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}
