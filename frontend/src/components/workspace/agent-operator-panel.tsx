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
import { Input } from "@/components/ui/input";
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
  E2E_SURPASS_TARGET_SCORE,
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
  fetchE2ESurpassCertification,
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
  rerunBrowserDesktopRepairRecipeEvidenceBatch,
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
  type E2ESurpassCertification,
  type RepairRouteQualityReport,
  type ReplayEvidenceHint,
  type OrganizationTopology,
  type OrganizationTopologyLiftReport,
  type OrganizationTopologyProposalsReport,
  type SubagentFitnessReport,
} from "@/core/agent-trace/api";
import {
  fetchPluginLifecycleHistory,
  fetchPluginPublisherTrust,
  fetchPluginSmokeSummary,
  revokePluginPublisherKey,
  rotatePluginPublisherKey,
} from "@/core/plugins/api";
import type {
  PluginLifecycleHistory,
  PluginPublisherTrustReport,
  PluginSmokeSummary,
} from "@/core/plugins/types";
import { useI18n } from "@/core/i18n/hooks";
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
  target_score: E2E_SURPASS_TARGET_SCORE,
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
  publisher_verified_count: 0,
  unsigned_count: 0,
  invalid_signature_count: 0,
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

const EMPTY_PLUGIN_PUBLISHER_TRUST: PluginPublisherTrustReport = {
  schema: "octopus.plugin_publisher_trust_report.v1",
  path: "",
  exists: false,
  publisher_count: 0,
  key_count: 0,
  active_key_count: 0,
  revoked_key_count: 0,
  rotation_due_count: 0,
  ready: false,
  publishers: [],
  next_actions: [],
};

const EMPTY_PLUGIN_LIFECYCLE_HISTORY: PluginLifecycleHistory = {
  schema: "octopus.plugin_lifecycle_history.v1",
  total: 0,
  items: [],
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
  target_score: E2E_SURPASS_TARGET_SCORE,
  surpass_margin: 1,
  competitors: ["codex", "claude_code", "openclaw", "hermes", "octopus"],
  external_competitors: ["codex", "claude_code", "openclaw", "hermes"],
  overall: {},
  ranking: [],
  verdict: "behind",
  dimensions: [],
  octopus_below_target: [],
  octopus_strengths: [],
  octopus_external_gap_dimensions: [],
  octopus_focus_gaps: [],
  next_focus: [],
};

const EMPTY_E2E_SURPASS_CERTIFICATION: E2ESurpassCertification = {
  schema: "octopus.e2e_surpass_certification.v1",
  target_score: E2E_SURPASS_TARGET_SCORE,
  ready: false,
  verdict: "needs_work",
  summary: {
    scorecard_octopus: 0,
    scorecard_best_external: 0,
    scorecard_evidence_adjusted_octopus: 0,
    automation_octopus: 0,
    automation_codex: 0,
    quality_ready: 0,
    quality_total: 0,
    all_dimensions_surpassed: false,
    scorecard_gap_dimensions: 0,
    automation_gap_dimensions: 0,
    behavioral_ready: false,
    behavioral_octopus_pass_pow_k: 0,
    behavioral_codex_pass_pow_k: 0,
  },
  checks: [],
  next_actions: [],
};

interface ReplayGateOverridePrompt {
  gate: AgentTraceReplayGate;
  message: string;
}

function useOperatorCopy() {
  const { t } = useI18n();
  return useCallback(
    (source: string) => t.agentOperator[source] ?? source,
    [t.agentOperator],
  );
}

function formatOperatorCopy(
  copy: (source: string) => string,
  source: string,
  values: Record<string, string | number>,
) {
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
    copy(source),
  );
}

export function AgentOperatorPanel() {
  const to = useOperatorCopy();
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
  const [pluginPublisherTrust, setPluginPublisherTrust] =
    useState<PluginPublisherTrustReport>(EMPTY_PLUGIN_PUBLISHER_TRUST);
  const [pluginLifecycleHistory, setPluginLifecycleHistory] =
    useState<PluginLifecycleHistory>(EMPTY_PLUGIN_LIFECYCLE_HISTORY);
  const [trustDenialSummary, setTrustDenialSummary] =
    useState<AgentTraceTrustDenialSummary>(EMPTY_TRUST_DENIAL_SUMMARY);
  const [policyRuleDrafts, setPolicyRuleDrafts] =
    useState<AgentTracePolicyReviewRuleDrafts>(EMPTY_POLICY_REVIEW_RULE_DRAFTS);
  const [agentScorecard, setAgentScorecard] =
    useState<AgentCompetitorScorecard>(EMPTY_AGENT_SCORECARD);
  const [scorecardError, setScorecardError] = useState<string | null>(null);
  const [e2eCertification, setE2eCertification] =
    useState<E2ESurpassCertification>(EMPTY_E2E_SURPASS_CERTIFICATION);
  const [e2eCertificationError, setE2eCertificationError] = useState<
    string | null
  >(null);
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
      pluginLifecycle,
      publisherTrust,
      trustDenials,
      ruleDrafts,
      scorecardResult,
      e2eCertificationResult,
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
      fetchAutomationRadar(E2E_SURPASS_TARGET_SCORE),
      fetchAutomationPolicyRuleDrafts(),
      fetchBrowserDesktopRepairRecipes(),
      fetchBrowserDesktopRepairRecipeVerifications(),
      fetchRepairRouteQuality(),
      fetchPluginSmokeSummary(),
      fetchPluginLifecycleHistory(),
      fetchPluginPublisherTrust(),
      fetchAgentTraceTrustDenialSummary(),
      fetchAgentTracePolicyReviewRuleDrafts(),
      fetchAgentCompetitorScorecard(E2E_SURPASS_TARGET_SCORE)
        .then((scorecard) => ({ scorecard, error: null as string | null }))
        .catch((err: unknown) => {
          swallow(err);
          return {
            scorecard: null,
            error: err instanceof Error ? err.message : String(err),
          };
        }),
      fetchE2ESurpassCertification(E2E_SURPASS_TARGET_SCORE)
        .then((certification) => ({
          certification,
          error: null as string | null,
        }))
        .catch((err: unknown) => {
          swallow(err);
          return {
            certification: null,
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
    setPluginLifecycleHistory(pluginLifecycle);
    setPluginPublisherTrust(publisherTrust);
    setTrustDenialSummary(trustDenials);
    setPolicyRuleDrafts(ruleDrafts);
    if (scorecardResult.scorecard) setAgentScorecard(scorecardResult.scorecard);
    setScorecardError(scorecardResult.error);
    if (e2eCertificationResult.certification) {
      setE2eCertification(e2eCertificationResult.certification);
    }
    setE2eCertificationError(e2eCertificationResult.error);
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
        reason:
          action === "promoted" ? to("Accepted from operator panel.") : "",
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
      setError(to("Override reason is required."));
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
            ? to(
                "Retired from operator panel using subagent fitness route evidence.",
              )
            : to(
                "Placed on watch from operator panel using subagent fitness route evidence.",
              ),
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
        formatOperatorCopy(
          to,
          "Queued {count} {kind} replay review item(s).",
          {
            count: result.queue.created + result.queue.updated,
            kind: to(kind),
          },
        ),
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
        formatOperatorCopy(
          to,
          "Queued {count} browser/desktop repair recipe item(s).",
          { count: result.created + result.updated },
        ),
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
        formatOperatorCopy(
          to,
          "Rejected {rejected} stale replay item(s); archived {archived} repair recipe item(s).",
          {
            rejected: result.rejected_count,
            archived: result.archived_recipe_count ?? 0,
          },
        ),
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

  const onRerunBlockedBrowserDesktopRepairRecipes = async () => {
    setBusyId("rerun-browser-desktop-repair-recipes");
    try {
      const result = await rerunBrowserDesktopRepairRecipeEvidenceBatch({
        promoteSourceCases: false,
        actor: "operator_panel",
      });
      setLastApplyResult(
        formatOperatorCopy(
          to,
          "Reran {attempted} browser/desktop repair recipe(s): {passed} passed, {failed} failed. Source cases remain operator-gated.",
          {
            attempted: result.attempted,
            passed: result.passed,
            failed: result.failed,
          },
        ),
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
        formatOperatorCopy(
          to,
          "Queued {count} repair-route promotion review item(s).",
          { count: result.created + result.updated },
        ),
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
        formatOperatorCopy(to, "Queued {count} replay evidence item(s).", {
          count: result.queue.created + result.queue.updated,
        }),
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
        formatOperatorCopy(
          to,
          "Queued {count} real scorecard gap review item(s).",
          { count: result.total },
        ),
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
        formatOperatorCopy(
          to,
          "Queued {count} {dimension} scorecard remediation item(s).",
          { count: result.total, dimension: dimensionId },
        ),
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
        formatOperatorCopy(
          to,
          "Installed {effect} rule for {tool} · {count} policy rules",
          {
            effect: result.rule.effect,
            tool: result.rule.tool,
            count: result.policy_rule_count,
          },
        ),
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
        formatOperatorCopy(
          to,
          "Installed {effect} automation rule for {tool} · {count} policy rules",
          {
            effect: result.rule.effect,
            tool: result.rule.tool,
            count: result.policy_rule_count,
          },
        ),
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
      setLastApplyResult(
        formatOperatorCopy(to, "Took over task {task}.", { task: taskId }),
      );
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
    <section className="workspace-panel px-5 py-4">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {to("Operator loop")}
          </div>
          <h2 className="mt-1 text-base font-semibold">
            {to("Agent evolution queue")}
          </h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
            {to(
              "Task runs become review candidates first, then you decide what is promoted into memory, backlog, rules, or archive.",
            )}
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
            {to("Apply promoted")}
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
            {to("Refresh")}
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
          label={to("Pending")}
          value={queueSummary.pending_count}
          tone="amber"
        />
        <Metric
          label={to("Promoted")}
          value={queueSummary.by_status.promoted ?? 0}
          tone="emerald"
        />
        <Metric
          label={to("Rejected")}
          value={queueSummary.by_status.rejected ?? 0}
          tone="rose"
        />
        <Metric label={to("Total")} value={queueSummary.total} tone="blue" />
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
      <E2ESurpassCertificationCard
        certification={e2eCertification}
        error={e2eCertificationError}
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
        rerunBusy={busyId === "rerun-browser-desktop-repair-recipes"}
        staleBusy={busyId === "reject-stale-browser-desktop-replay-artifacts"}
        onQueueBrowser={() => void onQueueBrowserDesktopReplay("browser")}
        onQueueDesktop={() => void onQueueBrowserDesktopReplay("desktop")}
        onQueueRepairRecipes={() => void onQueueBrowserDesktopRepairRecipes()}
        onRerunBlocked={() => void onRerunBlockedBrowserDesktopRepairRecipes()}
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
      <PluginHealthCard
        summary={pluginSmokeSummary}
        lifecycle={pluginLifecycleHistory}
      />
      <PublisherTrustCard
        report={pluginPublisherTrust}
        onChanged={setPluginPublisherTrust}
      />
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
            title={to("Recent task runs")}
            meta={`${taskRuns.length} ${to("loaded")}`}
          />
          <div className="overflow-hidden rounded-lg border border-border-default">
            {taskRuns.length === 0 ? (
              <EmptyPanel title={to("No task runs yet")} />
            ) : (
              taskRuns.map((run) => (
                <button
                  key={run.task_id}
                  type="button"
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border-default px-3 py-2 text-left last:border-b-0 hover:bg-muted/40",
                    selectedTaskId === run.task_id && "bg-primary/10",
                  )}
                  onClick={() => setSelectedTaskId(run.task_id)}
                >
                  <StatusDot status={run.status} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {run.title || run.summary || run.task_id}
                    </div>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="font-mono">{shortId(run.task_id)}</span>
                      <span>
                        {run.tool_calls_started ?? 0} {to("tools")}
                      </span>
                      {(run.tool_errors ?? 0) > 0 && (
                        <span className="text-destructive">
                          {run.tool_errors} {to("errors")}
                        </span>
                      )}
                    </div>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    {run.status ?? to("unknown")}
                  </Badge>
                </button>
              ))
            )}
          </div>

          <div className="rounded-lg border border-border-default bg-muted/15 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">
                  {selectedTask?.title ||
                    selectedTask?.summary ||
                    to("No task selected")}
                </div>
                {selectedTaskId && (
                  <div className="font-mono text-xs text-muted-foreground">
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
                {to("Queue review")}
              </Button>
            </div>
            <TimelinePreview timeline={timeline} />
          </div>
        </div>

        <div className="space-y-3">
          <PanelTitle
            icon={<ListChecksIcon className="size-4" />}
            title={to("Pending review queue")}
            meta={`${queueSummary.pending_count} ${to("pending")}`}
          />
          <div className="space-y-2">
            {queueItems.length === 0 ? (
              <EmptyPanel title={to("No pending review items")} />
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
  const to = useOperatorCopy();
  if (!timeline) {
    return <EmptyPanel title={to("No process timeline available")} />;
  }
  const nodes = timeline.timeline.slice(0, 8);
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Badge variant="outline" className="text-xs">
          {to("score")} {formatScore(timeline.overview.score)}
        </Badge>
        <Badge variant="outline" className="text-xs">
          {to("approvals")} {timeline.overview.approval_count ?? 0}
        </Badge>
        <Badge variant="outline" className="text-xs">
          {to("lessons")} {timeline.overview.experience_record_count ?? 0}
        </Badge>
      </div>
      <div className="max-h-72 space-y-1 overflow-y-auto pr-1">
        {nodes.map((node, index) => (
          <div
            key={`${node.lane}-${node.kind}-${node.ts ?? index}`}
            className="grid grid-cols-[5.5rem_1fr] gap-2 rounded-md bg-background/55 px-2 py-1.5 text-xs"
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
  const to = useOperatorCopy();
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
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
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
            {to("Task recovery queue")}
            <Badge variant="outline" className="text-xs">
              {queue.total} {to("tracked")}
            </Badge>
            <Badge
              variant={healthy ? "outline" : "destructive"}
              className="text-xs"
            >
              {actionable.length} {to("action")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {topItem
              ? `${to(taskRecoveryActionLabel(topItem.recommended_action))} · ${topItem.title || topItem.task_id}`
              : to("No stalled, failed, or approval-blocked task runs.")}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-right font-mono text-xs">
          <GateStat label={to("shown")} value={queue.count} />
          <GateStat
            label={to("takeover")}
            value={countRecovery(queue, "takeover")}
          />
          <GateStat
            label={to("resume")}
            value={countRecovery(queue, "resume")}
          />
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
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      <span className="font-mono">{shortId(item.task_id)}</span>
                      <span>{item.status ?? to("unknown")}</span>
                      {item.kind && <span>{item.kind}</span>}
                      {item.lease_health?.state && (
                        <span>
                          {to("lease")} {item.lease_health.state}
                        </span>
                      )}
                    </div>
                  </div>
                  <Badge variant="outline" className="shrink-0 text-xs">
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
                    className="text-xs"
                  >
                    {to(taskRecoveryActionLabel(item.recommended_action))}
                  </Badge>
                  {item.has_checkpoint && (
                    <Badge variant="outline" className="text-xs">
                      {to("checkpoint")} {shortId(checkpointId)}
                    </Badge>
                  )}
                  {item.thread_id && (
                    <Badge variant="outline" className="text-xs">
                      {to("thread")} {shortId(item.thread_id)}
                    </Badge>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <div className="min-w-0 text-xs text-muted-foreground">
                    <div>
                      {item.can_resume
                        ? to("Resume-safe state is available")
                        : item.can_takeover
                          ? to("Lease can be reclaimed")
                          : to(taskRecoveryHint(item.recommended_action))}
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
                      className="h-7 shrink-0 px-2 text-xs"
                      disabled={busy}
                      onClick={() => onTakeover(item.task_id)}
                    >
                      <GitBranchIcon className="mr-1 size-3" />
                      {to("Take over")}
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
  const to = useOperatorCopy();
  const [selectedGapId, setSelectedGapId] = useState<string | null>(null);
  const octopusScore = report.overall.octopus ?? 0;
  const evidenceAdjustedOctopusScore =
    report.evidence_adjusted_overall?.octopus ?? octopusScore;
  const belowTarget = report.octopus_below_target ?? [];
  const focusGaps = report.octopus_focus_gaps ?? belowTarget;
  const externalGaps =
    report.octopus_external_gap_dimensions ??
    report.octopus_external_leaders ??
    [];
  const strengths = report.octopus_strengths ?? [];
  const certification = report.parity_certification;
  const evidenceLayers = report.evidence_layers;
  const behavioralEvidence = evidenceLayers?.behavioral_head_to_head;
  const topGap = focusGaps
    .slice()
    .sort(
      (lhs, rhs) =>
        (rhs.octopus_gap_to_effective_target ?? rhs.octopus_gap_to_target) -
        (lhs.octopus_gap_to_effective_target ?? lhs.octopus_gap_to_target),
    )[0];
  const selectedGapCandidate =
    focusGaps.find((dimension) => dimension.id === selectedGapId) ?? topGap;
  const selectedGap = selectedGapCandidate
    ? (belowTarget.find(
        (dimension) => dimension.id === selectedGapCandidate.id,
      ) ?? selectedGapCandidate)
    : undefined;
  const selectedGapChecklist = selectedGap?.octopus_evidence_checklist ?? [];
  const selectedGapQueueItem = selectedGap
    ? scorecardGapQueueItemForDimension(queueItems, selectedGap.id)
    : null;
  const healthy =
    octopusScore >= report.target_score &&
    externalGaps.length === 0 &&
    (!behavioralEvidence || behavioralEvidence.ready);
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
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
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
            {to("Competitor scorecard")}
            <Badge variant="outline" className="text-xs">
              {error ? to("degraded") : report.verdict.replaceAll("_", " ")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {error
              ? error
              : topGap
                ? `${topGap.title} gap ${
                    topGap.octopus_gap_to_effective_target ??
                    topGap.octopus_gap_to_target
                  } vs effective target`
                : behavioralEvidence && !behavioralEvidence.ready
                  ? to("Behavioral head-to-head is not certified")
                  : certification?.ready
                    ? `Certification passed ${certification.passed}/${certification.total}`
                    : to("Octopus has no tracked effective scorecard gaps")}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {to(
              "Architecture is estimated; static certification and same-task behavioral evidence are tracked separately.",
            )}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-right font-mono text-xs xl:grid-cols-6">
            <GateStat label={to("Architecture")} value={octopusScore} />
            <GateStat
              label={to("Static evidence")}
              value={evidenceAdjustedOctopusScore}
            />
            {behavioralEvidence && (
              <GateStat
                label={to("Behavior %")}
                value={Math.round(behavioralEvidence.octopus_pass_pow_k * 100)}
              />
            )}
            <GateStat label="Codex" value={report.overall.codex ?? 0} />
            <GateStat label="Claude" value={report.overall.claude_code ?? 0} />
            <GateStat label="OpenClaw" value={report.overall.openclaw ?? 0} />
            <GateStat label="Hermes" value={report.overall.hermes ?? 0} />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={queueBusy || focusGaps.length === 0}
            onClick={onQueueRealGaps}
          >
            <ListChecksIcon
              className={cn("mr-1.5 size-3", queueBusy && "animate-spin")}
            />
            {to("Queue real gaps")}
          </Button>
        </div>
      </div>

      <div className="mt-2 grid gap-2 lg:grid-cols-[0.95fr_1.05fr]">
        <div className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {to("Real comparison ranking")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(report.ranking ?? []).map((row, index) => (
              <Badge
                key={row.competitor}
                variant="outline"
                className={cn(
                  "text-xs",
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
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {to("Effective focus gaps")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {focusGaps.length === 0 ? (
              <>
                <Badge variant="outline" className="text-xs">
                  {to("clear")}
                </Badge>
                {certification && (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-xs",
                      certification.ready
                        ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                        : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                    )}
                  >
                    {to("certified")} {certification.passed}/
                    {certification.total}
                  </Badge>
                )}
              </>
            ) : (
              focusGaps.slice(0, 5).map((dimension) => (
                <button
                  key={dimension.id}
                  type="button"
                  aria-controls="scorecard-gap-drilldown"
                  aria-pressed={selectedGap?.id === dimension.id}
                  className={cn(
                    "rounded-full border px-2 py-0.5 text-xs text-amber-700 transition-colors hover:bg-amber-500/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60 dark:text-amber-300",
                    selectedGap?.id === dimension.id
                      ? "border-amber-500/60 bg-amber-500/20"
                      : "border-amber-500/30 bg-amber-500/10",
                  )}
                  onClick={() => setSelectedGapId(dimension.id)}
                >
                  {dimension.title}{" "}
                  {dimension.octopus_gap_to_effective_target ??
                    dimension.octopus_gap_to_target}
                </button>
              ))
            )}
          </div>
          {externalGaps.length > 0 && (
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {to("external leader gaps")}: {externalGaps.length}
            </div>
          )}
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
            className="border-emerald-500/25 bg-emerald-500/10 text-xs text-emerald-700 dark:text-emerald-300"
          >
            {to("leads")} {dimension.title} {dimension.scores.octopus}
          </Badge>
        ))}
        {report.next_focus.slice(0, 2).map((item) => (
          <Badge
            key={item}
            variant="outline"
            className="max-w-full text-xs"
          >
            <span className="truncate">{item}</span>
          </Badge>
        ))}
      </div>
    </div>
  );
}

function E2ESurpassCertificationCard({
  certification,
  error,
}: {
  certification: E2ESurpassCertification;
  error?: string | null;
}) {
  const to = useOperatorCopy();
  const summary = certification.summary;
  const failedChecks = certification.checks.filter((check) => !check.passed);
  const passedChecks = certification.checks.length - failedChecks.length;
  const ready = !error && certification.ready;
  const behavioralReady = summary.behavioral_ready;
  const behavioralBlocked = Boolean(
    certification.behavioral?.infrastructure?.active,
  );
  const focusText = error
    ? error
    : ready
      ? to(
          "same-task repeated behavioral runs and static release gates clear the Codex bar",
        )
      : failedChecks[0]?.title ||
        certification.next_actions[0] ||
        to("waiting for E2E certification evidence");
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        ready
          ? "border-emerald-500/25 bg-emerald-500/10"
          : "border-amber-500/30 bg-amber-500/10",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            {ready ? (
              <CheckCircle2Icon className="size-4 text-emerald-700 dark:text-emerald-300" />
            ) : (
              <XCircleIcon className="size-4 text-amber-700 dark:text-amber-300" />
            )}
            {to("E2E surpass certification")}
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                ready
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
              )}
            >
              {error
                ? to("degraded")
                : certification.verdict.replaceAll("_", " ")}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {to("quality")} {summary.quality_ready}/{summary.quality_total}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                behavioralReady
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
              )}
            >
              {to("behavior")}{" "}
              {behavioralReady
                ? to("verified")
                : behavioralBlocked
                  ? to("provider blocked")
                  : to("missing")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {focusText}
          </div>
          {!error && (
            <div className="mt-1 truncate text-xs text-muted-foreground">
              {to("scorecard")} {summary.scorecard_octopus}{" "}
              {to("vs best external")} {summary.scorecard_best_external} ·{" "}
              {to("automation")} {summary.automation_octopus} {to("vs Codex")}{" "}
              {summary.automation_codex}
              {behavioralReady && (
                <>
                  {" "}
                  · pass^k{" "}
                  {Math.round(summary.behavioral_octopus_pass_pow_k * 100)}% vs
                  Codex {Math.round(summary.behavioral_codex_pass_pow_k * 100)}%
                </>
              )}
            </div>
          )}
        </div>
        <div className="grid shrink-0 grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 text-right font-mono text-xs">
          <GateStat label={to("Scorecard")} value={summary.scorecard_octopus} />
          <GateStat
            label={to("Evidence")}
            value={summary.scorecard_evidence_adjusted_octopus}
          />
          <GateStat
            label={to("Automation")}
            value={summary.automation_octopus}
          />
          <GateStat label={to("Quality")} value={summary.quality_ready} />
          <GateStat
            label={
              behavioralBlocked ? to("Behavior blocked") : to("Behavior")
            }
            value={
              behavioralReady
                ? Math.round(summary.behavioral_octopus_pass_pow_k * 100)
                : 0
            }
          />
        </div>
      </div>

      <div className="mt-2 grid gap-2 lg:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5">
          <div className="mb-1 flex items-center justify-between gap-2">
            <div className="min-w-0 truncate text-xs font-medium text-muted-foreground">
              {to("Certification checks")}
            </div>
            <Badge variant="outline" className="shrink-0 text-xs">
              {passedChecks}/{certification.checks.length}
            </Badge>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {failedChecks.length === 0 && certification.checks.length > 0 ? (
              <Badge
                variant="outline"
                className="border-emerald-500/25 bg-emerald-500/10 text-xs text-emerald-700 dark:text-emerald-300"
              >
                {to("all checks passed")}
              </Badge>
            ) : (
              failedChecks.slice(0, 3).map((check) => (
                <Badge
                  key={check.id}
                  variant="outline"
                  className="border-amber-500/30 bg-amber-500/10 text-xs text-amber-700 dark:text-amber-300"
                >
                  {check.title} {check.score}/{check.target}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="rounded-md border border-background/70 bg-background/60 px-2 py-1.5">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {to("Gap counters")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline" className="text-xs">
              {to("scorecard gaps")} {summary.scorecard_gap_dimensions}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {to("automation gaps")} {summary.automation_gap_dimensions}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                summary.all_dimensions_surpassed &&
                  "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
              )}
            >
              {to("dimensions")}{" "}
              {summary.all_dimensions_surpassed
                ? to("surpassed")
                : to("open")}
            </Badge>
          </div>
        </div>
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
  const to = useOperatorCopy();
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
      aria-label={`${to("Scorecard gap drill-down for")} ${gap.title}`}
      className="mt-2 rounded-md border border-background/70 bg-background/60 px-2 py-1.5"
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-semibold">{gap.title}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {gap.why}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          {queueItem ? (
            <Badge
              variant="outline"
              className="border-blue-500/25 bg-blue-500/10 text-xs text-blue-700 dark:text-blue-300"
            >
              {to("queued")} {queueItem.priority}
            </Badge>
          ) : null}
          <Badge variant="outline" className="text-xs">
            {to("real")} {realScore}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {to("evidence")} {evidenceScore}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {to("effective gap")}{" "}
            {gap.octopus_gap_to_effective_target ?? gap.octopus_gap_to_target}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {to("surpass gap")} {gap.octopus_gap_to_surpass ?? 0}
          </Badge>
          {gap.best_external_competitor && (
            <Badge variant="outline" className="text-xs">
              {to("best")} {competitorLabel(gap.best_external_competitor)}{" "}
              {gap.best_external_score ?? 0}
            </Badge>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-col gap-2 rounded-md border border-border-default bg-muted/15 px-2 py-1.5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-medium text-muted-foreground">
            {to("Remediation queue")}
          </div>
          <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
            {queueItem
              ? `${queueItem.id} · ${queueItem.status} · x${queueItem.occurrences}`
              : to("not queued")}
          </div>
          {queueItem ? (
            <div className="mt-0.5 truncate font-mono text-xs text-muted-foreground">
              {to("target")} {queueItem.target_bucket} · {to("audit")}{" "}
              {auditSummary.total}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-7 px-2 text-xs"
            disabled={queueBusy}
            onClick={onQueue}
          >
            <ListChecksIcon
              className={cn("mr-1.5 size-3", queueBusy && "animate-spin")}
            />
            {queueItem ? to("Refresh queue item") : to("Queue this gap")}
          </Button>
          {queueItem ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs"
              disabled={applyBusy || queueItem.status !== "promoted"}
              onClick={onApplyPromoted}
            >
              <CheckCircle2Icon
                className={cn("mr-1.5 size-3", applyBusy && "animate-spin")}
              />
              {to("Apply gap")}
            </Button>
          ) : null}
        </div>
      </div>

      {nextActions.length > 0 && (
        <div className="mt-2 grid gap-1.5 lg:grid-cols-2">
          {nextActions.slice(0, 2).map((action) => (
            <div
              key={action}
              className="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-800 dark:text-amber-200"
            >
              {action}
            </div>
          ))}
        </div>
      )}

      {operatorDrilldown?.schema ===
        "octopus.scorecard_operator_drilldown.v1" &&
        drilldownLinks.length > 0 && (
          <div className="mt-2 rounded-md border border-border-default bg-muted/15 px-2 py-1.5">
            <div className="mb-1 flex items-center justify-between gap-2">
              <div className="min-w-0 truncate text-xs font-medium text-muted-foreground">
                {to("Evidence sources")}
              </div>
              <Badge variant="outline" className="shrink-0 text-xs">
                {drilldownLinks.length} {to("links")}
              </Badge>
            </div>
            <div className="grid gap-1.5 lg:grid-cols-2">
              {drilldownLinks.slice(0, 4).map((link) => (
                <div
                  key={`${link.id ?? link.label}-${link.href}`}
                  className="min-w-0 rounded-md border border-border-default bg-background/50 px-2 py-1.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0 truncate text-xs font-medium">
                      {link.label ?? link.id ?? to("Evidence link")}
                    </div>
                    {link.method ? (
                      <Badge variant="outline" className="shrink-0 text-xs">
                        {link.method}
                      </Badge>
                    ) : null}
                  </div>
                  {link.href ? (
                    <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
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
            <div className="min-w-0 truncate text-xs font-medium text-muted-foreground">
              {to("Evidence checklist")}
            </div>
            <Badge variant="outline" className="shrink-0 text-xs">
              {gap.octopus_missing_evidence_count ?? 0} {to("missing")}
            </Badge>
          </div>
          <div className="grid gap-1.5 lg:grid-cols-2">
            {checklist.slice(0, 2).map((item) => (
              <div
                key={item.id ?? item.title}
                className="rounded-md border border-border-default bg-muted/15 px-2 py-1.5"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-xs font-medium">
                    {item.title ?? item.id ?? "evidence"}
                  </div>
                  <Badge variant="outline" className="shrink-0 text-xs">
                    {Math.round((item.score ?? 0) * 100)}%
                  </Badge>
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5 text-xs text-muted-foreground">
                  <span>
                    {to("impl")} {item.implementation.present}/
                    {item.implementation.total}
                  </span>
                  <span>
                    {to("tests")} {item.tests.present}/{item.tests.total}
                  </span>
                  {item.implementation.missing_count +
                    item.tests.missing_count >
                    0 && (
                    <span className="text-amber-700 dark:text-amber-300">
                      {item.implementation.missing_count +
                        item.tests.missing_count}{" "}
                      {to("missing")}
                    </span>
                  )}
                </div>
                {item.next_actions[0] && (
                  <div className="mt-1 truncate text-xs text-muted-foreground">
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
  const to = useOperatorCopy();
  const octopusScore = radar.overall.octopus ?? 0;
  const codexScore = radar.overall.codex ?? 0;
  const readyDrafts = radar.policy_rule_drafts.ready;
  const topDraft = drafts.drafts[0] ?? null;
  const topGaps = radar.octopus_gaps ?? [];
  return (
    <div className="mt-3 rounded-lg border border-border-default bg-background/60 px-3 py-2">
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon className="size-4 text-blue-700 dark:text-blue-300" />
            {to("Automation radar")}
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                radar.verdict === "leading" &&
                  "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
              )}
            >
              {radar.verdict.replaceAll("_", " ")}
            </Badge>
            <Badge
              variant="outline"
              className={cn(
                "text-xs",
                readyDrafts
                  ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                  : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
              )}
            >
              {to("policy drafts")} {radar.policy_rule_drafts.verified}/
              {radar.policy_rule_drafts.total}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {to(
              "Browser, desktop, visual replay, and signed automation policy coverage.",
            )}
          </div>
        </div>
        <div className="grid shrink-0 grid-cols-2 sm:grid-cols-3 gap-2 text-right font-mono text-xs">
          <GateStat label={to("Octo auto")} value={octopusScore} />
          <GateStat label="Codex" value={codexScore} />
          <GateStat
            label={to("Ready")}
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
        <div className="rounded-md border border-border-default bg-muted/15 px-2 py-1.5">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            {to("Remaining automation edges")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {topGaps.length === 0 ? (
              <Badge variant="outline" className="text-xs">
                {to("clear")}
              </Badge>
            ) : (
              topGaps.slice(0, 4).map((gap) => (
                <Badge key={gap.id} variant="outline" className="text-xs">
                  {gap.title} {gap.scores.octopus}
                </Badge>
              ))
            )}
          </div>
        </div>
        <div className="rounded-md border border-border-default bg-muted/15 px-2 py-1.5">
          <div className="mb-1 flex items-center justify-between gap-2">
            <div className="min-w-0 truncate text-xs font-medium text-muted-foreground">
              {to("Signed automation rule drafts")}
            </div>
            <Badge variant="outline" className="shrink-0 text-xs">
              {drafts.verified}/{drafts.total}
            </Badge>
          </div>
          {topDraft ? (
            <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="truncate font-mono text-xs">
                  {topDraft.signed_payload.rule.tool}
                </div>
                <div className="truncate text-xs text-muted-foreground">
                  {topDraft.signed_payload.rule.reason}
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 shrink-0 px-2 text-xs"
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
                {to("Install deny rule")}
              </Button>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">
              {to("No automation rule drafts available.")}
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
  const to = useOperatorCopy();
  const gate = prompt?.gate ?? null;
  return (
    <Dialog open={!!prompt} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{to("Replay gate blocked apply")}</DialogTitle>
          <DialogDescription>
            {to(
              "Promotion was stopped because replay gate did not pass. Override only when you have reviewed the failing cases.",
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2">
          <div className="text-sm font-medium text-destructive">
            {prompt?.message ?? to("Replay gate did not pass")}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {gate?.reason || to("No reason provided")}
          </div>
          <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2 text-center font-mono text-xs">
            <GateStat label={to("cases")} value={gate?.summary.total ?? 0} />
            <GateStat label={to("pass")} value={gate?.summary.passed ?? 0} />
            <GateStat label={to("fail")} value={gate?.summary.failed ?? 0} />
            <GateStat
              label={to("low")}
              value={gate?.summary.below_min_score ?? 0}
            />
          </div>
        </div>
        <Textarea
          aria-label={to("Override reason")}
          value={reason}
          onChange={(event) => onReasonChange(event.target.value)}
          placeholder={to(
            "Record why this replay gate override is acceptable.",
          )}
          className="min-h-24 resize-none text-sm"
        />
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            {to("Cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={onConfirm}
            disabled={busy || !reason.trim()}
          >
            {to("Override gate")}
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
  const to = useOperatorCopy();
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
          : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-medium">{to("Promotion audit")}</div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {!integrityOk
              ? `Audit chain broken at #${integrity?.broken_at ?? "?"}`
              : topologyBlocks > 0
                ? to("Operator policy blocked team topology attempts")
                : risky
                  ? to("Overrides were used after replay gate blocked apply")
                  : to("No blocked gate overrides recorded")}
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {to("chain")} {integrityOk ? to("ok") : to("failed")} ·{" "}
            {integrity?.entries_checked ?? 0} {to("checked")}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-right font-mono text-xs">
          <GateStat label={to("audit")} value={summary.total} />
          <GateStat label={to("over")} value={summary.override_count} />
          <GateStat label={to("gate")} value={summary.gate_failed_count} />
          <GateStat label={to("topo")} value={topologyBlocks} />
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
  const to = useOperatorCopy();
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
            : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            {to("Memory quality")}
            <Badge variant="outline" className="text-xs">
              {reliabilityPercent}% {to("reliable")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {topAction ??
              (summary.total > 0
                ? to("Recall memories are fresh and contradiction-clean")
                : to("No committed experience memories yet"))}
          </div>
          <div className="mt-1 truncate font-mono text-xs text-muted-foreground">
            {to("active")} {summary.active_count} · {to("bucket experience")}{" "}
            {summary.by_bucket.experience ?? 0}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-right font-mono text-xs">
          <GateStat label={to("mem")} value={summary.total} />
          <GateStat label={to("stale")} value={summary.stale_count} />
          <GateStat label={to("contra")} value={summary.contradicted_count} />
          <GateStat label={to("low")} value={summary.low_reliability_count} />
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
  const to = useOperatorCopy();
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
              : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ListChecksIcon className="size-4 text-primary" />
            {to("Auto verifier")}
            <Badge variant="outline" className="text-xs">
              {passPercent}% {to("pass")}
            </Badge>
            <Badge
              variant={repairRoutes.ready ? "outline" : "destructive"}
              className="text-xs"
            >
              {to("routes")} {repairScorePercent}%
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {alerts[0]?.message ??
              (latest
                ? latest.selected_command
                : to("No auto-verifier decisions recorded yet"))}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-right font-mono text-xs">
          <GateStat label={to("runs")} value={report.total} />
          <GateStat label={to("pass")} value={report.pass_count} />
          <GateStat label={to("fail")} value={report.fail_count} />
          <GateStat
            label="ms"
            value={Math.round(report.avg_duration_ms ?? 0)}
          />
        </div>
      </div>
      <div className="mt-2 flex flex-col gap-2 rounded-md border border-background/70 bg-background/60 px-2 py-1.5 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">
            {repairCandidates.length}
          </span>{" "}
          {to("repair-route promotion candidate(s)")}
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
          className="h-7 shrink-0 px-2 text-xs"
          onClick={onQueueRepairRoutes}
          disabled={queueBusy || repairCandidates.length === 0}
        >
          <GitBranchIcon className="mr-1.5 size-3" />
          {to("Queue routes")}
        </Button>
      </div>
      {alerts.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {alerts.slice(0, 3).map((alert) => (
            <Badge
              key={`${alert.family}:${alert.severity}`}
              variant="outline"
              className="border-destructive/30 bg-destructive/10 text-xs text-destructive"
            >
              {alert.family} {to("drift")}{" "}
              {Math.round(alert.pass_rate * 100)}%
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
                <div className="min-w-0 truncate font-mono text-xs">
                  #{candidate.rank} {candidate.command}
                </div>
                <Badge variant="outline" className="shrink-0 text-xs">
                  {candidate.family}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>
                  {Math.round(candidate.pass_rate * 100)}% {to("history")}
                </span>
                <span>
                  {candidate.history_count} {to("samples")}
                </span>
                <span>{Math.round(candidate.avg_duration_ms)}ms</span>
              </div>
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {candidate.reason}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PluginHealthCard({
  summary,
  lifecycle,
}: {
  summary: PluginSmokeSummary;
  lifecycle: PluginLifecycleHistory;
}) {
  const to = useOperatorCopy();
  const risky =
    summary.failed_count > 0 ||
    summary.warning_count > 0 ||
    (summary.invalid_signature_count ?? 0) > 0;
  const compatibility = summary.compatibility;
  const rows =
    summary.failed.length > 0
      ? summary.failed
      : summary.review_required.length > 0
        ? summary.review_required
        : summary.warnings;
  const latestLifecycle = lifecycle.items.at(-1);
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        summary.failed_count > 0
          ? "border-destructive/30 bg-destructive/10"
          : risky
            ? "border-amber-500/30 bg-amber-500/10"
            : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ListChecksIcon className="size-4 text-primary" />
            {to("Plugin health")}
            <Badge variant="outline" className="text-xs">
              {summary.ok_count}/{summary.total} {to("ok")}
            </Badge>
            {compatibility && (
              <Badge
                variant="outline"
                className={cn(
                  "text-xs",
                  compatibility.verdict === "fail"
                    ? "border-destructive/30 bg-destructive/10 text-destructive"
                    : compatibility.verdict === "review"
                      ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                      : "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
                )}
              >
                {to("compat")} {compatibility.verdict}
              </Badge>
            )}
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {summary.failed_count > 0
              ? to("Some plugins failed local smoke checks")
              : summary.review_required_count > 0
                ? to("Some local plugins need operator review")
                : to("Installed Codex plugins passed local smoke checks")}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-right font-mono text-xs">
          <GateStat label={to("total")} value={summary.total} />
          <GateStat label={to("ok")} value={summary.ok_count} />
          <GateStat label={to("fail")} value={summary.failed_count} />
          <GateStat label={to("warn")} value={summary.warning_count} />
          <GateStat
            label="signed"
            value={summary.publisher_verified_count ?? 0}
          />
          {compatibility && (
            <GateStat label="compat" value={compatibility.passed} />
          )}
        </div>
      </div>
      {compatibility?.next_actions?.[0] && (
        <div className="mt-2 truncate text-xs text-muted-foreground">
          {compatibility.next_actions[0]}
        </div>
      )}
      <div className="mt-2 flex items-center justify-between gap-2 rounded-md border border-background/70 bg-background/60 px-2 py-1.5 text-xs">
        <span className="font-medium">{to("Lifecycle history")}</span>
        <span className="min-w-0 truncate text-muted-foreground">
          {latestLifecycle
            ? `${latestLifecycle.operation} ${latestLifecycle.plugin_id} · ${latestLifecycle.status}`
            : to("No install, upgrade, or rollback transactions")}
        </span>
        <Badge variant="outline" className="shrink-0 text-xs">
          {lifecycle.total} {to("tx")}
        </Badge>
      </div>
      {rows.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rows.slice(0, 4).map((item, index) => (
            <Badge
              key={`${item.plugin_id ?? item.plugin_name ?? index}`}
              variant="outline"
              className={cn(
                "max-w-full text-xs",
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

function PublisherTrustCard({
  report,
  onChanged,
}: {
  report: PluginPublisherTrustReport;
  onChanged: (report: PluginPublisherTrustReport) => void;
}) {
  const to = useOperatorCopy();
  const [mode, setMode] = useState<"rotate" | "revoke" | null>(null);
  const [publisherId, setPublisherId] = useState("");
  const [previousKeyId, setPreviousKeyId] = useState("");
  const [keyId, setKeyId] = useState("");
  const [publicKey, setPublicKey] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);

  const openRotate = (publisher = "", previous = "") => {
    setPublisherId(publisher);
    setPreviousKeyId(previous);
    setKeyId("");
    setPublicKey("");
    setReason("scheduled rotation");
    setDialogError(null);
    setMode("rotate");
  };
  const openRevoke = (publisher: string, key: string) => {
    setPublisherId(publisher);
    setKeyId(key);
    setReason("");
    setDialogError(null);
    setMode("revoke");
  };
  const submit = async () => {
    if (!mode) return;
    setBusy(true);
    setDialogError(null);
    try {
      const result =
        mode === "rotate"
          ? await rotatePluginPublisherKey({
              publisher_id: publisherId,
              previous_key_id: previousKeyId || undefined,
              new_key_id: keyId,
              new_public_key: publicKey,
              reason,
            })
          : await revokePluginPublisherKey({
              publisher_id: publisherId,
              key_id: keyId,
              reason,
            });
      onChanged(result.trust);
      setMode(null);
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        report.ready
          ? "border-border-default bg-muted/15"
          : "border-amber-500/30 bg-amber-500/10",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlertIcon className="size-4 text-primary" />
            {to("Publisher trust")}
            <Badge variant="outline" className="text-xs">
              {report.active_key_count} {to("active")}
            </Badge>
            {report.rotation_due_count > 0 && (
              <Badge
                variant="outline"
                className="border-amber-500/30 text-xs text-amber-700 dark:text-amber-300"
              >
                {report.rotation_due_count} {to("due")}
              </Badge>
            )}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {to(
              "Ed25519 publisher keys · atomic rotation · audited revocation",
            )}
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={() => openRotate()}>
          {to("Rotate key")}
        </Button>
      </div>
      <div className="mt-2 space-y-1.5">
        {report.publishers.flatMap((publisher) =>
          publisher.keys.map((key) => (
            <div
              key={`${publisher.publisher_id}:${key.key_id}`}
              className="flex items-center justify-between gap-2 rounded-md border border-border-default bg-background/40 px-2 py-1.5"
            >
              <div className="min-w-0 text-xs">
                <div className="truncate font-mono">
                  {publisher.publisher_id}/{key.key_id}
                </div>
                <div className="truncate text-muted-foreground">
                  {key.public_key_fingerprint}
                  {key.age_days !== null ? ` · ${key.age_days}d` : ""}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Badge variant="outline" className="text-xs">
                  {key.status}
                </Badge>
                {key.status === "active" && (
                  <>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        openRotate(publisher.publisher_id, key.key_id)
                      }
                    >
                      {to("Replace")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-destructive"
                      onClick={() =>
                        openRevoke(publisher.publisher_id, key.key_id)
                      }
                    >
                      {to("Revoke")}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )),
        )}
        {report.publishers.length === 0 && (
          <div className="text-xs text-muted-foreground">
            {report.next_actions[0] ?? to("No publisher keys registered.")}
          </div>
        )}
      </div>

      <Dialog
        open={mode !== null}
        onOpenChange={(open) => !open && setMode(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {mode === "rotate"
                ? to("Rotate publisher key")
                : to("Revoke publisher key")}
            </DialogTitle>
            <DialogDescription>
              {mode === "rotate"
                ? to(
                    "Register a new Ed25519 public key and retire the previous key atomically.",
                  )
                : to(
                    "Revocation takes effect immediately and is written to the governance audit chain.",
                  )}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              aria-label={to("Publisher ID")}
              placeholder={to("Publisher ID")}
              value={publisherId}
              disabled={mode === "revoke"}
              onChange={(event) => setPublisherId(event.target.value)}
            />
            {mode === "rotate" && (
              <Input
                aria-label={to("Previous key ID")}
                placeholder={to("Previous key ID (optional)")}
                value={previousKeyId}
                onChange={(event) => setPreviousKeyId(event.target.value)}
              />
            )}
            <Input
              aria-label={
                mode === "rotate" ? to("New key ID") : to("Key ID")
              }
              placeholder={
                mode === "rotate" ? to("New key ID") : to("Key ID")
              }
              value={keyId}
              disabled={mode === "revoke"}
              onChange={(event) => setKeyId(event.target.value)}
            />
            {mode === "rotate" && (
              <Textarea
                aria-label={to("Ed25519 public key")}
                placeholder={to("Base64 Ed25519 public key")}
                value={publicKey}
                onChange={(event) => setPublicKey(event.target.value)}
              />
            )}
            <Textarea
              aria-label={to("Reason")}
              placeholder={to("Reason")}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            {dialogError && (
              <div className="text-sm text-destructive">{dialogError}</div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setMode(null)}
              disabled={busy}
            >
              {to("Cancel")}
            </Button>
            <Button
              variant={mode === "revoke" ? "destructive" : "default"}
              disabled={
                busy ||
                !publisherId.trim() ||
                !keyId.trim() ||
                !reason.trim() ||
                (mode === "rotate" && !publicKey.trim())
              }
              onClick={() => void submit()}
            >
              {busy
                ? to("Applying…")
                : mode === "rotate"
                  ? to("Rotate")
                  : to("Revoke")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
  const to = useOperatorCopy();
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
          : "border-border-default bg-muted/15",
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
            {to("Tool safety")}
            <Badge variant="outline" className="text-xs">
              {summary.total} {to("denied")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {summary.total > 0
              ? `${topTool?.[0] ?? "tool"} has recent policy denials`
              : to("No static tool denials recorded in current trace window")}
          </div>
        </div>
        <div className="flex shrink-0 items-start gap-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-right font-mono text-xs">
            <GateStat label={to("deny")} value={summary.by_action.deny ?? 0} />
            <GateStat
              label={to("block")}
              value={summary.by_action.block ?? 0}
            />
            <GateStat label={to("halt")} value={summary.by_action.halt ?? 0} />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 shrink-0 px-2 text-xs"
            disabled={!canQueue || busy}
            onClick={onQueuePolicyReview}
          >
            <ListChecksIcon className="mr-1.5 size-3.5" />
            {to("Queue policy review")}
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
                <Badge variant="outline" className="shrink-0 text-xs">
                  {item.risk_level || item.action}
                </Badge>
              </div>
              <div className="mt-1 truncate text-xs text-muted-foreground">
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
  const to = useOperatorCopy();
  const drafts = report.drafts ?? [];
  const hasDrafts = drafts.length > 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        hasDrafts
          ? "border-emerald-500/25 bg-emerald-500/10"
          : "border-border-default bg-muted/15",
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
            {to("Policy review rules")}
            <Badge variant="outline" className="text-xs">
              {report.verified}/{report.total} {to("signed")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {hasDrafts
              ? to(
                  "Replay-backed policy reviews produced signed install drafts",
                )
              : to("No signed policy-review rule drafts yet")}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-right font-mono text-xs">
          <GateStat label={to("drafts")} value={report.total} />
          <GateStat label={to("signed")} value={report.verified} />
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
                  <Badge variant="outline" className="shrink-0 text-xs">
                    {shortId(signature || draft.draft_id)}
                  </Badge>
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {rule.reason || to("Replay-backed policy review rule")}
                </div>
                <div className="mt-2 flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-xs"
                    disabled={installing}
                    onClick={() => onInstall(draft.draft_id)}
                  >
                    <CheckCircle2Icon className="mr-1.5 size-3.5" />
                    {to("Install signed rule")}
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
  const to = useOperatorCopy();
  const risks = report.top_risks.slice(0, 3);
  const hasRisks = risks.length > 0;
  return (
    <div
      className={cn(
        "mt-3 rounded-lg border px-3 py-2",
        hasRisks
          ? "border-amber-500/30 bg-amber-500/10"
          : "border-border-default bg-muted/15",
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
            {to("Subagent risk")}
            <Badge variant="outline" className="text-xs">
              {report.role_count} {to("roles")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {hasRisks
              ? to(
                  "Route evidence has identified watch or retirement candidates",
                )
              : to(
                  "No watch or retirement candidates in current fitness evidence",
                )}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-right font-mono text-xs">
          <GateStat label={to("risks")} value={report.top_risks.length} />
          <GateStat
            label={to("route")}
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
                    "shrink-0 text-xs",
                    item.verdict === "retire_candidate"
                      ? "border-destructive/30 bg-destructive/10 text-destructive"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                  )}
                >
                  {item.verdict}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>
                  {to("score")} {item.score.toFixed(2)}
                </span>
                <span>
                  {item.sample_count} {to("samples")}
                </span>
                {(item.routing_evidence_count ?? 0) > 0 && (
                  <span>
                    {item.routing_evidence_count} {to("route evidence")}
                  </span>
                )}
                {item.by_evidence_source?.deep_research_route_decision ? (
                  <span>
                    {item.by_evidence_source.deep_research_route_decision}{" "}
                    {to("deep research")}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                {item.recommendation}
              </div>
              <div className="mt-2 flex justify-end gap-1.5">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={busyId === `subagent-policy:${item.role}:watch`}
                  onClick={() => onWatch(item.role, item.evidence_item_ids)}
                >
                  {to("Watch")}
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  size="sm"
                  className="h-7 px-2 text-xs"
                  disabled={busyId === `subagent-policy:${item.role}:retire`}
                  onClick={() => onRetire(item.role, item.evidence_item_ids)}
                >
                  {to("Retire")}
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
  const to = useOperatorCopy();
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
            : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            {to("Topology policy")}
            <Badge variant="outline" className="text-xs">
              {topologies.length} {to("teams")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {blocked.length > 0
              ? to(
                  "Operator-retired subagents are present in active topologies",
                )
              : impacted.length > 0
                ? to("Watched subagents are present in active topologies")
                : to("No active topology is affected by subagent policy")}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-right font-mono text-xs">
          <GateStat label={to("blocked")} value={blocked.length} />
          <GateStat label={to("watch")} value={watchCount} />
          <GateStat label={to("teams")} value={topologies.length} />
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
                    "shrink-0 text-xs",
                    topology.subagent_policy?.blocked
                      ? "border-destructive/30 bg-destructive/10 text-destructive"
                      : "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
                  )}
                >
                  {topology.subagent_policy?.status ?? to("clear")}
                </Badge>
              </div>
              <div className="mt-1 flex flex-wrap gap-2 text-xs text-muted-foreground">
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
  const to = useOperatorCopy();
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
            : "border-border-default bg-muted/15",
      )}
    >
      <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <GitBranchIcon className="size-4 text-primary" />
            {to("Team promotion")}
            <Badge variant="outline" className="text-xs">
              {proposals.count} {to("proposals")}
            </Badge>
          </div>
          <div className="mt-1 truncate text-xs text-muted-foreground">
            {subagentProposals > 0
              ? to("Strong subagents are ready for team topology promotion")
              : lift.count > 0
                ? to("Promotion lift is being tracked from team performance")
                : to("No subagent-derived team promotions yet")}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-right font-mono text-xs">
          <GateStat label={to("sub")} value={subagentProposals} />
          <GateStat label={to("up")} value={improved} />
          <GateStat label={to("wait")} value={pending} />
          <GateStat label={to("down")} value={regressed} />
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
                <Badge variant="outline" className="shrink-0 text-xs">
                  {((proposal.rank_score ?? proposal.confidence) * 100).toFixed(
                    0,
                  )}
                  %
                </Badge>
              </div>
              {proposal.detail.historical_lift ? (
                <div className="mt-1 text-xs text-emerald-700 dark:text-emerald-300">
                  lift +{proposal.detail.historical_lift.improved_count}/-
                  {proposal.detail.historical_lift.regressed_count}
                </div>
              ) : null}
              <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
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
  const to = useOperatorCopy();
  return (
    <div className="rounded-lg border border-border-default bg-background/65 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("text-xs", priorityClass(item.priority))}>
              {item.priority}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {item.target_bucket}
            </Badge>
            <span className="text-xs text-muted-foreground">
              x{item.occurrences}
            </span>
          </div>
          <div className="mt-2 text-sm font-medium">{item.title}</div>
          <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {item.text}
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
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
            label={to("Promote")}
            disabled={busy}
            onClick={onPromote}
            icon={<CheckCircle2Icon className="size-3.5" />}
          />
          <IconButton
            label={to("Reject")}
            disabled={busy}
            onClick={onReject}
            icon={<XCircleIcon className="size-3.5" />}
          />
          <IconButton
            label={to("Archive")}
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
      <span className="text-xs text-muted-foreground">{meta}</span>
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
      <div className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-xl font-semibold">{value}</div>
    </div>
  );
}

function EmptyPanel({ title }: { title: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border-default px-3 py-8 text-center text-sm text-muted-foreground">
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
  if (id === "openclaw") return "OpenClaw";
  if (id === "hermes") return "Hermes";
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
