import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { WorkBuddyCloudStorePanel } from "./workbuddy-cloud-store-panel";

const mocks = vi.hoisted(() => ({
  listCloudStoreExperts: vi.fn(),
  listCloudStoreCategories: vi.fn(),
  installCloudExpert: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/core/agents/agent-world-api", () => ({
  listCloudStoreExperts: mocks.listCloudStoreExperts,
  listCloudStoreCategories: mocks.listCloudStoreCategories,
  installCloudExpert: mocks.installCloudExpert,
}));

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
  return Array.from(document.querySelectorAll('[data-slot="card-title"]')).filter(
    (el) => /^专家 \d+$/.test((el.textContent || "").trim()),
  ) as HTMLElement[];
}

/** 找某位专家的卡片(标题精确匹配)。 */
function cardOf(name: string): HTMLElement {
  const title = cardTitles().find(
    (el) => el.textContent?.trim() === name,
  );
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

  it("点击卡片打开详情弹窗,展示 quick_prompts 与安装入口", async () => {
    const user = userEvent.setup();
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 5");

    await user.click(cardOf("专家 5"));
    expect(
      await screen.findByText(/专家详情 · 专家 5/),
    ).toBeInTheDocument();
    expect(screen.getByText("开场提问 5")).toBeInTheDocument();
    expect(screen.getByText(/第 5 位专家的简介/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /安装此专家/ }),
    ).toBeInTheDocument();
  });

  it("已安装专家显示「已安装」且按钮禁用", async () => {
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 0");

    // expert-0 / expert-1 已安装 → 卡片内按钮为「已安装」且 disabled
    const installedButtons = screen
      .getAllByRole("button", { name: /^已安装$/ })
      .filter((b) => (b as HTMLButtonElement).disabled);
    expect(installedButtons.length).toBeGreaterThanOrEqual(2);
  });

  it("安装走确认流:显示分步进度,成功后 toast 成功提示", async () => {
    const user = userEvent.setup();
    // 用可控 promise 模拟真实下载耗时,让进度弹窗可被断言
    let resolveInstall!: (v: unknown) => void;
    mocks.installCloudExpert.mockReturnValue(
      new Promise((res) => {
        resolveInstall = res;
      }),
    );
    renderWithProviders(<WorkBuddyCloudStorePanel />, { locale: "zh-CN" });

    await screen.findByText("专家 3");

    // 卡片内「安装」按钮(专家 3 未安装)
    const card = cardOf("专家 3");
    const installBtn = within(card).getByRole("button", { name: /^安装$/ });
    await user.click(installBtn);

    // 分步进度弹窗
    expect(await screen.findByText(/下载 bundle/)).toBeInTheDocument();
    expect(screen.getByText(/解压校验/)).toBeInTheDocument();
    expect(screen.getByText(/导入为本地 Agent/)).toBeInTheDocument();

    await waitFor(() => {
      expect(mocks.installCloudExpert).toHaveBeenCalledWith("wb_expert-3");
    });

    // 完成安装 → toast 成功提示
    resolveInstall({ installed: true, agent_id: "wb_expert-3" });
    await waitFor(() => {
      expect(mocks.toast.success).toHaveBeenCalledWith(
        "专家「专家 3」安装成功",
      );
    });
  });
});
