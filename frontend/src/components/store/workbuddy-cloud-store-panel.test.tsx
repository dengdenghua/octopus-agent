import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { WorkBuddyCloudStorePanel } from "./workbuddy-cloud-store-panel";

const mocks = vi.hoisted(() => ({
  listCloudStoreExperts: vi.fn(),
  listCloudStoreCategories: vi.fn(),
  installCloudExpert: vi.fn(),
  deleteAgent: vi.fn(),
  listAgents: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/core/agents/agent-world-api", () => ({
  listCloudStoreExperts: mocks.listCloudStoreExperts,
  listCloudStoreCategories: mocks.listCloudStoreCategories,
  installCloudExpert: mocks.installCloudExpert,
}));

vi.mock("@/core/agents/api", () => ({ deleteAgent: mocks.deleteAgent, listAgents: mocks.listAgents }));

vi.mock("sonner", () => ({
  toast: mocks.toast,
}));

const experts = Array.from({ length: 70 }, (_, i) => ({
  id: `wb_expert-${i}`,
  name: `expert-${i}`,
  display_name: `专家 ${i}`,
  description: `第 ${i} 位专家的简介`,
  author: "WorkBuddy(腾讯)",
  category: "research",
  category_id: "research",
  tags: ["研究", `tag-${i % 3}`],
  icon: "🧑‍💼",
  avatar_url: "",
  is_team: i % 10 === 0,
  is_installed: i < 2,
  bundle_url: `https://example.com/bundle-${i}.tar.gz`,
  quick_prompts: [`开场提问 ${i}`, "第二个开场"],
  profession: `领域 ${i % 5}`,
  source: "workbuddy-cloud",
}));

/** 卡片标题元素 = [data-slot="card-title"] 文本恰为「专家 N」。 */
function cardTitles(): HTMLElement[] {
  return Array.from(
    document.querySelectorAll('[data-slot="card"] button[aria-label] > span:first-child'),
  ).filter((el) =>
    /^专家 \d+$/.test((el.textContent || "").trim()),
  ) as HTMLElement[];
}

/** 找某位专家的卡片(标题精确匹配)。 */
function cardOf(name: string): HTMLElement {
  const title = cardTitles().find((el) => el.textContent?.trim() === name);
  if (!title) throw new Error(`card not found: ${name}`);
  return title.closest('[data-slot="card"]') as HTMLElement;
}

describe("WorkBuddyCloudStorePanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listCloudStoreExperts.mockResolvedValue({
      agents: experts,
      total: experts.length,
      page: 1,
      page_size: 500,
    });
    mocks.listCloudStoreCategories.mockResolvedValue({
      categories: [{ id: "research", name: { zh: "研究", en: "Research" } }],
      meta: { count: experts.length },
    });
    mocks.installCloudExpert.mockResolvedValue({
      installed: true,
      agent_id: "wb_expert-0",
    });
  });

  it("首屏只渲染 PAGE_SIZE(60) 张卡片,提供「加载更多」", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 0");
    await waitFor(() => expect(cardTitles().length).toBe(60));

    // 计数显示 70/70
    expect(screen.getByText(/70\/70/)).toBeInTheDocument();

    // 加载更多 → 70 张
    await user.click(screen.getByRole("button", { name: /加载更多/ }));
    await waitFor(() => expect(cardTitles().length).toBe(70));
    expect(screen.getByText(/已全部加载/)).toBeInTheDocument();
  });

  it("嵌入人才市场时只展示指定类型并使用对应分类数量", async () => {
    renderWithProviders(<WorkBuddyCloudStorePanel embedded kind="team" />, {
      locale: "zh-CN",
    });

    await screen.findByText("专家 0");
    await waitFor(() => expect(cardTitles()).toHaveLength(7));
    expect(cardTitles().map((title) => title.textContent?.trim())).toEqual([
      "专家 0",
      "专家 10",
      "专家 20",
      "专家 30",
      "专家 40",
      "专家 50",
      "专家 60",
    ]);
    expect(screen.queryByText("专家 1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "全部7" })).toBeVisible();
    expect(screen.queryByText(/7\/70/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /搜索专家/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /刷新/ }),
    ).not.toBeInTheDocument();
  });

  it("专家页复用人才市场外层搜索且不会混入专家团", async () => {
    renderWithProviders(
      <WorkBuddyCloudStorePanel embedded kind="agent" searchQuery="专家 11" />,
      { locale: "zh-CN" },
    );

    await screen.findByText("专家 11");
    expect(cardTitles().map((title) => title.textContent?.trim())).toEqual([
      "专家 11",
    ]);
    expect(screen.queryByText("专家 10")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /搜索专家/ }),
    ).not.toBeInTheDocument();
  });

  it("统一目录只用一个专家团开关过滤团队", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <WorkBuddyCloudStorePanel
        embedded
        showTypeFilter={false}
        showTeamFilter
      />,
      { locale: "zh-CN" },
    );

    await screen.findByText("专家 1");
    const categoryButtons = within(
      screen.getByTestId("workbuddy-category-scroll"),
    ).getAllByRole("button");
    expect(
      categoryButtons.slice(0, 2).map((button) => button.textContent),
    ).toEqual(["全部", "已添加"]);
    const teamFilter = screen.getByRole("button", { name: "专家团" });
    expect(teamFilter).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "已添加", exact: true }));
    expect(screen.getByRole("button", { name: "已添加", exact: true })).toHaveAttribute("aria-pressed", "true");
    await user.click(teamFilter);
    await waitFor(() => expect(cardTitles()).toHaveLength(7));
    expect(screen.queryByText("专家 1")).not.toBeInTheDocument();
    expect(teamFilter).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "已添加", exact: true })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "已添加", exact: true }));
    await user.click(screen.getByRole("button", { name: "研究" }));
    await screen.findByText("专家 1");
    expect(teamFilter).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "已添加", exact: true })).toHaveAttribute("aria-pressed", "false");
  });

  it("点击卡片打开详情弹窗,展示 quick_prompts 与安装入口", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 5");

    await user.click(cardOf("专家 5"));
    expect(await screen.findByText(/专家详情 · 专家 5/)).toBeInTheDocument();
    expect(screen.getByText("开场提问 5")).toBeInTheDocument();
    expect(screen.getByText(/第 5 位专家的简介/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /添加到我的智能体/ }),
    ).toBeInTheDocument();
  });

  it("已添加专家提供可用的管理入口", async () => {
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 0");

    expect(screen.getByRole("button", { name: "管理专家 0" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "管理专家 1" })).toBeEnabled();
  });

  it("routes template creation to the unified page without importing immediately", async () => {
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });
    await screen.findByText("专家 3");
    await userEvent.click(within(cardOf("专家 3")).getByRole("button", { name: /^添加$/ }));
    expect(window.location.hash).toBe("#/workspace/agents/new?cloudExpert=wb_expert-3");
    expect(mocks.installCloudExpert).not.toHaveBeenCalled();
  });

 it("卸载已安装专家后详情恢复安装入口", async () => {
   mocks.listAgents.mockResolvedValue([{ name: "expert_1" }]);
   mocks.deleteAgent.mockResolvedValue(undefined);
   const user = userEvent.setup();
   renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });
   await screen.findByText("专家 1");
   await user.click(cardOf("专家 1"));
   await user.click(screen.getByRole("button", { name: "更多智能体操作" }));
   await user.click(screen.getByRole("menuitem", { name: "移除智能体" }));
   expect(mocks.deleteAgent).not.toHaveBeenCalled();
   const confirmation = screen.getByRole("dialog", { name: "移除“专家 1”？" });
   await user.click(within(confirmation).getByRole("button", { name: "移除智能体", exact: true }));
   await waitFor(() => expect(mocks.deleteAgent).toHaveBeenCalledWith("expert_1"));
   expect(await screen.findByRole("button", { name: /添加到我的智能体/ })).toBeInTheDocument();
 });

});
