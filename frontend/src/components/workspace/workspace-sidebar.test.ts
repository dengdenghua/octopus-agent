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

describe("workspace sidebar project grouping", () => {
  const makeThread = (
    threadId: string,
    mode: string,
    metadata: Record<string, unknown> = {},
  ) =>
    ({
      thread_id: threadId,
      title: threadId,
      updated_at: "2026-06-29T00:00:00Z",
      metadata: {
        mode,
        ...metadata,
      },
      values: {},
    }) as never;

  test("treats team threads as project threads", () => {
    expect(__testing.isProjectThreadMode("team")).toBe(true);
    expect(__testing.isProjectThreadMode("code")).toBe(true);
    expect(__testing.isProjectThreadMode("chat")).toBe(false);
  });

  test("keeps team history out of chat recents and under projects", () => {
    const threads = [
      makeThread("chat-1", "chat"),
      makeThread("team-1", "team", {
        workspace_path: "/Users/dangbei/Public/octopus/octopus-agent",
      }),
      makeThread("code-1", "code", {
        workspace_path: "/Users/dangbei/Public/octopus/octopus-agent",
      }),
    ];

    expect(
      __testing.buildConversationThreadSummaries(threads).map((t) => t.id),
    ).toEqual(["chat-1"]);
    const projectThreads = __testing.buildProjectThreadSummaries(threads);
    expect(projectThreads.map((t) => t.id)).toEqual(["team-1", "code-1"]);
    expect(projectThreads.find((t) => t.id === "team-1")?.href).toBe(
      "/workspace/realtime/team-1",
    );
  });

  test("groups team history by workspace folder before generated team label", () => {
    expect(
      __testing.projectNameForThread(
        { mode: "team" },
        {
          project: "Team · Eve",
          workspace_path: "/Users/dangbei/Public/octopus/octopus-agent",
        },
      ),
    ).toBe("octopus-agent");
  });

  test("groups team history without a folder under personal space", () => {
    expect(
      __testing.projectNameForThread(
        { mode: "team" },
        {
          project: "Team",
          workspace_path: "",
        },
        "个人空间",
      ),
    ).toBe("个人空间");
  });

  test("keeps explicit project labels for code threads", () => {
    expect(
      __testing.projectNameForThread(
        { mode: "code" },
        {
          project: "总项目",
          workspace_path: "/Users/dangbei/Public/octopus/octopus-agent",
        },
      ),
    ).toBe("总项目");
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
