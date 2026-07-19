import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/harness";

import { ChatsDrawer } from "./chats-drawer";

vi.mock("@/core/threads/hooks", () => ({
  useThreads: () => ({ data: [] }),
  useDeleteThread: () => ({ isPending: false, mutate: vi.fn() }),
}));

describe("ChatsDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps settings reachable from the narrow-screen navigation", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const openSettings = vi.fn();
    window.addEventListener("octopus:open-settings", openSettings);

    renderWithProviders(<ChatsDrawer open onOpenChange={onOpenChange} />, {
      locale: "zh-CN",
    });

    await user.click(screen.getByRole("button", { name: "设置" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    await waitFor(() => expect(openSettings).toHaveBeenCalledTimes(1));
    window.removeEventListener("octopus:open-settings", openSettings);
  });
});
