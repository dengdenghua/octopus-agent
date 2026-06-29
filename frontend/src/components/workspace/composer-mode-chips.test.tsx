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
    render(<ComposerModeChips active={["plan", "spec"]} onRemove={onRemove} />);

    expect(screen.getByTestId("composer-chip-plan")).toBeTruthy();
    expect(screen.getByTestId("composer-chip-spec")).toBeTruthy();
    expect(screen.getByText("规划")).toBeTruthy(); // plan label
    expect(screen.getByText("规格")).toBeTruthy(); // spec label

    await user.click(screen.getByTestId("composer-chip-remove-plan"));
    expect(onRemove).toHaveBeenCalledWith("plan");
  });

  it("renders nothing when no mode is active", () => {
    const { container } = render(
      <ComposerModeChips active={[]} onRemove={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("defines the three codex composer modes (project is a group mode, not here)", () => {
    expect(Object.keys(COMPOSER_MODES).sort()).toEqual(["goal", "plan", "spec"]);
  });
});
