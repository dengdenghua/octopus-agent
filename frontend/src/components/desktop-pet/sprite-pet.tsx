import { useEffect, useMemo, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import type { ContentBox } from "@/lib/pet-align";

export type SpritePetMood =
  | "idle"
  | "thinking"
  | "working"
  | "waiting"
  | "success"
  | "error"
  | "curious"
  | "concerned"
  | "happy"
  | "tired";

export type SpritePetSize = "sm" | "md" | "lg";

export type SpritePetProps = {
  mood?: SpritePetMood;
  size?: SpritePetSize;
  className?: string;
  spriteSheet?: string;
  frameCount?: number;
  frameWidth?: number;
  frameHeight?: number;
  rowCount?: number;
  singleFrame?: boolean;
  /** 图片内可见内容盒（透明边距）。作为 Sprite 元数据随 DOM 暴露
   * （data-content-box），角落对齐组件可自动读取，插件生成的
   * Sprite 配置也能直接携带。 */
  contentBox?: ContentBox;
  onComplete?: () => void;
};

type MoodConfig = {
  row: number;
  frameDuration: number;
  loop: boolean;
  fallback: SpritePetMood;
};

const MOODS: Record<SpritePetMood, MoodConfig> = {
  idle: { row: 0, frameDuration: 180, loop: true, fallback: "idle" },
  thinking: { row: 1, frameDuration: 240, loop: true, fallback: "thinking" },
  working: { row: 2, frameDuration: 130, loop: true, fallback: "working" },
  waiting: { row: 3, frameDuration: 220, loop: true, fallback: "waiting" },
  success: { row: 4, frameDuration: 100, loop: false, fallback: "idle" },
  error: { row: 5, frameDuration: 180, loop: false, fallback: "idle" },
  curious: { row: 6, frameDuration: 160, loop: false, fallback: "idle" },
  concerned: { row: 8, frameDuration: 180, loop: false, fallback: "idle" },
  happy: { row: 4, frameDuration: 100, loop: false, fallback: "idle" },
  tired: { row: 7, frameDuration: 280, loop: true, fallback: "tired" },
};

const SIZE_SCALE: Record<SpritePetSize, number> = { sm: 0.5, md: 0.75, lg: 1 };

export function SpritePet({
  mood = "idle",
  size = "sm",
  className,
  spriteSheet = "/images/octopus-pet.png",
  frameCount = 8,
  frameWidth = 192,
  frameHeight = 208,
  rowCount = 9,
  singleFrame = true,
  contentBox,
  onComplete,
}: SpritePetProps) {
  const [frame, setFrame] = useState(0);
  const frameRef = useRef(0);
  const startedAtRef = useRef<number | null>(null);
  const frameConfig = MOODS[mood];
  const scale = SIZE_SCALE[size];
  const displayWidth = frameWidth * scale;
  const displayHeight = frameHeight * scale;
  const backgroundWidth = singleFrame ? displayWidth : frameWidth * frameCount * scale;
  const backgroundHeight = singleFrame ? displayHeight : frameHeight * rowCount * scale;
  // singleFrame（静态单帧）时禁用浮动/旋转：frame 循环仍由 rAF 驱动，
  // 若保留 motion，不同浏览器 rAF 时序不同会让宠物上下浮动 ±1.5px，
  // 出现"跨浏览器/跨时刻高度差几像素"的观感。
  const motion = singleFrame ? 0 : Math.sin(frame * 0.45) * 1.5;

  const style = useMemo(
    () => ({
      width: displayWidth,
      height: displayHeight,
      backgroundImage: `url("${spriteSheet}")`,
      backgroundPosition: singleFrame
        ? "center"
        : `-${frame * displayWidth}px -${frameConfig.row * displayHeight}px`,
      backgroundSize: `${backgroundWidth}px ${backgroundHeight}px`,
      transform: `translateY(${motion}px) rotate(${motion * 0.35}deg)`,
    }),
    [
      backgroundHeight,
      backgroundWidth,
      displayHeight,
      displayWidth,
      frame,
      frameConfig.row,
      motion,
      singleFrame,
      spriteSheet,
    ],
  );

  useEffect(() => {
    frameRef.current = 0;
    startedAtRef.current = null;
    setFrame(0);
  }, [mood]);

  useEffect(() => {
    let animationFrame = 0;

    const tick = (timestamp: number) => {
      if (startedAtRef.current === null) startedAtRef.current = timestamp;
      if (timestamp - startedAtRef.current >= frameConfig.frameDuration) {
        const nextFrame = frameRef.current + 1;
        if (nextFrame >= frameCount) {
          if (!frameConfig.loop) {
            setFrame(0);
            onComplete?.();
            return;
          }
          frameRef.current = 0;
        } else {
          frameRef.current = nextFrame;
        }
        setFrame(frameRef.current);
        startedAtRef.current = timestamp;
      }
      animationFrame = window.requestAnimationFrame(tick);
    };

    animationFrame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(animationFrame);
  }, [frameConfig.frameDuration, frameConfig.loop, frameCount, onComplete]);

  return (
    <span
      aria-label={`Octopus pet: ${mood}`}
      className={cn("block shrink-0 bg-no-repeat", className)}
      data-content-box={
        contentBox ? JSON.stringify(contentBox) : undefined
      }
      data-mood={mood}
      data-testid="sprite-pet"
      role="img"
      style={style}
    />
  );
}

export default SpritePet;
