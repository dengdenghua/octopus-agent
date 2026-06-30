import {
  BoxesIcon,
  FlagIcon,
  GitBranchIcon,
  MessageCircleIcon,
  type LucideIcon,
} from "lucide-react";
import { useMemo } from "react";

import { cn } from "@/lib/utils";

/**
 * How the team works on a turn:
 * - chat (单聊): one agent answers — @someone routes to them, else the leader.
 * - cluster (集群): the leader decomposes → dispatches → each role works → merges.
 * - swarm (蜂群): agents react to a shared blackboard, parallel & leaderless.
 * - project (项目): milestone-driven — handed to the Project OS to break into
 *   a task DAG, execute, and gate on acceptance.
 * The backend still auto-picks cluster vs swarm by graph shape when no explicit
 * pick is sent; choosing 集群/蜂群 forces that engine (serve_mesh "0"/"1").
 */
export type TeamMode = "chat" | "cluster" | "swarm" | "project";

export type LegacyTeamMode =
  | "cowork"
  | "group_chat"
  | "free"
  | "free_chat"
  | "debate"
  | "pipeline";

export function normalizeTeamMode(
  value: TeamMode | LegacyTeamMode | string | null | undefined,
): TeamMode {
  if (
    value === "cluster"
    || value === "swarm"
    || value === "chat"
    || value === "project"
  ) {
    return value;
  }
  // Legacy: the old single "cowork/group" auto-picked the engine — map it to
  // 集群 (the orchestrated default). Free/group_chat collapse to 单聊.
  if (value === "cowork" || value === "debate" || value === "pipeline") {
    return "cluster";
  }
  return "chat";
}

export const TEAM_MODE_META: Record<
  TeamMode,
  { label: string; description: string; icon: LucideIcon }
> = {
  chat: {
    label: "单聊",
    description: "一个 agent 接话 · @谁就他，不@默认队长",
    icon: MessageCircleIcon,
  },
  cluster: {
    label: "集群",
    description: "队长拆解 → 分派 → 各司其职 → 汇总（有分工、有中心）",
    icon: GitBranchIcon,
  },
  swarm: {
    label: "蜂群",
    description: "围一块黑板各自反应、并行涌现（无中心、自组织）",
    icon: BoxesIcon,
  },
  project: {
    label: "项目",
    description: "里程碑驱动 · 交给 Project OS 拆任务 → 执行 → 验收",
    icon: FlagIcon,
  },
};

export const TEAM_MODES: TeamMode[] = ["chat", "cluster", "swarm", "project"];

/** Per-turn engine force the backend reads (集群→sequential, 蜂群→mesh). */
export function serveMeshForMode(mode: TeamMode): "0" | "1" | undefined {
  if (mode === "cluster") return "0";
  if (mode === "swarm") return "1";
  return undefined;
}

export function TeamModePicker({
  value,
  onChange,
  className,
}: {
  value: TeamMode;
  onChange: (mode: TeamMode) => void;
  className?: string;
}) {
  const activeIndex = useMemo(
    () => Math.max(0, TEAM_MODES.indexOf(value)),
    [value],
  );
  const count = TEAM_MODES.length;

  return (
    <div
      className={cn(
        "relative flex items-center rounded-full bg-muted/50 p-[3px] ring-1 ring-border/20",
        className,
      )}
    >
      <div
        className="absolute top-[3px] bottom-[3px] rounded-full bg-background shadow-sm ring-1 ring-border/40 transition-all duration-300 ease-out"
        style={{
          left: `calc(${activeIndex} * (100% - 4px) / ${count} + 2px)`,
          width: `calc((100% - 4px) / ${count})`,
        }}
      />
      {TEAM_MODES.map((mode) => {
        const meta = TEAM_MODE_META[mode];
        const Icon = meta.icon;
        const active = value === mode;
        return (
          <button
            key={mode}
            type="button"
            onClick={() => onChange(mode)}
            className={cn(
              "relative z-10 flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium transition-colors duration-200",
              active
                ? "text-foreground"
                : "text-muted-foreground/60 hover:text-muted-foreground",
            )}
          >
            <Icon className="size-3.5" />
            {meta.label}
          </button>
        );
      })}
    </div>
  );
}

export function TeamModeDescription({
  mode,
  className,
}: {
  mode: TeamMode;
  className?: string;
}) {
  return (
    <p className={cn("text-muted-foreground text-xs", className)}>
      {TEAM_MODE_META[mode].description}
    </p>
  );
}
