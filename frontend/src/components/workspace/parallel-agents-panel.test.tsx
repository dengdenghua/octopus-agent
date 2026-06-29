import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as ParallelApi from "@/core/parallel-agents/api";
import type {
  BatchResult,
  OrchestratorStatus,
  TaskResult,
} from "@/core/parallel-agents/api";
import { renderWithProviders } from "@/test/harness";

import { ParallelAgentsPanel } from "./parallel-agents-panel";

const fetchStatusMock = vi.fn();
const fetchBatchMock = vi.fn();

vi.mock("@/core/parallel-agents/api", async () => {
  const actual = await vi.importActual<typeof ParallelApi>(
    "@/core/parallel-agents/api",
  );
  return {
    ...actual,
    fetchOrchestratorStatus: (...args: unknown[]) => fetchStatusMock(...args),
    fetchBatch: (...args: unknown[]) => fetchBatchMock(...args),
    cancelAll: vi.fn(),
    cancelTask: vi.fn(),
  };
});

function orchestratorStatus(
  overrides: Partial<OrchestratorStatus> = {},
): OrchestratorStatus {
  return {
    active_count: 0,
    pending_count: 0,
    completed_count: 0,
    failed_count: 0,
    cancelled_count: 0,
    max_concurrency: 8,
    batches: {},
    ...overrides,
  };
}

function task(overrides: Partial<TaskResult> = {}): TaskResult {
  return {
    task_id: "task_1",
    batch_id: "batch_1",
    description: "Run one worker",
    status: "completed",
    result: "ok",
    error: null,
    started_at: null,
    completed_at: null,
    duration_seconds: null,
    subagent_name: "coder",
    work_contract: null,
    ...overrides,
  };
}

function batch(overrides: Partial<BatchResult> = {}): BatchResult {
  return {
    batch_id: "batch_1",
    status: "completed",
    total_tasks: 1,
    completed_tasks: 1,
    failed_tasks: 0,
    cancelled_tasks: 0,
    created_at: null,
    completed_at: null,
    results: [task()],
    aggregated_content: null,
    aggregation_strategy: "concat",
    conflicts: [],
    event_log: [],
    plan: null,
    ...overrides,
  };
}

describe("<ParallelAgentsPanel />", () => {
  beforeEach(() => {
    fetchStatusMock.mockReset();
    fetchBatchMock.mockReset();
  });

  it("loads a terminal batch instead of hiding it behind the empty state", async () => {
    fetchStatusMock.mockResolvedValue(
      orchestratorStatus({
        failed_count: 1,
        batches: { batch_timeout: "timed_out" },
      }),
    );
    fetchBatchMock.mockResolvedValue(
      batch({
        batch_id: "batch_timeout",
        status: "timed_out",
        completed_tasks: 0,
        failed_tasks: 1,
        results: [
          task({
            batch_id: "batch_timeout",
            status: "timed_out",
            result: null,
            error: "deadline exceeded",
          }),
        ],
      }),
    );

    renderWithProviders(<ParallelAgentsPanel />);

    await waitFor(() =>
      expect(fetchBatchMock).toHaveBeenCalledWith("batch_timeout"),
    );
    expect(await screen.findByText("deadline exceeded")).toBeInTheDocument();
    expect(screen.getByText("Timed Out")).toBeInTheDocument();
    expect(screen.queryByText("No parallel tasks")).not.toBeInTheDocument();
  });

  it("still prefers a running batch when terminal history also exists", async () => {
    fetchStatusMock.mockResolvedValue(
      orchestratorStatus({
        active_count: 1,
        failed_count: 1,
        batches: {
          batch_failed: "failed",
          batch_running: "running",
        },
      }),
    );
    fetchBatchMock.mockResolvedValue(
      batch({
        batch_id: "batch_running",
        status: "running",
        completed_tasks: 0,
        results: [
          task({
            batch_id: "batch_running",
            status: "running",
            result: null,
          }),
        ],
      }),
    );

    renderWithProviders(<ParallelAgentsPanel />);

    await waitFor(() =>
      expect(fetchBatchMock).toHaveBeenCalledWith("batch_running"),
    );
    expect(fetchBatchMock).not.toHaveBeenCalledWith("batch_failed");
  });
});
