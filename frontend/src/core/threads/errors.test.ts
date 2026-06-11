import { describe, expect, it } from "vitest";

import { getStreamErrorMessage } from "./errors";

describe("getStreamErrorMessage", () => {
  it("maps missing stream endpoints to a product message", () => {
    expect(
      getStreamErrorMessage(new Error("Stream failed: 404"), "friendly"),
    ).toBe("friendly");
  });

  it("maps unavailable stream endpoints to a product message", () => {
    expect(
      getStreamErrorMessage({ message: "Stream failed: 503" }, "friendly"),
    ).toBe("friendly");
  });

  it("preserves specific non-endpoint errors", () => {
    expect(getStreamErrorMessage("Model timed out", "friendly")).toBe(
      "Model timed out",
    );
  });
});
