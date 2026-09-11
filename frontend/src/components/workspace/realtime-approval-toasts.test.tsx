import { describe, expect, test, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import { RealtimeApprovalPrompt } from "./realtime-approval-toasts";
import { renderWithProviders } from "@/test/harness";

const recruitment = vi.hoisted(() => ({ prepare: vi.fn() }));
vi.mock("@/core/agents/project-recruitment", () => ({ provisionProjectRoles: recruitment.prepare }));

describe("<RealtimeApprovalPrompt />", () => {
  test("HUB recruitment waits for approval and returns the loaded role before joining", async () => {
    recruitment.prepare.mockReset();
    recruitment.prepare.mockResolvedValue({ "hub:research": "loaded_research" });
    const resolveApproval = vi.fn();
    const roles = [{ source: "hub", key: "hub:research", expert_id: "research", name: "市场研究员" }];
    renderWithProviders(<RealtimeApprovalPrompt approvals={[{
      requestId: 22, method: "item/commandExecution/requestApproval",
      createdAt: "2026-09-11T00:00:00.000Z",
      params: { tool: "project_initiation", roleProvisions: roles, argsPreview: "人员方案" },
    }]} resolveApproval={resolveApproval} />, { locale: "zh-CN" });
    expect(recruitment.prepare).not.toHaveBeenCalled();
    expect(resolveApproval).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(resolveApproval).toHaveBeenCalledWith(22, true, { "hub:research": "loaded_research" }));
    expect(recruitment.prepare).toHaveBeenCalledWith(roles, expect.any(Function));
  });
  test("opens a staffing dialog and waits for the user's decision", () => {
    const resolveApproval = vi.fn();
    renderWithProviders(<RealtimeApprovalPrompt approvals={[{
      requestId: 21, method: "item/commandExecution/requestApproval",
      createdAt: "2026-09-11T00:00:00.000Z",
      params: { tool: "project_initiation", argsPreview: "立项方案",
        staffingReview: [{ name: "研究员", role: "市场分析", source: "hub", responsibilities: "分析市场证据", phases: [2] }],
      },
    }]} resolveApproval={resolveApproval} />, { locale: "zh-CN" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("从 HUB 添加")).toBeInTheDocument();
    expect(screen.getByText("分析市场证据")).toBeInTheDocument();
    expect(resolveApproval).not.toHaveBeenCalled();
  });
  test("shows staffing approval as a readable proposal rather than a shell command", () => {
    renderWithProviders(
      <RealtimeApprovalPrompt approvals={[{
        requestId: 20, method: "item/commandExecution/requestApproval",
        createdAt: "2026-09-11T00:00:00.000Z",
        params: { tool: "project_initiation", argsPreview: "Budget and staffing proposal" },
      }]} resolveApproval={vi.fn()} />,
    );
    expect(screen.getByRole("region", { name: "Project proposal and staffing · Requires approval" })).toBeInTheDocument();
    expect(screen.getByText("Budget and staffing proposal")).not.toHaveClass("truncate");
  });
  test("shows pending approvals with approve and reject actions", () => {
    const resolveApproval = vi.fn();

    renderWithProviders(
      <RealtimeApprovalPrompt
        approvals={[
          {
            requestId: 7,
            method: "item/commandExecution/requestApproval",
            createdAt: "2026-05-09T00:00:00.000Z",
            params: {
              tool: "write_text_file",
              argsPreview: "plan.md",
              detail: "write_text_file wants to execute",
            },
          },
        ]}
        resolveApproval={resolveApproval}
      />,
    );

    expect(
      screen.getByRole("region", {
        name: "Write file · Requires approval",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("plan.md")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(resolveApproval).toHaveBeenNthCalledWith(1, 7, true);
    expect(resolveApproval).toHaveBeenNthCalledWith(2, 7, false);
  });

  test("uses localized intent labels instead of raw tool identifiers", () => {
    renderWithProviders(
      <RealtimeApprovalPrompt
        approvals={[
          {
            requestId: 8,
            method: "item/commandExecution/requestApproval",
            createdAt: "2026-05-09T00:00:00.000Z",
            params: {
              tool: "exec_shell",
              argsPreview: "pnpm test",
            },
          },
        ]}
        resolveApproval={vi.fn()}
      />,
      { locale: "zh-CN" },
    );

    expect(
      screen.getByRole("region", {
        name: "运行命令 · 需要审批",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("pnpm test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "批准" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "拒绝" })).toBeInTheDocument();
  });

  test("extracts the command from a Python-style args preview", () => {
    renderWithProviders(
      <RealtimeApprovalPrompt
        approvals={[
          {
            requestId: 10,
            method: "item/commandExecution/requestApproval",
            createdAt: "2026-05-09T00:00:00.000Z",
            params: {
              tool: "exec_shell",
              argsPreview: "{'command': 'pwd'}",
            },
          },
        ]}
        resolveApproval={vi.fn()}
      />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("pwd")).toBeInTheDocument();
    expect(screen.queryByText("{'command': 'pwd'}")).not.toBeInTheDocument();
  });

  test("renders nothing visible", () => {
    const { container } = renderWithProviders(
      <RealtimeApprovalPrompt approvals={[]} resolveApproval={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test("removes the prompt when the server withdraws its approval", () => {
    const resolveApproval = vi.fn();
    const approval = {
      requestId: 9,
      method: "item/commandExecution/requestApproval",
      createdAt: "2026-05-09T00:00:00.000Z",
      params: { tool: "exec_shell", argsPreview: "pnpm test" },
    };
    const { rerender } = renderWithProviders(
      <RealtimeApprovalPrompt
        approvals={[approval]}
        resolveApproval={resolveApproval}
      />,
    );
    expect(screen.getByText("pnpm test")).toBeInTheDocument();

    rerender(
      <RealtimeApprovalPrompt
        approvals={[]}
        resolveApproval={resolveApproval}
      />,
    );

    expect(screen.queryByText("pnpm test")).not.toBeInTheDocument();
  });
});
