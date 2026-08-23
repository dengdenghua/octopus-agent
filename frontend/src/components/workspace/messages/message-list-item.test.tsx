import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Message } from "@/core/api/types";
import { describe, expect, it, vi } from "vitest";

import {
  containsProtocolMarkers,
  messageClipboardText,
  MessageTimestamp,
  ShadowReviewAction,
  threadMessageToCoworkRoomMessage,
} from "./message-list-item";

const evolutionMocks = vi.hoisted(() => ({
  getStatus: vi.fn(),
  queueRun: vi.fn(),
}));

vi.mock("@/core/evolution/api", () => ({
  getDualHelixShadowStatus: evolutionMocks.getStatus,
  queueDualHelixShadowRun: evolutionMocks.queueRun,
}));

describe("MessageTimestamp", () => {
  it("renders nothing when no timestamp is provided", () => {
    const { container } = render(<MessageTimestamp />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the timestamp is unparseable", () => {
    const { container } = render(<MessageTimestamp createdAt="not-a-date" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a local HH:mm label", () => {
    render(<MessageTimestamp createdAt="2026-05-09T10:30:00Z" alwaysVisible />);
    expect(screen.getByText(/\d{2}:\d{2}/)).toBeInTheDocument();
  });

  it("is always visible when alwaysVisible is set, otherwise hover-revealed", () => {
    const { rerender } = render(
      <MessageTimestamp createdAt="2026-05-09T10:30:00Z" alwaysVisible />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("opacity-100");

    rerender(
      <MessageTimestamp
        createdAt="2026-05-09T10:30:00Z"
        alwaysVisible={false}
      />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("opacity-0");
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain(
      "group-hover/conversation-message:opacity-100",
    );
  });

  it("aligns to the end for user bubbles", () => {
    render(<MessageTimestamp createdAt="2026-05-09T10:30:00Z" align="end" />);
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("self-end");
  });
});

describe("protocol cleaning bail-out", () => {
  it("does not skip the bare legacy sub-agent placeholder", () => {
    // The legacy placeholder may appear WITHOUT the optional `[...]`
    // prefix; its ASCII `(` must therefore be a first-mark so the
    // streaming fast path still runs the cleaning chain.
    expect(
      containsProtocolMarkers("(sub-agent exceeded token budget 100/200)"),
    ).toBe(true);
  });

  it("empties a bare legacy sub-agent placeholder from clipboard text", () => {
    const message = {
      type: "ai",
      content: "(sub-agent exceeded token budget 100/200)",
    } as unknown as Message;
    expect(messageClipboardText(message)).toBe("");
  });

  it("still skips plain prose without protocol markers", () => {
    expect(
      containsProtocolMarkers("这是一段普通的流式回答，没有任何协议标记。"),
    ).toBe(false);
    expect(containsProtocolMarkers("plain english prose here")).toBe(false);
  });
});

describe("project group message mirror", () => {
  it("uses the canonical thread message id as an idempotent room source", () => {
    const message = {
      id: "human-42",
      type: "human",
      content: "请把这项工作交给 @agent:planner",
    } as Message;

    expect(
      threadMessageToCoworkRoomMessage(message, "thread-1", 3, undefined),
    ).toMatchObject({
      seq: -1,
      text: "请把这项工作交给 @agent:planner",
      metadata: { source_message_id: "thread:human-42" },
    });
  });

  it("hydrates prior project receipts from the hidden room mirror", () => {
    const message = {
      id: "human-42",
      type: "human",
      content: "确定采用 A 方案",
    } as Message;
    const metadata = {
      source_message_id: "thread:human-42",
      project_actions: [
        {
          id: "action-1",
          action: "record_decision" as const,
          project_id: "project-1",
          target: { kind: "decision", id: "decision-1" },
        },
      ],
    };

    expect(
      threadMessageToCoworkRoomMessage(message, "thread-1", 3, {
        "thread:human-42": metadata,
      }).metadata,
    ).toBe(metadata);
  });
});

describe("ShadowReviewAction", () => {
  it("queues the opposite-engine review only after an explicit click", async () => {
    evolutionMocks.getStatus.mockResolvedValue({
      ok: true,
      enabled: true,
      runs: [],
    });
    evolutionMocks.queueRun.mockResolvedValue({
      run_id: "shadow-1",
      goal: "修复问题",
      primary_engine: "octopus",
      shadow_engine: "codex",
      status: "queued",
      created_at: "2026-08-23T00:00:00Z",
      source_thread_id: "thread-1",
      source_message_id: "answer-1",
    });

    render(
      <ShadowReviewAction
        context={{
          goal: "修复问题",
          primaryEngine: "octopus",
          primaryOutput: "已经修复",
          threadId: "thread-1",
          messageId: "answer-1",
          workspacePath: "/workspace/project",
        }}
      />,
    );

    expect(evolutionMocks.queueRun).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "让另一引擎复核本次任务" }),
    );

    await waitFor(() =>
      expect(evolutionMocks.queueRun).toHaveBeenCalledWith({
        goal: "修复问题",
        primary_engine: "octopus",
        primary_output: "已经修复",
        workspace_path: "/workspace/project",
        source_thread_id: "thread-1",
        source_message_id: "answer-1",
      }),
    );
    expect(
      screen.getByRole("button", { name: "另一引擎正在影子复核" }),
    ).toBeDisabled();
  });
});
