import { describe, expect, test } from "vitest";

import { __testing } from "./workspace-sidebar";

describe("workspace sidebar route activation", () => {
  test("leaves primary nav inactive on agent-scoped chat threads", () => {
    const pathname = "/workspace/agents/general/chats/thread-1";

    expect(
      __testing.isNavRouteActive(pathname, "/workspace/realtime/new"),
    ).toBe(false);
    expect(__testing.isNavRouteActive(pathname, "/workspace/agents")).toBe(
      false,
    );
  });

  test("keeps primary chat active only on chat entry routes", () => {
    expect(
      __testing.isNavRouteActive(
        "/workspace/realtime/new",
        "/workspace/realtime/new",
      ),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive(
        "/workspace/agents/general/chats/new",
        "/workspace/realtime/new",
      ),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive(
        "/workspace/realtime/thread-1",
        "/workspace/realtime/new",
      ),
    ).toBe(false);
  });

  test("keeps the Hub active on normal agent routes", () => {
    expect(
      __testing.isNavRouteActive("/workspace/agents", "/workspace/agents"),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive("/workspace/agents/new", "/workspace/agents"),
    ).toBe(true);
  });

  test("keeps Hub in the surface selected by the sidebar entry", () => {
    expect(
      __testing.isCompanySurfaceActive("/workspace/agents", "?surface=chat"),
    ).toBe(false);
    expect(
      __testing.isCompanySurfaceActive("/workspace/agents", "?surface=company"),
    ).toBe(true);
    expect(__testing.isCompanySurfaceActive("/workspace/agents", "")).toBe(
      true,
    );
  });
});

describe("workspace sidebar thread status lights", () => {
  test("maps paused and pending background tasks onto conversation history", () => {
    const href = "/workspace/agents/general/chats/thread-1";
    const statusByHref = __testing.buildThreadRunStatusByHref({
      activeTeamTasks: [],
      backgroundTasks: {
        active: [],
        paused: [
          {
            agent_id: "general",
            note: "",
            reason: "user_request",
            requested_at: 1,
            requested_by: "user",
            task_id: "task-1",
            thread_id: "thread-1",
          },
        ],
        pending: [],
      },
      liveThreadRunStatusByHref: new Map(),
      threadHrefById: new Map([["thread-1", href]]),
    });

    expect(statusByHref.get(href)).toBe("waiting");
  });

  test("merges live workbench status over active background task status", () => {
    const href = "/workspace/agents/general/chats/thread-2";
    const statusByHref = __testing.buildThreadRunStatusByHref({
      activeTeamTasks: [],
      backgroundTasks: {
        active: [
          {
            agent_id: "general",
            current_iteration: 2,
            max_iterations: 12,
            max_tokens: 100_000,
            max_usd: 0,
            cost_usd: 0,
            started_at: 1,
            task_id: "task-2",
            thread_id: "thread-2",
            tokens_spent: 1200,
          },
        ],
        paused: [],
        pending: [],
      },
      liveThreadRunStatusByHref: new Map([[href, "waiting"]]),
      threadHrefById: new Map([["thread-2", href]]),
    });

    expect(statusByHref.get(href)).toBe("waiting");
  });

  test("keeps waiting ahead of running so colors match the workbench pause state", () => {
    expect(__testing.mergeThreadRunStatus("running", "waiting")).toBe(
      "waiting",
    );
  });
});
