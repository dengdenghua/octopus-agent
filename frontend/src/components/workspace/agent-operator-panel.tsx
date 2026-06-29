import {
  ArchiveIcon,
  BarChart3Icon,
  CheckCircle2Icon,
  Clock3Icon,
  GitBranchIcon,
  ListChecksIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
  XCircleIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  AgentTraceRequestError,
  applyAgentTraceReviewQueuePromotions,
  decideAgentTraceReviewQueueItem,
  decideSubagentPolicy,
  fetchAgentCompetitorScorecard,
  fetchAgentTraceProcessTimeline,
  fetchAgentTracePolicyReviewRuleDrafts,
  fetchAgentTraceExperienceQualitySummary,
  fetchAgentTracePromotionAuditSummary,
  fetchAgentTraceReplayGate,
  fetchAgentTraceReviewQueue,
  fetchAgentTraceReviewQueueSummary,
  fetchAgentTraceTrustDenialSummary,
  fetchTaskRecoveryQueue,
  fetchAutomationPolicyRuleDrafts,
  fetchAutomationRadar,
  fetchAutoVerifierMetrics,
  fetchBrowserDesktopQuality,
  fetchBrowserDesktopRepairRecipeVerifications,
  fetchBrowserDesktopRepairRecipes,
  fetchRepairRouteQuality,
  fetchOrganizationTopologyLift,
  fetchOrganizationTopologyProposals,
  fetchAgentTraceTaskRuns,
  fetchOrganizationTopologies,
  fetchSubagentFitness,
  installAutomationPolicyRuleDraft,
  installAgentTracePolicyReviewRuleDraft,
  queueComputerActivityReplayCase,
  queueReplayEvidenceHint,
  queueAgentTraceTaskRunReview,
  queueAgentScorecardGaps,
  queueBrowserDesktopRepairRecipes,
  queueLatestBrowserSessionReplayCase,
  queueRepairRoutePromotionCandidates,
  rejectStaleBrowserDesktopReplayArtifacts,
  takeoverTaskRun,
  type AgentCompetitorScorecard,
  type AgentTraceProcessTimeline,
  type AgentTracePolicyReviewRuleDrafts,
  type AgentTraceExperienceQualitySummary,
  type AgentTracePromotionAuditSummary,
  type AgentTraceReplayGate,
  type AgentTraceReviewQueueItem,
  type AgentTraceReviewQueueSummary,
  type AgentTraceTaskRecoveryQueue,
  type AgentTraceTaskRun,
  type AgentTraceTrustDenialSummary,
  type AutomationPolicyRuleDraftsReport,
  type AutomationRadarReport,
  type AutoVerifierMetricsReport,
  type BrowserDesktopQualityReport,
  type BrowserDesktopRepairRecipesReport,
  type BrowserDesktopRepairRecipeVerificationsReport,
  type RepairRouteQualityReport,
  type ReplayEvidenceHint,
  type OrganizationTopology,
  type OrganizationTopologyLiftReport,
  type OrganizationTopologyProposalsReport,
  type SubagentFitnessReport,
} from "@/core/agent-trace/api";
import { fetchPluginSmokeSummary } from "@/core/plugins/api";
import type { PluginSmokeSummary } from "@/core/plugins/types";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";
import {
  BrowserDesktopReplayReviewCard,
  GateStat,
  ReplayEvidenceDrilldownCard,
  ReplayGateCard,
  StatusDot,
  priorityClass,
} from "./replay-panel";

const EMPTY_SUMMARY: AgentTraceReviewQueueSummary = {
  schema: "octopus.review_queue.v1",
  total: 0,
  pending_count: 0,
  by_status: {},
  by_priority: {},
  by_target_bucket: {},
  next_actions: [],
};

const EMPTY_TASK_RECOVERY_QUEUE: AgentTraceTaskRecoveryQueue = {
  schema: "octopus.task_recovery_queue.v1",
  total: 0,
  count: 0,
  limit: 8,
  items: [],
};

const EMPTY_AUDIT_SUMMARY: AgentTracePromotionAuditSummary = {
  schema: "octopus.promotion_audit_summary.v1",
  total: 0,
  by_status: {},
  by_target: {},
  by_event_type: {},
  integrity: {
    schema: "octopus.governance_audit_chain.v1",
    path: "",
    ok: true,
    entries_checked: 0,
    broken_at: null,
    error: "",
    details: [],
  },
  override_count: 0,
  gate_failed_count: 0,
  gate_blocked_override_count: 0,
  topology_policy_block_count: 0,
  latest: [],
};

const EMPTY_EXPERIENCE_QUALITY: AgentTraceExperienceQualitySummary = {
  schema: "octopus.experience_memory_quality_summary.v1",
  total: 0,
  active_count: 0,
  contradicted_count: 0,
  stale_count: 0,
  low_reliability_count: 0,
  avg_reliability: 0,
  by_bucket: {},
  top_risks: [],
  next_actions: [],
};

const EMPTY_SUBAGENT_FITNESS: SubagentFitnessReport = {
  schema: "octopus.subagent_fitness.v1",
  role: null,
  roles: [],
  role_count: 0,
  top_risks: [],
  next_actions: [],
};

const EMPTY_TOPOLOGY_PROPOSALS: OrganizationTopologyProposalsReport = {
  schema: "octopus.topology_proposals.merged.v1",
  count: 0,
  persisted_count: 0,
  subagent_promotion_count: 0,
  proposals: [],
};

const EMPTY_TOPOLOGY_LIFT: OrganizationTopologyLiftReport = {
  schema: "octopus.topology_promotion_lift.v1",
  count: 0,
  reports: [],
};

const EMPTY_AUTO_VERIFIER_METRICS: AutoVerifierMetricsReport = {
  schema: "octopus.auto_verifier_metrics.v1",
  total: 0,
  pass_count: 0,
  fail_count: 0,
  pass_rate: 0,
  avg_duration_ms: 0,
  families: [],
  alerts: [],
  top_failures: [],
  recent_decisions: [],
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

const EMPTY_AUTOMATION_RADAR: AutomationRadarReport = {
  schema: "octopus.automation_radar.v1",
  target_score: 95,
  scope: "browser_desktop_visual_automation",
  competitors: ["codex", "claude_code", "cursor", "octopus"],
  overall: {},
  ranking: [],
  verdict: "behind",
  dimensions: [],
  octopus_gaps: [],
  octopus_strengths: [],
  browser_desktop_quality: {
    schema: "octopus.browser_desktop_quality.v1",
    score: 0,
    passed: 0,
    total: 0,
    ready: false,
  },
  parity_certification: {
    schema: "octopus.parity_certification.v1",
    passed: 0,
    total: 0,
    ready: false,
  },
  policy_rule_drafts: {
    schema: "octopus.automation_policy_rule_drafts.v1",
    total: 0,
    verified: 0,
    ready: false,
  },
  next_focus: [],
};

const EMPTY_AUTOMATION_POLICY_RULE_DRAFTS: AutomationPolicyRuleDraftsReport = {
  schema: "octopus.automation_policy_rule_drafts.v1",
  total: 0,
  verified: 0,
  drafts: [],
};

const EMPTY_BROWSER_DESKTOP_REPAIR_RECIPES: BrowserDesktopRepairRecipesReport =
  {
    schema: "octopus.browser_desktop_repair_recipes.v1",
    total_pending_cases: 0,
    recipe_count: 0,
    recipes: [],
    ready: true,
    next_actions: [],
  };

const EMPTY_BROWSER_DESKTOP_REPAIR_VERIFICATIONS: BrowserDesktopRepairRecipeVerificationsReport =
  {
    schema: "octopus.browser_desktop_repair_recipe_verifications.v1",
    total: 0,
    verified_count: 0,
    blocked_count: 0,
    ready: true,
    verifications: [],
    next_actions: [],
  };

const EMPTY_REPAIR_ROUTE_QUALITY: RepairRouteQualityReport = {
  schema: "octopus.repair_route_quality.v1",
  score: 1,
  ready: true,
  quality_gate: {
    schema: "octopus.repair_route_quality_gate.v1",
    score: 1,
    ready: true,
    blockers: [],
    signals: {},
  },
  total_failures: 0,
  route_count: 0,
  routes: [],
  promotion_candidates: [],
  summary: {},
  recommendations: [],
};

const EMPTY_PLUGIN_SMOKE_SUMMARY: PluginSmokeSummary = {
  schema: "octopus.codex_plugin_smoke_summary.v1",
  total: 0,
  ok_count: 0,
  failed_count: 0,
  review_required_count: 0,
  warning_count: 0,
  failed: [],
  review_required: [],
  warnings: [],
  compatibility: {
    schema: "octopus.codex_plugin_compatibility.v1",
    verdict: "fail",
    passed: 0,
    total: 4,
    surface_totals: {},
    requirements: [],
    next_actions: [],
  },
};

const EMPTY_TRUST_DENIAL_SUMMARY: AgentTraceTrustDenialSummary = {
  schema: "octopus.trust_denial_summary.v1",
  total: 0,
  by_tool: {},
  by_action: {},
  recent: [],
};

const EMPTY_POLICY_REVIEW_RULE_DRAFTS: AgentTracePolicyReviewRuleDrafts = {
  schema: "octopus.policy_review_rule_drafts.v1",
  total: 0,
  verified: 0,
  drafts: [],
};

const EMPTY_AGENT_SCORECARD: AgentCompetitorScorecard = {
  schema: "octopus.agent_competitor_scorecard.v1",
  target_score: 90,
  competitors: ["codex", "claude_code", "cursor", "octopus"],
  overall: {},
  ranking: [],
  verdict: "behind",
  dimensions: [],
  octopus_below_target: [],
  octopus_strengths: [],
  next_focus: [],
};

interface ReplayGateOverridePrompt {
  gate: AgentTraceReplayGate;
  message: string;
}

export function AgentOperatorPanel() {
  const [taskRuns, setTaskRuns] = useState<AgentTraceTaskRun[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [timeline, setTimeline] = useState<AgentTraceProcessTimeline | null>(
    null,
  );
  const [queueItems, setQueueItems] = useState<AgentTraceReviewQueueItem[]>([]);
  const [browserDesktopQueueItems, setBrowserDesktopQueueItems] = useState<
    AgentTraceReviewQueueItem[]
  >([]);
  const [scorecardGapQueueItems, setScorecardGapQueueItems] = useState<
    AgentTraceReviewQueueItem[]
  >([]);
  const [queueSummary, setQueueSummary] =
    useState<AgentTraceReviewQueueSummary>(EMPTY_SUMMARY);
  const [taskRecoveryQueue, setTaskRecoveryQueue] =
    useState<AgentTraceTaskRecoveryQueue>(EMPTY_TASK_RECOVERY_QUEUE);
  const [auditSummary, setAuditSummary] =
    useState<AgentTracePromotionAuditSummary>(EMPTY_AUDIT_SUMMARY);
  const [experienceQuality, setExperienceQuality] =
    useState<AgentTraceExperienceQualitySummary>(EMPTY_EXPERIENCE_QUALITY);
  const [subagentFitness, setSubagentFitness] = useState<SubagentFitnessReport>(
    EMPTY_SUBAGENT_FITNESS,
  );
  const [topologies, setTopologies] = useState<OrganizationTopology[]>([]);
  const [topologyProposals, setTopologyProposals] =
    useState<OrganizationTopologyProposalsReport>(EMPTY_TOPOLOGY_PROPOSALS);
  const [topologyLift, setTopologyLift] =
    useState<OrganizationTopologyLiftReport>(EMPTY_TOPOLOGY_LIFT);
  const [autoVerifierMetrics, setAutoVerifierMetrics] =
    useState<AutoVerifierMetricsReport>(EMPTY_AUTO_VERIFIER_METRICS);
  const [browserDesktopQuality, setBrowserDesktopQuality] =
    useState<BrowserDesktopQualityReport>(EMPTY_BROWSER_DESKTOP_QUALITY);
  const [automationRadar, setAutomationRadar] = useState<AutomationRadarReport>(
    EMPTY_AUTOMATION_RADAR,
  );
  const [automationPolicyRuleDrafts, setAutomationPolicyRuleDrafts] =
    useState<AutomationPolicyRuleDraftsReport>(
      EMPTY_AUTOMATION_POLICY_RULE_DRAFTS,
    );
  const [browserDesktopRepairRecipes, setBrowserDesktopRepairRecipes] =
    useState<BrowserDesktopRepairRecipesReport>(
      EMPTY_BROWSER_DESKTOP_REPAIR_RECIPES,
    );
  const [
    browserDesktopRepairVerifications,
    setBrowserDesktopRepairVerifications,
  ] = useState<BrowserDesktopRepairRecipeVerificationsReport>(
    EMPTY_BROWSER_DESKTOP_REPAIR_VERIFICATIONS,
  );
  const [repairRouteQuality, setRepairRouteQuality] =
    useState<RepairRouteQualityReport>(EMPTY_REPAIR_ROUTE_QUALITY);
  const [pluginSmokeSummary, setPluginSmokeSummary] =
    useState<PluginSmokeSummary>(EMPTY_PLUGIN_SMOKE_SUMMARY);
  const [trustDenialSummary, setTrustDenialSummary] =
    useState<AgentTraceTrustDenialSummary>(EMPTY_TRUST_DENIAL_SUMMARY);
  const [policyRuleDrafts, setPolicyRuleDrafts] =
    useState<AgentTracePolicyReviewRuleDrafts>(EMPTY_POLICY_REVIEW_RULE_DRAFTS);
  const [agentScorecard, setAgentScorecard] =
    useState<AgentCompetitorScorecard>(EMPTY_AGENT_SCORECARD);
  const [scorecardError, setScorecardError] = useState<string | null>(null);
  const [replayGate, setReplayGate] = useState<AgentTraceReplayGate | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [lastApplyResult, setLastApplyResult] = useState<string | null>(null);
  const [overridePrompt, setOverridePrompt] =
    useState<ReplayGateOverridePrompt | null>(null);
  const [overrideReason, setOverrideReason] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorReplayEvidence, setErrorReplayEvidence] =
    useState<ReplayEvidenceHint | null>(null);

  const refreshQueue = useCallback(async () => {
    const [
      items,
      browserDesktopItems,
      scorecardGapItems,
      summary,
      recoveryQueue,
      gate,
      audit,
      memoryQuality,
      fitness,
      organizationTopologies,
      proposals,
      lift,
      autoVerifier,
      browserDesktopHealth,
      automationRadarReport,
      automationPolicyDrafts,
      browserRepairRecipes,
      browserRepairVerifications,
      repairRoutes,
      pluginSmoke,
      trustDenials,
      ruleDrafts,
      scorecardResult,
    ] = await Promise.all([
      fetchAgentTraceReviewQueue(12, 0, { status: "pending" }),
      fetchAgentTraceReviewQueue(6, 0, {
        status: "pending",
        targetBucket: "browser_desktop_replay",
      }),
      fetchAgentTraceReviewQueue(10, 0, {
        status: "pending",
        targetBucket: "scorecard_gap_backlog",
      }),
      fetchAgentTraceReviewQueueSummary(),
      fetchTaskRecoveryQueue({ limit: 8 }),
      fetchAgentTraceReplayGate({ status: "completed" }),
      fetchAgentTracePromotionAuditSummary(),
      fetchAgentTraceExperienceQualitySummary(),
      fetchSubagentFitness(),
      fetchOrganizationTopologies(),
      fetchOrganizationTopologyProposals(),
      fetchOrganizationTopologyLift(),
      fetchAutoVerifierMetrics(),
      fetchBrowserDesktopQuality(),
      fetchAutomationRadar(),
      fetchAutomationPolicyRuleDrafts(),
      fetchBrowserDesktopRepairRecipes(),
      fetchBrowserDesktopRepairRecipeVerifications(),
      fetchRepairRouteQuality(),
      fetchPluginSmokeSummary(),
      fetchAgentTraceTrustDenialSummary(),
      fetchAgentTracePolicyReviewRuleDrafts(),
      fetchAgentCompetitorScorecard()
        .then((scorecard) => ({ scorecard, error: null as string | null }))
        .catch((err: unknown) => {
          swallow(err);
          return {
            scorecard: null,
            error: err instanceof Error ? err.message : String(err),
          };
        }),
    ]);
    setQueueItems(items);
    setBrowserDesktopQueueItems(browserDesktopItems);
    setScorecardGapQueueItems(scorecardGapItems);
    setQueueSummary(summary);
    setTaskRecoveryQueue(recoveryQueue);
    setReplayGate(gate);
    setAuditSummary(audit);
    setExperienceQuality(memoryQuality);
    setSubagentFitness(fitness);
    setTopologies(organizationTopologies);
    setTopologyProposals(proposals);
    setTopologyLift(lift);
    setAutoVerifierMetrics(autoVerifier);
    setBrowserDesktopQuality(browserDesktopHealth);
    setAutomationRadar(automationRadarReport);
    setAutomationPolicyRuleDrafts(automationPolicyDrafts);
    setBrowserDesktopRepairRecipes(browserRepairRecipes);
    setBrowserDesktopRepairVerifications(browserRepairVerifications);
    setRepairRouteQuality(repairRoutes);
    setPluginSmokeSummary(pluginSmoke);
    setTrustDenialSummary(trustDenials);
    setPolicyRuleDrafts(ruleDrafts);
    if (scorecardResult.scorecard) setAgentScorecard(scorecardResult.scorecard);
    setScorecardError(scorecardResult.error);
  }, []);

  const refreshTaskRuns = useCallback(async () => {
    const rows = await fetchAgentTraceTaskRuns(8);
    setTaskRuns(rows);
    setSelectedTaskId((current) => current ?? rows[0]?.task_id ?? null);
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    try {
      await Promise.all([refreshTaskRuns(), refreshQueue()]);
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [refreshQueue, refreshTaskRuns]);

  useEffect(() => {
    void refreshAll();
    const timer = window.setInterval(refreshAll, 8000);
    return () => window.clearInterval(timer);
  }, [refreshAll]);

  useEffect(() => {
    if (!selectedTaskId) {
      setTimeline(null);
      return;
    }
    let cancelled = false;
    fetchAgentTraceProcessTimeline(selectedTaskId)
      .then((next) => {
        if (!cancelled) setTimeline(next);
      })
      .catch((err) => {
        swallow(err);
        if (!cancelled) setTimeline(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedTaskId]);

  const selectedTask = useMemo(
    () => taskRuns.find((run) => run.task_id === selectedTaskId) ?? null,
    [selectedTaskId, taskRuns],
  );

  const onQueueSelectedReview = async () => {
    if (!selectedTaskId) return;
    setBusyId(`queue:${selectedTaskId}`);
    try {
      await queueAgentTraceTaskRunReview(selectedTaskId);
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onDecide = async (
    item: AgentTraceReviewQueueItem,
    action: "promoted" | "rejected" | "archived",
  ) => {
    setBusyId(item.id);
    try {
      await decideAgentTraceReviewQueueItem(item.id, {
        action,
        promotedTo: action === "promoted" ? item.target_bucket : undefined,
        reason: action === "promoted" ? "Accepted from operator panel." : "",
      });
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onApplyPromoted = async () => {
    setBusyId("apply-promoted");
    try {
      const result = await applyAgentTraceReviewQueuePromotions({ limit: 50 });
      setLastApplyResult(formatApplyResult(result));
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      const blocked = replayGateBlockFromError(err);
      if (blocked) {
        setOverridePrompt(blocked);
        setOverrideReason("");
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setBusyId(null);
    }
  };

  const onOverrideApply = async () => {
    const reason = overrideReason.trim();
    if (!reason) {
      setError("Override reason is required.");
      return;
    }
    setBusyId("override-apply");
    try {
      const result = await applyAgentTraceReviewQueuePromotions({
        limit: 50,
        overrideReplayGate: true,
        overrideReason: reason,
      });
      setLastApplyResult(formatApplyResult(result));
      setOverridePrompt(null);
      setOverrideReason("");
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onSubagentPolicyDecision = async (
    role: string,
    action: "watch" | "retire",
    evidenceItemIds: string[],
  ) => {
    setBusyId(`subagent-policy:${role}:${action}`);
    try {
      await decideSubagentPolicy(role, {
        action,
        evidenceItemIds,
        reason:
          action === "retire"
            ? "Retired from operator panel using subagent fitness route evidence."
            : "Placed on watch from operator panel using subagent fitness route evidence.",
      });
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueTrustDenials = async () => {
    setBusyId("queue-trust-denials");
    try {
      const next = await fetchAgentTraceTrustDenialSummary(1000, {
        queueRepeated: true,
        minOccurrences: 2,
      });
      setTrustDenialSummary(next);
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueBrowserDesktopReplay = async (kind: "browser" | "desktop") => {
    setBusyId(`queue-${kind}-desktop-replay`);
    try {
      const result =
        kind === "browser"
          ? await queueLatestBrowserSessionReplayCase()
          : await queueComputerActivityReplayCase();
      setLastApplyResult(
        `Queued ${result.queue.created + result.queue.updated} ${kind} replay review item(s).`,
      );
      await refreshQueue();
      setError(null);
      setErrorReplayEvidence(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
      setErrorReplayEvidence(replayEvidenceFromError(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueBrowserDesktopRepairRecipes = async () => {
    setBusyId("queue-browser-desktop-repair-recipes");
    try {
      const result = await queueBrowserDesktopRepairRecipes();
      setLastApplyResult(
        `Queued ${result.created + result.updated} browser/desktop repair recipe item(s).`,
      );
      await refreshQueue();
      setError(null);
      setErrorReplayEvidence(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onRejectStaleBrowserDesktopReplayArtifacts = async () => {
    setBusyId("reject-stale-browser-desktop-replay-artifacts");
    try {
      const result = await rejectStaleBrowserDesktopReplayArtifacts();
      setLastApplyResult(
        `Rejected ${result.rejected_count} stale replay item(s); archived ${
          result.archived_recipe_count ?? 0
        } repair recipe item(s).`,
      );
      await refreshQueue();
      setError(null);
      setErrorReplayEvidence(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueRepairRoutePromotions = async () => {
    setBusyId("queue-repair-route-promotions");
    try {
      const result = await queueRepairRoutePromotionCandidates();
      setLastApplyResult(
        `Queued ${result.created + result.updated} repair-route promotion review item(s).`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueErrorReplayEvidence = async () => {
    if (!errorReplayEvidence) return;
    setBusyId("queue-error-replay-evidence");
    try {
      const result = await queueReplayEvidenceHint(errorReplayEvidence);
      setLastApplyResult(
        `Queued ${result.queue.created + result.queue.updated} replay evidence item(s).`,
      );
      await refreshQueue();
      setError(null);
      setErrorReplayEvidence(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueRealScorecardGaps = async () => {
    setBusyId("queue-scorecard-gaps");
    try {
      const result = await queueAgentScorecardGaps({
        targetScore: agentScorecard.target_score,
        limit: 10,
      });
      setLastApplyResult(
        `Queued ${result.total} real scorecard gap review item(s).`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onQueueScorecardGap = async (dimensionId: string) => {
    setBusyId(`queue-scorecard-gap:${dimensionId}`);
    try {
      const result = await queueAgentScorecardGaps({
        targetScore: agentScorecard.target_score,
        limit: 1,
        dimensionId,
        reason: "operator scorecard drill-down remediation",
      });
      setLastApplyResult(
        `Queued ${result.total} ${dimensionId} scorecard remediation item(s).`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onInstallPolicyRuleDraft = async (draftId: string) => {
    setBusyId(`install-policy-rule:${draftId}`);
    try {
      const result = await installAgentTracePolicyReviewRuleDraft(draftId);
      setLastApplyResult(
        `Installed ${result.rule.effect} rule for ${result.rule.tool} · ${result.policy_rule_count} policy rules`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onInstallAutomationPolicyRuleDraft = async (draftId: string) => {
    setBusyId(`install-automation-policy-rule:${draftId}`);
    try {
      const result = await installAutomationPolicyRuleDraft(draftId);
      setLastApplyResult(
        `Installed ${result.rule.effect} automation rule for ${result.rule.tool} · ${result.policy_rule_count} policy rules`,
      );
      await refreshQueue();
      setError(null);
    } catch (err) {
      swallow(err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  };

  const onTakeoverTaskRun = async (taskId: string) => {
    setBusyId(`takeover-task:${taskId}`);
    try {
      await takeoverTaskRun(taskId);
      setLastApplyResult(`Took over task ${taskId}.`);
      await Promise.all([refreshTaskRuns(), refreshQueue()]);
      setError(null);
    } catch (err) {
      swallow(err);
      setError(readRequestErrorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="workspace-panel rounded-[1.5rem] px-5 py-4">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Operator loop
          </div>
          <h2 className="mt-1 text-base font-semibold">
            Agent evolution queue
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            Task runs become review candidates first, then you decide what is
            promoted into memory, backlog, rules, or archive.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => void onApplyPromoted()}
            disabled={
              busyId === "apply-promoted" ||
              (queueSummary.by_status.promoted ?? 0) === 0
            }
          >
            <CheckCircle2Icon className="mr-1.5 size-3.5" />
            Apply promoted
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-8"
            onClick={() => void refreshAll()}
            disabled={loading}
          >
            <RefreshCwIcon
              className={cn("mr-1.5 size-3.5", loading && "animate-spin")}
            />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      {errorReplayEvidence && (
        <ReplayEvidenceDrilldownCard
          evidence={errorReplayEvidence}
          busy={busyId === "queue-error-replay-evidence"}
          onQueue={() => void onQueueErrorReplayEvidence()}
        />
      )}
      {lastApplyResult && (
        <div className="mb-3 rounded-lg border border-emerald-500/25 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          {lastApplyResult}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-4">
        <Metric
          label="Pending"
          value={queueSummary.pending_count}
          tone="amber"
        />
        <Metric
          label="Promoted"
          value={queueSummary.by_status.promoted ?? 0}
          tone="emerald"
        />
        <Metric
          label="Rejected"
          value={queueSummary.by_status.rejected ?? 0}
          tone="rose"
        />
        <Metric label="Total" value={queueSummary.total} tone="blue" />
      </div>

      <ReplayGateCard gate={replayGate} />
      <TaskRecoveryQueueCard
        queue={taskRecoveryQueue}
        busyId={busyId}
        onTakeover={(taskId) => void onTakeoverTaskRun(taskId)}
      />
      <CompetitorScorecardCard
        report={agentScorecard}
        error={scorecardError}
        auditSummary={auditSummary}
        queueItems={scorecardGapQueueItems}
        queueBusy={busyId === "queue-scorecard-gaps"}
        busyId={busyId}
        applyBusy={busyId === "apply-promoted"}
        onQueueRealGaps={() => void onQueueRealScorecardGaps()}
        onQueueGap={(dimensionId) => void onQueueScorecardGap(dimensionId)}
        onApplyPromoted={() => void onApplyPromoted()}
      />
      <AutomationRadarCard
        radar={automationRadar}
        drafts={automationPolicyRuleDrafts}
        busyId={busyId}
        onInstallDraft={(draftId) =>
          void onInstallAutomationPolicyRuleDraft(draftId)
        }
      />
      <BrowserDesktopReplayReviewCard
        items={browserDesktopQueueItems}
        total={queueSummary.by_target_bucket.browser_desktop_replay ?? 0}
        quality={browserDesktopQuality}
        repairRecipes={browserDesktopRepairRecipes}
        repairVerifications={browserDesktopRepairVerifications}
        browserBusy={busyId === "queue-browser-desktop-replay"}
        desktopBusy={busyId === "queue-desktop-desktop-replay"}
        recipeBusy={busyId === "queue-browser-desktop-repair-recipes"}
        staleBusy={busyId === "reject-stale-browser-desktop-replay-artifacts"}
        onQueueBrowser={() => void onQueueBrowserDesktopReplay("browser")}
        onQueueDesktop={() => void onQueueBrowserDesktopReplay("desktop")}
        onQueueRepairRecipes={() => void onQueueBrowserDesktopRepairRecipes()}
        onRejectStale={() => void onRejectStaleBrowserDesktopReplayArtifacts()}
      />
      <PromotionAuditSummaryCard summary={auditSummary} />
      <MemoryQualityCard summary={experienceQuality} />
      <AutoVerifierCard
        report={autoVerifierMetrics}
        repairRoutes={repairRouteQuality}
        queueBusy={busyId === "queue-repair-route-promotions"}
        onQueueRepairRoutes={() => void onQueueRepairRoutePromotions()}
      />
      <PluginHealthCard summary={pluginSmokeSummary} />
      <ToolSafetyCard
        summary={trustDenialSummary}
        busy={busyId === "queue-trust-denials"}
        onQueuePolicyReview={() => void onQueueTrustDenials()}
      />
      <PolicyReviewRuleDraftCard
        report={policyRuleDrafts}
        busyId={busyId}
        onInstall={(draftId) => void onInstallPolicyRuleDraft(draftId)}
      />
      <SubagentRiskCard
        report={subagentFitness}
        busyId={busyId}
        onWatch={(role, evidence) =>
          void onSubagentPolicyDecision(role, "watch", evidence)
        }
        onRetire={(role, evidence) =>
          void onSubagentPolicyDecision(role, "retire", evidence)
        }
      />
      <TopologyPromotionCard
        proposals={topologyProposals}
        lift={topologyLift}
      />
      <TopologyPolicyCard topologies={topologies} />

      <div className="mt-4 grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
        <div className="space-y-3">
          <PanelTitle
            icon={<GitBranchIcon className="size-4" />}
            title="Recent task runs"
            meta={`${taskRuns.length} loaded`}
          />
          <div className="overflow-hidden rounded-lg border border-border/60">
            {taskRuns.length === 0 ? (
              <EmptyPanel title="No task runs yet" />
            ) : (
              taskRuns.map((run) => (
                <button
                  key={run.task_id}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border/50 px-3 py-2 text-left last:border-b-0 hover:bg-muted/40",
                    selectedTaskId === run.task_id && "bg-primary/10",
                  )}
                  onClick={() => setSelectedTaskId(run.task_id)}
                >
                  <StatusDot status={run.status} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {run.title || run.summary || run.task_id}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                      <span className="font-mono">{shortId(run.task_id)}</span>
                      <span>{run.tool_calls_started ?? 0} tools</span>
                      {(run.tool_errors ?? 0) > 0 && (
                        <span className="text-destructive">
                          {run.tool_errors} errors
                        </span>
                      )}
                    </div>
                  </div>
                  <Badge variant="outline" className="text-[10px]">
                    {run.status ?? "unknown"}
                  </Badge>
                </button>
              ))
            )}
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/15 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">
                  {selectedTask?.title ||
                    selectedTask?.summary ||
                    "No task selected"}
                </div>
                {selectedTaskId && (
                  <div className="font-mono text-[11px] text-muted-foreground">
                    {selectedTaskId}
                  </div>
                )}
              </div>
              <Button
                size="sm"
                className="h-8 shrink-0"
                disabled={
                  !selectedTaskId || busyId === `queue:${selectedTaskId}`
                }
                onClick={() => void onQueueSelectedReview()}
              >
                <ListChecksIcon className="mr-1.5 size-3.5" />
                Queue review
              </Button>
            </div>
            <TimelinePreview timeline={timeline} />
          </div>
        </div>

        <div className="space-y-3">
          <PanelTitle
            icon={<ListChecksIcon className="size-4" />}
            title="Pending review queue"
            meta={`${queueSummary.pending_count} pending`}
          />
          <div className="space-y-2">
            {queueItems.length === 0 ? (
              <EmptyPanel title="No pending review items" />
            ) : (
              queueItems.map((item) => (
                <ReviewQueueRow
                  key={item.id}
                  item={item}
                  busy={busyId === item.id}
                  onPromote={() => void onDecide(item, "promoted")}
                  onReject={() => void onDecide(item, "rejected")}
                  onArchive={() => void onDecide(item, "archived")}
                />
              ))
            )}
          </div>
        </div>
      </div>
      <ReplayGateOverrideDialog
        prompt={overridePrompt}
        reason={overrideReason}
        busy={busyId === "override-apply"}
        onCancel={() => setOverridePrompt(null)}
        onReasonChange={setOverrideReason}
        onConfirm={() => void onOverrideApply()}
      />
    </section>
  );
}

function TimelinePreview({
  timeline,
}: {
  timeline: AgentTraceProcessTimeline | null;
}) {
  if (!timeline) return <EmptyPanel title="No process timeline available" />;
  const nodes = timeline.timeline.slice(0, 8);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline" className="text-[10px]">
          score {formatScore(timeline.overview.score)}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          approvals {timeline.overview.approval_count ?? 0}
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          lessons {timeline.overview.experience_record_count ?? 0}
        </Badge>
      </div>
      <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
        {nodes.map((node, index) => (
          <div
            key={`${node.lane}-${node.kind}-${node.ts ?? index}`}
            className="grid grid-cols-[5.5rem_1fr] gap-2 rounded-md bg-background/55 px-2 py-1.5 text-[11px]"
          >
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Clock3Icon className="size-3" />
              <span className="truncate">{node.lane}</span>
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium">
                {node.title || node.kind}
              </div>
              {(node.text || node.tool || node.status) && (
                <div className="truncate text-muted-foreground">
                  {node.text || node.tool || node.status}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TaskRecoveryQueueCard({
  queue,
  busyId,
  onTakeover,
}: {
  queue: AgentTraceTaskRecoveryQueue;
  busyId: string | null;
  onTakeover: (taskId: string) => void;
}) {
  const actionable = queue.items.filter(
    (item) => item.recommended_action !== "monitor",
  );
  const topItem = actionable[0] ?? queue.items[0];
  const healthy = actionable.length === 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        healthy
          ? "border-emerald-500/25 bg-emerald-500/10"
          : "border-amber-500/30 bg-amber-500/10",
      )}
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
            <GitBranchIcon
              className={cn(
                "size-4",
                healthy
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-amber-700 dark:text-amber-300",
              )}
            />
            Task recovery queue
            <Badge variant="outline" className="text-[10px]">
              {queue.total} tracked
            </Badge>
            <Badge
              variant={healthy ? "outline" : "destructive"}
              className="text-[10px]"
            >
              {actionable.length} action
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {topItem
              ? `${taskRecoveryActionLabel(topItem.recommended_action)} · ${topItem.title || topItem.task_id}`
              : "No stalled, failed, or approval-blocked task runs."}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-right font-mono text-[11px]">
          <GateStat label="shown" value={queue.count} />
          <GateStat label="takeover" value={countRecovery(queue, "takeover")} />
          <GateStat label="resume" value={countRecovery(queue, "resume")} />
        </div>
      </div>
      {queue.items.length > 0 && (
        <div className="mt-2 grid gap-2 lg:grid-cols-2">
          {queue.items.slice(0, 4).map((item) => {
            const busy = busyId === `takeover-task:${item.task_id}`;
            const steps = taskRecoverySteps(item);
            const checkpointId =
              item.checkpoint_id ||
              item.resume_checkpoint_id ||
              item.latest_checkpoint_id ||
              "available";
            return (
              <div
                key={item.task_id}
                className="rounded-md border border-background/70 bg-background/55 px-2 py-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-xs font-medium">
                      {item.title || item.task_id}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                      <span className="font-mono">{shortId(item.task_id)}</span>
                      <span>{item.status ?? "unknown"}</span>
                      {item.kind && <span>{item.kind}</span>}
                      {item.lease_health?.state && (
                        <span>lease {item.lease_health.state}</span>
                      )}
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    P{item.priority}
                  </Badge>
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <Badge
                    variant={
                      item.recommended_action === "monitor"
                        ? "outline"
                        : "secondary"
                    }
                    className="text-[10px]"
                  >
                    {taskRecoveryActionLabel(item.recommended_action)}
                  </Badge>
                  {item.has_checkpoint && (
                    <Badge variant="outline" className="text-[10px]">
                      checkpoint {shortId(checkpointId)}
                    </Badge>
                  )}
                  {item.thread_id && (
                    <Badge variant="outline" className="text-[10px]">
                      thread {shortId(item.thread_id)}
                    </Badge>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <div className="min-w-0 text-[10px] text-muted-foreground">
                    <div>
                      {item.can_resume
                        ? "Resume-safe state is available"
                        : item.can_takeover
                          ? "Lease can be reclaimed"
                          : taskRecoveryHint(item.recommended_action)}
                    </div>
                    {steps.length > 0 && (
                      <div className="mt-0.5 truncate font-mono">
                        {steps.join(" -> ")}
                      </div>
                    )}
                  </div>
                  {item.can_takeover && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-7 shrink-0 px-2 text-[11px]"
                      disabled={busy}
                      onClick={() => onTakeover(item.task_id)}
                    >
                      <GitBranchIcon className="mr-1 size-3" />
                      Take over
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CompetitorScorecardCard({
  report,
  error,
  auditSummary,
  queueItems,
  queueBusy,
  busyId,
  applyBusy,
  onQueueRealGaps,
  onQueueGap,
  onApplyPromoted,
}: {
  report: AgentCompetitorScorecard;
  error?: string | null;
  auditSummary: AgentTracePromotionAuditSummary;
  queueItems: AgentTraceReviewQueueItem[];
  queueBusy: boolean;
  busyId: string | null;
  applyBusy: boolean;
  onQueueRealGaps: () => void;
  onQueueGap: (dimensionId: string) => void;
  onApplyPromoted: () => void;
}) {
  const [selectedGapId, setSelectedGapId] = useState<string | null>(null);
  const octopusScore = report.overall.octopus ?? 0;
  const evidenceAdjustedOctopusScore =
    report.evidence_adjusted_overall?.octopus ?? octopusScore;
  const belowTarget = report.octopus_below_target ?? [];
  const strengths = report.octopus_strengths ?? [];
  const certification = report.parity_certification;
  const topGap = belowTarget
    .slice()
    .sort(
      (lhs, rhs) => rhs.octopus_gap_to_target - lhs.octopus_gap_to_target,
    )[0];
  const selectedGap =
    belowTarget.find((dimension) => dimension.id === selectedGapId) ?? topGap;
  const selectedGapChecklist = selectedGap?.octopus_evidence_checklist ?? [];
  const selectedGapQueueItem = selectedGap
    ? scorecardGapQueueItemForDimension(queueItems, selectedGap.id)
    : null;
  const healthy = octopusScore >= report.target_score;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        error
          ? "border-amber-500/30 bg-amber-500/10"
          : healthy
            ? "border-emerald-500/25 bg-emerald-500/10"
            : "border-amber-500/30 bg-amber-500/10",
      )}
    >
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <BarChart3Icon
              className={cn(
                "size-4",
                !error && healthy
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-amber-700 dark:text-amber-300",
              )}
            />
            Competitor scorecard
            <Badge variant="outline" className="text-[10px]">
              {error ? "degraded" : report.verdict.replaceAll("_", " ")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {error
              ? error
              : topGap
                ? `${topGap.title} is ${topGap.octopus_gap_to_target} point(s) under target`
                : certification?.ready
                  ? `Certification passed ${certification.passed}/${certification.total}`
                  : "Octopus is at or above the target across tracked dimensions"}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            Overall is external-calibrated baseline; evidence score is shown
            separately.
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="grid grid-cols-5 gap-2 text-right font-mono text-[11px]">
            <GateStat label="Octo real" value={octopusScore} />
            <GateStat label="Evidence" value={evidenceAdjustedOctopusScore} />
            <GateStat label="Codex" value={report.overall.codex ?? 0} />
            <GateStat label="Claude" value={report.overall.claude_code ?? 0} />
            <GateStat label="Cursor" value={report.overall.cursor ?? 0} />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-[11px]"
            disabled={queueBusy || belowTarget.length === 0}
            onClick={onQueueRealGaps}
          >
            <ListChecksIcon
              className={cn("mr-1.5 size-3", queueBusy && "animate-spin")}
            />
            Queue real gaps
          </Button>
        </div>
      </div>

      <div className="mt-2 grid gap-2 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5">
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">
            Real comparison ranking
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(report.ranking ?? []).map((row, index) => (
              <Badge
                key={row.competitor}
                variant="outline"
                className={cn(
                  "text-[10px]",
                  row.competitor === "octopus" &&
                    "border-primary/30 bg-primary/10 text-primary",
                )}
              >
                #{index + 1} {competitorLabel(row.competitor)} {row.score}
              </Badge>
            ))}
          </div>
        </div>
        <div className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5">
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">
            Below 90 real baseline
          </div>
          <div className="flex flex-wrap gap-1.5">
            {belowTarget.length === 0 ? (
              <>
                <Badge variant="outline" className="text-[10px]">
                  clear
                </Badge>
                {certification && (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-[10px]",
                      certification.ready
                        ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                    )}
                  >
                    certified {certification.passed}/{certification.total}
                  </Badge>
                )}
              </>
            ) : (
              belowTarget.slice(0, 5).map((dimension) => (
                <button
                  key={dimension.id}
                  type="button"
                  aria-controls="scorecard-gap-drilldown"
                  aria-pressed={selectedGap?.id === dimension.id}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-[10px] text-amber-700 transition-colors hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 dark:text-amber-300",
                    selectedGap?.id === dimension.id
                      ? "border-amber-500/60 bg-amber-500/20"
                      : "border-amber-500/30 bg-amber-500/10",
                  )}
                  onClick={() => setSelectedGapId(dimension.id)}
                >
                  {dimension.title} {dimension.scores.octopus}
                </button>
              ))
            )}
          </div>
        </div>
      </div>

      {selectedGap && (
        <ScorecardGapDrilldown
          gap={selectedGap}
          checklist={selectedGapChecklist}
          queueItem={selectedGapQueueItem}
          auditSummary={auditSummary}
          queueBusy={busyId === `queue-scorecard-gap:${selectedGap.id}`}
          applyBusy={applyBusy}
          onQueue={() => onQueueGap(selectedGap.id)}
          onApplyPromoted={onApplyPromoted}
        />
      )}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {strengths.slice(0, 3).map((dimension) => (
          <Badge
            key={dimension.id}
            variant="outline"
            className="border-emerald-500/25 bg-emerald-500/10 text-[10px] text-emerald-700 dark:text-emerald-300"
          >
            leads {dimension.title} {dimension.scores.octopus}
          </Badge>
        ))}
        {report.next_focus.slice(0, 2).map((item) => (
          <Badge
            key={item}
            variant="outline"
            className="max-w-full text-[10px]"
          >
            <span className="truncate">{item}</span>
          </Badge>
        ))}
      </div>
    </div>
  );
}

function ScorecardGapDrilldown({
  gap,
  checklist,
  queueItem,
  auditSummary,
  queueBusy,
  applyBusy,
  onQueue,
  onApplyPromoted,
}: {
  gap: AgentCompetitorScorecard["dimensions"][number];
  checklist: NonNullable<
    AgentCompetitorScorecard["dimensions"][number]["octopus_evidence_checklist"]
  >;
  queueItem: AgentTraceReviewQueueItem | null;
  auditSummary: AgentTracePromotionAuditSummary;
  queueBusy: boolean;
  applyBusy: boolean;
  onQueue: () => void;
  onApplyPromoted: () => void;
}) {
  const realScore = gap.octopus_baseline_score ?? gap.scores.octopus;
  const evidenceScore =
    gap.octopus_evidence_adjusted_score ??
    gap.evidence_adjusted_scores?.octopus ??
    realScore;
  const nextActions = gap.octopus_next_actions ?? [];
  const operatorDrilldown = gap.operator_drilldown;
  const drilldownLinks = operatorDrilldown?.links ?? [];
  return (
    <div
      id="scorecard-gap-drilldown"
      role="region"
      aria-label={`Scorecard gap drill-down for ${gap.title}`}
      className="mt-2 rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-semibold">{gap.title}</div>
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            {gap.why}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {queueItem ? (
            <Badge
              variant="outline"
              className="border-blue-500/25 bg-blue-500/10 text-[10px] text-blue-700 dark:text-blue-300"
            >
              queued {queueItem.priority}
            </Badge>
          ) : null}
          <Badge variant="outline" className="text-[10px]">
            real {realScore}
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            evidence {evidenceScore}
          </Badge>
          <Badge variant="outline" className="text-[10px]">
            gap {gap.octopus_gap_to_target}
          </Badge>
        </div>
      </div>

      <div className="mt-2 flex flex-col gap-2 rounded-md border border-border/50 bg-muted/15 px-2 py-1.5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="text-[11px] font-medium text-muted-foreground">
            Remediation queue
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
            {queueItem
              ? `${queueItem.id} · ${queueItem.status} · x${queueItem.occurrences}`
              : "not queued"}
          </div>
          {queueItem ? (
            <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
              target {queueItem.target_bucket} · audit {auditSummary.total}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-[11px]"
            disabled={queueBusy}
            onClick={onQueue}
          >
            <ListChecksIcon
              className={cn("mr-1.5 size-3", queueBusy && "animate-spin")}
            />
            {queueItem ? "Refresh queue item" : "Queue this gap"}
          </Button>
          {queueItem ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-[11px]"
              disabled={applyBusy || queueItem.status !== "promoted"}
              onClick={onApplyPromoted}
            >
              <CheckCircle2Icon
                className={cn("mr-1.5 size-3", applyBusy && "animate-spin")}
              />
              Apply gap
            </Button>
          ) : null}
        </div>
      </div>

      {nextActions.length > 0 && (
        <div className="mt-2 grid gap-1.5 lg:grid-cols-2">
          {nextActions.slice(0, 2).map((action) => (
            <div
              key={action}
              className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-800 dark:text-amber-200"
            >
              {action}
            </div>
          ))}
        </div>
      )}

      {operatorDrilldown?.schema ===
        "octopus.scorecard_operator_drilldown.v1" &&
        drilldownLinks.length > 0 && (
          <div className="mt-2 rounded-md border border-border/50 bg-muted/15 px-2 py-1.5">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="min-w-0 truncate text-[11px] font-medium text-muted-foreground">
                Evidence sources
              </div>
              <Badge variant="outline" className="shrink-0 text-[10px]">
                {drilldownLinks.length} links
              </Badge>
            </div>
            <div className="grid gap-1.5 lg:grid-cols-2">
              {drilldownLinks.slice(0, 4).map((link) => (
                <div
                  key={`${link.id ?? link.label}-${link.href}`}
                  className="min-w-0 rounded-md border border-border/50 bg-background/50 px-2 py-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 truncate text-xs font-medium">
                      {link.label ?? link.id ?? "Evidence link"}
                    </div>
                    {link.method ? (
                      <Badge variant="outline" className="shrink-0 text-[10px]">
                        {link.method}
                      </Badge>
                    ) : null}
                  </div>
                  {link.href ? (
                    <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
                      {link.href}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        )}

      {checklist.length > 0 && (
        <div className="mt-2">
          <div className="mb-1 flex items-center justify-between gap-2">
            <div className="min-w-0 truncate text-[11px] font-medium text-muted-foreground">
              Evidence checklist
            </div>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {gap.octopus_missing_evidence_count ?? 0} missing
            </Badge>
          </div>
          <div className="grid gap-1.5 lg:grid-cols-2">
            {checklist.slice(0, 2).map((item) => (
              <div
                key={item.id ?? item.title}
                className="rounded-md border border-border/50 bg-muted/15 px-2 py-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-xs font-medium">
                    {item.title ?? item.id ?? "evidence"}
                  </div>
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {Math.round((item.score ?? 0) * 100)}%
                  </Badge>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
                  <span>
                    impl {item.implementation.present}/
                    {item.implementation.total}
                  </span>
                  <span>
                    tests {item.tests.present}/{item.tests.total}
                  </span>
                  {item.implementation.missing_count +
                    item.tests.missing_count >
                    0 && (
                    <span className="text-amber-700 dark:text-amber-300">
                      {item.implementation.missing_count +
                        item.tests.missing_count}{" "}
                      missing
                    </span>
                  )}
                </div>
                {item.next_actions[0] && (
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">
                    {item.next_actions[0]}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function AutomationRadarCard({
  radar,
  drafts,
  busyId,
  onInstallDraft,
}: {
  radar: AutomationRadarReport;
  drafts: AutomationPolicyRuleDraftsReport;
  busyId: string | null;
  onInstallDraft: (draftId: string) => void;
}) {
  const octopusScore = radar.overall.octopus ?? 0;
  const codexScore = radar.overall.codex ?? 0;
  const readyDrafts = radar.policy_rule_drafts.ready;
  const topDraft = drafts.drafts[0] ?? null;
  const topGaps = radar.octopus_gaps ?? [];
  return (
    <div className="mt-3 rounded-lg border border-border/70 bg-background/60 px-3 py-2">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon className="size-4 text-blue-700 dark:text-blue-300" />
            Automation radar
            <Badge
              variant="outline"
              className={cn(
                "text-[10px]",
                radar.verdict === "leading" &&
                  "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
              )}
            >
              {radar.verdict.replaceAll("_", " ")}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-[10px]",
                readyDrafts
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
              )}
            >
              policy drafts {radar.policy_rule_drafts.verified}/
              {radar.policy_rule_drafts.total}
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            Browser, desktop, visual replay, and signed automation policy
            coverage.
          </div>
        </div>
        <div className="grid shrink-0 grid-cols-3 gap-2 text-right font-mono text-[11px]">
          <GateStat label="Octo auto" value={octopusScore} />
          <GateStat label="Codex" value={codexScore} />
          <GateStat
            label="Ready"
            value={
              radar.browser_desktop_quality.ready &&
              radar.parity_certification.ready &&
              readyDrafts
                ? 1
                : 0
            }
          />
        </div>
      </div>

      <div className="mt-2 grid gap-2 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="rounded-md border border-border/50 bg-muted/15 px-2 py-1.5">
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">
            Remaining automation edges
          </div>
          <div className="flex flex-wrap gap-1.5">
            {topGaps.length === 0 ? (
              <Badge variant="outline" className="text-[10px]">
                clear
              </Badge>
            ) : (
              topGaps.slice(0, 4).map((gap) => (
                <Badge key={gap.id} variant="outline" className="text-[10px]">
                  {gap.title} {gap.scores.octopus}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="rounded-md border border-border/50 bg-muted/15 px-2 py-1.5">
          <div className="mb-1 flex items-center justify-between gap-2">
            <div className="min-w-0 truncate text-[11px] font-medium text-muted-foreground">
              Signed automation rule drafts
            </div>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {drafts.verified}/{drafts.total}
            </Badge>
          </div>
          {topDraft ? (
            <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="truncate font-mono text-[10px]">
                  {topDraft.signed_payload.rule.tool}
                </div>
                <div className="truncate text-[10px] text-muted-foreground">
                  {topDraft.signed_payload.rule.reason}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 shrink-0 px-2 text-[11px]"
                disabled={
                  busyId ===
                  `install-automation-policy-rule:${topDraft.draft_id}`
                }
                onClick={() => onInstallDraft(topDraft.draft_id)}
              >
                <ShieldAlertIcon
                  className={cn(
                    "mr-1.5 size-3",
                    busyId ===
                      `install-automation-policy-rule:${topDraft.draft_id}` &&
                      "animate-spin",
                  )}
                />
                Install deny rule
              </Button>
            </div>
          ) : (
            <div className="text-[11px] text-muted-foreground">
              No automation rule drafts available.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ReplayGateOverrideDialog({
  prompt,
  reason,
  busy,
  onCancel,
  onReasonChange,
  onConfirm,
}: {
  prompt: ReplayGateOverridePrompt | null;
  reason: string;
  busy: boolean;
  onCancel: () => void;
  onReasonChange: (value: string) => void;
  onConfirm: () => void;
}) {
  const gate = prompt?.gate ?? null;
  return (
    <Dialog open={!!prompt} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Replay gate blocked apply</DialogTitle>
          <DialogDescription>
            Promotion was stopped because replay gate did not pass. Override
            only when you have reviewed the failing cases.
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2">
          <div className="text-sm font-medium text-destructive">
            {prompt?.message ?? "Replay gate did not pass"}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {gate?.reason || "No reason provided"}
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 text-center font-mono text-xs">
            <GateStat label="cases" value={gate?.summary.total ?? 0} />
            <GateStat label="pass" value={gate?.summary.passed ?? 0} />
            <GateStat label="fail" value={gate?.summary.failed ?? 0} />
            <GateStat label="low" value={gate?.summary.below_min_score ?? 0} />
          </div>
        </div>
        <Textarea
          aria-label="Override reason"
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
          placeholder="Record why this replay gate override is acceptable."
          className="min-h-24 resize-none text-sm"
        />
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={busy || !reason.trim()}
          >
            Override gate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PromotionAuditSummaryCard({
  summary,
}: {
  summary: AgentTracePromotionAuditSummary;
}) {
  const topologyBlocks = summary.topology_policy_block_count ?? 0;
  const integrity = summary.integrity;
  const integrityOk = integrity?.ok ?? true;
  const risky =
    summary.gate_blocked_override_count > 0 ||
    topologyBlocks > 0 ||
    !integrityOk;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        risky
          ? "border-amber-500/30 bg-amber-500/10"
          : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-medium">Promotion audit</div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {!integrityOk
              ? `Audit chain broken at #${integrity?.broken_at ?? "?"}`
              : topologyBlocks > 0
                ? "Operator policy blocked team topology attempts"
                : risky
                  ? "Overrides were used after replay gate blocked apply"
                  : "No blocked gate overrides recorded"}
          </div>
          <div className="mt-1 truncate text-[10px] text-muted-foreground">
            chain {integrityOk ? "ok" : "failed"} ·{" "}
            {integrity?.entries_checked ?? 0} checked
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2 text-right font-mono text-[11px]">
          <GateStat label="audit" value={summary.total} />
          <GateStat label="over" value={summary.override_count} />
          <GateStat label="gate" value={summary.gate_failed_count} />
          <GateStat label="topo" value={topologyBlocks} />
        </div>
      </div>
    </div>
  );
}

function MemoryQualityCard({
  summary,
}: {
  summary: AgentTraceExperienceQualitySummary;
}) {
  const risky =
    summary.contradicted_count > 0 ||
    summary.stale_count > 0 ||
    summary.low_reliability_count > 0;
  const reliabilityPercent = Math.round((summary.avg_reliability ?? 0) * 100);
  const topAction = summary.next_actions[0];
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        risky
          ? "border-amber-500/30 bg-amber-500/10"
          : summary.total > 0
            ? "border-emerald-500/25 bg-emerald-500/10"
            : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            Memory quality
            <Badge variant="outline" className="text-[10px]">
              {reliabilityPercent}% reliable
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {topAction ??
              (summary.total > 0
                ? "Recall memories are fresh and contradiction-clean"
                : "No committed experience memories yet")}
          </div>
          <div className="mt-1 truncate font-mono text-[10px] text-muted-foreground">
            active {summary.active_count} · bucket experience{" "}
            {summary.by_bucket.experience ?? 0}
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2 text-right font-mono text-[11px]">
          <GateStat label="mem" value={summary.total} />
          <GateStat label="stale" value={summary.stale_count} />
          <GateStat label="contra" value={summary.contradicted_count} />
          <GateStat label="low" value={summary.low_reliability_count} />
        </div>
      </div>
    </div>
  );
}

function AutoVerifierCard({
  report,
  repairRoutes,
  queueBusy,
  onQueueRepairRoutes,
}: {
  report: AutoVerifierMetricsReport;
  repairRoutes: RepairRouteQualityReport;
  queueBusy: boolean;
  onQueueRepairRoutes: () => void;
}) {
  const decisions = report.recent_decisions ?? [];
  const latest = decisions.length > 0 ? decisions[decisions.length - 1] : null;
  const candidates = latest?.candidates?.slice(0, 2) ?? [];
  const alerts = report.alerts ?? [];
  const repairCandidates = repairRoutes.promotion_candidates ?? [];
  const passPercent = Math.round((report.pass_rate ?? 0) * 100);
  const repairScorePercent = Math.round((repairRoutes.score ?? 0) * 100);
  const repairBlockers = repairRoutes.quality_gate?.blockers ?? [];
  const hasSignal = report.total > 0 || latest !== null;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        alerts.length > 0
          ? "border-destructive/30 bg-destructive/10"
          : report.fail_count > 0
            ? "border-amber-500/30 bg-amber-500/10"
            : hasSignal
              ? "border-emerald-500/25 bg-emerald-500/10"
              : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ListChecksIcon className="size-4 text-primary" />
            Auto verifier
            <Badge variant="outline" className="text-[10px]">
              {passPercent}% pass
            </Badge>
            <Badge
              variant={repairRoutes.ready ? "outline" : "destructive"}
              className="text-[10px]"
            >
              routes {repairScorePercent}%
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {alerts[0]?.message ??
              (latest
                ? latest.selected_command
                : "No auto-verifier decisions recorded yet")}
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2 text-right font-mono text-[11px]">
          <GateStat label="runs" value={report.total} />
          <GateStat label="pass" value={report.pass_count} />
          <GateStat label="fail" value={report.fail_count} />
          <GateStat
            label="ms"
            value={Math.round(report.avg_duration_ms ?? 0)}
          />
        </div>
      </div>
      <div className="mt-2 flex flex-col gap-2 rounded-md border border-background/70 bg-background/60 px-2 py-1.5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">
            {repairCandidates.length}
          </span>{" "}
          repair-route promotion candidate(s)
          {repairCandidates[0]?.route
            ? ` · top ${repairCandidates[0].route}`
            : ""}
          {repairBlockers.length > 0
            ? ` · blocked by ${repairBlockers[0]?.replaceAll("_", " ") ?? ""}`
            : ""}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="h-7 shrink-0 px-2 text-[11px]"
          onClick={onQueueRepairRoutes}
          disabled={queueBusy || repairCandidates.length === 0}
        >
          <GitBranchIcon className="mr-1.5 size-3" />
          Queue routes
        </Button>
      </div>
      {alerts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {alerts.slice(0, 3).map((alert) => (
            <Badge
              key={`${alert.family}:${alert.severity}`}
              variant="outline"
              className="border-destructive/30 bg-destructive/10 text-[10px] text-destructive"
            >
              {alert.family} drift {Math.round(alert.pass_rate * 100)}%
            </Badge>
          ))}
        </div>
      )}
      {candidates.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {candidates.map((candidate) => (
            <div
              key={`${candidate.rank}:${candidate.command}`}
              className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate font-mono text-[11px]">
                  #{candidate.rank} {candidate.command}
                </div>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  {candidate.family}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <span>{Math.round(candidate.pass_rate * 100)}% history</span>
                <span>{candidate.history_count} samples</span>
                <span>{Math.round(candidate.avg_duration_ms)}ms</span>
              </div>
              <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                {candidate.reason}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PluginHealthCard({ summary }: { summary: PluginSmokeSummary }) {
  const risky = summary.failed_count > 0 || summary.warning_count > 0;
  const compatibility = summary.compatibility;
  const rows =
    summary.failed.length > 0
      ? summary.failed
      : summary.review_required.length > 0
        ? summary.review_required
        : summary.warnings;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        summary.failed_count > 0
          ? "border-destructive/30 bg-destructive/10"
          : risky
            ? "border-amber-500/30 bg-amber-500/10"
            : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ListChecksIcon className="size-4 text-primary" />
            Plugin health
            <Badge variant="outline" className="text-[10px]">
              {summary.ok_count}/{summary.total} ok
            </Badge>
            {compatibility && (
              <Badge
                variant="outline"
                className={cn(
                  "text-[10px]",
                  compatibility.verdict === "fail"
                    ? "border-destructive/30 bg-destructive/10 text-destructive"
                    : compatibility.verdict === "review"
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                      : "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                )}
              >
                compat {compatibility.verdict}
              </Badge>
            )}
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {summary.failed_count > 0
              ? "Some plugins failed local smoke checks"
              : summary.review_required_count > 0
                ? "Some local plugins need operator review"
                : "Installed Codex plugins passed local smoke checks"}
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2 text-right font-mono text-[11px]">
          <GateStat label="total" value={summary.total} />
          <GateStat label="ok" value={summary.ok_count} />
          <GateStat label="fail" value={summary.failed_count} />
          <GateStat label="warn" value={summary.warning_count} />
          {compatibility && (
            <GateStat label="compat" value={compatibility.passed} />
          )}
        </div>
      </div>
      {compatibility?.next_actions?.[0] && (
        <div className="mt-2 truncate text-[11px] text-muted-foreground">
          {compatibility.next_actions[0]}
        </div>
      )}
      {rows.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rows.slice(0, 4).map((item, index) => (
            <Badge
              key={`${item.plugin_id ?? item.plugin_name ?? index}`}
              variant="outline"
              className={cn(
                "max-w-full text-[10px]",
                summary.failed_count > 0
                  ? "border-destructive/30 bg-destructive/10 text-destructive"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
              )}
            >
              <span className="truncate">
                {item.plugin_name ?? item.plugin_id ?? "plugin"}
              </span>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ToolSafetyCard({
  summary,
  busy,
  onQueuePolicyReview,
}: {
  summary: AgentTraceTrustDenialSummary;
  busy: boolean;
  onQueuePolicyReview: () => void;
}) {
  const recent = summary.recent ?? [];
  const topTool = Object.entries(summary.by_tool ?? {}).sort(
    (lhs, rhs) => rhs[1] - lhs[1],
  )[0];
  const canQueue = summary.total >= 2;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        summary.total > 0
          ? "border-amber-500/30 bg-amber-500/10"
          : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon
              className={cn(
                "size-4",
                summary.total > 0
                  ? "text-amber-600 dark:text-amber-300"
                  : "text-muted-foreground",
              )}
            />
            Tool safety
            <Badge variant="outline" className="text-[10px]">
              {summary.total} denied
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {summary.total > 0
              ? `${topTool?.[0] ?? "tool"} has recent policy denials`
              : "No static tool denials recorded in current trace window"}
          </div>
        </div>
        <div className="flex shrink-0 items-start gap-3">
          <div className="grid grid-cols-3 gap-2 text-right font-mono text-[11px]">
            <GateStat label="deny" value={summary.by_action.deny ?? 0} />
            <GateStat label="block" value={summary.by_action.block ?? 0} />
            <GateStat label="halt" value={summary.by_action.halt ?? 0} />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 shrink-0 px-2 text-[11px]"
            disabled={!canQueue || busy}
            onClick={onQueuePolicyReview}
          >
            <ListChecksIcon className="mr-1.5 size-3.5" />
            Queue policy review
          </Button>
        </div>
      </div>
      {recent.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {recent.slice(-2).map((item, index) => (
            <div
              key={`${item.id ?? index}:${item.tool_name}`}
              className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-xs font-medium">
                  {item.tool_name}
                </div>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  {item.risk_level || item.action}
                </Badge>
              </div>
              <div className="mt-1 truncate text-[11px] text-muted-foreground">
                {item.reason || item.action}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PolicyReviewRuleDraftCard({
  report,
  busyId,
  onInstall,
}: {
  report: AgentTracePolicyReviewRuleDrafts;
  busyId: string | null;
  onInstall: (draftId: string) => void;
}) {
  const drafts = report.drafts ?? [];
  const hasDrafts = drafts.length > 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        hasDrafts
          ? "border-emerald-500/25 bg-emerald-500/10"
          : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon
              className={cn(
                "size-4",
                hasDrafts
                  ? "text-emerald-700 dark:text-emerald-300"
                  : "text-muted-foreground",
              )}
            />
            Policy review rules
            <Badge variant="outline" className="text-[10px]">
              {report.verified}/{report.total} signed
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {hasDrafts
              ? "Replay-backed policy reviews produced signed install drafts"
              : "No signed policy-review rule drafts yet"}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-right font-mono text-[11px]">
          <GateStat label="drafts" value={report.total} />
          <GateStat label="signed" value={report.verified} />
        </div>
      </div>
      {hasDrafts && (
        <div className="mt-2 space-y-1.5">
          {drafts.slice(0, 2).map((draft) => {
            const rule = draft.signed_payload.rule ?? {};
            const signature = draft.signature.digest ?? "";
            const installing =
              busyId === `install-policy-rule:${draft.draft_id}`;
            return (
              <div
                key={draft.draft_id}
                className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-xs font-medium">
                    {rule.effect ?? "deny"} {rule.tool ?? "tool"}
                  </div>
                  <Badge variant="outline" className="shrink-0 text-[10px]">
                    {shortId(signature || draft.draft_id)}
                  </Badge>
                </div>
                <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                  {rule.reason || "Replay-backed policy review rule"}
                </div>
                <div className="mt-2 flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[11px]"
                    disabled={installing}
                    onClick={() => onInstall(draft.draft_id)}
                  >
                    <CheckCircle2Icon className="mr-1.5 size-3.5" />
                    Install signed rule
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SubagentRiskCard({
  report,
  busyId,
  onWatch,
  onRetire,
}: {
  report: SubagentFitnessReport;
  busyId: string | null;
  onWatch: (role: string, evidenceItemIds: string[]) => void;
  onRetire: (role: string, evidenceItemIds: string[]) => void;
}) {
  const risks = report.top_risks.slice(0, 3);
  const hasRisks = risks.length > 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        hasRisks
          ? "border-amber-500/30 bg-amber-500/10"
          : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon
              className={cn(
                "size-4",
                hasRisks
                  ? "text-amber-600 dark:text-amber-300"
                  : "text-muted-foreground",
              )}
            />
            Subagent risk
            <Badge variant="outline" className="text-[10px]">
              {report.role_count} roles
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {hasRisks
              ? "Route evidence has identified watch or retirement candidates"
              : "No watch or retirement candidates in current fitness evidence"}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-right font-mono text-[11px]">
          <GateStat label="risks" value={report.top_risks.length} />
          <GateStat
            label="route"
            value={report.top_risks.reduce(
              (total, item) => total + (item.routing_evidence_count ?? 0),
              0,
            )}
          />
        </div>
      </div>
      {hasRisks && (
        <div className="mt-2 space-y-1.5">
          {risks.map((item) => (
            <div
              key={item.role}
              className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-xs font-medium">
                  {item.role}
                </div>
                <Badge
                  variant="outline"
                  className={cn(
                    "shrink-0 text-[10px]",
                    item.verdict === "retire_candidate"
                      ? "border-destructive/30 bg-destructive/10 text-destructive"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                  )}
                >
                  {item.verdict}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                <span>score {item.score.toFixed(2)}</span>
                <span>{item.sample_count} samples</span>
                {(item.routing_evidence_count ?? 0) > 0 && (
                  <span>{item.routing_evidence_count} route evidence</span>
                )}
                {item.by_evidence_source?.deep_research_route_decision ? (
                  <span>
                    {item.by_evidence_source.deep_research_route_decision} deep
                    research
                  </span>
                ) : null}
              </div>
              <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                {item.recommendation}
              </div>
              <div className="mt-2 flex justify-end gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  disabled={busyId === `subagent-policy:${item.role}:watch`}
                  onClick={() => onWatch(item.role, item.evidence_item_ids)}
                >
                  Watch
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  disabled={busyId === `subagent-policy:${item.role}:retire`}
                  onClick={() => onRetire(item.role, item.evidence_item_ids)}
                >
                  Retire
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TopologyPolicyCard({
  topologies,
}: {
  topologies: OrganizationTopology[];
}) {
  const impacted = topologies.filter((topology) => {
    const policy = topology.subagent_policy;
    return policy?.blocked || (policy?.watch_count ?? 0) > 0;
  });
  const blocked = impacted.filter(
    (topology) => topology.subagent_policy?.blocked,
  );
  const watchCount = impacted.reduce(
    (total, topology) => total + (topology.subagent_policy?.watch_count ?? 0),
    0,
  );
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        blocked.length > 0
          ? "border-destructive/30 bg-destructive/10"
          : impacted.length > 0
            ? "border-amber-500/30 bg-amber-500/10"
            : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            Topology policy
            <Badge variant="outline" className="text-[10px]">
              {topologies.length} teams
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {blocked.length > 0
              ? "Operator-retired subagents are present in active topologies"
              : impacted.length > 0
                ? "Watched subagents are present in active topologies"
                : "No active topology is affected by subagent policy"}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-right font-mono text-[11px]">
          <GateStat label="blocked" value={blocked.length} />
          <GateStat label="watch" value={watchCount} />
          <GateStat label="teams" value={topologies.length} />
        </div>
      </div>
      {impacted.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {impacted.slice(0, 3).map((topology) => (
            <div
              key={topology.fingerprint}
              className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-xs font-medium">
                  {topology.name}
                </div>
                <Badge
                  variant="outline"
                  className={cn(
                    "shrink-0 text-[10px]",
                    topology.subagent_policy?.blocked
                      ? "border-destructive/30 bg-destructive/10 text-destructive"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                  )}
                >
                  {topology.subagent_policy?.status ?? "clear"}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
                {[
                  ...(topology.subagent_policy?.retired ?? []),
                  ...(topology.subagent_policy?.watch ?? []),
                ]
                  .slice(0, 3)
                  .map((item) => (
                    <span
                      key={`${topology.fingerprint}:${item.role}:${item.agent_id}`}
                    >
                      {item.role}:{item.agent_id}
                    </span>
                  ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TopologyPromotionCard({
  proposals,
  lift,
}: {
  proposals: OrganizationTopologyProposalsReport;
  lift: OrganizationTopologyLiftReport;
}) {
  const subagentProposals = proposals.subagent_promotion_count ?? 0;
  const improved = lift.reports.filter(
    (item) => item.verdict === "improved",
  ).length;
  const regressed = lift.reports.filter(
    (item) => item.verdict === "regressed",
  ).length;
  const pending = lift.reports.filter(
    (item) => item.verdict === "pending_after_runs",
  ).length;
  const hasSignal = subagentProposals > 0 || lift.count > 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        regressed > 0
          ? "border-destructive/30 bg-destructive/10"
          : hasSignal
            ? "border-emerald-500/25 bg-emerald-500/10"
            : "border-border/60 bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            Team promotion
            <Badge variant="outline" className="text-[10px]">
              {proposals.count} proposals
            </Badge>
          </div>
          <div className="mt-1 truncate text-[11px] text-muted-foreground">
            {subagentProposals > 0
              ? "Strong subagents are ready for team topology promotion"
              : lift.count > 0
                ? "Promotion lift is being tracked from team performance"
                : "No subagent-derived team promotions yet"}
          </div>
        </div>
        <div className="grid grid-cols-4 gap-2 text-right font-mono text-[11px]">
          <GateStat label="sub" value={subagentProposals} />
          <GateStat label="up" value={improved} />
          <GateStat label="wait" value={pending} />
          <GateStat label="down" value={regressed} />
        </div>
      </div>
      {proposals.proposals.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {proposals.proposals.slice(0, 2).map((proposal, index) => (
            <div
              key={`${proposal.base_topology}:${String(proposal.detail.new_agent ?? index)}`}
              className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-xs font-medium">
                  {String(proposal.detail.role ?? proposal.kind)} {"->"}{" "}
                  {String(proposal.detail.new_agent ?? "agent")}
                </div>
                <Badge variant="outline" className="shrink-0 text-[10px]">
                  {((proposal.rank_score ?? proposal.confidence) * 100).toFixed(
                    0,
                  )}
                  %
                </Badge>
              </div>
              {proposal.detail.historical_lift ? (
                <div className="mt-1 text-[10px] text-emerald-700 dark:text-emerald-300">
                  lift +{proposal.detail.historical_lift.improved_count}/-
                  {proposal.detail.historical_lift.regressed_count}
                </div>
              ) : null}
              <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">
                {proposal.rationale}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewQueueRow({
  item,
  busy,
  onPromote,
  onReject,
  onArchive,
}: {
  item: AgentTraceReviewQueueItem;
  busy: boolean;
  onPromote: () => void;
  onReject: () => void;
  onArchive: () => void;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-background/65 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("text-[10px]", priorityClass(item.priority))}>
              {item.priority}
            </Badge>
            <Badge variant="outline" className="text-[10px]">
              {item.target_bucket}
            </Badge>
            <span className="text-[11px] text-muted-foreground">
              x{item.occurrences}
            </span>
          </div>
          <div className="mt-2 text-sm font-medium">{item.title}</div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {item.text}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
            <span>{item.candidate_kind}</span>
            {(item.source_task_ids ?? []).slice(0, 2).map((taskId) => (
              <span key={taskId} className="font-mono">
                {shortId(taskId)}
              </span>
            ))}
          </div>
        </div>
        <div className="flex shrink-0 gap-1">
          <IconButton
            label="Promote"
            disabled={busy}
            onClick={onPromote}
            icon={<CheckCircle2Icon className="size-3.5" />}
          />
          <IconButton
            label="Reject"
            disabled={busy}
            onClick={onReject}
            icon={<XCircleIcon className="size-3.5" />}
          />
          <IconButton
            label="Archive"
            disabled={busy}
            onClick={onArchive}
            icon={<ArchiveIcon className="size-3.5" />}
          />
        </div>
      </div>
    </div>
  );
}

function IconButton({
  label,
  icon,
  disabled,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="size-8"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
    >
      {icon}
    </Button>
  );
}

function PanelTitle({
  icon,
  title,
  meta,
}: {
  icon: ReactNode;
  title: string;
  meta: string;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2 text-sm font-semibold">
        <span className="text-primary">{icon}</span>
        {title}
      </div>
      <span className="text-[11px] text-muted-foreground">{meta}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "amber" | "emerald" | "rose" | "blue";
}) {
  const tones = {
    amber: "border-amber-500/25 bg-amber-500/10",
    emerald: "border-emerald-500/25 bg-emerald-500/10",
    rose: "border-rose-500/25 bg-rose-500/10",
    blue: "border-blue-500/25 bg-blue-500/10",
  };
  return (
    <div className={cn("rounded-lg border px-3 py-2", tones[tone])}>
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
    </div>
  );
}

function EmptyPanel({ title }: { title: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border/70 px-3 py-8 text-center text-sm text-muted-foreground">
      {title}
    </div>
  );
}

function shortId(id: string | number) {
  const text = String(id);
  return text.length > 16 ? `${text.slice(0, 16)}...` : text;
}

function countRecovery(queue: AgentTraceTaskRecoveryQueue, needle: string) {
  return queue.items.filter((item) => item.recommended_action.includes(needle))
    .length;
}

function taskRecoverySteps(item: AgentTraceTaskRecoveryQueue["items"][number]) {
  const raw = item.steps?.length ? item.steps : item.recovery_plan?.steps;
  if (!Array.isArray(raw)) return [];
  return raw.map((step) => step.trim()).filter(Boolean);
}

function taskRecoveryActionLabel(action: string) {
  switch (action) {
    case "takeover_and_resume":
      return "take over + resume";
    case "takeover_for_approval":
      return "take over approval";
    case "resume_from_checkpoint":
      return "resume checkpoint";
    case "restart":
      return "restart";
    case "resume_paused_task":
      return "resume paused";
    case "takeover":
      return "take over";
    case "dispatch":
      return "dispatch";
    case "await_operator_approval":
      return "operator approval";
    case "approval_policy_denied":
      return "approval denied";
    case "capability_policy_denied":
      return "capability denied";
    case "monitor":
      return "monitor";
    default:
      return action.replaceAll("_", " ");
  }
}

function taskRecoveryHint(action: string) {
  switch (action) {
    case "resume_from_checkpoint":
      return "Open the loop run and resume from checkpoint";
    case "restart":
      return "Restart the task from the latest safe state";
    case "await_operator_approval":
      return "Resolve the pending approval request";
    case "approval_policy_denied":
    case "capability_policy_denied":
      return "Review policy before retrying";
    case "dispatch":
      return "Worker dispatch is pending";
    default:
      return taskRecoveryActionLabel(action);
  }
}

function competitorLabel(id: string) {
  if (id === "claude_code") return "Claude";
  if (id === "octopus") return "Octopus";
  if (id === "codex") return "Codex";
  if (id === "cursor") return "Cursor";
  return id;
}

function scorecardGapQueueItemForDimension(
  items: AgentTraceReviewQueueItem[],
  dimensionId: string,
) {
  return (
    items.find((item) => {
      const metadata = item.metadata ?? {};
      return (
        metadata.dimension_id === dimensionId ||
        item.candidate_kind === `scorecard_gap:${dimensionId}` ||
        (item.tags ?? []).includes(dimensionId)
      );
    }) ?? null
  );
}

function formatScore(score: unknown) {
  return typeof score === "number" ? score.toFixed(2) : "--";
}

function formatApplyResult(result: {
  applied: number;
  skipped: number;
  failed: number;
  replay_gate?: AgentTraceReplayGate;
  override_replay_gate?: boolean;
}) {
  const gate = result.replay_gate;
  return `Applied ${result.applied}, skipped ${result.skipped}, failed ${result.failed}${
    gate ? ` · gate ${gate.passed ? "passed" : "blocked"}` : ""
  }${result.override_replay_gate ? " · override" : ""}`;
}

function readRequestErrorMessage(err: unknown): string {
  if (!(err instanceof AgentTraceRequestError)) {
    return err instanceof Error ? err.message : String(err);
  }
  const detail = err.detail;
  if (typeof detail === "string") return detail;
  if (!detail || typeof detail !== "object") return err.message;
  const raw = detail as {
    detail?: unknown;
    error?: unknown;
    message?: unknown;
  };
  if (typeof raw.detail === "string") return raw.detail;
  if (typeof raw.error === "string") return raw.error;
  if (typeof raw.message === "string") return raw.message;
  return err.message;
}

function replayEvidenceFromError(err: unknown): ReplayEvidenceHint | null {
  if (!(err instanceof AgentTraceRequestError)) return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  const raw = detail as {
    replay_evidence?: unknown;
    detail?: unknown;
  };
  const candidate =
    raw.replay_evidence ??
    (raw.detail && typeof raw.detail === "object"
      ? (raw.detail as { replay_evidence?: unknown }).replay_evidence
      : null);
  if (!candidate || typeof candidate !== "object") return null;
  const evidence = candidate as ReplayEvidenceHint;
  if (!evidence.case_id && !evidence.fingerprint && !evidence.queue_url) {
    return null;
  }
  return evidence;
}

function replayGateBlockFromError(
  err: unknown,
): ReplayGateOverridePrompt | null {
  if (!(err instanceof AgentTraceRequestError) || err.status !== 409)
    return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  const raw = detail as {
    message?: unknown;
    replay_gate?: unknown;
  };
  if (!raw.replay_gate || typeof raw.replay_gate !== "object") return null;
  return {
    gate: raw.replay_gate as AgentTraceReplayGate,
    message:
      typeof raw.message === "string"
        ? raw.message
        : "replay gate did not pass",
  };
}
