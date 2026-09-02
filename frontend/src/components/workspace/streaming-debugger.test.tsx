import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import { StreamingDebugger } from "./streaming-debugger";

function event(id: string, status: LiveToolEvent["status"]): LiveToolEvent {
  return {
    id,
    name: `tool-${id}`,
    status,
    startedAt: 1_000,
    iteration: 0,
  };
}

describe("<StreamingDebugger />", () => {
  beforeEach(() => {
    vi.stubEnv("DEV", false);
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    window.localStorage.clear();
  });

  it("does not mount or scan event data while disabled", () => {
    let statusReads = 0;
    const trackedEvent = {
      id: "tracked",
      name: "tracked-tool",
      get status() {
        statusReads += 1;
        return "running" as const;
      },
      startedAt: 1_000,
      iteration: 0,
    } satisfies LiveToolEvent;

    const { container, rerender } = render(
      <StreamingDebugger events={[trackedEvent]} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(statusReads).toBe(0);

    rerender(<StreamingDebugger events={[trackedEvent, trackedEvent]} />);

    expect(container).toBeEmptyDOMElement();
    expect(statusReads).toBe(0);
  });

  it("keeps the debugger UI and filtering available when explicitly enabled", async () => {
    window.localStorage.setItem("octopus:debug:streaming", "1");
    const user = userEvent.setup();

    render(
      <StreamingDebugger
        events={[event("running", "running"), event("failed", "error")]}
      />,
    );

    await user.click(screen.getByTitle("流式调试面板 (Ctrl+Shift+D)"));

    expect(screen.getByText(/共 2 个事件/)).toBeInTheDocument();
    expect(screen.getByText("tool-running")).toBeInTheDocument();
    expect(screen.getByText("tool-failed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "错误", exact: true }));

    expect(screen.queryByText("tool-running")).not.toBeInTheDocument();
    expect(screen.getByText("tool-failed")).toBeInTheDocument();
  });
});
