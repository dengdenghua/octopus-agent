/**
 * 项目切换器 · 同一个 DOM，两种形态
 *
 * - 桌面（md+）：左栏纵向列表，带搜索、筛选、进度条、健康度圆点、逾期徽标
 * - 窄屏：顶部横向可滑动条带
 *
 * 刻意只渲染一份 DOM（靠 md: 类切换形态），而不是 `hidden md:flex` 各写一份：
 * 后者会让搜索框、按钮在无障碍树里出现两次，测试与读屏都会撞车；更重要的
 * 是原实现在窄屏下 `hidden` 掉整个项目列表，手机上根本没法切换项目。
 *
 * 行的数据来源由调用方决定：`/api/projects/portfolio` 正常时是带进度/健康度
 * 的完整行，接口失败时降级为 `/api/projects` 的裸元数据行。
 */

import { AlertTriangleIcon, SearchIcon, TimerIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  type ProjectRow,
  type ProjectStatusFilter,
  filterProjectRows,
  sortProjectRows,
} from "@/core/projects/portfolio";
import {
  HEALTH_DOT,
  HEALTH_LABEL,
  STATUS_TONE,
  statusLabel,
} from "./project-meta";

export interface ProjectSwitcherProps {
  /** 全量行（组件内部做筛选，保证「无匹配」文案能给出真实总数）。 */
  rows: readonly ProjectRow[];
  selectedId: string | null;
  onSelect: (projectId: string) => void;
  query: string;
  onQueryChange: (query: string) => void;
  filter: ProjectStatusFilter;
  onFilterChange: (filter: ProjectStatusFilter) => void;
  className?: string;
}

const FILTERS: Array<{ value: ProjectStatusFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "active", label: "进行中" },
  { value: "attention", label: "需关注" },
  { value: "closed", label: "已结束" },
];

function StatusChip({ row }: { row: ProjectRow }) {
  if (row.overdue > 0) {
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-0.5 border-orange-500/30 bg-orange-500/15 text-[10px] text-orange-600"
      >
        <TimerIcon className="size-2.5" />
        {row.overdue}
      </Badge>
    );
  }
  if (row.risks > 0) {
    return (
      <Badge
        variant="outline"
        className="shrink-0 gap-0.5 border-amber-500/30 bg-amber-500/15 text-[10px] text-amber-600"
      >
        <AlertTriangleIcon className="size-2.5" />
        {row.risks}
      </Badge>
    );
  }
  return null;
}

export function ProjectSwitcher({
  rows,
  selectedId,
  onSelect,
  query,
  onQueryChange,
  filter,
  onFilterChange,
  className = "",
}: ProjectSwitcherProps) {
  const visible = sortProjectRows(filterProjectRows(rows, query, filter));

  return (
    <aside
      className={`flex min-h-0 flex-col border-b border-border/60 md:w-64 md:border-b-0 md:border-r ${className}`}
      aria-label="项目列表"
    >
      <div className="shrink-0 space-y-2 px-3 py-2.5">
        <div className="flex items-center justify-between text-[11px] text-muted-foreground">
          <span>
            项目（{visible.length}/{rows.length}）
          </span>
          {query.trim() && (
            <button
              type="button"
              className="rounded px-1 hover:bg-muted"
              onClick={() => onQueryChange("")}
            >
              清除搜索
            </button>
          )}
        </div>
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            placeholder="搜索项目名称 / 目标"
            aria-label="搜索项目"
            className="h-8 pr-2 pl-8 text-base md:text-xs"
          />
        </div>
        <div className="flex items-center gap-1 overflow-x-auto">
          {FILTERS.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => onFilterChange(item.value)}
              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] transition-colors ${
                filter === item.value
                  ? "bg-foreground text-background"
                  : "bg-muted/60 text-muted-foreground hover:bg-muted"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 gap-1.5 overflow-x-auto px-3 pb-2.5 md:flex-col md:gap-1 md:overflow-y-auto md:px-2 md:pt-1">
        {visible.length === 0 && (
          <div className="px-1 py-3 text-[11px] text-muted-foreground">
            {rows.length === 0
              ? "还没有项目。"
              : "没有匹配的项目 —— 换个关键词或清空筛选。"}
          </div>
        )}
        {visible.map((row) => {
          const selected = selectedId === row.id;
          const pct = Math.round(row.progress * 100);
          return (
            <button
              key={row.id}
              type="button"
              onClick={() => onSelect(row.id)}
              aria-current={selected ? "true" : undefined}
              className={`w-40 shrink-0 rounded-lg border px-2.5 py-2 text-left transition-colors md:w-full ${
                selected
                  ? "border-primary/40 bg-muted/60"
                  : "border-transparent hover:bg-muted/40"
              }`}
            >
              <div className="flex items-center justify-between gap-1.5">
                <span className="flex min-w-0 items-center gap-1.5">
                  {row.readable ? (
                    <span
                      className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[row.health]}`}
                      title={HEALTH_LABEL[row.health] ?? row.health}
                    />
                  ) : (
                    <span
                      className="size-2 shrink-0 rounded-full border border-dashed border-muted-foreground/60"
                      title="尚未获取到进度数据"
                    />
                  )}
                  <span className="truncate text-xs font-medium">{row.name}</span>
                </span>
                <StatusChip row={row} />
              </div>

              <div className="mt-1.5 flex items-center gap-1.5">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className={`h-full rounded-full ${HEALTH_DOT[row.health]}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                  {pct}%
                </span>
              </div>

              <div className="mt-1 flex items-center justify-between gap-1.5">
                <span className="truncate text-[10px] text-muted-foreground">
                  {row.readable
                    ? `${row.doneTasks}/${row.totalTasks} 任务 · 剩 ${row.remainingEstimate}d`
                    : row.goal || "尚未获取进度"}
                </span>
                <Badge
                  variant="outline"
                  className={`hidden shrink-0 text-[10px] md:inline-flex ${STATUS_TONE[row.status] ?? ""}`}
                >
                  {statusLabel(row.status)}
                </Badge>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
