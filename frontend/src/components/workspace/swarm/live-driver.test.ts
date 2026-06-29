import { describe, expect, it } from "vitest";

import type { BatchResult } from "@/core/parallel-agents/api";

import { batchToSession } from "./live-driver";

function batch(overrides: Partial<BatchResult> = {}): BatchResult {
  return {
    batch_id: "batch_failed",
    status: "failed",
    total_tasks: 3,
    completed_tasks: 1,
    failed_tasks: 1,
    cancelled_tasks: 1,
    created_at: "2026-06-29T00:00:00Z",
    completed_at: "2026-06-29T00:00:05Z",
    aggregated_content: "[writer] done",
    aggregation_strategy: "concat",
    conflicts: [],
    plan: {
      batch_id: "batch_failed",
      strategy: "parallel_agents",
      max_concurrency: 3,
      contracts: [],
      phases: [
        { phase_index: 0, task_ids: ["ok", "bad", "stop"], parallel: true },
      ],
    },
    event_log: [],
    results: [
      {
        task_id: "ok",
        batch_id: "batch_failed",
        description: "ok task",
        status: "completed",
        result: "done",
        error: null,
        started_at: "2026-06-29T00:00:00Z",
        completed_at: "2026-06-29T00:00:01Z",
        duration_seconds: 1,
        subagent_name: "writer",
      },
      {
        task_id: "bad",
        batch_id: "batch_failed",
        description: "bad task",
        status: "failed",
        result: null,
        error: "boom",
        started_at: "2026-06-29T00:00:00Z",
        completed_at: "2026-06-29T00:00:02Z",
        duration_seconds: 2,
        subagent_name: "reviewer",
      },
      {
        task_id: "stop",
        batch_id: "batch_failed",
        description: "cancel task",
        status: "cancelled",
        result: null,
        error: "dependency_failed",
        started_at: null,
        completed_at: "2026-06-29T00:00:03Z",
        duration_seconds: null,
        subagent_name: "tester",
      },
    ],
    ...overrides,
  };
}

describe("batchToSession", () => {
  it("preserves failed and cancelled terminal task states", () => {
    const session = batchToSession(batch());

    expect(session.status).toBe("done");
    expect(session.workflow?.status).toBe("failed");
    expect(session.workflow?.completedTasks).toBe(1);
    expect(session.workflow?.failedTasks).toBe(1);
    expect(session.workflow?.cancelledTasks).toBe(1);
    expect(session.agents.map((agent) => agent.status)).toEqual([
      "done",
      "failed",
      "cancelled",
    ]);
    expect(session.phaseReports?.[0]?.status).toBe("partial");
    expect(session.phaseReports?.[0]?.failed).toBe(2);
  });
});
