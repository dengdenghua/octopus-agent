import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { ComposerStepProgress } from "./composer-step-progress";
import type { LiveToolEvent } from "./live-tool-timeline";
import { renderWithProviders } from "@/test/harness";

function event(partial: Partial<LiveToolEvent>): LiveToolEvent {
  return {
    id: "event-1",
    name: "todo_write",
    status: "running",
    startedAt: 1_000,
    iteration: 0,
    ...partial,
  };
}

describe("<ComposerStepProgress />", () => {
  test("shows progress from an explicit task plan and opens its details", () => {
    const onOpenDetails = vi.fn();
    renderWithProviders(
      <ComposerStepProgress
        isLoading
        events={[
          event({
            input: {
              items: [
                { content: "Inspect the project", status: "completed" },
                { content: "Implement the change", status: "in_progress" },
                { content: "Verify the result", status: "pending" },
              ],
            },
          }),
        ]}
        onOpenDetails={onOpenDetails}
      />,
    );

    const button = screen.getByRole("button", { name: /Step 2 \/ 3/ });
    expect(button).toHaveTextContent("Step 2 / 3");
    expect(button).toHaveAttribute("title", "Implement the change");

    fireEvent.click(button);
    expect(onOpenDetails).toHaveBeenCalledTimes(1);
  });

  test("does not turn generic tool activity into numbered steps", () => {
    const { container } = renderWithProviders(
      <ComposerStepProgress
        isLoading
        events={[
          event({
            name: "read_file",
            input: { path: "src/app.tsx" },
          }),
          event({
            id: "event-2",
            name: "shell_command",
            input: { command: "npm test" },
          }),
        ]}
        onOpenDetails={() => undefined}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  test("leaves the composer after a successful completed answer", () => {
    const { container } = renderWithProviders(
      <ComposerStepProgress
        hasAnswer
        runSettled
        events={[
          event({
            status: "done",
            input: {
              items: [
                { content: "Inspect the project", status: "completed" },
                { content: "Verify the result", status: "completed" },
              ],
            },
          }),
        ]}
        onOpenDetails={() => undefined}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
