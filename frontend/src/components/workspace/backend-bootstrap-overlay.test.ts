import { describe, expect, it } from "vitest";

import { isPackagedShell } from "./backend-bootstrap-overlay";

describe("isPackagedShell", () => {
  it("recognizes the secure packaged desktop protocol", () => {
    expect(
      isPackagedShell({
        location: { protocol: "octopus-app:" },
        octopus: { isElectron: true },
      }),
    ).toBe(true);
  });

  it("rejects legacy file URLs and ordinary web sessions", () => {
    expect(
      isPackagedShell({
        location: { protocol: "file:" },
        octopus: { isElectron: true },
      }),
    ).toBe(false);
    expect(
      isPackagedShell({
        location: { protocol: "http:" },
        octopus: { isElectron: false },
      }),
    ).toBe(false);
  });
});
