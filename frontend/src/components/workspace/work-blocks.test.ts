import { describe, expect, test } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import {
  pickCurrentWorkBlock,
  progressForWorkBlocks,
  statusText,
  toWorkBlocks,
} from "./work-blocks";

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

describe("work blocks", () => {
  test("accepts localized status labels without changing the default fallback", () => {
    expect(statusText("running")).toBe("正在执行");
    expect(
      statusText("running", {
        running: "Running",
        waiting_approval: "Waiting",
        warning: "Recovered",
        error: "Failed",
        done: "Done",
      }),
    ).toBe("Running");
  });

  test("filters transport and child tool events", () => {
    const blocks = toWorkBlocks([
      event({ id: "transport", name: "response_stream" }),
      event({ id: "gateway", name: "model_gateway", status: "running" }),
      event({ id: "reasoning", name: "model_reasoning" }),
      event({
        id: "child",
        name: "grep",
        parentToolUseId: "shell-1",
        input: { pattern: "needle" },
      }),
      event({ id: "read", name: "read_file", input: { path: "src/app.tsx" } }),
    ]);

    expect(blocks.map((block) => block.id)).toEqual(["read"]);
    expect(blocks[0]).toMatchObject({
      kind: "read",
      actionLabel: "阅读",
      target: "app.tsx",
      title: "阅读 app.tsx",
      subtitle: "app.tsx",
    });
  });

  test("coalesces restored start and result records for one tool call", () => {
    const blocks = toWorkBlocks([
      event({
        id: "same-call",
        status: "running",
        startedAt: 1000,
        input: { path: "src/app.tsx" },
      }),
      event({
        id: "same-call",
        status: "done",
        startedAt: 1010,
        finishedAt: 1020,
        output: { content: "source" },
      }),
    ]);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      id: "same-call",
      status: "done",
      startedAt: 1000,
      target: "app.tsx",
    });
    expect(blocks[0].outputText).toContain("source");
  });

  test("uses active todo text and running block for progress", () => {
    const blocks = toWorkBlocks([
      event({
        id: "todo",
        name: "todo_write",
        input: {
          items: [
            { content: "one", status: "completed" },
            { content: "implement renderer", status: "in_progress" },
          ],
        },
      }),
      event({
        id: "shell",
        name: "shell_command",
        status: "running",
        startedAt: 2000,
        input: { command: "npm run typecheck" },
      }),
    ]);

    expect(blocks[0]).toMatchObject({
      actionLabel: "编写待办清单",
      title: "编写待办清单",
      subtitle: "implement renderer",
    });
    expect(blocks[1]).toMatchObject({
      actionLabel: "运行终端",
      target: "",
      title: "运行终端",
      subtitle: "正在执行",
    });
    expect(blocks[1].title).not.toContain("npm run typecheck");
    expect(blocks[1].subtitle).not.toContain("npm run typecheck");
    const current = pickCurrentWorkBlock(blocks);
    expect(current?.id).toBe("shell");
    expect(progressForWorkBlocks(blocks, current!)).toEqual({
      current: 2,
      total: 2,
    });
  });

  test("promotes MCP progress into visible block text", () => {
    const blocks = toWorkBlocks([
      event({
        id: "mcp-progress",
        name: "mcp:read_workbook",
        status: "running",
        input: {
          server: "sheets",
          tool: "read_workbook",
          progress: {
            label: "Reading workbook",
            percent: 0.42,
            current: 21,
            total: 50,
          },
        },
      }),
    ]);

    expect(blocks[0]).toMatchObject({
      id: "mcp-progress",
      title: "Reading workbook",
      subtitle: "42%",
    });
  });

  test("treats manual verification-required audit as waiting, not a hard failure", () => {
    const blocks = toWorkBlocks([
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

    expect(blocks[0]).toMatchObject({
      id: "verify-required",
      title: "等待验证",
      status: "waiting_approval",
      subtitle: "等待确认",
    });
  });

  test("keeps real read failures red", () => {
    const blocks = toWorkBlocks([
      event({
        id: "read-error",
        name: "read_file",
        status: "error",
        input: { path: "missing.ts" },
        output: { error: "ENOENT" },
      }),
    ]);

    expect(blocks[0]).toMatchObject({
      id: "read-error",
      kind: "read",
      status: "error",
      title: "阅读 missing.ts",
    });
  });

  test("uses explicit terminal failure wording for command errors", () => {
    const blocks = toWorkBlocks([
      event({
        id: "shell-error",
        name: "shell_command",
        status: "error",
        input: { command: "npm run build" },
        output: { error: "exit 1" },
      }),
    ]);

    expect(blocks[0]).toMatchObject({
      id: "shell-error",
      actionLabel: "终端运行失败",
      target: "",
      title: "终端运行失败",
      subtitle: "执行失败",
    });
    expect(blocks[0].title).not.toContain("npm run build");
    expect(blocks[0].subtitle).not.toContain("npm run build");
  });

  test("uses public terminal summaries without leaking local cwd", () => {
    const blocks = toWorkBlocks([
      event({
        id: "shell-cwd",
        name: "shell_command",
        status: "running",
        input: {
          command: "cat ~/.ssh/id_rsa && pnpm test",
          cwd: "/Users/dangbei/Public/octopus/octopus-agent",
        },
      }),
    ]);

    expect(blocks[0]).toMatchObject({
      id: "shell-cwd",
      title: "运行终端",
      subtitle: "octopus-agent",
    });
    expect(blocks[0].title).not.toContain("cat ~/.ssh");
    expect(blocks[0].subtitle).not.toContain("/Users/");
  });

  test("classifies swarm dispatch and document skills as workflow blocks", () => {
    const blocks = toWorkBlocks([
      event({
        id: "swarm",
        name: "call_agent_parallel",
        input: {
          specs: [
            { agent_id: "researcher", prompt: "A" },
            { agent_id: "reviewer", prompt: "B" },
            { agent_id: "writer", prompt: "C" },
          ],
        },
      }),
      event({
        id: "docx",
        name: "docx",
        input: { name: "docx" },
      }),
    ]);

    expect(blocks.map((block) => block.kind)).toEqual(["swarm", "skill"]);
    expect(blocks[0].title).toContain("3");
    expect(blocks[1].title).toContain("DOCX");
  });
});
