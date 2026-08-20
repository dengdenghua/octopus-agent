import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ModuleEditorDialog } from "./module-editor-dialog";
import { renderWithProviders } from "@/test/harness";
import {
  resetModuleStateCache,
  setModuleStateProvider,
} from "@/core/modules/enabled-modules";

function memoryProvider(initial: string[] = []) {
  let disabled = [...initial];
  return {
    readDisabled: () => [...disabled],
    writeDisabled: (ids: string[]) => {
      disabled = [...ids];
    },
    current: () => [...disabled],
  };
}

describe("ModuleEditorDialog", () => {
  beforeEach(() => {
    setModuleStateProvider(memoryProvider());
    resetModuleStateCache();
  });

  it("renders group headings and module cards", () => {
    renderWithProviders(
      <ModuleEditorDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("工作台核心")).toBeInTheDocument();
    expect(screen.getByText("知识与存储")).toBeInTheDocument();
    expect(screen.getByText("社区与发现")).toBeInTheDocument();
  });

  it("shows pinned modules as non-interactive with an always-on label", () => {
    renderWithProviders(
      <ModuleEditorDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    // The agent roster (navHR) is pinned — it must not be a toggle button.
    expect(screen.getByText("常驻")).toBeInTheDocument();
  });

  it("toggles a removable module off and persists it", async () => {
    const provider = memoryProvider();
    setModuleStateProvider(provider);
    resetModuleStateCache();

    renderWithProviders(
      <ModuleEditorDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const toggles = screen.getAllByRole("button", { pressed: true });
    expect(toggles.length).toBeGreaterThan(0);

    await userEvent.click(toggles[0]);
    expect(provider.current().length).toBe(1);
  });

  it("closes via the done button", async () => {
    const onOpenChange = vi.fn();
    renderWithProviders(
      <ModuleEditorDialog open onOpenChange={onOpenChange} />,
      { locale: "zh-CN" },
    );

    await userEvent.click(screen.getByRole("button", { name: "完成" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("localizes group headings", () => {
    renderWithProviders(
      <ModuleEditorDialog open onOpenChange={vi.fn()} />,
      { locale: "en-US" },
    );
    expect(screen.getByText("Knowledge & storage")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Done" }),
    ).toBeInTheDocument();
  });
});
