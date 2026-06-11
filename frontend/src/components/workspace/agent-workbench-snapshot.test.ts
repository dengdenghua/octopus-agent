import { renderHook } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import {
  buildAgentWorkbenchSnapshot,
  currentScreenFrame,
  screenBlocksForAgent,
  useAgentWorkbenchSnapshot,
} from "./agent-workbench-snapshot";

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

const deriveAgentTiles = () => [];

describe("agent workbench snapshot", () => {
  test("keeps the same version for duplicate visible state", () => {
    const events = [
      event({
        id: "read-1",
        input: { path: "src/app.tsx" },
      }),
    ];
    const { result, rerender } = renderHook(
      ({ items }: { items: LiveToolEvent[] }) =>
        useAgentWorkbenchSnapshot(items, { deriveAgentTiles }),
      { initialProps: { items: events } },
    );

    const first = result.current;
    expect(first.version).toBe(1);

    rerender({ items: [...events] });
    expect(result.current).toBe(first);
    expect(result.current.version).toBe(1);

    rerender({
      items: [
        event({
          id: "read-1",
          input: { path: "src/app.tsx" },
        }),
        event({
          id: "shell-1",
          name: "shell_command",
          status: "running",
          startedAt: 2000,
          input: { command: "pnpm test" },
        }),
      ],
    });
    expect(result.current).not.toBe(first);
    expect(result.current.version).toBe(2);
  });

  test("selects one current screen frame instead of replaying historical blocks", () => {
    const snapshot = buildAgentWorkbenchSnapshot(
      [
        event({
          id: "spawn-1",
          name: "subagent",
          lifecycle: "spawned",
          status: "running",
          agentId: "writer-a",
          subAgentRole: "writer",
          subagentCodename: "Spark-01",
        }),
        event({
          id: "read-main",
          name: "read_file",
          input: { path: "src/old.ts" },
        }),
        event({
          id: "read-agent",
          name: "read_file",
          agentId: "writer-a",
          subAgentRole: "writer",
          startedAt: 1500,
          input: { path: "agent/old.md" },
        }),
        event({
          id: "shell-main",
          name: "shell_command",
          status: "running",
          startedAt: 2000,
          input: { command: "pnpm test" },
        }),
      ],
      { deriveAgentTiles },
    );

    const mainBlocks = screenBlocksForAgent(snapshot.blocks, null);
    expect(mainBlocks.map((block) => block.id)).toEqual([
      "read-main",
      "shell-main",
    ]);
    expect(currentScreenFrame(mainBlocks).block?.id).toBe("shell-main");
    expect(currentScreenFrame(mainBlocks, "read-main").block?.id).toBe(
      "read-main",
    );

    const agentBlocks = screenBlocksForAgent(snapshot.blocks, "writer-a");
    expect(agentBlocks.map((block) => block.id)).toEqual([
      "spawn-1",
      "read-agent",
    ]);
    expect(currentScreenFrame(agentBlocks).block?.id).toBe("read-agent");
  });

  test("uses server workbench snapshot as the current-frame source", () => {
    const snapshot = buildAgentWorkbenchSnapshot(
      [
        event({
          id: "todo-server",
          name: "todo_write",
          input: {
            workbenchSnapshot: {
              schemaVersion: 2,
              version: 7,
              status: "running",
              phases: [
                {
                  id: "server-phase-1",
                  index: 1,
                  total: 2,
                  title: "Phase 1: Read docs",
                  status: "done",
                },
                {
                  id: "server-phase-2",
                  index: 2,
                  total: 2,
                  title: "Phase 2: Run tests",
                  status: "running",
                  activeItemId: "shell-server",
                },
              ],
              currentPhaseId: "server-phase-2",
              currentItemId: "shell-server",
              workspaceFocus: {
                itemId: "shell-server",
                view: "terminal",
                title: "Running tests",
              },
              updatedAt: "2026-01-01T00:00:00.000Z",
            },
          },
        }),
        event({
          id: "read-old",
          name: "read_file",
          startedAt: 1500,
          input: { path: "src/old.ts" },
        }),
        event({
          id: "shell-server",
          name: "shell_command",
          status: "running",
          startedAt: 2000,
          input: { command: "pnpm test" },
        }),
      ],
      { deriveAgentTiles },
    );

    expect(snapshot.currentPhase?.id).toBe("server-phase-2");
    expect(snapshot.currentBlock?.id).toBe("shell-server");
    expect(snapshot.focusedTab).toBe("terminal");
    expect(snapshot.phases.map((phase) => phase.id)).toEqual([
      "server-phase-1",
      "server-phase-2",
    ]);
  });

  test("keeps observed frame ids attached to their server phases", () => {
    const snapshot = buildAgentWorkbenchSnapshot(
      [
        event({
          id: "read-server",
          name: "read_file",
          input: { path: "src/context.ts" },
        }),
        event({
          id: "snapshot-1",
          name: "todo_write",
          startedAt: 1200,
          input: {
            workbenchSnapshot: {
              schemaVersion: 2,
              version: 1,
              status: "running",
              phases: [
                {
                  id: "phase-read",
                  index: 1,
                  total: 2,
                  title: "Phase 1: Read context",
                  status: "running",
                  activeItemId: "read-server",
                },
                {
                  id: "phase-test",
                  index: 2,
                  total: 2,
                  title: "Phase 2: Test",
                  status: "pending",
                },
              ],
              currentPhaseId: "phase-read",
              currentItemId: "read-server",
              updatedAt: "2026-01-01T00:00:00.000Z",
            },
          },
        }),
        event({
          id: "shell-server",
          name: "shell_command",
          status: "running",
          startedAt: 2000,
          input: { command: "pnpm test" },
        }),
        event({
          id: "snapshot-2",
          name: "todo_write",
          startedAt: 2200,
          status: "running",
          input: {
            workbenchSnapshot: {
              schemaVersion: 2,
              version: 2,
              status: "running",
              phases: [
                {
                  id: "phase-read",
                  index: 1,
                  total: 2,
                  title: "Phase 1: Read context",
                  status: "done",
                },
                {
                  id: "phase-test",
                  index: 2,
                  total: 2,
                  title: "Phase 2: Test",
                  status: "running",
                  activeItemId: "shell-server",
                },
              ],
              currentPhaseId: "phase-test",
              currentItemId: "shell-server",
              updatedAt: "2026-01-01T00:00:01.000Z",
            },
          },
        }),
      ],
      { deriveAgentTiles },
    );

    expect(snapshot.phases.map((phase) => [phase.id, phase.blockIds])).toEqual([
      ["phase-read", ["read-server"]],
      ["phase-test", ["shell-server"]],
    ]);
  });
});
