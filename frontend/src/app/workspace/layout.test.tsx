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

  test("applies the active persona's illustration palette to the workspace", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) =>
        key === "octopus.active-agent" ? "market_researcher" : null,
      ),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    });

    renderWithProviders(<WorkspaceLayout />, { locale: "zh-CN" });

    expect(screen.getByText("sidebar").parentElement).toHaveAttribute(
      "data-persona-theme",
      "noah",
    );
  });

  test("renders design chat as an embedded surface without duplicating the sidebar", () => {
    renderWithProviders(<WorkspaceLayout />, {
      initialRoute: "/workspace/realtime/new?embedded=design",
      locale: "zh-CN",
    });

    expect(screen.queryByText("sidebar")).not.toBeInTheDocument();
    expect(screen.getByTestId("workspace-location").textContent).toBe(
      "/workspace/realtime/new?embedded=design",
    );
    expect(
      screen
        .getByTestId("workspace-location")
        .closest('[data-slot="sidebar-wrapper"]'),
    ).not.toBeNull();
  });

  test("renders desktop apps as embedded workspaces without duplicating the sidebar", () => {
    renderWithProviders(<WorkspaceLayout />, {
      initialRoute: "/workspace/storage?library=images&embedded=app",
      locale: "zh-CN",
    });

    expect(screen.queryByText("sidebar")).not.toBeInTheDocument();
    expect(screen.getByTestId("workspace-location").textContent).toBe(
      "/workspace/storage?library=images&embedded=app",
    );
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
        workspacePath: "/Users/example/Public/octopus-agent",
      });
    });

    expect(screen.getByTestId("workspace-location").textContent).toBe(
      "/workspace/realtime/new?agent=coder&workspace_path=%2FUsers%2Fexample%2FPublic%2Foctopus-agent",
    );
  });

  test("starts a fresh Design task in place and preserves its project scope", () => {
    renderWithProviders(<WorkspaceLayout />, {
      initialRoute:
        "/workspace/design?thread=old&project=project-1&name=Launch&design_stage=storyboard",
      locale: "zh-CN",
    });

    act(() => {
      eventBus.emit("task:new", undefined);
    });

    const location = screen.getByTestId("workspace-location").textContent || "";
    expect(location).toContain("/workspace/design?");
    expect(location).toContain("project=project-1");
    expect(location).toContain("name=Launch");
    expect(location).toContain("new_task=");
    expect(location).not.toContain("thread=old");
    expect(location).not.toContain("design_stage");
  });
});
