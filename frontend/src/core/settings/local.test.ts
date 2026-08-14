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

  it("provides safe personal-space defaults and normalizes invalid stored modes", () => {
    expect(getLocalSettings().personal_space).toEqual({
      default_folder: "",
      default_mode: "general",
      remember_last_mode: true,
      custom_instructions: "",
    });

    localStorage.setItem(
      LOCAL_SETTINGS_KEY,
      JSON.stringify({
        personal_space: {
          default_folder: "  /Users/example/Octopus  ",
          default_mode: "unknown",
          custom_instructions: "x".repeat(2100),
        },
      }),
    );

    const settings = getLocalSettings().personal_space;
    expect(settings.default_folder).toBe("/Users/example/Octopus");
    expect(settings.default_mode).toBe("general");
    expect(settings.custom_instructions).toHaveLength(2000);
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
