import { beforeEach, describe, expect, it } from "vitest";

import {
  loadComposerDraft,
  NEW_THREAD_DRAFT_KEY,
  saveComposerDraft,
} from "./composer-draft";

describe("composer-draft", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("round-trips a draft per thread", () => {
    saveComposerDraft("t-1", "写了一半的消息");
    expect(loadComposerDraft("t-1")).toBe("写了一半的消息");
    expect(loadComposerDraft("t-2")).toBeNull();
  });

  it("stores the new-thread composer under a dedicated key", () => {
    saveComposerDraft(undefined, "新会话草稿");
    expect(
      window.localStorage.getItem(`octopus:composer-draft:${NEW_THREAD_DRAFT_KEY}`),
    ).toBe("新会话草稿");
    expect(loadComposerDraft(null)).toBe("新会话草稿");
  });

  it("clears the entry when the draft is emptied", () => {
    saveComposerDraft("t-1", "abc");
    saveComposerDraft("t-1", "");
    expect(loadComposerDraft("t-1")).toBeNull();
  });

  it("never throws when storage is unavailable", () => {
    const original = window.localStorage;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: () => {
          throw new Error("denied");
        },
        setItem: () => {
          throw new Error("denied");
        },
        removeItem: () => {
          throw new Error("denied");
        },
      },
    });
    expect(() => saveComposerDraft("t-1", "x")).not.toThrow();
    expect(loadComposerDraft("t-1")).toBeNull();
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: original,
    });
  });
});
