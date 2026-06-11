import { describe, expect, it } from "vitest";

import { stripTraceLabelPrefixes } from "./trace-labels";

describe("stripTraceLabelPrefixes", () => {
  it("removes repeated ReAct field labels without removing the content", () => {
    expect(
      stripTraceLabelPrefixes(
        "Thought: inspect the file\nAction: read_file({\"path\":\"a.ts\"})\nObservation: ok",
      ),
    ).toBe("inspect the file\nread_file({\"path\":\"a.ts\"})\nok");
  });

  it("handles bullets and Chinese labels", () => {
    expect(
      stripTraceLabelPrefixes("- \u601d\u8003: \u68c0\u67e5\u72b6\u6001\n* \u6267\u884c\uff1aweb_search({})"),
    ).toBe("\u68c0\u67e5\u72b6\u6001\nweb_search({})");
  });
});
