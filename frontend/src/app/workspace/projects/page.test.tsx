import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

const toastMocks = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock("sonner", () => ({ toast: toastMocks }));
vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({ Authorization: "Bearer test-token" }),
  getToken: () => "test-token",
  jsonAuthHeaders: () => ({
    Authorization: "Bearer test-token",
    "Content-Type": "application/json",
  }),
}));
vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
  getOctopusBaseURL: () => "",
}));
vi.mock("@/components/workspace/create-project-dialog", () => ({
  CreateProjectDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="创建项目" /> : null,
}));

import ProjectsPage from "./page";

const SECRET_RUNTIME_ERROR =
  "RuntimeError: sub-agent runner not configured; call set_sub_agent_runner(fn) during bootstrap";

function jsonResponse(
  value: unknown,
  init: ResponseInit = { status: 200 },
): Response {
  return new Response(JSON.stringify(value), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...Object.fromEntries(new Headers(init.headers).entries()),
    },
  });
}

function projectDetail(options?: {
  risks?: Array<{
    type: "milestone" | "task";
    task?: string;
    milestone?: string;
    health: string;
    detail: string;
  }>;
  actions?: Array<{
    action: string;
    label: string;
    api: { method: string; path: string };
  }>;
}) {
  return {
    project: {
      id: "project-1",
      name: "Release hardening",
      goal: "Ship safely",
      status: "running",
      owner: "Eve",
      created_at: "2026-08-20T10:00:00Z",
      started_at: "2026-08-20T11:00:00Z",
      finished_at: "",
    },
    milestones: [],
    tasks: {},
    pm: {
      project_id: "project-1",
      name: "Release hardening",
      status: "running",
      overall_progress: 0,
      done_tasks: 0,
      total_tasks: 0,
      total_estimate: 0,
      remaining_estimate: 0,
      milestones: [],
      burndown: [],
      risks: options?.risks ?? [],
      blockers: [],
      overdue: [],
      next_actions: [],
      assignments: {},
    },
    retro: null,
    available_actions: [],
    action_specs: options?.actions ?? [],
  };
}

describe("ProjectsPage production error states", () => {
  const originalFetch = globalThis.fetch;
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    toastMocks.error.mockReset();
    toastMocks.success.mockReset();
    globalThis.fetch = fetchMock;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("keeps the loading state separate from empty content", () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => {}));

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.queryByText(/把目标变成一个项目/)).not.toBeInTheDocument();
  });

  it("shows a friendly list error and only exposes a safe trace id", async () => {
    fetchMock.mockResolvedValue(
      new Response(SECRET_RUNTIME_ERROR, {
        status: 500,
        headers: { "X-Request-Id": "request-safe-123" },
      }),
    );

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("项目加载失败，请稍后重试。");
    expect(alert).toHaveTextContent("追踪 ID：request-safe-123");
    expect(alert).not.toHaveTextContent(SECRET_RUNTIME_ERROR);
    expect(screen.queryByText(/把目标变成一个项目/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("uses the genuine empty state only after a successful empty response", async () => {
    fetchMock.mockResolvedValue(jsonResponse([]));

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    expect(
      screen.getByRole("heading", { level: 1, name: "项目管理" }),
    ).toBeInTheDocument();
    expect(await screen.findByText(/把目标变成一个项目/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "创建第一个项目" }),
    );
    expect(
      screen.getByRole("dialog", { name: "创建项目" }),
    ).toBeInTheDocument();
  });

  it("sanitizes detail request failures", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/projects") {
        return Promise.resolve(
          jsonResponse([
            { id: "project-1", name: "Release hardening", status: "running" },
          ]),
        );
      }
      return Promise.resolve(
        new Response(SECRET_RUNTIME_ERROR, {
          status: 500,
          headers: { "X-Trace-Id": "trace-safe-456" },
        }),
      );
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("项目加载失败，请稍后重试。");
    expect(alert).toHaveTextContent("追踪 ID：trace-safe-456");
    expect(alert).not.toHaveTextContent(SECRET_RUNTIME_ERROR);
  });

  it("replaces backend risk detail with stable user-facing copy", async () => {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/projects") {
        return Promise.resolve(
          jsonResponse([
            { id: "project-1", name: "Release hardening", status: "running" },
          ]),
        );
      }
      return Promise.resolve(
        jsonResponse(
          projectDetail({
            risks: [
              {
                type: "task",
                task: "Run delegated task",
                health: "failed",
                detail: `${SECRET_RUNTIME_ERROR}; trace_id=risk-safe-789`,
              },
            ],
          }),
        ),
      );
    });

    const { container } = renderWithProviders(<ProjectsPage />, {
      locale: "zh-CN",
    });

    expect(await screen.findByText("Run delegated task")).toBeInTheDocument();
    expect(
      screen.getByText("任务执行失败或受阻，请检查配置后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText(/追踪 ID：/)).toHaveTextContent("risk-safe-789");
    expect(container).not.toHaveTextContent(SECRET_RUNTIME_ERROR);
    expect(container.querySelector("main")).toBeNull();
  });

  it("does not put an action response body into the toast", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/projects") {
        return Promise.resolve(
          jsonResponse([
            { id: "project-1", name: "Release hardening", status: "running" },
          ]),
        );
      }
      if (url === "/api/projects/project-1/run") {
        return Promise.resolve(
          new Response(SECRET_RUNTIME_ERROR, {
            status: 500,
            headers: { "X-Trace-Id": "action-safe-321" },
          }),
        );
      }
      return Promise.resolve(
        jsonResponse(
          projectDetail({
            actions: [
              {
                action: "run",
                label: "Run project",
                api: { method: "POST", path: "/api/projects/project-1/run" },
              },
            ],
          }),
        ),
      );
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });
    await user.click(
      await screen.findByRole("button", { name: "Run project" }),
    );

    await waitFor(() =>
      expect(toastMocks.error).toHaveBeenCalledWith(
        "操作失败，请稍后重试。 追踪 ID：action-safe-321",
      ),
    );
    expect(toastMocks.error).not.toHaveBeenCalledWith(
      expect.stringContaining(SECRET_RUNTIME_ERROR),
    );
  });
});

// ─── 跨项目面板（今天要处理 / 项目总览 / 甘特 / 切换器） ────────────────

const DAY = 24 * 60 * 60 * 1000;

/** 相对「现在」构造日期，避免断言随真实时钟漂移。 */
function isoDaysFromNow(days: number, hour = 10): string {
  const d = new Date(Date.now() + days * DAY);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
}

function portfolioEntry(overrides: Record<string, unknown> = {}) {
  return {
    id: "project-1",
    name: "投资",
    goal: "跑通投资闭环",
    status: "running",
    owner: "eve",
    created_at: isoDaysFromNow(-9),
    started_at: "",
    finished_at: "",
    execution_thread_id: "",
    health: "on_track",
    readable: true,
    progress: 0,
    done_tasks: 0,
    total_tasks: 0,
    total_estimate: 0,
    remaining_estimate: 0,
    counts: {
      milestones: 0,
      risks: 0,
      blockers: 0,
      overdue: 0,
      next_actions: 0,
    },
    milestones: [],
    overdue: [],
    next_actions: [],
    risks: [],
    ...overrides,
  };
}

function portfolioMilestone(
  id: string,
  name: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    id,
    name,
    status: "running",
    health: "on_track",
    priority: "P2",
    planned_start: isoDaysFromNow(-5),
    due_at: isoDaysFromNow(5),
    done: 0,
    total: 2,
    failed: 0,
    progress: 0.25,
    remaining_estimate: 4,
    overdue_count: 0,
    ...overrides,
  };
}

function detailPayload(
  milestones: Array<Record<string, unknown>>,
  project: Record<string, unknown> = {},
) {
  return {
    project: {
      id: "project-1",
      name: "投资",
      goal: "跑通投资闭环",
      status: "running",
      owner: "eve",
      created_at: isoDaysFromNow(-9),
      started_at: "",
      finished_at: "",
      ...project,
    },
    milestones: [],
    tasks: {},
    pm: {
      project_id: "project-1",
      name: "投资",
      status: "running",
      overall_progress: 0,
      done_tasks: 0,
      total_tasks: 0,
      total_estimate: 0,
      remaining_estimate: 0,
      milestones,
      burndown: [],
      risks: [],
      blockers: [],
      overdue: [],
      next_actions: [],
      assignments: {},
    },
    retro: null,
    available_actions: [],
    action_specs: [],
  };
}

describe("ProjectsPage cross-project cockpit", () => {
  const originalFetch = globalThis.fetch;
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    toastMocks.error.mockReset();
    toastMocks.success.mockReset();
    globalThis.fetch = fetchMock;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function route(
    handlers: {
      list?: unknown;
      portfolio?: unknown;
      portfolioStatus?: number;
      detail?: unknown;
    } = {},
  ) {
    fetchMock.mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/projects") {
        return Promise.resolve(jsonResponse(handlers.list ?? []));
      }
      if (url === "/api/projects/portfolio") {
        if (handlers.portfolioStatus && handlers.portfolioStatus >= 400) {
          return Promise.resolve(
            new Response("boom", { status: handlers.portfolioStatus }),
          );
        }
        return Promise.resolve(jsonResponse(handlers.portfolio ?? []));
      }
      return Promise.resolve(
        jsonResponse(handlers.detail ?? detailPayload([])),
      );
    });
  }

  const list = [
    { id: "project-1", name: "投资", status: "running" },
    { id: "project-2", name: "规格书", status: "running" },
  ];

  it("把两个项目的逾期项聚到置顶的「今天要处理」里并标红", async () => {
    route({
      list,
      portfolio: [
        portfolioEntry({
          counts: {
            milestones: 1,
            risks: 0,
            blockers: 0,
            overdue: 2,
            next_actions: 1,
          },
          overdue: [
            {
              milestone: "deliver",
              id: "t1",
              goal: "修复登录回归",
              due_at: isoDaysFromNow(-2),
              priority: "P0",
            },
          ],
          next_actions: [
            {
              milestone: "deliver",
              task_id: "a1",
              task: "写完结论文档",
              priority: "P1",
              estimate: 1,
              due_at: isoDaysFromNow(0),
            },
          ],
        }),
        portfolioEntry({
          id: "project-2",
          name: "规格书",
          counts: {
            milestones: 0,
            risks: 0,
            blockers: 0,
            overdue: 1,
            next_actions: 0,
          },
          overdue: [
            {
              milestone: "spec",
              id: "t2",
              goal: "补齐接口清单",
              due_at: isoDaysFromNow(-1),
              priority: "P2",
            },
          ],
        }),
      ],
      detail: detailPayload([]),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    expect(await screen.findByText("今天要处理")).toBeInTheDocument();
    expect(screen.getByText("修复登录回归")).toBeInTheDocument();
    expect(screen.getByText("补齐接口清单")).toBeInTheDocument();
    expect(screen.getByText("写完结论文档")).toBeInTheDocument();
    expect(screen.getByText(/已逾期 2 天/)).toBeInTheDocument();
    expect(screen.getByText(/已逾期 1 天/)).toBeInTheDocument();
    // 「今天到期」同时是分组标题和 duePhrase(0) 的行内文案，用分组副标题断言。
    expect(screen.getByText("今天内完成")).toBeInTheDocument();
    // 逾期项用暖色容器，而不是普通卡片。
    expect(screen.getByText("修复登录回归").closest(".border-orange-500\\/25"))
      .not.toBeNull();
  });

  it("点「去处理」切到对应项目", async () => {
    const user = userEvent.setup();
    route({
      list,
      portfolio: [
        // 默认选中的是列表第一项（project-1），所以把待处理项挂在 project-2 上，
        // 点「去处理」才有可观察的切换效果。
        portfolioEntry({ id: "project-1", name: "投资" }),
        portfolioEntry({
          id: "project-2",
          name: "规格书",
          counts: {
            milestones: 0,
            risks: 0,
            blockers: 0,
            overdue: 1,
            next_actions: 0,
          },
          overdue: [
            {
              milestone: "spec",
              id: "t1",
              goal: "修复登录回归",
              due_at: isoDaysFromNow(-2),
              priority: "P0",
            },
          ],
        }),
      ],
      detail: detailPayload([], { id: "project-2", name: "规格书" }),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/projects/project-1",
        expect.anything(),
      ),
    );

    await user.click(
      await screen.findByRole("button", { name: "去处理：修复登录回归" }),
    );

    // 主视图切到 project-2 —— 请求打到 project-2 的详情接口。
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/projects/project-2",
        expect.anything(),
      ),
    );
  });

  it("没有紧急项时给出明确的「今天没有」结论而不是一片空白", async () => {
    route({
      list,
      portfolio: [portfolioEntry({ id: "project-1" })],
      detail: detailPayload([]),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    expect(
      await screen.findByText(/今天没有逾期或到期项/),
    ).toBeInTheDocument();
  });

  it("portfolio 接口挂了也不挡路：列表降级、聚合块不渲染、不额外弹 alert", async () => {
    route({
      list,
      portfolioStatus: 500,
      detail: detailPayload([]),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    // 项目仍然列得出来（降级为 /api/projects 的元数据行）。
    expect(await screen.findByText("项目（2/2）")).toBeInTheDocument();
    expect(screen.queryByText("今天要处理")).not.toBeInTheDocument();
    expect(screen.queryByText("项目总览")).not.toBeInTheDocument();
    // 只有详情请求成功，页面不应出现任何 role=alert。
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await waitFor(() => expect(toastMocks.error).not.toHaveBeenCalled());
  });

  it("两台设备都能切项目：窄屏也保留项目切换器与搜索", async () => {
    const user = userEvent.setup();
    route({
      list,
      portfolio: [
        portfolioEntry({ id: "project-1", name: "投资" }),
        portfolioEntry({ id: "project-2", name: "规格书" }),
      ],
      detail: detailPayload([]),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    const aside = await screen.findByLabelText("项目列表");
    expect(aside).toBeInTheDocument();
    // 切换器不是 `hidden md:flex` —— 窄屏下必须仍在文档流里可见。
    expect(aside.className).not.toContain("hidden");

    await user.type(screen.getByLabelText("搜索项目"), "规格");
    expect(await screen.findByText("项目（1/2）")).toBeInTheDocument();
  });

  it("≥2 个项目时给出项目总览，只有一个项目时不占用版面", async () => {
    route({
      list,
      portfolio: [
        portfolioEntry({ id: "project-1", name: "投资", progress: 0.5, total_tasks: 4, done_tasks: 2 }),
        portfolioEntry({ id: "project-2", name: "规格书" }),
      ],
      detail: detailPayload([]),
    });

    const { unmount } = renderWithProviders(<ProjectsPage />, {
      locale: "zh-CN",
    });
    expect(await screen.findByText("项目总览")).toBeInTheDocument();
    expect(screen.getByText("2 个项目")).toBeInTheDocument();
    unmount();

    route({
      list: [list[0]!],
      portfolio: [portfolioEntry({ id: "project-1", name: "投资" })],
      detail: detailPayload([]),
    });
    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });
    expect(await screen.findByText("今天要处理")).toBeInTheDocument();
    expect(screen.queryByText("项目总览")).not.toBeInTheDocument();
  });

  it("按计划开始/截止铺出里程碑时间轴，缺日期的里程碑进「未排期」", async () => {
    route({
      list: [list[0]!],
      portfolio: [portfolioEntry({ id: "project-1" })],
      detail: detailPayload([
        {
          id: "m1",
          name: "deliver",
          status: "running",
          health: "on_track",
          priority: "P2",
          planned_start: isoDaysFromNow(-5),
          due_at: isoDaysFromNow(5),
          done: 1,
          total: 4,
          failed: 0,
          progress: 0.25,
          total_estimate: 8,
          remaining_estimate: 6,
          overdue_tasks: [],
          success_criteria: [],
        },
        {
          id: "m2",
          name: "archive",
          status: "planned",
          health: "on_track",
          priority: "P3",
          planned_start: "",
          due_at: "",
          done: 0,
          total: 0,
          failed: 0,
          progress: 0,
          total_estimate: 0,
          remaining_estimate: 0,
          overdue_tasks: [],
          success_criteria: [],
        },
      ]),
    });

    const { container } = renderWithProviders(<ProjectsPage />, {
      locale: "zh-CN",
    });

    expect(await screen.findByText("里程碑时间轴")).toBeInTheDocument();
    expect(screen.getByText("今日")).toBeInTheDocument();
    expect(screen.getByText(/未排期 · 1/)).toBeInTheDocument();
    // 缺日期的里程碑不会伪造进坐标轴。
    expect(container.querySelector('[id="milestone-m2"]')).not.toBeNull();
  });

  it("点甘特条会高亮对应的里程碑卡片", async () => {
    const user = userEvent.setup();
    route({
      list: [list[0]!],
      portfolio: [portfolioEntry({ id: "project-1" })],
      detail: detailPayload([
        {
          id: "m1",
          name: "deliver",
          status: "running",
          health: "on_track",
          priority: "P2",
          planned_start: isoDaysFromNow(-5),
          due_at: isoDaysFromNow(5),
          done: 1,
          total: 4,
          failed: 0,
          progress: 0.25,
          total_estimate: 8,
          remaining_estimate: 6,
          overdue_tasks: [],
          success_criteria: [],
        },
      ]),
    });

    const { container } = renderWithProviders(<ProjectsPage />, {
      locale: "zh-CN",
    });

    const bar = await screen.findByRole("button", { name: /deliver ·/ });
    await user.click(bar);

    await waitFor(() =>
      expect(
        container.querySelector('[id="milestone-m1"]')?.className,
      ).toContain("ring-2"),
    );
  });

  it("里程碑健康度给出分布环形图与估时拆解", async () => {
    route({
      list: [list[0]!],
      portfolio: [portfolioEntry({ id: "project-1" })],
      detail: detailPayload([
        {
          id: "m1",
          name: "deliver",
          status: "running",
          health: "at_risk",
          priority: "P1",
          planned_start: isoDaysFromNow(-5),
          due_at: isoDaysFromNow(5),
          done: 1,
          total: 4,
          failed: 0,
          progress: 0.25,
          total_estimate: 8,
          remaining_estimate: 6,
          overdue_tasks: [],
          success_criteria: [],
        },
      ]),
    });

    renderWithProviders(<ProjectsPage />, { locale: "zh-CN" });

    expect(await screen.findByText("健康度分布")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: /里程碑健康度分布：共 1 个/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("里程碑估时")).toBeInTheDocument();
    expect(screen.getByText("已完成 2d · 剩余 6d")).toBeInTheDocument();
  });
});
