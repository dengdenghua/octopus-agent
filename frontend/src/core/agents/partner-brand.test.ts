import { describe, expect, it } from "vitest";

import { localPartnerLogoUrl } from "./partner-brand";

describe("localPartnerLogoUrl", () => {
  it("uses the bundled official Claude icon instead of the fragile favicon", () => {
    expect(
      localPartnerLogoUrl("claude-code", "https://claude.ai/favicon.ico"),
    ).toContain("claude-code.png");
  });

  it("keeps API-provided icons for unknown partners", () => {
    expect(
      localPartnerLogoUrl("custom-cli", "https://example.test/logo.svg"),
    ).toBe("https://example.test/logo.svg");
  });
});
