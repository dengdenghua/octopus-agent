import { screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { StreamVitals } from "@/core/realtime";
import { renderWithProviders } from "@/test/harness";

import { RunDurationBadge } from "./run-duration-badge";

function vitals(partial: Partial<StreamVitals> = {}): StreamVitals {
  return {
    phase: "working",
    ttftMs: null,
    lastDeltaAgeMs: 0,
    sinceActivityMs: 0,
    elapsedMs: 137_000,
    maxDeltaGapMs: 0,
    stalled: false,
    ...partial,
  };
}

describe("RunDurationBadge", () => {
  test("places the total run duration in the header status", () => {
    renderWithProviders(<RunDurationBadge isLoading vitals={vitals()} />, {
      locale: "zh-CN",
    });

    expect(screen.getByTestId("run-duration-badge")).toHaveTextContent(
      "正在处理",
    );
    expect(screen.getByTestId("run-duration-badge")).toHaveTextContent("137s");
  });

  test("does not render after the run settles", () => {
    renderWithProviders(<RunDurationBadge isLoading={false} vitals={vitals()} />);
    expect(screen.queryByTestId("run-duration-badge")).not.toBeInTheDocument();
  });
});
