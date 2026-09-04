import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollaborationDeliveryRecovery } from "./collaboration-delivery-recovery";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      coworkCollab: {
        deliveryPending: (n: number) => `${n} replies awaiting delivery`,
        deliveryWaiting: "Recovering",
        deliveryFailed: "Delivery failed",
        deliveryRetry: "Retry",
        deliveryDismiss: "Dismiss this reply",
        deliveryUnknownMember: "Collaborator",
        deliveryMonitorUnavailable: "Monitor unavailable",
      },
    },
  }),
}));

function response(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    json: async () => body,
  } as Response;
}

describe("CollaborationDeliveryRecovery", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("stays out of the execution surface when every reply is delivered", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ deliveries: [] }));
    const rendered = render(
      <CollaborationDeliveryRecovery threadId="thread-1" />,
    );

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByTestId("collaboration-delivery-recovery"),
    ).not.toBeInTheDocument();
    expect(rendered.container).toBeEmptyDOMElement();
  });

  it("shows a failed member reply and removes it after a successful retry", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        response({
          deliveries: [
            {
              delivery_id: "delivery-1",
              status: "failed",
              attempt: 2,
              max_attempts: 8,
              last_error: "disk temporarily unavailable",
              payload: {
                item: {
                  agent_display_name: "Kane",
                  text: "Verified result",
                },
              },
            },
          ],
        }),
      )
      .mockResolvedValueOnce(response({ ok: true }))
      .mockResolvedValueOnce(response({ deliveries: [] }));

    render(<CollaborationDeliveryRecovery threadId="thread-1" />);

    expect(
      await screen.findByText("1 replies awaiting delivery"),
    ).toBeInTheDocument();
    expect(screen.getByText("Kane")).toBeInTheDocument();
    expect(screen.getByText("Delivery failed")).toBeInTheDocument();
    expect(screen.getByText("Verified result")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() =>
      expect(
        screen.queryByTestId("collaboration-delivery-recovery"),
      ).not.toBeInTheDocument(),
    );
    expect(fetch).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/deliveries/delivery-1/retry"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps status-check failures recoverable without covering the workbench", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("offline"));
    render(<CollaborationDeliveryRecovery threadId="thread-1" />);

    expect(await screen.findByText("Monitor unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
