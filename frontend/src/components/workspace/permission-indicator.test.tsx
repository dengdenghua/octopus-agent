import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

    const trigger = screen.getByRole("button", {
      name: "Permissions: Trusted",
    });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent("Trusted");
    expect(trigger.className).toContain("bg-muted/45");
    expect(trigger.className).not.toContain("amber");

    openPermissionMenu(trigger);

    expect(await screen.findByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText("Edit files")).toBeInTheDocument();
    expect(screen.getAllByText("Trusted").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Plan")).toBeInTheDocument();

    expect(
      screen.queryByText(
        "Allow file edits automatically; still confirm other risky actions.",
      ),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Edit files"));

    await waitFor(() => {
      expect(onModeChange).toHaveBeenCalledWith("acceptEdits");
    });
  });

  it("shows the mode description only on hover", async () => {
    const user = userEvent.setup();

    renderWithProviders(
      <PermissionIndicator mode="plan" onModeChange={vi.fn()} />,
    );

    openPermissionMenu(
      screen.getByRole("button", { name: "Permissions: Plan" }),
    );

    const confirmItem = await screen.findByText("Confirm");
    expect(screen.queryByText("Confirm before risky tool use.")).toBeNull();

    await user.hover(confirmItem);

    expect(
      await screen.findByRole("tooltip", {
        name: "Confirm before risky tool use.",
      }),
    ).toBeInTheDocument();
  });
});
