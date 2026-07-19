import { act, screen } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";
import type * as ReactRouterDom from "react-router-dom";

import { renderWithProviders } from "@/test/harness";
import { STUB_RESPONSE_EVENT } from "@/core/api/client";
import { eventBus } from "@/core/events";

import WorkspaceLayout from "./layout";

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof ReactRouterDom>("react-router-dom");
  return {
    ...actual,
    Outlet: () => {
      const location = actual.useLocation();
      return (
        <div data-testid="workspace-location">
          {location.pathname}
          {location.search}
        </div>
      );
    },
  };
});

vi.mock("@/components/workspace/workspace-sidebar", () => ({
  WorkspaceSidebar: () => <aside>sidebar</aside>,
}));

describe("<WorkspaceLayout /> stub response banner", () => {
  afterEach(() => {
    eventBus.clear();
    vi.unstubAllGlobals();
  });

  test("does not show stub response banners by default", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => null),
    });
    renderWithProviders(<WorkspaceLayout />, { locale: "zh-CN" });

    act(() => {
      window.dispatchEvent(
        new CustomEvent(STUB_RESPONSE_EVENT, {
          detail: { method: "GET", path: "/api/account/usage" },
        }),
      );
    });

    expect(screen.queryByText("模拟后端响应")).not.toBeInTheDocument();
  });

  test("shows stub response banners when debug flag is enabled", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) =>
        key === "octopus.debug.showStubResponses" ? "true" : null,
      ),
    });
    renderWithProviders(<WorkspaceLayout />, { locale: "zh-CN" });

    act(() => {
      window.dispatchEvent(
        new CustomEvent(STUB_RESPONSE_EVENT, {
          detail: { method: "GET", path: "/api/account/usage" },
        }),
      );
    });

    expect(screen.getByText("模拟后端响应")).toBeInTheDocument();
  });

  test("preserves agent and project identity when starting a fresh task", () => {
    renderWithProviders(<WorkspaceLayout />, {
      initialRoute: "/workspace/realtime/existing",
      locale: "zh-CN",
    });

    act(() => {
      eventBus.emit("task:new", {
        agentId: "coder",
        workspacePath: "/Users/dangbei/Public/octopus-agent",
      });
    });

    expect(screen.getByTestId("workspace-location").textContent).toBe(
      "/workspace/realtime/new?agent=coder&workspace_path=%2FUsers%2Fdangbei%2FPublic%2Foctopus-agent",
    );
  });
});
