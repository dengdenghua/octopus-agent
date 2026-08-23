import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  LAST_AGENT_WORKSPACE_ROUTE_KEY,
  WorkspaceSurfaceSwitch,
} from "./workspace-surface-switch";

afterEach(() => {
  sessionStorage.clear();
});

describe("WorkspaceSurfaceSwitch", () => {
  it("links directly to the standalone browser route", () => {
    renderWithProviders(<WorkspaceSurfaceSwitch active="agent" />, {
      initialRoute: "/workspace/realtime/thread-7?mode=team",
    });

    expect(screen.getByRole("tab", { name: "AI Browser" })).toHaveAttribute(
      "href",
      "/browser",
    );
  });

  it("remembers the active EchoAI route without importing the workspace shell", async () => {
    renderWithProviders(<WorkspaceSurfaceSwitch active="agent" />, {
      initialRoute: "/workspace/realtime/thread-42?mode=team",
    });

    await waitFor(() =>
      expect(sessionStorage.getItem(LAST_AGENT_WORKSPACE_ROUTE_KEY)).toBe(
        "/workspace/realtime/thread-42?mode=team",
      ),
    );
  });

  it("returns from the browser to the remembered EchoAI route", () => {
    sessionStorage.setItem(
      LAST_AGENT_WORKSPACE_ROUTE_KEY,
      "/workspace/realtime/thread-42?mode=team",
    );
    renderWithProviders(<WorkspaceSurfaceSwitch active="browser" />, {
      initialRoute: "/browser",
    });

    expect(screen.getByRole("tab", { name: "EchoAI" })).toHaveAttribute(
      "href",
      "/workspace/realtime/thread-42?mode=team",
    );
    expect(screen.getByRole("tab", { name: "AI Browser" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
