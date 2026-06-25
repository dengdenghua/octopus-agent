import { describe, expect, test } from "vitest";

import { deriveAgentPhases, progressForPhases } from "./agent-phases";
import type { LiveToolEvent } from "./live-tool-timeline";

function event(partial: Partial<LiveToolEvent>): LiveToolEvent {
  return {
    id: "event-1",
    name: "read_file",
    status: "done",
    startedAt: 1000,
    iteration: 0,
    ...partial,
  };
}

describe("agent phases", () => {
  test("does not let a stale approval hold progress after a run settles", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "approval",
          name: "write_text_file",
          status: "waiting_approval",
          input: { path: "plan.md" },
        }),
      ],
      { hasAnswer: true, runSettled: true },
    );

    expect(state.currentPhase?.status).toBe("done");
    expect(state.currentPhase?.title).toContain("Phase 2");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 2,
      total: 2,
    });
  });

  test("keeps waiting approval active before the final answer", () => {
    const state = deriveAgentPhases([
      event({
        id: "approval",
        name: "write_text_file",
        status: "waiting_approval",
        input: { path: "plan.md" },
      }),
    ]);

    expect(state.currentPhase?.status).toBe("waiting_approval");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 1,
      total: 2,
    });
  });

  test("keeps unfinished todo phases active when an interim answer exists", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "todo-1",
          name: "todo_write",
          status: "done",
          input: {
            items: [
              { content: "已确认调研范围", status: "completed" },
              { content: "撰写 plan.md", status: "completed" },
              {
                content: "执行 deep-research-swarm 多源调研",
                status: "pending",
              },
              { content: "正在汇总最终交付", status: "pending" },
            ],
          },
        }),
      ],
      { hasAnswer: true },
    );

    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "done",
      "pending",
      "pending",
    ]);
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 3,
      total: 4,
    });
  });

  test("marks stale unfinished todo phases complete after a settled answer", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "todo-1",
          name: "todo_write",
          status: "done",
          input: {
            items: [
              { content: "已确认调研范围", status: "completed" },
              { content: "撰写 plan.md", status: "completed" },
              {
                content: "执行 deep-research-swarm 多源调研",
                status: "pending",
              },
              { content: "正在汇总最终交付", status: "pending" },
            ],
          },
        }),
      ],
      { hasAnswer: true, runSettled: true },
    );

    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "done",
      "done",
      "done",
    ]);
    expect(state.currentPhase?.status).toBe("done");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 4,
      total: 4,
    });
  });

  test("marks the first unfinished todo phase failed when a settled run has no deliverable", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "todo-1",
          name: "todo_write",
          status: "done",
          input: {
            items: [
              { content: "create plan.md", status: "completed" },
              { content: "run deep research", status: "in_progress" },
              { content: "write long report", status: "pending" },
              { content: "deliver final answer", status: "pending" },
            ],
          },
        }),
      ],
      { runSettled: true, runFailed: true },
    );

    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "error",
      "pending",
      "pending",
    ]);
    expect(state.currentPhase?.title).toBe("Phase 2: run deep research");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 2,
      total: 4,
    });
  });

  test("keeps unfinished todo phases pending when the run is paused", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "todo-1",
          name: "todo_write",
          status: "done",
          input: {
            items: [
              { content: "confirm scope", status: "completed" },
              { content: "write plan.md", status: "completed" },
              { content: "run deep-research-swarm", status: "pending" },
              { content: "assemble final report", status: "pending" },
            ],
          },
        }),
      ],
      { hasAnswer: true, runSettled: true, paused: true },
    );

    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "done",
      "pending",
      "pending",
    ]);
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 3,
      total: 4,
    });
  });

  test("allows only the earliest active todo phase to run", () => {
    const state = deriveAgentPhases([
      event({
        id: "todo-1",
        name: "todo_write",
        status: "done",
        input: {
          items: [
            { content: "create research plan", status: "completed" },
            { content: "deep research NAS market", status: "in_progress" },
            { content: "write research report", status: "in_progress" },
          ],
        },
      }),
    ]);

    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "running",
      "pending",
    ]);
    expect(state.currentPhase?.title).toBe("Phase 2: deep research NAS market");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 2,
      total: 3,
    });
  });

  test("plain research-shaped events use generic phases instead of a fixed research template", () => {
    const state = deriveAgentPhases([
      event({
        id: "ev-search",
        name: "web_search",
        status: "done",
      }),
      event({
        id: "ev-write",
        name: "write_text_file",
        status: "running",
      }),
    ]);

    expect(state.phases.length).toBe(2);
    const statuses = state.phases.map((phase) => phase.status);
    expect(state.phases[0]?.id).toBe("generic:execute");
    expect(state.phases[1]?.id).toBe("generic:deliver");
    expect(statuses).toEqual(["running", "pending"]);
  });

  test("prioritizes waiting approval over running in generic phases", () => {
    const state = deriveAgentPhases([
      event({
        id: "ev-search-running",
        name: "web_search",
        status: "running",
        input: { query: "market signal" },
      }),
      event({
        id: "ev-fetch-approval",
        name: "fetch_url",
        status: "waiting_approval",
        input: { url: "https://example.com/report" },
      }),
    ]);

    expect(state.currentPhase?.status).toBe("waiting_approval");
    expect(state.phases.map((phase) => phase.status)).toEqual([
      "waiting_approval",
    ]);
  });

  test("treats manual verification-required audit as waiting in generic phases", () => {
    const state = deriveAgentPhases([
      event({
        id: "read-package",
        name: "read_file",
        status: "done",
        input: { path: "package.json" },
      }),
      event({
        id: "verify-required",
        name: "verification:manual",
        status: "error",
        input: { command: "verification required" },
        output: {
          summary:
            "Code changes were produced but no verification step was recorded before final answer.",
        },
      }),
    ]);

    expect(state.blocks.map((block) => [block.id, block.status])).toEqual([
      ["read-package", "done"],
      ["verify-required", "waiting_approval"],
    ]);
    expect(state.currentPhase?.status).toBe("waiting_approval");
    expect(state.phases.map((phase) => phase.status)).toEqual([
      "done",
      "waiting_approval",
    ]);
    expect(state.phases[0]?.blockIds).toEqual(["read-package"]);
    expect(state.phases[1]?.blockIds).toEqual(["verify-required"]);
  });

  test("settled research-shaped events still resolve through generic phases", () => {
    const state = deriveAgentPhases(
      [
        event({
          id: "ev-search",
          name: "web_search",
          status: "done",
        }),
        event({
          id: "ev-report",
          name: "write_text_file",
          status: "done",
          input: { path: "report.md" },
        }),
      ],
      { hasAnswer: true, runSettled: true },
    );

    expect(state.phases.length).toBe(2);
    expect(state.phases.map((phase) => phase.status)).toEqual(["done", "done"]);
    expect(state.currentPhase?.title).toBe("Phase 2: 整理结果与交付");
    expect(progressForPhases(state.phases, state.currentPhase!)).toEqual({
      current: 2,
      total: 2,
    });
  });
});
