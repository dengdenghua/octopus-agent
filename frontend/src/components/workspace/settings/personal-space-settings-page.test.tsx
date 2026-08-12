import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { getLocalSettings } from "@/core/settings";
import { renderWithProviders } from "@/test/harness";

import PersonalSpaceSettingsPage from "./personal-space-settings-page";

describe("PersonalSpaceSettingsPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists the default mode and custom work rules", () => {
    renderWithProviders(<PersonalSpaceSettingsPage />, { locale: "zh-CN" });

    fireEvent.click(screen.getByRole("button", { name: "研究" }));
    fireEvent.change(screen.getByRole("textbox", { name: "自定义工作规则" }), {
      target: { value: "研究时优先使用一手来源。" },
    });

    const personal = getLocalSettings().personal_space;
    expect(personal.default_mode).toBe("research");
    expect(personal.custom_instructions).toBe("研究时优先使用一手来源。");
  });

  it("can disable remembering composer mode changes", () => {
    renderWithProviders(<PersonalSpaceSettingsPage />, { locale: "zh-CN" });

    fireEvent.click(
      screen.getByRole("switch", { name: "记住输入框中的模式选择" }),
    );

    expect(getLocalSettings().personal_space.remember_last_mode).toBe(false);
  });

  it("keeps reply style under conversation personalization", () => {
    renderWithProviders(<PersonalSpaceSettingsPage />, { locale: "zh-CN" });

    expect(
      screen.getByRole("button", { name: "reply-style-default" }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(
      screen.getByRole("button", { name: "reply-style-professional" }),
    );

    expect(getLocalSettings().context.reply_style).toBe("professional");
  });
});
