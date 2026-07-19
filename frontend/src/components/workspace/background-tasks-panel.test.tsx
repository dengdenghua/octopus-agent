import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BackgroundTask } from "@/core/background/types";
import { renderWithProviders } from "@/test/harness";

import {
  BackgroundTasksPanel,
  BackgroundTasksTrigger,
} from "./background-tasks-panel";

const hookMocks = vi.hoisted(() => ({
  useBackgroundTasks: vi.fn(),
  useBackgroundTaskOutput: vi.fn(),
}));

vi.mock("@/core/background/hooks", () => hookMocks);

const actions = {
  refresh: vi.fn(),
  submit: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
  remove: vi.fn(),
};

function task(
  overrides: Partial<BackgroundTask> & Pick<BackgroundTask, "task_id">,
): BackgroundTask {
  const now = Date.now();
  return {
    task_id: overrides.task_id,
    name: "后台任务",
    prompt: "整理本周项目进展",
    assistant_id: "general",
    thread_id: "thread-12345678",
    status: "running",
    created_at: new Date(now - 180_000).toISOString(),
    updated_at: new Date(now - 120_000).toISOString(),
    heartbeat_at: null,
    started_at: new Date(now - 150_000).toISOString(),
    finished_at: null,
    error: null,
    output_count: 0,
    max_duration: 3600,
    max_iterations: 20,
    extra: {},
    ...overrides,
  };
}

function mockTaskList(tasks: BackgroundTask[]) {
  hookMocks.useBackgroundTasks.mockReturnValue({
    tasks,
    loading: false,
    error: null,
    ...actions,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockTaskList([]);
  hookMocks.useBackgroundTaskOutput.mockReturnValue({
    messages: [],
    done: false,
    doneStatus: null,
  });
});

describe("BackgroundTasksPanel", () => {
  it("exposes a localized trigger that opens the panel", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BackgroundTasksTrigger />, { locale: "zh-CN" });

    await user.click(screen.getByRole("button", { name: "后台任务" }));
    expect(
      screen.getByRole("dialog", { name: "后台任务" }),
    ).toBeInTheDocument();
  });

  it("replaces raw backend errors with a localized recoverable state", async () => {
    const user = userEvent.setup();
    hookMocks.useBackgroundTasks.mockReturnValue({
      tasks: [],
      loading: false,
      error: "Failed to list tasks: Not Found",
      ...actions,
    });

    renderWithProviders(<BackgroundTasksPanel open onOpenChange={vi.fn()} />, {
      locale: "zh-CN",
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "后台任务加载失败，请稍后重试。",
    );
    expect(
      screen.queryByText("Failed to list tasks: Not Found"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试" }));
    expect(actions.refresh).toHaveBeenCalledOnce();
  });

  it("localizes its empty and create-task states with associated labels", async () => {
    const user = userEvent.setup();
    renderWithProviders(<BackgroundTasksPanel open onOpenChange={vi.fn()} />, {
      locale: "zh-CN",
    });

    expect(
      screen.getByRole("dialog", { name: "后台任务" }),
    ).toBeInTheDocument();
    expect(screen.getByText("暂无任务")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "关闭" })).toBeInTheDocument();

    const createButtons = screen.getAllByRole("button", { name: "新建任务" });
    await user.click(createButtons.at(-1)!);

    expect(
      screen.getByRole("textbox", { name: "任务名称" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "提示词" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回" })).toBeInTheDocument();
  });

  it("supports keyboard-focusable task selection and confirms destructive actions", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    const runningTask = task({ task_id: "running-task", name: "运行报告" });
    const completedTask = task({
      task_id: "completed-task",
      name: "季度报告",
      status: "completed",
      finished_at: new Date().toISOString(),
    });
    mockTaskList([runningTask, completedTask]);
    hookMocks.useBackgroundTaskOutput.mockReturnValue({
      messages: [],
      done: true,
      doneStatus: "completed",
    });

    renderWithProviders(<BackgroundTasksPanel open onOpenChange={vi.fn()} />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("1 个进行中")).toBeInTheDocument();
    expect(screen.getAllByText("2 分钟前")).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: /运行报告/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /季度报告/ }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(confirmSpy).toHaveBeenCalledWith("确定要取消后台任务“运行报告”吗？");
    expect(actions.cancel).toHaveBeenCalledWith("running-task");

    await user.click(screen.getByRole("button", { name: "删除" }));
    expect(confirmSpy).toHaveBeenCalledWith(
      "确定要永久删除后台任务“季度报告”吗？",
    );
    expect(actions.remove).toHaveBeenCalledWith("completed-task");

    await user.click(screen.getByRole("button", { name: /季度报告/ }));
    expect(screen.getByText("任务状态：已完成")).toBeInTheDocument();
    expect(screen.getByText("对话:")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回" })).toBeInTheDocument();

    confirmSpy.mockRestore();
  });
});
