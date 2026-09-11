import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  LAST_AGENT_WORKSPACE_ROUTE_KEY,
  WorkspaceSurfaceSwitch,
} from "./workspace-surface-switch";

afterEach(() => {
  sessionStorage.clear();
});

describe("WorkspaceSurfaceSwitch", () => {
  it("slides from the previous position when the other route remounts the header", () => {
    const original = HTMLElement.prototype.animate;
    const animate = vi.fn(() => ({ cancel: vi.fn() }));
    HTMLElement.prototype.animate = animate as unknown as typeof original;
    try {
      const first = renderWithProviders(
        <WorkspaceSurfaceSwitch active="agent" />,
        {
          initialRoute: "/workspace/realtime/new",
        },
      );
      first.unmount();
      animate.mockClear();
      const second = renderWithProviders(
        <WorkspaceSurfaceSwitch active="browser" />,
        {
          initialRoute: "/browser",
        },
      );
      expect(animate).toHaveBeenCalledWith(
        [
          { transform: "translateX(0)", width: "44px" },
          { transform: "translateX(48px)", width: "44px" },
        ],
        expect.objectContaining({ duration: 180 }),
      );
      second.unmount();
    } finally {
      if (original) HTMLElement.prototype.animate = original;
      else Reflect.deleteProperty(HTMLElement.prototype, "animate");
    }
  });
  it("links directly to the desktop browser mode", () => {
    renderWithProviders(<WorkspaceSurfaceSwitch active="agent" />, {
      initialRoute: "/workspace/realtime/thread-7?mode=team",
    });

    expect(screen.getByRole("tab", { name: "AI Browser" })).toHaveAttribute(
      "href",
      "/browser",
    );
  });

  it("remembers the active Echo route without importing the workspace shell", async () => {
    renderWithProviders(<WorkspaceSurfaceSwitch active="agent" />, {
      initialRoute: "/workspace/realtime/thread-42?mode=team",
    });

    await waitFor(() =>
      expect(sessionStorage.getItem(LAST_AGENT_WORKSPACE_ROUTE_KEY)).toBe(
        "/workspace/realtime/thread-42?mode=team",
      ),
    );
  });

  it("returns from the browser to the remembered Echo route", () => {
    sessionStorage.setItem(
      LAST_AGENT_WORKSPACE_ROUTE_KEY,
      "/workspace/realtime/thread-42?mode=team",
    );
    renderWithProviders(<WorkspaceSurfaceSwitch active="browser" />, {
      initialRoute: "/browser",
    });

    expect(screen.getByRole("tab", { name: "Echo" })).toHaveAttribute(
      "href",
      "/workspace/realtime/thread-42?mode=team",
    );
    expect(screen.getByRole("tab", { name: "AI Browser" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
