import { act, renderHook } from "@testing-library/react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { useResizablePanel } from "./use-resizable-panel";

afterEach(() => {
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  localStorage.removeItem("resize-cancel-test");
});

it.each(["blur", "Escape"])(
  "cancels a drag on %s without persisting or expanding",
  (reason) => {
    const onDragEnd = vi.fn();
    const onDragMove = vi.fn();
    localStorage.setItem("resize-cancel-test", "500");
    document.body.style.cursor = "crosshair";
    document.body.style.userSelect = "text";
    const { result, unmount } = renderHook(() =>
      useResizablePanel({
        storageKey: "resize-cancel-test",
        minPx: 300,
        maxPx: 1000,
        defaultCssWidth: "500px",
        viewportWidth: 1440,
        fallbackPx: 500,
        clamp: (px) => Math.max(300, Math.min(1000, px)),
        onDragEnd,
        onDragMove,
      }),
    );
    const panel = document.createElement("aside");
    const handle = panel.appendChild(document.createElement("div"));
    vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
      width: 500,
    } as DOMRect);
    act(() =>
      result.current.handleMouseDown({
        button: 0,
        target: handle,
        clientX: 900,
        preventDefault: vi.fn(),
      } as unknown as ReactMouseEvent),
    );
    act(() =>
      document.dispatchEvent(new MouseEvent("mousemove", { clientX: 100 })),
    );
    act(() => {
      if (reason === "blur") window.dispatchEvent(new Event("blur"));
      else
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
      document.dispatchEvent(new MouseEvent("mouseup"));
    });
    expect(result.current.resolvedPx).toBe(500);
    expect(onDragMove).toHaveBeenLastCalledWith(500);
    expect(onDragEnd).not.toHaveBeenCalled();
    expect(localStorage.getItem("resize-cancel-test")).toBe("500");
    expect(document.body.style.cursor).toBe("crosshair");
    expect(document.body.style.userSelect).toBe("text");
    unmount();
  },
);
