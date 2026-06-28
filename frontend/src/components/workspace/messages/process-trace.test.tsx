import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { AllProviders } from "@/test/harness";
import type { LiveToolEvent } from "../live-tool-timeline";

import { ProcessTrace } from "./process-trace";

function event(
  name: string,
  overrides: Partial<LiveToolEvent> = {},
): LiveToolEvent {
  return {
    id: `${name}-${overrides.status ?? "done"}`,
    name,
    status: "done",
    startedAt: 1000,
    iteration: 1,
    ...overrides,
  };
}

describe("ProcessTrace", () => {
  test("renders the running process as a flat timeline instead of nested cards", () => {
    render(
      <AllProviders>
        <ProcessTrace
          live
          mode="code"
          events={[
            event("agent_thought", {
              id: "thought-1",
              thought: "Inspect the streaming UX before changing layout.",
            }),
            event("read_file", {
              id: "read-1",
              status: "running",
              input: { path: "frontend/src/components/workspace" },
            }),
          ]}
        />
      </AllProviders>,
    );

    const timeline = screen.getByTestId("process-trace-timeline");
    expect(timeline).toBeInTheDocument();
    expect(timeline.className).toContain("border-l");
    expect(timeline.className).not.toContain("rounded-xl");

    const sections = screen.getAllByTestId("process-trace-section");
    expect(sections.length).toBeGreaterThan(0);
    for (const section of sections) {
      expect(section.className).toContain("border-l");
      expect(section.className).not.toContain("rounded-xl");
    }

    expect(screen.getAllByText("Thinking process").length).toBeGreaterThan(0);
    expect(screen.getByText("Execution")).toBeInTheDocument();
  });
});
