import {
  useCallback,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type PointerEvent,
} from "react";

import { cn } from "@/lib/utils";

type GlassMaterial = "thin" | "card" | "dock" | "sheet" | "input";

interface LiquidGlassProps extends HTMLAttributes<HTMLDivElement> {
  material?: GlassMaterial;
  interactive?: boolean;
  blur?: number;
  chroma?: number;
  depth?: number;
  displacement?: number;
  noise?: number;
}

const materialClass: Record<GlassMaterial, string> = {
  thin: "octo-liquid-glass--thin",
  card: "octo-liquid-glass--card",
  dock: "octo-liquid-glass--dock",
  sheet: "octo-liquid-glass--sheet",
  input: "octo-liquid-glass--input",
};

export function LiquidGlass({
  material = "card",
  interactive = false,
  blur,
  chroma,
  depth,
  displacement,
  noise,
  children,
  className,
  style,
  onPointerMove,
  onPointerLeave,
  ...props
}: LiquidGlassProps) {
  const [spot, setSpot] = useState({ x: 50, y: 28 });
  const offsetX = ((spot.x - 50) / 50) * (displacement ?? 1.5);
  const offsetY = ((spot.y - 50) / 50) * (displacement ?? 1.5);

  const updateSpot = useCallback((event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    setSpot({
      x: ((event.clientX - rect.left) / rect.width) * 100,
      y: ((event.clientY - rect.top) / rect.height) * 100,
    });
  }, []);

  return (
    <div
      {...props}
      onPointerMove={(event) => {
        if (interactive) updateSpot(event);
        onPointerMove?.(event);
      }}
      onPointerLeave={(event) => {
        if (interactive) setSpot({ x: 50, y: 28 });
        onPointerLeave?.(event);
      }}
      className={cn(
        "octo-liquid-glass",
        materialClass[material],
        interactive && "octo-liquid-glass--interactive",
        className,
      )}
      style={
        {
          "--glass-x": `${spot.x}%`,
          "--glass-y": `${spot.y}%`,
          "--glass-shift-x": `${offsetX}px`,
          "--glass-shift-y": `${offsetY}px`,
          ...(blur != null ? { "--glass-blur": `${blur}px` } : {}),
          ...(chroma != null ? { "--glass-saturate": chroma } : {}),
          ...(depth != null ? { "--glass-depth": depth } : {}),
          ...(displacement != null
            ? { "--glass-displacement": `${displacement}px` }
            : {}),
          ...(noise != null ? { "--glass-noise": noise } : {}),
          ...style,
        } as CSSProperties
      }
    >
      <span aria-hidden className="octo-liquid-glass__lens" />
      {children}
    </div>
  );
}

export const liquidGlassClass = (
  material: GlassMaterial = "card",
  interactive = false,
) =>
  cn(
    "octo-liquid-glass",
    materialClass[material],
    interactive && "octo-liquid-glass--interactive",
  );
