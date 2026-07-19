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
  test("stays hidden when the turn is idle", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading={false} liveToolEvents={[]} />,
      { locale: "zh-CN" },
    );

    expect(
      screen.queryByTestId("conversation-activity-pulse"),
    ).not.toBeInTheDocument();
  });

  test("shows only the measured runtime state and elapsed time", () => {
    renderWithProviders(
      <PublicThinkingStatus isLoading liveToolEvents={[]} vitals={vitals()} />,
      { locale: "zh-CN" },
    );

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("模型处理中");
    expect(status).toHaveTextContent("8s");
    expect(status).not.toHaveTextContent("理解");
    expect(status).not.toHaveTextContent("规划");
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
    expect(pulse).toHaveTextContent("模型处理中");
    expect(pulse).toHaveTextContent("12s");
    expect(pulse).toHaveTextContent("web search: Kimi streaming interaction");
  });

  test("gets out of the way while answer tokens are flowing", () => {
    renderWithProviders(
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
    expect(status).toHaveTextContent("仍在处理，响应较慢");
    expect(status).toHaveTextContent("31s");
    expect(status).toHaveAttribute("data-phase", "slow");
  });
});
