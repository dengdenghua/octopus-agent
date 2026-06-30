import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  FileChangeItem,
  McpToolCallItem,
  SubagentItem,
  TodoListItem,
  Turn,
  VerificationItem,
} from "@/core/realtime/items";

import {
  useThreadStreamRealtime,
  liveToolEventsFromConversation,
  liveToolEventsFromLastTurn,
} from "./use-thread-stream-realtime";
import { useRealtimeThread } from "@/core/realtime";

vi.mock("@/core/realtime", () => ({
  useRealtimeThread: vi.fn(),
}));

const BASE_TS = "2026-05-09T00:00:00.000Z";
const DONE_TS = "2026-05-09T00:00:02.000Z";

function makeConversation(turns: Turn[]): Conversation {
  return {
    threadId: "th-test",
    turns,
    pendingApprovals: [],
    tokenUsage: null,
    resumeState: "resumed",
  };
}

function makeConversationWithApproval(turns: Turn[]): Conversation {
  return {
    ...makeConversation(turns),
    pendingApprovals: [
      {
        requestId: 7,
        method: "item/commandExecution/requestApproval",
        params: {
          itemId: "cmd-approval",
          tool: "exec_shell",
          argsPreview: "rm -rf /tmp/demo",
          detail: "dangerous command",
        },
        createdAt: BASE_TS,
      },
    ],
  };
}

function makeTurn(items: Turn["items"], id = "turn-1"): Turn {
  return {
    id,
    threadId: "th-test",
    status: "completed",
    startedAt: BASE_TS,
    completedAt: DONE_TS,
    items,
    error: null,
  };
}

function commandItem(
  overrides: Partial<CommandExecutionItem> = {},
): CommandExecutionItem {
  return {
    id: "cmd-1",
    type: "commandExecution",
    status: "completed",
    createdAt: BASE_TS,
    command: "list_cwd",
    inputPreview: { path: "." },
    cwd: "/repo",
    aggregatedOutput: "listed files",
    exitCode: 0,
    processId: null,
    networkAccess: false,
    ...overrides,
  };
}

function mcpItem(overrides: Partial<McpToolCallItem> = {}): McpToolCallItem {
  return {
    id: "mcp-1",
    type: "mcpToolCall",
    status: "completed",
    createdAt: BASE_TS,
    server: "fs",
    tool: "read",
    arguments: { path: "README.md" },
    result: { ok: true },
    error: null,
    durationMs: 25,
    ...overrides,
  };
}

function fileChangeItem(
  overrides: Partial<FileChangeItem> = {},
): FileChangeItem {
  return {
    id: "file-1",
    type: "fileChange",
    status: "completed",
    createdAt: BASE_TS,
    changes: [{ path: "src/app.ts", op: "update" }],
    grantRoot: "/repo",
    ...overrides,
  };
}

function todoItem(overrides: Partial<TodoListItem> = {}): TodoListItem {
  return {
    id: "todo-1",
    type: "todo-list",
    status: "completed",
    createdAt: BASE_TS,
    explanation: "plan",
    plan: [{ title: "Inspect", status: "completed" }],
    ...overrides,
  };
}

function subagentItem(overrides: Partial<SubagentItem> = {}): SubagentItem {
  return {
    id: "subagent-1",
    type: "subagent",
    status: "completed",
    createdAt: BASE_TS,
    subagentId: "researcher-a",
    role: "researcher",
    name: "Researcher",
    codename: "Spark-abc",
    avatar: "R",
    parentItemId: null,
    summary: "checked options",
    error: null,
    iterationCount: 2,
    filesTouched: ["notes.md"],
    ...overrides,
  };
}

function verificationItem(
  overrides: Partial<VerificationItem> = {},
): VerificationItem {
  return {
    id: "verify-1",
    type: "verification",
    status: "completed",
    createdAt: BASE_TS,
    command: "pnpm test",
    kind: "test",
    exitCode: 0,
    summary: "passed",
    stdoutTail: "ok",
    stderrTail: null,
    relatedFiles: ["src/app.ts"],
    relatedChangeItemIds: ["file-1"],
    ...overrides,
  };
}

function artifactItem(overrides: Partial<ArtifactItem> = {}): ArtifactItem {
  return {
    id: "artifact-1",
    type: "artifact",
    status: "completed",
    createdAt: BASE_TS,
    artifactId: "artifact-report",
    kind: "pdf",
    path: "reports/out.pdf",
    mimeType: "application/pdf",
    title: "Report",
    version: 1,
    createdByItemId: null,
    previewUrl: "/preview/report",
    renderStatus: "rendered",
    validationStatus: "passed",
    ...overrides,
  };
}

describe("liveToolEventsFromConversation", () => {
  it("maps realtime tool items into LiveToolEvents", () => {
    const conv = makeConversation([
      makeTurn([commandItem(), mcpItem(), fileChangeItem(), todoItem()]),
    ]);

    const events = liveToolEventsFromConversation(conv);

    expect(events.map((event) => event.name)).toEqual([
      "list_cwd",
      "mcp:read",
      "file_change",
      "todo_write",
    ]);
    expect(events[0]).toMatchObject({
      id: "cmd-1",
      status: "done",
      input: {
        path: ".",
        command: "list_cwd",
        tool: "list_cwd",
        cwd: "/repo",
        networkAccess: false,
      },
      output: "listed files",
    });
    expect(events[1]).toMatchObject({
      durationMs: 25,
      output: { ok: true },
    });
    expect(events[2]?.input).toMatchObject({
      changes: [{ path: "src/app.ts", op: "update" }],
      grantRoot: "/repo",
    });
    expect(events[3]?.input).toMatchObject({
      items: [{ content: "Inspect", status: "completed" }],
      explanation: "plan",
    });
  });

  it("surfaces MCP progress without changing completed result shape when absent", () => {
    const conv = makeConversation([
      makeTurn([
        mcpItem({
          progress: {
            label: "Reading workbook",
            status: "running",
            percent: 42,
            current: 21,
            total: 50,
            preview: { sheet: "Revenue" },
            updatedAt: BASE_TS,
          },
        }),
      ]),
    ]);

    const [event] = liveToolEventsFromConversation(conv);

    expect(event.input).toMatchObject({
      progress: {
        label: "Reading workbook",
        percent: 42,
        current: 21,
        total: 50,
      },
    });
    expect(event.output).toMatchObject({
      result: { ok: true },
      progress: {
        label: "Reading workbook",
        preview: { sheet: "Revenue" },
      },
    });
  });

  it("appends server-authored turn phases as the preferred todo_write event", () => {
    const turn: Turn = {
      ...makeTurn([commandItem()]),
      phases: [
        {
          id: "phase-1",
          index: 1,
          total: 2,
          title: "Phase 1: Inspect context",
          status: "done",
        },
        {
          id: "phase-2",
          index: 2,
          total: 2,
          title: "Phase 2: Patch reducer",
          status: "running",
          activeItemId: "cmd-1",
        },
      ],
      workspaceFocus: {
        itemId: "cmd-1",
        view: "terminal",
        title: "Running tests",
      },
      workbenchSnapshot: {
        schemaVersion: 2,
        version: 3,
        status: "running",
        phases: [
          {
            id: "phase-1",
            index: 1,
            total: 2,
            title: "Phase 1: Inspect context",
            status: "done",
          },
          {
            id: "phase-2",
            index: 2,
            total: 2,
            title: "Phase 2: Patch reducer",
            status: "running",
            activeItemId: "cmd-1",
          },
        ],
        currentPhaseId: "phase-2",
        currentItemId: "cmd-1",
        workspaceFocus: {
          itemId: "cmd-1",
          view: "terminal",
          title: "Running tests",
        },
        updatedAt: "2026-01-01T00:00:00.000Z",
      },
    };

    const events = liveToolEventsFromLastTurn(makeConversation([turn]));
    const phaseEvent = events.at(-1);

    expect(phaseEvent?.id).toBe("server-phases:turn-1");
    expect(phaseEvent?.name).toBe("todo_write");
    expect(phaseEvent?.status).toBe("running");
    expect(phaseEvent?.input).toMatchObject({
      source: "turn.phases",
      workbenchSnapshot: { version: 3 },
      workspaceFocus: { itemId: "cmd-1", view: "terminal" },
      items: [
        { content: "Phase 1: Inspect context", status: "completed" },
        {
          content: "Phase 2: Patch reducer",
          status: "in_progress",
          activeItemId: "cmd-1",
        },
      ],
    });
  });

  it("maps first-class subagent, verification, and artifact items into LiveToolEvents", () => {
    const conv = makeConversation([
      makeTurn([
        subagentItem({ parentItemId: "parent-call-1" }),
        verificationItem(),
        artifactItem(),
      ]),
    ]);

    const events = liveToolEventsFromConversation(conv);

    expect(events.map((event) => event.name)).toEqual([
      "subagent",
      "verification:test",
      "artifact",
    ]);
    expect(events[0]).toMatchObject({
      agentId: "researcher-a",
      subAgentRole: "researcher",
      subagentCodename: "Spark-abc",
      parentToolUseId: "parent-call-1",
      iterationCount: 2,
      filesTouched: ["notes.md"],
    });
    expect(events[1]).toMatchObject({
      output: { exitCode: 0, summary: "passed" },
    });
    expect(events[2]).toMatchObject({
      input: {
        path: "reports/out.pdf",
        kind: "pdf",
        workspaceFocus: {
          itemId: "artifact-1",
          view: "artifact",
          title: "Report",
          subtitle: "reports/out.pdf",
          previewUrl: "/preview/report",
        },
      },
      output: { renderStatus: "rendered", validationStatus: "passed" },
    });
  });

  it("preserves running and failed statuses", () => {
    const conv = makeConversation([
      makeTurn([
        commandItem({ id: "running", status: "inProgress" }),
        commandItem({
          id: "failed",
          status: "failed",
          aggregatedOutput: "boom",
        }),
        commandItem({ id: "declined", status: "declined" }),
      ]),
    ]);

    expect(
      liveToolEventsFromConversation(conv).map((event) => event.status),
    ).toEqual(["running", "error", "error"]);
  });

  it("returns only the latest turn for lastTurnToolEvents", () => {
    const conv = makeConversation([
      makeTurn([commandItem({ id: "old", command: "read_file" })], "turn-old"),
      makeTurn([commandItem({ id: "new", command: "web_search" })], "turn-new"),
    ]);

    expect(
      liveToolEventsFromConversation(conv).map((event) => event.id),
    ).toEqual(["old", "new"]);
    expect(liveToolEventsFromLastTurn(conv).map((event) => event.id)).toEqual([
      "new",
    ]);
  });

  it("surfaces pending approvals as waiting tool events", () => {
    const conv = makeConversationWithApproval([
      makeTurn([commandItem({ id: "old", command: "read_file" })]),
    ]);

    const allEvents = liveToolEventsFromConversation(conv);
    const lastTurnEvents = liveToolEventsFromLastTurn(conv);

    expect(allEvents.at(-1)).toMatchObject({
      id: "cmd-approval",
      name: "exec_shell",
      status: "waiting_approval",
      input: {
        requestId: 7,
        argsPreview: "rm -rf /tmp/demo",
      },
    });
    expect(lastTurnEvents.at(-1)?.status).toBe("waiting_approval");
  });

  it("translates a __subagent_spawned__ marker into a lifecycle=spawned event", () => {
    const conv = makeConversation([
      makeTurn([
        mcpItem({
          id: "spawn-1",
          status: "inProgress",
          tool: "__subagent_spawned__",
          server: "subagent",
          arguments: {
            agent_id: "researcher_a",
            role: "researcher",
            codename: "Spark-abc",
            avatar: "🔍",
            prompt_preview: "explore vendor X",
            parent_tool_use_id: "parent-call-1",
          },
          result: null,
          durationMs: null,
        }),
      ]),
    ]);

    const events = liveToolEventsFromConversation(conv);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      id: "spawn-1",
      lifecycle: "spawned",
      status: "running",
      agentId: "researcher_a",
      subAgentRole: "researcher",
      subagentCodename: "Spark-abc",
      parentToolUseId: "parent-call-1",
      subagentAvatar: "🔍",
    });
  });

  it("translates a __subagent_finished__ marker into a lifecycle=finished event", () => {
    const conv = makeConversation([
      makeTurn([
        mcpItem({
          id: "finish-1",
          status: "completed",
          tool: "__subagent_finished__",
          server: "subagent",
          arguments: {},
          result: {
            agent_id: "researcher_a",
            role: "researcher",
            codename: "Spark-abc",
            avatar: "🔍",
            parent_tool_use_id: "parent-call-1",
            ok: true,
            duration_s: 1.5,
            iteration_count: 3,
            files_touched: ["a.py", "b.py"],
          },
          durationMs: 1500,
        }),
      ]),
    ]);

    const events = liveToolEventsFromConversation(conv);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      id: "finish-1",
      lifecycle: "finished",
      status: "done",
      durationMs: 1500,
      agentId: "researcher_a",
      subAgentRole: "researcher",
      subagentCodename: "Spark-abc",
      subagentAvatar: "🔍",
      parentToolUseId: "parent-call-1",
      iterationCount: 3,
      filesTouched: ["a.py", "b.py"],
    });
  });

  it("marks a __subagent_finished__ event as error when ok is false", () => {
    const conv = makeConversation([
      makeTurn([
        mcpItem({
          id: "finish-err",
          status: "completed",
          tool: "__subagent_finished__",
          server: "subagent",
          arguments: {},
          result: {
            agent_id: "researcher_a",
            role: "researcher",
            codename: "Spark-abc",
            avatar: "🔍",
            ok: false,
            duration_s: 0.5,
            iteration_count: 1,
            files_touched: [],
            error: "boom",
          },
          durationMs: 500,
        }),
      ]),
    ]);

    const events = liveToolEventsFromConversation(conv);
    expect(events[0]?.lifecycle).toBe("finished");
    expect(events[0]?.status).toBe("error");
  });
});

describe("useThreadStreamRealtime permissions", () => {
  function mockRealtime(startTurn = vi.fn().mockResolvedValue(undefined)) {
    vi.mocked(useRealtimeThread).mockReturnValue({
      state: makeConversation([]),
      connected: true,
      startTurn,
      resolveApproval: vi.fn(),
      resume: vi.fn().mockResolvedValue(undefined),
      interrupt: vi.fn().mockResolvedValue(undefined),
      compact: vi.fn().mockResolvedValue({ compacted: false }),
      decideHunk: vi.fn().mockResolvedValue(undefined),
    });
    return startTurn;
  }

  it("reports the server-created thread id when starting from the new-thread route", async () => {
    const onStart = vi.fn();
    const liveTurn: Turn = {
      ...makeTurn([], "turn-live"),
      threadId: "server-thread-1",
      status: "inProgress",
      completedAt: null,
    };
    vi.mocked(useRealtimeThread).mockReturnValue({
      state: makeConversation([liveTurn]),
      connected: true,
      startTurn: vi.fn().mockResolvedValue(undefined),
      resolveApproval: vi.fn(),
      resume: vi.fn().mockResolvedValue(undefined),
      interrupt: vi.fn().mockResolvedValue(undefined),
      compact: vi.fn().mockResolvedValue({ compacted: false }),
      decideHunk: vi.fn().mockResolvedValue(undefined),
    });

    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "new",
        onStart,
      }),
    );

    expect(result.current[0].threadId).toBe("server-thread-1");
    await waitFor(() => expect(onStart).toHaveBeenCalledWith("server-thread-1"));
    expect(onStart).not.toHaveBeenCalledWith("new");
  });

  it("sends default sandbox permissions by default", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "hello", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    expect(payload).toEqual(
      expect.objectContaining({
        approvalPolicy: "on-request",
        sandboxPolicy: {
          type: "workspaceWrite",
          networkAccess: true,
        },
        metadata: {
          context: expect.objectContaining({
            permission_mode: "default",
            sandbox_mode: "sandbox",
            execution_environment: "sandbox",
          }),
        },
      }),
    );
    expect(payload).not.toHaveProperty("planningMode");
  });

  it("allows attachment-only turns so pasted screenshots still reach the model", async () => {
    const startTurn = mockRealtime();
    const file = new File(["img"], "screen.png", { type: "image/png" });
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "new",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("new", {
        text: "",
        files: [
          {
            type: "file",
            mediaType: "image/png",
            filename: "screen.png",
            url: "data:image/png;base64,AAAA",
            file,
          },
        ],
      });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        input: "",
        attachments: [
          expect.objectContaining({
            filename: "screen.png",
            mediaType: "image/png",
            data_url: expect.stringMatching(/^data:image\/png;base64,/),
          }),
        ],
      }),
    );
  });

  it("dispatches failed image attachments back to the composer on send error", async () => {
    const startTurn = vi.fn().mockRejectedValue(new Error("socket dropped"));
    mockRealtime(startTurn);
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    const file = new File(["img"], "screen.png", { type: "image/png" });
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", {
        text: "",
        files: [
          {
            type: "file",
            mediaType: "image/png",
            filename: "screen.png",
            url: "data:image/png;base64,AAAA",
            file,
          },
        ],
      });
    });

    await waitFor(() =>
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "octopus:send-failed",
          detail: expect.objectContaining({
            threadId: "th-test",
            text: "",
            images: [expect.objectContaining({ name: "screen.png" })],
          }),
        }),
      ),
    );
    dispatchSpy.mockRestore();
  });

  it("restores the original Codex marker text when a send fails", async () => {
    const startTurn = vi.fn().mockRejectedValue(new Error("socket dropped"));
    mockRealtime(startTurn);
    const dispatchSpy = vi.spyOn(window, "dispatchEvent");
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", {
        text: "/codex goal\nFinish the hardening pass",
        files: [],
      });
    });

    await waitFor(() =>
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "octopus:send-failed",
          detail: expect.objectContaining({
            threadId: "th-test",
            text: "/codex goal\nFinish the hardening pass",
          }),
        }),
      ),
    );
    dispatchSpy.mockRestore();
  });

  it("marks first-screen realtime turns as coding-agent turns", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "fix the tests", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: {
          context: expect.objectContaining({
            mode: "code",
            capability_mode: "code",
            code_mode: "solo",
            permission_mode: "default",
            sandbox_mode: "sandbox",
            execution_environment: "sandbox",
          }),
        },
      }),
    );
  });

  it("does not add code capability defaults to explicit chat/react turns", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: {
          mode: "react",
          permission_mode: "default",
          personal_mode: "research",
        },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "summarize this topic", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    const context = (payload?.metadata as { context?: Record<string, unknown> })
      ?.context;
    expect(context).toMatchObject({
      mode: "react",
      personal_mode: "research",
      permission_mode: "default",
      sandbox_mode: "sandbox",
      execution_environment: "sandbox",
    });
    expect(context).not.toHaveProperty("capability_mode");
    expect(context).not.toHaveProperty("code_mode");
  });

  it("keeps team turns in team mode without stealth code capability defaults", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "team-thread",
        context: {
          mode: "team",
          permission_mode: "default",
          team_mode: "chat",
          workspace_path: "/repo",
        },
      }),
    );

    act(() => {
      result.current[1]("team-thread", { text: "ask the group", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    const context = (payload?.metadata as { context?: Record<string, unknown> })
      ?.context;
    expect(context).toMatchObject({
      mode: "team",
      team_mode: "chat",
      workspace_path: "/repo",
      permission_mode: "default",
    });
    expect(context).not.toHaveProperty("capability_mode");
    expect(context).not.toHaveProperty("code_mode");
  });

  it("passes collaborator cluster topology while staying on the current thread", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "chat-thread",
        context: {
          mode: "team",
          permission_mode: "default",
          team_mode: "cowork",
          serve_mesh: "0",
          topology_id: "cowork",
          agent_roster: [
            { agent_id: "general", display_name: "General", role: "tl" },
            { agent_id: "coder", display_name: "Coder", role: "member" },
          ],
        },
      }),
    );

    act(() => {
      result.current[1]("chat-thread", {
        text: "继续这个任务",
        files: [],
      });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    const context = (payload?.metadata as { context?: Record<string, unknown> })
      ?.context;
    expect(payload).toEqual(
      expect.objectContaining({
        topologyId: "cowork",
      }),
    );
    expect(context).toMatchObject({
      mode: "team",
      team_mode: "cowork",
      serve_mesh: "0",
      topology_id: "cowork",
      permission_mode: "default",
    });
    expect(context?.agent_roster).toHaveLength(2);
    expect(context).not.toHaveProperty("capability_mode");
    expect(context).not.toHaveProperty("code_mode");
  });

  it("adds code capability defaults to explicit project code turns", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "code-thread",
        context: {
          mode: "code",
          permission_mode: "default",
          workspace_path: "/repo",
        },
      }),
    );

    act(() => {
      result.current[1]("code-thread", { text: "fix the bug", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: {
          context: expect.objectContaining({
            mode: "code",
            workspace_path: "/repo",
            capability_mode: "code",
            code_mode: "solo",
          }),
        },
      }),
    );
  });

  it("turns composer Codex Plan marker into runtime metadata", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", {
        text: "/codex plan\nRefactor the router",
        files: [],
      });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        input: "Refactor the router",
        planningMode: true,
        metadata: {
          context: expect.objectContaining({
            codex_mode: "plan",
            completion_policy: "plan",
            mode_preset: "codex.plan",
            workflow_preset: "codex.plan",
          }),
        },
      }),
    );
  });

  it("turns composer Codex Goal marker into bounded goal metadata", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "default" },
      }),
    );

    act(() => {
      result.current[1]("th-test", {
        text: "/codex goal\nFinish the hardening pass",
        files: [],
      });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    const context = (payload?.metadata as { context?: Record<string, unknown> })
      ?.context;
    expect(payload).toEqual(
      expect.objectContaining({
        input: "Finish the hardening pass",
      }),
    );
    expect(payload).not.toHaveProperty("planningMode");
    expect(context).toMatchObject({
      codex_mode: "goal",
      completion_policy: "goal",
      goal_mode: true,
      mode_preset: "codex.goal",
      workflow_preset: "codex.goal",
    });
  });

  it("sends selected reasoning effort as top-level turn effort", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: {
          permission_mode: "default",
          reasoning_effort: "xhigh",
        },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "solve the hard bit", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        effort: "xhigh",
        metadata: {
          context: expect.objectContaining({
            reasoning_effort: "xhigh",
          }),
        },
      }),
    );
  });

  it("maps legacy full access to bypassPermissions", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "full" },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "hello", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    const payload = startTurn.mock.calls[0]?.[0];
    expect(payload).toEqual(
      expect.objectContaining({
        approvalPolicy: "never",
        sandboxPolicy: {
          type: "dangerFullAccess",
          networkAccess: true,
        },
        metadata: {
          context: expect.objectContaining({
            permission_mode: "bypassPermissions",
            sandbox_mode: "full",
            execution_environment: "local",
          }),
        },
      }),
    );
    expect(payload).not.toHaveProperty("planningMode");
  });

  it("sends plan permission mode as planningMode without auto approval", async () => {
    const startTurn = mockRealtime();
    const { result } = renderHook(() =>
      useThreadStreamRealtime({
        threadId: "th-test",
        context: { permission_mode: "plan" },
      }),
    );

    act(() => {
      result.current[1]("th-test", { text: "make a plan first", files: [] });
    });

    await waitFor(() => expect(startTurn).toHaveBeenCalled());
    expect(startTurn).toHaveBeenCalledWith(
      expect.objectContaining({
        approvalPolicy: "on-request",
        sandboxPolicy: {
          type: "workspaceWrite",
          networkAccess: true,
        },
        planningMode: true,
        metadata: {
          context: expect.objectContaining({
            permission_mode: "plan",
            sandbox_mode: "sandbox",
            execution_environment: "sandbox",
          }),
        },
      }),
    );
  });
});
