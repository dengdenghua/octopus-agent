import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import EvolutionPage from "./page";

vi.mock("@/components/workspace/evolution-dashboard", () => ({
  default: () => <div>dashboard-stub</div>,
}));

vi.mock("@/components/workspace/evolution-control-panel", () => ({
  EvolutionControlPanel: () => <div>control-panel-stub</div>,
}));

vi.mock("@/components/workspace/settings/evolution-settings-page", () => ({
  default: () => <div>settings-stub</div>,
}));

vi.mock("@/components/workspace/workspace-container", () => ({
  WorkspaceContainer: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  WorkspaceBody: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));

describe("EvolutionPage", () => {
  it("uses localized page actions and exposes monitor expansion state", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EvolutionPage />, {
      locale: "en-US",
      initialRoute: "/workspace/evolution",
    });

    expect(
      screen.getByRole("link", { name: "Reflection rules" }),
    ).toHaveAttribute("href", "/workspace/reflex");

    const toggle = screen.getByRole("button", {
      name: "Show runtime monitor",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute(
      "aria-controls",
      "evolution-runtime-monitor",
    );

    await user.click(toggle);
    expect(
      screen.getByRole("button", { name: "Hide runtime monitor" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("heading", { name: "Show runtime monitor", level: 2 }),
    ).toBeInTheDocument();
    expect(screen.getByText("control-panel-stub")).toBeInTheDocument();
  });
});
