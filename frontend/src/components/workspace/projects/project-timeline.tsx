/**
 * 里程碑时间轴（甘特视图）
 *
 * 页面副标题写着「规划里程碑」，但此前没有任何时间维度可视化 —— 里程碑只有
 * 一行行文字。这里按 `planned_start → due_at` 把里程碑铺到一条时间轴上，
 * 画出今日基准线，逾期/阻塞用暖色标出。
 *
 * 实现用百分比定位的 div（不引任何图表库）：条宽随容器自适应，文字不参与
 * 缩放，因此窄屏下也不会糊。缺少日期的里程碑不塞进坐标轴，单独列在下方，
 * 避免伪造出并不存在的排期。
 */

import { CalendarRangeIcon, TimerIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  type GanttInput,
  type GanttLayout,
  ganttLayout,
} from "@/core/projects/portfolio";
import {
  HEALTH_BAR_FILL,
  HEALTH_BAR_TRACK,
  HEALTH_DOT,
  HEALTH_LABEL,
} from "./project-meta";

export interface ProjectTimelineProps {
  milestones: readonly GanttInput[];
  now?: Date | number;
  onSelectMilestone?: (milestoneId: string) => void;
}

const LEGEND: Array<{ health: keyof typeof HEALTH_DOT; label: string }> = [
  { health: "completed", label: "完成" },
  { health: "on_track", label: "正常" },
  { health: "at_risk", label: "有风险" },
  { health: "overdue", label: "已逾期" },
  { health: "blocked", label: "阻塞" },
];

function trackStyle(value: number) {
  return { left: `${value}%` } as const;
}

/** 本地自然日 → `2026/09/10`，避免经 ISO 往返时区。 */
function fmtDay(ms: number): string {
  const d = new Date(ms);
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function ProjectTimeline({
  milestones,
  now,
  onSelectMilestone,
}: ProjectTimelineProps) {
  const layout: GanttLayout = ganttLayout(milestones, now);

  if (layout.bars.length === 0 && layout.unscheduled.length === 0) {
    return (
      <div className="rounded-lg border border-dashed px-3 py-4 text-xs text-muted-foreground">
        还没有可排期的里程碑 —— 执行 Run 让引擎拆解计划后，这里会按计划开始 /
        截止日期铺出时间轴。
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {LEGEND.map((item) => (
          <span key={item.health} className="inline-flex items-center gap-1">
            <span
              className={`size-2 rounded-sm ${HEALTH_BAR_FILL[item.health]}`}
            />
            {item.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <span className="h-3 w-px bg-rose-500" />
          今日
        </span>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[22rem] overflow-hidden rounded-lg border">
          {/* 刻度表头 */}
          <div className="flex border-b bg-muted/30">
            <div className="w-24 shrink-0 border-r px-2 py-1.5 text-[11px] text-muted-foreground sm:w-36 md:w-44">
              里程碑
            </div>
            <div className="relative h-7 flex-1">
              {layout.ticks.map((tick) => (
                <span
                  key={tick.key}
                  className="absolute top-1.5 -translate-x-1/2 text-[10px] tabular-nums text-muted-foreground"
                  style={trackStyle(tick.leftPct)}
                >
                  {tick.label}
                </span>
              ))}
              {layout.todayPct !== null && (
                <span
                  className="absolute top-0 h-full w-px bg-rose-500/70"
                  style={trackStyle(layout.todayPct)}
                />
              )}
            </div>
          </div>

          {/* 里程碑行 */}
          {layout.bars.map((bar) => {
            const label = `${bar.name} · ${fmtDay(bar.startMs)} → ${fmtDay(
              bar.endMs - 1,
            )}`;
            return (
              <div
                key={bar.id}
                className="flex border-b last:border-b-0 hover:bg-muted/20"
              >
                <div className="flex w-24 shrink-0 items-center gap-1.5 border-r px-2 py-2 sm:w-36 md:w-44">
                  <span
                    className={`size-2 shrink-0 rounded-full ${HEALTH_DOT[bar.health]}`}
                  />
                  <span
                    className="truncate text-[11px] font-medium"
                    title={bar.name}
                  >
                    {bar.name}
                  </span>
                </div>
                <div className="relative min-h-[2.5rem] flex-1 py-2">
                  {/* 网格线 */}
                  {layout.ticks.map((tick) => (
                    <span
                      key={tick.key}
                      className="absolute top-0 h-full w-px bg-border/60"
                      style={trackStyle(tick.leftPct)}
                    />
                  ))}
                  {layout.todayPct !== null && (
                    <span
                      className="absolute top-0 h-full w-px bg-rose-500/60"
                      style={trackStyle(layout.todayPct)}
                    />
                  )}
                  <button
                    type="button"
                    className={`absolute top-1/2 h-5 -translate-y-1/2 overflow-hidden rounded ${HEALTH_BAR_TRACK[bar.health]} ${
                      onSelectMilestone ? "cursor-pointer" : "cursor-default"
                    }`}
                    style={{ left: `${bar.leftPct}%`, width: `${bar.widthPct}%` }}
                    title={label}
                    aria-label={`${label}，进度 ${Math.round(bar.progress * 100)}%`}
                    onClick={() => onSelectMilestone?.(bar.id)}
                  >
                    <span
                      className={`block h-full rounded ${HEALTH_BAR_FILL[bar.health]}`}
                      style={{ width: `${Math.round(bar.progress * 100)}%` }}
                    />
                  </button>
                  {bar.overdueCount > 0 && (
                    <span
                      className="absolute top-1/2 flex -translate-y-1/2 items-center gap-0.5 rounded bg-orange-500/15 px-1 py-px text-[10px] tabular-nums text-orange-600"
                      style={{ left: `calc(${bar.leftPct + bar.widthPct}% + 4px)` }}
                    >
                      <TimerIcon className="size-2.5" />
                      {bar.overdueCount}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {layout.unscheduled.length > 0 && (
        <div className="rounded-lg border border-dashed px-3 py-2.5">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
            <CalendarRangeIcon className="size-3" />
            未排期 · {layout.unscheduled.length}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {layout.unscheduled.map((item) => (
              <Badge
                key={item.id}
                variant="outline"
                className="gap-1 text-[10px] font-normal"
              >
                <span
                  className={`size-1.5 rounded-full ${HEALTH_DOT[item.health]}`}
                />
                {item.name}
                <span className="text-muted-foreground">
                  {HEALTH_LABEL[item.health] ?? item.health}
                </span>
              </Badge>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span>
          跨度 {Math.max(1, Math.round(layout.spanMs / (24 * 60 * 60 * 1000)))} 天
        </span>
        {layout.bars.length > 0 && (
          <span className="inline-flex items-center gap-1">
            条内深色部分为已完成进度
          </span>
        )}
      </div>
    </div>
  );
}
