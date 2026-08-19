import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { CapabilityMarketPanel } from "./capability-market-panel";

const mocks = vi.hoisted(() => ({
  listCapabilities: vi.fn(),
  installCapability: vi.fn(),
  uninstallCapability: vi.fn(),
  setCapabilityEnabled: vi.fn(),
  getCapabilityStatus: vi.fn(),
  connectCapability: vi.fn(),
  disconnectCapability: vi.fn(),
}));

vi.mock("@/core/agents/agent-world-api", () => ({
  listCapabilities: mocks.listCapabilities,
  installCapability: mocks.installCapability,
  uninstallCapability: mocks.uninstallCapability,
  setCapabilityEnabled: mocks.setCapabilityEnabled,
  getCapabilityStatus: mocks.getCapabilityStatus,
  connectCapability: mocks.connectCapability,
  disconnectCapability: mocks.disconnectCapability,
}));

const westock = {
  id: "westock-mcp",
  name: "westock-mcp",
  name_zh: "腾讯股票",
  description: "腾讯股票行情",
  description_zh: "腾讯股票行情",
  type: "mcp" as const,
  auth_mode: "token",
  source: "connector" as const,
  provider_id: "",
  mcp_servers: ["westock-mcp"],
  skill_count: 3,
  examples_zh: [],
  installed: true,
  enabled: false,
  version: "1.0.0",
};

const browserPlugin = {
  id: "browser",
  name: "Browser",
  name_zh: "Browser",
  description: "Control the in-app browser",
  description_zh: "控制 in-app 浏览器",
  type: "plugin" as const,
  auth_mode: "none",
  source: "codex_plugin" as const,
  author: "OpenAI",
  mcp_servers: [],
  skill_count: 1,
  installed: false,
  enabled: false,
  version: "26.810.52044",
};

describe("CapabilityMarketPanel", () => {
  it("renders connectors + plugins unified from the backend", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [westock, browserPlugin],
      total: 2,
    });
    mocks.getCapabilityStatus.mockResolvedValue({
      connected: false,
      auth_mode: "token",
    });

    renderWithProviders(<CapabilityMarketPanel />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(screen.getByText("腾讯股票")).toBeInTheDocument(),
    );
    // 连接器 + 插件都显示
    expect(screen.getByText("Browser")).toBeInTheDocument();
    expect(screen.getAllByText("连接器").length).toBeGreaterThan(0);
    expect(screen.getAllByText("插件").length).toBeGreaterThan(0);
    expect(screen.getByText("技能 ×3")).toBeInTheDocument();
    // 已安装连接器 → 连接 / 已禁用 按钮
    expect(
      screen.getByRole("button", { name: "连接" }),
    ).toBeInTheDocument();
    // 未安装插件 → 安装 按钮
    expect(
      screen.getByRole("button", { name: "安装" }),
    ).toBeInTheDocument();
    expect(mocks.listCapabilities).toHaveBeenCalledTimes(1);
  });

  it("shows install button for not-installed capabilities", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [{ ...westock, installed: false, enabled: false }],
      total: 1,
    });
    renderWithProviders(<CapabilityMarketPanel />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "安装" }),
      ).toBeInTheDocument(),
    );
  });
});
