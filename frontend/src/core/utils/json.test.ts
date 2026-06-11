import { describe, expect, it } from "vitest";

import { tryParseJSON } from "./json";

describe("tryParseJSON", () => {
  it("parses valid JSON", () => {
    expect(tryParseJSON('{"a":1}')).toEqual({ a: 1 });
  });

  it("parses valid JSON array", () => {
    expect(tryParseJSON("[1,2,3]")).toEqual([1, 2, 3]);
  });

  it("handles incomplete JSON gracefully (best-effort)", () => {
    const result = tryParseJSON('{"a":1, "b":');
    expect(result).toBeDefined();
    expect(result.a).toBe(1);
  });

  it("returns null for completely invalid input", () => {
    const result = tryParseJSON("not json at all }{");
    expect(result === null || result === undefined).toBe(true);
  });

  it("parses empty object", () => {
    expect(tryParseJSON("{}")).toEqual({});
  });

  it("parses string value", () => {
    expect(tryParseJSON('"hello"')).toBe("hello");
  });
});
