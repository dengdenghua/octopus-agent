/**
 * 今天要处理 · 跨项目聚合块（置顶）
 *
 * 这是原项目管理页最大的空白：逾期任务、今日到期、有风险里程碑此前只能
 * 逐个点进项目才能发现。这里把 N 个项目的这三类条目压成一块，
 * 逾期标红，每条给一个「去处理」直达按钮。
 */

import {
  AlertTriangleIcon,
  ArrowRightIcon,
  CalendarRangeIcon,
  ShieldAlertIcon,
  TimerIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  type TodayItem,
  type TodayQueue,
} from "@/core/projects/portfolio";
import { PRIORITY_TONE, duePhrase } from "./project-meta";

export interface TodayQueuePanelProps {
  queue: TodayQueue;
  onSelectProject: (projectId: string) => void;
}

interface GroupSpec {
  key: string;
  title: string;
  hint: string;
  items: TodayItem[];
  tone: "danger" | "warn" | "neutral";
  icon: React.ReactNode;
}

const TONE_ROW: Record<GroupSpec["tone"], string> = {
  danger: "border-orange-500/25 bg-orange-500/[0.06]",
  warn: "border-amber-500/25 bg-amber-500/[0.05]",
  neutral: "border-border bg-card/50",
};

const TONE_TITLE: Record<GroupSpec["tone"], string> = {
  danger: "text-orange-600",
  warn: "text-amber-600",
  neutral: "text-muted-foreground",
};

function TodayGroup({
  spec,
  onSelectProject,
}: {
  spec: GroupSpec;
  onSelectProject: (projectId: string) => void;
}) {
  if (spec.items.length === 0) return null;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        <span className={`flex items-center gap-1 text-xs font-semibold ${TONE_TITLE[spec.tone]}`}>
          {spec.icon}
          {spec.title}
          <span className="tabular-nums">· {spec.items.length}</span>
        </span>
        <span className="text-[11px] text-muted-foreground">{spec.hint}</span>
      </div>
      <div className="space-y-1.5">
        {spec.items.map((item) => (
          <div
            key={item.key}
            className={`flex flex-wrap items-start gap-2 rounded-lg border px-2.5 py-2 md:flex-nowrap ${TONE_ROW[spec.tone]}`}
          >
            <Badge
              variant="outline"
              className={`mt-0.5 shrink-0 text-[10px] ${PRIORITY_TONE[item.priority] ?? ""}`}
            >
              {item.priority}
            </Badge>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium" title={item.title}>
                {item.title}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  <span className="max-w-[9rem] truncate font-medium text-foreground/70">
                    {item.projectName}
                  </span>
                </span>
                {item.milestone && (
                  <span className="max-w-[10rem] truncate">
                    里程碑 · {item.milestone}
                  </span>
                )}
                {item.dueAt && (
                  <span className="inline-flex items-center gap-1">
                    <CalendarRangeIcon className="size-3" />
                    {duePhrase(item.daysLeft)}
                  </span>
                )}
                {item.scope === "milestone" && (
                  <span className="rounded bg-muted px-1 py-px text-[10px]">
                    里程碑级
                  </span>
                )}
              </div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 shrink-0 gap-1 px-2 text-[11px]"
              aria-label={`去处理：${item.title}`}
              onClick={() => onSelectProject(item.projectId)}
            >
              去处理
              <ArrowRightIcon className="size-3" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function TodayQueuePanel({
  queue,
  onSelectProject,
}: TodayQueuePanelProps) {
  const groups: GroupSpec[] = [
    {
      key: "overdue",
      title: "已逾期",
      hint: "先处理这些",
      items: queue.overdue,
      tone: "danger",
      icon: <TimerIcon className="size-3.5" />,
    },
    {
      key: "due-today",
      title: "今天到期",
      hint: "今天内完成",
      items: queue.dueToday,
      tone: "warn",
      icon: <CalendarRangeIcon className="size-3.5" />,
    },
    {
      key: "at-risk",
      title: "有风险里程碑",
      hint: "需要关注",
      items: queue.atRisk,
      tone: "neutral",
      icon: <ShieldAlertIcon className="size-3.5" />,
    },
  ];
  const hiddenTotal = queue.hidden.overdue + queue.hidden.nextActions;

  return (
    <Card
      className={
        queue.overdue.length > 0
          ? "border-orange-500/30 bg-orange-500/[0.02]"
          : undefined
      }
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span
              className={`flex size-7 items-center justify-center rounded-lg ${
                queue.overdue.length > 0
                  ? "bg-orange-500/15 text-orange-600"
                  : "bg-muted/60 text-muted-foreground"
              }`}
            >
              <AlertTriangleIcon className="size-4" />
            </span>
            <div>
              <div className="text-sm font-semibold">今天要处理</div>
              <div className="text-[11px] text-muted-foreground">
                跨全部项目的逾期、今日到期与风险项
              </div>
            </div>
          </div>
          {queue.total > 0 && (
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Badge variant="outline" className="text-[10px]">
                共 {queue.total} 条
              </Badge>
            </div>
          )}
        </div>

        {queue.total === 0 ? (
          <div className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-3 text-xs text-muted-foreground">
            <TimerIcon className="size-3.5" />
            今天没有逾期或到期项，先推进「下一步动作」里的任务即可。
          </div>
        ) : (
          <div className="space-y-3">
            {groups.map((spec) => (
              <TodayGroup
                key={spec.key}
                spec={spec}
                onSelectProject={onSelectProject}
              />
            ))}
          </div>
        )}

        {hiddenTotal > 0 && (
          <div className="text-[11px] text-muted-foreground">
            每条项目最多聚合 20 条逾期、10 条待办，另有 {hiddenTotal} 条未在此展开，
            进入项目查看完整清单。
          </div>
        )}
      </CardContent>
    </Card>
  );
}
