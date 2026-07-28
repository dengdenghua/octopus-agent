import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import SubscriptionSettingsPage from "./subscription-settings-page";

const subscriptionMocks = vi.hoisted(() => ({
  subscription: null as null | Record<string, unknown>,
  cancel: vi.fn(),
  refetchSubscription: vi.fn(),
  refetchLink: vi.fn(),
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    user: { user_id: "123", username: "123" },
  }),
}));

vi.mock("@/core/account", () => ({
  useSubscription: () => ({
    data: subscriptionMocks.subscription,
    isLoading: false,
    isError: false,
    refetch: subscriptionMocks.refetchSubscription,
  }),
  useCancelSubscription: () => ({
    mutate: subscriptionMocks.cancel,
    isPending: false,
  }),
  useProfile: () => ({ data: undefined }),
}));

vi.mock("@/core/oct/hooks", () => ({
  useOctLink: () => ({
    data: null,
    isLoading: false,
    isError: true,
    refetch: subscriptionMocks.refetchLink,
  }),
  useOctGoods: () => ({
    data: [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useCreateOrder: () => ({ mutateAsync: vi.fn() }),
}));

vi.mock("@/components/workspace/pay-order-dialog", () => ({
  PayOrderDialog: () => null,
}));

describe("SubscriptionSettingsPage", () => {
  beforeEach(() => {
    subscriptionMocks.subscription = null;
    vi.clearAllMocks();
  });

  it("turns a missing billing link into an explained, recoverable state", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SubscriptionSettingsPage />, { locale: "zh-CN" });

    expect(screen.getByText("套餐暂时不可用")).toBeInTheDocument();
    expect(screen.getByText(/计费服务尚未连接/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重新连接套餐服务" }));
    expect(subscriptionMocks.refetchLink).toHaveBeenCalledOnce();
  });

  it("requires confirmation before cancelling a paid subscription", async () => {
    const user = userEvent.setup();
    subscriptionMocks.subscription = {
      tier: "pro",
      auto_renew: true,
    };
    renderWithProviders(<SubscriptionSettingsPage />, { locale: "zh-CN" });

    await user.click(screen.getByRole("button", { name: "取消" }));
    expect(subscriptionMocks.cancel).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "取消订阅？" });
    expect(dialog).toHaveTextContent("当前权益会保留到已付费周期结束");
    await user.click(screen.getByRole("button", { name: "取消订阅" }));
    expect(subscriptionMocks.cancel).toHaveBeenCalledOnce();
  });
});
