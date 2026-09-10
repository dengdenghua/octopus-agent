/**
 * 项目 / 里程碑图表 · 全部内联手写 SVG + CSS，零外部图表库。
 *
 * 铁律：AI 生成的页面一旦引用 CDN 图表库，用户只存 HTML 时就会 404。
 * 这里所有图形都由本文件的 DOM/SVG 直接产出。
 */

import type { ProjectHealth } from "@/core/projects/portfolio";
import type { EstimateRow } from "@/core/projects/portfolio";
import { HEALTH_DOT, HEALTH_FILL, HEALTH_LABEL } from "./project-meta";

// ─── 健康度环形图 ────────────────────────────────────────────────────

export interface HealthDonutProps {
  counts: Record<ProjectHealth, number>;
  /** 环心文案下方的说明。 */
  caption?: string;
  size?: number;
  thickness?: number;
}

const DONUT_ORDER: ProjectHealth[] = [
  "blocked",
  "overdue",
  "at_risk",
  "on_track",
  "completed",
];

export function HealthDonut({
  counts,
  caption = "里程碑",
  size = 104,
  thickness = 12,
}: HealthDonutProps) {
  const total = DONUT_ORDER.reduce((sum, health) => sum + (counts[health] ?? 0), 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const center = size / 2;
  let consumed = 0;

  const segments = DONUT_ORDER.flatMap((health) => {
    const count = counts[health] ?? 0;
    if (count <= 0 || total <= 0) return [];
    const length = (count / total) * circumference;
    const segment = {
      health,
      count,
      length,
      offset: consumed,
    };
    consumed += length;
    return [segment];
  });

  return (
    <div className="flex items-center gap-3">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-label={`里程碑健康度分布：共 ${total} 个`}
        >
          <circle
            cx={center}
            cy={center}
            r={radius}
            fill="none"
            stroke="#e5e7eb"
            strokeWidth={thickness}
          />
          {segments.map((segment) => (
            <circle
              key={segment.health}
              cx={center}
              cy={center}
              r={radius}
              fill="none"
              stroke={HEALTH_FILL[segment.health]}
              strokeWidth={thickness}
              strokeDasharray={`${segment.length} ${circumference - segment.length}`}
              strokeDashoffset={-segment.offset}
              transform={`rotate(-90 ${center} ${center})`}
            />
          ))}
          <text
            x={center}
            y={center - 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={size * 0.24}
            fontWeight={600}
            fill="#111827"
          >
            {total}
          </text>
          <text
            x={center}
            y={center + size * 0.16}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={size * 0.11}
            fill="#6b7280"
          >
            {caption}
          </text>
        </svg>
      </div>
      <ul className="min-w-0 flex-1 space-y-1">
        {DONUT_ORDER.filter((health) => (counts[health] ?? 0) > 0).map(
          (health) => (
            <li
              key={health}
              className="flex items-center justify-between gap-2 text-xs"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span
                  className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[health]}`}
                />
                <span className="truncate">{HEALTH_LABEL[health]}</span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                {counts[health]}
              </span>
            </li>
          ),
        )}
        {total === 0 && (
          <li className="text-xs text-muted-foreground">还没有里程碑</li>
        )}
      </ul>
    </div>
  );
}

// ─── 各项目进度对比 ──────────────────────────────────────────────────

export interface ProgressRowInput {
  id: string;
  name: string;
  health: ProjectHealth;
  progress: number;
  doneTasks: number;
  totalTasks: number;
  overdue: number;
}

export interface ProjectProgressBarsProps {
  rows: readonly ProgressRowInput[];
  selectedId?: string | null;
  onSelectProject?: (projectId: string) => void;
}

function pct(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, Math.round(value * 100)));
}

export function ProjectProgressBars({
  rows,
  selectedId,
  onSelectProject,
}: ProjectProgressBarsProps) {
  if (rows.length === 0) {
    return <div className="text-xs text-muted-foreground">暂无项目。</div>;
  }
  return (
    <ul className="space-y-2">
      {rows.map((row) => {
        const value = pct(row.progress);
        const interactive = typeof onSelectProject === "function";
        const RowTag = interactive ? "button" : "div";
        return (
          <li key={row.id}>
            <RowTag
              {...(interactive
                ? {
                    type: "button" as const,
                    onClick: () => onSelectProject?.(row.id),
                    "aria-label": `查看项目进度：${row.name}`,
                  }
                : {})}
              className={`w-full rounded-md px-1 py-0.5 text-left transition-colors ${
                interactive ? "hover:bg-muted/40" : ""
              } ${selectedId === row.id ? "bg-muted/40" : ""}`}
            >
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span
                    className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[row.health]}`}
                  />
                  <span className="truncate font-medium">{row.name}</span>
                  {row.overdue > 0 && (
                    <span className="shrink-0 rounded bg-orange-500/15 px-1 py-px text-[10px] tabular-nums text-orange-600">
                      逾期 {row.overdue}
                    </span>
                  )}
                </span>
                <span className="shrink-0 tabular-nums text-muted-foreground">
                  {value}%
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2">
                <div
                  className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
                  role="progressbar"
                  aria-valuenow={value}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`${row.name} 进度`}
                >
                  <div
                    className={`h-full rounded-full ${HEALTH_DOT[row.health]}`}
                    style={{ width: `${value}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">
                  {row.doneTasks}/{row.totalTasks} 任务
                </span>
              </div>
            </RowTag>
          </li>
        );
      })}
    </ul>
  );
}

// ─── 里程碑估时堆叠条 ────────────────────────────────────────────────

export function EstimateStack({
  rows,
}: {
  rows: readonly EstimateRow[];
}) {
  if (rows.length === 0) {
    return <div className="text-xs text-muted-foreground">暂无估算数据。</div>;
  }
  const maxTotal = Math.max(...rows.map((row) => row.totalEstimate), 1);
  return (
    <ul className="space-y-2.5">
      {rows.map((row) => {
        const scale = (value: number) => `${(value / maxTotal) * 100}%`;
        const flagged =
          row.health === "at_risk" ||
          row.health === "overdue" ||
          row.health === "blocked";
        return (
          <li key={row.id} className="space-y-1">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="flex min-w-0 items-center gap-1.5">
                <span
                  className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[row.health]}`}
                />
                <span className="truncate" title={row.name}>
                  {row.name}
                </span>
              </span>
              <span className="shrink-0 tabular-nums text-muted-foreground">
                已完成 {row.doneEstimate}d · 剩余 {row.remainingEstimate}d
              </span>
            </div>
            <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-emerald-500/80"
                style={{ width: scale(row.doneEstimate) }}
                title={`已完成估时 ${row.doneEstimate}d`}
              />
              <div
                className={`h-full ${flagged ? "bg-orange-500/70" : "bg-slate-400/70"}`}
                style={{ width: scale(row.remainingEstimate) }}
                title={`剩余估时 ${row.remainingEstimate}d`}
              />
            </div>
            <div className="flex items-center justify-between text-[10px] text-muted-foreground">
              <span>共 {row.totalEstimate}d</span>
              <span className="tabular-nums">{pct(row.progress)}%</span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
