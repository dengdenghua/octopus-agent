import { waitFor, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { SettingsDialog } from "./settings-dialog";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    user: null,
    logout: vi.fn(),
    authStatus: null,
    isLoading: false,
    isGuest: true,
  }),
}));

describe("SettingsDialog", () => {
  beforeEach(() => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
  });

  it("returns the content viewport to the top when switching sections", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <SettingsDialog
        open
        defaultSection="appearance"
        onOpenChange={vi.fn()}
      />,
      { locale: "zh-CN" },
    );

    const viewport = document.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]',
    );
    expect(viewport).not.toBeNull();
    if (!viewport) return;
    viewport.scrollTop = 160;

    await user.click(screen.getByRole("button", { name: "MCP 服务" }));

    await waitFor(() => expect(viewport.scrollTop).toBe(0));
  });
});
