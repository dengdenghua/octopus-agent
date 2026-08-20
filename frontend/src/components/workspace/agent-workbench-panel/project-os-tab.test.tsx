import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  AgentWorkbenchPanel,
} from "../agent-workbench-panel";
import { ProjectOsTab, type ProjectFullState } from "./project-os-tab";

const projectState: ProjectFullState = {
  project: {
    id: "P-1",
    name: "PM 演示",
    goal: "做一个真实项目管理模式的演示项目",
    status: "running",
    owner: "codex",
    created_at: "2026-08-20T00:00:00Z",
    started_at: "2026-08-20T01:00:00Z",
    finished_at: "",
  },
  milestones: [
    { id: "MS1", name: "需求梳理", status: "done", priority: "P1", due_at: "2026-08-21" },
    { id: "MS2", name: "方案设计", status: "running", priority: "P1", due_at: "2026-08-22" },
  ],
  tasks: {},
  pm: {
    project_id: "P-1",
    name: "PM 演示",
    status: "running",
    overall_progress: 42,
    done_tasks: 3,
    total_tasks: 7,
    remaining_estimate: 4,
    milestones: [
      {
        id: "MS1",
        name: "需求梳理",
        status: "done",
        health: "completed",
        priority: "P1",
        due_at: "2026-08-21",
        done: 2,
        total: 2,
        failed: 0,
        progress: 100,
      },
      {
        id: "MS2",
        name: "方案设计",
        status: "running",
        health: "at_risk",
        priority: "P1",
        due_at: "2026-08-22",
        done: 1,
        total: 5,
        failed: 1,
        progress: 20,
      },
    ],
    risks: [{ type: "task", health: "at_risk", detail: "方案评审被驳回" }],
    blockers: [],
    next_actions: [
      { milestone: "MS2", task_id: "t1", task: "输出技术方案", priority: "P0", estimate: 1, due_at: "2026-08-21" },
    ],
  },
  retro: null,
  available_actions: ["run", "tick"],
  action_specs: [
    {
      action: "run",
      label: "Run",
      api: { method: "POST", path: "/api/projects/P-1/run", body: { max_ticks: 5 } },
    },
    {
      action: "tick",
      label: "Tick",
      api: { method: "POST", path: "/api/projects/P-1/tick" },
    },
  ],
};

describe("ProjectOsTab", () => {
  it("renders project name, status, milestones and actions", () => {
    renderWithProviders(
      <ProjectOsTab state={projectState} />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("PM 演示")).toBeTruthy();
    expect(screen.getByText("进行中")).toBeTruthy();
    expect(screen.getByText("需求梳理")).toBeTruthy();
    expect(screen.getByText("方案设计")).toBeTruthy();
    expect(screen.getByText("整体进度")).toBeTruthy();
    expect(screen.getByText("42%")).toBeTruthy();
    expect(screen.getByText("Run")).toBeTruthy();
    expect(screen.getByText("Tick")).toBeTruthy();
    expect(screen.getByText("打开项目管理页")).toBeTruthy();
  });

  it("renders retro when the project is finished", () => {
    renderWithProviders(
      <ProjectOsTab
        state={{
          ...projectState,
          project: { ...projectState.project, status: "done" },
          retro: {
            project_id: "P-1",
            name: "PM 演示",
            goal: "",
            status: "done",
            milestone_count: 2,
            task_count: 7,
            done_tasks: 5,
            failed_tasks: 2,
            rejected_tasks: 1,
            attempts_total: 9,
            total_estimate: 8,
            duration_days: 2,
            blocked_milestones: [],
            recommendations: ["拆分大任务"],
          },
        }}
      />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("项目复盘")).toBeTruthy();
    expect(screen.getByText("拆分大任务")).toBeTruthy();
  });
});

describe("AgentWorkbenchPanel project tab", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => projectState,
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("surfaces the 项目 tab when the thread has a bound project", async () => {
    renderWithProviders(
      <AgentWorkbenchPanel
        activeTab="project"
        events={[]}
        threadId="thread-1"
      />,
      { locale: "zh-CN" },
    );

    await waitFor(() => {
      expect(screen.getByText("PM 演示")).toBeTruthy();
    });
    expect(screen.getByText("项目")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/projects/by-thread/thread-1"),
      expect.anything(),
    );
  });

  it("falls back to the agent surface when no project is bound", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({}),
    });

    renderWithProviders(
      <AgentWorkbenchPanel
        activeTab="project"
        events={[]}
        threadId="thread-1"
      />,
      { locale: "zh-CN" },
    );

    // 无绑定项目 → 项目 tab 不出现在标签栏
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
    expect(screen.queryByText("项目")).toBeNull();
  });
});
