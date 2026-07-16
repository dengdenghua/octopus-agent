import { screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { renderWithProviders } from "@/test/harness";

import type { LiveToolEvent } from "./live-tool-timeline";
import { PublicThinkingStatus } from "./public-thinking-status";

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

describe("PublicThinkingStatus", () => {
  test("stays hidden when the turn is idle", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading={false} liveToolEvents={[]} />,
      { locale: "zh-CN" },
    );

    expect(
      screen.queryByTestId("conversation-activity-pulse"),
    ).not.toBeInTheDocument();
  });

  test("speaks naturally while understanding the request", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading liveToolEvents={[]} />,
      { locale: "zh-CN" },
    );

    expect(screen.getByRole("status")).toHaveTextContent("正在理解你的要求");
  });

  test("shows the current action and its public target", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        liveToolEvents={[toolEvent("running")]}
      />,
      { locale: "zh-CN" },
    );

    const pulse = screen.getByTestId("conversation-activity-pulse");
    expect(pulse).toHaveTextContent("正在动手处理");
    expect(pulse).toHaveTextContent("web search: Kimi streaming interaction");
  });

  test("keeps the latest result visible while the answer starts streaming", () => {
    renderWithProviders(
      <PublicThinkingStatus
        isLoading
        hasStreamingMessage
        liveToolEvents={[
          toolEvent("done", { finishedAt: 2_000, output: "found" }),
        ]}
      />,
      { locale: "zh-CN" },
    );

    const pulse = screen.getByTestId("conversation-activity-pulse");
    expect(pulse).toHaveTextContent("刚拿到结果");
    expect(pulse).toHaveTextContent("正在回答你");
  });
});
