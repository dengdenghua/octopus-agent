import { afterEach, beforeEach, describe, expect, test } from "vitest";

import {
  modeFromProjectKind,
  readStoredModeOverride,
  writeStoredModeOverride,
} from "./mode-selector";

const STORAGE_KEY = "octopus:modeOverride";

describe("modeFromProjectKind", () => {
  test("maps builder to develop", () => {
    expect(modeFromProjectKind("builder")).toBe("develop");
  });

  test("maps coder to develop", () => {
    expect(modeFromProjectKind("coder")).toBe("develop");
  });

  test("maps architect to audit", () => {
    expect(modeFromProjectKind("architect")).toBe("audit");
  });
});

describe("readStoredModeOverride / writeStoredModeOverride", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    window.localStorage.clear();
  });

  test("returns null when nothing is stored", () => {
    expect(readStoredModeOverride("/workspace/a")).toBeNull();
  });

  test("round-trips a stored override and keeps the map structure", () => {
    writeStoredModeOverride("/workspace/a", "audit");
    writeStoredModeOverride("/workspace/b", "uxui");

    expect(readStoredModeOverride("/workspace/a")).toBe("audit");
    expect(readStoredModeOverride("/workspace/b")).toBe("uxui");

    const raw = window.localStorage.getItem(STORAGE_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!) as Record<string, string>;
    expect(parsed).toEqual({ "/workspace/a": "audit", "/workspace/b": "uxui" });
  });

  test("overwrites the override for an existing workspace path", () => {
    writeStoredModeOverride("/workspace/a", "develop");
    writeStoredModeOverride("/workspace/a", "uxui");

    expect(readStoredModeOverride("/workspace/a")).toBe("uxui");
  });

  test("returns null for an invalid stored value", () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ "/workspace/a": "invalid-mode" }),
    );
    expect(readStoredModeOverride("/workspace/a")).toBeNull();
  });

  test("returns null when stored JSON is malformed", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not valid json");
    expect(readStoredModeOverride("/workspace/a")).toBeNull();
  });

  test("no-ops on the SSR branch (window undefined)", () => {
    const originalWindow = globalThis.window;
    // Simulate server-side rendering where window is missing.
    (globalThis as { window?: unknown }).window = undefined;

    expect(readStoredModeOverride("/workspace/a")).toBeNull();
    expect(() =>
      writeStoredModeOverride("/workspace/a", "audit"),
    ).not.toThrow();

    (globalThis as { window?: unknown }).window = originalWindow;
    expect(readStoredModeOverride("/workspace/a")).toBeNull();
  });
});