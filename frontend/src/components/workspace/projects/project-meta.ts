/**
 * 项目管理控制台的共享展示元数据。
 *
 * 页面与子组件都从这里取标签/配色，避免同一个健康度在两处出现不同说法
 * （此前 `STATUS_LABEL` 与 `HEALTH_LABEL` 只在 page.tsx 内部重复定义）。
 */

import type { ProjectHealth } from "@/core/projects/portfolio";

export const STATUS_LABEL: Record<string, string> = {
  planning: "规划中",
  running: "进行中",
  blocked: "已阻塞",
  done: "已完成",
  failed: "失败",
};

export const HEALTH_LABEL: Record<string, string> = {
  on_track: "正常",
  at_risk: "有风险",
  overdue: "已逾期",
  blocked: "阻塞",
  completed: "完成",
};

export const HEALTH_TONE: Record<ProjectHealth, string> = {
  on_track: "bg-emerald-500/15 text-emerald-600 border-emerald-500/30",
  at_risk: "bg-amber-500/15 text-amber-600 border-amber-500/30",
  overdue: "bg-orange-500/15 text-orange-600 border-orange-500/30",
  blocked: "bg-rose-500/15 text-rose-600 border-rose-500/30",
  completed: "bg-sky-500/15 text-sky-600 border-sky-500/30",
};

export const HEALTH_DOT: Record<ProjectHealth, string> = {
  on_track: "bg-emerald-500",
  at_risk: "bg-amber-500",
  overdue: "bg-orange-500",
  blocked: "bg-rose-500",
  completed: "bg-sky-500",
};

export const HEALTH_FILL: Record<ProjectHealth, string> = {
  on_track: "#10b981",
  at_risk: "#f59e0b",
  overdue: "#f97316",
  blocked: "#f43f5e",
  completed: "#0ea5e9",
};

/** 甘特条：底色（计划区间）与进度条（已完成部分）。 */
export const HEALTH_BAR_TRACK: Record<ProjectHealth, string> = {
  on_track: "bg-emerald-500/25",
  at_risk: "bg-amber-500/25",
  overdue: "bg-orange-500/30",
  blocked: "bg-rose-500/30",
  completed: "bg-sky-500/25",
};

export const HEALTH_BAR_FILL: Record<ProjectHealth, string> = {
  on_track: "bg-emerald-500",
  at_risk: "bg-amber-500",
  overdue: "bg-orange-500",
  blocked: "bg-rose-500",
  completed: "bg-sky-500",
};

export const HEALTH_LABEL_EN: Record<ProjectHealth, string> = {
  on_track: "On track",
  at_risk: "At risk",
  overdue: "Overdue",
  blocked: "Blocked",
  completed: "Completed",
};

export const STATUS_TONE: Record<string, string> = {
  planning: "bg-muted text-muted-foreground",
  running: "bg-emerald-500/15 text-emerald-600",
  blocked: "bg-rose-500/15 text-rose-600",
  done: "bg-sky-500/15 text-sky-600",
  failed: "bg-rose-500/15 text-rose-600",
};

export const PRIORITY_TONE: Record<string, string> = {
  P0: "bg-rose-500/15 text-rose-600",
  P1: "bg-amber-500/15 text-amber-600",
  P2: "bg-muted text-muted-foreground",
  P3: "bg-muted text-muted-foreground/70",
};

export function statusLabel(status: string | undefined): string {
  if (!status) return "—";
  return STATUS_LABEL[status] ?? status;
}

export function healthLabel(health: string): string {
  return HEALTH_LABEL[health] ?? health;
}

export function fmtDate(value: string | undefined | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function fmtDateTime(value: string | undefined | null): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 「已逾期 3 天」/「今天到期」/「还剩 2 天」/「未排期」 */
export function duePhrase(daysLeft: number | null): string {
  if (daysLeft === null) return "未排期";
  if (daysLeft < 0) return `已逾期 ${Math.abs(daysLeft)} 天`;
  if (daysLeft === 0) return "今天到期";
  if (daysLeft === 1) return "明天到期";
  return `还剩 ${daysLeft} 天`;
}
