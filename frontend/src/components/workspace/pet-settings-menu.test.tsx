import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { PetSettingsMenu } from "./pet-settings-menu";
import { getPetSettings } from "@/core/pet/pet-settings";

const KEY = "octopus.pet.settings";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  window.localStorage.clear();
});

function openMenu() {
  const trigger = screen.getByRole("button", { name: "宠物设置" });
  fireEvent.pointerDown(trigger, { button: 0 });
  fireEvent.click(trigger);
}

describe("PetSettingsMenu", () => {
  it("header 渲染宠物设置入口", () => {
    render(<PetSettingsMenu />);
    expect(
      screen.getByRole("button", { name: "宠物设置" }),
    ).toBeInTheDocument();
  });

  it("打开面板后展示「显示宠物」开关，默认开启", async () => {
    render(<PetSettingsMenu />);
    openMenu();
    const toggle = await screen.findByRole("switch", { name: "显示宠物" });
    expect(toggle).toHaveAttribute("data-state", "checked");
  });

  it("关闭开关后持久化 visible: false，并同步到 store", async () => {
    render(<PetSettingsMenu />);
    openMenu();
    const toggle = await screen.findByRole("switch", { name: "显示宠物" });
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(getPetSettings()).toEqual({ visible: false });
    });
    expect(window.localStorage.getItem(KEY)).toBe(
      JSON.stringify({ visible: false }),
    );
  });

  it("再次打开可重新开启宠物", async () => {
    window.localStorage.setItem(KEY, JSON.stringify({ visible: false }));
    render(<PetSettingsMenu />);
    openMenu();
    const toggle = await screen.findByRole("switch", { name: "显示宠物" });
    expect(toggle).toHaveAttribute("data-state", "unchecked");
    fireEvent.click(toggle);

    await waitFor(() => {
      expect(getPetSettings()).toEqual({ visible: true });
    });
  });
});
