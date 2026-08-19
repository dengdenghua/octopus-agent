import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

vi.mock("./capability-market-panel", () => ({
  CapabilityMarketPanel: () => <div data-testid="cap-panel">能力面板</div>,
}));
vi.mock("./workbuddy-cloud-store-panel", () => ({
  WorkBuddyCloudStorePanel: () => <div data-testid="expert-panel">专家面板</div>,
}));
vi.mock("./registry-plugins-panel", () => ({
  RegistryPluginsPanel: () => <div data-testid="plugin-panel">插件面板</div>,
}));
vi.mock("./registry-skills-panel", () => ({
  RegistrySkillsPanel: () => <div data-testid="skill-panel">技能面板</div>,
}));

import { UnifiedMarketplacePanel } from "./unified-marketplace-panel";

describe("UnifiedMarketplacePanel", () => {
  it("合并展示 连接器·插件 / 专家 / 插件 / 技能 四个分栏,默认显示能力面板", async () => {
    renderWithProviders(<UnifiedMarketplacePanel />, { locale: "zh-CN" });

    // 四个分栏 tab 都在
    expect(screen.getByRole("tab", { name: "连接器·插件" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "专家" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "插件" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "技能" })).toBeInTheDocument();

    // 默认展示能力(连接器·插件)面板
    expect(screen.getByTestId("cap-panel")).toBeInTheDocument();
  });

  it("切换到专家分栏显示专家商城", async () => {
    renderWithProviders(<UnifiedMarketplacePanel />, { locale: "zh-CN" });
    await userEvent.click(screen.getByRole("tab", { name: "专家" }));
    expect(await screen.findByTestId("expert-panel")).toBeInTheDocument();
  });
});
