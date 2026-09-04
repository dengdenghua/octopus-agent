import { describe, expect, test } from "vitest";

import {
  dedupeRunReviewEvents,
  deriveRunReviews,
  type RunReviewEvent,
} from "./run-review-panel";

function event(partial: RunReviewEvent): RunReviewEvent {
  return {
    event_type: "step",
    ts: "2026-05-22T00:00:00.000Z",
    task_id: "task-1",
    ...partial,
  };
}

describe("deriveRunReviews", () => {
  test("groups journal events into task-level run reviews", () => {
    const reviews = deriveRunReviews([
      event({
        event_type: "sub_tool_start",
        tool_call_id: "tool-1",
        tool_name: "read_file",
      }),
      event({
        event_type: "sub_tool_end",
        tool_call_id: "tool-1",
        tool_name: "read_file",
        duration_ms: 42,
      }),
      event({
        event_type: "file_op",
        action: "write",
        path: "frontend/src/app.tsx",
      }),
      event({
        event_type: "budget_commit",
        tokens: 1200,
        usd: 0.012,
      }),
    ]);

    expect(reviews).toHaveLength(1);
    expect(reviews[0]).toMatchObject({
      id: "task-1",
      status: "done",
      eventCount: 4,
      fileCount: 1,
      tokens: 1200,
      usd: 0.012,
    });
    expect(reviews[0]?.tools.map((tool) => tool.name)).toContain("read_file");
    expect(reviews[0]?.files).toEqual(["frontend/src/app.tsx"]);
  });

  test("marks active tool calls as running until their end event arrives", () => {
    const [review] = deriveRunReviews([
      event({
        event_type: "sub_tool_start",
        tool_call_id: "tool-1",
        tool_name: "web_search",
      }),
    ]);

    expect(review?.status).toBe("running");
  });

  test("extracts risks from approvals and errors for learning review", () => {
    const [review] = deriveRunReviews([
      event({ event_type: "tool_approval_request" }),
      event({ event_type: "sub_tool_end", is_error: true, tool_name: "bash" }),
      event({ event_type: "budget_breaker_reject" }),
    ]);

    expect(review?.status).toBe("error");
    expect(review?.approvalCount).toBe(1);
    expect(review?.errorCount).toBe(2);
    expect(review?.risks).toEqual(
      expect.arrayContaining([
        "approval_required",
        "sub_tool_end",
        "budget_breaker_reject",
      ]),
    );
  });
});

describe("dedupeRunReviewEvents", () => {
  test("collapses SSE replay frames by event id", () => {
    const first = event({
      event_id: "journal-42",
      event_type: "sub_tool_end",
      tool_call_id: "tool-1",
      tool_name: "read_file",
    });

    expect(dedupeRunReviewEvents([first, { ...first }])).toEqual([first]);
  });

  test("uses a stable payload key for legacy frames without an id", () => {
    const first = event({
      event_type: "file_op",
      action: "write",
      path: "src/app.tsx",
    });
    const duplicate = { ...first };

    expect(dedupeRunReviewEvents([first, duplicate])).toHaveLength(1);
  });
});
