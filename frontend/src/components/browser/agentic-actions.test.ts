// withActionTimeout: a hung webview IPC promise must settle as a
// rejection instead of freezing the copilot loop in `busy` forever.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { withActionTimeout } from "./agentic-actions";

describe("withActionTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("passes a fast result through untouched", async () => {
    const result = withActionTimeout(Promise.resolve("ok"), "click", 1_000);
    await expect(result).resolves.toBe("ok");
  });

  it("rejects a hung promise at the deadline with the action label", async () => {
    const hung = new Promise<never>(() => {});
    const raced = withActionTimeout(hung, "click", 5_000);
    const settled = expect(raced).rejects.toThrow(
      /action timeout \(5s\): click/,
    );
    await vi.advanceTimersByTimeAsync(5_001);
    await settled;
  });

  it("propagates the underlying rejection before the deadline", async () => {
    const failing = Promise.reject(new Error("selector not found"));
    await expect(withActionTimeout(failing, "click", 5_000)).rejects.toThrow(
      "selector not found",
    );
  });

  it("clears the timer when the promise settles first", async () => {
    const spy = vi.spyOn(globalThis, "clearTimeout");
    await withActionTimeout(Promise.resolve(1), "wait", 5_000);
    expect(spy).toHaveBeenCalled();
    spy.mockRestore();
  });
});
