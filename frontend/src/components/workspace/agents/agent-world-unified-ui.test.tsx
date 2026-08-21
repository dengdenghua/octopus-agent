import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";
import { renderWithProviders } from "@/test/harness";

const listStoreAgentsMock = vi.hoisted(() => vi.fn());

vi.mock("@/core/agents/agent-world-api", () => ({
  importAgentFromPack: vi.fn(),
  installAgent: vi.fn(),
  listStoreAgents: listStoreAgentsMock,
  previewAgentPack: vi.fn(),
}));

import {
  AgentWorldUnified,
  AgentsTab,
  resolveHubMarketRoute,
} from "./agent-world-unified";

const emptyCounts = new Map([
  ["all" as const, 0],
  ["assistant" as const, 0],
  ["coder" as const, 0],
  ["researcher" as const, 0],
  ["creative" as const, 0],
  ["automation" as const, 0],
  ["specialist" as const, 0],
  ["financial" as const, 0],
]);

beforeEach(() => {
  listStoreAgentsMock.mockReset();
  listStoreAgentsMock.mockResolvedValue({ agents: [] });
});

function renderAgentsTab({
  loading = false,
  loadError = false,
  onRetry = vi.fn(),
}: {
  loading?: boolean;
  loadError?: boolean;
  onRetry?: () => void;
} = {}) {
  renderWithProviders(
    <AgentsTab
      agents={[]}
      filteredAgents={[]}
      loading={loading}
      loadError={loadError}
      activeCategory="all"
      categoryCounts={emptyCounts}
      onCategoryChange={vi.fn()}
      onSelectAgent={vi.fn()}
      onInstallChange={vi.fn()}
      onRetry={onRetry}
    />,
    { locale: "zh-CN" },
  );
}

describe("Agent Hub role list states", () => {
  it("announces loading without exposing empty controls", () => {
    renderAgentsTab({ loading: true });
    expect(screen.getByRole("status")).toHaveTextContent("正在加载角色");
    expect(screen.queryByRole("button", { name: "全部" })).toBeNull();
  });

  it("keeps a failed load recoverable", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    renderAgentsTab({ loadError: true, onRetry });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "角色列表加载失败，请稍后重试。",
    );
    await user.click(screen.getByRole("button", { name: "重新加载" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("exposes category selection state without counts polluting names", () => {
    renderAgentsTab();
    expect(screen.getByRole("group", { name: "按角色类型筛选" })).toBeVisible();
    expect(screen.getByRole("button", { name: "全部" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "编程" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});

describe("HUB market shell", () => {
  it("opens on a focused market landing page", () => {
    renderWithProviders(
      <SidebarProvider>
        <AgentWorldUnified />
      </SidebarProvider>,
      {
        initialRoute: "/workspace/agents",
        locale: "zh-CN",
      },
    );

    expect(screen.getByRole("tab", { name: "精选" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "人才市场" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "应用市场" })).toBeVisible();
    expect(screen.getByRole("button", { name: "我的库" })).toBeVisible();
    expect(screen.getByRole("button", { name: /发布/ })).toBeVisible();
    expect(screen.queryByText(/统一资产/)).toBeNull();
  });

  it("keeps legacy HUB tabs mapped into the new market hierarchy", () => {
    expect(resolveHubMarketRoute("?tab=agents")).toEqual({
      section: "agents",
      applicationView: "featured",
    });
    expect(resolveHubMarketRoute("?tab=plugins")).toEqual({
      section: "applications",
      applicationView: "all",
    });
    expect(resolveHubMarketRoute("?tab=skills")).toEqual({
      section: "applications",
      applicationView: "all",
    });
    expect(resolveHubMarketRoute("?tab=assets")).toEqual({
      section: "applications",
      applicationView: "library",
    });
  });

  it("returns to the featured landing page when the HUB link clears a legacy tab", async () => {
    function NavigableHub() {
      const navigate = useNavigate();
      return (
        <>
          <button
            type="button"
            onClick={() => navigate("/workspace/agents?surface=chat")}
          >
            返回 HUB
          </button>
          <SidebarProvider>
            <AgentWorldUnified />
          </SidebarProvider>
        </>
      );
    }

    renderWithProviders(<NavigableHub />, {
      initialRoute: "/workspace/agents?tab=plugins",
      locale: "zh-CN",
    });

    expect(screen.getByRole("tab", { name: "应用市场" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "全部应用" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await userEvent.click(screen.getByRole("button", { name: "返回 HUB" }));

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "精选" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
  });

  it("leaves the HUD deep-link surface free of marketplace chrome", () => {
    renderWithProviders(<AgentWorldUnified />, {
      initialRoute: "/workspace/agents?hud=1&agent=eve",
      locale: "zh-CN",
    });

    expect(screen.queryByTestId("hub-market-navigation")).toBeNull();
  });
});
