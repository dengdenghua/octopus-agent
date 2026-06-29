import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: {}, locale: "zh", setLocale: () => Promise.resolve() }),
}));

import { COMPOSER_MODES, ComposerModeChips } from "./composer-mode-chips";

describe("ComposerModeChips", () => {
  it("renders a deletable chip per active mode", async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();
    render(
      <ComposerModeChips active={["project", "plan"]} onRemove={onRemove} />,
    );

    expect(screen.getByTestId("composer-chip-project")).toBeTruthy();
    expect(screen.getByTestId("composer-chip-plan")).toBeTruthy();
    expect(screen.getByText("项目模式")).toBeTruthy(); // MS/project label
    expect(screen.getByText("规划")).toBeTruthy();

    await user.click(screen.getByTestId("composer-chip-remove-project"));
    expect(onRemove).toHaveBeenCalledWith("project");
  });

  it("renders nothing when no mode is active", () => {
    const { container } = render(
      <ComposerModeChips active={[]} onRemove={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("defines all four modes with the right MS flag", () => {
    expect(Object.keys(COMPOSER_MODES).sort()).toEqual(
      ["goal", "plan", "project", "spec"],
    );
    // MS / project mode is the flag icon (the user's "小旗帜").
    expect(COMPOSER_MODES.project.icon.displayName ?? COMPOSER_MODES.project.icon.name)
      .toMatch(/Flag/);
  });
});
