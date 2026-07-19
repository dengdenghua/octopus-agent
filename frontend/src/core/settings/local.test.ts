import { beforeEach, describe, expect, it } from "vitest";

import {
  clearThreadModelReferences,
  getLocalSettings,
  getThreadModelName,
  saveThreadModelName,
} from "./local";

const LOCAL_SETTINGS_KEY = "octopus.local-settings";

describe("local settings defaults", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults chat capability mode to react", () => {
    expect(getLocalSettings().context.mode).toBe("react");
  });

  it("normalizes persisted chat mode to react", () => {
    localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({
        context: {
          mode: "chat",
        },
      }),
    );

    expect(getLocalSettings().context.mode).toBe("react");
  });

  it("clears only thread overrides that reference a deleted model", () => {
    saveThreadModelName("thread-a", "removed-model");
    saveThreadModelName("thread-b", "kept-model");
    saveThreadModelName("thread-c", "removed-model");

    expect(clearThreadModelReferences("removed-model")).toBe(2);
    expect(getThreadModelName("thread-a")).toBeUndefined();
    expect(getThreadModelName("thread-b")).toBe("kept-model");
    expect(getThreadModelName("thread-c")).toBeUndefined();
  });
});
