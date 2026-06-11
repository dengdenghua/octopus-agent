import { describe, expect, it } from "vitest";

import type {
  AgentMessageItem,
  ArtifactItem,
  CommandExecutionItem,
  Conversation,
  ErrorItem,
  FileChangeItem,
  McpToolCallItem,
  PlanItem,
  ReasoningItem,
  TodoListItem,
  Turn,
  UserMessageItem,
  VerificationItem,
} from "@/core/realtime/items";

import {
  conversationIsLoading,
  conversationLastError,
  conversationStreamingMessage,
  conversationToAgentThreadState,
  splitReactTrace,
} from "./realtime-adapter";

// ───────────────────────────────────────────────────────────────
// Builders
// ───────────────────────────────────────────────────────────────

function makeConv(turns: Turn[]): Conversation {
  return {
    threadId: "th-test",
    turns,
    pendingApprovals: [],
    tokenUsage: null,
    resumeState: "resumed",
  };
}

function makeTurn(items: Turn["items"], status: Turn["status"] = "completed"): Turn {
  return {
    id: "t1",
    threadId: "th-test",
    status,
    startedAt: "2026-05-09T00:00:00Z",
    completedAt: status === "completed" ? "2026-05-09T00:00:01Z" : null,
    items,
    error: null,
  };
}

const userMsg = (text: string, id = "u1"): UserMessageItem => ({
  id,
  type: "userMessage",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  text,
});

const agentMsg = (text: string, id = "a1"): AgentMessageItem => ({
  id,
  type: "agentMessage",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  text,
});

const reasoning = (content: string, id = "r1"): ReasoningItem => ({
  id,
  type: "reasoning",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  summary: [],
  content,
});

const planItem = (text: string, id = "p1"): PlanItem => ({
  id,
  type: "plan",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  text,
});

const cmd = (
  command: string,
  id = "c1",
  overrides: Partial<CommandExecutionItem> = {},
): CommandExecutionItem => ({
  id,
  type: "commandExecution",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  command,
  cwd: "/tmp",
  aggregatedOutput: "ok\n",
  exitCode: 0,
  processId: "pid-1",
  networkAccess: false,
  ...overrides,
});

const mcp = (server: string, tool: string, id = "m1"): McpToolCallItem => ({
  id,
  type: "mcpToolCall",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  server,
  tool,
  arguments: { x: 1 },
  result: null,
  error: null,
  durationMs: 12,
});

const fileChange = (paths: string[], id = "f1"): FileChangeItem => ({
  id,
  type: "fileChange",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  changes: paths.map((p) => ({ path: p, op: "update" as const })),
  grantRoot: "/repo",
});

const artifact = (path: string, id = "art1"): ArtifactItem => ({
  id,
  type: "artifact",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  artifactId: id,
  kind: "pdf",
  path,
  mimeType: "application/pdf",
  title: "Report",
  version: 1,
  createdByItemId: null,
  previewUrl: null,
  renderStatus: "rendered",
  validationStatus: "passed",
});

const verification = (command: string, id = "v1"): VerificationItem => ({
  id,
  type: "verification",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  command,
  kind: "test",
  exitCode: 0,
  summary: "passed",
  stdoutTail: "ok",
  stderrTail: null,
  relatedFiles: ["src/app.ts"],
  relatedChangeItemIds: ["f1"],
});

const todoList = (entries: TodoListItem["plan"], id = "td1"): TodoListItem => ({
  id,
  type: "todo-list",
  status: "completed",
  createdAt: "2026-05-09T00:00:00Z",
  explanation: null,
  plan: entries,
});

const errorItem = (message: string, id = "e1"): ErrorItem => ({
  id,
  type: "error",
  status: "failed",
  createdAt: "2026-05-09T00:00:00Z",
  message,
  willRetry: false,
  errorInfo: null,
});

// ───────────────────────────────────────────────────────────────
// Tests
// ───────────────────────────────────────────────────────────────

describe("conversationToAgentThreadState · userMessage", () => {
  it("maps a userMessage to a HumanMessage", () => {
    const state = conversationToAgentThreadState(
      makeConv([makeTurn([userMsg("hello")])]),
    );
    expect(state.messages).toHaveLength(1);
    expect(state.messages[0]).toMatchObject({
      type: "human",
      content: "hello",
      id: "u1",
    });
  });

  it("attaches attachments when present", () => {
    const u: UserMessageItem = {
      ...userMsg("with file"),
      attachments: [{ name: "a.txt", size: 10 }],
    };
    const state = conversationToAgentThreadState(makeConv([makeTurn([u])]));
    expect(state.messages[0]?.additional_kwargs).toEqual({
      attachments: [{ name: "a.txt", size: 10 }],
    });
  });
});

describe("conversationToAgentThreadState · agentMessage + reasoning", () => {
  it("collapses reasoning before agentMessage into reasoning_content", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("q"),
          reasoning("step 1\nstep 2"),
          agentMsg("answer"),
        ]),
      ]),
    );
    expect(state.messages).toHaveLength(2);
    const ai = state.messages[1] as { type: string; content: string; additional_kwargs?: Record<string, unknown> };
    expect(ai.type).toBe("ai");
    expect(ai.content).toBe("answer");
    expect(ai.additional_kwargs?.reasoning_content).toBe("step 1\nstep 2");
  });

  it("merges multiple reasoning items into one block separated by blank lines", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("q"),
          reasoning("first", "r1"),
          reasoning("second", "r2"),
          agentMsg("done"),
        ]),
      ]),
    );
    const ai = state.messages[1] as { additional_kwargs?: Record<string, unknown> };
    expect(ai.additional_kwargs?.reasoning_content).toBe("first\n\nsecond");
  });

  it("uses summary when content is empty", () => {
    const r: ReasoningItem = {
      ...reasoning(""),
      summary: ["bullet 1", "bullet 2"],
    };
    const state = conversationToAgentThreadState(
      makeConv([makeTurn([userMsg("q"), r, agentMsg("done")])]),
    );
    const ai = state.messages[1] as { additional_kwargs?: Record<string, unknown> };
    expect(ai.additional_kwargs?.reasoning_content).toBe("bullet 1\nbullet 2");
  });

  it("dedupes repeated final answers emitted in the same turn", () => {
    const answer = [
      "你想调研的是哪类 harness？",
      "",
      "- 宠物胸背带",
      "- 攀岩/户外安全带",
    ].join("\n");
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("做一个harness的调研"),
          agentMsg(`Thought: 需要先澄清品类。\n\nFinal Answer:\n\n${answer}`, "a1"),
          reasoning("系统要求先创建 todo，所以补一个任务列表。", "r2"),
          agentMsg(`Final Answer:\n\n${answer}`, "a2"),
        ]),
      ]),
    );

    expect(state.messages).toHaveLength(2);
    expect(state.messages.map((message) => message.id)).toEqual(["u1", "a1"]);
    expect(state.messages[1]?.content).toBe(answer);
    expect(
      (state.messages[1]?.additional_kwargs as Record<string, unknown>)
        .reasoning_content,
    ).toContain("系统要求先创建 todo");
  });

  it("suppresses post-final todo bookkeeping from the main conversation", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("research a niche market"),
          reasoning("collect evidence", "r1"),
          agentMsg("# Report\n\nFull final answer with enough detail.", "a1"),
          reasoning(
            "The report has already been delivered as the Final Answer. I just need to update todo_write to mark the last item as completed.",
            "r2",
          ),
          cmd("todo_write", "todo-done"),
          reasoning(
            "All tasks are now completed. The report was already delivered in my Final Answer above.",
            "r3",
          ),
          agentMsg("All tasks are completed.", "a2"),
        ]),
      ]),
    );

    expect(state.messages).toHaveLength(2);
    expect(state.messages.map((message) => message.id)).toEqual(["u1", "a1"]);
    expect(state.messages[1]?.content).toContain("# Report");
  });

  it("merges post-final trace items back into the delivered answer", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("research a niche market"),
          reasoning("collect initial evidence", "r1"),
          agentMsg("# Report\n\nOpportunity, competitors, risks, and next steps.", "a1"),
          reasoning(
            "The todo-protocol guard keeps blocking my final answer. Let me check what happened.",
            "r2",
          ),
          cmd("todo_write", "todo-done"),
        ]),
      ]),
    );

    expect(state.messages).toHaveLength(2);
    const ai = state.messages[1] as {
      content: string;
      additional_kwargs?: Record<string, unknown>;
      tool_calls?: unknown[];
    };
    expect(ai.content).toContain("# Report");
    expect(ai.additional_kwargs?.reasoning_content).toContain(
      "collect initial evidence",
    );
    expect(ai.additional_kwargs?.reasoning_content).toContain(
      "todo-protocol guard",
    );
    expect(ai.tool_calls).toHaveLength(1);
  });
});

describe("conversationToAgentThreadState · plan", () => {
  it("attaches plan to the next agentMessage as thinking_plan", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([userMsg("q"), planItem("1. do X\n2. do Y"), agentMsg("doing")]),
      ]),
    );
    const ai = state.messages[1] as { additional_kwargs?: Record<string, unknown> };
    expect(ai.additional_kwargs?.thinking_plan).toBe("1. do X\n2. do Y");
  });
});

describe("conversationToAgentThreadState · tool calls", () => {
  it("turns commandExecution into a named tool_call on the trailing AIMessage", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("ls"),
          cmd("list_cwd", "c1", { inputPreview: { path: "/tmp" } }),
          agentMsg("see output above"),
        ]),
      ]),
    );
    const ai = state.messages[1] as { tool_calls?: Array<{ name: string; args: Record<string, unknown> }> };
    expect(ai.tool_calls).toHaveLength(1);
    expect(ai.tool_calls?.[0]?.name).toBe("list_cwd");
    expect(ai.tool_calls?.[0]?.args).toMatchObject({
      path: "/tmp",
      command: "list_cwd",
      exit_code: 0,
    });
  });

  it("turns mcpToolCall into a tool_call with server.tool name", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([userMsg("q"), mcp("git", "status"), agentMsg("clean")]),
      ]),
    );
    const ai = state.messages[1] as { tool_calls?: Array<{ name: string }> };
    expect(ai.tool_calls?.[0]?.name).toBe("git.status");
  });

  it("appends tool_calls in declared order", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("q"),
          cmd("echo 1", "c1"),
          mcp("git", "status", "m1"),
          cmd("echo 2", "c2"),
          agentMsg("done"),
        ]),
      ]),
    );
    const ai = state.messages[1] as { tool_calls?: Array<{ id?: string; name: string }> };
    expect(ai.tool_calls?.map((tc) => tc.id)).toEqual(["c1", "m1", "c2"]);
  });
});

describe("conversationToAgentThreadState · fileChange", () => {
  it("collects paths into thread.artifacts", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("edit"),
          fileChange(["src/a.ts", "src/b.ts"]),
          agentMsg("done"),
        ]),
      ]),
    );
    expect(state.artifacts).toEqual(["src/a.ts", "src/b.ts"]);
  });

  it("also surfaces fileChange as a tool_call so the LiveToolTimeline sees it", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([userMsg("edit"), fileChange(["x.ts"]), agentMsg("ok")]),
      ]),
    );
    const ai = state.messages[1] as { tool_calls?: Array<{ name: string }> };
    expect(ai.tool_calls?.[0]?.name).toBe("file_change");
  });
});

describe("conversationToAgentThreadState · first-class control items", () => {
  it("collects artifact paths and surfaces verification as a tool call", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          userMsg("q"),
          artifact("reports/out.pdf"),
          verification("pnpm test"),
          agentMsg("done"),
        ]),
      ]),
    );

    expect(state.artifacts).toContain("reports/out.pdf");
    const ai = state.messages.find((message) => message.type === "ai");
    expect(ai?.tool_calls?.map((tool) => tool.name)).toContain("verification");
    const verifyCall = ai?.tool_calls?.find((tool) => tool.name === "verification");
    expect(verifyCall?.args).toMatchObject({
      command: "pnpm test",
      exit_code: 0,
      related_files: ["src/app.ts"],
    });
  });
});

describe("conversationToAgentThreadState · todo-list", () => {
  it("maps todo-list to thread.todos", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          todoList([
            { title: "do X", status: "in_progress" },
            { title: "do Y", status: "pending" },
          ]),
        ]),
      ]),
    );
    expect(state.todos).toEqual([
      { content: "do X", status: "in_progress" },
      { content: "do Y", status: "pending" },
    ]);
  });

  it("the latest todo-list update wins within a turn", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([
          todoList([{ title: "old", status: "pending" }], "td1"),
          todoList(
            [
              { title: "old", status: "completed" },
              { title: "new", status: "in_progress" },
            ],
            "td2",
          ),
        ]),
      ]),
    );
    expect(state.todos).toHaveLength(2);
    expect(state.todos?.[0]?.status).toBe("completed");
  });

  it("does not emit a message for the todo-list (no AIMessage placeholder)", () => {
    const state = conversationToAgentThreadState(
      makeConv([makeTurn([todoList([{ title: "x", status: "pending" }])])]),
    );
    expect(state.messages).toEqual([]);
  });
});

describe("conversationToAgentThreadState · error", () => {
  it("surfaces error as an AIMessage with additional_kwargs.error", () => {
    const state = conversationToAgentThreadState(
      makeConv([makeTurn([userMsg("q"), errorItem("LLM 500")], "failed")]),
    );
    expect(state.messages).toHaveLength(2);
    const ai = state.messages[1] as { type: string; additional_kwargs?: Record<string, unknown> };
    expect(ai.type).toBe("ai");
    const err = ai.additional_kwargs?.error as Record<string, unknown> | undefined;
    expect(err?.message).toBe("LLM 500");
    expect(err?.will_retry).toBe(false);
  });
});

describe("conversationToAgentThreadState · interrupted turn", () => {
  it("flushes leftover reasoning/tool_calls as a synthetic AIMessage", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn(
          [userMsg("q"), reasoning("thinking…"), cmd("running")],
          "interrupted",
        ),
      ]),
    );
    expect(state.messages).toHaveLength(2);
    const ai = state.messages[1] as {
      type: string;
      content: string;
      additional_kwargs?: Record<string, unknown>;
      tool_calls?: unknown[];
    };
    expect(ai.type).toBe("ai");
    expect(ai.content).toBe("");
    expect(ai.additional_kwargs?.reasoning_content).toBe("thinking…");
    expect(ai.tool_calls).toHaveLength(1);
  });

  it("preserves agent_message + tool_call ordering when interrupted mid-stream", () => {
    // P0-2 regression: a turn that produced text + a tool call but
    // got interrupted before the next reasoning step should still
    // surface BOTH the ai-message and the tool_call. The adapter
    // emits the agent message first (as a complete AI message) and
    // flushes the trailing tool_call as a synthetic second AI
    // message; the LiveToolTimeline reads both.
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn(
          [userMsg("q"), agentMsg("partial answer"), cmd("ls")],
          "interrupted",
        ),
      ]),
    );
    const aiMessages = state.messages.filter((m) => m.type === "ai") as Array<{
      content: string;
      tool_calls?: unknown[];
    }>;
    // Two AI messages: the polished agent response, plus a synthetic
    // flush carrying the trailing tool_call.
    expect(aiMessages.length).toBeGreaterThanOrEqual(2);
    expect(aiMessages.some((ai) => ai.content.includes("partial answer"))).toBe(true);
    expect(
      aiMessages.some((ai) => Array.isArray(ai.tool_calls) && ai.tool_calls.length > 0),
    ).toBe(true);
  });

  it("marks isLoading=false on a failed turn so the input box re-enables", () => {
    // P0-2 regression: a failed turn must not keep the loading flag
    // on. Otherwise the user cannot type a follow-up.
    const conv = makeConv([
      {
        ...makeTurn([userMsg("q"), reasoning("oh no")], "failed"),
        error: { message: "upstream 500" },
      },
    ]);
    expect(conversationIsLoading(conv)).toBe(false);
  });

  it("does NOT mark isLoading=true on a resumed in-progress turn synthesised by stale reconnect", () => {
    // P0-5 adjacent: when ``thread/resume`` returns a turn in
    // ``inProgress`` state but the run actually died on the server
    // (stale_in_progress_turn handler will close it), we still
    // surface it as loading until the synthesised turn/interrupted
    // arrives. This is the contract the realtime hook depends on.
    const conv = makeConv([
      makeTurn([userMsg("q"), reasoning("…")], "inProgress"),
    ]);
    expect(conversationIsLoading(conv)).toBe(true);
  });

  it("surfaces a tool_call that's still inProgress (waiting on user approval)", () => {
    // The approval round-trip is modelled as a commandExecution item
    // that stays inProgress until the user accepts. The adapter must
    // already surface that tool_call so the LiveToolTimeline can
    // render the approval card.
    const pendingCmd: CommandExecutionItem = {
      ...cmd("rm -rf /tmp/work"),
      status: "inProgress",
    };
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([userMsg("q"), reasoning("about to run"), pendingCmd], "inProgress"),
      ]),
    );
    const ai = state.messages.find((m) => m.type === "ai") as {
      tool_calls?: Array<{ name?: string; args?: unknown }>;
    } | undefined;
    expect(ai).toBeDefined();
    expect(ai!.tool_calls).toBeDefined();
    expect(ai!.tool_calls!.length).toBeGreaterThan(0);
    const call = ai!.tool_calls![0];
    expect(call.name).toBeTruthy();
  });
});

describe("conversationToAgentThreadState · multi-turn", () => {
  it("accumulates messages across turns in order", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([userMsg("q1", "u1"), agentMsg("a1", "ai1")]),
        makeTurn([userMsg("q2", "u2"), agentMsg("a2", "ai2")]),
      ]),
    );
    expect(state.messages.map((m) => m.id)).toEqual(["u1", "ai1", "u2", "ai2"]);
  });
});

describe("conversationToAgentThreadState · base override", () => {
  it("preserves base.title and base.agent_roster", () => {
    const state = conversationToAgentThreadState(makeConv([]), {
      title: "My Thread",
      agent_roster: [{ name: "alice", display_name: "Alice", role: "tl" }],
    });
    expect(state.title).toBe("My Thread");
    expect(state.agent_roster?.[0]?.name).toBe("alice");
  });

  it("merges base.artifacts before turn-extracted ones", () => {
    const state = conversationToAgentThreadState(
      makeConv([
        makeTurn([fileChange(["new.ts"])]),
      ]),
      { artifacts: ["pre-existing.ts"] },
    );
    expect(state.artifacts).toEqual(["pre-existing.ts", "new.ts"]);
  });
});

describe("conversationIsLoading", () => {
  it("returns true when last turn is inProgress", () => {
    const conv = makeConv([
      makeTurn([userMsg("q"), agentMsg("a")], "completed"),
      makeTurn([userMsg("q2")], "inProgress"),
    ]);
    expect(conversationIsLoading(conv)).toBe(true);
  });

  it("returns false when last turn is completed", () => {
    expect(
      conversationIsLoading(
        makeConv([makeTurn([userMsg("q"), agentMsg("a")], "completed")]),
      ),
    ).toBe(false);
  });

  it("returns false on an empty conversation", () => {
    expect(conversationIsLoading(makeConv([]))).toBe(false);
  });
});

describe("conversationStreamingMessage", () => {
  it("returns the active AI message while the latest turn is streaming", () => {
    const conv = makeConv([
      makeTurn(
        [
          userMsg("q"),
          reasoning("checking context"),
          {
            ...agentMsg("partial answer", "a-stream"),
            status: "inProgress",
          },
        ],
        "inProgress",
      ),
    ]);

    const streaming = conversationStreamingMessage(conv);

    expect(streaming).toMatchObject({
      type: "ai",
      id: "a-stream",
      content: "partial answer",
    });
    expect(streaming?.additional_kwargs?.reasoning_content).toBe(
      "checking context",
    );
  });

  it("returns a synthetic AI message for reasoning-only in-progress turns", () => {
    const conv = makeConv([
      makeTurn([userMsg("q"), reasoning("thinking")], "inProgress"),
    ]);

    const streaming = conversationStreamingMessage(conv);

    expect(streaming).toMatchObject({
      type: "ai",
      content: "",
    });
    expect(streaming?.additional_kwargs?.reasoning_content).toBe("thinking");
  });

  it("returns null after the latest turn is completed", () => {
    const conv = makeConv([
      makeTurn([userMsg("q"), agentMsg("done")], "completed"),
    ]);

    expect(conversationStreamingMessage(conv)).toBeNull();
  });
});

describe("conversationLastError", () => {
  it("returns undefined when the last turn completed cleanly", () => {
    expect(
      conversationLastError(
        makeConv([makeTurn([userMsg("q"), agentMsg("a")], "completed")]),
      ),
    ).toBeUndefined();
  });

  it("returns an Error when the last turn failed", () => {
    const err = conversationLastError(
      makeConv([makeTurn([userMsg("q"), errorItem("boom")], "failed")]),
    );
    expect(err).toBeInstanceOf(Error);
    expect(err?.message).toBe("boom");
  });

  it("falls back to turn.error.message if no ErrorItem is present", () => {
    const turn: Turn = {
      ...makeTurn([userMsg("q")], "failed"),
      error: { message: "transport closed" },
    };
    const err = conversationLastError(makeConv([turn]));
    expect(err?.message).toBe("transport closed");
  });

  it("surfaces a failed verification item as the last-turn error", () => {
    const err = conversationLastError(
      makeConv([
        makeTurn(
          [
            userMsg("q"),
            {
              ...verification("verification required"),
              status: "failed",
              kind: "manual",
              summary:
                "Code changes were produced but no verification step was recorded before final answer.",
            },
          ],
          "failed",
        ),
      ]),
    );

    expect(err?.message).toBe(
      "Code changes were produced but no verification step was recorded before final answer.",
    );
  });

  it("does not surface no-output planner placeholders as user-visible errors", () => {
    const err = conversationLastError(
      makeConv([
        makeTurn(
          [userMsg("深度调研"), agentMsg("[planner] (no output)")],
          "failed",
        ),
      ]),
    );

    expect(err).toBeUndefined();
  });
});

describe("splitReactTrace", () => {
  it("returns full text as finalAnswer when no markers", () => {
    expect(splitReactTrace("hello world")).toEqual({
      thought: "",
      finalAnswer: "hello world",
    });
  });

  it("strips Thought/Action and surfaces Final Answer", () => {
    const trace = [
      "Thought: I need to look up the answer.",
      "Action: web_search({\"q\":\"foo\"})",
      "Observation: results...",
      "Thought: Now I have enough.",
      "Final Answer: 42 is the answer.",
    ].join("\n");
    const out = splitReactTrace(trace);
    expect(out.finalAnswer).toBe("42 is the answer.");
    expect(out.thought).toContain("I need to look up");
    expect(out.thought).toContain("Now I have enough");
    expect(out.thought).not.toContain("web_search");
    expect(out.thought).not.toContain("Final Answer");
  });

  it("handles Chinese markers", () => {
    const trace = "思考: 这个问题需要分析。\n最终答案: 42";
    const out = splitReactTrace(trace);
    expect(out.finalAnswer).toBe("42");
    expect(out.thought).toBe("这个问题需要分析。");
  });

  it("falls back to thought when no Final Answer yet", () => {
    const trace = "Thought: still thinking…\nAction: foo()";
    const out = splitReactTrace(trace);
    expect(out.finalAnswer).toBe("");
    // Final thought is held back as the in-progress placeholder; with
    // only one thought, the held-back set is empty.
    expect(out.thought).toBe("");
  });

  it("uses LAST Final Answer when multiple present", () => {
    const trace = "Final Answer: first\nThought: oops\nFinal Answer: second";
    expect(splitReactTrace(trace).finalAnswer).toBe("second");
  });

  it("preserves markdown inside Final Answer", () => {
    const trace = "Thought: prep.\nFinal Answer: # Title\n\n- a\n- b\n\n```js\nx=1\n```";
    const out = splitReactTrace(trace);
    expect(out.finalAnswer).toContain("# Title");
    expect(out.finalAnswer).toContain("```js");
  });
});
