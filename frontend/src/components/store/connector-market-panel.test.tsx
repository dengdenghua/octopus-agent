import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { ConnectorMarketPanel } from "./connector-market-panel";

const mocks = vi.hoisted(() => ({
  listConnectors: vi.fn(),
  installConnector: vi.fn(),
  uninstallConnector: vi.fn(),
  enableConnector: vi.fn(),
  disableConnector: vi.fn(),
  getConnectorStatus: vi.fn(),
  connectConnector: vi.fn(),
  disconnectConnector: vi.fn(),
}));

vi.mock("@/core/agents/agent-world-api", () => ({
  listConnectors: mocks.listConnectors,
  installConnector: mocks.installConnector,
  uninstallConnector: mocks.uninstallConnector,
  enableConnector: mocks.enableConnector,
  disableConnector: mocks.disableConnector,
  getConnectorStatus: mocks.getConnectorStatus,
  connectConnector: mocks.connectConnector,
  disconnectConnector: mocks.disconnectConnector,
}));

const westock = {
  id: "westock-mcp",
  name: "westock-mcp",
  name_zh: "腾讯股票",
  description: "腾讯股票行情",
  description_zh: "腾讯股票行情",
  type: "mcp" as const,
  auth_mode: "token",
  source: "workbuddy",
  provider_id: "",
  mcp_servers: ["westock-mcp"],
  skill_count: 3,
  examples_zh: [],
  installed: true,
  enabled: false,
  version: "1.0.0",
};

describe("ConnectorMarketPanel", () => {
  it("renders the connector grid from the backend", async () => {
    mocks.listConnectors.mockResolvedValue({ connectors: [westock], total: 1 });
    mocks.getConnectorStatus.mockResolvedValue({
      connector_id: "westock-mcp",
      auth_mode: "token",
      connected: false,
    });

    renderWithProviders(<ConnectorMarketPanel />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(screen.getByText("腾讯股票")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("MCP").length).toBeGreaterThan(0);
    expect(screen.getByText("技能 ×3")).toBeInTheDocument();
    expect(screen.getByText("未连接")).toBeInTheDocument();
    // 已安装 → 显示 连接 与 启用 按钮,而不是 安装
    expect(
      screen.getByRole("button", { name: "连接" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "已禁用" }),
    ).toBeInTheDocument();
    expect(mocks.listConnectors).toHaveBeenCalledTimes(1);
  });

  it("shows install button for not-installed connectors", async () => {
    mocks.listConnectors.mockResolvedValue({
      connectors: [{ ...westock, installed: false, enabled: false }],
      total: 1,
    });
    renderWithProviders(<ConnectorMarketPanel />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "安装" }),
      ).toBeInTheDocument(),
    );
  });
});
