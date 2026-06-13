import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { PermissionIndicator } from "./permission-indicator";

function openPermissionMenu(trigger: HTMLElement) {
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
}

describe("<PermissionIndicator />", () => {
  it("renders a compact localized menu and changes the selected mode", async () => {
    const onModeChange = vi.fn();

    renderWithProviders(
      <PermissionIndicator
        mode="bypassPermissions"
        onModeChange={onModeChange}
      />,
    );

    const trigger = screen.getByTestId("permission-mode-trigger");
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveAccessibleName("Permissions: Trusted");
    expect(trigger).toHaveTextContent("Trusted");
    expect(trigger.className).toContain("bg-muted/45");
    expect(trigger.className).not.toContain("amber");

    openPermissionMenu(trigger);

    expect(
      await screen.findByTestId("permission-mode-menu"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("permission-mode-option-default"),
    ).toHaveTextContent("Confirm");
    expect(
      screen.getByTestId("permission-mode-option-acceptEdits"),
    ).toHaveTextContent("Edit files");
    expect(screen.getByText("Edit files")).toBeInTheDocument();
    expect(screen.getAllByText("Trusted").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Plan")).toBeInTheDocument();

    expect(
      screen.getByText(
        "Allow file edits automatically; still confirm other risky actions.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Edit files"));

    await waitFor(() => {
      expect(onModeChange).toHaveBeenCalledWith("acceptEdits");
    });
  });

  it("shows mode descriptions directly in the menu", async () => {
    renderWithProviders(
      <PermissionIndicator mode="plan" onModeChange={vi.fn()} />,
    );

    openPermissionMenu(
      screen.getByRole("button", { name: "Permissions: Plan" }),
    );

    const confirmItem = await screen.findByText("Confirm");
    expect(confirmItem).toBeInTheDocument();
    expect(screen.getByTestId("permission-mode-option-plan")).toHaveTextContent(
      "Plan",
    );

    expect(
      screen.getByText("Confirm before risky tool use."),
    ).toBeInTheDocument();
  });
});
