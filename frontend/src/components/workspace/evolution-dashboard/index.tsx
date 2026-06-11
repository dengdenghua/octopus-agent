import React, { useMemo } from "react";
import {
  AlertTriangleIcon,
  BrainCircuitIcon,
  TrendingUpIcon,
  ActivityIcon,
  DatabaseIcon,
  Loader2Icon,
  BookOpenIcon,
  LightbulbIcon,
  ZapIcon,
  InfoIcon,
} from "lucide-react";

import {
  useEvolutionOverview,
  useLearningCurve,
  useSkillPerformance,
  useMemoryGrowth,
  useRecommendations,
} from "@/core/evolution/hooks";
import type {
  EvolutionOverview,
  LearningCurvePoint,
  SkillPerformance,
  Recommendation,
} from "@/core/evolution/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { GeneLockControlCard } from "@/components/workspace/gene-lock-badge";

import { SparklineChart } from "./sparkline-chart";

function scoreColor(value: number): string {
  if (value >= 0.7) return "text-emerald-500";
  if (value >= 0.4) return "text-amber-500";
  return "text-red-500";
}

function numberOrZero(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function fixed(value: unknown, digits: number): string {
  return numberOrZero(value).toFixed(digits);
}

function countColor(value: number, good: number, moderate: number): string {
  if (value >= good) return "text-emerald-500";
  if (value >= moderate) return "text-amber-500";
  return "text-red-500";
}

function successRateClass(rate: number): string {
  if (rate >= 0.8) return "text-emerald-600 dark:text-emerald-400";
  if (rate >= 0.5) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

export function EvolutionDashboard({ className }: { className?: string }) {
  const { t } = useI18n();
  const overviewQ = useEvolutionOverview();
  const learningCurveQ = useLearningCurve();
  const skillPerformanceQ = useSkillPerformance();
  const memoryGrowthQ = useMemoryGrowth();
  const recommendationsQ = useRecommendations();

  const isLoading =
    overviewQ.isLoading ||
    learningCurveQ.isLoading ||
    skillPerformanceQ.isLoading ||
    recommendationsQ.isLoading;

  const firstError =
    overviewQ.error ||
    learningCurveQ.error ||
    skillPerformanceQ.error ||
    recommendationsQ.error;

  if (isLoading) {
    return (
      <div className={cn("flex h-full items-center justify-center", className)}>
        <div className="flex flex-col items-center gap-3">
          <Loader2Icon className="size-8 animate-spin text-purple-500" />
          <span className="text-sm text-muted-foreground">
            {t.evolutionDashboard.loading}
          </span>
        </div>
      </div>
    );
  }

  if (firstError) {
    return (
      <div className={cn("space-y-4", className)}>
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400">
          {t.evolutionDashboard.connectionFailed}
        </div>
      </div>
    );
  }

  const memorySparkline = memoryGrowthQ.data
    ? memoryGrowthQ.data.map(
        (d) => d.fact + d.preference + d.learned_skill + d.relationship,
      )
    : [];
  const overview = overviewQ.data ?? null;
  const learningCurve = learningCurveQ.data ?? [];
  const skillPerformance = skillPerformanceQ.data ?? [];
  const recommendations = recommendationsQ.data ?? [];
  const topSkills = [...skillPerformance]
    .filter(
      (skill) =>
        numberOrZero(skill.usage_count) > 0 ||
        numberOrZero(skill.success_rate) > 0,
    )
    .sort((a, b) => numberOrZero(b.usage_count) - numberOrZero(a.usage_count))
    .slice(0, 5);

  return (
    <div className={cn("space-y-5", className)}>
      <GrowthStoryHero
        overview={overview}
        memorySparkline={memorySparkline}
        recommendationCount={recommendations.length}
      />

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <LearningStory data={learningCurve} />
        <SkillStory data={topSkills} />
      </div>

      <RecommendationsStory data={recommendations} />
    </div>
  );
}

export default EvolutionDashboard;

function formatPercent(value: unknown, digits = 0): string {
  return `${fixed(numberOrZero(value) * 100, digits)}%`;
}

function GrowthStoryHero({
  overview,
  memorySparkline,
  recommendationCount,
}: {
  overview: EvolutionOverview | null;
  memorySparkline: number[];
  recommendationCount: number;
}) {
  const skills = overview?.skills;
  const memory = overview?.memory;
  const learningEvents = numberOrZero(overview?.learning_events);
  const improvementScore = numberOrZero(overview?.improvement_score);
  const improvementPct = Math.round(improvementScore * 100);
  const totalSkills = numberOrZero(skills?.total);
  const autoSkills = numberOrZero(skills?.auto_extracted);
  const totalMemories = numberOrZero(memory?.total_facts);
  const ruleCount = numberOrZero(memory?.categories?.rules);
  const hasEvidence =
    totalSkills > 0 || totalMemories > 0 || learningEvents > 0 || recommendationCount > 0;
  const stages = [
    {
      icon: ActivityIcon,
      title: "观察任务",
      value: learningEvents,
      unit: "次",
      done: learningEvents > 0,
      description: "从真实对话和执行过程里找经验。",
    },
    {
      icon: DatabaseIcon,
      title: "沉淀记忆",
      value: totalMemories,
      unit: "条",
      done: totalMemories > 0,
      description: "把可复用事实、偏好和规则存下来。",
    },
    {
      icon: BookOpenIcon,
      title: "形成技能",
      value: totalSkills,
      unit: "个",
      done: totalSkills > 0,
      description: "把稳定做法变成下次可调用的能力。",
    },
    {
      icon: LightbulbIcon,
      title: "提出改进",
      value: recommendationCount,
      unit: "项",
      done: recommendationCount > 0,
      description: "给下一轮优化留下明确方向。",
    },
  ];

  return (
    <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
      <div className="rounded-xl border border-border/60 bg-gradient-to-br from-primary/10 via-background to-background p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <BrainCircuitIcon className="size-4 text-primary" />
              这段时间它进化了什么
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {hasEvidence
                ? `它已经沉淀了 ${totalMemories} 条记忆、${totalSkills} 个技能，并从 ${learningEvents} 次学习事件里提炼经验。`
                : "还没有足够的进化证据。跑过更多任务后，这里会自动变成可读的成长记录。"}
            </p>
          </div>
          <div className="shrink-0 rounded-lg border border-primary/20 bg-background/80 px-4 py-3 text-right shadow-sm">
            <div className="text-[11px] text-muted-foreground">综合提升感</div>
            <div className={cn("mt-1 text-3xl font-bold tabular-nums", scoreColor(improvementScore))}>
              {improvementPct}
            </div>
            <div className="text-[11px] text-muted-foreground">/ 100</div>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-4">
          {stages.map((stage, index) => (
            <EvolutionStage key={stage.title} stage={stage} index={index + 1} />
          ))}
        </div>

        <GeneLockControlCard compact className="mt-3" />
      </div>

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
        <StoryMetric
          icon={BookOpenIcon}
          title="自动形成的技能"
          value={autoSkills}
          detail={totalSkills > 0 ? `占全部技能 ${formatPercent(autoSkills / Math.max(totalSkills, 1))}` : "等待技能沉淀"}
        />
        <StoryMetric
          icon={DatabaseIcon}
          title="可复用经验库"
          value={totalMemories}
          detail={ruleCount > 0 ? `${ruleCount} 条是规则/避坑经验` : "记住事实、偏好和执行经验"}
          sparkline={memorySparkline.length >= 2 ? memorySparkline : undefined}
        />
        <StoryMetric
          icon={LightbulbIcon}
          title="下一步建议"
          value={recommendationCount}
          detail={recommendationCount > 0 ? "可以继续点开查看" : "暂时没有需要你处理的建议"}
        />
      </div>
    </section>
  );
}

function EvolutionStage({
  stage,
  index,
}: {
  stage: {
    icon: React.ElementType;
    title: string;
    value: number;
    unit: string;
    done: boolean;
    description: string;
  };
  index: number;
}) {
  const Icon = stage.icon;
  return (
    <div
      className={cn(
        "relative rounded-lg border px-3 py-3",
        stage.done
          ? "border-primary/30 bg-primary/5"
          : "border-border/50 bg-muted/25 text-muted-foreground",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex size-6 items-center justify-center rounded-full text-[11px] font-semibold",
              stage.done ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
            )}
          >
            {index}
          </span>
          <Icon className={cn("size-3.5", stage.done && "text-primary")} />
        </div>
        <span className="text-[11px] tabular-nums">
          {stage.value}{stage.unit}
        </span>
      </div>
      <div className="mt-3 text-sm font-semibold">{stage.title}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {stage.description}
      </p>
    </div>
  );
}

function StoryMetric({
  icon: Icon,
  title,
  value,
  detail,
  sparkline,
}: {
  icon: React.ElementType;
  title: string;
  value: number;
  detail: string;
  sparkline?: number[];
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-card px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
            <Icon className="size-3.5" />
            {title}
          </div>
          <div className="mt-2 text-2xl font-bold tabular-nums">{value}</div>
          <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            {detail}
          </div>
        </div>
        {sparkline && <SparklineChart data={sparkline} color="#3b82f6" width={64} height={24} />}
      </div>
    </div>
  );
}

function LearningStory({ data }: { data: LearningCurvePoint[] }) {
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border/60 bg-card p-4">
        <SectionTitle icon={TrendingUpIcon} title="能力趋势" />
        <EmptyStory text="还没有形成趋势。等它跑过几轮任务后，这里会展示成功率和耗时变化。" />
      </section>
    );
  }

  const compact = data.slice(-6);
  const first = compact[0];
  const last = compact[compact.length - 1];
  const firstRate = numberOrZero(first?.success_rate);
  const lastRate = numberOrZero(last?.success_rate);
  const delta = lastRate - firstRate;
  const avgDuration =
    compact.reduce((sum, point) => sum + numberOrZero(point.avg_duration_ms), 0) /
    compact.length;

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <SectionTitle icon={TrendingUpIcon} title="能力趋势" />
        <div className="text-right">
          <div
            className={cn(
              "text-sm font-semibold tabular-nums",
              delta >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400",
            )}
          >
            {delta >= 0 ? "+" : ""}
            {formatPercent(delta, 0)}
          </div>
          <div className="text-[11px] text-muted-foreground">最近变化</div>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <MiniStat label="当前成功率" value={formatPercent(lastRate, 0)} />
        <MiniStat
          label="平均耗时"
          value={avgDuration >= 1000 ? `${fixed(avgDuration / 1000, 1)}s` : `${Math.round(avgDuration)}ms`}
        />
        <MiniStat
          label="最近技能调用"
          value={String(compact.reduce((sum, point) => sum + numberOrZero(point.skills_used), 0))}
        />
      </div>

      <div className="mt-4 flex items-end gap-2 overflow-hidden rounded-lg border border-border/40 bg-muted/20 px-3 py-3">
        {compact.map((point) => {
          const rate = numberOrZero(point.success_rate);
          return (
            <div key={point.week} className="flex min-w-0 flex-1 flex-col items-center gap-2">
              <div className="flex h-20 w-full items-end justify-center">
                <div
                  className={cn(
                    "w-full max-w-8 rounded-t-md",
                    rate >= 0.8
                      ? "bg-emerald-500"
                      : rate >= 0.5
                        ? "bg-amber-500"
                        : "bg-red-500",
                  )}
                  style={{ height: `${Math.max(rate * 100, 6)}%` }}
                />
              </div>
              <div className="truncate text-[10px] text-muted-foreground">{point.week}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SkillStory({ data }: { data: SkillPerformance[] }) {
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border/60 bg-card p-4">
        <SectionTitle icon={BrainCircuitIcon} title="变强的能力" />
        <EmptyStory text="暂时还没有技能表现数据。后续会按使用次数和成功率展示最常用能力。" />
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4">
      <SectionTitle icon={BrainCircuitIcon} title="变强的能力" />
      <div className="mt-4 space-y-3">
        {data.map((skill) => {
          const rate = numberOrZero(skill.success_rate);
          return (
            <div key={skill.name} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate font-medium">{skill.name}</span>
                <span className={cn("shrink-0 tabular-nums", successRateClass(rate))}>
                  {formatPercent(rate)}
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className={cn(
                    "h-full rounded-full",
                    rate >= 0.8
                      ? "bg-emerald-500"
                      : rate >= 0.5
                        ? "bg-amber-500"
                        : "bg-red-500",
                  )}
                  style={{ width: `${Math.max(rate * 100, 4)}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>调用 {numberOrZero(skill.usage_count)} 次</span>
                <span>{skill.source}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function RecommendationsStory({ data }: { data: Recommendation[] }) {
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border/60 bg-card p-4">
        <SectionTitle icon={LightbulbIcon} title="下一步怎么变强" />
        <EmptyStory text="目前没有待处理建议。系统会在发现可优化点时，把它翻译成这里的普通话建议。" />
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border/60 bg-card p-4">
      <SectionTitle icon={LightbulbIcon} title="下一步怎么变强" />
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        {data.slice(0, 3).map((rec, index) => (
          <div
            key={`${rec.title}-${index}`}
            className="rounded-lg border border-border/50 bg-muted/20 px-3 py-3"
          >
            <div className="flex items-center gap-2">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
                {index + 1}
              </span>
              <span className="min-w-0 truncate text-sm font-semibold">{rec.title}</span>
            </div>
            <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted-foreground">
              {rec.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function SectionTitle({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold">
      <Icon className="size-4 text-primary" />
      {title}
    </div>
  );
}

function EmptyStory({ text }: { text: string }) {
  return (
    <div className="mt-4 rounded-lg border border-dashed border-border/70 bg-muted/20 px-4 py-6 text-center text-xs leading-relaxed text-muted-foreground">
      {text}
    </div>
  );
}

function OverviewTab({
  overview,
  memorySparkline,
}: {
  overview: EvolutionOverview | null;
  memorySparkline: number[];
}) {
  const { t } = useI18n();

  if (!overview) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border text-xs text-muted-foreground">
        {t.evolutionDashboard.connectionFailed}
      </div>
    );
  }

  const { skills, memory, learning_events, improvement_score } = overview;
  const safeImprovementScore = numberOrZero(improvement_score);
  const improvementPct = Math.round(safeImprovementScore * 100);

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <StatCard
        icon={BookOpenIcon}
        label={t.evolutionDashboard.skills}
        value={skills.total}
        colorClass={countColor(skills.total, 10, 1)}
      />
      <StatCard
        icon={DatabaseIcon}
        label={t.evolutionDashboard.memories}
        value={memory.total_facts}
        colorClass={countColor(memory.total_facts, 50, 1)}
        sparkline={
          memorySparkline.length >= 2 ? memorySparkline : undefined
        }
      />
      <StatCard
        icon={ActivityIcon}
        label={t.evolutionDashboard.learningEvents}
        value={learning_events}
        colorClass={countColor(learning_events, 100, 1)}
      />
      <div className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-md">
        <div className="flex items-center gap-2 text-muted-foreground">
          <TrendingUpIcon className="size-4" />
          <span className="text-xs font-medium">
            {t.evolutionDashboard.improvementScore}
          </span>
        </div>
        <div className="mt-2 flex items-baseline gap-1">
          <span
            className={cn(
              "text-2xl font-bold tabular-nums",
              scoreColor(safeImprovementScore),
            )}
          >
            {improvementPct}
          </span>
          <span className="text-xs text-muted-foreground">
            {t.evolutionDashboard.of100}
          </span>
        </div>
        <svg
          width="100%"
          height={6}
          viewBox="0 0 100 6"
          className="mt-2"
          aria-hidden="true"
        >
          <rect x={0} y={0} width={100} height={6} rx={3} fill="currentColor" className="text-muted" />
          <rect
            x={0}
            y={0}
            width={improvementPct}
            height={6}
            rx={3}
            className={
              improvementPct >= 70
                ? "text-emerald-500"
                : improvementPct >= 40
                  ? "text-amber-500"
                  : "text-red-500"
            }
            fill="currentColor"
          />
        </svg>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  colorClass,
  sparkline,
}: {
  icon: React.ElementType;
  label: string;
  value: number;
  colorClass: string;
  sparkline?: number[];
}) {
  return (
    <div className="rounded-lg border bg-card p-4 transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Icon className="size-4" />
          <span className="text-xs font-medium">{label}</span>
        </div>
        {sparkline && (
          <SparklineChart
            data={sparkline}
            color="#3b82f6"
            width={56}
            height={20}
          />
        )}
      </div>
      <div className="mt-2">
        <span className={cn("text-2xl font-bold tabular-nums", colorClass)}>
          {value}
        </span>
      </div>
    </div>
  );
}

function LearningCurveTab({
  data,
}: {
  data: LearningCurvePoint[] | null;
}) {
  const { t } = useI18n();

  if (!data || data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border text-xs text-muted-foreground">
        {t.evolutionDashboard.noLearningData}
      </div>
    );
  }

  const padL = 45;
  const padR = 15;
  const padT = 15;
  const padB = 35;
  const svgW = 600;
  const svgH = 280;
  const chartW = svgW - padL - padR;
  const chartH = svgH - padT - padB;

  const yTicks = [0, 25, 50, 75, 100];

  const xStep = data.length > 1 ? chartW / (data.length - 1) : 0;

  const pts = data.map((d, i) => ({
    x: padL + (data.length > 1 ? i * xStep : chartW / 2),
    y: padT + chartH - numberOrZero(d.success_rate) * chartH,
  }));

  const polylineStr = pts
    .map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`)
    .join(" ");

  const avgSuccess =
    data.reduce((s, d) => s + numberOrZero(d.success_rate), 0) / data.length;
  const avgDuration =
    data.reduce((s, d) => s + numberOrZero(d.avg_duration_ms), 0) / data.length;
  const totalSkills = data.reduce((s, d) => s + numberOrZero(d.skills_used), 0);

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card p-4">
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full text-muted-foreground"
          preserveAspectRatio="xMidYMid meet"
        >
          {yTicks.map((v) => {
            const y = padT + chartH - (v / 100) * chartH;
            return (
              <g key={v}>
                <line
                  x1={padL}
                  y1={y}
                  x2={svgW - padR}
                  y2={y}
                  stroke="currentColor"
                  strokeOpacity={0.1}
                />
                <text
                  x={padL - 6}
                  y={y + 3}
                  textAnchor="end"
                  fill="currentColor"
                  fontSize={10}
                >
                  {v}%
                </text>
              </g>
            );
          })}

          <line
            x1={padL}
            y1={padT + chartH}
            x2={svgW - padR}
            y2={padT + chartH}
            stroke="currentColor"
            strokeOpacity={0.15}
          />

          {data.map((d, i) => {
            const x = padL + (data.length > 1 ? i * xStep : chartW / 2);
            const showLabel = data.length <= 8 || i % 2 === 0;
            return (
              <text
                key={d.week}
                x={x}
                y={svgH - 6}
                textAnchor="middle"
                fill="currentColor"
                fontSize={10}
                opacity={showLabel ? 1 : 0}
              >
                {d.week}
              </text>
            );
          })}

          {data.length > 1 && (
            <polyline
              points={polylineStr}
              fill="none"
              stroke="#10b981"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {pts.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={3.5}
              fill="#10b981"
              stroke="white"
              strokeWidth={1.5}
            />
          ))}
        </svg>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <MiniStat label="Avg Success Rate" value={`${fixed(avgSuccess * 100, 1)}%`} />
        <MiniStat
          label="Avg Duration"
          value={
            avgDuration >= 1000
              ? `${fixed(avgDuration / 1000, 1)}s`
              : `${Math.round(avgDuration)}ms`
          }
        />
        <MiniStat label="Total Skills Used" value={String(totalSkills)} />
      </div>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function SkillsPerformanceTab({
  data,
}: {
  data: SkillPerformance[] | null;
}) {
  const { t } = useI18n();

  const sorted = useMemo(() => {
    if (!data) return [];
    return [...data].sort((a, b) => numberOrZero(b.usage_count) - numberOrZero(a.usage_count));
  }, [data]);

  if (!data || data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border text-xs text-muted-foreground">
        {t.evolutionDashboard.noSkillData}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border/40 overflow-hidden">
      <table className="w-full text-[11px]">
        <thead className="bg-muted/50 text-muted-foreground">
          <tr>
            <th className="text-left px-2 py-1">
              {t.evolutionDashboard.skillName}
            </th>
            <th className="text-right px-2 py-1">
              {t.evolutionDashboard.usageCount}
            </th>
            <th className="text-right px-2 py-1">
              {t.evolutionDashboard.successRate}
            </th>
            <th className="text-right px-2 py-1">Avg Cost</th>
            <th className="text-left px-2 py-1">Source</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((s) => (
            <tr key={s.name} className="border-t border-border/30">
              <td className="px-2 py-1 font-medium">{s.name}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {numberOrZero(s.usage_count)}
              </td>
              <td
                className={cn(
                  "px-2 py-1 text-right tabular-nums",
                  successRateClass(numberOrZero(s.success_rate)),
                )}
              >
                {fixed(numberOrZero(s.success_rate) * 100, 0)}%
              </td>
              <td className="px-2 py-1 text-right tabular-nums text-muted-foreground">
                ${fixed(s.avg_cost_usd, 4)}
              </td>
              <td className="px-2 py-1 text-muted-foreground">{s.source}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecommendationsTab({
  data,
}: {
  data: Recommendation[] | null;
}) {
  const { t } = useI18n();

  if (!data || data.length === 0) {
    return (
      <div className="flex h-48 items-center justify-center rounded-lg border text-xs text-muted-foreground">
        <div className="text-center">
          <LightbulbIcon className="mx-auto mb-2 size-6 text-emerald-500" />
          {t.evolutionDashboard.noRecommendations}
        </div>
      </div>
    );
  }

  const severityIcon: Record<string, React.ElementType> = {
    info: InfoIcon,
    warning: AlertTriangleIcon,
    critical: AlertTriangleIcon,
  };

  const severityColor: Record<string, string> = {
    info: "text-blue-500",
    warning: "text-amber-500",
    critical: "text-red-500",
  };

  const severityBorder: Record<string, string> = {
    info: "border-l-blue-500",
    warning: "border-l-amber-500",
    critical: "border-l-red-500",
  };

  const severityBg: Record<string, string> = {
    info: "bg-blue-50/50 dark:bg-blue-950/20",
    warning: "bg-amber-50/50 dark:bg-amber-950/20",
    critical: "bg-red-50/50 dark:bg-red-950/20",
  };

  return (
    <div className="space-y-3">
      {data.map((rec, i) => {
        const Icon = severityIcon[rec.severity] ?? InfoIcon;
        return (
          <div
            key={i}
            className={cn(
              "rounded-lg border border-l-4 p-4",
              severityBorder[rec.severity] ?? severityBorder.info,
              severityBg[rec.severity] ?? severityBg.info,
            )}
          >
            <div className="flex items-start gap-3">
              <Icon
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  severityColor[rec.severity] ?? severityColor.info,
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium">{rec.title}</div>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                  {rec.description}
                </p>
                {rec.action_label && (
                  <button
                    type="button"
                    className="mt-2 inline-flex items-center gap-1 rounded-lg bg-primary/10 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/20 transition-colors"
                  >
                    <ZapIcon className="size-3" />
                    {rec.action_label}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
