import { describe, expect, test } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import {
  pickCurrentWorkBlock,
  progressForWorkBlocks,
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
      title: "阅读 app.tsx",
      subtitle: "src/app.tsx",
    });
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

    expect(blocks[0].title).toBe("implement renderer");
    expect(blocks[1].title).toBe("运行 npm run typecheck");
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
