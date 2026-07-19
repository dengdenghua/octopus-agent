// Reducer is the heart of the realtime client. Tests target it directly:
// no React, no WebSocket, no async — just pure transitions.
//
// Coverage:
//   * Turn upsert (started + completed by id, idempotent)
//   * Item lifecycle (started → delta accumulation → completed replace)
//   * Out-of-order delta (item not yet known → no crash, no-op)
//   * Out-of-order item/started after item/completed → no regression
//   * Token usage update preserves turns
//   * Error event surfaces an error item on the active turn
import { describe, expect, it } from "vitest";

import { emptyConversation, type Conversation, type Turn } from "./items";
import { reduce, type ConversationEvent } from "./reducer";

const T0_ISO = "2026-01-01T00:00:00.000Z";

function blankTurn(id: string, threadId: string): Turn {
  return {
    id,
    threadId,
    status: "inProgress",
    startedAt: T0_ISO,
    completedAt: null,
    items: [],
    error: null,
  };
}

function apply(
  state: Conversation,
  ...events: ConversationEvent[]
): Conversation {
  return events.reduce((s, e) => reduce(s, e).next, state);
}

describe("reducer", () => {
  it("turn/started inserts and turn/completed replaces", () => {
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "turn/completed",
        params: {
          threadId: "th",
          turn: {
            ...blankTurn("trn-1", "th"),
            status: "completed",
            completedAt: T0_ISO,
          },
        },
      },
    );
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0].status).toBe("completed");
  });

  it("turn/completed closes in-progress items missing from final payload", () => {
    const withItem = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "itm-c",
            type: "commandExecution",
            status: "inProgress",
            createdAt: T0_ISO,
            command: "npm test",
            cwd: null,
            aggregatedOutput: "",
            exitCode: null,
            processId: null,
            networkAccess: false,
          },
        },
      },
    );
    const result = reduce(withItem, {
      method: "turn/completed",
      params: {
        threadId: "th",
        turn: {
          ...blankTurn("trn-1", "th"),
          status: "completed",
          completedAt: T0_ISO,
        },
      },
    });

    expect(result.changedItemIds).toEqual(["itm-c"]);
    expect(result.next.turns[0].items[0].status).toBe("completed");
  });

  it("turn/completed marks dangling items interrupted when turn is interrupted", () => {
    const withItem = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "itm-a",
            type: "agentMessage",
            status: "inProgress",
            createdAt: T0_ISO,
            text: "partial",
          },
        },
      },
    );
    const state = reduce(withItem, {
      method: "turn/completed",
      params: {
        threadId: "th",
        turn: {
          ...blankTurn("trn-1", "th"),
          status: "interrupted",
          completedAt: T0_ISO,
        },
      },
    }).next;

    expect(state.turns[0].items[0].status).toBe("interrupted");
  });

  it("repairs a legacy completed public draft in an interrupted snapshot", () => {
    const withTurn = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("trn-1", "th") },
    });
    const state = reduce(withTurn, {
      method: "turn/completed",
      params: {
        threadId: "th",
        turn: {
          ...blankTurn("trn-1", "th"),
          status: "interrupted",
          completedAt: T0_ISO,
          items: [
            {
              id: "draft-answer",
              type: "agentMessage",
              status: "completed",
              createdAt: T0_ISO,
              text: 'str = ""',
              messageKind: "commentary",
            },
          ],
        },
      },
    }).next;

    expect(state.turns[0].items[0].status).toBe("interrupted");
  });

  it("turn/interrupted optimistically closes the active turn", () => {
    const withItem = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "itm-a",
            type: "reasoning",
            status: "inProgress",
            createdAt: T0_ISO,
            content: "thinking",
          },
        },
      },
    );
    const state = reduce(withItem, {
      method: "turn/interrupted",
      params: { threadId: "th", turnId: "trn-1", completedAt: T0_ISO },
    }).next;

    expect(state.turns[0].status).toBe("interrupted");
    expect(state.turns[0].completedAt).toBe(T0_ISO);
    expect(state.turns[0].items[0].status).toBe("interrupted");
  });

  it("turn/interrupted invalidates only the last prose item, not completed evidence", () => {
    const withItems = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "tool-1",
            type: "commandExecution",
            status: "completed",
            createdAt: T0_ISO,
            command: "read_file",
            cwd: null,
            aggregatedOutput: "source",
            exitCode: 0,
            processId: null,
            networkAccess: false,
          },
        },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "draft-answer",
            type: "agentMessage",
            status: "completed",
            createdAt: T0_ISO,
            text: "unfinished",
          },
        },
      },
    );
    const state = reduce(withItems, {
      method: "turn/interrupted",
      params: { threadId: "th", turnId: "trn-1", completedAt: T0_ISO },
    }).next;

    expect(
      state.turns[0].items.find((item) => item.id === "tool-1")?.status,
    ).toBe("completed");
    expect(
      state.turns[0].items.find((item) => item.id === "draft-answer")?.status,
    ).toBe("interrupted");
  });

  it("item/started inserts, item delta accumulates, item/completed replaces", () => {
    const turn = blankTurn("trn-1", "th");
    const state = apply(
      emptyConversation("th"),
      { method: "turn/started", params: { threadId: "th", turn } },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "itm-a",
            type: "agentMessage",
            status: "inProgress",
            createdAt: T0_ISO,
            text: "",
          },
        },
      },
      {
        method: "item/agentMessage/delta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-a",
          delta: "hello ",
        },
      },
      {
        method: "item/agentMessage/delta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-a",
          delta: "world",
        },
      },
      {
        method: "item/completed",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            id: "itm-a",
            type: "agentMessage",
            status: "completed",
            createdAt: T0_ISO,
            text: "hello world",
          },
        },
      },
    );
    const item = state.turns[0].items.find((i) => i.id === "itm-a");
    expect(item?.type).toBe("agentMessage");
    if (item?.type === "agentMessage") {
      expect(item.text).toBe("hello world");
      expect(item.status).toBe("completed");
    }
  });

  it("passes first-class control/artifact items through lifecycle updates", () => {
    const artifact = {
      id: "itm-art",
      type: "artifact" as const,
      status: "inProgress" as const,
      createdAt: T0_ISO,
      artifactId: "art-1",
      kind: "pdf" as const,
      path: "reports/out.pdf",
      mimeType: "application/pdf",
      title: "Report",
      version: 1,
      createdByItemId: null,
      previewUrl: null,
      renderStatus: "rendering" as const,
      validationStatus: "pending" as const,
    };
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: { threadId: "th", turnId: "trn-1", item: artifact },
      },
      {
        method: "item/completed",
        params: {
          threadId: "th",
          turnId: "trn-1",
          item: {
            ...artifact,
            status: "completed",
            renderStatus: "rendered",
            validationStatus: "passed",
          },
        },
      },
    );
    const item = state.turns[0].items[0];
    expect(item.type).toBe("artifact");
    if (item.type === "artifact") {
      expect(item.renderStatus).toBe("rendered");
      expect(item.validationStatus).toBe("passed");
    }
  });

  it("delta for unknown item is a no-op (idempotent under loss)", () => {
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/agentMessage/delta",
        params: { threadId: "th", turnId: "trn-1", itemId: "lost", delta: "x" },
      },
    );
    expect(state.turns[0].items).toHaveLength(0);
  });

  it("item/started arriving after item/completed does not regress", () => {
    const completed = {
      id: "itm-x",
      type: "agentMessage" as const,
      status: "completed" as const,
      createdAt: T0_ISO,
      text: "final",
    };
    const inflight = { ...completed, status: "inProgress" as const, text: "" };
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/completed",
        params: { threadId: "th", turnId: "trn-1", item: completed },
      },
      {
        method: "item/started",
        params: { threadId: "th", turnId: "trn-1", item: inflight },
      },
    );
    const item = state.turns[0].items[0];
    expect(item.status).toBe("completed");
    if (item.type === "agentMessage") expect(item.text).toBe("final");
  });

  it("orders late lifecycle snapshots by server timeline sequence", () => {
    const turn = blankTurn("trn-1", "th");
    const state = apply(
      emptyConversation("th"),
      { method: "turn/started", params: { threadId: "th", turn } },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: turn.id,
          item: {
            id: "answer",
            type: "agentMessage",
            status: "inProgress",
            createdAt: T0_ISO,
            text: "",
            timelineSequence: 3,
            parentItemId: "tool",
          },
        },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: turn.id,
          item: {
            id: "commentary",
            type: "agentMessage",
            status: "inProgress",
            createdAt: T0_ISO,
            text: "Checking the implementation.",
            messageKind: "commentary",
            timelineSequence: 1,
          },
        },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: turn.id,
          item: {
            id: "tool",
            type: "commandExecution",
            status: "inProgress",
            createdAt: T0_ISO,
            command: "read_file",
            cwd: null,
            aggregatedOutput: "",
            exitCode: null,
            processId: null,
            networkAccess: false,
            timelineSequence: 2,
            parentItemId: "commentary",
          },
        },
      },
    );

    expect(state.turns[0].items.map((item) => item.id)).toEqual([
      "commentary",
      "tool",
      "answer",
    ]);
  });

  it("keeps legacy user slots fixed while ordering coordinated replay items", () => {
    const user = {
      id: "user",
      type: "userMessage" as const,
      status: "completed" as const,
      createdAt: T0_ISO,
      text: "go",
    };
    const answer = {
      id: "answer",
      type: "agentMessage" as const,
      status: "completed" as const,
      createdAt: T0_ISO,
      text: "done",
      timelineSequence: 2,
    };
    const commentary = {
      id: "commentary",
      type: "agentMessage" as const,
      status: "completed" as const,
      createdAt: T0_ISO,
      text: "working",
      messageKind: "commentary" as const,
      timelineSequence: 1,
    };
    const state = apply(emptyConversation("th"), {
      method: "turn/started",
      params: {
        threadId: "th",
        turn: {
          ...blankTurn("trn-1", "th"),
          items: [user, answer, commentary],
        },
      },
    });

    expect(state.turns[0].items.map((item) => item.id)).toEqual([
      "user",
      "commentary",
      "answer",
    ]);
  });

  it("reasoning delta accumulates onto reasoning content", () => {
    const reasoning = {
      id: "itm-r",
      type: "reasoning" as const,
      status: "inProgress" as const,
      createdAt: T0_ISO,
      summary: [],
      content: "",
    };
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: { threadId: "th", turnId: "trn-1", item: reasoning },
      },
      {
        method: "item/reasoning/textDelta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-r",
          delta: "step one. ",
          contentIndex: 0,
        },
      },
      {
        method: "item/reasoning/textDelta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-r",
          delta: "step two.",
          contentIndex: 0,
        },
      },
    );
    const item = state.turns[0].items[0];
    if (item.type === "reasoning") {
      expect(item.content).toBe("step one. step two.");
    } else {
      expect.fail("expected a reasoning item");
    }
  });

  it("commandExecution outputDelta accumulates aggregatedOutput", () => {
    const cmd = {
      id: "itm-c",
      type: "commandExecution" as const,
      status: "inProgress" as const,
      createdAt: T0_ISO,
      command: "ls",
      cwd: null,
      aggregatedOutput: "",
      exitCode: null,
      processId: null,
      networkAccess: false,
    };
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "item/started",
        params: { threadId: "th", turnId: "trn-1", item: cmd },
      },
      {
        method: "item/commandExecution/outputDelta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-c",
          delta: "line1\n",
        },
      },
      {
        method: "item/commandExecution/outputDelta",
        params: {
          threadId: "th",
          turnId: "trn-1",
          itemId: "itm-c",
          delta: "line2\n",
        },
      },
    );
    const item = state.turns[0].items[0];
    if (item.type === "commandExecution") {
      expect(item.aggregatedOutput).toBe("line1\nline2\n");
    } else {
      expect.fail("expected commandExecution");
    }
  });

  it("token usage update preserves turns and items", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("trn-1", "th") },
    });
    const after = reduce(before, {
      method: "thread/tokenUsage/updated",
      params: { threadId: "th", tokenUsage: { totalTokens: 42 } },
    }).next;
    expect(after.turns).toBe(before.turns);
    expect(after.tokenUsage).toEqual({ totalTokens: 42 });
  });

  it("error event surfaces an error item on the active turn", () => {
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("trn-1", "th") },
      },
      {
        method: "error",
        params: {
          threadId: "th",
          turnId: "trn-1",
          error: { message: "boom" },
          willRetry: false,
        },
      },
    );
    const errors = state.turns[0].items.filter((i) => i.type === "error");
    expect(errors).toHaveLength(1);
    if (errors[0].type === "error") {
      expect(errors[0].message).toBe("boom");
    }
  });

  it("error item ids stay unique within the same millisecond", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("trn-1", "th") },
    });
    const originalNow = Date.now;
    Date.now = () => 123;
    try {
      const state = apply(
        before,
        {
          method: "error",
          params: {
            threadId: "th",
            turnId: "trn-1",
            error: { message: "one" },
            willRetry: false,
          },
        },
        {
          method: "error",
          params: {
            threadId: "th",
            turnId: "trn-1",
            error: { message: "two" },
            willRetry: false,
          },
        },
      );
      const errors = state.turns[0].items.filter((i) => i.type === "error");
      expect(errors).toHaveLength(2);
      expect(new Set(errors.map((i) => i.id)).size).toBe(2);
    } finally {
      Date.now = originalNow;
    }
  });

  it("unknown method is a no-op", () => {
    const before = emptyConversation("th");
    // Cast through ``unknown`` — the goal is to prove the closed-set
    // switch silently ignores anything outside the union.
    const after = reduce(before, {
      method: "future/event",
      params: {},
    } as unknown as ConversationEvent).next;
    expect(after).toBe(before);
  });

  it("hunk decision marks only the targeted hunk on the target fileChange item", () => {
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("tn", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "tn",
          item: {
            id: "it-fc",
            type: "fileChange",
            status: "inProgress",
            createdAt: T0_ISO,
            changes: [
              {
                path: "foo.py",
                op: "update",
                hunks: [
                  {
                    id: "h1",
                    oldStart: 1,
                    oldLines: 1,
                    newStart: 1,
                    newLines: 1,
                    body: "-a\n+b\n",
                    decision: "pending",
                  },
                  {
                    id: "h2",
                    oldStart: 5,
                    oldLines: 1,
                    newStart: 5,
                    newLines: 1,
                    body: "-c\n+d\n",
                    decision: "pending",
                  },
                ],
              },
            ],
            grantRoot: null,
          },
        },
      },
      {
        method: "item/fileChange/hunkDecision",
        params: {
          threadId: "th",
          turnId: "tn",
          itemId: "it-fc",
          hunkId: "h1",
          decision: "accepted",
          path: "foo.py",
        },
      },
    );
    const fc = state.turns[0].items[0];
    if (fc.type !== "fileChange") throw new Error("expected fileChange");
    const hunks = fc.changes[0].hunks!;
    expect(hunks[0].decision).toBe("accepted");
    expect(hunks[1].decision).toBe("pending");
  });

  it("hunk decision on unknown item is a no-op", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("tn", "th") },
    });
    const after = reduce(before, {
      method: "item/fileChange/hunkDecision",
      params: {
        threadId: "th",
        turnId: "tn",
        itemId: "missing",
        hunkId: "h1",
        decision: "accepted",
        path: "foo.py",
      },
    } as ConversationEvent).next;
    expect(after).toBe(before);
  });

  it("turn/plan/updated stores server-authored phases and workspace focus", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("tn", "th") },
    });
    const result = reduce(before, {
      method: "turn/plan/updated",
      params: {
        threadId: "th",
        turnId: "tn",
        phases: [
          {
            id: "phase-1",
            index: 1,
            total: 2,
            title: "Inspect context",
            status: "done",
          },
          {
            id: "phase-2",
            index: 2,
            total: 2,
            title: "Patch reducer",
            status: "running",
            activeItemId: "tool-1",
          },
        ],
        workspaceFocus: {
          itemId: "tool-1",
          view: "terminal",
          title: "Running tests",
          subtitle: "pnpm test",
        },
        workbenchSnapshot: {
          schemaVersion: 2,
          version: 1,
          status: "running",
          phases: [
            {
              id: "phase-1",
              index: 1,
              total: 2,
              title: "Inspect context",
              status: "done",
            },
            {
              id: "phase-2",
              index: 2,
              total: 2,
              title: "Patch reducer",
              status: "running",
              activeItemId: "tool-1",
            },
          ],
          currentPhaseId: "phase-2",
          currentItemId: "tool-1",
          workspaceFocus: {
            itemId: "tool-1",
            view: "terminal",
            title: "Running tests",
          },
          updatedAt: T0_ISO,
        },
      },
    });

    expect(result.changedTurnIds).toEqual(["tn"]);
    expect(result.changedItemIds).toEqual([]);
    expect(result.next.turns[0].phases?.map((phase) => phase.title)).toEqual([
      "Inspect context",
      "Patch reducer",
    ]);
    expect(result.next.turns[0].workspaceFocus).toMatchObject({
      itemId: "tool-1",
      view: "terminal",
    });
    expect(result.next.turns[0].workbenchSnapshot).toMatchObject({
      version: 1,
      currentPhaseId: "phase-2",
      currentItemId: "tool-1",
    });
  });

  it("workbench/snapshot stores the current frame and mirrors phases/focus", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("tn", "th") },
    });
    const result = reduce(before, {
      method: "workbench/snapshot",
      params: {
        threadId: "th",
        turnId: "tn",
        snapshot: {
          schemaVersion: 2,
          version: 2,
          status: "running",
          phases: [
            {
              id: "phase-a",
              index: 1,
              total: 1,
              title: "Browse docs",
              status: "running",
              activeItemId: "browser-1",
            },
          ],
          currentPhaseId: "phase-a",
          currentItemId: "browser-1",
          workspaceFocus: {
            itemId: "browser-1",
            view: "browser",
            title: "Browser",
          },
          updatedAt: T0_ISO,
        },
      },
    });

    expect(result.changedTurnIds).toEqual(["tn"]);
    expect(result.changedItemIds).toEqual([]);
    expect(result.next.turns[0].workbenchSnapshot?.version).toBe(2);
    expect(result.next.turns[0].phases?.[0]?.title).toBe("Browse docs");
    expect(result.next.turns[0].workspaceFocus?.view).toBe("browser");
  });

  it("item/mcpToolCall/progress updates the matching MCP item", () => {
    const before = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("tn", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "tn",
          item: {
            id: "mcp-1",
            type: "mcpToolCall",
            status: "inProgress",
            createdAt: T0_ISO,
            server: "browser",
            tool: "screenshot",
            arguments: {},
            result: null,
            error: null,
            durationMs: null,
          },
        },
      },
    );
    const result = reduce(before, {
      method: "item/mcpToolCall/progress",
      params: {
        threadId: "th",
        turnId: "tn",
        itemId: "mcp-1",
        progress: {
          label: "Capturing screenshot",
          status: "running",
          percent: 40,
          updatedAt: T0_ISO,
        },
        workspaceFocus: {
          itemId: "mcp-1",
          view: "browser",
          title: "Browser screenshot",
        },
      },
    });

    const item = result.next.turns[0].items[0];
    if (item.type !== "mcpToolCall") throw new Error("expected mcpToolCall");
    expect(result.changedItemIds).toEqual(["mcp-1"]);
    expect(item.progress).toMatchObject({
      label: "Capturing screenshot",
      percent: 40,
    });
    expect(result.next.turns[0].workspaceFocus?.view).toBe("browser");
  });

  it("item/fileChange/hunkDelta appends and replaces hunks idempotently", () => {
    const before = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("tn", "th") },
      },
      {
        method: "item/started",
        params: {
          threadId: "th",
          turnId: "tn",
          item: {
            id: "fc-1",
            type: "fileChange",
            status: "inProgress",
            createdAt: T0_ISO,
            changes: [],
            grantRoot: null,
          },
        },
      },
      {
        method: "item/fileChange/hunkDelta",
        params: {
          threadId: "th",
          turnId: "tn",
          itemId: "fc-1",
          path: "src/app.ts",
          op: "update",
          hunk: {
            id: "h1",
            oldStart: 1,
            oldLines: 1,
            newStart: 1,
            newLines: 1,
            body: "-old\n+new\n",
            decision: "pending",
          },
        },
      },
    );
    const after = reduce(before, {
      method: "item/fileChange/hunkDelta",
      params: {
        threadId: "th",
        turnId: "tn",
        itemId: "fc-1",
        path: "src/app.ts",
        op: "update",
        hunk: {
          id: "h1",
          oldStart: 1,
          oldLines: 1,
          newStart: 1,
          newLines: 2,
          body: "-old\n+new\n+again\n",
          decision: "pending",
        },
        workspaceFocus: {
          itemId: "fc-1",
          view: "diff",
          title: "Editing src/app.ts",
        },
      },
    }).next;

    const item = after.turns[0].items[0];
    if (item.type !== "fileChange") throw new Error("expected fileChange");
    expect(item.changes).toHaveLength(1);
    expect(item.changes[0].hunks).toHaveLength(1);
    expect(item.changes[0].hunks?.[0]?.newLines).toBe(2);
    expect(after.turns[0].workspaceFocus?.view).toBe("diff");
  });

  it("turn/metaSkill/hint attaches the hint to the matching turn", () => {
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("tn", "th") },
      },
      {
        method: "turn/metaSkill/hint",
        params: {
          threadId: "th",
          turnId: "tn",
          name: "bug-hunt",
          description: "安全漏洞猎手",
          kind: "skill_cluster",
          affinity: ["security", "code", "audit"],
          stepCount: 5,
        },
      },
    );
    expect(state.turns[0].metaSkillHint).toEqual({
      name: "bug-hunt",
      description: "安全漏洞猎手",
      kind: "skill_cluster",
      affinity: ["security", "code", "audit"],
      stepCount: 5,
    });
  });

  it("turn/metaSkill/hint for an unknown turn is a no-op", () => {
    // Race: the hint can arrive before turn/started in pathological
    // network ordering. Reducer must drop it silently rather than
    // creating a phantom turn.
    const before = apply(emptyConversation("th"));
    const result = reduce(before, {
      method: "turn/metaSkill/hint",
      params: {
        threadId: "th",
        turnId: "nope",
        name: "bug-hunt",
        description: "x",
        kind: "skill_cluster",
        affinity: [],
        stepCount: 1,
      },
    });
    expect(result.next).toBe(before);
    expect(result.changedTurnIds).toEqual([]);
  });

  it("turn/grounding attaches consulted sources to the turn", () => {
    const sources = [
      {
        kind: "doc" as const,
        title: "Hemolymph",
        path: "23-memory/hemolymph.md",
      },
      {
        kind: "source" as const,
        title: "react_loop.py",
        path: "runtime/react_loop.py:501",
      },
    ];
    const state = apply(
      emptyConversation("th"),
      {
        method: "turn/started",
        params: { threadId: "th", turn: blankTurn("tn", "th") },
      },
      {
        method: "turn/grounding",
        params: { threadId: "th", turnId: "tn", sources },
      },
    );
    expect(state.turns[0].grounding).toEqual(sources);
  });

  it("turn/grounding with empty sources or unknown turn is a no-op", () => {
    const before = apply(emptyConversation("th"), {
      method: "turn/started",
      params: { threadId: "th", turn: blankTurn("tn", "th") },
    });
    // empty list → dropped
    const empty = reduce(before, {
      method: "turn/grounding",
      params: { threadId: "th", turnId: "tn", sources: [] },
    });
    expect(empty.next).toBe(before);
    // unknown turn (race before turn/started) → dropped silently
    const unknown = reduce(before, {
      method: "turn/grounding",
      params: {
        threadId: "th",
        turnId: "nope",
        sources: [{ kind: "doc", title: "X", path: "x.md" }],
      },
    });
    expect(unknown.next).toBe(before);
    expect(unknown.changedTurnIds).toEqual([]);
  });
});
