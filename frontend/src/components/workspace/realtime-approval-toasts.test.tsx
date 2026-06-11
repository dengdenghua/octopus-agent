import { describe, expect, test, vi } from "vitest";

import { RealtimeApprovalToasts } from "./realtime-approval-toasts";
import { renderWithProviders } from "@/test/harness";

const { toastMock } = vi.hoisted(() => ({
  toastMock: vi.fn(),
}));

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
});
