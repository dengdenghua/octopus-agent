import { screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { renderWithProviders } from "@/test/harness";

import type { LiveToolEvent } from "./live-tool-timeline";
import { PublicThinkingStatus } from "./public-thinking-status";
import type { StreamVitals } from "@/core/realtime/stream-vitals";

function toolEvent(
  status: LiveToolEvent["status"],
  overrides: Partial<LiveToolEvent> = {},
): LiveToolEvent {
  return {
    id: `search-${status}`,
    name: "web_search",
    status,
    startedAt: 1_000,
    input: { query: "Kimi streaming interaction" },
    ...overrides,
  };
}

function vitals(overrides: Partial<StreamVitals> = {}): StreamVitals {
  return {
    phase: "working",
    ttftMs: null,
    lastDeltaAgeMs: Infinity,
    sinceActivityMs: 500,
    elapsedMs: 8_000,
    maxDeltaGapMs: 0,
    stalled: false,
    ...overrides,
  };
}

describe("PublicThinkingStatus", () => {
  test("keeps the stable live region empty on an initially idle turn", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading={false} liveToolEvents={[]} />,
      { locale: "zh-CN" },
    );

    expect(
      screen.queryByTestId("conversation-activity-pulse"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  test("shows a neutral processing label once the task is underway", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading liveToolEvents={[]} vitals={vitals()} />,
      { locale: "zh-CN" },
    );

    const status = screen.getByRole("status");
    const pulse = screen.getByTestId("conversation-activity-pulse");
    // Mid-task pauses are NOT "thinking" — that label is reserved for the
    // pre-first-response window of a fresh turn (see the waiting case).
    expect(status).toHaveTextContent("正在处理");
    expect(status).not.toHaveTextContent("8s");
    expect(pulse).toHaveTextContent("8s");
    expect(pulse).toHaveAttribute("aria-hidden", "true");
    expect(status).not.toHaveTextContent("思考中");
    expect(status).not.toHaveTextContent("理解");
    expect(status).not.toHaveTextContent("规划");
    expect(status).not.toHaveTextContent("模型");
  });

  test("distinguishes an alive connection from a model that has not responded", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[]}
        vitals={vitals({ phase: "waiting", elapsedMs: 18_000 })}
      />,
      { locale: "zh-CN" },
    );

    const status = screen.getByRole("status");
    const pulse = screen.getByTestId("conversation-activity-pulse");
    expect(status).toHaveTextContent("思考中");
    expect(status).not.toHaveTextContent("18s");
    expect(pulse).toHaveTextContent("18s");
    expect(status).not.toHaveTextContent("模型处理中");
    expect(status).not.toHaveTextContent("模型");
  });

  test("shows the current action and its public target", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[toolEvent("running")]}
        vitals={vitals({ elapsedMs: 12_000 })}
      />,
      { locale: "zh-CN" },
    );

    const pulse = screen.getByTestId("conversation-activity-pulse");
    // The running action leads the line — no generic "思考中" wrapper.
    expect(pulse).toHaveTextContent("搜索资料: Kimi streaming interaction");
    expect(pulse).not.toHaveTextContent("12s");
    expect(pulse).not.toHaveTextContent("思考中");
    expect(pulse).not.toHaveTextContent("web_search");
  });

  test("keeps status details concise and does not leak shell commands", () => {
    const { rerender } = renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[
          toolEvent("running", {
            id: "read-running",
            name: "read_file",
            input: {
              path: "/Users/example/Public/octopus/octopus-agent/src/app.ts",
            },
          }),
        ]}
        vitals={vitals({ elapsedMs: 12_000 })}
      />,
      { locale: "zh-CN" },
    );

    const pulse = screen.getByTestId("conversation-activity-pulse");
    expect(pulse).toHaveTextContent("查看文件: app.ts");
    expect(pulse).not.toHaveTextContent("/Users/");
    expect(pulse).not.toHaveTextContent("read_file");

    rerender(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[
          toolEvent("running", {
            id: "shell-running",
            name: "exec_shell",
            input: { command: "cat ~/.ssh/id_rsa && pnpm test" },
          }),
        ]}
        vitals={vitals({ elapsedMs: 13_000 })}
      />,
    );

    expect(screen.getByTestId("conversation-activity-pulse")).toHaveTextContent(
      "执行操作",
    );
    expect(
      screen.getByTestId("conversation-activity-pulse"),
    ).not.toHaveTextContent("cat ~/.ssh/id_rsa");
  });

  test("gets out of the way while answer tokens are flowing", () => {
    const { rerender } = renderWithProviders(
      <PublicThinkingStatus
        isLoading
        hasStreamingMessage
        vitals={vitals({ phase: "streaming" })}
        liveToolEvents={[
          toolEvent("done", { finishedAt: 2_000, output: "found" }),
        ]}
      />,
      { locale: "zh-CN" },
    );

    expect(
      screen.queryByTestId("conversation-activity-pulse"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("正在处理");

    rerender(
      <PublicThinkingStatus
        isLoading
        hasStreamingMessage
        vitals={vitals({ phase: "streaming", elapsedMs: 9_000 })}
        liveToolEvents={[]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/^正在处理$/);
    expect(screen.getByRole("status")).not.toHaveTextContent("9s");

    rerender(
      <PublicThinkingStatus
        isLoading={false}
        hasStreamingMessage={false}
        vitals={vitals({ phase: "idle" })}
        liveToolEvents={[]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("处理已结束");

    rerender(
      <PublicThinkingStatus
        isLoading={false}
        hasStreamingMessage={false}
        vitals={vitals({ phase: "idle", elapsedMs: 20_000 })}
        liveToolEvents={[]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/^处理已结束$/);
  });

  test("reports measured silence without inventing a process stage", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[]}
        vitals={vitals({
          phase: "slow",
          elapsedMs: 31_000,
          sinceActivityMs: 14_000,
          stalled: true,
        })}
      />,
      { locale: "zh-CN" },
    );

    const status = screen.getByRole("status");
    const pulse = screen.getByTestId("conversation-activity-pulse");
    expect(status).toHaveTextContent("还在继续，稍慢一些");
    expect(status).not.toHaveTextContent("31s");
    expect(pulse).toHaveTextContent("31s");
    expect(pulse).toHaveAttribute("data-phase", "slow");
  });

  test("shows a waiting lane before turn vitals are seeded", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[]}
        vitals={vitals({ phase: "idle", elapsedMs: 0 })}
      />,
      { locale: "zh-CN" },
    );

    expect(screen.getByTestId("conversation-activity-pulse")).toHaveTextContent(
      "思考中",
    );
    expect(
      screen.queryByTestId("conversation-activity-elapsed"),
    ).not.toBeInTheDocument();
  });

  test("formats minute-long first-response waits as a readable duration", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[]}
        vitals={vitals({ phase: "waiting", elapsedMs: 104_500 })}
      />,
      { locale: "zh-CN" },
    );

    expect(
      screen.getByTestId("conversation-activity-elapsed"),
    ).toHaveTextContent("1m 44s");
    expect(screen.getByTestId("conversation-activity-pulse")).toHaveTextContent(
      "首个响应较慢，任务仍在等待",
    );
    expect(screen.getByTestId("conversation-activity-pulse")).toHaveAttribute(
      "data-first-response-delayed",
      "true",
    );
    expect(screen.getByRole("status")).not.toHaveTextContent("1m 44s");
  });
});
