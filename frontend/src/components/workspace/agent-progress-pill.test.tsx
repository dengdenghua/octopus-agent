import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { AgentProgressPill } from "./agent-progress-pill";
import type { LiveToolEvent } from "./live-tool-timeline";
import { renderWithProviders } from "@/test/harness";

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

describe("<AgentProgressPill />", () => {
  test("does not render for transport-only events", () => {
    const { container } = renderWithProviders(
      <AgentProgressPill
        events={[
          event({ id: "transport-1", name: "turn_request" }),
          event({ id: "transport-2", name: "response_stream" }),
        ]}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  test("shows current progress and expands inline without a workspace shortcut", () => {
    renderWithProviders(
      <AgentProgressPill
        events={[
          event({
            id: "read-1",
            name: "read_file",
            input: { path: "src/app.tsx" },
          }),
          event({
            id: "shell-1",
            name: "shell_command",
            status: "running",
            startedAt: 2000,
            input: { command: "npm run typecheck" },
          }),
        ]}
      />,
    );

    const pill = screen.getByRole("button", {
      name: /Current Progress 2\/2/,
    });
    expect(screen.getByText("Current Progress 2/2")).toBeInTheDocument();
    expect(screen.getByText(/Phase 2:/)).toBeInTheDocument();

    fireEvent.click(pill);
    expect(pill).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.queryByRole("button", { name: "Open Workspace" }),
    ).not.toBeInTheDocument();
  });

  test("minimizes one task into a single progress bead and restores from it", () => {
    renderWithProviders(
      <AgentProgressPill
        events={[
          event({
            id: "read-1",
            name: "read_file",
            iteration: 0,
            input: { path: "src/app.tsx" },
          }),
          event({
            id: "shell-1",
            name: "shell_command",
            status: "done",
            iteration: 1,
            startedAt: 2000,
            input: { command: "npm run typecheck" },
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Minimize Progress" }));
    expect(screen.queryByText("Current Progress 2/2")).not.toBeInTheDocument();
    const bead = screen.getByRole("button", { name: "Restore Progress" });
    expect(bead).toHaveClass("bg-muted-foreground/45");
    expect(bead.childElementCount).toBe(0);

    fireEvent.click(bead);
    expect(
      screen.getByRole("button", { name: /Current Progress 2\/2/ }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  test("uses a themed breathing bead while minimized work is still running", () => {
    renderWithProviders(
      <AgentProgressPill
        events={[
          event({
            id: "read-1",
            name: "read_file",
            iteration: 0,
            input: { path: "src/app.tsx" },
          }),
          event({
            id: "shell-1",
            name: "shell_command",
            status: "running",
            iteration: 1,
            startedAt: 2000,
            input: { command: "npm run typecheck" },
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Minimize Progress" }));

    const bead = screen.getByRole("button", { name: "Restore Progress" });
    expect(bead).toHaveClass("bg-primary/70");
    expect(bead.querySelector("[aria-hidden='true']")).toHaveClass(
      "animate-pulse",
      "bg-primary/15",
    );
  });

  test("keeps a manually minimized plan minimized across remounts until the plan changes", () => {
    const progressScopeKey = "agent-progress-pill:minimized-plan-remount";
    const planEvents = [
      event({
        id: "todo-1",
        name: "todo_write",
        status: "running",
        input: {
          items: [
            { content: "collect material", status: "completed" },
            { content: "write report", status: "in_progress" },
          ],
        },
      }),
    ];

    const first = renderWithProviders(
      <AgentProgressPill
        progressScopeKey={progressScopeKey}
        events={planEvents}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Minimize Progress" }));
    expect(
      screen.getByRole("button", { name: "Restore Progress" }),
    ).toBeInTheDocument();
    first.unmount();

    const second = renderWithProviders(
      <AgentProgressPill
        progressScopeKey={progressScopeKey}
        events={[
          event({
            id: "todo-2",
            name: "todo_write",
            status: "running",
            input: {
              items: [
                { content: "collect material", status: "completed" },
                { content: "write report", status: "completed" },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.queryByText("Current Progress 2/2")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Restore Progress" }),
    ).toBeInTheDocument();
    second.unmount();

    renderWithProviders(
      <AgentProgressPill
        progressScopeKey={progressScopeKey}
        events={[
          event({
            id: "todo-3",
            name: "todo_write",
            status: "running",
            input: {
              items: [
                { content: "confirm scope", status: "completed" },
                { content: "run new research", status: "in_progress" },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.getByText("Current Progress 2/2")).toBeInTheDocument();
  });

  test("auto-minimizes completed runs into a small progress bead", () => {
    renderWithProviders(
      <AgentProgressPill
        hasAnswer
        runSettled
        events={[
          event({
            id: "read-1",
            name: "read_file",
            iteration: 0,
            input: { path: "src/app.tsx" },
          }),
          event({
            id: "shell-1",
            name: "shell_command",
            status: "done",
            iteration: 1,
            startedAt: 2000,
            input: { command: "npm run typecheck" },
          }),
        ]}
      />,
    );

    expect(screen.queryByText("Current Progress 2/2")).not.toBeInTheDocument();
    const bead = screen.getByRole("button", { name: "Restore Progress" });
    expect(bead).toHaveAttribute("title", "Current Progress 2/2");

    fireEvent.click(bead);

    expect(
      screen.getByRole("button", { name: /Current Progress 2\/2/ }),
    ).toHaveAttribute("aria-expanded", "true");
  });

  test("uses active todo text when todo_write drives the current step", () => {
    renderWithProviders(
      <AgentProgressPill
        events={[
          event({
            id: "todo-1",
            name: "todo_write",
            status: "running",
            input: {
              items: [
                { content: "collect material", status: "completed" },
                {
                  content: "check and fix",
                  activeForm: "create board deck - check and fix",
                  status: "in_progress",
                },
              ],
            },
          }),
        ]}
      />,
    );

    expect(
      screen.getByText("Phase 2: create board deck - check and fix"),
    ).toBeInTheDocument();
  });

  test("does not mark stale pending todo steps as failed after a settled answer", () => {
    const { container } = renderWithProviders(
      <AgentProgressPill
        hasAnswer
        runSettled
        events={[
          event({
            id: "todo-1",
            name: "todo_write",
            status: "done",
            input: {
              items: [
                { content: "create plan", status: "completed" },
                { content: "run research", status: "pending" },
              ],
            },
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Restore Progress" }));

    expect(screen.getAllByText("Phase 2: run research").length).toBeGreaterThan(
      0,
    );
    expect(container.querySelector(".animate-spin")).toBeNull();
    expect(container.querySelector(".text-destructive")).toBeNull();
  });

  test("keeps approval running while an interim answer exists", () => {
    renderWithProviders(
      <AgentProgressPill
        hasAnswer
        events={[
          event({
            id: "approval-1",
            name: "write_text_file",
            status: "waiting_approval",
            input: { path: "plan.md" },
          }),
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: /Current Progress 1\/2/ }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Phase 1:/)).toBeInTheDocument();
  });

  test("does not keep a stale approval running after the run settles", () => {
    renderWithProviders(
      <AgentProgressPill
        hasAnswer
        runSettled
        events={[
          event({
            id: "approval-1",
            name: "write_text_file",
            status: "waiting_approval",
            input: { path: "plan.md" },
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Restore Progress" }));

    expect(
      screen.getByRole("button", { name: /Current Progress 2\/2/ }),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Phase 2:/).length).toBeGreaterThan(0);
  });
});
