/**
 * Desktop pet entry point.
 *
 * Historical: this directory previously hosted a Canvas-2D pet engine plus
 * Three.js GLTF/FBX 3D characters. Those have been removed in preparation
 * for a Live2D Cubism migration.
 *
 * The Electron desktop pet still lives in `pet-sidecar/` (Godot-based),
 * driven by `frontend/electron/pet-sidecar.cjs` over UDP 8765. That pipeline
 * is independent from this in-page slot and is NOT touched by this module.
 *
 * To re-enable an in-page mascot, expose a `DesktopPetMascot` component
 * here and mount it inside `ChatComposer`. The component must accept at
 * minimum: `mood: "idle" | "thinking" | "happy" | "working" | "error"`
 * and a `size: "sm" | "md" | "lg"` prop, so callers can swap engines
 * without touching the chat composer.
 *
 * Corner alignment: pass `anchor={{ corner, gap }}` (+ optional `contentBox`)
 * to make the pet self-align to the nearest positioned ancestor's corner,
 * measuring real geometry instead of hard-coded pixels. See
 * `frontend/src/lib/pet-align.ts` for the pure math.
 *
 * Live2D integration plan (target stack):
 *   - npm: `pixi-live2d-display` + `pixi.js`
 *   - assets: `live2d/<model>/<model>.model3.json` + textures
 *   - mount: <canvas/> inside a transparent DOM element, sized via `size`
 *   - mood mapping: drive Live2D motion groups
 *       idle     -> idle.motion3.json
 *       thinking -> tap_head.motion3.json (loop)
 *       happy    -> happy.motion3.json
 *       working  -> idle.motion3.json + expression F01 (focused)
 *       error    -> idle.motion3.json + expression F02 (sad)
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";
import {
  alignToCorner,
  type ContentBox,
  type Corner,
  type CornerGap,
  type PetAnchorConfig,
} from "@/lib/pet-align";

import { SpritePet, type SpritePetMood, type SpritePetSize } from "./sprite-pet";
export { createPetState, petStateFromAgentEvent, reducePetState } from "./pet-state-machine";
export type { PetAction, PetState, PetStateEvent } from "./pet-state-machine";
export type {
  AlignResult,
  ContentBox,
  Corner,
  CornerGap,
  PetAnchorConfig,
  PetBox,
  RectLike,
} from "@/lib/pet-align";
export { alignToCorner } from "@/lib/pet-align";

export type PetMood = SpritePetMood;
export type PetSize = "sm" | "md" | "lg";

export interface DesktopPetMascotProps {
  mood?: PetMood;
  size?: PetSize;
  className?: string;
  /** 声明式角落对齐：给定时自动吸附宿主（最近定位祖先）的对应角。 */
  anchor?: PetAnchorConfig;
  /** 图片内可见内容盒（透明边距）；对齐以可见像素边缘为基准。 */
  contentBox?: ContentBox;
}

export function DesktopPetMascot({
  mood = "idle",
  size = "sm",
  className,
  anchor,
  contentBox,
}: DesktopPetMascotProps) {
  if (!anchor) return <SpritePet mood={mood} size={size} className={className} contentBox={contentBox} />;
  return (
    <PetCornerAnchor anchor={anchor} contentBox={contentBox} className={className}>
      <SpritePet mood={mood} size={size} contentBox={contentBox} />
    </PetCornerAnchor>
  );
}

export { SpritePet };
export type { SpritePetMood, SpritePetSize };

/**
 * 把子元素吸附到宿主（最近定位祖先）指定角的定位容器。
 *
 * 测量宿主 padding box 与子元素原始盒（offsetWidth/Height，不受 transform
 * 影响），由 `alignToCorner` 计算宿主局部坐标，再通过 absolute left/top
 * 应用——与旧版 CSS `right/bottom` 语义等价但不再依赖写死像素。
 * 宿主/子元素尺寸变化时经 ResizeObserver 自动重算。
 */
export function PetCornerAnchor({
  anchor,
  contentBox,
  className,
  children,
}: {
  anchor?: PetAnchorConfig;
  contentBox?: ContentBox;
  className?: string;
  children: ReactNode;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left?: number; top?: number }>({});

  useLayoutEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;
    const petEl = wrapper.firstElementChild as HTMLElement | null;
    if (!petEl) return;

    // 宿主 = 最近的非 static 定位祖先（与 absolute 的 containing block 一致）
    let host: HTMLElement | null = wrapper.parentElement;
    while (host && getComputedStyle(host).position === "static") {
      host = host.parentElement;
    }
    if (!host) return;

    // contentBox 未显式传入时，从 Sprite 的 data-content-box 元数据读取
    let resolvedContentBox = contentBox;
    if (!resolvedContentBox) {
      const raw = petEl.dataset.contentBox;
      if (raw) {
        try {
          resolvedContentBox = JSON.parse(raw) as ContentBox;
        } catch {
          resolvedContentBox = undefined;
        }
      }
    }

    const recompute = () => {
      const hostRect = host.getBoundingClientRect();
      const cs = getComputedStyle(host);
      const bL = parseFloat(cs.borderLeftWidth) || 0;
      const bT = parseFloat(cs.borderTopWidth) || 0;
      const bR = parseFloat(cs.borderRightWidth) || 0;
      const bB = parseFloat(cs.borderBottomWidth) || 0;

      // 对齐基准用 padding box（与 CSS right/bottom 的 containing block 一致）
      const paddingBox = {
        left: hostRect.left + bL,
        top: hostRect.top + bT,
        right: hostRect.right - bR,
        bottom: hostRect.bottom - bB,
      };

      const corner: Corner = anchor?.corner ?? "bottom-right";
      const gap: CornerGap = { x: 0, y: 0, ...anchor?.gap };

      // 用 layout 尺寸：不受 SpritePet 的 translateY/rotate transform 影响
      const petSize = { width: petEl.offsetWidth, height: petEl.offsetHeight };
      const { left, top } = alignToCorner(
        paddingBox,
        petSize,
        { corner, gap },
        resolvedContentBox,
      );
      setPos({ left, top });
    };

    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(host);
    observer.observe(petEl);
    window.addEventListener("resize", recompute);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", recompute);
    };
    // 依赖用原始值（corner / gap.x / gap.y / contentBox 对象），刻意不用
    // anchor?.gap 整体——调用方常内联传入，对象引用每帧都变会导致重算抖动。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anchor?.corner, anchor?.gap?.x, anchor?.gap?.y, contentBox]);

  return (
    <div
      ref={wrapperRef}
      className={cn("pointer-events-none absolute z-10", className)}
      style={pos}
    >
      {children}
    </div>
  );
}

export default DesktopPetMascot;
