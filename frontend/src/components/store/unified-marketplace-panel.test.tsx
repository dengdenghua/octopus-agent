import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/harness";

vi.mock("./capability-market-panel", () => ({
  CapabilityMarketPanel: () => <div data-testid="cap-panel">插件面板</div>,
}));
vi.mock("./workbuddy-cloud-store-panel", () => ({
  WorkBuddyCloudStorePanel: () => <div data-testid="expert-panel">专家面板</div>,
}));
vi.mock("./registry-plugins-panel", () => ({
  RegistryPluginsPanel: () => <div data-testid="plugin-panel">注册表插件面板</div>,
}));
vi.mock("./registry-skills-panel", () => ({
  RegistrySkillsPanel: () => <div data-testid="skill-panel">技能面板</div>,
}));

import { UnifiedMarketplacePanel } from "./unified-marketplace-panel";

describe("UnifiedMarketplacePanel", () => {
  it("分栏统一为 插件/技能/专家,默认展示插件(能力包+注册表)", async () => {
    renderWithProviders(<UnifiedMarketplacePanel />, { locale: "zh-CN" });

    // 三个分栏(统一叫插件,无「连接器」字样)
    expect(screen.getByRole("tab", { name: "插件" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "技能" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "专家" })).toBeInTheDocument();
    expect(screen.queryByText(/连接器/)).not.toBeInTheDocument();

    // 默认插件 tab:能力包 + 注册表插件 都在
    expect(screen.getByTestId("cap-panel")).toBeInTheDocument();
    expect(screen.getByTestId("plugin-panel")).toBeInTheDocument();
  });

  it("切换到专家分栏显示专家商城", async () => {
    renderWithProviders(<UnifiedMarketplacePanel />, { locale: "zh-CN" });
    await userEvent.click(screen.getByRole("tab", { name: "专家" }));
    expect(await screen.findByTestId("expert-panel")).toBeInTheDocument();
  });
});
