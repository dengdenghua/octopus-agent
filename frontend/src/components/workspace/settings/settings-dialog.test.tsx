import { fireEvent, waitFor, screen } from "@testing-library/react";
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
    window.localStorage.removeItem("octopus_settings_dialog_size");
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

    expect(screen.getByRole("button", { name: "外观" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    const viewport = document.querySelector<HTMLElement>(
      '[data-slot="scroll-area-viewport"]',
    );
    expect(viewport).not.toBeNull();
    if (!viewport) return;
    viewport.scrollTop = 160;

    await user.click(screen.getByRole("button", { name: "MCP 服务" }));

    await waitFor(() => expect(viewport.scrollTop).toBe(0));
    expect(screen.getByRole("button", { name: "MCP 服务" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("button", { name: "外观" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("resizes one axis at a time from the keyboard handle", () => {
    renderWithProviders(
      <SettingsDialog
        open
        defaultSection="appearance"
        onOpenChange={vi.fn()}
      />,
      { locale: "zh-CN" },
    );

    const dialog = screen.getByRole("dialog", { name: "设置" });
    const handle = screen.getByRole("separator", { name: "拖动调整大小" });

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(dialog).toHaveStyle({ width: "776px", height: "560px" });

    fireEvent.keyDown(handle, { key: "ArrowDown" });
    expect(dialog).toHaveStyle({ width: "776px", height: "576px" });
    expect(window.localStorage.getItem("octopus_settings_dialog_size")).toBe(
      JSON.stringify({ w: 776, h: 576 }),
    );
  });

  it("explains observability before opening its dedicated workspace", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    renderWithProviders(
      <SettingsDialog
        open
        defaultSection="observability"
        onOpenChange={onOpenChange}
      />,
      { locale: "zh-CN" },
    );

    expect(
      screen.getByRole("heading", { name: "运行可观测性" }),
    ).toBeInTheDocument();
    expect(screen.getByText("实时活动")).toBeInTheDocument();
    expect(screen.getByText("工具与文件轨迹")).toBeInTheDocument();
    expect(screen.getByText("运行健康")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "打开可观测性工作台" }),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
