import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useHistoryDraft } from "./use-history-draft";

it("prepares only this thread's draft and releases the listener on navigation", () => {
  const setDraft = vi.fn();
  const view = renderHook(() => useHistoryDraft("current", setDraft));
  const dispatch = (detail: unknown) =>
    window.dispatchEvent(new CustomEvent("octopus:edit-message", { detail }));
  dispatch({ threadId: "another", text: "private" });
  dispatch({ threadId: "current", text: null });
  expect(setDraft).not.toHaveBeenCalled();
  dispatch({ threadId: "current", text: "edited" });
  expect(setDraft).toHaveBeenCalledExactlyOnceWith("edited");
  view.unmount();
  dispatch({ threadId: "current", text: "stale" });
  expect(setDraft).toHaveBeenCalledTimes(1);
});
