import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { DualHelixEvolutionPanel } from "./dual-helix-evolution-panel";

vi.mock("@/core/evolution/api", () => ({
  getCodexGapReport: vi.fn(async () => ({
    ok: true,
    schema: "octopus.codex_gap_report.v1",
    parity_score: 0.9,
    advantage_score: 0.8,
    combined_score: 0.85,
    verdict: "differentiated",
    capabilities: [
      {
        id: "loop",
        area: "codex_parity",
        title: "Execution loop",
        why: "baseline",
        score: 0.7,
        target_score: 0.9,
        status: "gap",
        next_actions: ["Promote verified repair policy"],
      },
    ],
  })),
  getAgentBenchmarkReport: vi.fn(async () => ({
    ok: true,
    schema: "octopus.agent_benchmark.v1",
    score: 0.75,
    passed: 9,
    total: 12,
    ready: false,
    cases: [],
  })),
  getDualHelixEvidence: vi.fn(async () => ({
    ok: true,
    schema: "octopus.dual_helix_evidence.v1",
    paired_count: 3,
    unpaired_count: 1,
    octopus_wins: 2,
    codex_wins: 1,
    ties: 0,
    octopus_win_rate: 0.667,
    strands: {
      octopus: { samples: 4, successes: 3, success_rate: 0.75 },
      codex: { samples: 3, successes: 2, success_rate: 0.667 },
    },
    pairs: [],
  })),
  getDualHelixShadowStatus: vi.fn(async () => ({
    ok: true,
    enabled: false,
    isolation: "bounded_snapshot_read_only",
    runs: [],
  })),
  setDualHelixShadowEnabled: vi.fn(async (enabled: boolean) => ({
    ok: true,
    enabled,
    runs: [],
  })),
}));

vi.mock("@/core/coder/api", () => ({
  coderUpstreamUpdateQueryKey: ["coder", "upstream"],
  getCoderUpstreamUpdate: vi.fn(async () => ({
    current_version: "0.149.0",
    latest_version: "0.150.0",
    update_available: true,
  })),
}));

vi.mock("@/core/evolution/hooks", () => ({
  useLedger: () => ({
    data: {
      total: 2,
      records: [
        {
          id: "one",
          description: "codex verifier failure",
          proposer: "realtime_cerebrum",
          status: "proposed",
        },
      ],
    },
  }),
  useCanary: () => ({ data: { active_count: 1, canaries: [] } }),
}));

describe("DualHelixEvolutionPanel", () => {
  it("renders both engine strands and real evolution evidence", async () => {
    renderWithProviders(<DualHelixEvolutionPanel />, { locale: "zh-CN" });

    expect(
      await screen.findByRole("heading", { name: "双引擎螺旋进化" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Octopus Native")).toBeInTheDocument();
    expect(screen.getByText("OpenAI Codex")).toBeInTheDocument();
    expect(await screen.findByText("9/12")).toBeInTheDocument();
    expect(
      await screen.findByText(/3 对任务已完成实战互评/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Promote verified repair policy"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Codex v0\.150\.0 待审核/)).toBeInTheDocument();
    expect(screen.getByText("保护模式已关闭")).toBeInTheDocument();
    expect(
      screen.getByText(/开启开关本身不会调用模型或产生费用/),
    ).toBeInTheDocument();
  });

  it("separates real comparisons, shadow reviews, and ledger evidence", async () => {
    renderWithProviders(<DualHelixEvolutionPanel view="evidence" />, {
      locale: "zh-CN",
    });

    expect(
      await screen.findByRole("heading", { name: "双引擎实验证据" }),
    ).toBeInTheDocument();
    expect(screen.getByText("同任务双引擎对照")).toBeInTheDocument();
    expect(screen.getByText("影子复核记录")).toBeInTheDocument();
    expect(screen.getByText("进化账本")).toBeInTheDocument();
  });
});
