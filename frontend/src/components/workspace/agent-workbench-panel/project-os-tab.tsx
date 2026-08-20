"use client";

/**
 * ProjectOSTab — 右侧工作台「项目」标签页。
 *
 * 在实时会话工作台里就地渲染当前线程绑定的 Project OS 项目驾驶舱：
 *   - 项目名 / 状态徽章 / PM 归属
 *   - 整体进度与里程碑健康度（紧凑列表）
 *   - PM 驾驶舱摘要（下一步动作、风险/阻塞）
 *   - 完工项目复盘
 *   - 快捷操作（Run / Tick / Recover / Inspect / Report）
 *
 * 数据与操作全部复用后端只读模型：GET /api/projects/by-thread/{threadId}
 * 一次返回 project + milestones + tasks + pm + retro + action_specs。
 */

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";

import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import {
  AlertTriangleIcon,
  ArrowRightIcon,
  ClipboardListIcon,
  ExternalLinkIcon,
  FlagIcon,
  ListChecksIcon,
  PlayIcon,
  RotateCcwIcon,
  UserRoundIcon,
} from "lucide-react";
import { toast } from "sonner";
import { Link } from "react-router-dom";

import { jsonAuthHeaders } from "@/core/auth/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

type Health = "on_track" | "at_risk" | "overdue" | "blocked" | "completed";

interface ActionSpec {
  action: string;
  label: string;
  api: { method: string; path: string; body?: Record<string, unknown> };
  realtime_command?: string;
}

interface MilestonePM {
  id: string;
  name: string;
  status: string;
  health: Health;
  priority: string;
  due_at: string;
  done: number;
  total: number;
  failed: number;
  progress: number;
}

interface PmeReport {
  project_id: string;
  name: string;
  status: string;
  overall_progress: number;
  done_tasks: number;
  total_tasks: number;
  remaining_estimate: number;
  milestones: MilestonePM[];
  risks: Array<{
    type: "milestone" | "task";
    health: string;
    detail: string;
  }>;
  blockers: string[];
  next_actions: Array<{
    milestone: string;
    task_id: string;
    task: string;
    priority: string;
    estimate: number;
    due_at: string;
  }>;
}

interface Retro {
  project_id: string;
  name: string;
  goal: string;
  status: string;
  milestone_count: number;
  task_count: number;
  done_tasks: number;
  failed_tasks: number;
  rejected_tasks: number;
  attempts_total: number;
  total_estimate: number;
  duration_days: number | null;
  blocked_milestones: string[];
  recommendations: string[];
}

export interface ProjectFullState {
  project: {
    id: string;
    name: string;
    goal: string;
    status: string;
    owner: string;
    created_at: string;
    started_at: string;
    finished_at: string;
  };
  milestones: Array<{
    id: string;
    name: string;
    status: string;
    priority: string;
    due_at: string;
  }>;
  tasks: Record<string, unknown[]>;
  pm: PmeReport | null;
  retro: Retro | null;
  available_actions: string[];
  action_specs: ActionSpec[];
}

const STATUS_LABEL: Record<string, string> = {
  planning: "规划中",
  running: "进行中",
  blocked: "已阻塞",
  done: "已完成",
  failed: "失败",
};

const STATUS_TONE: Record<string, string> = {
  planning: "bg-muted text-muted-foreground",
  running: "bg-emerald-500/15 text-emerald-600",
  blocked: "bg-rose-500/15 text-rose-600",
  done: "bg-sky-500/15 text-sky-600",
  failed: "bg-rose-500/15 text-rose-600",
};

const HEALTH_LABEL: Record<Health, string> = {
  on_track: "正常",
  at_risk: "有风险",
  overdue: "已逾期",
  blocked: "阻塞",
  completed: "完成",
};

const HEALTH_DOT: Record<Health, string> = {
  on_track: "bg-emerald-500",
  at_risk: "bg-amber-500",
  overdue: "bg-orange-500",
  blocked: "bg-rose-500",
  completed: "bg-sky-500",
};

const PRIORITY_TONE: Record<string, string> = {
  P0: "bg-rose-500/15 text-rose-600",
  P1: "bg-amber-500/15 text-amber-600",
};

function fmtDate(value: string | undefined | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function SectionLabel({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground/80">
      {icon}
      <span>{children}</span>
    </div>
  );
}



/**
 * useBoundProjectState — 拉取当前线程绑定的 Project OS 项目。
 * 404（未绑定项目）解析为 null，与「加载中」区分开：loading=true 时 tab
 * 不显示；有项目后才把「项目」标签加入工作台。
 */
export function useBoundProjectState(threadId: string | undefined | null) {
  return useQuery<ProjectFullState | null>({
    queryKey: ["project", "by-thread", threadId ?? ""],
    queryFn: async () => {
      const res = await fetch(
        `${getBackendBaseURL()}/api/projects/by-thread/${threadId}`,
        { headers: authHeaders() },
      );
      if (res.status === 404) return null;
      if (!res.ok) throw new Error(`Failed to load project: ${res.statusText}`);
      return (await res.json()) as ProjectFullState;
    },
    enabled: !!threadId,
    retry: false,
    refetchInterval: 15000,
  });
}

export function ProjectOsTab({
  state,
  onRefetch,
}: {
  state: ProjectFullState;
  onRefetch?: () => void;
}) {
  const { project, pm, retro, action_specs } = state;

  const executeAction = useCallback(
    async (spec: ActionSpec) => {
      if (!spec.api) return;
      try {
        const res = await fetch(spec.api.path, {
          method: spec.api.method,
          headers: jsonAuthHeaders(),
          body: spec.api.body
            ? JSON.stringify(spec.api.body)
            : undefined,
        });
        if (!res.ok) {
          const text = await res.text();
          toast.error(`操作失败（${res.status}）：${text.slice(0, 200)}`);
          return;
        }
        toast.success(`${spec.label} 已执行`);
        onRefetch?.();
      } catch (e) {
        toast.error(`操作失败：${(e as Error).message}`);
      }
    },
    [onRefetch],
  );

  const overall = pm?.overall_progress ?? 0;
  const milestones = pm?.milestones ?? [];

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="space-y-4 p-3">
        {/* 项目头 */}
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="min-w-0 flex-1 truncate text-sm font-semibold">
              {project.name || project.id}
            </h3>
            <Badge
              variant="outline"
              className={`shrink-0 text-[10px] ${STATUS_TONE[project.status] ?? ""}`}
            >
              {STATUS_LABEL[project.status] ?? project.status}
            </Badge>
          </div>
          {project.goal ? (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              {project.goal}
            </p>
          ) : null}
          {project.owner ? (
            <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
              <UserRoundIcon className="size-3" />
              PM · {project.owner}
            </div>
          ) : null}

          {action_specs.length > 0 ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {action_specs.map((spec) => (
                <Button
                  key={spec.action}
                  size="sm"
                  variant="outline"
                  className="h-7 gap-1 px-2 text-[11px]"
                  onClick={() => executeAction(spec)}
                >
                  {spec.action.startsWith("recover") ? (
                    <RotateCcwIcon className="size-3" />
                  ) : spec.action === "run" ? (
                    <PlayIcon className="size-3" />
                  ) : (
                    <ArrowRightIcon className="size-3" />
                  )}
                  {spec.label}
                </Button>
              ))}
            </div>
          ) : null}
        </div>

        {/* 整体进度 */}
        <div className="space-y-1.5 rounded-lg border border-border-default bg-card/60 p-2.5">
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>整体进度</span>
            <span className="font-medium text-foreground/80">{overall}%</span>
          </div>
          <Progress value={overall} className="h-1.5" />
          {pm ? (
            <div className="text-[11px] text-muted-foreground">
              任务 {pm.done_tasks}/{pm.total_tasks} · 剩余估时{" "}
              {pm.remaining_estimate}d
            </div>
          ) : null}
        </div>

        {/* 里程碑 */}
        {milestones.length > 0 ? (
          <div className="space-y-2">
            <SectionLabel icon={<FlagIcon className="size-3" />}>
              里程碑（{milestones.length}）
            </SectionLabel>
            <div className="space-y-2">
              {milestones.map((m) => (
                <div
                  key={m.id}
                  className="rounded-lg border border-border-default bg-card/40 p-2"
                >
                  <div className="flex items-center gap-2">
                    <span
                      className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[m.health] ?? "bg-muted"}`}
                    />
                    <span className="min-w-0 flex-1 truncate text-xs font-medium">
                      {m.name}
                    </span>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {m.done}/{m.total}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    <Progress value={m.progress} className="h-1" />
                    <span className="w-9 shrink-0 text-right text-[10px] text-muted-foreground">
                      {m.progress}%
                    </span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[10px] text-muted-foreground">
                    <span
                      className={`rounded-full px-1.5 py-px ${HEALTH_DOT[m.health] ? "bg-muted/60" : ""}`}
                    >
                      {HEALTH_LABEL[m.health] ?? m.health}
                    </span>
                    {m.due_at ? <span>截止 {fmtDate(m.due_at)}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}

        {/* PM 驾驶舱摘要 */}
        {pm ? (
          <>
            {pm.next_actions.length > 0 ? (
              <div className="space-y-2">
                <SectionLabel icon={<ListChecksIcon className="size-3" />}>
                  下一步
                </SectionLabel>
                <div className="space-y-1.5">
                  {pm.next_actions.slice(0, 4).map((a) => (
                    <div
                      key={a.task_id}
                      className="flex items-start gap-1.5 rounded-md bg-muted/40 px-2 py-1.5 text-[11px]"
                    >
                      {a.priority === "P0" || a.priority === "P1" ? (
                        <Badge
                          variant="outline"
                          className={`h-4 px-1 text-[9px] ${PRIORITY_TONE[a.priority] ?? ""}`}
                        >
                          {a.priority}
                        </Badge>
                      ) : null}
                      <span className="min-w-0 flex-1 truncate">
                        {a.task}
                      </span>
                      <span className="shrink-0 text-muted-foreground">
                        {a.estimate}d
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {pm.risks.length > 0 || pm.blockers.length > 0 ? (
              <div className="space-y-2">
                <SectionLabel
                  icon={<AlertTriangleIcon className="size-3" />}
                >
                  风险 / 阻塞
                </SectionLabel>
                <div className="space-y-1.5">
                  {pm.blockers.map((b, i) => (
                    <div
                      key={`b-${i}`}
                      className="flex items-start gap-1.5 rounded-md bg-rose-500/[0.06] px-2 py-1.5 text-[11px] text-rose-600"
                    >
                      <FlagIcon className="mt-px size-3 shrink-0" />
                      <span className="min-w-0 flex-1">{b}</span>
                    </div>
                  ))}
                  {pm.risks.slice(0, 4).map((r, i) => (
                    <div
                      key={`r-${i}`}
                      className="flex items-start gap-1.5 rounded-md bg-amber-500/[0.06] px-2 py-1.5 text-[11px] text-amber-700"
                    >
                      <AlertTriangleIcon className="mt-px size-3 shrink-0" />
                      <span className="min-w-0 flex-1">{r.detail}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </>
        ) : null}

        {/* 复盘 */}
        {retro ? (
          <div className="space-y-2 rounded-lg border border-sky-500/30 bg-sky-500/[0.04] p-2.5">
            <SectionLabel
              icon={<ClipboardListIcon className="size-3 text-sky-500" />}
            >
              项目复盘
            </SectionLabel>
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <div className="rounded-md bg-card/60 px-2 py-1.5">
                <div className="text-muted-foreground">交付</div>
                <div className="font-semibold">
                  {retro.done_tasks}/{retro.task_count}
                </div>
              </div>
              <div className="rounded-md bg-card/60 px-2 py-1.5">
                <div className="text-muted-foreground">重试</div>
                <div className="font-semibold">{retro.attempts_total}</div>
              </div>
            </div>
            {retro.recommendations.length > 0 ? (
              <ul className="space-y-1">
                {retro.recommendations.map((r, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-1.5 text-[11px] text-muted-foreground"
                  >
                    <ArrowRightIcon className="mt-0.5 size-3 shrink-0 text-sky-500" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {/* 打开完整驾驶舱 */}
        <Link
          to="/workspace/projects"
          className="flex items-center justify-center gap-1.5 rounded-md border border-border-default py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        >
          <ExternalLinkIcon className="size-3" />
          打开项目管理页
        </Link>
      </div>
    </div>
  );
}
