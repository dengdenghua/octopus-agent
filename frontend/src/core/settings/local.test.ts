import { beforeEach, describe, expect, it } from "vitest";

import { getLocalSettings } from "./local";

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
});
