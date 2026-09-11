import { useLocation } from "react-router-dom";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { CloudSkillsPanel } from "./cloud-skills-panel";

const mocks = vi.hoisted(() => ({
  fetchCloudSkills: vi.fn(),
  fetchCloudInstalled: vi.fn(),
  fetchUnifiedAssets: vi.fn(),
  streamInstallCloudSkill: vi.fn(),
  manageCloudSkill: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/core/agents/agent-world-api", () => ({
  fetchCloudSkills: mocks.fetchCloudSkills,
  fetchCloudInstalled: mocks.fetchCloudInstalled,
  fetchUnifiedAssets: mocks.fetchUnifiedAssets,
  streamInstallCloudSkill: mocks.streamInstallCloudSkill,
  manageCloudSkill: mocks.manageCloudSkill,
}));

vi.mock("sonner", () => ({ toast: mocks.toast }));

describe("CloudSkillsPanel", () => {
  it("shows role users, expands their names and filters unlinked installed skills", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({ items: [] });
    mocks.fetchCloudInstalled.mockResolvedValue({
      skills: ["plugin-creator", "skill-creator"],
      plugins: [],
      local_skills: ["plugin-creator", "skill-creator"].map((name) => ({
        id: name,
        name,
        source: "builtin",
        kind: "skill",
      })),
      skill_users: {
        "skill-creator": [
          { id: "eve", name: "Eve" },
          { id: "leon", name: "Leon" },
          { id: "raven", name: "Raven" },
        ],
      },
    });
    renderWithProviders(<CloudSkillsPanel />);
    await userEvent.click(
      await screen.findByRole("button", { name: "查看 技能创建器 的使用角色" }),
    );
    const roleSection = within(screen.getByRole("dialog")).getByRole("region", {
      name: "角色使用者",
    });
    expect(within(roleSection).getByText("Raven")).toBeVisible();
    expect(within(roleSection).getByText(/不代表实际调用次数/)).toBeVisible();
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "关闭" }),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "角色关联" }),
      "unlinked",
    );
    expect(screen.getByText("插件创建器")).toBeVisible();
    expect(screen.queryByText("技能创建器")).not.toBeInTheDocument();
    expect(screen.getByText("未关联角色", { selector: "span" })).toBeVisible();
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "角色关联" }),
      "linked",
    );
    expect(screen.getByText("技能创建器")).toBeVisible();
    expect(screen.queryByText("插件创建器")).not.toBeInTheDocument();
  });

  it("does not claim roles are unused when association data is unavailable", async () => {
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("writing");
    expect(screen.getByRole("combobox", { name: "角色关联" })).toBeDisabled();
    expect(
      screen.queryByText("未关联角色", { selector: "span" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("角色关联未加载").length).toBeGreaterThan(0);
  });

  it("disables and restores a built-in without offering uninstall", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({ items: [] });
    let enabled = true;
    mocks.fetchCloudInstalled.mockImplementation(async () => ({
      skills: ["plugin-creator"],
      plugins: [],
      local_skills: [
        {
          id: "plugin-creator",
          name: "plugin-creator",
          source: "builtin",
          kind: "skill",
        },
      ],
      skill_states: {
        "plugin-creator": { enabled, can_toggle: true, can_uninstall: false },
      },
    }));
    mocks.manageCloudSkill.mockImplementation(async (_name, action) => {
      enabled = action === "enable";
    });
    renderWithProviders(<CloudSkillsPanel />);
    await userEvent.click(
      await screen.findByRole("button", { name: "管理 插件创建器" }),
    );
    expect(
      screen.queryByRole("button", { name: "卸载技能" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "停用技能" }));
    await screen.findByRole("button", { name: "恢复启用" });
    expect(
      screen.queryByRole("button", { name: "使用技能" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "恢复启用" }));
    expect(
      await screen.findByRole("button", { name: "使用技能" }),
    ).toBeEnabled();
    expect(mocks.manageCloudSkill).toHaveBeenNthCalledWith(
      1,
      "plugin-creator",
      "disable",
    );
    expect(mocks.manageCloudSkill).toHaveBeenNthCalledWith(
      2,
      "plugin-creator",
      "enable",
    );
  });

  it("confirms uninstall of the chosen downloaded version and offers installation again", async () => {
    const name = "external-download";
    mocks.fetchCloudSkills.mockResolvedValue({
      items: [{ name, source: "minimax-design", description: "download" }],
    });
    let installed = true;
    mocks.fetchCloudInstalled.mockImplementation(async () => ({
      skills: installed ? [name] : [],
      plugins: [],
      local_skills: installed
        ? [{ id: name, name, source: "local", kind: "skill" }]
        : [],
      skill_states: installed
        ? { [name]: { enabled: true, can_toggle: true, can_uninstall: true } }
        : {},
    }));
    mocks.manageCloudSkill.mockImplementation(async () => {
      installed = false;
    });
    renderWithProviders(<CloudSkillsPanel />);
    await userEvent.click(
      await screen.findByRole("button", { name: "管理 external download" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "卸载技能" }));
    expect(mocks.manageCloudSkill).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "确认卸载" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(await screen.findByRole("button", { name: "安装" })).toBeEnabled();
    expect(mocks.manageCloudSkill).toHaveBeenCalledWith(name, "uninstall");
  });

  it("shows bundled creator tools as installed in developer tools without downloading", async () => {
    const names = ["skill-creator", "plugin-creator", "agent-generator"];
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string }) => ({
        items:
          opts.source === "external"
            ? []
            : [{ name: "agent-generator", description: "Generate an agent" }],
      }),
    );
    mocks.fetchCloudInstalled.mockResolvedValue({
      skills: names,
      plugins: [],
      local_skills: names.map((name) => ({
        id: name,
        name,
        kind: "skill",
        source: "builtin",
        description: name,
      })),
    });
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("插件创建器");
    await userEvent.click(screen.getByRole("button", { name: "开发工具" }));
    for (const name of ["技能创建器", "插件创建器", "智能体生成器"]) {
      expect(
        screen.getByRole("button", { name: `使用 ${name}` }),
      ).toBeEnabled();
    }
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(
      screen.queryByRole("button", { name: "安装" }),
    ).not.toBeInTheDocument();
    expect(mocks.streamInstallCloudSkill).not.toHaveBeenCalled();
  });

  it("loads remote repositories independently and filters by source", async () => {
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string }) =>
        opts.source === "external"
          ? {
              items: [
                {
                  name: "external-test",
                  display_name: "Remote Design",
                  description: "Design guidance",
                  external: true,
                  source: "anthropic",
                  repository: "anthropics/skills",
                },
              ],
              meta: {
                sources: [
                  { source: "anthropic", state: "ready", count: 1 },
                  { source: "openai", state: "unavailable", count: 0 },
                ],
              },
            }
          : { items: [{ name: "echo-demo", description: "Echo demo" }] },
    );
    const user = userEvent.setup();
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });
    await screen.findByText("Remote Design");
    expect(screen.getByText(/OpenAI 官方：暂不可用/)).toBeVisible();
    const sources = screen.getByRole("combobox", { name: "技能源" });
    await user.selectOptions(sources, "anthropic");
    expect(screen.getByText("Remote Design")).toBeVisible();
    expect(screen.queryByText("echo demo")).not.toBeInTheDocument();
    await user.selectOptions(sources, "local");
    expect(screen.getByText("local only")).toBeVisible();
    expect(screen.queryByText("Remote Design")).not.toBeInTheDocument();
  });

  it("uses Skills.sh search matches even when the title has no literal keyword", async () => {
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string; search?: string }) =>
        opts.source === "external"
          ? {
              items: [
                {
                  name: "external-matched",
                  display_name: "UX Workflow",
                  description: "Guidance",
                  external: true,
                  source: "skills.sh",
                  search_match: opts.search,
                },
              ],
            }
          : { items: [] },
    );
    const user = userEvent.setup();
    renderWithProviders(<CloudSkillsPanel searchQuery="frontend" />, {
      locale: "zh-CN",
    });
    await screen.findByText("UX Workflow");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "技能源" }),
      "skills.sh",
    );
    expect(screen.getByText("UX Workflow")).toBeVisible();
    expect(mocks.fetchCloudSkills).toHaveBeenCalledWith(
      expect.objectContaining({ source: "external", search: "frontend" }),
    );
  });

  it("opens a draft using the installed alias without sending a message", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({
      items: [
        { name: "writing-cloud", aliases: ["writing"], description: "Writer" },
      ],
    });
    function LocationProbe() {
      const location = useLocation();
      return (
        <output data-testid="location">
          {location.pathname}
          {location.search}
        </output>
      );
    }
    renderWithProviders(
      <>
        <CloudSkillsPanel />
        <LocationProbe />
      </>,
    );
    const row = (await screen.findByText("writing cloud")).closest(
      '[role="listitem"]',
    )!;
    await userEvent.click(within(row).getByRole("button", { name: /^使用 / }));
    const location = screen.getByTestId("location").textContent!;
    expect(location.split("?")[0]).toBe("/workspace/realtime/new");
    expect(new URLSearchParams(location.split("?")[1]).get("prompt")).toBe(
      "@skill:writing\n",
    );
    expect(mocks.streamInstallCloudSkill).not.toHaveBeenCalled();
  });

  it("loads results in batches and resets the batch when filtering", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({
      items: Array.from({ length: 85 }, (_, i) => ({
        name: `sample-${i}`,
        description: "Demo",
      })),
    });
    mocks.fetchUnifiedAssets.mockResolvedValue({ items: [] });
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("sample 0");
    expect(screen.getAllByRole("listitem")).toHaveLength(40);
    await userEvent.click(screen.getByRole("button", { name: "加载更多" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(80);
    const filter = screen.getByRole("group", { name: "技能安装状态" });
    await userEvent.click(
      within(filter).getByRole("button", { name: "已安装", exact: true }),
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    await userEvent.click(
      within(filter).getByRole("button", { name: "全部", exact: true }),
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(40);
  });

  it("groups same-name sources while keeping installation identities independent", async () => {
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string }) => ({
        items:
          opts.source === "external"
            ? [
                {
                  name: "external-openai-pdf",
                  original_name: "pdf",
                  display_name: "pdf",
                  external: true,
                  source: "openai",
                  description: "OpenAI PDF",
                },
                {
                  name: "external-anthropic-pdf",
                  original_name: "pdf",
                  display_name: "pdf",
                  external: true,
                  source: "anthropic",
                  description: "Anthropic PDF",
                },
              ]
            : [{ name: "pdf", source: "echo", description: "echo PDF" }],
      }),
    );
    mocks.fetchUnifiedAssets.mockResolvedValue({
      items: [{ id: "pdf", name: "pdf", kind: "skill", source: "local" }],
    });
    mocks.streamInstallCloudSkill.mockResolvedValue({ installed: true });
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("echo · 3 个来源版本");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("已安装 1 · 当前目录 1")).toBeVisible();
    await userEvent.click(
      screen.getByRole("button", { name: "查看 pdf 详情" }),
    );
    const dialog = screen.getByRole("dialog");
    const select = within(dialog).getByRole("combobox", { name: "来源版本" });
    await userEvent.selectOptions(select, "cloud:external-openai-pdf");
    expect(within(dialog).getByText("OpenAI PDF")).toBeVisible();
    expect(
      within(dialog).queryByRole("button", { name: "使用技能" }),
    ).not.toBeInTheDocument();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "安装技能" }),
    );
    await waitFor(() =>
      expect(mocks.streamInstallCloudSkill).toHaveBeenCalledWith(
        "external-openai-pdf",
        expect.any(Function),
      ),
    );
    await within(dialog).findByRole("button", { name: "使用技能" });
    await userEvent.selectOptions(select, "cloud:external-anthropic-pdf");
    expect(
      within(dialog).getByRole("button", { name: "安装技能" }),
    ).toBeEnabled();
    expect(within(dialog).getByText("Anthropic PDF")).toBeVisible();
    await userEvent.click(
      within(dialog).getByRole("button", { name: "关闭", exact: true }),
    );
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "技能源" }),
      "anthropic",
    );
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Anthropic PDF")).toBeVisible();
    expect(screen.getByRole("button", { name: "选择来源" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "使用 pdf" }),
    ).not.toBeInTheDocument();
  });

  it("does not group different original names just because display titles match", async () => {
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string }) => ({
        items:
          opts.source === "external"
            ? [
                {
                  name: "external-second",
                  original_name: "document-audit",
                  display_name: "pdf",
                  external: true,
                  source: "openai",
                  description: "Audit",
                },
              ]
            : [{ name: "pdf", source: "echo", description: "Create" }],
      }),
    );
    mocks.fetchUnifiedAssets.mockResolvedValue({ items: [] });
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("Audit");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("installs Design packages and retains tool requirements and original platform", async () => {
    mocks.fetchCloudSkills.mockImplementation(
      async (opts: { source?: string }) => ({
        items:
          opts.source === "external"
            ? [
                {
                  name: "external-design-story",
                  original_name: "story",
                  display_name: "短剧分镜",
                  description: "规划镜头",
                  tags: ["短剧漫剧"],
                  source: "minimax-design",
                  external: true,
                  catalog_only: false,
                  compatibility: "图像、视频生成需配置对应工具",
                  version: "1.2.3",
                  source_url: "https://design.minimaxi.com/",
                },
              ]
            : [],
      }),
    );
    mocks.fetchUnifiedAssets.mockResolvedValue({ items: [] });
    renderWithProviders(<CloudSkillsPanel />);
    await screen.findByText("短剧分镜");
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "技能源" }),
      "minimax-design",
    );
    expect(screen.getByRole("button", { name: "安装" })).toBeEnabled();
    await userEvent.click(
      screen.getByRole("button", { name: "查看 external-design-story 详情" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("link", {
        name: "查看来源",
      }),
    ).toHaveAttribute("href", "https://design.minimaxi.com/");
    expect(
      within(dialog).getByText("图像、视频生成需配置对应工具"),
    ).toBeVisible();
    mocks.streamInstallCloudSkill.mockImplementation(
      async (name, onProgress) => {
        onProgress({ phase: "completed", progress: 100, message: "安装完成" });
        return { installed: true, name };
      },
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "安装技能" }),
    );
    await waitFor(() =>
      expect(mocks.streamInstallCloudSkill).toHaveBeenCalledWith(
        "external-design-story",
        expect.any(Function),
      ),
    );
    expect(
      await within(dialog).findByRole("button", { name: /使用/ }),
    ).toBeEnabled();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchCloudSkills.mockResolvedValue({
      total: 2,
      items: [
        { name: "writing", description: "云端写作技能", version: "1.0.0" },
        { name: "research", description: "云端研究技能", version: "1.0.0" },
      ],
    });
    mocks.fetchCloudInstalled.mockResolvedValue({ skills: [], plugins: [] });
    mocks.fetchUnifiedAssets.mockResolvedValue({
      total: 2,
      summary: { counts: { skill: 2 } },
      items: [
        {
          id: "writing",
          name: "writing",
          kind: "skill",
          source: "local",
          description: "本地写作技能",
        },
        {
          id: "local-only",
          name: "local-only",
          kind: "skill",
          source: "codex",
          description: "仅存在于本地",
        },
      ],
    });
  });

  it("filters merged Chinese and English categories without duplicate options", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({
      items: [
        { name: "english-course", tags: ["education"], description: "English" },
        {
          name: "chinese-course",
          tags: ["教育", "education"],
          description: "Chinese",
        },
        {
          name: "frontend-kit",
          tags: ["frontend", "full-stack"],
          description: "Code",
        },
      ],
    });
    const user = userEvent.setup();
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });
    await screen.findByText("english course");
    const category = screen.getByRole("group", { name: "技能分类" });
    expect(
      within(category).getAllByRole("button", { name: "教育学习" }),
    ).toHaveLength(1);
    expect(
      within(category).queryByRole("button", { name: "education" }),
    ).not.toBeInTheDocument();
    await user.click(
      within(category).getByRole("button", { name: "教育学习" }),
    );
    expect(screen.getByText("english course")).toBeVisible();
    expect(screen.getByText("chinese course")).toBeVisible();
    expect(screen.queryByText("frontend kit")).not.toBeInTheDocument();
    await user.click(
      within(category).getByRole("button", { name: "开发工具" }),
    );
    expect(screen.getByText("frontend kit")).toBeVisible();
    expect(screen.queryByText("english course")).not.toBeInTheDocument();
    await user.click(
      within(category).getByRole("button", { name: "其他技能" }),
    );
    expect(screen.getByText("local only")).toBeVisible();
  });

  it("uses live local inventory even when the materialized asset index is missing", async () => {
    mocks.fetchUnifiedAssets.mockRejectedValue(new Error("HTTP 404"));
    mocks.fetchCloudInstalled.mockResolvedValue({
      skills: ["writing", "local-only"],
      plugins: [],
      local_skills: [
        { id: "writing", name: "writing", kind: "skill", source: "builtin" },
        {
          id: "local-only",
          name: "local-only",
          kind: "skill",
          source: "local",
        },
      ],
    });
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });
    await screen.findByText("已安装 2 · 当前目录 3");
    expect(screen.getAllByText("writing")).toHaveLength(1);
    const card = screen.getByText("local only").closest('[role="listitem"]');
    expect(within(card!).getByRole("button", { name: /^使用 / })).toBeEnabled();
  });

  it("matches cloud package aliases to existing local names", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({
      items: [
        {
          name: "writing-1234567890",
          display_name: "writing",
          aliases: ["writing"],
          description: "Writer",
        },
      ],
    });
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });
    await screen.findByText("已安装 2 · 当前目录 2");
    expect(screen.getAllByText("writing")).toHaveLength(1);
    expect(screen.queryByText("writing 1234567890")).not.toBeInTheDocument();
  });

  it("merges cloud and local skills and marks local matches as installed", async () => {
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });

    const writingCard = (await screen.findByText("writing")).closest(
      '[role="listitem"]',
    );
    const localOnlyCard = screen
      .getByText("local only")
      .closest('[role="listitem"]');
    expect(writingCard).not.toBeNull();
    expect(localOnlyCard).not.toBeNull();
    expect(
      within(writingCard!).getByRole("button", { name: /^使用 / }),
    ).toBeEnabled();
    expect(
      within(localOnlyCard!).getByRole("button", { name: /^使用 / }),
    ).toBeEnabled();
    expect(screen.getByText("已安装 2 · 当前目录 3")).toBeVisible();
  });

  it("streams installation progress and commits the installed state", async () => {
    mocks.streamInstallCloudSkill.mockImplementation(
      async (
        name: string,
        onProgress: (event: Record<string, unknown>) => void,
      ) => {
        onProgress({ phase: "installing", progress: 45, message: "正在下载" });
        onProgress({
          phase: "completed",
          progress: 100,
          message: "安装完成",
          result: { installed: true, name, path: `/skills/${name}` },
        });
        return { installed: true, name, path: `/skills/${name}` };
      },
    );
    const user = userEvent.setup();
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });

    const researchCard = (await screen.findByText("research")).closest(
      '[role="listitem"]',
    );
    await user.click(
      within(researchCard!).getByRole("button", { name: "安装" }),
    );

    await waitFor(() => {
      expect(mocks.streamInstallCloudSkill).toHaveBeenCalledWith(
        "research",
        expect.any(Function),
      );
      expect(
        within(researchCard!).getByRole("button", { name: /^使用 / }),
      ).toBeEnabled();
    });
    expect(mocks.toast.success).toHaveBeenCalledWith("技能「research」已安装");
  });

  it("keeps installation totals stable when a search has no matches", async () => {
    const clearSearch = vi.fn();
    renderWithProviders(
      <CloudSkillsPanel
        searchQuery="no-such-skill"
        onClearSearch={clearSearch}
      />,
      { locale: "zh-CN" },
    );
    expect(await screen.findByText("已安装 2 · 当前目录 3")).toBeVisible();
    expect(screen.getByText("0 个结果")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "查看全部技能" }));
    expect(clearSearch).toHaveBeenCalledOnce();
  });

  it("filters installed skills and cleans metadata markers in details", async () => {
    mocks.fetchCloudSkills.mockResolvedValue({
      items: [
        { name: "writing", description: "|" },
        { name: "research", description: "研究" },
      ],
    });
    renderWithProviders(<CloudSkillsPanel />, { locale: "zh-CN" });
    await screen.findByText("writing");
    await userEvent.click(
      within(screen.getByRole("group", { name: "技能安装状态" })).getByRole(
        "button",
        { name: "已安装" },
      ),
    );
    expect(screen.queryByText("research")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "查看 writing 详情" }),
    );
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByText("|")).not.toBeInTheDocument();
    expect(
      within(dialog).getByText("暂无用途说明，可查看来源与版本。"),
    ).toBeVisible();
  });
});
