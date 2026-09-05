import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import {
  CollaborationCollectorPanel,
  latestCollaborationCoordinate,
} from "./collaboration-collector-panel";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      coworkCollab: {
        collectorTitle: "Member execution",
        collectorProgress: (completed: number, total: number) =>
          `${completed}/${total} returned`,
        collectorSuccess: "Completed",
        collectorFailed: "Incomplete",
        collectorWaiting: "Waiting",
        collectorRetrying: "Retrying",
        collectorCancelled: "Cancelled",
        collectorRetryFailedOnly: "Retry failed members only",
        collectorRetryFailedRuns: (n: number) => `Retry failed runs (${n})`,
        collectorRetryFailed: "Retry could not start",
        collectorQueueFull: "Queue busy; failed members are preserved",
        collectorStop: "Stop collaboration",
        collectorStopRuns: (n: number) => `Stop active runs (${n})`,
        collectorStopFailed: "Collaboration could not be stopped",
        collectorSteer: "Redirect",
        collectorSteerMemberLabel: (name: string) => `Redirect ${name}`,
        collectorSteerPlaceholder: (name: string) =>
          `New instructions for ${name} only…`,
        collectorSteerSubmit: "Send correction",
        collectorSteerCancel: "Cancel",
        collectorSteerFailed: "Correction could not be sent",
        collectorStopMember: "Stop member",
        collectorStopMemberLabel: (name: string) => `Stop ${name}`,
        collectorStopMemberFailed: "The member could not be stopped",
        collectorAttempts: (n: number) => `${n} attempts`,
        collectorAttempt: (n: number) => `Attempt ${n}`,
        collectorContextDelivery: (
          mode: string,
          sent: number,
          avoided: number,
        ) => `${mode} context ${sent} sent ${avoided} avoided`,
        collectorContextPlan: (
          mode: string,
          selected: number,
          full: number,
          reductionPercent: number,
        ) =>
          `Context routing ${mode} ${selected}/${full} saved ${reductionPercent}%`,
        collectorMemoryCheckpoint: (throughTurn: number, rawTurns: number) =>
          `memory through ${throughTurn} of ${rawTurns} raw turns`,
        collectorArchived: "Archived",
        collectorMonitorUnavailable: "Monitor unavailable",
      },
    },
  }),
}));

function event(partial: Partial<LiveToolEvent> = {}): LiveToolEvent {
  return {
    id: "team-1",
    iteration: 1,
    name: "team_swarm",
    startedAt: 1,
    status: "done",
    input: {
      arguments: {
        collaboration_run_id: "cowork-fanout:turn-1",
        specs: [
          { agent_id: "coder", display_name: "Kane" },
          { agent_id: "reviewer", display_name: "Raven" },
        ],
        context_plan: {
          deep_recall_escalated: false,
          estimated_reduction_ratio: 0.75,
          full_context_estimated_tokens: 1600,
          selected_estimated_tokens: 400,
        },
      },
    },
    ...partial,
  };
}

function response(body: unknown, ok = true, status = ok ? 200 : 500): Response {
  return {
    json: async () => body,
    ok,
    status,
  } as Response;
}

const failedCollector = {
  active_retry_child_ids: [],
  attempt_count: 2,
  completed_count: 2,
  expected_child_ids: ["coder", "reviewer"],
  expected_count: 2,
  failure_count: 1,
  generation: 1,
  remaining_child_ids: [],
  results: [
    {
      attempt: 1,
      child_id: "coder",
      completed_at: "2026-09-05T00:00:00Z",
      result: { error: "model timed out" },
      status: "failed",
    },
    {
      attempt: 1,
      child_id: "reviewer",
      completed_at: "2026-09-05T00:00:01Z",
      result: {
        text: "reviewed",
        context_delivery: {
          avoided_estimated_tokens: 320,
          mode: "incremental",
          sent_estimated_tokens: 48,
        },
        session_compaction: {
          checkpoint_through_turn: 12,
          checkpoint_valid: true,
          raw_turns_retained: 16,
        },
      },
      status: "success",
    },
  ],
  revision: 3,
  status: "completed",
  success_count: 1,
};

describe("CollaborationCollectorPanel", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("finds the durable run coordinate and human member names", () => {
    const coordinate = latestCollaborationCoordinate([event()]);

    expect(coordinate?.runId).toBe("cowork-fanout:turn-1");
    expect(coordinate?.displayNames.get("coder")).toBe("Kane");
    expect(coordinate?.contextPlan).toEqual({
      deepRecall: false,
      fullTokens: 1600,
      reductionPercent: 75,
      selectedTokens: 400,
    });
  });

  it("explains when context routing escalated to long-term recall", async () => {
    const recallEvent = event({
      output: {
        result: {
          context_plan: {
            deep_recall_escalated: true,
            estimated_reduction_ratio: 0.9781,
            full_context_estimated_tokens: 19_406,
            selected_estimated_tokens: 425,
          },
        },
      },
    });
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ collector: failedCollector }))
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(response({ collectors: [] }));

    render(
      <CollaborationCollectorPanel
        events={[recallEvent]}
        threadId="thread-1"
      />,
    );

    expect(
      await screen.findByTestId("collaboration-context-plan"),
    ).toHaveTextContent("Context routing recall 425/19406 saved 97.8%");
  });

  it("shows durable member outcomes and retries only the failed lane", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ collector: failedCollector }))
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(
        response({
          collectors: [
            {
              retryable_child_ids: ["coder"],
              run_id: "cowork-fanout:turn-1",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        response({
          collector: {
            ...failedCollector,
            active_retry_child_ids: ["coder"],
            completed_count: 1,
            failure_count: 0,
            generation: 2,
            remaining_child_ids: ["coder"],
            revision: 4,
            status: "collecting",
          },
        }),
      )
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(response({ collectors: [] }))
      .mockResolvedValueOnce(
        response({
          collector: {
            ...failedCollector,
            attempt_count: 3,
            failure_count: 0,
            generation: 2,
            results: [
              {
                ...failedCollector.results[0],
                attempt: 2,
                result: { text: "fixed" },
                status: "success",
              },
              failedCollector.results[1],
            ],
            revision: 5,
            success_count: 2,
          },
        }),
      )
      .mockResolvedValueOnce(
        response({
          attempts: [
            ...failedCollector.results,
            {
              ...failedCollector.results[0],
              attempt: 2,
              result: { text: "fixed" },
              status: "success",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(response({ collectors: [] }));

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );

    expect(await screen.findByText("Member execution")).toBeInTheDocument();
    expect(screen.getByText("Kane")).toBeInTheDocument();
    expect(screen.getByText("model timed out")).toBeInTheDocument();
    expect(screen.getByText("Raven")).toBeInTheDocument();
    expect(
      screen.getByText(/incremental context 48 sent 320 avoided/),
    ).toHaveTextContent("memory through 12 of 16 raw turns");

    fireEvent.click(
      screen.getByRole("button", { name: "Retry failed members only" }),
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/collector/retry"),
        expect.objectContaining({
          body: JSON.stringify({ child_ids: ["coder"] }),
          method: "POST",
        }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByText("2/2 returned")).toBeInTheDocument(),
    );
  });

  it("keeps failed members retryable when queue backpressure rejects the batch", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ collector: failedCollector }))
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(
        response({
          collectors: [
            {
              retryable_child_ids: ["coder"],
              run_id: "cowork-fanout:turn-1",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        response({ detail: { code: "COWORK_QUEUE_FULL" } }, false, 429),
      );

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Retry failed members only",
      }),
    );

    expect(
      await screen.findByText("Queue busy; failed members are preserved"),
    ).toBeInTheDocument();
    expect(screen.getByText("model timed out")).toBeInTheDocument();
  });

  it("retries failed members across collaboration runs in one operation", async () => {
    const retryingCollector = {
      ...failedCollector,
      active_retry_child_ids: ["coder"],
      completed_count: 1,
      failure_count: 0,
      generation: 2,
      remaining_child_ids: ["coder"],
      revision: 4,
      status: "collecting",
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ collector: failedCollector }))
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(
        response({
          collectors: [
            {
              retryable_child_ids: ["coder"],
              run_id: "cowork-fanout:turn-1",
            },
            {
              retryable_child_ids: ["researcher"],
              run_id: "cowork-fanout:turn-0",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        response({ collectors: [retryingCollector, retryingCollector] }),
      )
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(response({ collectors: [] }))
      .mockResolvedValueOnce(
        response({
          collector: {
            ...failedCollector,
            generation: 2,
            revision: 5,
          },
        }),
      )
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(response({ collectors: [] }));

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Retry failed runs (2)" }),
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/collectors/retry"),
        expect.objectContaining({
          body: JSON.stringify({
            run_ids: ["cowork-fanout:turn-1", "cowork-fanout:turn-0"],
          }),
          method: "POST",
        }),
      ),
    );
  });

  it("sends a durable correction only to the selected active member", async () => {
    const activeCollector = {
      ...failedCollector,
      attempt_count: 1,
      completed_count: 1,
      expected_count: 2,
      failure_count: 0,
      remaining_child_ids: ["coder"],
      results: [failedCollector.results[1]],
      revision: 1,
      status: "collecting" as const,
      success_count: 1,
    };
    let correctionSent = false;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/collector/coder/steer")) {
        correctionSent = true;
        return response({
          collector: { ...activeCollector, revision: 2 },
          steering: { child_id: "coder", seq: 1 },
        });
      }
      if (url.includes("/collector/attempts")) {
        return response({ attempts: activeCollector.results });
      }
      if (url.includes("/collectors?")) {
        return response({
          collectors: [
            {
              collector: { status: "collecting" },
              retryable_child_ids: [],
              run_id: "cowork-fanout:turn-1",
            },
          ],
        });
      }
      if (url.includes("/collector?after_revision=0")) {
        return response({
          collector: correctionSent
            ? { ...failedCollector, revision: 3 }
            : activeCollector,
        });
      }
      if (url.includes("/collector?after_revision=1")) {
        return await new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Redirect Kane" }),
    );
    const editor = screen.getByRole("textbox", {
      name: "New instructions for Kane only…",
    });
    fireEvent.change(editor, {
      target: { value: "Verify the newest primary source before answering." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send correction" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/collector/coder/steer"),
        expect.objectContaining({
          body: JSON.stringify({
            text: "Verify the newest primary source before answering.",
          }),
          method: "POST",
        }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
  });

  it("stops one active member without cancelling the rest of the run", async () => {
    const activeCollector = {
      ...failedCollector,
      attempt_count: 1,
      completed_count: 1,
      failure_count: 0,
      remaining_child_ids: ["coder"],
      results: [failedCollector.results[1]],
      revision: 1,
      status: "collecting" as const,
      success_count: 1,
    };
    const stoppedCollector = {
      ...failedCollector,
      failure_count: 0,
      results: [
        {
          ...failedCollector.results[0],
          result: { error: "member cancelled by user" },
          status: "cancelled" as const,
        },
        failedCollector.results[1],
      ],
      revision: 2,
    };
    let memberStopped = false;
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      const url = String(input);
      if (init?.method === "POST" && url.endsWith("/collector/coder/cancel")) {
        memberStopped = true;
        return response({ collector: stoppedCollector });
      }
      if (url.includes("/collector/attempts")) {
        return response({
          attempts: memberStopped
            ? stoppedCollector.results
            : activeCollector.results,
        });
      }
      if (url.includes("/collectors?")) {
        return response({
          collectors: memberStopped
            ? []
            : [
                {
                  collector: { status: "collecting" },
                  retryable_child_ids: [],
                  run_id: "cowork-fanout:turn-1",
                },
              ],
        });
      }
      if (url.includes("/collector?after_revision=0")) {
        return response({
          collector: memberStopped ? stoppedCollector : activeCollector,
        });
      }
      if (url.includes("/collector?after_revision=1")) {
        return await new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
        });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Stop Kane" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/collector/coder/cancel"),
        expect.objectContaining({
          body: JSON.stringify({}),
          method: "POST",
        }),
      ),
    );
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
  });

  it("stops an active collaboration run without showing a retry action", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ collector: failedCollector }))
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(
        response({
          collectors: [
            {
              collector: { status: "collecting" },
              retryable_child_ids: [],
              run_id: "cowork-fanout:older-active-turn",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        response({
          collectors: [
            {
              collector: { ...failedCollector, status: "cancelled" },
              run_id: "cowork-fanout:older-active-turn",
            },
          ],
        }),
      )
      .mockResolvedValueOnce(response({ attempts: failedCollector.results }))
      .mockResolvedValueOnce(response({ collectors: [] }));

    render(
      <CollaborationCollectorPanel events={[event()]} threadId="thread-1" />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Stop collaboration" }),
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/collectors/cancel"),
        expect.objectContaining({
          body: JSON.stringify({
            run_ids: ["cowork-fanout:older-active-turn"],
          }),
          method: "POST",
        }),
      ),
    );
  });
});
