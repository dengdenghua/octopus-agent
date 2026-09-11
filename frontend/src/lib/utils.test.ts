import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("UI typography class merging", () => {
  it.each(["ui", "ui-caption", "ui-body", "ui-title"])(
    "keeps the %s font size and foreground color independently",
    (size) => {
      expect(
        cn("text-sm text-muted-foreground", `text-${size} text-primary`),
      ).toBe(`text-${size} text-primary`);
      expect(cn(`text-${size} text-primary`, "text-sm")).toBe(
        "text-primary text-sm",
      );
    },
  );

  it("preserves independent responsive and interaction styles", () => {
    expect(
      cn("text-ui sm:text-ui-body hover:text-primary", "text-foreground"),
    ).toBe("text-ui sm:text-ui-body hover:text-primary text-foreground");
  });
});
