import { useQuery } from "@tanstack/react-query";
import {
  ActivityIcon,
  CheckCircle2Icon,
  DnaIcon,
  GitCompareArrowsIcon,
  RefreshCwIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  coderUpstreamUpdateQueryKey,
  getCoderUpstreamUpdate,
} from "@/core/coder/api";
import {
  getAgentBenchmarkReport,
  getCodexGapReport,
  getDualHelixEvidence,
  getDualHelixShadowStatus,
} from "@/core/evolution/api";
import { useCanary, useLedger } from "@/core/evolution/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const helixQueryKey = ["evolution", "dual-helix"] as const;
const shadowQueryKey = [...helixQueryKey, "shadow"] as const;

function percent(value?: number) {
  return `${Math.round(Math.max(0, Math.min(1, value ?? 0)) * 100)}%`;
}

const ZH_ACTIONS: Record<string, string> = {
  "Add automatic repair-route promotion evidence for repeated verifier drift.":
    "为重复出现的验证偏移补充自动修复路线晋升证据。",
  "Add threat-model regression cases for every high-risk tool class.":
    "为每类高风险工具补齐威胁模型回归用例。",
  "Surface signed policy-review rule drafts in the operator panel.":
    "在运行监控中展示已签名的策略评审规则草案。",
};

function localizeAction(action: string, zh: boolean) {
  return zh ? (ZH_ACTIONS[action] ?? action) : action;
}

function localizeVerdict(verdict: string | undefined, zh: boolean) {
  if (!verdict) return "—";
  if (!zh) return verdict;
  return verdict === "differentiated" ? "已形成差异化" : verdict;
}

function ScoreBar({ value, tone }: { value: number; tone: "cyan" | "violet" }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-500",
          tone === "cyan" ? "bg-cyan-500" : "bg-violet-500",
        )}
        style={{ width: percent(value) }}
      />
    </div>
  );
}

function EngineCard({
  name,
  label,
  value,
  score,
  tone,
  detail,
}: {
  name: string;
  label: string;
  value: string;
  score: number;
  tone: "cyan" | "violet";
  detail: string;
}) {
  return (
    <article
      className={cn(
        "rounded-xl border bg-card p-4",
        tone === "cyan" ? "border-cyan-500/25" : "border-violet-500/25",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            {label}
          </div>
          <h3 className="mt-1 text-sm font-semibold">{name}</h3>
        </div>
        <span
          className={cn(
            "rounded-full px-2 py-1 font-mono text-[10px]",
            tone === "cyan"
              ? "bg-cyan-500/10 text-cyan-600 dark:text-cyan-300"
              : "bg-violet-500/10 text-violet-600 dark:text-violet-300",
          )}
        >
          {value}
        </span>
      </div>
      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{detail}</span>
        <span className="font-mono font-semibold">{percent(score)}</span>
      </div>
      <div className="mt-2">
        <ScoreBar value={score} tone={tone} />
      </div>
    </article>
  );
}

function HelixBridge() {
  return (
    <div
      className="relative hidden min-h-40 items-center justify-center md:flex"
      aria-hidden="true"
    >
      <div className="absolute h-[82%] w-px -rotate-[16deg] bg-gradient-to-b from-cyan-500 via-foreground/25 to-violet-500" />
      <div className="absolute h-[82%] w-px rotate-[16deg] bg-gradient-to-b from-violet-500 via-foreground/25 to-cyan-500" />
      <div className="z-10 grid size-12 place-items-center rounded-full border bg-background shadow-sm">
        <DnaIcon className="size-5 text-primary" />
      </div>
    </div>
  );
}

export function DualHelixEvolutionPanel({
  view = "overview",
}: {
  view?: "overview" | "evidence";
}) {
  const { locale } = useI18n();
  const zh = locale.toLowerCase().startsWith("zh");
  const gap = useQuery({
    queryKey: [...helixQueryKey, "gap"],
    queryFn: getCodexGapReport,
    staleTime: 60_000,
  });
  const benchmark = useQuery({
    queryKey: [...helixQueryKey, "benchmark"],
    queryFn: getAgentBenchmarkReport,
    staleTime: 60_000,
  });
  const paired = useQuery({
    queryKey: [...helixQueryKey, "paired-evidence"],
    queryFn: getDualHelixEvidence,
    staleTime: 30_000,
  });
  const shadow = useQuery({
    queryKey: shadowQueryKey,
    queryFn: getDualHelixShadowStatus,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
  const upstream = useQuery({
    queryKey: coderUpstreamUpdateQueryKey,
    queryFn: ({ signal }) => getCoderUpstreamUpdate(signal),
    staleTime: 60_000,
  });
  const ledger = useLedger({ limit: 8 });
  const canary = useCanary();
  const refreshing =
    gap.isFetching ||
    benchmark.isFetching ||
    paired.isFetching ||
    shadow.isFetching ||
    upstream.isFetching;
  const refresh = () => {
    void Promise.all([
      gap.refetch(),
      benchmark.refetch(),
      paired.refetch(),
      shadow.refetch(),
      upstream.refetch(),
    ]);
  };
  const capabilities = gap.data?.capabilities ?? [];
  const gaps = capabilities
    .filter((item) => item.score < item.target_score)
    .sort((a, b) => a.score - b.score)
    .slice(0, 3);
  const nextActions = (gaps.length ? gaps : capabilities)
    .flatMap((item) => item.next_actions ?? [])
    .slice(0, 3);
  const error =
    gap.error ??
    benchmark.error ??
    paired.error ??
    shadow.error ??
    upstream.error;

  if (view === "evidence") {
    const pairs = paired.data?.pairs ?? [];
    const runs = shadow.data?.runs ?? [];
    return (
      <section className="space-y-3" aria-label="实验证据">
        <div className="rounded-xl border bg-gradient-to-br from-violet-500/[0.06] via-background to-cyan-500/[0.06] p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <GitCompareArrowsIcon className="size-4 text-primary" />
                双引擎实验证据
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                只展示真实任务配对、隔离影子复核和可追溯的进化记录。
              </p>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCwIcon
                className={cn("mr-1.5 size-3.5", refreshing && "animate-spin")}
              />
              刷新证据
            </Button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["真实配对", paired.data?.paired_count ?? 0],
              ["Octopus 胜出", paired.data?.octopus_wins ?? 0],
              ["Codex 胜出", paired.data?.codex_wins ?? 0],
              ["影子复核", runs.length],
            ].map(([label, value]) => (
              <div
                key={String(label)}
                className="rounded-lg border bg-card/80 px-3 py-2.5"
              >
                <div className="text-[11px] text-muted-foreground">{label}</div>
                <div className="mt-1 font-mono text-lg font-semibold">
                  {value}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-2">
          <article className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold">同任务双引擎对照</h3>
            <div className="mt-3 space-y-2">
              {pairs.length ? (
                pairs.map((pair) => (
                  <div
                    key={pair.goal_fingerprint}
                    className="rounded-lg border border-border-subtle bg-muted/25 px-3 py-2.5"
                  >
                    <div className="truncate text-xs font-medium">
                      {pair.goal}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[10px] text-muted-foreground">
                      <span className="rounded-full bg-cyan-500/10 px-2 py-0.5 text-cyan-700 dark:text-cyan-300">
                        Octopus · {pair.octopus.outcome}
                      </span>
                      <span>↔</span>
                      <span className="rounded-full bg-violet-500/10 px-2 py-0.5 text-violet-700 dark:text-violet-300">
                        Codex · {pair.codex.outcome}
                      </span>
                      <span className="ml-auto">
                        胜出：{pair.winner === "tie" ? "平局" : pair.winner}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-lg border border-dashed px-3 py-8 text-center text-xs text-muted-foreground">
                  暂无同任务双引擎样本。可在对话回答下方点击 DNA
                  按钮发起影子复核。
                </div>
              )}
            </div>
          </article>

          <article className="rounded-xl border bg-card p-4">
            <h3 className="text-sm font-semibold">影子复核记录</h3>
            <div className="mt-3 space-y-2">
              {runs.length ? (
                runs.map((run) => (
                  <div
                    key={run.run_id}
                    className="rounded-lg border border-border-subtle bg-muted/25 px-3 py-2.5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-xs font-medium">
                          {run.goal}
                        </div>
                        <div className="mt-1 text-[10px] text-muted-foreground">
                          {run.primary_engine} → {run.shadow_engine} ·
                          只读隔离副本
                        </div>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-2 py-0.5 text-[10px]",
                          run.status === "completed"
                            ? "bg-success/10 text-success"
                            : run.status === "failed"
                              ? "bg-destructive/10 text-destructive"
                              : "bg-primary/10 text-primary",
                        )}
                      >
                        {run.status}
                      </span>
                    </div>
                    {run.result || run.error ? (
                      <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-muted-foreground">
                        {run.result || run.error}
                      </p>
                    ) : null}
                  </div>
                ))
              ) : (
                <div className="rounded-lg border border-dashed px-3 py-8 text-center text-xs text-muted-foreground">
                  暂无影子复核记录。
                </div>
              )}
            </div>
          </article>
        </div>

        <article className="rounded-xl border bg-card p-4">
          <h3 className="text-sm font-semibold">进化账本</h3>
          <div className="mt-3 divide-y divide-border-subtle">
            {(ledger.data?.records ?? []).map((record) => (
              <div
                key={record.id}
                className="flex items-center gap-3 py-2 text-xs"
              >
                <span className="size-1.5 shrink-0 rounded-full bg-primary" />
                <span className="min-w-0 flex-1 truncate">
                  {record.description}
                </span>
                <span className="shrink-0 text-[10px] text-muted-foreground">
                  {record.status}
                </span>
              </div>
            ))}
            {!ledger.data?.records?.length ? (
              <div className="py-6 text-center text-xs text-muted-foreground">
                暂无进化账本记录。
              </div>
            ) : null}
          </div>
        </article>
        {error ? (
          <p role="alert" className="text-xs text-destructive">
            部分证据加载失败：
            {error instanceof Error ? error.message : String(error)}
          </p>
        ) : null}
      </section>
    );
  }

  return (
    <section
      className="space-y-3"
      aria-label={zh ? "双螺旋进化" : "Dual-helix evolution"}
    >
      <div className="overflow-hidden rounded-xl border border-border bg-gradient-to-br from-cyan-500/[0.06] via-background to-violet-500/[0.07] p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="grid size-8 place-items-center rounded-lg bg-primary/10 text-primary">
                <DnaIcon className="size-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold">
                  {zh ? "双引擎螺旋进化" : "Dual-engine helix evolution"}
                </h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {zh
                    ? "Codex 提供能力基线，Octopus 沉淀可验证的行为基因。"
                    : "Codex supplies the capability baseline; Octopus promotes verified behavior genes."}
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="rounded-full border bg-background/70 px-2.5 py-1 text-[10px] text-muted-foreground">
              {shadow.data?.enabled ? "保护模式已开启" : "保护模式已关闭"}
            </span>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={refresh}
              disabled={refreshing}
            >
              <RefreshCwIcon
                className={cn("mr-1.5 size-3.5", refreshing && "animate-spin")}
              />
              {zh ? "刷新进化证据" : "Refresh evidence"}
            </Button>
          </div>
        </div>

        <div className="mt-4 grid items-stretch gap-3 md:grid-cols-[1fr_80px_1fr]">
          <EngineCard
            name="Octopus Native"
            label={zh ? "行为基因链" : "Behavior gene strand"}
            value={localizeVerdict(gap.data?.verdict, zh)}
            score={gap.data?.advantage_score ?? 0}
            tone="cyan"
            detail={zh ? "差异化能力" : "Differentiated capability"}
          />
          <HelixBridge />
          <EngineCard
            name="OpenAI Codex"
            label={zh ? "能力基准链" : "Capability baseline strand"}
            value={`v${upstream.data?.current_version ?? "—"}`}
            score={gap.data?.parity_score ?? 0}
            tone="violet"
            detail={zh ? "能力对齐度" : "Capability parity"}
          />
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[
          [
            ShieldCheckIcon,
            zh ? "已验证能力" : "Verified capabilities",
            benchmark.data
              ? `${benchmark.data.passed}/${benchmark.data.total}`
              : "—",
          ],
          [
            DnaIcon,
            zh ? "真实任务样本" : "Live task samples",
            String(paired.data?.paired_count ?? 0),
          ],
          [
            ActivityIcon,
            zh ? "待验证候选" : "Pending candidates",
            String(canary.data?.active_count ?? 0),
          ],
          [
            SparklesIcon,
            zh ? "当前状态" : "Current status",
            benchmark.data && benchmark.data.passed === benchmark.data.total
              ? zh
                ? "稳定"
                : "Stable"
              : zh
                ? "观察中"
                : "Watching",
          ],
        ].map(([Icon, label, value]) => {
          const MetricIcon = Icon as typeof ActivityIcon;
          return (
            <div
              key={String(label)}
              className="rounded-xl border bg-card px-3 py-3"
            >
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <MetricIcon className="size-3.5" />
                {String(label)}
              </div>
              <div className="mt-2 font-mono text-lg font-semibold">
                {String(value)}
              </div>
            </div>
          );
        })}
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <article className="rounded-xl border bg-card p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <GitCompareArrowsIcon className="size-4 text-primary" />
            {zh ? "能力对照产生的下一代候选" : "Next-generation candidates"}
          </h3>
          <div className="mt-3 space-y-2">
            {nextActions.length ? (
              nextActions.map((action, index) => (
                <div
                  key={`${action}-${index}`}
                  className="flex gap-2 rounded-lg bg-muted/45 px-3 py-2 text-xs"
                >
                  <span className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full bg-primary/10 font-mono text-[9px] text-primary">
                    {index + 1}
                  </span>
                  <span className="leading-5">
                    {localizeAction(action, zh)}
                  </span>
                </div>
              ))
            ) : (
              <p className="rounded-lg bg-success/10 px-3 py-2 text-xs text-success">
                {zh
                  ? "当前能力基线没有未达标项，继续从真实任务中采集差异。"
                  : "No baseline gaps; continue collecting differences from live tasks."}
              </p>
            )}
          </div>
        </article>

        <article className="rounded-xl border bg-card p-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ActivityIcon className="size-4 text-primary" />
            {zh ? "最近进化证据" : "Recent evolution evidence"}
          </h3>
          <div className="mt-3 space-y-2">
            {(ledger.data?.records ?? []).slice(0, 4).map((record) => {
              const codex = /codex/i.test(
                `${record.description} ${record.proposer}`,
              );
              return (
                <div key={record.id} className="flex items-start gap-2 text-xs">
                  <span
                    className={cn(
                      "mt-1.5 size-1.5 shrink-0 rounded-full",
                      codex ? "bg-violet-500" : "bg-cyan-500",
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{record.description}</div>
                    <div className="mt-0.5 text-[10px] text-muted-foreground">
                      {codex ? "Codex" : "Octopus"} ·{" "}
                      {zh && record.status === "proposed"
                        ? "候选"
                        : record.status}
                    </div>
                  </div>
                </div>
              );
            })}
            {!ledger.data?.records?.length ? (
              <p className="text-xs text-muted-foreground">
                {zh ? "暂无任务证据。" : "No task evidence yet."}
              </p>
            ) : null}
          </div>
        </article>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card px-3 py-2.5 text-[10px] text-muted-foreground">
        {[
          zh ? "观察" : "Observe",
          zh ? "双引擎对照" : "Compare",
          zh ? "生成候选" : "Forge",
          zh ? "影子验证" : "Shadow",
          zh ? "灰度晋升" : "Promote",
        ].map((step, index) => (
          <div key={step} className="flex items-center gap-2">
            {index > 0 ? <span aria-hidden>→</span> : null}
            <span className="flex items-center gap-1.5 rounded-full bg-muted px-2 py-1">
              {index === 4 ? (
                <CheckCircle2Icon className="size-3 text-success" />
              ) : (
                <span className="size-1.5 rounded-full bg-primary/70" />
              )}
              {step}
            </span>
          </div>
        ))}
        <span className="ml-auto">
          {paired.data?.paired_count
            ? zh
              ? `${paired.data.paired_count} 对任务已完成实战互评 · `
              : `${paired.data.paired_count} live pairs reviewed · `
            : zh
              ? "等待同任务双引擎样本 · "
              : "Awaiting same-task engine samples · "}
          {upstream.data?.update_available
            ? zh
              ? `Codex v${upstream.data.latest_version} 待审核`
              : `Codex v${upstream.data.latest_version} awaiting review`
            : zh
              ? "Codex 上游已同步"
              : "Codex upstream synced"}
        </span>
      </div>

      <p className="px-1 text-[10px] text-muted-foreground">
        {shadow.data?.enabled
          ? zh
            ? "影子模式已授权：仅在明确提交影子任务时运行，使用隔离快照和只读权限。"
            : "Shadow mode is authorized only for explicitly submitted reviews, using isolated snapshots and read-only permissions."
          : zh
            ? "影子模式默认关闭；开启开关本身不会调用模型或产生费用。"
            : "Shadow mode is off by default; enabling it alone does not call a model or incur cost."}
      </p>

      {error ? (
        <p role="alert" className="text-xs text-destructive">
          {zh
            ? "部分进化证据加载失败："
            : "Some evolution evidence failed to load: "}
          {error instanceof Error ? error.message : String(error)}
        </p>
      ) : null}
    </section>
  );
}
