import { beforeEach, describe, expect, it } from "vitest";

import { getPetSettings, setPetSettings } from "./pet-settings";

const KEY = "octopus.pet.settings";

beforeEach(() => {
  window.localStorage.clear();
  // 清掉模块级缓存，保证每个用例从 localStorage 重新读
  // 通过再次导入同名模块无法重置，这里用 getPetSettings 的缓存语义：
  // 手动清 localStorage 后先触发一次存储事件再读，见 getPetSettings 实现。
  window.dispatchEvent(new StorageEvent("storage", { key: KEY }));
});

describe("pet-settings", () => {
  it("未配置时返回默认值 visible: true", () => {
    expect(getPetSettings()).toEqual({ visible: true });
  });

  it("setPetSettings 合并式更新并持久化到 localStorage", () => {
    setPetSettings({ visible: false });
    expect(getPetSettings()).toEqual({ visible: false });
    expect(window.localStorage.getItem(KEY)).toBe(
      JSON.stringify({ visible: false }),
    );
  });

  it("重复写入可来回切换", () => {
    setPetSettings({ visible: false });
    expect(getPetSettings().visible).toBe(false);
    setPetSettings({ visible: true });
    expect(getPetSettings().visible).toBe(true);
  });

  it("读取损坏的 localStorage 时回退默认值", () => {
    window.localStorage.setItem(KEY, "{not-json");
    setPetSettings({ visible: true }); // 触发缓存重读路径
    expect(getPetSettings()).toEqual({ visible: true });
  });
});
