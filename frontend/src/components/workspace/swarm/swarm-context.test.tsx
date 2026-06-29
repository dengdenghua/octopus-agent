import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BatchStreamCallbacks } from "@/core/parallel-agents/api";

import { SwarmProvider, useSwarm } from "./swarm-context";

const fetchBatch = vi.fn();
let streamCallbacks: BatchStreamCallbacks | null = null;

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      traceGenerator: {},
    },
  }),
}));

vi.mock("@/core/parallel-agents/api", () => ({
  fetchBatch: (...args: unknown[]) => fetchBatch(...args),
  fetchFirstRunningSession: vi.fn(async () => null),
  streamBatch: (_batchId: string, callbacks: BatchStreamCallbacks) => {
    streamCallbacks = callbacks;
    return vi.fn();
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  return <SwarmProvider>{children}</SwarmProvider>;
}

describe("SwarmProvider live batch state", () => {
  beforeEach(() => {
    fetchBatch.mockReset();
    fetchBatch.mockResolvedValue(null);
    streamCallbacks = null;
  });

  it("keeps failed batch_complete status in workflow when batch refetch fails", async () => {
    const { result } = renderHook(() => useSwarm(), { wrapper });

    act(() => {
      result.current.connectBatch("batch_failed");
    });
    expect(streamCallbacks).not.toBeNull();

    await act(async () => {
      streamCallbacks?.onBatchComplete?.({
        type: "batch_complete",
        batch_id: "batch_failed",
        status: "failed",
        payload: {
          status: "failed",
          total_tasks: 2,
          completed_tasks: 1,
          failed_tasks: 1,
          cancelled_tasks: 0,
        },
      });
    });

    await waitFor(() => {
      expect(result.current.connectedBatchId).toBeNull();
      expect(result.current.session.status).toBe("done");
      expect(result.current.session.workflow?.status).toBe("failed");
    });
    expect(result.current.session.workflow).toMatchObject({
      stage: "final_report",
      progress: 1,
      totalTasks: 2,
      completedTasks: 1,
      failedTasks: 1,
      cancelledTasks: 0,
    });
  });
});
