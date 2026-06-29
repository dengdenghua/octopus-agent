import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AgentOperatorPanel } from "./agent-operator-panel";

const api = vi.hoisted(() => ({
  AgentTraceRequestError: class AgentTraceRequestError extends Error {
    status: number;
    detail: unknown;

    constructor(status: number, detail: unknown) {
      super(`Agent trace request failed: ${status}`);
      this.name = "AgentTraceRequestError";
      this.status = status;
      this.detail = detail;
    }
  },
  applyAgentTraceReviewQueuePromotions: vi.fn(),
  decideAgentTraceReviewQueueItem: vi.fn(),
  decideSubagentPolicy: vi.fn(),
  fetchAgentCompetitorScorecard: vi.fn(),
  fetchAgentTraceProcessTimeline: vi.fn(),
  fetchAgentTraceExperienceQualitySummary: vi.fn(),
  fetchAgentTracePolicyReviewRuleDrafts: vi.fn(),
  fetchAgentTracePromotionAuditSummary: vi.fn(),
  fetchAgentTraceReplayGate: vi.fn(),
  fetchAgentTraceReviewQueue: vi.fn(),
  fetchAgentTraceReviewQueueSummary: vi.fn(),
  fetchAgentTraceTaskRuns: vi.fn(),
  fetchAgentTraceTrustDenialSummary: vi.fn(),
  fetchTaskRecoveryQueue: vi.fn(),
  fetchAutomationPolicyRuleDrafts: vi.fn(),
  fetchAutomationRadar: vi.fn(),
  fetchAutoVerifierMetrics: vi.fn(),
  fetchBrowserDesktopQuality: vi.fn(),
  fetchBrowserDesktopRepairRecipeVerifications: vi.fn(),
  fetchBrowserDesktopRepairRecipes: vi.fn(),
  fetchRepairRouteQuality: vi.fn(),
  fetchOrganizationTopologyLift: vi.fn(),
  fetchOrganizationTopologyProposals: vi.fn(),
  fetchOrganizationTopologies: vi.fn(),
  fetchSubagentFitness: vi.fn(),
  installAutomationPolicyRuleDraft: vi.fn(),
  installAgentTracePolicyReviewRuleDraft: vi.fn(),
  queueComputerActivityReplayCase: vi.fn(),
  queueReplayEvidenceHint: vi.fn(),
  queueAgentTraceTaskRunReview: vi.fn(),
  queueAgentScorecardGaps: vi.fn(),
  queueBrowserDesktopRepairRecipes: vi.fn(),
  queueLatestBrowserSessionReplayCase: vi.fn(),
  queueRepairRoutePromotionCandidates: vi.fn(),
  rejectStaleBrowserDesktopReplayArtifacts: vi.fn(),
  takeoverTaskRun: vi.fn(),
}));

const pluginApi = vi.hoisted(() => ({
  fetchPluginSmokeSummary: vi.fn(),
}));

vi.mock("@/core/agent-trace/api", () => api);
vi.mock("@/core/plugins/api", () => pluginApi);

describe("<AgentOperatorPanel />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchAgentTraceTaskRuns.mockResolvedValue([
      {
        task_id: "turn-1",
        title: "Build report",
        status: "completed",
        tool_calls_started: 2,
        tool_errors: 0,
      },
    ]);
    api.fetchAgentTraceReviewQueue.mockImplementation(
      (
        _limit: number,
        _offset: number,
        filters?: { targetBucket?: string },
      ) => {
        if (filters?.targetBucket === "browser_desktop_replay") {
          return Promise.resolve([
            {
              id: "rq-browser-replay",
              source: "browser_session_replay",
              source_kind: "browser_desktop_replay",
              candidate_kind: "browser_session_replay_case",
              priority: "P1",
              target_bucket: "browser_desktop_replay",
              title: "Review browser replay case: workspace",
              text: "Browser session `workspace` replay case captured for operator review.",
              status: "pending",
              occurrences: 1,
              metadata: {
                schema: "octopus.browser_session_replay_case.v1",
                action_count: 2,
              },
            },
          ]);
        }
        if (filters?.targetBucket === "scorecard_gap_backlog") {
          return Promise.resolve([
            {
              id: "rq-scorecard-ecosystem",
              source: "agent_scorecard_gap",
              source_kind: "scorecard_gap",
              candidate_kind: "scorecard_gap:ecosystem_maturity",
              priority: "P0",
              target_bucket: "scorecard_gap_backlog",
              title: "Raise Ecosystem maturity",
              text: "Close ecosystem maturity gap.",
              status: "pending",
              occurrences: 2,
              tags: ["scorecard_gap", "real_baseline", "ecosystem_maturity"],
              metadata: {
                schema: "octopus.agent_scorecard_gap.v1",
                dimension_id: "ecosystem_maturity",
                remediation: {
                  schema: "octopus.scorecard_gap_remediation.v1",
                  dimension_id: "ecosystem_maturity",
                  status: "queued",
                  primary_action:
                    "Ship stable public docs for code mode, permissions, replay, and plugins.",
                },
              },
            },
          ]);
        }
        return Promise.resolve([
          {
            id: "rq-1",
            source: "task_run_review",
            source_kind: "learning_candidate",
            candidate_kind: "success_pattern",
            priority: "P1",
            target_bucket: "experience",
            title: "Useful workflow pattern",
            text: "Keep this workflow for future tasks.",
            status: "pending",
            occurrences: 2,
            source_task_ids: ["turn-1"],
          },
        ]);
      },
    );
    api.fetchAgentTraceReviewQueueSummary.mockResolvedValue({
      schema: "octopus.review_queue.v1",
      total: 4,
      pending_count: 2,
      by_status: { pending: 2, promoted: 1, rejected: 1 },
      by_priority: { P1: 1 },
      by_target_bucket: {
        experience: 1,
        browser_desktop_replay: 1,
        scorecard_gap_backlog: 1,
      },
      next_actions: [],
    });
    api.fetchTaskRecoveryQueue.mockResolvedValue({
      schema: "octopus.task_recovery_queue.v1",
      total: 2,
      count: 2,
      limit: 8,
      generated_at: "2026-06-26T00:00:00Z",
      filters: { include_monitor: false },
      items: [
        {
          task_id: "task-expired-loop",
          status: "running",
          kind: "loop",
          title: "Expired loop task",
          owner_id: "alice",
          thread_id: "thread-recovery-1",
          workspace_path: null,
          recommended_action: "takeover_and_resume",
          priority: 108,
          can_takeover: true,
          can_resume: true,
          has_checkpoint: true,
          latest_checkpoint_id: "checkpoint-expired-loop",
          resume_checkpoint_id: null,
          checkpoint_id: "checkpoint-expired-loop",
          operation: "takeover_then_resume",
          steps: ["takeover_task", "resume_from_checkpoint"],
          recovery_plan: {
            checkpoint_id: "checkpoint-expired-loop",
            operation: "takeover_then_resume",
            steps: ["takeover_task", "resume_from_checkpoint"],
          },
          lease_health: {
            state: "expired",
            holder_id: "worker-a",
            recommended_action: "takeover_and_resume",
            can_takeover: true,
            can_resume: true,
            recovery: {
              checkpoint_id: "checkpoint-expired-loop",
              operation: "takeover_then_resume",
              steps: ["takeover_task", "resume_from_checkpoint"],
            },
          },
          updated_at: "2026-06-26T00:00:00Z",
          created_at: "2026-06-25T00:00:00Z",
        },
        {
          task_id: "task-failed-loop",
          status: "failed",
          kind: "loop",
          title: "Failed loop task",
          owner_id: "alice",
          thread_id: null,
          workspace_path: null,
          recommended_action: "resume_from_checkpoint",
          priority: 90,
          can_takeover: false,
          can_resume: true,
          has_checkpoint: true,
          latest_checkpoint_id: "checkpoint-failed-loop",
          resume_checkpoint_id: "resume-failed-loop",
          checkpoint_id: "resume-failed-loop",
          operation: "resume_from_checkpoint",
          steps: ["resume_from_checkpoint"],
          recovery_plan: {
            checkpoint_id: "resume-failed-loop",
            operation: "resume_from_checkpoint",
            steps: ["resume_from_checkpoint"],
          },
          lease_health: {
            state: "terminal",
            recommended_action: "resume_from_checkpoint",
            can_takeover: false,
            can_resume: true,
            recovery: {
              checkpoint_id: "resume-failed-loop",
              operation: "resume_from_checkpoint",
              steps: ["resume_from_checkpoint"],
            },
          },
          updated_at: "2026-06-26T00:00:00Z",
          created_at: "2026-06-25T00:00:00Z",
        },
      ],
    });
    api.fetchAgentTraceReplayGate.mockResolvedValue({
      schema: "octopus.replay_gate.v1",
      passed: true,
      reason: "all_replay_evaluations_passed",
      thresholds: { min_cases: 1, min_score: 1 },
      summary: {
        total: 1,
        passed: 1,
        failed: 0,
        below_min_score: 0,
      },
      failing_cases: [],
    });
    api.fetchAgentTracePromotionAuditSummary.mockResolvedValue({
      schema: "octopus.promotion_audit_summary.v1",
      total: 2,
      by_status: { applied: 2 },
      by_target: { experience: 2 },
      by_event_type: { promotion_apply: 1, topology_policy_block: 2 },
      override_count: 1,
      gate_failed_count: 1,
      gate_blocked_override_count: 1,
      topology_policy_block_count: 2,
      latest: [],
    });
    api.fetchAgentTraceExperienceQualitySummary.mockResolvedValue({
      schema: "octopus.experience_memory_quality_summary.v1",
      total: 3,
      active_count: 2,
      contradicted_count: 1,
      stale_count: 1,
      low_reliability_count: 1,
      avg_reliability: 0.82,
      by_bucket: { experience: 2, experiment_backlog: 1 },
      top_risks: [],
      next_actions: ["Refresh stale memories with replay-backed evidence."],
    });
    api.fetchSubagentFitness.mockResolvedValue({
      schema: "octopus.subagent_fitness.v1",
      role: null,
      roles: [
        {
          role: "virtual-research-competitor-analyst",
          score: 0.12,
          confidence: 0.6,
          sample_count: 3,
          by_status: { rejected: 3 },
          promoted_count: 0,
          rejected_count: 3,
          pending_count: 0,
          routing_evidence_count: 3,
          by_evidence_source: { deep_research_route_decision: 3 },
          verdict: "retire_candidate",
          recommendation:
            "Review or retire the virtual-research-competitor-analyst subagent before assigning more critical work.",
          evidence_item_ids: ["route-research-1"],
        },
      ],
      role_count: 1,
      top_risks: [
        {
          role: "virtual-research-competitor-analyst",
          score: 0.12,
          confidence: 0.6,
          sample_count: 3,
          by_status: { rejected: 3 },
          promoted_count: 0,
          rejected_count: 3,
          pending_count: 0,
          routing_evidence_count: 3,
          by_evidence_source: { deep_research_route_decision: 3 },
          verdict: "retire_candidate",
          recommendation:
            "Review or retire the virtual-research-competitor-analyst subagent before assigning more critical work.",
          evidence_item_ids: ["route-research-1"],
        },
      ],
      next_actions: [
        {
          role: "virtual-research-competitor-analyst",
          verdict: "retire_candidate",
          action:
            "Review or retire the virtual-research-competitor-analyst subagent before assigning more critical work.",
        },
      ],
    });
    api.fetchOrganizationTopologies.mockResolvedValue([
      {
        name: "research_swarm_v1",
        protocol: "sequential",
        task_bucket: "research-report",
        fingerprint: "topo-1",
        agents: {
          researcher: { agent_id: "virtual-research-competitor-analyst" },
        },
        subagent_policy: {
          status: "blocked",
          blocked: true,
          retired: [
            {
              role: "researcher",
              agent_id: "virtual-research-competitor-analyst",
              status: "retired",
              reason: "operator retired",
              actor: "operator-test",
              updated_at: "2026-06-19T00:00:00Z",
              evidence_item_ids: ["route-research-1"],
            },
          ],
          watch: [],
          retired_count: 1,
          watch_count: 0,
          policy_count: 1,
          lastUpdated: "2026-06-19T00:00:00Z",
        },
      },
    ]);
    api.fetchOrganizationTopologyProposals.mockResolvedValue({
      schema: "octopus.topology_proposals.merged.v1",
      count: 1,
      persisted_count: 0,
      subagent_promotion_count: 1,
      proposals: [
        {
          kind: "swap_agent",
          base_topology: "topo-1",
          bucket: "research-report",
          detail: {
            role: "researcher",
            new_agent: "researcher",
            source: "subagent_fitness",
            historical_lift: {
              matched_promotions: 1,
              improved_count: 1,
              regressed_count: 0,
              avg_success_rate_delta: 0.3,
              avg_quality_score_delta: 0.2,
              rank_adjustment: 0.12,
            },
          },
          confidence: 0.82,
          rank_score: 0.94,
          rationale: "subagent researcher is strong",
        },
      ],
    });
    api.fetchOrganizationTopologyLift.mockResolvedValue({
      schema: "octopus.topology_promotion_lift.v1",
      count: 1,
      reports: [
        {
          topology: "research_swarm_v1+swap",
          fingerprint: "topo-2",
          base_fingerprint: "topo-1",
          bucket: "research-report",
          mutation: "swap_agent",
          promotion_source: "subagent_fitness",
          before: { success_rate: 0.5 },
          after: { success_rate: 0.8 },
          lift: { success_rate_delta: 0.3 },
          verdict: "improved",
        },
      ],
    });
    api.fetchAutoVerifierMetrics.mockResolvedValue({
      schema: "octopus.auto_verifier_metrics.v1",
      total: 2,
      pass_count: 1,
      fail_count: 1,
      pass_rate: 0.5,
      avg_duration_ms: 120,
      families: [
        {
          family: "ruff",
          total: 2,
          pass_count: 1,
          fail_count: 1,
          pass_rate: 0.5,
          avg_duration_ms: 120,
          latest_ts: "2026-06-19T00:00:00Z",
          commands: [
            {
              command: "python -m ruff check src/foo.py",
              count: 2,
            },
          ],
        },
      ],
      alerts: [
        {
          family: "ruff",
          severity: "critical",
          total: 3,
          fail_count: 2,
          pass_rate: 0.333,
          latest_ts: "2026-06-19T00:00:00Z",
          top_command: "python -m ruff check src/foo.py",
          message: "ruff verifier family is drifting: 2/3 recent runs failed",
        },
      ],
      top_failures: [],
      recent_decisions: [
        {
          schema: "octopus.auto_verifier_decision.v1",
          ts: "2026-06-19T00:00:00Z",
          selected_command: "python -m ruff check src/foo.py",
          candidates: [
            {
              rank: 1,
              command: "python -m ruff check src/foo.py",
              kind: "lint",
              priority: 1,
              family: "ruff",
              history_count: 2,
              pass_rate: 0.75,
              avg_duration_ms: 120,
              reason:
                "priority=1; ruff history count=2, smoothed pass_rate=0.750, avg_duration_ms=120.0",
              original_index: 0,
            },
          ],
        },
      ],
    });
    api.fetchBrowserDesktopQuality.mockResolvedValue({
      schema: "octopus.browser_desktop_quality.v1",
      score: 1,
      passed: 5,
      total: 5,
      ready: true,
      checks: [],
      replay_trends: {
        schema: "octopus.browser_desktop_replay_trends.v1",
        total: 36,
        pending_count: 2,
        reviewed_count: 34,
        promoted_count: 2,
        rejected_count: 32,
        review_rate: 0.944,
        stale_source_artifact_count: 1,
        by_status: { pending: 2, promoted: 2, rejected: 32 },
        by_candidate_kind: {
          browser_pixel_replay_gate_case: 32,
          browser_session_replay_case: 2,
          computer_activity_replay_case: 2,
        },
        latest: [],
        next_actions: [
          "Regenerate or reject 1 stale browser/desktop replay artifact(s).",
        ],
      },
      next_actions: [],
    });
    api.fetchAutomationRadar.mockResolvedValue({
      schema: "octopus.automation_radar.v1",
      target_score: 95,
      scope: "browser_desktop_visual_automation",
      competitors: ["codex", "claude_code", "cursor", "octopus"],
      overall: {
        codex: 93,
        claude_code: 85,
        cursor: 80,
        octopus: 95,
      },
      ranking: [
        { competitor: "octopus", score: 95 },
        { competitor: "codex", score: 93 },
      ],
      verdict: "leading",
      dimensions: [],
      octopus_gaps: [
        {
          id: "operator_visibility",
          title: "Operator visibility",
          weight: 10,
          why: "Expose automation health.",
          scores: { codex: 93, claude_code: 86, cursor: 83, octopus: 93 },
          leader: "codex",
          octopus_gap_to_target: 2,
          octopus_gap_to_codex: 0,
          evidence_ready: true,
          evidence_checks: [],
          missing_check_ids: [],
          next_actions: [
            "Make every browser and desktop replay case reachable from the operator scorecard.",
          ],
        },
      ],
      octopus_strengths: [],
      browser_desktop_quality: {
        schema: "octopus.browser_desktop_quality.v1",
        score: 1,
        passed: 5,
        total: 5,
        ready: true,
      },
      parity_certification: {
        schema: "octopus.parity_certification.v1",
        passed: 14,
        total: 14,
        ready: true,
      },
      policy_rule_drafts: {
        schema: "octopus.automation_policy_rule_drafts.v1",
        total: 7,
        verified: 7,
        ready: true,
      },
      next_focus: [],
    });
    api.fetchAutomationPolicyRuleDrafts.mockResolvedValue({
      schema: "octopus.automation_policy_rule_drafts.v1",
      total: 7,
      verified: 7,
      drafts: [
        {
          schema: "octopus.policy_review_rule_draft.v1",
          draft_id: "auto-prd-1",
          signed_payload: {
            schema: "octopus.automation_policy_review_rule_draft.v1",
            proposal_id: "automation:desktop_execute",
            proposal_kind: "automation_policy_review",
            review_queue_item_id: null,
            automation: {
              id: "desktop_execute",
              surface: "desktop",
              tool: "computer_execute_token",
            },
            rule: {
              effect: "deny",
              tool: "computer_execute_token",
              args_contains: "",
              reason:
                "Desktop execute tokens can move the mouse and type on the host.",
            },
            evidence: {},
            review_required: true,
          },
          signature: {
            schema: "octopus.policy_review_rule_signature.v1",
            algorithm: "sha256:canonical-json",
            digest: "auto1234567890",
          },
        },
      ],
    });
    api.fetchBrowserDesktopRepairRecipes.mockResolvedValue({
      schema: "octopus.browser_desktop_repair_recipes.v1",
      total_pending_cases: 1,
      recipe_count: 1,
      ready: false,
      next_actions: [
        "Queue 1 deterministic browser/desktop repair recipe(s) for operator review.",
      ],
      recipes: [
        {
          schema: "octopus.browser_desktop_repair_recipe.v1",
          recipe_id: "browser-desktop-recipe:abc",
          cluster_key: "browser_session|failed|navigate|page_crashed",
          candidate_kind: "browser_session_replay_case",
          title: "Stabilize browser session replay: navigate",
          priority: "P0",
          occurrences: 2,
          source_item_ids: ["rq-browser-replay"],
          case_ids: ["browser-session:workspace"],
          fingerprints: ["abcdef0123456789"],
          evidence_summary: {},
          recommended_steps: [
            "Re-run the browser session replay through `navigate`.",
          ],
          verification_plan: {},
          promotion_gate: {},
        },
      ],
    });
    api.fetchBrowserDesktopRepairRecipeVerifications.mockResolvedValue({
      schema: "octopus.browser_desktop_repair_recipe_verifications.v1",
      total: 1,
      verified_count: 0,
      blocked_count: 1,
      ready: false,
      verifications: [
        {
          schema: "octopus.browser_desktop_repair_recipe_verification.v1",
          item_id: "rq-recipe",
          recipe_id: "browser-desktop-recipe:abc",
          title: "Stabilize browser session replay: navigate",
          priority: "P0",
          status: "needs_rerun_evidence",
          blockers: ["missing_verification_evidence"],
          source_status_counts: { pending: 1 },
          missing_evidence: ["browser_session_replay_case"],
          verification_evidence: {},
        },
      ],
      next_actions: [
        "Attach rerun evidence for 1 browser/desktop repair recipe(s).",
      ],
    });
    api.fetchRepairRouteQuality.mockResolvedValue({
      schema: "octopus.repair_route_quality.v1",
      score: 0.62,
      ready: false,
      quality_gate: {
        schema: "octopus.repair_route_quality_gate.v1",
        score: 0.62,
        ready: false,
        blockers: ["failed_verifications", "p0_promotion_candidates"],
        signals: {
          total_failures: 2,
          failed_verification_rate: 1,
          promotion_candidate_count: 1,
        },
      },
      total_failures: 2,
      route_count: 1,
      routes: [],
      promotion_candidates: [
        {
          schema: "octopus.repair_route_promotion_candidate.v1",
          route: "test_driven_repair",
          priority: "P0",
          status: "needs_operator_review",
          evidence: {
            count: 2,
            share: 1,
            failed_verification_count: 2,
            unverified_code_changes: 0,
            recommended_commands: [
              {
                command: "python -m pytest tests/test_checkout.py -q",
                count: 2,
              },
            ],
            example_proposal_ids: ["proposal-1", "proposal-2"],
          },
          promotion_gate: {
            schema: "octopus.repair_route_promotion_gate.v1",
            requires_operator_review: true,
            requires_passing_rerun: true,
            blocks_auto_promotion: true,
          },
        },
      ],
      summary: {},
      recommendations: ["Prioritize repair-route `test_driven_repair`."],
    });
    api.fetchAgentTraceTrustDenialSummary.mockResolvedValue({
      schema: "octopus.trust_denial_summary.v1",
      total: 2,
      by_tool: { exec_shell: 2 },
      by_action: { deny: 2 },
      recent: [
        {
          id: 1,
          ts: "2026-06-19T00:00:00Z",
          thread_id: "thread-1",
          turn_id: "turn-deny",
          task_id: "task-1",
          agent_id: "agent-a",
          tool_name: "exec_shell",
          decision: "rejected",
          action: "deny",
          reason: "no destructive shell",
          risk_level: "critical",
        },
      ],
    });
    api.fetchAgentTracePolicyReviewRuleDrafts.mockResolvedValue({
      schema: "octopus.policy_review_rule_drafts.v1",
      total: 1,
      verified: 1,
      drafts: [
        {
          schema: "octopus.policy_review_rule_draft.v1",
          draft_id: "prd-1",
          signed_payload: {
            schema: "octopus.policy_review_rule_draft.v1",
            proposal_id: "proposal-1",
            proposal_kind: "review_queue_policy_review",
            review_queue_item_id: "rq-policy",
            rule: {
              effect: "deny",
              tool: "exec_shell",
              args_contains: "",
              reason: "no destructive shell",
            },
            evidence: { replay_gate: { passed: true } },
            review_required: true,
          },
          signature: {
            schema: "octopus.policy_review_rule_signature.v1",
            algorithm: "sha256:canonical-json",
            digest: "abc1234567890",
          },
        },
      ],
    });
    api.fetchAgentCompetitorScorecard.mockResolvedValue({
      schema: "octopus.agent_competitor_scorecard.v1",
      target_score: 90,
      competitors: ["codex", "claude_code", "cursor", "octopus"],
      overall: {
        codex: 93,
        claude_code: 91,
        cursor: 86,
        octopus: 91,
      },
      ranking: [
        { competitor: "codex", score: 93 },
        { competitor: "octopus", score: 91 },
        { competitor: "claude_code", score: 91 },
        { competitor: "cursor", score: 86 },
      ],
      verdict: "competitive",
      evidence_adjusted_overall: {
        codex: 93,
        claude_code: 91,
        cursor: 86,
        octopus: 91,
      },
      evidence_adjusted_ranking: [
        { competitor: "codex", score: 93 },
        { competitor: "octopus", score: 91 },
        { competitor: "claude_code", score: 91 },
        { competitor: "cursor", score: 86 },
      ],
      evidence_adjusted_verdict: "competitive",
      scorecard_policy: {
        schema: "octopus.agent_scorecard_policy.v1",
        overall: "external_calibrated_baseline",
        evidence_adjusted_overall: "internal_certification_floor",
        certification_floors_do_not_change_overall: true,
      },
      dimensions: [],
      octopus_below_target: [
        {
          id: "ecosystem_maturity",
          title: "Ecosystem maturity",
          weight: 5,
          why: "Documentation, enterprise polish, integrations, and broad user trust.",
          scores: { codex: 95, claude_code: 90, cursor: 88, octopus: 88 },
          evidence_adjusted_scores: {
            codex: 95,
            claude_code: 90,
            cursor: 88,
            octopus: 94,
          },
          leader: "codex",
          octopus_gap_to_target: 2,
          octopus_baseline_score: 88,
          octopus_evidence_adjusted_score: 94,
          octopus_certified_score_floor: 94,
          octopus_evidence_readiness: 1,
          octopus_evidence: [],
          octopus_evidence_checklist: [
            {
              id: "operator_readiness_docs",
              title: "Operator readiness documentation",
              score: 1,
              status: "strong",
              implementation: {
                present: 2,
                total: 2,
                missing_count: 0,
                missing: [],
                coverage: 1,
              },
              tests: {
                present: 1,
                total: 1,
                missing_count: 0,
                missing: [],
                coverage: 1,
              },
              next_actions: [
                "Ship stable public docs for code mode, permissions, replay, and plugins.",
              ],
            },
          ],
          operator_drilldown: {
            schema: "octopus.scorecard_operator_drilldown.v1",
            dimension_id: "ecosystem_maturity",
            certified_floor: 94,
            links: [
              {
                id: "plugin_permission_rule_drafts",
                label: "Plugin permission rule drafts",
                method: "GET",
                href: "/api/plugins/permission-rule-drafts",
              },
              {
                id: "team_task_timeline",
                label: "Team task timeline",
                method: "GET",
                href: "/api/team-tasks/{task_id}/process-timeline",
              },
            ],
            source_refs: [
              {
                kind: "review_queue",
                target_bucket: "scorecard_gap_backlog",
              },
            ],
          },
          octopus_next_actions: [
            "Ship stable public docs for code mode, permissions, replay, and plugins.",
          ],
        },
      ],
      octopus_strengths: [
        {
          id: "governance_operator",
          title: "Governance operator loop",
          weight: 5,
          why: "Governance loop",
          scores: { codex: 92, claude_code: 88, cursor: 78, octopus: 94 },
          leader: "octopus",
          octopus_gap_to_target: 0,
          octopus_evidence_readiness: 1,
          octopus_evidence: [],
          octopus_next_actions: [],
        },
      ],
      next_focus: [],
      ecosystem_readiness: {
        schema: "octopus.ecosystem_readiness.v1",
        score: 1,
        passed: 4,
        total: 4,
        missing_count: 0,
        topics: [],
        next_actions: [],
      },
      parity_certification: {
        schema: "octopus.parity_certification.v1",
        passed: 14,
        total: 14,
        ready: true,
        by_kind: {
          parity: { passed: 6, total: 6 },
          operational_excellence: { passed: 4, total: 4 },
          advantage: { passed: 4, total: 4 },
        },
        requirements: [],
        dimension_score_floors: {
          product_experience: 97,
          browser_desktop: 97,
          ecosystem_maturity: 94,
          differentiated_agent_os: 97,
        },
        dimension_evidence: {},
        next_actions: [],
      },
      codex_gap: {
        schema: "octopus.codex_gap_report.v1",
        combined_score: 1,
        verdict: "differentiated",
        next_focus: [],
      },
    });
    pluginApi.fetchPluginSmokeSummary.mockResolvedValue({
      schema: "octopus.codex_plugin_smoke_summary.v1",
      total: 2,
      ok_count: 1,
      failed_count: 1,
      review_required_count: 1,
      warning_count: 1,
      failed: [
        {
          plugin_id: "empty",
          plugin_name: "Empty",
          issues: ["plugin exposes no capabilities"],
        },
      ],
      review_required: [
        {
          plugin_id: "research",
          plugin_name: "Research",
          reason: "local plugin manifest smoke check",
        },
      ],
      warnings: [
        {
          plugin_id: "research",
          plugin_name: "Research",
          warnings: [
            "MCP-capable plugin has no explicit permissions declaration",
          ],
        },
      ],
      compatibility: {
        schema: "octopus.codex_plugin_compatibility.v1",
        verdict: "fail",
        passed: 3,
        total: 4,
        surface_totals: {
          capabilities: 1,
          skills: 1,
          apps: 0,
          mcp: 1,
          commands: 0,
        },
        requirements: [
          {
            id: "no_smoke_failures",
            passed: false,
            detail: "1 plugin smoke failure(s)",
          },
        ],
        next_actions: ["Fix plugins with failed local smoke checks."],
      },
    });
    api.fetchAgentTraceProcessTimeline.mockResolvedValue({
      schema: "octopus.process_timeline.v1",
      task_id: "turn-1",
      overview: {
        status: "completed",
        score: 0.92,
        approval_count: 1,
        experience_record_count: 2,
      },
      timeline: [
        {
          lane: "execution",
          kind: "task_start",
          title: "Task started",
          text: "Build report",
        },
      ],
    });
    api.decideAgentTraceReviewQueueItem.mockResolvedValue({
      id: "rq-1",
      status: "promoted",
    });
    api.decideSubagentPolicy.mockResolvedValue({
      schema: "octopus.subagent_policy.v1",
      role: "virtual-research-competitor-analyst",
      action: "retire",
      policy: { status: "retired" },
      summary: {
        schema: "octopus.subagent_policy.v1",
        policies: {},
        policy_count: 1,
        retired_count: 1,
        watch_count: 0,
        lastUpdated: "2026-06-19T00:00:00Z",
      },
    });
    api.applyAgentTraceReviewQueuePromotions.mockResolvedValue({
      schema: "octopus.promotion_applier.v1",
      dry_run: false,
      applied: 1,
      failed: 0,
      skipped: 0,
      results: [],
      replay_gate: {
        schema: "octopus.replay_gate.v1",
        passed: true,
        reason: "all_replay_evaluations_passed",
        thresholds: { min_cases: 1, min_score: 1 },
        summary: {
          total: 1,
          passed: 1,
          failed: 0,
          below_min_score: 0,
        },
        failing_cases: [],
      },
      override_replay_gate: false,
    });
    api.installAgentTracePolicyReviewRuleDraft.mockResolvedValue({
      schema: "octopus.policy_review_rule_install.v1",
      installed: true,
      draft_id: "prd-1",
      rule: {
        effect: "deny",
        tool: "exec_shell",
        args_contains: "",
        reason: "no destructive shell",
      },
      policy_rule_count: 3,
    });
    api.installAutomationPolicyRuleDraft.mockResolvedValue({
      schema: "octopus.policy_review_rule_install.v1",
      installed: true,
      draft_id: "auto-prd-1",
      source_kind: "automation_policy_review",
      rule: {
        effect: "deny",
        tool: "computer_execute_token",
        args_contains: "",
        reason:
          "Desktop execute tokens can move the mouse and type on the host.",
      },
      policy_rule_count: 4,
    });
    api.queueAgentTraceTaskRunReview.mockResolvedValue({
      created: 0,
      updated: 1,
      total: 3,
      items: [],
    });
    api.queueLatestBrowserSessionReplayCase.mockResolvedValue({
      ok: true,
      schema: "octopus.browser_session_replay_case_queue.v1",
      queue: {
        created: 1,
        updated: 0,
        total: 4,
        items: [],
      },
    });
    api.queueRepairRoutePromotionCandidates.mockResolvedValue({
      schema: "octopus.repair_route_promotion_queue.v1",
      created: 1,
      updated: 0,
      candidates: [],
      items: [],
    });
    api.queueBrowserDesktopRepairRecipes.mockResolvedValue({
      schema: "octopus.browser_desktop_repair_recipe_queue.v1",
      created: 1,
      updated: 0,
      recipes: [],
      items: [],
    });
    api.rejectStaleBrowserDesktopReplayArtifacts.mockResolvedValue({
      schema: "octopus.browser_desktop_stale_replay_artifact_rejection.v1",
      inspected: 3,
      rejected_count: 1,
      archived_recipe_count: 2,
      skipped_count: 0,
      rejected: [],
      archived_recipes: [],
    });
    api.queueComputerActivityReplayCase.mockResolvedValue({
      ok: true,
      schema: "octopus.computer_activity_replay_case_queue.v1",
      queue: {
        created: 0,
        updated: 1,
        total: 4,
        items: [],
      },
    });
    api.queueReplayEvidenceHint.mockResolvedValue({
      ok: true,
      schema: "octopus.computer_activity_replay_case_queue.v1",
      queue: {
        created: 1,
        updated: 0,
        total: 5,
        items: [],
      },
    });
    api.queueAgentScorecardGaps.mockResolvedValue({
      ok: true,
      schema: "octopus.agent_scorecard_gap_queue.v1",
      created: 7,
      updated: 0,
      total: 7,
      items: [],
      scorecard: {
        overall: { octopus: 91 },
        verdict: "competitive",
        evidence_adjusted_overall: { octopus: 91 },
        below_target_count: 1,
      },
    });
    api.takeoverTaskRun.mockResolvedValue({
      schema: "octopus.task_run_takeover.v1",
      task_run: { task_id: "task-expired-loop", status: "running" },
      lease_health: { state: "ok", recommended_action: "monitor" },
    });
  });

  it("renders task runs, timeline and pending review queue", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    expect(
      await screen.findByText("Agent evolution queue"),
    ).toBeInTheDocument();
    expect((await screen.findAllByText("Build report")).length).toBeGreaterThan(
      0,
    );
    expect(
      await screen.findByText("Useful workflow pattern"),
    ).toBeInTheDocument();
    expect(await screen.findByText("score 0.92")).toBeInTheDocument();
    expect(await screen.findByText("Replay gate")).toBeInTheDocument();
    expect(
      await screen.findByText("all_replay_evaluations_passed"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Task recovery queue")).toBeInTheDocument();
    expect(await screen.findByText("Expired loop task")).toBeInTheDocument();
    expect(await screen.findByText("take over + resume")).toBeInTheDocument();
    expect(
      await screen.findByText("takeover_task -> resume_from_checkpoint"),
    ).toBeInTheDocument();
    expect(await screen.findByText("resume checkpoint")).toBeInTheDocument();
    expect(
      await screen.findByText("resume_from_checkpoint"),
    ).toBeInTheDocument();
    expect(await screen.findByText("lease expired")).toBeInTheDocument();
    expect(await screen.findByText("Competitor scorecard")).toBeInTheDocument();
    expect(
      await screen.findByText("Browser/Desktop replay review"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Review browser replay case: workspace"),
    ).toBeInTheDocument();
    expect(await screen.findByText("browser 2")).toBeInTheDocument();
    expect(await screen.findByText("1 recipes")).toBeInTheDocument();
    expect(await screen.findByText("0/1 verified")).toBeInTheDocument();
    expect(await screen.findByText("review rate")).toBeInTheDocument();
    expect((await screen.findAllByText("94%")).length).toBeGreaterThan(0);
    expect(await screen.findByText(/stale artifacts 1/)).toBeInTheDocument();
    expect(
      await screen.findByText(
        /Top recipe: Stabilize browser session replay: navigate/,
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/1 recipe\(s\) need rerun evidence/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Ecosystem maturity is 2 point(s) under target"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Evidence")).toBeInTheDocument();
    const ecosystemGapButton = await screen.findByRole("button", {
      name: "Ecosystem maturity 88",
    });
    expect(ecosystemGapButton).toHaveAttribute(
      "aria-controls",
      "scorecard-gap-drilldown",
    );
    expect(ecosystemGapButton).toHaveAttribute("aria-pressed", "true");
    expect(
      await screen.findByRole("region", {
        name: "Scorecard gap drill-down for Ecosystem maturity",
      }),
    ).toBeInTheDocument();
    expect(await screen.findByText("real 88")).toBeInTheDocument();
    expect(await screen.findByText("evidence 94")).toBeInTheDocument();
    expect(await screen.findByText("gap 2")).toBeInTheDocument();
    expect(await screen.findByText("queued P0")).toBeInTheDocument();
    expect(
      await screen.findByText("rq-scorecard-ecosystem · pending · x2"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("target scorecard_gap_backlog · audit 2"),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: "Apply gap" }),
    ).toBeDisabled();
    expect(
      await screen.findAllByText(
        "Ship stable public docs for code mode, permissions, replay, and plugins.",
      ),
    ).toHaveLength(2);
    api.queueAgentScorecardGaps.mockResolvedValueOnce({
      ok: true,
      schema: "octopus.agent_scorecard_gap_queue.v1",
      created: 1,
      updated: 0,
      total: 1,
      items: [],
    });
    fireEvent.click(
      await screen.findByRole("button", { name: /Refresh queue item/ }),
    );
    await waitFor(() => {
      expect(api.queueAgentScorecardGaps).toHaveBeenCalledWith({
        targetScore: 90,
        limit: 1,
        dimensionId: "ecosystem_maturity",
        reason: "operator scorecard drill-down remediation",
      });
    });
    expect(await screen.findByText("#1 Codex 93")).toBeInTheDocument();
    expect(await screen.findByText("Promotion audit")).toBeInTheDocument();
    expect(await screen.findByText("Memory quality")).toBeInTheDocument();
    expect(await screen.findByText("82% reliable")).toBeInTheDocument();
    expect(
      await screen.findByText(
        "Refresh stale memories with replay-backed evidence.",
      ),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Operator policy blocked team topology attempts"),
    ).toBeInTheDocument();
    expect(await screen.findByText("topo")).toBeInTheDocument();
    expect(await screen.findByText("Subagent risk")).toBeInTheDocument();
    expect(
      await screen.findByText("virtual-research-competitor-analyst"),
    ).toBeInTheDocument();
    expect(await screen.findByText("3 route evidence")).toBeInTheDocument();
    expect(await screen.findByText("3 deep research")).toBeInTheDocument();
    expect(await screen.findByText("Team promotion")).toBeInTheDocument();
    expect(
      await screen.findByText("subagent researcher is strong"),
    ).toBeInTheDocument();
    expect(await screen.findByText("lift +1/-0")).toBeInTheDocument();
    expect(await screen.findByText("sub")).toBeInTheDocument();
    expect(await screen.findByText("up")).toBeInTheDocument();
    expect(await screen.findByText("Auto verifier")).toBeInTheDocument();
    expect(
      await screen.findByText(/python -m ruff check src\/foo\.py/),
    ).toBeInTheDocument();
    expect(await screen.findByText("ruff drift 33%")).toBeInTheDocument();
    expect(await screen.findByText("75% history")).toBeInTheDocument();
    expect(await screen.findByText("routes 62%")).toBeInTheDocument();
    expect(
      await screen.findAllByText((_content, element) =>
        Boolean(
          element?.textContent?.includes(
            "1 repair-route promotion candidate(s)",
          ),
        ),
      ),
    ).not.toHaveLength(0);
    expect(
      await screen.findByText(/top test_driven_repair/),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(/blocked by failed verifications/),
    ).toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: "Queue routes" }),
    );
    await waitFor(() => {
      expect(api.queueRepairRoutePromotionCandidates).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(
        "Queued 1 repair-route promotion review item(s).",
      ),
    ).toBeInTheDocument();
    expect(await screen.findByText("Plugin health")).toBeInTheDocument();
    expect(await screen.findByText("1/2 ok")).toBeInTheDocument();
    expect(await screen.findByText("compat fail")).toBeInTheDocument();
    expect(
      await screen.findByText("Fix plugins with failed local smoke checks."),
    ).toBeInTheDocument();
    expect(await screen.findByText("Empty")).toBeInTheDocument();
    expect(await screen.findByText("Tool safety")).toBeInTheDocument();
    expect(await screen.findByText("2 denied")).toBeInTheDocument();
    expect(
      (await screen.findAllByText("no destructive shell")).length,
    ).toBeGreaterThan(0);
    expect(await screen.findByText("Policy review rules")).toBeInTheDocument();
    expect(await screen.findByText("1/1 signed")).toBeInTheDocument();
    expect(await screen.findByText("deny exec_shell")).toBeInTheDocument();
    expect(await screen.findByText("Topology policy")).toBeInTheDocument();
    expect(await screen.findByText("research_swarm_v1")).toBeInTheDocument();
    expect(
      await screen.findByText("researcher:virtual-research-competitor-analyst"),
    ).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Promoted")).toBeInTheDocument();
  });

  it("takes over an expired task from the recovery queue", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const takeoverButton = await screen.findByRole("button", {
      name: /take over/i,
    });
    fireEvent.click(takeoverButton);

    await waitFor(() =>
      expect(api.takeoverTaskRun).toHaveBeenCalledWith("task-expired-loop"),
    );
    expect(
      await screen.findByText("Took over task task-expired-loop."),
    ).toBeInTheDocument();
    expect(api.fetchTaskRecoveryQueue).toHaveBeenCalledTimes(2);
  });

  it("promotes a pending review item", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const promote = await screen.findByRole("button", { name: "Promote" });
    fireEvent.click(promote);

    await waitFor(() => {
      expect(api.decideAgentTraceReviewQueueItem).toHaveBeenCalledWith("rq-1", {
        action: "promoted",
        promotedTo: "experience",
        reason: "Accepted from operator panel.",
      });
    });
  });

  it("queues the selected task run review", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const button = await screen.findByRole("button", { name: /Queue review/ });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.queueAgentTraceTaskRunReview).toHaveBeenCalledWith("turn-1");
    });
  });

  it("queues browser and desktop replay evidence from the operator panel", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue browser/ }),
    );
    await waitFor(() => {
      expect(api.queueLatestBrowserSessionReplayCase).toHaveBeenCalled();
    });
    expect(
      await screen.findByText("Queued 1 browser replay review item(s)."),
    ).toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue desktop/ }),
    );
    await waitFor(() => {
      expect(api.queueComputerActivityReplayCase).toHaveBeenCalled();
    });
    expect(
      await screen.findByText("Queued 1 desktop replay review item(s)."),
    ).toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue recipes/ }),
    );
    await waitFor(() => {
      expect(api.queueBrowserDesktopRepairRecipes).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(
        "Queued 1 browser/desktop repair recipe item(s).",
      ),
    ).toBeInTheDocument();

    fireEvent.click(await screen.findByRole("button", { name: /Clear stale/ }));
    await waitFor(() => {
      expect(api.rejectStaleBrowserDesktopReplayArtifacts).toHaveBeenCalled();
    });
    expect(
      await screen.findByText(
        "Rejected 1 stale replay item(s); archived 2 repair recipe item(s).",
      ),
    ).toBeInTheDocument();
  });

  it("shows replay evidence drill-downs from operator error states", async () => {
    api.queueComputerActivityReplayCase.mockRejectedValueOnce(
      new api.AgentTraceRequestError(404, {
        error: "preview token not found or expired",
        replay_evidence: {
          schema: "octopus.computer_replay_evidence_hint.v1",
          case_id: "computer-activity:abc123",
          fingerprint: "abc123",
          replay_ready: true,
          replay_case_url: "/api/computer/activity/replay-case",
          queue_url: "/api/computer/activity/replay-case/queue",
          queue_body: { limit: 100 },
        },
      }),
    );
    renderWithProviders(<AgentOperatorPanel />);

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue desktop/ }),
    );

    expect(
      await screen.findByText("preview token not found or expired"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Replay evidence available"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("computer-activity:abc123"),
    ).toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue evidence/ }),
    );

    await waitFor(() => {
      expect(api.queueReplayEvidenceHint).toHaveBeenCalledWith({
        schema: "octopus.computer_replay_evidence_hint.v1",
        case_id: "computer-activity:abc123",
        fingerprint: "abc123",
        replay_ready: true,
        replay_case_url: "/api/computer/activity/replay-case",
        queue_url: "/api/computer/activity/replay-case/queue",
        queue_body: { limit: 100 },
      });
    });
    expect(
      await screen.findByText("Queued 1 replay evidence item(s)."),
    ).toBeInTheDocument();
  });

  it("queues real scorecard gaps from the operator panel", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    expect(
      await screen.findByText("Plugin permission rule drafts"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("/api/plugins/permission-rule-drafts"),
    ).toBeInTheDocument();

    fireEvent.click(
      await screen.findByRole("button", { name: /Queue real gaps/ }),
    );

    await waitFor(() => {
      expect(api.queueAgentScorecardGaps).toHaveBeenCalledWith({
        targetScore: 90,
        limit: 10,
      });
    });
    expect(
      await screen.findByText("Queued 7 real scorecard gap review item(s)."),
    ).toBeInTheDocument();
  });

  it("queues repeated tool denials for policy review", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const button = await screen.findByRole("button", {
      name: /Queue policy review/,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.fetchAgentTraceTrustDenialSummary).toHaveBeenCalledWith(1000, {
        queueRepeated: true,
        minOccurrences: 2,
      });
    });
  });

  it("installs a signed policy-review rule draft", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const button = await screen.findByRole("button", {
      name: /Install signed rule/,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.installAgentTracePolicyReviewRuleDraft).toHaveBeenCalledWith(
        "prd-1",
      );
    });
    expect(
      await screen.findByText(
        "Installed deny rule for exec_shell · 3 policy rules",
      ),
    ).toBeInTheDocument();
  });

  it("shows automation radar and installs a signed automation deny rule", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    expect(await screen.findByText("Automation radar")).toBeInTheDocument();
    expect(await screen.findByText("policy drafts 7/7")).toBeInTheDocument();
    expect(
      await screen.findByText("computer_execute_token"),
    ).toBeInTheDocument();

    const button = await screen.findByRole("button", {
      name: /Install deny rule/,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.installAutomationPolicyRuleDraft).toHaveBeenCalledWith(
        "auto-prd-1",
      );
    });
    expect(
      await screen.findByText(
        "Installed deny automation rule for computer_execute_token · 4 policy rules",
      ),
    ).toBeInTheDocument();
  });

  it("applies promoted review queue items", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const button = await screen.findByRole("button", {
      name: /Apply promoted/,
    });
    fireEvent.click(button);

    await waitFor(() => {
      expect(api.applyAgentTraceReviewQueuePromotions).toHaveBeenCalledWith({
        limit: 50,
      });
    });
    expect(
      await screen.findByText("Applied 1, skipped 0, failed 0 · gate passed"),
    ).toBeInTheDocument();
  });

  it("opens an override confirmation when replay gate blocks apply", async () => {
    api.applyAgentTraceReviewQueuePromotions
      .mockRejectedValueOnce(
        new api.AgentTraceRequestError(409, {
          message: "replay gate did not pass",
          replay_gate: {
            schema: "octopus.replay_gate.v1",
            passed: false,
            reason: "insufficient_cases:1<2",
            thresholds: { min_cases: 2, min_score: 1 },
            summary: {
              total: 1,
              passed: 1,
              failed: 0,
              below_min_score: 0,
            },
            failing_cases: [],
          },
        }),
      )
      .mockResolvedValueOnce({
        schema: "octopus.promotion_applier.v1",
        dry_run: false,
        applied: 1,
        failed: 0,
        skipped: 0,
        results: [],
        replay_gate: {
          schema: "octopus.replay_gate.v1",
          passed: false,
          reason: "insufficient_cases:1<2",
          thresholds: { min_cases: 2, min_score: 1 },
          summary: {
            total: 1,
            passed: 1,
            failed: 0,
            below_min_score: 0,
          },
          failing_cases: [],
        },
        override_replay_gate: true,
      });

    renderWithProviders(<AgentOperatorPanel />);

    const apply = await screen.findByRole("button", {
      name: /Apply promoted/,
    });
    fireEvent.click(apply);

    expect(
      await screen.findByText("Replay gate blocked apply"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("insufficient_cases:1<2"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Override gate" }),
    ).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Override reason"), {
      target: { value: "Reviewed blocked replay gate and accepting risk." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Override gate" }));

    await waitFor(() => {
      expect(api.applyAgentTraceReviewQueuePromotions).toHaveBeenLastCalledWith(
        {
          limit: 50,
          overrideReplayGate: true,
          overrideReason: "Reviewed blocked replay gate and accepting risk.",
        },
      );
    });
    expect(
      await screen.findByText(
        "Applied 1, skipped 0, failed 0 · gate blocked · override",
      ),
    ).toBeInTheDocument();
  });

  it("shows a generic error instead of override dialog for non-409 apply failures", async () => {
    api.applyAgentTraceReviewQueuePromotions.mockRejectedValueOnce(
      new api.AgentTraceRequestError(500, { message: "internal failure" }),
    );

    renderWithProviders(<AgentOperatorPanel />);

    const apply = await screen.findByRole("button", {
      name: /Apply promoted/,
    });
    fireEvent.click(apply);

    expect(
      await screen.findByText("Agent trace request failed: 500"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Replay gate blocked apply"),
    ).not.toBeInTheDocument();
  });

  it("keeps the operator queue usable when the competitor scorecard fails", async () => {
    api.fetchAgentCompetitorScorecard.mockRejectedValueOnce(
      new Error("scorecard offline"),
    );

    renderWithProviders(<AgentOperatorPanel />);

    expect(
      await screen.findByText("Agent evolution queue"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("Useful workflow pattern"),
    ).toBeInTheDocument();
    expect(await screen.findByText("Competitor scorecard")).toBeInTheDocument();
    expect(await screen.findByText("degraded")).toBeInTheDocument();
    expect(await screen.findByText("scorecard offline")).toBeInTheDocument();
  });

  it("retires a risky subagent from the operator panel", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    const retire = await screen.findByRole("button", { name: "Retire" });
    fireEvent.click(retire);

    await waitFor(() => {
      expect(api.decideSubagentPolicy).toHaveBeenCalledWith(
        "virtual-research-competitor-analyst",
        {
          action: "retire",
          evidenceItemIds: ["route-research-1"],
          reason:
            "Retired from operator panel using subagent fitness route evidence.",
        },
      );
    });
  });
});
