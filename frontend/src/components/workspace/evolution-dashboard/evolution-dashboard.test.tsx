import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import EvolutionDashboard from "./index";

const queries = vi.hoisted(() => ({
  overview: { data: null, isLoading: false, error: null, refetch: vi.fn() },
  learning: { data: null, isLoading: false, error: null, refetch: vi.fn() },
  skills: { data: null, isLoading: false, error: null, refetch: vi.fn() },
  memory: { data: null, isLoading: false, error: null, refetch: vi.fn() },
  recommendations: {
    data: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  },
}));

vi.mock("@/core/evolution/hooks", () => ({
  useEvolutionOverview: () => queries.overview,
  useLearningCurve: () => queries.learning,
  useSkillPerformance: () => queries.skills,
  useMemoryGrowth: () => queries.memory,
  useRecommendations: () => queries.recommendations,
}));

vi.mock("@/components/workspace/gene-lock-badge", () => ({
  GeneLockControlCard: () => null,
}));

describe("EvolutionDashboard states", () => {
  beforeEach(() => {
    for (const query of Object.values(queries)) {
      query.data = null;
      query.isLoading = false;
      query.error = null;
      query.refetch.mockReset();
      query.refetch.mockResolvedValue(undefined);
    }
  });

  it("waits for memory growth instead of rendering partial metrics", () => {
    queries.memory.isLoading = true;
    renderWithProviders(<EvolutionDashboard />, { locale: "zh-CN" });

    expect(screen.getByRole("status")).toHaveTextContent("加载中");
    expect(screen.queryByText("这段时间它进化了什么")).toBeNull();
  });

  it("offers one-click retry for every dashboard source", async () => {
    const user = userEvent.setup();
    queries.overview.error = new Error("offline");
    renderWithProviders(<EvolutionDashboard />, { locale: "zh-CN" });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "连接进化看板 API 失败",
    );
    await user.click(screen.getByRole("button", { name: "重新加载" }));

    for (const query of Object.values(queries)) {
      expect(query.refetch).toHaveBeenCalledOnce();
    }
  });

  it("labels populated trend and skill charts", () => {
    queries.overview.data = {
      skills: { total: 1, auto_extracted: 1 },
      memory: { total_facts: 2, categories: { rules: 1 } },
      learning_events: 3,
      improvement_score: 0.72,
    };
    queries.learning.data = [
      {
        week: "2026-W28",
        success_rate: 0.75,
        avg_duration_ms: 1200,
        skills_used: 2,
      },
      {
        week: "2026-W29",
        success_rate: 0.9,
        avg_duration_ms: 900,
        skills_used: 4,
      },
    ];
    queries.skills.data = [
      {
        name: "source-check",
        usage_count: 8,
        success_rate: 0.875,
        source: "auto",
      },
    ];
    queries.memory.data = [];
    queries.recommendations.data = [];

    renderWithProviders(<EvolutionDashboard />, { locale: "zh-CN" });

    expect(
      screen.getByRole("heading", {
        name: "这段时间它进化了什么",
        level: 2,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "能力趋势" })).toBeVisible();
    expect(
      screen.getByRole("listitem", { name: "2026-W29: 90%" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("progressbar", {
        name: "source-check · 成功率",
      }),
    ).toHaveAttribute("aria-valuenow", "88");
  });
});
