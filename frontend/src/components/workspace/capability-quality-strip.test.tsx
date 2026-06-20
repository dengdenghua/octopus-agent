import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { CapabilityQualityStrip } from "./capability-quality-strip";

const api = vi.hoisted(() => ({
  fetchAgentCompetitorScorecard: vi.fn(),
  fetchBrowserDesktopQuality: vi.fn(),
}));

vi.mock("@/core/agent-trace/api", () => api);

describe("<CapabilityQualityStrip />", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchAgentCompetitorScorecard.mockResolvedValue({
      schema: "octopus.agent_competitor_scorecard.v1",
      target_score: 90,
      competitors: ["codex", "octopus"],
      overall: { codex: 93, octopus: 92 },
      ranking: [],
      verdict: "competitive",
      evidence_adjusted_overall: { codex: 93, octopus: 91 },
      evidence_adjusted_ranking: [],
      evidence_adjusted_verdict: "competitive",
      dimensions: [],
      octopus_below_target: [],
      octopus_strengths: [],
      next_focus: [],
      ecosystem_readiness: {
        schema: "octopus.ecosystem_readiness.v1",
        score: 0.94,
        passed: 8,
        total: 8,
        missing_count: 0,
        topics: [],
        next_actions: [],
      },
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
        pending_count: 0,
        reviewed_count: 36,
        promoted_count: 2,
        rejected_count: 34,
        review_rate: 1,
        stale_source_artifact_count: 0,
        by_status: {},
        by_candidate_kind: {},
        latest: [],
        next_actions: [],
      },
      next_actions: [],
    });
  });

  it("shows shared scorecard and browser quality on non-code surfaces", async () => {
    renderWithProviders(
      <CapabilityQualityStrip surface="browser" includeBrowserDesktop />,
    );

    expect(await screen.findByText("浏览器与桌面能力")).toBeInTheDocument();
    expect(await screen.findByText("Overall")).toBeInTheDocument();
    expect(await screen.findByText("Evidence")).toBeInTheDocument();
    expect(await screen.findByText("Eco")).toBeInTheDocument();
    expect(await screen.findByText("Browser")).toBeInTheDocument();
    expect(await screen.findByText("100 · stale 0")).toBeInTheDocument();
  });

  it("keeps the surface usable when quality APIs fail", async () => {
    api.fetchAgentCompetitorScorecard.mockRejectedValueOnce(
      new Error("scorecard unavailable"),
    );

    renderWithProviders(<CapabilityQualityStrip surface="knowledge" />);

    expect(await screen.findByText("知识与记忆能力")).toBeInTheDocument();
    expect(await screen.findByText("暂不可用")).toBeInTheDocument();
  });
});
