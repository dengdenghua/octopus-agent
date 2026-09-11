import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  ExecutionEngineBadge,
  ExecutionEnginePicker,
} from "./execution-engine-picker";

it("allows selecting Codex to configure its model when the current model is incompatible", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWithProviders(
    <ExecutionEnginePicker
      value="opencode"
      onChange={onChange}
      codexAvailable={false}
      unavailableReason="model_incompatible"
      opencodeAvailable
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "Execution engine: OpenCode" }),
  );
  const codex = screen.getByRole("menuitem", {
    name: /Codex.*Select this engine/,
  });
  expect(codex).not.toHaveAttribute("aria-disabled", "true");
  await user.click(codex);
  expect(onChange).toHaveBeenCalledExactlyOnceWith("codex");
});

it("shows a selected unavailable OpenCode reason and keeps alternate engines reachable", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWithProviders(
    <ExecutionEnginePicker
      value="opencode"
      onChange={onChange}
      codexAvailable
      opencodeAvailable={false}
      opencodeUnavailableReason="OpenCode is offline"
    />,
  );
  const trigger = screen.getByRole("button", {
    name: "Execution engine: OpenCode",
  });
  expect(trigger).toHaveAttribute("title", "OpenCode is offline");
  expect(
    trigger.querySelector('[data-testid="opencode-logo"]'),
  ).toBeInTheDocument();
  expect(trigger).not.toBeDisabled();
  await user.click(trigger);
  expect(
    screen.getByRole("menuitem", { name: /OpenCode.*OpenCode is offline/ }),
  ).toHaveAttribute("aria-disabled", "true");
  await user.click(
    screen.getByRole("menuitem", { name: /Codex.*Codex identity/ }),
  );
  expect(onChange).toHaveBeenCalledWith("codex");
});

it("offers two engines and Auto, without creating new native selections", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWithProviders(
    <ExecutionEnginePicker
      value="auto"
      resolvedEngine="opencode"
      onChange={onChange}
      codexAvailable={false}
      opencodeAvailable
      unavailableReason="account_required"
    />,
  );
  await user.click(
    screen.getByRole("button", { name: "Execution engine: Auto" }),
  );
  expect(screen.getByTestId("execution-engine-trigger")).toHaveAttribute(
    "title",
    "Execution engine: Auto · OpenCode",
  );
  expect(screen.getByTestId("execution-engine-trigger")).toHaveTextContent("");
  expect(
    screen.getByRole("menuitem", { name: /Codex.*Connect a Codex account/ }),
  ).toHaveAttribute("aria-disabled", "true");
  expect(screen.getAllByRole("menuitem")).toHaveLength(3);
  expect(screen.queryByRole("menuitem", { name: /Echo/ })).toBeNull();
  await user.click(
    screen.getByRole("menuitem", { name: /OpenCode.*OpenCode identity/ }),
  );
  expect(onChange).toHaveBeenCalledExactlyOnceWith("opencode");
});

it("preserves a saved native setting until the user chooses another engine", async () => {
  const user = userEvent.setup();
  const onChange = vi.fn();
  renderWithProviders(
    <ExecutionEnginePicker
      value="octopus"
      onChange={onChange}
      codexAvailable
      opencodeAvailable
    />,
  );
  await user.click(
    screen.getByRole("button", {
      name: "Execution engine: Legacy native mode",
    }),
  );
  expect(
    screen.getByText(/This session retains a legacy native setting/),
  ).toBeVisible();
  expect(onChange).not.toHaveBeenCalled();
  await user.click(
    screen.getByRole("menuitem", { name: /OpenCode.*OpenCode identity/ }),
  );
  expect(onChange).toHaveBeenCalledExactlyOnceWith("opencode");
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
    screen.getByRole("menuitem", { name: /Codex.*Codex identity/ }),
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
  expect(
    screen
      .getByRole("button", { name: "Execution engine: Codex" })
      .querySelector('[data-testid="codex-logo"]'),
  ).toBeInTheDocument();
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
