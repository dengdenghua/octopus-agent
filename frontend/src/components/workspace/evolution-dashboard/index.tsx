import React from "react";
import {
  BrainCircuitIcon,
  TrendingUpIcon,
  ActivityIcon,
  DatabaseIcon,
  Loader2Icon,
  BookOpenIcon,
  LightbulbIcon,
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
  const { t } = useI18n();
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
    totalSkills > 0 ||
    totalMemories > 0 ||
    learningEvents > 0 ||
    recommendationCount > 0;
  const stages = [
    {
      icon: ActivityIcon,
      title: t.evolutionDashboard.observeTasks,
      value: learningEvents,
      unit: t.evolutionDashboard.unitTimes,
      done: learningEvents > 0,
      description: t.evolutionDashboard.observeTasksDescription,
    },
    {
      icon: DatabaseIcon,
      title: t.evolutionDashboard.accumulateMemories,
      value: totalMemories,
      unit: t.evolutionDashboard.unitItems,
      done: totalMemories > 0,
      description: t.evolutionDashboard.accumulateMemoriesDescription,
    },
    {
      icon: BookOpenIcon,
      title: t.evolutionDashboard.formSkills,
      value: totalSkills,
      unit: t.evolutionDashboard.unitSkills,
      done: totalSkills > 0,
      description: t.evolutionDashboard.formSkillsDescription,
    },
    {
      icon: LightbulbIcon,
      title: t.evolutionDashboard.proposeImprovements,
      value: recommendationCount,
      unit: t.evolutionDashboard.unitSuggestions,
      done: recommendationCount > 0,
      description: t.evolutionDashboard.proposeImprovementsDescription,
    },
  ];

  return (
    <section className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
      <div className="rounded-xl border border-border-default bg-gradient-to-br from-primary/10 via-background to-background p-5">
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <BrainCircuitIcon className="size-4 text-primary" />
              {t.evolutionDashboard.recentEvolutionTitle}
            </div>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {hasEvidence
                ? t.evolutionDashboard.growthSummary(
                    totalMemories,
                    totalSkills,
                    learningEvents,
                  )
                : t.evolutionDashboard.noEvidenceDescription}
            </p>
          </div>
          <div className="shrink-0 rounded-lg border border-primary/20 bg-background/80 px-4 py-3 text-right shadow-[var(--shadow-xs)]">
            <div className="text-[11px] text-muted-foreground">
              {t.evolutionDashboard.overallImprovementLabel}
            </div>
            <div
              className={cn(
                "mt-1 text-3xl font-bold tabular-nums",
                scoreColor(improvementScore),
              )}
            >
              {improvementPct}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {t.evolutionDashboard.of100}
            </div>
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
          title={t.evolutionDashboard.autoExtractedSkills}
          value={autoSkills}
          detail={
            totalSkills > 0
              ? t.evolutionDashboard.autoExtractedSkillsShare(
                  formatPercent(autoSkills / Math.max(totalSkills, 1)),
                )
              : t.evolutionDashboard.waitingForSkillAccumulation
          }
        />
        <StoryMetric
          icon={DatabaseIcon}
          title={t.evolutionDashboard.reusableMemoryLibrary}
          value={totalMemories}
          detail={
            ruleCount > 0
              ? t.evolutionDashboard.ruleMemoryCount(ruleCount)
              : t.evolutionDashboard.memoryDetailDefault
          }
          sparkline={memorySparkline.length >= 2 ? memorySparkline : undefined}
        />
        <StoryMetric
          icon={LightbulbIcon}
          title={t.evolutionDashboard.nextSteps}
          value={recommendationCount}
          detail={
            recommendationCount > 0
              ? t.evolutionDashboard.nextStepsAvailable
              : t.evolutionDashboard.nextStepsNone
          }
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
          : "border-border-default bg-muted/25 text-muted-foreground",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "flex size-6 items-center justify-center rounded-full text-[11px] font-semibold",
              stage.done
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground",
            )}
          >
            {index}
          </span>
          <Icon className={cn("size-3.5", stage.done && "text-primary")} />
        </div>
        <span className="text-[11px] tabular-nums">
          {stage.value}
          {stage.unit}
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
    <div className="rounded-xl border border-border-default bg-card px-4 py-3">
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
        {sparkline && (
          <SparklineChart
            data={sparkline}
            color="#3b82f6"
            width={64}
            height={24}
          />
        )}
      </div>
    </div>
  );
}

function LearningStory({ data }: { data: LearningCurvePoint[] }) {
  const { t } = useI18n();
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border-default bg-card p-4">
        <SectionTitle
          icon={TrendingUpIcon}
          title={t.evolutionDashboard.capabilityTrend}
        />
        <EmptyStory text={t.evolutionDashboard.noTrendYet} />
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
    compact.reduce(
      (sum, point) => sum + numberOrZero(point.avg_duration_ms),
      0,
    ) / compact.length;

  return (
    <section className="rounded-xl border border-border-default bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <SectionTitle
          icon={TrendingUpIcon}
          title={t.evolutionDashboard.capabilityTrend}
        />
        <div className="text-right">
          <div
            className={cn(
              "text-sm font-semibold tabular-nums",
              delta >= 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-600 dark:text-red-400",
            )}
          >
            {delta >= 0 ? "+" : ""}
            {formatPercent(delta, 0)}
          </div>
          <div className="text-[11px] text-muted-foreground">
            {t.evolutionDashboard.recentChange}
          </div>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <MiniStat
          label={t.evolutionDashboard.currentSuccessRate}
          value={formatPercent(lastRate, 0)}
        />
        <MiniStat
          label={t.evolutionDashboard.avgDuration}
          value={
            avgDuration >= 1000
              ? `${fixed(avgDuration / 1000, 1)}s`
              : `${Math.round(avgDuration)}ms`
          }
        />
        <MiniStat
          label={t.evolutionDashboard.recentSkillCalls}
          value={String(
            compact.reduce(
              (sum, point) => sum + numberOrZero(point.skills_used),
              0,
            ),
          )}
        />
      </div>

      <div className="mt-4 flex items-end gap-2 overflow-hidden rounded-lg border border-border-subtle bg-muted/20 px-3 py-3">
        {compact.map((point) => {
          const rate = numberOrZero(point.success_rate);
          return (
            <div
              key={point.week}
              className="flex min-w-0 flex-1 flex-col items-center gap-2"
            >
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
              <div className="truncate text-[10px] text-muted-foreground">
                {point.week}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function SkillStory({ data }: { data: SkillPerformance[] }) {
  const { t } = useI18n();
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border-default bg-card p-4">
        <SectionTitle
          icon={BrainCircuitIcon}
          title={t.evolutionDashboard.strongerSkills}
        />
        <EmptyStory text={t.evolutionDashboard.noSkillPerformanceYet} />
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border-default bg-card p-4">
      <SectionTitle
        icon={BrainCircuitIcon}
        title={t.evolutionDashboard.strongerSkills}
      />
      <div className="mt-4 space-y-3">
        {data.map((skill) => {
          const rate = numberOrZero(skill.success_rate);
          return (
            <div key={skill.name} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate font-medium">
                  {skill.name}
                </span>
                <span
                  className={cn(
                    "shrink-0 tabular-nums",
                    successRateClass(rate),
                  )}
                >
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
                <span>
                  {t.evolutionDashboard.skillCalls(
                    numberOrZero(skill.usage_count),
                  )}
                </span>
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
  const { t } = useI18n();
  if (data.length === 0) {
    return (
      <section className="rounded-xl border border-border-default bg-card p-4">
        <SectionTitle
          icon={LightbulbIcon}
          title={t.evolutionDashboard.howToImproveNext}
        />
        <EmptyStory text={t.evolutionDashboard.noPendingRecommendations} />
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border-default bg-card p-4">
      <SectionTitle
        icon={LightbulbIcon}
        title={t.evolutionDashboard.howToImproveNext}
      />
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        {data.slice(0, 3).map((rec, index) => (
          <div
            key={`${rec.title}-${index}`}
            className="rounded-lg border border-border-default bg-muted/20 px-3 py-3"
          >
            <div className="flex items-center gap-2">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
                {index + 1}
              </span>
              <span className="min-w-0 truncate text-sm font-semibold">
                {rec.title}
              </span>
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

function SectionTitle({
  icon: Icon,
  title,
}: {
  icon: React.ElementType;
  title: string;
}) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold">
      <Icon className="size-4 text-primary" />
      {title}
    </div>
  );
}

function EmptyStory({ text }: { text: string }) {
  return (
    <div className="mt-4 rounded-lg border border-dashed border-border-default bg-muted/20 px-4 py-6 text-center text-xs leading-relaxed text-muted-foreground">
      {text}
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
