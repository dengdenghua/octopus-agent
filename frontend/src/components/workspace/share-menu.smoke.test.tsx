import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      share: {
        share: "分享",
        saveImage: "存为图片",
        copyImage: "复制图片",
        imageSaved: "",
        imageCopied: "",
        imageFailed: "",
        exportReplay: "导出可回放 HTML",
      },
    },
    locale: "zh",
    setLocale: () => Promise.resolve(),
  }),
}));

// Keep the canvas/clipboard layer out of jsdom — these tests only exercise
// the menu structure + the export wiring.
vi.mock("@/core/sharing/share-image", () => ({
  buildTaskShareImage: vi.fn(),
  canCopyImageToClipboard: () => false,
  copyPngToClipboard: vi.fn(),
  downloadPng: vi.fn(),
}));

import { ShareMenu } from "./share-menu";

describe("ShareMenu · replay export", () => {
  it("shows the export item and fires onExportReplay when provided", async () => {
    const onExportReplay = vi.fn();
    const user = userEvent.setup();
    render(<ShareMenu title="Run" onExportReplay={onExportReplay} />);

    await user.click(screen.getByRole("button", { name: "分享" }));
    const item = await screen.findByText("导出可回放 HTML");
    await user.click(item);

    expect(onExportReplay).toHaveBeenCalledTimes(1);
  });

  it("hides the export item when onExportReplay is omitted", async () => {
    const user = userEvent.setup();
    render(<ShareMenu title="Run" />);

    await user.click(screen.getByRole("button", { name: "分享" }));
    await screen.findByText("存为图片"); // menu is open

    expect(screen.queryByText("导出可回放 HTML")).not.toBeInTheDocument();
  });
});
