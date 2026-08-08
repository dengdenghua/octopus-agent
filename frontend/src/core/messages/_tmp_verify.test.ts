import { describe, expect, it } from "vitest";

import type { Message } from "@/core/api/types";

import { convertToSteps } from "@/components/workspace/messages/message-group";

import { groupMessages } from "./utils";

describe("tmp verify plan-prelude ordering", () => {
  it("routes a plan message before tool calls into the processing group", () => {
    const messages: Message[] = [
      { id: "1", type: "human", content: "帮我找3个AI应用爆点方向" },
      {
        id: "2",
        type: "ai",
        content: "接下来我会先圈定3个明显的AI应用爆点方向，再逐一验证。",
        additional_kwargs: { message_kind: "answer" },
      },
      {
        id: "3",
        type: "ai",
        content: "",
        tool_calls: [{ id: "tc1", name: "web_search", args: { query: "x" } }],
      },
    ];

    const result = groupMessages(messages, (group) => group);
    expect(result.map((group) => group.type)).toEqual([
      "human",
      "assistant:processing",
    ]);
    // The plan message must NOT become a standalone assistant bubble.
    expect(result[1]?.messages.map((m) => m.id)).toEqual(["2", "3"]);
  });

  it("turns the plan prelude into a commentary timeline step", () => {
    const messages: Message[] = [
      { id: "1", type: "human", content: "帮我找3个AI应用爆点方向" },
      {
        id: "2",
        type: "ai",
        content: "接下来我会先圈定3个明显的AI应用爆点方向，再逐一验证。",
        additional_kwargs: { message_kind: "answer" },
      },
      {
        id: "3",
        type: "ai",
        content: "",
        tool_calls: [{ id: "tc1", name: "web_search", args: { query: "x" } }],
      },
    ];

    const steps = convertToSteps(messages);
    expect(steps.some((step) => step.type === "commentary")).toBe(true);
    const commentary = steps.find((step) => step.type === "commentary");
    expect(
      commentary?.type === "commentary" && commentary.commentary,
    ).toContain("圈定3个");
    // The tool call must come after the prelude in the timeline.
    const commentaryIndex = steps.findIndex(
      (step) => step.type === "commentary",
    );
    const toolIndex = steps.findIndex((step) => step.type === "toolCall");
    expect(commentaryIndex).toBeGreaterThanOrEqual(0);
    expect(toolIndex).toBeGreaterThan(commentaryIndex);
  });

  it("defers the prelude commentary until after the first reasoning chunk so thinking appears before plan narration", () => {
    const messages: Message[] = [
      { id: "1", type: "human", content: "开始" },
      {
        id: "2",
        type: "ai",
        content: '用户说"开始"——按计划，从A1开始。',
        additional_kwargs: { message_kind: "answer" },
      },
      {
        id: "3",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            'The user said "开始". This means they want me to start executing the plan. Let me review the priorities.',
        },
        tool_calls: [{ id: "tc1", name: "read_file", args: { path: "x" } }],
      },
    ];

    const steps = convertToSteps(messages);
    const reasoningIndex = steps.findIndex((step) => step.type === "reasoning");
    const commentaryIndex = steps.findIndex(
      (step) => step.type === "commentary",
    );
    const toolIndex = steps.findIndex((step) => step.type === "toolCall");
    // Order must be: reasoning (understand the task) → commentary (announce the plan) → tool call (execute).
    expect(reasoningIndex).toBe(0);
    expect(commentaryIndex).toBeGreaterThan(reasoningIndex);
    expect(toolIndex).toBeGreaterThan(commentaryIndex);
  });
});
