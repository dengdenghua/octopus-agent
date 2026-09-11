import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { existsSync } from "node:fs";
import { renderWithProviders } from "@/test/harness";
import { DEPARTMENT_SCENARIOS, DepartmentScenarios, resolveDepartment } from "./department-scenarios";
import type { Agent } from "@/core/agents/types";
const mocks = vi.hoisted(() => ({ navigate: vi.fn(), preset: vi.fn(), list: vi.fn() }));
vi.mock("react-router-dom", async importOriginal => ({ ...await importOriginal<object>(), useNavigate: () => mocks.navigate }));
vi.mock("@/core/agents/api", () => ({ listAgents: mocks.list }));
vi.mock("@/core/collaboration/task-collaborator-preset", () => ({ writeTaskCollaboratorPreset: mocks.preset, taskCollaboratorRouteForLeader: () => "/workspace/realtime/new" }));
describe("department templates", () => {
  it("renders general and department scenarios under one heading", async () => {
    mocks.list.mockResolvedValue([]);
    const onLaunch = vi.fn();
    const view = renderWithProviders(<DepartmentScenarios additional={[{ id: "general-test", title: "通用协作", roles: [["general", "协调员"]], flow: "任务协调", output: "", onLaunch }]} />);
    expect(screen.getAllByRole("heading", { name: "精选场景" })).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "事业部协作模板" })).toBeNull();
    expect(screen.getAllByRole("button", { name: /^启动部门场景/ })).toHaveLength(6);
    expect(screen.queryByRole("button", { name: "启动部门场景：通用协作" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "展开全部 8 个场景" }));
    await userEvent.click(screen.getByRole("button", { name: "启动部门场景：通用协作" }));
    expect(onLaunch).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "收起场景" }));
    expect(screen.getAllByRole("button", { name: /^启动部门场景/ })).toHaveLength(6);
    view.unmount();
  });
  it("uses existing role directories and detects an incomplete team", () => {
    expect(DEPARTMENT_SCENARIOS).toHaveLength(7);
    for (const scenario of DEPARTMENT_SCENARIOS) {
      expect(new Set(scenario.roles.map(([id]) => id)).size).toBe(scenario.roles.length);
      for (const [id] of scenario.roles) expect(existsSync(`../agents/${id}`)).toBe(true);
      expect(resolveDepartment(scenario, []).missing).toHaveLength(scenario.roles.length);
    }
  });
  it("starts PM-led initiation without adding specialists before approval", async () => {
    const scenario = DEPARTMENT_SCENARIOS[0]!;
    mocks.list.mockResolvedValue(scenario.roles.map(([name]) => ({ name }) as Agent));
    renderWithProviders(<DepartmentScenarios />);
    const button = screen.getByRole("button", { name: `启动部门场景：${scenario.title}` });
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.getByRole("button", { name: `启动部门场景：${DEPARTMENT_SCENARIOS[2]!.title}` })).toBeEnabled();
    await userEvent.click(button);
    expect(mocks.preset).toHaveBeenCalledWith(expect.objectContaining({ collaboratorIds: [], mode: "chat" }));
    const prompt = new URLSearchParams(mocks.navigate.mock.calls.at(-1)![0].split("?")[1]).get("prompt")!;
    expect(prompt).toMatch(/^\/project run /);
    expect(prompt).toContain(scenario.flow);
    expect(prompt).toContain("审批弹窗");
    expect(prompt).toContain("从 HUB 匹配");
  });
});
