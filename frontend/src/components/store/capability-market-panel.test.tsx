import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

const documentsPlugin = {
  ...browserPlugin,
  id: "documents",
  name: "Documents",
  name_zh: "文档",
  description: "Create and edit documents",
  description_zh: "创建和编辑文档",
};

const sheetsPlugin = {
  ...browserPlugin,
  id: "spreadsheets",
  name: "Spreadsheets",
  name_zh: "表格",
  description: "Create spreadsheets",
  description_zh: "创建电子表格",
};

describe("CapabilityMarketPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getCapabilityStatus.mockResolvedValue({
      connected: false,
      auth_mode: "token",
    });
  });

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
    // 连接器 + 插件统一展示,不再出现「连接器」字样
    expect(screen.getByText("Browser")).toBeInTheDocument();
    expect(screen.queryByText(/连接器/)).not.toBeInTheDocument();
    expect(screen.getByText("技能 ×3")).toBeInTheDocument();
    // 已安装插件(连接器) → 连接 / 已禁用 按钮
    expect(screen.getByRole("button", { name: "连接" })).toBeInTheDocument();
    // 未安装插件 → 安装 按钮
    expect(screen.getByRole("button", { name: "安装" })).toBeInTheDocument();
    expect(mocks.listCapabilities).toHaveBeenCalledTimes(1);
  });

  it("shows install button for not-installed capabilities", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [{ ...westock, installed: false, enabled: false }],
      total: 1,
    });
    renderWithProviders(<CapabilityMarketPanel />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "安装" })).toBeInTheDocument(),
    );
  });

  it("按显式 ID 顺序展示精选并限制数量", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [browserPlugin, documentsPlugin, sheetsPlugin],
      total: 3,
    });

    const { container } = renderWithProviders(
      <CapabilityMarketPanel
        view="featured"
        featuredIds={["documents", "browser", "spreadsheets"]}
        maxItems={2}
        showToolbar={false}
      />,
      { locale: "zh-CN" },
    );

    await waitFor(() => expect(screen.getByText("文档")).toBeInTheDocument());
    const ids = Array.from(
      container.querySelectorAll<HTMLElement>("[data-capability-id]"),
    ).map((card) => card.dataset.capabilityId);
    expect(ids).toEqual(["documents", "browser"]);
    expect(screen.queryByText("表格")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("搜索插件")).not.toBeInTheDocument();
  });

  it("installed 视图只展示已安装应用", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [westock, browserPlugin],
      total: 2,
    });

    const { container } = renderWithProviders(
      <CapabilityMarketPanel view="installed" showToolbar={false} />,
      { locale: "zh-CN" },
    );

    await waitFor(() =>
      expect(screen.getByText("腾讯股票")).toBeInTheDocument(),
    );
    expect(
      container.querySelector('[data-capability-id="westock-mcp"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-capability-id="browser"]'),
    ).not.toBeInTheDocument();
  });

  it("外部搜索词在隐藏工具栏时仍然生效", async () => {
    mocks.listCapabilities.mockResolvedValue({
      capabilities: [westock, browserPlugin],
      total: 2,
    });

    renderWithProviders(
      <CapabilityMarketPanel searchQuery="in-app 浏览器" showToolbar={false} />,
      { locale: "zh-CN" },
    );

    await waitFor(() =>
      expect(screen.getByText("Browser")).toBeInTheDocument(),
    );
    expect(screen.queryByText("腾讯股票")).not.toBeInTheDocument();
  });
});
