/**
 * 宠物与宿主容器角落的对齐工具。
 *
 * 对齐不再依赖写死的 `right/bottom` 像素（宿主尺寸、Sprite 内部透明边距、
 * 尺寸档位任何一项变化都会导致需要重新肉眼调参），而是：
 *   1. 声明式指定「贴哪个角」+「外偏移 gap」；
 *   2. 通过 `contentBox`（图片内可见内容盒 / 透明边距）把对齐基准从
 *      "原始图片盒" 提升到 "可见像素边缘"。
 * 这样插件一键生成宠物时，只要输出 sprite 图 + `contentBox` 元数据 +
 * `anchor` 声明，渲染层即可自动吸附宿主角落，无需手工调像素。
 */

/** 宿主容器的四个角落。 */
export type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right";

/** 图片内可见内容盒：原始图片盒四边向内的透明边距（px）。 */
export interface ContentBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/**
 * 宠物可见边缘相对宿主角落的外偏移（px）。
 * 语义统一为"向外"：x 为正表示贴右角时向右探出、贴左角时向左探出；
 * y 为正表示贴下角时向下探出、贴上角时向上探出。
 * 与 CSS `right:-19px / bottom:-23px` 的旧写法等价换算：
 *   right:-19  →  gap.x = 19（向右探出）
 *   bottom:23  →  gap.y = -23（在底边之上）
 */
export interface CornerGap {
  x: number;
  y: number;
}

/** 声明式锚点配置。 */
export interface PetAnchorConfig {
  /** 贴宿主的哪个角。默认 "bottom-right"。 */
  corner?: Corner;
  /** 外偏移。默认 { x: 0, y: 0 }。 */
  gap?: CornerGap;
}

/** 与 DOMRect 兼容的矩形（用于纯函数，避免测试依赖 jsdom）。 */
export interface RectLike {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** 宠物原始盒尺寸（px）。 */
export interface PetBox {
  width: number;
  height: number;
}

export interface AlignResult {
  /** 宠物原始盒左上角相对宿主 padding box 左上角的水平偏移。 */
  left: number;
  /** 宠物原始盒左上角相对宿主 padding box 左上角的垂直偏移。 */
  top: number;
}

const EMPTY_CONTENT_BOX: ContentBox = { left: 0, top: 0, right: 0, bottom: 0 };

/**
 * 计算宠物原始盒的左上角位置，使其**可见内容盒**的指定角对准宿主矩形
 * 的对应角，并叠加 `gap` 外偏移。
 *
 * @param host 宿主矩形（调用方通常传 padding box，即扣除边框后的几何）。
 * @param pet  宠物原始盒尺寸（应使用 layout 尺寸，不受 transform 影响）。
 * @param config 角落 + 外偏移。
 * @param contentBox 图片内可见内容盒；缺省视为无透明边距。
 */
export function alignToCorner(
  host: RectLike,
  pet: PetBox,
  config?: PetAnchorConfig,
  contentBox?: ContentBox,
): AlignResult {
  const corner = config?.corner ?? "bottom-right";
  const gap = { x: 0, y: 0, ...config?.gap };
  const cb: ContentBox = { ...EMPTY_CONTENT_BOX, ...contentBox };

  const visibleWidth = pet.width - cb.left - cb.right;
  const visibleHeight = pet.height - cb.top - cb.bottom;

  const onRight = corner.endsWith("right");
  const onBottom = corner.startsWith("bottom");

  // 可见内容盒左上角（屏幕坐标）
  const visibleLeft = onRight
    ? host.right + gap.x - visibleWidth
    : host.left - gap.x;
  const visibleTop = onBottom
    ? host.bottom + gap.y - visibleHeight
    : host.top - gap.y;

  // 还原到原始图片盒左上角（屏幕坐标），再换算成相对宿主左上角的偏移
  return {
    left: visibleLeft - cb.left - host.left,
    top: visibleTop - cb.top - host.top,
  };
}
