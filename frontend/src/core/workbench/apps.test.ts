import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  resetWorkspaceWebShortcutCache,
  setWorkspaceWebShortcut,
  useWorkspaceWebShortcuts,
  workspaceWebAppRoute,
} from "./apps";

describe("workspace web shortcuts", () => {
  beforeEach(() => {
    localStorage.clear();
    resetWorkspaceWebShortcutCache();
  });

  it("pins, updates and removes a browser app for the workspace sidebar", () => {
    const { result } = renderHook(() => useWorkspaceWebShortcuts());

    act(() => {
      setWorkspaceWebShortcut(
        { name: "ChatGPT", url: "https://chatgpt.com/" },
        true,
      );
    });
    expect(result.current).toEqual([
      {
        id: "web:https://chatgpt.com/",
        name: "ChatGPT",
        url: "https://chatgpt.com/",
      },
    ]);

    act(() => {
      setWorkspaceWebShortcut(
        { name: "GPT", url: "https://chatgpt.com/" },
        true,
      );
    });
    expect(result.current).toHaveLength(1);
    expect(result.current[0]?.name).toBe("GPT");

    act(() => {
      setWorkspaceWebShortcut(
        { name: "GPT", url: "https://chatgpt.com/" },
        false,
      );
    });
    expect(result.current).toEqual([]);
  });

  it("rejects unsafe non-web targets", () => {
    const { result } = renderHook(() => useWorkspaceWebShortcuts());
    act(() => {
      setWorkspaceWebShortcut(
        { name: "Bad", url: "javascript:alert(1)" },
        true,
      );
    });
    expect(result.current).toEqual([]);
  });

  it("builds a workspace-local embedded app route", () => {
    expect(
      workspaceWebAppRoute({
        name: "ChatGPT",
        url: "https://chatgpt.com/?model=gpt-5",
      }),
    ).toBe(
      "/workspace/web-app?url=https%3A%2F%2Fchatgpt.com%2F%3Fmodel%3Dgpt-5&title=ChatGPT",
    );
  });
});
