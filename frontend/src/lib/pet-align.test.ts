import { describe, expect, it } from "vitest";

import { alignToCorner, type ContentBox, type PetAnchorConfig } from "./pet-align";

/** 宿主矩形：left=100, top=50, 宽 300, 高 200 → right=400, bottom=250 */
const HOST = { left: 100, top: 50, right: 400, bottom: 250 };
/** 宠物原始盒：宽 60, 高 40 */
const PET = { width: 60, height: 40 };

describe("alignToCorner", () => {
  it("默认贴 bottom-right，gap/contentBox 为 0：可见右下角与宿主右下角重合", () => {
    const r = alignToCorner(HOST, PET);
    expect(r).toEqual({ left: 400 - 60 - 100, top: 250 - 40 - 50 });
    // 可见右下角 == 宿主右下角
    expect(HOST.left + r.left + PET.width).toBe(HOST.right);
    expect(HOST.top + r.top + PET.height).toBe(HOST.bottom);
  });

  it("bottom-right + gap{x:19, y:-23}：右探出 19px，底边在宿主底边之上 23px", () => {
    const config: PetAnchorConfig = { corner: "bottom-right", gap: { x: 19, y: -23 } };
    const r = alignToCorner(HOST, PET, config);
    expect(HOST.left + r.left + PET.width).toBe(HOST.right + 19);
    expect(HOST.top + r.top + PET.height).toBe(HOST.bottom - 23);
  });

  it("top-left：可见左上角与宿主左上角重合", () => {
    const r = alignToCorner(HOST, PET, { corner: "top-left" });
    expect(r).toEqual({ left: 0, top: 0 });
    expect(HOST.left + r.left).toBe(HOST.left);
    expect(HOST.top + r.top).toBe(HOST.top);
  });

  it("top-right：可见右上角与宿主右上角重合", () => {
    const r = alignToCorner(HOST, PET, { corner: "top-right" });
    expect(HOST.left + r.left + PET.width).toBe(HOST.right);
    expect(HOST.top + r.top).toBe(HOST.top);
  });

  it("bottom-left：可见左下角与宿主左下角重合", () => {
    const r = alignToCorner(HOST, PET, { corner: "bottom-left" });
    expect(HOST.left + r.left).toBe(HOST.left);
    expect(HOST.top + r.top + PET.height).toBe(HOST.bottom);
  });

  it("top-right + gap{x:-10, y:8}：向左探出 10px，向上探出 8px", () => {
    const config: PetAnchorConfig = { corner: "top-right", gap: { x: -10, y: 8 } };
    const r = alignToCorner(HOST, PET, config);
    expect(HOST.left + r.left + PET.width).toBe(HOST.right - 10);
    expect(HOST.top + r.top).toBe(HOST.top - 8);
  });

  it("contentBox 参与：对齐基准是可见像素边缘而非原始图片盒", () => {
    const cb: ContentBox = { left: 2, top: 3, right: 4, bottom: 5 };
    const r = alignToCorner(HOST, PET, { corner: "bottom-right" }, cb);
    // 可见盒 = 原始盒向内收 2/3/4/5 → 可见宽 54，可见高 32
    // 可见右下角 = 宿主右下角
    const visibleLeft = HOST.left + r.left + cb.left;
    const visibleTop = HOST.top + r.top + cb.top;
    expect(visibleLeft + PET.width - cb.left - cb.right).toBe(HOST.right);
    expect(visibleTop + PET.height - cb.top - cb.bottom).toBe(HOST.bottom);
  });

  it("contentBox 与 gap 组合：先按可见盒吸附角落，再叠加外偏移", () => {
    const cb: ContentBox = { left: 2, top: 3, right: 4, bottom: 5 };
    const config: PetAnchorConfig = { corner: "bottom-right", gap: { x: 7, y: -9 } };
    const r = alignToCorner(HOST, PET, config, cb);
    const visibleRight = HOST.left + r.left + PET.width - cb.right;
    const visibleBottom = HOST.top + r.top + PET.height - cb.bottom;
    expect(visibleRight).toBe(HOST.right + 7);
    expect(visibleBottom).toBe(HOST.bottom - 9);
  });

  it("gap 缺省为 0，contentBox 缺省为全 0", () => {
    const r = alignToCorner(HOST, PET, { corner: "bottom-left" }, undefined);
    expect(r).toEqual({ left: 0, top: 250 - 40 - 50 });
  });
});
