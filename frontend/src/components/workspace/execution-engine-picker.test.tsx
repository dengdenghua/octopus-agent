import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  ExecutionEngineBadge,
  ExecutionEnginePicker,
} from "./execution-engine-picker";

it("explains unavailable Codex while keeping Auto and Octopus selectable", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWithProviders(
    <ExecutionEnginePicker
      value="auto"
      onChange={onChange}
      codexAvailable={false}
      unavailableReason="account_required"
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "Execution engine: Auto" }),
  );
  expect(
    screen.getByRole("menuitem", { name: /Codex Connect a Codex account/ }),
  ).toHaveAttribute("aria-disabled", "true");
  await user.click(
    screen.getByRole("menuitem", { name: /Octopus Use native/ }),
  );
  expect(onChange).toHaveBeenCalledExactlyOnceWith("octopus");
});

it("allows Codex for any role and freezes the choice while running", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  const { rerender } = renderWithProviders(
    <ExecutionEnginePicker value="auto" onChange={onChange} codexAvailable />,
  );
  await user.click(
    screen.getByRole("button", { name: "Execution engine: Auto" }),
  );
  await user.click(
    screen.getByRole("menuitem", { name: /Codex Run this role/ }),
  );
  expect(onChange).toHaveBeenCalledExactlyOnceWith("codex");
  rerender(
    <ExecutionEnginePicker
      value="codex"
      onChange={onChange}
      codexAvailable
      disabled
    />,
  );
  expect(
    screen.getByRole("button", { name: "Execution engine: Codex" }),
  ).toBeDisabled();
});

it("does not invent an engine receipt for legacy or malformed history", () => {
  const { container, rerender } = renderWithProviders(
    <ExecutionEngineBadge engine={undefined} />,
  );
  expect(container.querySelector("[data-execution-engine]")).toBeNull();
  rerender(<ExecutionEngineBadge engine="codex_app_server" />);
  expect(container.querySelector("[data-execution-engine]")).toBeNull();
  rerender(<ExecutionEngineBadge engine="codex" />);
  expect(screen.getByTitle("Executed by Codex")).toBeVisible();
});
