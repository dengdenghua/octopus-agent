import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/harness";

import { ChatsDrawer } from "./chats-drawer";

vi.mock("@/core/threads/hooks", () => ({
  useThreads: () => ({ data: [] }),
  useDeleteThread: () => ({ isPending: false, mutate: vi.fn() }),
  useRenameThread: () => ({ isPending: false, mutate: vi.fn() }),
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

  it("keeps primary workspace destinations reachable on narrow screens", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    renderWithProviders(<ChatsDrawer open onOpenChange={onOpenChange} />, {
      locale: "zh-CN",
    });

    expect(screen.getByRole("link", { name: "Hub" })).toHaveAttribute(
      "href",
      "/workspace/agents?surface=chat",
    );
    expect(screen.getByRole("link", { name: "自动化" })).toHaveAttribute(
      "href",
      "/workspace/intelligence?surface=chat",
    );
    expect(screen.getByRole("link", { name: "自进化" })).toHaveAttribute(
      "href",
      "/workspace/evolution?surface=chat",
    );
    expect(screen.getByRole("link", { name: "本地数据库" })).toHaveAttribute(
      "href",
      "/workspace/storage?surface=company&library=docs",
    );

    await user.click(screen.getByRole("link", { name: "本地数据库" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
