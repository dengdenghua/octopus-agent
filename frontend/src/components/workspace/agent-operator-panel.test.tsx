import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AgentOperatorPanel } from "./agent-operator-panel";

const api = vi.hoisted(() => ({
  applyAgentTraceReviewQueuePromotions: vi.fn(),
  decideAgentTraceReviewQueueItem: vi.fn(),
  fetchAgentTraceProcessTimeline: vi.fn(),
  fetchAgentTraceReviewQueue: vi.fn(),
  fetchAgentTraceReviewQueueSummary: vi.fn(),
  fetchAgentTraceTaskRuns: vi.fn(),
  queueAgentTraceTaskRunReview: vi.fn(),
}));

vi.mock("@/core/agent-trace/api", () => api);

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
    api.fetchAgentTraceReviewQueue.mockResolvedValue([
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
    api.fetchAgentTraceReviewQueueSummary.mockResolvedValue({
      schema: "octopus.review_queue.v1",
      total: 3,
      pending_count: 1,
      by_status: { pending: 1, promoted: 1, rejected: 1 },
      by_priority: { P1: 1 },
      by_target_bucket: { experience: 1 },
      next_actions: [],
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
    api.applyAgentTraceReviewQueuePromotions.mockResolvedValue({
      schema: "octopus.promotion_applier.v1",
      dry_run: false,
      applied: 1,
      failed: 0,
      skipped: 0,
      results: [],
    });
    api.queueAgentTraceTaskRunReview.mockResolvedValue({
      created: 0,
      updated: 1,
      total: 3,
      items: [],
    });
  });

  it("renders task runs, timeline and pending review queue", async () => {
    renderWithProviders(<AgentOperatorPanel />);

    expect(await screen.findByText("Agent evolution queue")).toBeInTheDocument();
    expect((await screen.findAllByText("Build report")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Useful workflow pattern")).toBeInTheDocument();
    expect(await screen.findByText("score 0.92")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Promoted")).toBeInTheDocument();
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
    expect(await screen.findByText("Applied 1, skipped 0, failed 0")).toBeInTheDocument();
  });
});
