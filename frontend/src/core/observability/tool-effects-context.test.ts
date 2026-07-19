import { describe, expect, it } from "vitest";

import { toolEffectsRefetchInterval } from "./tool-effects-context";

describe("tool effect receipt refresh cadence", () => {
  it("stops global scans for an idle conversation", () => {
    expect(
      toolEffectsRefetchInterval(false, [{ state: "indeterminate" }]),
    ).toBe(false);
  });

  it("keeps a short recovery poll only while the turn is active", () => {
    expect(toolEffectsRefetchInterval(true, [{ state: "indeterminate" }])).toBe(
      2_000,
    );
    expect(toolEffectsRefetchInterval(true, [{ state: "committed" }])).toBe(
      10_000,
    );
  });
});
