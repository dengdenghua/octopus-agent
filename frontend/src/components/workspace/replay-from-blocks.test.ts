import { describe, expect, it } from "vitest";

import type { LiveToolEvent } from "./live-tool-timeline";
import { buildReplayFromBlocks, redactSecrets } from "./replay-from-blocks";
import type { WorkBlock, WorkBlockKind } from "./work-blocks";

function block(
  over: Partial<Omit<WorkBlock, "kind" | "event">> & {
    kind: WorkBlockKind;
    event?: Partial<LiveToolEvent>;
  },
): WorkBlock {
  const event: LiveToolEvent = {
    id: over.id ?? "e1",
    name: "tool",
    status: "done",
    startedAt: 0,
    iteration: 0,
    ...over.event,
  };
  return {
    id: over.id ?? "b1",
    event,
    kind: over.kind,
    title: over.title ?? "title",
    subtitle: over.subtitle ?? "",
    status: over.status ?? "done",
    startedAt: 0,
    inputText: over.inputText ?? "",
    outputText: over.outputText ?? "",
  };
}

describe("buildReplayFromBlocks", () => {
  it("maps blocks into steps preserving kind/title/subtitle/status", () => {
    const data = buildReplayFromBlocks(
      [block({ kind: "file", title: "edit auth.ts", subtitle: "src/auth.ts", status: "done" })],
      { title: "Run" },
    );
    expect(data.title).toBe("Run");
    expect(data.steps).toHaveLength(1);
    expect(data.steps[0]).toMatchObject({
      kind: "file",
      title: "edit auth.ts",
      subtitle: "src/auth.ts",
      status: "done",
    });
  });

  it("renders a terminal step body as `$ cmd` plus output", () => {
    const data = buildReplayFromBlocks(
      [
        block({
          kind: "terminal",
          title: "shell",
          event: { input: { command: "ls -la" } },
          outputText: "file1\nfile2",
        }),
      ],
      { title: "Run" },
    );
    expect(data.steps[0].body).toBe("$ ls -la\nfile1\nfile2");
  });

  it("drops sub-agent lifecycle blocks", () => {
    const data = buildReplayFromBlocks(
      [
        block({ id: "a", kind: "agent", title: "spawn", event: { lifecycle: "spawned" } }),
        block({ id: "b", kind: "terminal", title: "real step", outputText: "ok" }),
      ],
      { title: "Run" },
    );
    expect(data.steps.map((s) => s.title)).toEqual(["real step"]);
  });

  it("inlines a screenshot only when it is already a data-URL", () => {
    const withData = buildReplayFromBlocks(
      [block({ kind: "browser", title: "shot", event: { output: { screenshot: "data:image/png;base64,AAA" } } })],
      { title: "Run" },
    );
    expect(withData.steps[0].image).toBe("data:image/png;base64,AAA");

    const withUrl = buildReplayFromBlocks(
      [block({ kind: "browser", title: "shot", event: { output: { screenshot: "https://x/y.png" } } })],
      { title: "Run" },
    );
    expect(withUrl.steps[0].image).toBeUndefined();
  });

  it("truncates an overlong body", () => {
    const huge = "x".repeat(5000);
    const data = buildReplayFromBlocks(
      [block({ kind: "terminal", title: "t", event: { input: { command: "echo" } }, outputText: huge })],
      { title: "Run" },
    );
    expect(data.steps[0].body!.length).toBeLessThan(1300);
    expect(data.steps[0].body!.endsWith("…")).toBe(true);
  });

  it("passes meta through to the replay data", () => {
    const data = buildReplayFromBlocks([block({ kind: "file", title: "x" })], {
      title: "My run",
      footer: "2026-06-13",
      brand: "Octopus",
    });
    expect(data).toMatchObject({ title: "My run", footer: "2026-06-13", brand: "Octopus" });
  });
});

describe("redactSecrets", () => {
  it("scrubs api keys, bearer tokens, jwts and long hex", () => {
    expect(redactSecrets("key sk-abcdefABCDEF0123456789")).toContain("«redacted-token»");
    expect(redactSecrets("Authorization: Bearer abcdefghijklmnop")).toContain("«redacted-bearer»");
    expect(
      redactSecrets(
        "t=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36",
      ),
    ).toContain("«redacted-jwt»");
    expect(redactSecrets('password = "hunter2secret"')).toContain("«redacted»");
    expect(redactSecrets(`x ${"a".repeat(40)}`)).toContain("«redacted-hex»");
  });

  it("leaves ordinary text untouched", () => {
    const text = "ran pnpm test, 12 passed in 3.2s";
    expect(redactSecrets(text)).toBe(text);
  });
});
