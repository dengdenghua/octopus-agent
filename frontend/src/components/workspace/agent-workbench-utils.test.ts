import { describe, expect, test } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import { diffEntriesFromBlocks } from "./agent-workbench-utils";
import { toWorkBlocks } from "./work-blocks";

function event(partial: Partial<LiveToolEvent>): LiveToolEvent {
  return {
    id: "event-1",
    name: "read_file",
    status: "done",
    startedAt: 1_000,
    iteration: 0,
    ...partial,
  };
}

describe("agent workbench diff entries", () => {
  test("does not classify read-only source evidence as changed files", () => {
    const blocks = toWorkBlocks([
      event({
        id: "read-runtime",
        input: { path: "runtime/core/cerebrum/react_loop.py" },
        output: { content: "def stream_react_loop(): ..." },
      }),
      event({
        id: "read-frontend",
        input: { path: "frontend/src/core/realtime/items.ts" },
        output: { content: "export interface AgentMessageItem {}" },
      }),
    ]);

    expect(blocks.every((block) => block.kind === "read")).toBe(true);
    expect(diffEntriesFromBlocks(blocks)).toEqual([]);
  });

  test("keeps real file mutations in the changed-file surface", () => {
    const blocks = toWorkBlocks([
      event({
        id: "write-frontend",
        name: "write_file",
        input: { path: "frontend/src/app.tsx", content: "export default App" },
        output: {
          path: "frontend/src/app.tsx",
          diff: "--- a/frontend/src/app.tsx\n+++ b/frontend/src/app.tsx\n@@ -1 +1 @@",
        },
      }),
    ]);

    expect(diffEntriesFromBlocks(blocks)).toMatchObject([
      { path: "frontend/src/app.tsx", status: "done" },
    ]);
  });
});
