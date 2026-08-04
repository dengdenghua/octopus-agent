import {
  RefreshCwIcon,
  PlayCircleIcon,
  ClipboardCheckIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  BrowserDesktopReplayReviewCard,
  ReplayEvidenceDrilldownCard,
  ReplayGateCard,
} from "@/components/workspace/replay-panel";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import {
  AgentTraceRequestError,
  applyAgentTraceReviewQueuePromotions,
  fetchAgentTraceReplayCases,
  fetchAgentTraceReplayEvaluations,
  fetchAgentTraceReplayGate,
  fetchAgentTraceReviewQueue,
  fetchBrowserDesktopQuality,
  fetchBrowserDesktopRepairRecipeVerifications,
  fetchBrowserDesktopRepairRecipes,
  queueBrowserDesktopRepairRecipes,
  queueComputerActivityReplayCase,
  queueLatestBrowserSessionReplayCase,
  queueReplayEvidenceHint,
  rejectStaleBrowserDesktopReplayArtifacts,
  rerunBrowserDesktopRepairRecipeEvidenceBatch,
  type AgentTraceReplayCase,
  type AgentTraceReplayEvaluation,
  type AgentTraceReplayGate,
  type AgentTraceReviewQueueItem,
  type BrowserDesktopQualityReport,
  type BrowserDesktopRepairRecipeVerificationsReport,
  type BrowserDesktopRepairRecipesReport,
  type ReplayEvidenceHint,
} from "@/core/agent-trace/api";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

const EMPTY_REPLAY_GATE: AgentTraceReplayGate = {
  schema: "octopus.replay_gate.v1",
  passed: false,
  reason: "Waiting for replay evaluations",
  thresholds: { min_cases: 1, min_score: 1 },
  summary: { total: 0, passed: 0, failed: 0, below_min_score: 0 },
  failing_cases: [],
};

const EMPTY_BROWSER_DESKTOP_QUALITY: BrowserDesktopQualityReport = {
  schema: "octopus.browser_desktop_quality.v1",
  score: 1,
  passed: 0,
  total: 0,
  ready: true,
  checks: [],
  replay_trends: {
    schema: "octopus.browser_desktop_replay_trends.v1",
    total: 0,
    pending_count: 0,
    reviewed_count: 0,
    promoted_count: 0,
    rejected_count: 0,
    review_rate: 0,
    stale_source_artifact_count: 0,
    by_status: {},
    by_candidate_kind: {},
    latest: [],
    next_actions: [],
  },
  next_actions: [],
};

const EMPTY_REPAIR_RECIPES: BrowserDesktopRepairRecipesReport = {
  schema: "octopus.browser_desktop_repair_recipes.v1",
  total_pending_cases: 0,
  recipe_count: 0,
  recipes: [],
  ready: true,
  next_actions: [],
};

const EMPTY_REPAIR_VERIFICATIONS: BrowserDesktopRepairRecipeVerificationsReport =
  {
    schema: "octopus.browser_desktop_repair_recipe_verifications.v1",
    total: 0,
    verified_count: 0,
    blocked_count: 0,
    ready: true,
    verifications: [],
    next_actions: [],
  };

export default function ReplayPage() {
  const { t } = useI18n();
  const [replayGate, setReplayGate] =
    useState<AgentTraceReplayGate>(EMPTY_REPLAY_GATE);
  const [browserDesktopItems, setBrowserDesktopItems] = useState<
    AgentTraceReviewQueueItem[]
  >([]);
  const [browserDesktopTotal, setBrowserDesktopTotal] = useState(0);
  const [browserDesktopQuality, setBrowserDesktopQuality] =
    useState<BrowserDesktopQualityReport>(EMPTY_BROWSER_DESKTOP_QUALITY);
  const [repairRecipes, setRepairRecipes] =
    useState<BrowserDesktopRepairRecipesReport>(EMPTY_REPAIR_RECIPES);
  const [repairVerifications, setRepairVerifications] =
    useState<BrowserDesktopRepairRecipeVerificationsReport>(
      EMPTY_REPAIR_VERIFICATIONS,
    );
  const [replayCases, setReplayCases] = useState<AgentTraceReplayCase[]>([]);
  const [replayEvaluations, setReplayEvaluations] = useState<
    AgentTraceReplayEvaluation[]
  >([]);
  const [replayEvidence, setReplayEvidence] =
    useState<ReplayEvidenceHint | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [browserBusy, setBrowserBusy] = useState(false);
  const [desktopBusy, setDesktopBusy] = useState(false);
  const [recipeBusy, setRecipeBusy] = useState(false);
  const [rerunBusy, setRerunBusy] = useState(false);
  const [staleBusy, setStaleBusy] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastApplyResult, setLastApplyResult] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [
        gate,
        browserDesktopQueue,
        quality,
        recipes,
        verifications,
        cases,
        evaluations,
      ] = await Promise.all([
        fetchAgentTraceReplayGate({ status: "completed" }),
        fetchAgentTraceReviewQueue(20, 0, {
          status: "pending",
          targetBucket: "browser_desktop_replay",
        }),
        fetchBrowserDesktopQuality(),
        fetchBrowserDesktopRepairRecipes(),
        fetchBrowserDesktopRepairRecipeVerifications(),
        fetchAgentTraceReplayCases({ limit: 50 }),
        fetchAgentTraceReplayEvaluations({ limit: 50 }),
      ]);
      setReplayGate(gate);
      setBrowserDesktopItems(browserDesktopQueue);
      setBrowserDesktopTotal(browserDesktopQueue.length);
      setBrowserDesktopQuality(quality);
      setRepairRecipes(recipes);
      setRepairVerifications(verifications);
      setReplayCases(cases.cases);
      setReplayEvaluations(evaluations.evaluations);
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleQueueBrowser = useCallback(async () => {
    setBrowserBusy(true);
    try {
      await queueLatestBrowserSessionReplayCase();
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBrowserBusy(false);
    }
  }, [refresh]);

  const handleQueueDesktop = useCallback(async () => {
    setDesktopBusy(true);
    try {
      await queueComputerActivityReplayCase();
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDesktopBusy(false);
    }
  }, [refresh]);

  const handleQueueRecipes = useCallback(async () => {
    setRecipeBusy(true);
    try {
      await queueBrowserDesktopRepairRecipes();
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRecipeBusy(false);
    }
  }, [refresh]);

  const handleRejectStale = useCallback(async () => {
    setStaleBusy(true);
    try {
      await rejectStaleBrowserDesktopReplayArtifacts();
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStaleBusy(false);
    }
  }, [refresh]);

  const handleRerunBlocked = useCallback(async () => {
    setRerunBusy(true);
    try {
      const result = await rerunBrowserDesktopRepairRecipeEvidenceBatch({
        promoteSourceCases: false,
        actor: "replay_workspace",
      });
      setLastApplyResult(
        t.replay.rerunResult(
          result.attempted,
          result.passed,
          result.failed,
        ),
      );
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRerunBusy(false);
    }
  }, [refresh, t]);

  const handleQueueEvidence = useCallback(async () => {
    if (!replayEvidence) return;
    setEvidenceBusy(true);
    try {
      await queueReplayEvidenceHint(replayEvidence);
      setReplayEvidence(null);
      await refresh();
    } catch (err: unknown) {
      if (err instanceof AgentTraceRequestError) {
        setError(err.message);
      } else {
        swallow(err);
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setEvidenceBusy(false);
    }
  }, [replayEvidence, refresh]);

  const handleApplyPromotions = useCallback(async () => {
    setBusy(true);
    setLastApplyResult(null);
    try {
      const result = await applyAgentTraceReviewQueuePromotions({
        target: "browser_desktop_replay",
        limit: 20,
      });
      setLastApplyResult(
        t.replay.applyResult(
          result.applied,
          result.skipped,
          result.failed,
        ),
      );
      await refresh();
    } catch (err: unknown) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [refresh, t]);

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="px-4 pb-4">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-4">
          <section className="workspace-panel px-4 py-4 sm:px-6 sm:py-5">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="flex min-w-0 items-start gap-4 sm:items-center">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-[var(--shadow-xs)]">
                  <PlayCircleIcon className="size-5" />
                </div>
                <div className="min-w-0">
                  <h1 className="text-xl sm:text-2xl font-bold tracking-tight">
                    {t.sidebar.navReplay}
                  </h1>
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    {t.replay.pageDescription}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2 md:justify-end">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 whitespace-nowrap"
                  disabled={busy}
                  onClick={() => void handleApplyPromotions()}
                >
                  <ClipboardCheckIcon className="mr-2 size-4" />
                  {t.replay.applyPromotions}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 whitespace-nowrap"
                  disabled={loading}
                  onClick={() => void refresh()}
                >
                  <RefreshCwIcon
                    className={cn("mr-2 size-4", loading && "animate-spin")}
                  />
                  {t.replay.refresh}
                </Button>
              </div>
            </div>
            {lastApplyResult && (
              <div className="mt-3 rounded-md border border-success/25 bg-success/10 px-3 py-2 text-xs text-success">
                {lastApplyResult}
              </div>
            )}
            {error && (
              <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                {error}
              </div>
            )}
          </section>

          <section className="workspace-panel px-4 py-4 sm:px-5 sm:py-5">
            <ReplayGateCard gate={replayGate} />
            {replayEvidence && (
              <ReplayEvidenceDrilldownCard
                evidence={replayEvidence}
                busy={evidenceBusy}
                onQueue={() => void handleQueueEvidence()}
              />
            )}
            <BrowserDesktopReplayReviewCard
              items={browserDesktopItems}
              total={browserDesktopTotal}
              quality={browserDesktopQuality}
              repairRecipes={repairRecipes}
              repairVerifications={repairVerifications}
              browserBusy={browserBusy}
              desktopBusy={desktopBusy}
              recipeBusy={recipeBusy}
              rerunBusy={rerunBusy}
              staleBusy={staleBusy}
              onQueueBrowser={() => void handleQueueBrowser()}
              onQueueDesktop={() => void handleQueueDesktop()}
              onQueueRepairRecipes={() => void handleQueueRecipes()}
              onRerunBlocked={() => void handleRerunBlocked()}
              onRejectStale={() => void handleRejectStale()}
            />
          </section>

          <section className="workspace-panel px-4 py-4 sm:px-5 sm:py-5">
            <Tabs defaultValue="cases" className="flex flex-col gap-4">
              <TabsList className="h-9 w-fit rounded-lg">
                <TabsTrigger value="cases" className="h-8 gap-1.5 px-3 text-xs">
                  <PlayCircleIcon className="size-3.5" />
                  {t.replay.tabCases(replayCases.length)}
                </TabsTrigger>
                <TabsTrigger
                  value="evaluations"
                  className="h-8 gap-1.5 px-3 text-xs"
                >
                  <ClipboardCheckIcon className="size-3.5" />
                  {t.replay.tabEvaluations(replayEvaluations.length)}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="cases" className="mt-0">
                <ReplayCasesTable cases={replayCases} loading={loading} />
              </TabsContent>

              <TabsContent value="evaluations" className="mt-0">
                <ReplayEvaluationsTable
                  evaluations={replayEvaluations}
                  loading={loading}
                />
              </TabsContent>
            </Tabs>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function ReplayCasesTable({
  cases,
  loading,
}: {
  cases: AgentTraceReplayCase[];
  loading: boolean;
}) {
  const { t } = useI18n();
  if (loading && cases.length === 0) {
    return (
      <div className="rounded-md border border-border-default bg-muted/15 px-3 py-4 text-xs text-muted-foreground">
        {t.replay.loadingCases}
      </div>
    );
  }
  if (cases.length === 0) {
    return (
      <div className="rounded-md border border-border-default bg-muted/15 px-3 py-4 text-xs text-muted-foreground">
        {t.replay.emptyCases}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto max-w-full">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-border-default text-muted-foreground">
          <tr>
            <th className="px-2 py-2 font-medium">case_id</th>
            <th className="px-2 py-2 font-medium">fingerprint</th>
            <th className="px-2 py-2 font-medium">task_id</th>
            <th className="px-2 py-2 font-medium">status</th>
            <th className="px-2 py-2 font-medium">steps</th>
            <th className="px-2 py-2 font-medium">replayable</th>
            <th className="px-2 py-2 font-medium">resume</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => (
            <tr
              key={item.case_id}
              className="border-b border-border-subtle align-top"
            >
              <td className="px-2 py-2 font-mono text-xs">
                {item.case_id}
              </td>
              <td className="px-2 py-2 font-mono text-xs text-muted-foreground">
                {item.fingerprint}
              </td>
              <td className="px-2 py-2 font-mono text-xs text-muted-foreground">
                {item.source.task_id ?? "—"}
              </td>
              <td className="px-2 py-2">
                <Badge variant="outline" className="text-xs">
                  {item.source.status ?? "—"}
                </Badge>
              </td>
              <td className="px-2 py-2 font-mono text-xs">
                {item.replay.step_count ?? 0}
              </td>
              <td className="px-2 py-2">
                <Badge
                  variant="outline"
                  className={cn(
                    "text-xs",
                    item.replay.replayable
                      ? "border-success/30 bg-success/10 text-success"
                      : "border-muted bg-muted/20 text-muted-foreground",
                  )}
                >
                  {item.replay.replayable ? "yes" : "no"}
                </Badge>
              </td>
              <td className="px-2 py-2">
                <Badge
                  variant="outline"
                  className={cn(
                    "text-xs",
                    item.resume.available
                      ? "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300"
                      : "border-muted bg-muted/20 text-muted-foreground",
                  )}
                >
                  {item.resume.available ? "available" : "n/a"}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReplayEvaluationsTable({
  evaluations,
  loading,
}: {
  evaluations: AgentTraceReplayEvaluation[];
  loading: boolean;
}) {
  const { t } = useI18n();
  if (loading && evaluations.length === 0) {
    return (
      <div className="rounded-md border border-border-default bg-muted/15 px-3 py-4 text-xs text-muted-foreground">
        {t.replay.loadingEvaluations}
      </div>
    );
  }
  if (evaluations.length === 0) {
    return (
      <div className="rounded-md border border-border-default bg-muted/15 px-3 py-4 text-xs text-muted-foreground">
        {t.replay.emptyEvaluations}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto max-w-full">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-border-default text-muted-foreground">
          <tr>
            <th className="px-2 py-2 font-medium">case_id</th>
            <th className="px-2 py-2 font-medium">fingerprint</th>
            <th className="px-2 py-2 font-medium">passed</th>
            <th className="px-2 py-2 font-medium">score</th>
            <th className="px-2 py-2 font-medium">checks</th>
            <th className="px-2 py-2 font-medium">task_id</th>
          </tr>
        </thead>
        <tbody>
          {evaluations.map((item) => (
            <tr
              key={item.case_id}
              className="border-b border-border-subtle align-top"
            >
              <td className="px-2 py-2 font-mono text-xs">
                {item.case_id}
              </td>
              <td className="px-2 py-2 font-mono text-xs text-muted-foreground">
                {item.fingerprint}
              </td>
              <td className="px-2 py-2">
                <Badge
                  variant="outline"
                  className={cn(
                    "text-xs",
                    item.passed
                      ? "border-success/30 bg-success/10 text-success"
                      : "border-destructive/30 bg-destructive/10 text-destructive",
                  )}
                >
                  {item.passed ? "pass" : "fail"}
                </Badge>
              </td>
              <td className="px-2 py-2 font-mono text-xs">
                {item.score.toFixed(3)}
              </td>
              <td className="px-2 py-2">
                <div className="flex flex-wrap gap-1">
                  {item.checks.map((check) => (
                    <Badge
                      key={check.name}
                      variant="outline"
                      className={cn(
                        "text-xs",
                        check.passed
                          ? "border-success/25 bg-success/5 text-success"
                          : "border-destructive/25 bg-destructive/5 text-destructive",
                      )}
                      title={check.description}
                    >
                      {check.passed ? "✓" : "✗"} {check.name}
                    </Badge>
                  ))}
                </div>
              </td>
              <td className="px-2 py-2 font-mono text-xs text-muted-foreground">
                {item.source.task_id ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
