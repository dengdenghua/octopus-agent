import { describe, expect, test, vi } from "vitest";

import { RealtimeApprovalToasts } from "./realtime-approval-toasts";
import { renderWithProviders } from "@/test/harness";

const { toastDismissMock, toastMock } = vi.hoisted(() => ({
  toastDismissMock: vi.fn(),
  toastMock: Object.assign(vi.fn(), { dismiss: vi.fn() }),
}));

toastMock.dismiss = toastDismissMock;

vi.mock("sonner", () => ({
  toast: toastMock,
}));

describe("<RealtimeApprovalToasts />", () => {
  test("shows pending approvals with approve and reject actions", () => {
    const resolveApproval = vi.fn();

    renderWithProviders(
      <RealtimeApprovalToasts
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

    expect(toastMock).toHaveBeenCalledWith(
      "write_text_file",
      expect.objectContaining({
        id: "7",
        description: "plan.md",
        duration: 120_000,
        dismissible: false,
        action: expect.objectContaining({ label: "Approve" }),
        cancel: expect.objectContaining({ label: "Reject" }),
      }),
    );

    const options = toastMock.mock.calls[0]?.[1] as {
      action: { onClick: () => void };
      cancel: { onClick: () => void };
    };
    options.action.onClick();
    options.cancel.onClick();

    expect(resolveApproval).toHaveBeenNthCalledWith(1, 7, true);
    expect(resolveApproval).toHaveBeenNthCalledWith(2, 7, false);
  });

  test("renders nothing visible", () => {
    const { container } = renderWithProviders(
      <RealtimeApprovalToasts approvals={[]} resolveApproval={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  test("dismisses a toast when the server withdraws its approval", () => {
    const resolveApproval = vi.fn();
    const approval = {
      requestId: 9,
      method: "item/commandExecution/requestApproval",
      createdAt: "2026-05-09T00:00:00.000Z",
      params: { tool: "exec_shell", argsPreview: "pnpm test" },
    };
    const { rerender } = renderWithProviders(
      <RealtimeApprovalToasts
        approvals={[approval]}
        resolveApproval={resolveApproval}
      />,
    );

    rerender(
      <RealtimeApprovalToasts
        approvals={[]}
        resolveApproval={resolveApproval}
      />,
    );

    expect(toastDismissMock).toHaveBeenCalledWith("9");
  });
});
